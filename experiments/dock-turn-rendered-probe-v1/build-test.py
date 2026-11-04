#!/usr/bin/env python3
"""CPU fixture checks real private build and rejection of modified inputs."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('turn_build_fixture', HERE / 'build.py')
builder = importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)


class BuildTest(unittest.TestCase):
    def test_real_build_and_mutation_rejection(self):
        with tempfile.TemporaryDirectory(prefix='turn-build-fixture-') as temp:
            output = Path(temp) / 'build'; receipt = builder.build(output)
            self.assertEqual(builder.verify(output), receipt)
            arm = output / 'candidate-10'
            for path in (arm / 'build/flex/sim/dependencies.flex',
                         arm / 'flex/sim/case.flex', arm / 'simulator'):
                data = path.read_bytes(); path.write_bytes(data + b'\n')
                with self.subTest(path=path), self.assertRaises(ValueError):
                    builder.verify(output)
                path.write_bytes(data)
            self.assertEqual(builder.verify(output), receipt)


if __name__ == '__main__':
    unittest.main()
