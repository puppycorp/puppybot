#!/usr/bin/env python3
"""CPU-only fixed-epoch package integrity fixtures."""
import importlib.util
import json
import struct
import tempfile
import unittest
from pathlib import Path

root = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('package', root / 'datasets/visual-control/chase-v1/levels/package-matched-epoch8.py')
package = importlib.util.module_from_spec(spec); spec.loader.exec_module(package)


def model(path):
    path.mkdir(); (path / 'kernels').mkdir()
    header = b'PUPV0001' + struct.pack('<Q', 1) + bytes(16 + 256)
    for name, content in (('weights.bin', header + b'selected'), ('epoch-8.bin', header + b'epoch888'),
                          ('last.bin', header + b'epoch888'), ('policy', b'policy'),
                          ('model.pup', b'graph'), ('factory.flex', b'factory')):
        (path / name).write_bytes(content)
    (path / 'kernels' / 'one.hip').write_bytes(b'kernel')
    receipt = {'weightsSHA256': package.digest(path / 'weights.bin'), 'binarySHA256': package.digest(path / 'policy'),
               'graphSHA256': package.digest(path / 'model.pup'), 'kernels': {'one.hip': package.digest(path / 'kernels/one.hip')},
               'epochs': 8, 'checkpointEveryEpochs': 8}
    (path / 'receipt.json').write_text(json.dumps(receipt))
    rows = [{'epoch': n, 'optimizerSteps': n * 464} for n in range(9)]
    (path / 'curves.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in rows))


class PackageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.control = self.root / 'control'; self.treatment = self.root / 'treatment'
        model(self.control); model(self.treatment); self.out = self.root / 'pair'

    def test_create_verify_and_no_overwrite(self):
        result = package.create(self.control, self.treatment, self.out)
        self.assertEqual(result['epoch'], 8)
        self.assertEqual((self.out / 'control/training-receipt.json').read_bytes(), (self.control / 'receipt.json').read_bytes())
        self.assertEqual((self.out / 'control/weights.bin').read_bytes(), (self.control / 'epoch-8.bin').read_bytes())
        self.assertEqual(package.verify(self.control, self.treatment, self.out), result)
        with self.assertRaises(ValueError): package.create(self.control, self.treatment, self.out)

    def test_corrupt_package_rejected(self):
        package.create(self.control, self.treatment, self.out)
        p = self.out / 'control/weights.bin'; p.chmod(0o644); p.write_bytes(b'corrupt'); p.chmod(0o444)
        with self.assertRaises(ValueError): package.verify(self.control, self.treatment, self.out)

    def test_writable_or_receipt_tamper_rejected(self):
        package.create(self.control, self.treatment, self.out)
        p = self.out / 'control/receipt.json'; p.chmod(0o644)
        with self.assertRaises(ValueError): package.verify(self.control, self.treatment, self.out)
        p.write_text('{}'); p.chmod(0o444)
        with self.assertRaises(ValueError): package.verify(self.control, self.treatment, self.out)

    def test_wrong_epoch_or_architecture_rejected(self):
        (self.control / 'last.bin').write_bytes(b'wrong')
        with self.assertRaises(ValueError): package.create(self.control, self.treatment, self.out)
        epoch = (self.control / 'epoch-8.bin').read_bytes()
        altered = bytearray(epoch); altered[40] = 7
        (self.control / 'epoch-8.bin').write_bytes(altered); (self.control / 'last.bin').write_bytes(altered)
        with self.assertRaises(ValueError): package.create(self.control, self.treatment, self.out)

    def test_bad_policy_and_kernel_receipts_rejected(self):
        (self.control / 'policy').write_bytes(b'changed')
        with self.assertRaises(ValueError): package.create(self.control, self.treatment, self.out)
        (self.control / 'policy').write_bytes(b'policy'); (self.control / 'kernels/one.hip').write_bytes(b'changed')
        with self.assertRaises(ValueError): package.create(self.control, self.treatment, self.out)


if __name__ == '__main__':
    unittest.main()
