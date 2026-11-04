#!/usr/bin/env python3
"""Small CPU checks of factorial training-layout scene preparation."""
import importlib.util
import struct
import tempfile
import unittest
from pathlib import Path

path = Path(__file__).resolve().parents[2] / 'datasets/visual-control/chase-v1/levels/prepare-route-factorial.py'
spec = importlib.util.spec_from_file_location('factorial', path)
factorial = importlib.util.module_from_spec(spec); spec.loader.exec_module(factorial)


class FactorialTest(unittest.TestCase):
    def test_spawn_only(self):
        source = (factorial.SCENES / '15/1/environment.bin').read_bytes()
        for heading in factorial.HEADINGS:
            output = factorial.environment(source, heading)
            self.assertEqual(source[:96], output[:96])
            self.assertEqual(source[120:], output[120:])
            self.assertEqual(struct.unpack_from('<3d', output, 96), (*factorial.XY, heading))

    def test_invalid_environment(self):
        for data in (b'', b'bad magic' + bytes(300)):
            with self.assertRaises(ValueError): factorial.environment(data, .42)

    def test_complete_and_corruption_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'out'; manifest = factorial.prepare(factorial.SCENES, output)
            self.assertEqual(len(manifest['conditions']), 27)
            factorial.verify(factorial.SCENES, output, manifest)
            env = output / manifest['conditions'][0]['catalog'] / '0/environment.bin'
            data = bytearray(env.read_bytes()); data[-1] ^= 1; env.write_bytes(data)
            with self.assertRaises(ValueError): factorial.verify(factorial.SCENES, output, manifest)
            with self.assertRaises(ValueError): factorial.prepare(factorial.SCENES, output)


if __name__ == '__main__':
    unittest.main()
