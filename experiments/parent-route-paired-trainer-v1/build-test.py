#!/usr/bin/env python3
"""CPU-only reproducible private trainer build and corruption checks."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
spec = importlib.util.spec_from_file_location('paired_trainer_builder', HERE / 'build.py')
builder = importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)


class BuildTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='parent-paired-trainer-test-', dir=ROOT / 'build/flex/sim')
        cls.output = Path(cls.temp.name) / 'private'
        cls.receipt = builder.build(cls.output)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_full_compilation_and_reproducible_source_binding(self):
        self.assertEqual(builder.verify(self.output), self.receipt)
        self.assertEqual(self.receipt['dimensions'], [1031, 935, 300])
        self.assertEqual(self.receipt['auxiliaryMaskEpisodeRange'], [928, 935])
        self.assertGreater(len(self.receipt['imports']), 10)
        workflow = (self.output / 'flex-source/control/workflow.flex').read_text()
        self.assertIn(f'vc_add(args,"{self.output / "trainer"}")', workflow)
        train = (self.output / 'flex-source/control/train.flex').read_text()
        self.assertLess(train.index('    pt_check_rows(episodes);'), train.index('vp_init(load64(argv+24)'))
        self.assertEqual(train.count('pt_check_rows(episodes);'), 1)

    def test_changed_source_binary_fixture_or_receipt_rejected(self):
        for path in (self.output / 'trainer', self.output / 'flex-source/control/loss.flex',
                     self.output / 'clone-fixture/target'):
            with self.subTest(path=path.name):
                original = path.read_bytes()
                try:
                    path.write_bytes(original + b'\n')
                    with self.assertRaises(ValueError):
                        builder.verify(self.output)
                finally:
                    path.write_bytes(original)
        receipt_path = self.output / 'build.json'; original = receipt_path.read_bytes()
        try:
            receipt = json.loads(original); receipt['auxiliaryMaskEpisodeRange'] = [928, 934]
            receipt_path.write_text(json.dumps(receipt))
            with self.assertRaises(ValueError): builder.verify(self.output)
        finally:
            receipt_path.write_bytes(original)
        self.assertEqual(builder.verify(self.output), self.receipt)

    def test_existing_output_and_low_disk_rejected(self):
        with self.assertRaises(FileExistsError): builder.build(self.output)
        usage = type('Usage', (), {'free': 37 * 1024**3})()
        with mock.patch.object(builder.shutil, 'disk_usage', return_value=usage):
            with self.assertRaisesRegex(ValueError, '38 GiB'):
                builder.build(self.output.parent / 'other')
        self.assertFalse((self.output.parent / 'other').exists())

    def test_unexpected_source_and_path_anchors_rejected(self):
        with self.assertRaises(ValueError): builder.transform.dataset('unrelated')
        with self.assertRaises(ValueError): builder.transform.train('unrelated')
        with self.assertRaises(ValueError): builder.transform.workflow('unrelated', 'a', 'b')
        with self.assertRaises(ValueError): builder.transform.workflow('unrelated', 'a', 'bad"path')


if __name__ == '__main__':
    unittest.main()
