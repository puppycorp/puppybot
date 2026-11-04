#!/usr/bin/env python3
"""Synthetic PBENV001 collider/metadata checks; no real scenes generated."""
import copy
import importlib.util
import struct
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('world_geometry', HERE / 'world_geometry.py')
world = importlib.util.module_from_spec(spec)
spec.loader.exec_module(world)


def scene(two_rooms=True):
    layout = {'generator': 'diverse-v1', 'layoutId': 291 if two_rooms else 290,
              'startPose': [.1, -.2, .3], 'obstacles': [[-2, .5, .25, .3]],
              'rooms': [[-4, -3, 1.5 if two_rooms else 4, 3]],
              'door': [1.5, .2, .8] if two_rooms else None}
    boxes = {'Wall.west': (-4, 0, 1.25, .06, 3, 1.25, 0),
             'Wall.east': (4, 0, 1.25, .06, 3, 1.25, 0),
             'Wall.south': (0, -3, 1.25, 4, .06, 1.25, 0),
             'Wall.north': (0, 3, 1.25, 4, .06, 1.25, 0),
             'Obstacle': (-2, .5, .3, .25, .3, .3, 0)}
    if two_rooms:
        layout['rooms'].append([1.5, -3, 4, 3])
        low, high = -.6, 1.0
        boxes['Wall.partition-a'] = (1.5, (low - 3) / 2, 1.25, .06, (low + 3) / 2, 1.25, 0)
        boxes['Wall.partition-b'] = (1.5, (high + 3) / 2, 1.25, .06, (3 - high) / 2, 1.25, 0)
    count, vertices = len(boxes), (len(boxes) + 1) * 36
    data = bytearray(256 + count * 128 + vertices * 72)
    data[:8] = b'PBENV001'; struct.pack_into('<3q', data, 8, count, vertices, vertices)
    struct.pack_into('<7d', data, 64, -4, -3, 4, 3, .1, -.2, .3)
    for index, (name, values) in enumerate(boxes.items()):
        offset = 256 + index * 128
        encoded = name.encode(); data[offset:offset + len(encoded)] = encoded
        struct.pack_into('<7d', data, offset + 48, *values)
    return layout, bytes(data)


class WorldGeometryTest(unittest.TestCase):
    def test_one_and_two_room_consistency(self):
        for two in (False, True):
            layout, data = scene(two)
            result = world.check_metadata(layout, data)
            self.assertEqual(result['colliders'], 7 if two else 5)
            self.assertEqual(result['startPose'], [.1, -.2, .3])

    def test_metadata_lies_or_changed_world_fail(self):
        layout, data = scene()
        for mutate in ('room', 'door', 'obstacle', 'start'):
            altered = copy.deepcopy(layout)
            if mutate == 'room': altered['rooms'][0][0] -= .1
            if mutate == 'door': altered['door'][1] += .1
            if mutate == 'obstacle': altered['obstacles'][0][0] += .1
            if mutate == 'start': altered['startPose'][0] += .1
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                world.check_metadata(altered, data)
        altered = bytearray(data); struct.pack_into('<d', altered, 256 + 48, -3.9)
        with self.assertRaises(ValueError): world.check_metadata(layout, bytes(altered))

    def test_malformed_shape_duplicate_names_and_nan_fail(self):
        layout, data = scene()
        with self.assertRaises(ValueError): world.check_metadata(layout, data[:-1])
        altered = bytearray(data); altered[384:432] = altered[256:304]
        with self.assertRaises(ValueError): world.check_metadata(layout, bytes(altered))
        altered = bytearray(data); struct.pack_into('<d', altered, 256 + 48, float('nan'))
        with self.assertRaises(ValueError): world.check_metadata(layout, bytes(altered))

    def test_digest_ignores_title_spawn_and_record_order(self):
        _, data = scene()
        altered = bytearray(data); altered[128:140] = b'other title\0'
        struct.pack_into('<d', altered, 96, .4)
        first, second = bytes(altered[256:384]), bytes(altered[384:512])
        altered[256:384], altered[384:512] = second, first
        self.assertEqual(world.collider_digest(data), world.collider_digest(bytes(altered)))
        struct.pack_into('<d', altered, 256 + 48, 3.9)
        self.assertNotEqual(world.collider_digest(data), world.collider_digest(bytes(altered)))

    def test_float32_projection_flags_different_doubles_as_same_shape(self):
        _, data = scene()
        altered = bytearray(data)
        struct.pack_into('<d', altered, 256 + 48, -4 + 1e-10)
        self.assertNotEqual(world.collider_digest(data), world.collider_digest(bytes(altered)))
        self.assertEqual(world.projected_physics_digest(data), world.projected_physics_digest(bytes(altered)))


if __name__ == '__main__':
    unittest.main()
