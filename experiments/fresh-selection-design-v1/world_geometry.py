#!/usr/bin/env python3
"""Check diverse-layout metadata against PBENV001 collider geometry.

This read-only helper checks the generated box colliders and starting pose,
not the rendered mesh, full model ancestry or near-equivalent geometry.
"""
import hashlib
import json
import math
import struct


def finite_vector(values, length):
    if not isinstance(values, (list, tuple)) or len(values) != length:
        raise ValueError('invalid geometry vector')
    if any(type(value) not in (int, float) or not math.isfinite(value) for value in values):
        raise ValueError('nonfinite geometry value')
    return tuple(0.0 if value == 0 else float(value) for value in values)


def same(actual, expected):
    return len(actual) == len(expected) and all(
        math.isclose(a, b, rel_tol=0.0, abs_tol=1e-12) for a, b in zip(actual, expected))


def decode(blob):
    if not isinstance(blob, bytes) or len(blob) < 256 or blob[:8] != b'PBENV001':
        raise ValueError('invalid environment header')
    count, vertices, overview = struct.unpack_from('<3q', blob, 8)
    if (not 1 <= count <= 160 or not 3 <= vertices <= 1000000 or vertices % 3 or
            overview != vertices or len(blob) != 256 + 128 * count + 72 * vertices):
        raise ValueError('invalid environment size or shape')
    bounds = finite_vector(struct.unpack_from('<4d', blob, 64), 4)
    start = finite_vector(struct.unpack_from('<3d', blob, 96), 3)
    if (bounds[0] >= bounds[2] or bounds[1] >= bounds[3] or
            not bounds[0] < start[0] < bounds[2] or not bounds[1] < start[1] < bounds[3] or
            any(abs(value) > 100 for value in bounds + start)):
        raise ValueError('invalid environment bounds or start')
    records = {}
    for index in range(count):
        offset = 256 + 128 * index
        name_bytes = blob[offset:offset + 48]
        if b'\0' not in name_bytes:
            raise ValueError('unterminated collider name')
        name_bytes = name_bytes.split(b'\0', 1)[0]
        if not name_bytes or any(value < 32 or value > 126 for value in name_bytes):
            raise ValueError('invalid collider name')
        name = name_bytes.decode('ascii')
        values = finite_vector(struct.unpack_from('<7d', blob, offset + 48), 7)
        if (name in records or any(abs(value) > 100 for value in values) or
                any(value <= 0.00001 for value in values[3:6])):
            raise ValueError('duplicate or invalid collider')
        records[name] = values
    return bounds, start, records


def collider_digest(blob):
    bounds, _, records = decode(blob)
    # The simulator uses collider geometry, not these names. Ignore record
    # order, title and spawn so renaming a layout does not hide exact reuse.
    geometry = {'bounds': bounds, 'colliders': sorted(records.values())}
    return hashlib.sha256(json.dumps(geometry, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def projected_physics_digest(blob):
    """Hash a float32 projection of box geometry; a conservative overlap hint.

    The simulator passes positions and half-sizes to the physics engine as
    float32, as well as float32 sine/cosine of half-yaw. Python's math library
    and the device implementation are not independently proven bit-exact,
    so this is a diagnostic screen, not a complete physics-equivalence proof.
    Bounds/start are intentionally excluded: differing priors must not hide
    duplicate static collider shapes.
    """
    _, _, records = decode(blob)
    boxes = []
    for x, y, z, hx, hy, hz, yaw in records.values():
        boxes.append(struct.pack('<8f', x, y, z, hx, hy, hz, math.sin(yaw / 2), math.cos(yaw / 2)))
    return hashlib.sha256(b''.join(sorted(boxes))).hexdigest()


def check_metadata(layout, blob):
    if not isinstance(layout, dict):
        raise ValueError('layout metadata must be an object')
    layout_id = layout.get('layoutId')
    if type(layout_id) is not int or layout_id < 0 or layout.get('generator') != 'diverse-v1':
        raise ValueError('invalid diverse layout identity')
    rooms = layout.get('rooms')
    if not isinstance(rooms, list) or len(rooms) != 1 + layout_id % 2:
        raise ValueError('room count differs from layout')
    rooms = [finite_vector(room, 4) for room in rooms]
    obstacles = layout.get('obstacles')
    if not isinstance(obstacles, list) or len(obstacles) != 1:
        raise ValueError('expected exactly one obstacle')
    obstacle = finite_vector(obstacles[0], 4)
    bounds, start, records = decode(blob)
    if not same(start, finite_vector(layout.get('startPose'), 3)):
        raise ValueError('metadata start differs from world')
    xmin, ymin, xmax, ymax = bounds
    if not same((-xmin, -ymin), (xmax, ymax)):
        raise ValueError('diverse world bounds are not symmetric')
    expected = {
        'Wall.west': (xmin, 0, 1.25, .06, ymax, 1.25, 0),
        'Wall.east': (xmax, 0, 1.25, .06, ymax, 1.25, 0),
        'Wall.south': (0, ymin, 1.25, xmax, .06, 1.25, 0),
        'Wall.north': (0, ymax, 1.25, xmax, .06, 1.25, 0),
        'Obstacle': (obstacle[0], obstacle[1], .3, obstacle[2], obstacle[3], .3, 0),
    }
    if layout_id % 2:
        door = finite_vector(layout.get('door'), 3)
        x, y, half = door
        if half <= 0 or not ymin < y - half < y + half < ymax or not xmin < x < xmax:
            raise ValueError('invalid partition doorway')
        low, high = y - half, y + half
        expected['Wall.partition-a'] = (x, (low - ymax) / 2, 1.25, .06, (low + ymax) / 2, 1.25, 0)
        expected['Wall.partition-b'] = (x, (high + ymax) / 2, 1.25, .06, (ymax - high) / 2, 1.25, 0)
        expected_rooms = [(xmin, ymin, x, ymax), (x, ymin, xmax, ymax)]
    else:
        if layout.get('door') is not None:
            raise ValueError('single room must not have a partition')
        expected_rooms = [(xmin, ymin, xmax, ymax)]
    if len(rooms) != len(expected_rooms) or any(not same(a, b) for a, b in zip(rooms, expected_rooms)):
        raise ValueError('metadata rooms differ from world')
    if set(records) != set(expected) or any(not same(records[name], values) for name, values in expected.items()):
        raise ValueError('metadata walls or obstacle differ from world colliders')
    return {'colliderGeometrySHA256': collider_digest(blob),
            'projectedPhysicsSHA256': projected_physics_digest(blob),
            'colliders': len(records), 'startPose': list(start),
            'scope': ('metadata versus PBENV001 static collider boxes and spawn; f32 projection is only an '
                      'overlap hint; rendered mesh and complete physics equivalence not checked')}
