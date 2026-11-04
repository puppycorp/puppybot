#!/usr/bin/env python3
"""CPU receipt checks for the staged full matched training gate."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
p = ROOT / 'datasets/visual-control/chase-v1/levels/run-heading-training.py'
s = importlib.util.spec_from_file_location('training', p); training = importlib.util.module_from_spec(s); s.loader.exec_module(training)


class ReceiptTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.m = Path(self.tmp.name); (self.m / 'kernels').mkdir()
        for name in ('data.bin','weights.bin','policy','model.pup'):
            (self.m / name).write_bytes(name.encode())
        (self.m / 'kernels/k.hip').write_bytes(b'kernel')
        self.d = training.base.sha(self.m / 'data.bin'); self.maphash = 'map'; self.parent = 'parent'
        self.r = {'dataSHA256':self.d, 'memoryMapTargetsSHA256':self.maphash, 'initialWeightsSHA256':self.parent,
                  'seed':6900000, 'epochs':8, 'batch':2, 'checkpointEveryEpochs':8,
                  'sequenceMirrorAugmentation':True, 'carryCue':True, 'speedTransitionLossWeight':1,
                  'actionCodec':'joint-seven-v1', 'weightsSHA256':training.base.sha(self.m/'weights.bin'),
                  'binarySHA256':training.base.sha(self.m/'policy'), 'graphSHA256':training.base.sha(self.m/'model.pup'),
                  'kernels':{'k.hip':training.base.sha(self.m/'kernels/k.hip')}}

    def save(self): (self.m / 'receipt.json').write_text(json.dumps(self.r))

    def test_valid_and_wrong_options(self):
        self.save(); training.verify_full_receipt(self.m, self.d, self.maphash, self.parent)
        for key, value in [('carryCue', False), ('seed', 1), ('epochs', 1), ('actionCodec','unknown')]:
            old = self.r[key]; self.r[key] = value; self.save()
            with self.subTest(key=key), self.assertRaises(ValueError): training.verify_full_receipt(self.m, self.d, self.maphash, self.parent)
            self.r[key] = old

    def test_changed_kernel_or_data_rejected(self):
        self.save(); (self.m/'kernels/k.hip').write_bytes(b'changed')
        with self.assertRaises(ValueError): training.verify_full_receipt(self.m, self.d, self.maphash, self.parent)
        (self.m/'kernels/k.hip').write_bytes(b'kernel'); (self.m/'data.bin').write_bytes(b'changed')
        with self.assertRaises(ValueError): training.verify_full_receipt(self.m, self.d, self.maphash, self.parent)


if __name__ == '__main__': unittest.main()
