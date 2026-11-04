#!/usr/bin/env python3
"""CPU fixtures for the one-update evidence checks; no GPU is launched."""
import importlib.util
import json
import struct
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('audit', HERE / 'audit.py')
audit = importlib.util.module_from_spec(spec); spec.loader.exec_module(audit)


def tensor(values):
    values = list(values) + [0.] * (7 - len(values))
    header = bytearray(288); header[:8] = b'PUPV0001'
    struct.pack_into('<QQQ', header, 8, 1, 288, len(values) * 4)
    header[32:43] = b'actor7.bias'
    struct.pack_into('<QQQ4Q', header, 32 + 192, 1, len(values), 0, len(values), 1, 1, 1)
    return bytes(header) + struct.pack(f'<{len(values)}f', *values)


class Checks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.saved = audit.PARENT, audit.DATA, audit.MAP
        self.initial = tensor([1.0, 2.0]); audit.PARENT = __import__('hashlib').sha256(self.initial).hexdigest()
        audit.DATA = {'control': __import__('hashlib').sha256(b'control').hexdigest(),
                      'treatment': __import__('hashlib').sha256(b'treatment').hexdigest()}
        audit.MAP = 'map-hash'

    def tearDown(self):
        audit.PARENT, audit.DATA, audit.MAP = self.saved; self.tmp.cleanup()

    def model(self, arm):
        model = self.root / arm; model.mkdir(); (model / 'kernels').mkdir()
        blobs = {'backend.txt': b'hip', 'data.bin': arm.encode(), 'seed.bin': self.initial,
                 'initial.bin': self.initial, 'weights.bin': tensor([1.1, 2.0]),
                 'policy': b'policy', 'model.pup': b'graph',
                 'first-gradients.bin': tensor([.1 if arm == 'control' else .3, .2]), 'first-after.bin': tensor([1.1, 2.0]),
                 'epoch-1.bin': tensor([1.1, 2.0]), 'last.bin': tensor([1.1, 2.0]),
                 'first-order.bin': struct.pack('<1031Q', *audit.order_for_seed(audit.SEED)),
                 'first-mirror-mask.bin': struct.pack('<Q', 3)}
        blobs['final-order.bin'] = blobs['first-order.bin']
        for name, blob in blobs.items(): (model / name).write_bytes(blob)
        (model / 'kernels/k').write_bytes(b'kernel')
        receipt = {'dataSHA256': audit.DATA[arm], 'memoryMapTargetsSHA256': audit.MAP,
                   'initialWeightsSHA256': audit.PARENT, 'seed': audit.SEED, 'epochs': 1, 'batch': 2,
                   'learningRateMicros': 100, 'checkpointEveryEpochs': 1, 'maxOptimizerSteps': 1,
                   'sequenceMirrorAugmentation': True, 'carryCue': True, 'speedTransitionLossWeight': 1,
                   'stopLossWeight': 5, 'actionCodec': 'joint-seven-v1',
                   'weightsSHA256': audit.sha(model / 'weights.bin'), 'binarySHA256': audit.sha(model / 'policy'),
                   'graphSHA256': audit.sha(model / 'model.pup'), 'kernels': {'k': audit.sha(model / 'kernels/k')}}
        (model / 'receipt.json').write_text(json.dumps(receipt))
        curves = [{'epoch': i, 'optimizerSteps': i, 'maxOptimizerSteps': 1, 'gradientNorm': float(i),
                   'trainingLoss': .4, 'validationLoss': .5, 'mapTrainingLoss': .2 if i else None,
                   'mapValidationLoss': .3} for i in (0, 1)]
        (model / 'curves.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in curves))
        return model

    def test_one_step_pair_and_exact_first_batch(self):
        left = audit.audit_model(self.model('control'), 'control')
        right = audit.audit_model(self.model('treatment'), 'treatment')
        self.assertEqual(left['firstBatch'], [203, 934])
        self.assertEqual(audit.compare(left, right)['status'], 'one_step_diagnostic_only')

    def test_nonfinite_tensor_and_missing_update_rejected(self):
        model = self.model('control')
        for blob in (tensor([float('nan'), 1]), tensor([0., 0.])):
            (model / 'first-gradients.bin').write_bytes(blob)
            with self.assertRaises(ValueError): audit.audit_model(model, 'control')
        (model / 'first-gradients.bin').write_bytes(tensor([1., 2.]))
        (model / 'first-after.bin').write_bytes(self.initial)
        with self.assertRaises(ValueError): audit.audit_model(model, 'control')

    def test_wrong_batch_or_augmentation_rejected(self):
        control = audit.audit_model(self.model('control'), 'control')
        treatment = audit.audit_model(self.model('treatment'), 'treatment')
        treatment['mirrorMask'] ^= 1
        with self.assertRaises(ValueError): audit.compare(control, treatment)
        (self.root / 'treatment/first-mirror-mask.bin').write_bytes(struct.pack('<Q', 2))
        with self.assertRaises(ValueError): audit.audit_model(self.root / 'treatment', 'treatment')
        (self.root / 'control/first-order.bin').write_bytes(bytes(1031 * 8))
        with self.assertRaises(ValueError): audit.audit_model(self.root / 'control', 'control')

    def test_equal_gradients_are_inconclusive(self):
        control = audit.audit_model(self.model('control'), 'control')
        treatment = audit.audit_model(self.model('treatment'), 'treatment')
        treatment['checkpoints']['first-gradients.bin']['actorBias'] = control['checkpoints']['first-gradients.bin']['actorBias']
        with self.assertRaises(ValueError): audit.compare(control, treatment)

    def test_step_and_aux_loss_rejected(self):
        model = self.model('control'); curves = [json.loads(s) for s in (model / 'curves.jsonl').read_text().splitlines()]
        for field, value in (('optimizerSteps', 2), ('mapTrainingLoss', None)):
            modified = [dict(row) for row in curves]; modified[1][field] = value
            (model / 'curves.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in modified))
            with self.assertRaises(ValueError): audit.audit_model(model, 'control')


if __name__ == '__main__': unittest.main()
