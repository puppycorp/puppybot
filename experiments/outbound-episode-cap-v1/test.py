#!/usr/bin/env python3
"""Exercise the copied actual trainer's dataset-size gate without GPU setup."""
import importlib.util
import os
import shutil
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
spec = importlib.util.spec_from_file_location('outbound_capacity_transform', HERE / 'transform.py')
transform = importlib.util.module_from_spec(spec); spec.loader.exec_module(transform)


class TrainerCapacityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='puppy-outbound-capacity-')
        cls.root = Path(cls.temp.name)
        shutil.copytree(ROOT / 'flex', cls.root / 'flex', symlinks=True)
        (cls.root / 'build').symlink_to(ROOT / 'build', target_is_directory=True)
        trainer = cls.root / 'flex/control/train.flex'
        text = trainer.read_text()
        anchor = 'vp_require(pt_data_size==32+episodes*pt_record_size,"truncated demonstration data");'
        if text.count(anchor) != 1:
            raise ValueError('unexpected trainer header anchor')
        # Exit immediately after the real mapped-header, capacity and byte-size
        # checks. This copied probe never initializes GPU or reads image rows.
        trainer.write_text(text.replace(anchor, anchor + '\n    pl_print(1,"header check passed\\n");return 0;', 1))
        dataset = cls.root / 'flex/control/dataset.flex'
        original = dataset.read_text()
        cls.binaries = {}
        for name, source in (('old', original), ('candidate', transform.transform(original))):
            dataset.write_text(source); binary = cls.root / name
            built = subprocess.run([str(ROOT / 'build/flex/control/compiler'), str(trainer), '-o', str(binary)],
                                   cwd=ROOT, capture_output=True, text=True, timeout=120)
            if built.returncode:
                raise RuntimeError(built.stdout + '\n' + built.stderr)
            cls.binaries[name] = binary

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def header(self, magic, episodes, fit, length=300):
        path = self.root / 'sparse-dataset.bin'; row = 56 if magic == b'PVDATA04' else 44
        with path.open('wb') as stream:
            stream.write(magic + struct.pack('<3q', episodes, fit, length))
            stream.truncate(32 + episodes * length * (21168 + row))
        # This is a synthetic sparse header file, never an actual aggregate.
        self.assertLess(path.stat().st_blocks * 512, 1024 * 1024)
        return path

    def invoke(self, binary, data):
        return subprocess.run([str(self.binaries[binary]), 'unused', 'unused', 'unused', str(data),
                               'unused', '0', '1', '100', '7'], cwd=ROOT,
                              capture_output=True, text=True, timeout=20)

    def test_candidate_accepts_1029_and_1030_but_original_does_not(self):
        for episodes, fit in ((1029, 933), (1030, 933)):
            with self.subTest(episodes=episodes):
                data = self.header(b'PVDATA04', episodes, fit)
                self.assertNotEqual(self.invoke('old', data).returncode, 0)
                result = self.invoke('candidate', data)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('header check passed', result.stdout)

    def test_candidate_rejects_1031_and_keeps_legacy_limit(self):
        for magic, episodes, fit in ((b'PVDATA04', 1031, 933), (b'PVDATA01', 257, 250)):
            with self.subTest(magic=magic, episodes=episodes):
                result = self.invoke('candidate', self.header(magic, episodes, fit))
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('header check passed', result.stdout)

    def test_original_1024_remains_accepted(self):
        data = self.header(b'PVDATA04', 1024, 928)
        for binary in ('old', 'candidate'):
            result = self.invoke(binary, data)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_changed_source_anchor_is_rejected(self):
        with self.assertRaises(ValueError): transform.transform('unexpected source')


if __name__ == '__main__': unittest.main()
