#!/usr/bin/env python3
"""Exercise the isolated full trainer build without a GPU or real dataset."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
spec = importlib.util.spec_from_file_location('trainer_builder', HERE / 'build.py')
builder = importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)


class BuildTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='outbound-trainer-test-', dir=ROOT / 'build/flex/sim')
        cls.output = Path(cls.tmp.name) / 'build'
        cls.receipt = builder.build(cls.output)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_full_build_and_source_pins(self):
        self.assertEqual(builder.verify(self.output), self.receipt)
        self.assertEqual(self.receipt['dimensions'], [1029, 933, 300])
        self.assertEqual(self.receipt['episodeRange'], [928, 933])
        self.assertGreater(len(self.receipt['imports']), 10)
        workflow = (self.output / 'flex-source/control/workflow.flex').read_text()
        self.assertIn(f'vc_add(args,"{self.output / "trainer"}")', workflow)
        self.assertIn('FICLONE failed', (self.output / 'flex-source/control/dataset.flex').read_text())

    def test_unrelated_source_or_binary_changes_are_rejected(self):
        for path in (self.output / 'control', self.output / 'flex-source/control/loss.flex'):
            with self.subTest(path=path.name):
                original = path.read_bytes()
                try:
                    path.write_bytes(original + b'\n')
                    with self.assertRaises(ValueError): builder.verify(self.output)
                finally:
                    path.write_bytes(original)
        self.assertEqual(builder.verify(self.output), self.receipt)

    def test_no_existing_output_overwrite_and_low_disk_rejected(self):
        with self.assertRaises(FileExistsError): builder.build(self.output)
        usage = type('Usage', (), {'free': 35 * 1024**3})()
        with mock.patch.object(builder.shutil, 'disk_usage', return_value=usage):
            with self.assertRaisesRegex(ValueError, 'headroom'):
                builder.build(self.output.parent / 'other')
        self.assertFalse((self.output.parent / 'other').exists())

    def test_rejects_bad_receipt_and_transforms(self):
        receipt_path = self.output / 'build.json'; original = receipt_path.read_bytes()
        try:
            receipt = json.loads(original); receipt['episodeRange'] = [929, 934]
            receipt_path.write_text(json.dumps(receipt))
            with self.assertRaises(ValueError): builder.verify(self.output)
        finally:
            receipt_path.write_bytes(original)
        with self.assertRaises(ValueError): builder.workflow('unrelated', self.output / 'trainer')
        self.assertEqual(builder.verify(self.output), self.receipt)


if __name__ == '__main__':
    unittest.main()
