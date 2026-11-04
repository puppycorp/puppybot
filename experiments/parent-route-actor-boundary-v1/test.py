#!/usr/bin/env python3
"""Compile the isolated collector and verify native boundary fixtures."""
import importlib.util
import shutil
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
COMPILER = ROOT / 'build/flex/control/compiler'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


audit = load('parent_boundary_audit', HERE / 'audit.py')
transform = load('parent_boundary_transform', HERE / 'transform.py')
builder = load('parent_boundary_build', HERE / 'build.py')


class BoundaryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = tempfile.TemporaryDirectory()
        root = Path(cls.build.name)
        source = root / 'flex'
        shutil.copytree(ROOT / 'flex', source, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        chase = source / 'control/chase.flex'
        chase.write_text(transform.transform(chase.read_text()))
        shutil.copyfile(HERE / 'parent-boundary.flex', source / 'control/parent-boundary.flex')
        subprocess.run([str(COMPILER), str(source / 'control/main.flex'), '-o', str(root / 'control')],
                       cwd=ROOT, check=True, timeout=120)
        cls.probe = root / 'probe'
        shutil.copyfile(HERE / 'probe.flex', source / 'control/parent-boundary-probe.flex')
        subprocess.run([str(COMPILER), str(source / 'control/parent-boundary-probe.flex'), '-o', str(cls.probe)],
                       cwd=ROOT, check=True, timeout=120)

    @classmethod
    def tearDownClass(cls):
        cls.build.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.actor = self.root / 'actor.bin'; self.boundary = self.root / 'boundary.bin'
        subprocess.run([str(self.probe), str(self.actor), str(self.boundary)], cwd=ROOT, check=True)
        self.data = self.root / 'data.bin'; self.maps = self.root / 'map.bin'
        images = [bytearray(audit.IMAGE), bytearray(audit.IMAGE)]
        images[0][0] = 42; images[1][0] = 99
        feedback = [struct.pack('<7f', *([0] * 7)), struct.pack('<7f', *([0] * 6 + [1]))]
        labels = [struct.pack('<2f', .6, 1), struct.pack('<2f', 0, 1)]
        records = b''.join(f + label + struct.pack('<2f', 0, 1) for f, label in zip(feedback, labels))
        # Two episodes, each with two frames: only episode 0 is inspected.
        episode = b''.join(images) + records
        self.data.write_bytes(struct.pack('<8s3q', b'PVDATA01', 2, 1, 2) + episode * 2)
        m0 = bytearray(144); m1 = bytearray(144); m0[0] = m1[0] = 2; m1[1] = 1
        self.maps.write_bytes(struct.pack('<8s3q', b'PVMAP001', 2, 1, 2) + (m0 + m1) * 2)
        self.rows = [{'sequence': 3, 'step': 505, 'action': [0, 1],
                      'state': {'totalSteps': 505, 'findReturn': {'consumedIndex': 0, 'phase': 'return', 'deliveries': 0}}},
                     {'sequence': 4, 'step': 515, 'action': [.6, 1],
                      'state': {'totalSteps': 515, 'findReturn': {'consumedIndex': 0, 'phase': 'return', 'deliveries': 1}}}]

    def tearDown(self):
        self.temp.cleanup()

    def check(self):
        return audit.audit(self.data, self.maps, self.actor, self.boundary, 7820010, 0, self.rows, 2)

    def mutate(self, path, position, value):
        data = bytearray(path.read_bytes()); data[position] = value; path.write_bytes(data)

    def reset_fixture(self):
        self.tearDown()
        self.setUp()

    def test_native_records_align_with_data(self):
        self.assertEqual(self.check()['labelDifferences'], 2)

    def test_changed_actor_image_and_map_are_rejected(self):
        self.mutate(self.data, 32, 43)
        with self.assertRaisesRegex(ValueError, 'RGB'):
            self.check()
        self.reset_fixture()
        self.mutate(self.maps, 32, 1)
        with self.assertRaisesRegex(ValueError, 'map'):
            self.check()

    def test_changed_carry_action_and_teacher_are_rejected(self):
        self.rows[0]['state']['findReturn']['phase'] = 'delivered'
        with self.assertRaisesRegex(ValueError, 'carry cue'):
            self.check()
        self.reset_fixture()
        self.rows[1]['action'] = [0, 1]
        with self.assertRaisesRegex(ValueError, 'action'):
            self.check()
        self.reset_fixture()
        self.mutate(self.boundary, 40 + 24 + 144, 0)
        with self.assertRaisesRegex(ValueError, 'teacher label'):
            self.check()

    def test_truncated_and_wrong_order_are_rejected(self):
        self.actor.write_bytes(self.actor.read_bytes()[:-1])
        with self.assertRaises(ValueError):
            self.check()
        self.reset_fixture()
        self.rows[0]['sequence'] = 4
        with self.assertRaisesRegex(ValueError, 'order'):
            self.check()

    def test_binary_rebuild_and_source_tampering(self):
        old = builder.OUTPUT
        try:
            builder.OUTPUT = self.root / 'private-build'
            record = builder.build(builder.OUTPUT)
            self.assertEqual(builder.verify(builder.OUTPUT), record)
            path = builder.OUTPUT / 'flex/control/chase.flex'
            original = path.read_bytes()
            path.write_bytes(original + b'\n')
            with self.assertRaisesRegex(ValueError, 'sources changed'):
                builder.verify(builder.OUTPUT)
            path.write_bytes(original)
            binary = builder.OUTPUT / 'control'
            value = bytearray(binary.read_bytes()); value[-1] ^= 1; binary.write_bytes(value)
            with self.assertRaisesRegex(ValueError, 'binary differs'):
                builder.verify(builder.OUTPUT)
        finally:
            builder.OUTPUT = old

    def test_label_differences_only_after_delivery_are_rejected(self):
        self.rows[0]['state']['findReturn']['deliveries'] = 1
        for path, offset in ((self.data, 32 + 2 * audit.IMAGE + 28),
                             (self.boundary, 40 + 24 + audit.MAP)):
            contents = bytearray(path.read_bytes())
            contents[offset:offset + 8] = struct.pack('<2f', 0, 1)
            path.write_bytes(contents)
        with self.assertRaisesRegex(ValueError, 'first-delivery prefix'):
            audit.audit(self.data, self.maps, self.actor, self.boundary, 7820010, 0, self.rows, 1)


if __name__ == '__main__':
    unittest.main()
