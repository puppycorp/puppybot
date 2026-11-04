#!/usr/bin/env python3
"""Read-only audit helpers for a single-step paired trainer diagnostic."""
import hashlib
import json
import math
import struct
from pathlib import Path


PARENT = '9c586f40ad6fc1a13a17f325cd3b33da5aca07e4790ee0922fd59049cd89f0d1'
DATA = {'control': 'b9dc5993760a0b8117d303cbdd083eca21014f8824ce52d796715c90d349ea84',
        'treatment': '6d70db07119cedda63acb7ee044bbd96fc864e3609894be9cb78158101b50769'}
MAP = '8d970ce34bfa5acd626598ea843fe5895427814a02582dcd4bc0a9116779affb'
SEED = 7120260


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def order_for_seed(seed):
    order = list(range(1031)); rng = seed
    for i in range(934, 0, -1):
        rng = (rng * 1103515245 + 12345) & 2147483647
        j = rng % (i + 1); order[i], order[j] = order[j], order[i]
    return tuple(order)


def checkpoint(path):
    data = Path(path).read_bytes()
    if len(data) < 32 or data[:8] != b'PUPV0001':
        raise ValueError('invalid checkpoint magic')
    count, start, size = struct.unpack_from('<QQQ', data, 8)
    if not 0 < count <= 4096 or start != 32 + count * 256 or size % 4 or start + size != len(data):
        raise ValueError('invalid checkpoint dimensions')
    offset = 0; names = set(); actor_bias = None
    for i in range(count):
        record = data[32 + i * 256:32 + (i + 1) * 256]
        name = record[:192].split(b'\0', 1)[0]
        rank, elements, at = struct.unpack_from('<QQQ', record, 192)
        dims = struct.unpack_from('<4Q', record, 216)
        if (not name or name in names or not 1 <= rank <= 4 or at != offset or
                any(d == 0 for d in dims) or math.prod(dims) != elements):
            raise ValueError('invalid checkpoint tensor table')
        names.add(name)
        if name == b'actor7.bias':
            if rank != 1 or elements != 7: raise ValueError('invalid categorical actor bias')
            actor_bias = list(struct.unpack_from('<7f', data, start + at))
        offset += elements * 4
    if offset != size:
        raise ValueError('checkpoint tensor size mismatch')
    values = struct.iter_unpack('<f', data[start:]); nonzero = 0
    for (value,) in values:
        if not math.isfinite(value): raise ValueError('nonfinite checkpoint value')
        nonzero += value != 0
    return {'tableSHA256': hashlib.sha256(data[:start]).hexdigest(),
            'sha256': hashlib.sha256(data).hexdigest(), 'nonzero': nonzero, 'actorBias': actor_bias}


def audit_model(model, arm, runtime=None):
    model = Path(model)
    if arm not in DATA: raise ValueError('unknown arm')
    receipt = json.loads((model / 'receipt.json').read_text())
    expected = {'dataSHA256': DATA[arm], 'memoryMapTargetsSHA256': MAP,
                'initialWeightsSHA256': PARENT, 'seed': SEED, 'epochs': 1, 'batch': 2,
                'learningRateMicros': 100, 'checkpointEveryEpochs': 1, 'maxOptimizerSteps': 1,
                'sequenceMirrorAugmentation': True, 'carryCue': True, 'speedTransitionLossWeight': 1,
                'stopLossWeight': 5, 'actionCodec': 'joint-seven-v1'}
    if any(receipt.get(k) != v or type(receipt.get(k)) is not type(v) for k, v in expected.items()):
        raise ValueError('smoke receipt differs from registered options')
    if (model / 'backend.txt').read_bytes() != b'hip' or sha(model / 'data.bin') != DATA[arm]:
        raise ValueError('backend or input data differs')
    if sha(model / 'seed.bin') != PARENT or sha(model / 'initial.bin') != PARENT:
        raise ValueError('initial weights differ from parent')
    for key, name in (('weightsSHA256', 'weights.bin'), ('binarySHA256', 'policy'), ('graphSHA256', 'model.pup')):
        if sha(model / name) != receipt.get(key): raise ValueError('published artifact hash differs')
    kernels = receipt.get('kernels')
    if not isinstance(kernels, dict) or not kernels:
        raise ValueError('kernel receipt missing')
    for name, digest in kernels.items():
        if Path(name).name != name or sha(model / 'kernels' / name) != digest:
            raise ValueError('kernel hash differs')
    if runtime is not None and (receipt.get('binarySHA256') != runtime.get('binarySHA256') or
            receipt.get('graphSHA256') != runtime.get('graphSHA256') or kernels != runtime.get('kernels')):
        raise ValueError('published runtime differs from registered parent')
    order_bytes = (model / 'first-order.bin').read_bytes()
    if len(order_bytes) != 1031 * 8 or order_bytes != (model / 'final-order.bin').read_bytes():
        raise ValueError('training order size or saved order differs')
    order = struct.unpack('<1031Q', order_bytes)
    if order != order_for_seed(SEED) or order[:2] != (203, 934):
        raise ValueError('unexpected fitting order or first batch')
    mirror = (model / 'first-mirror-mask.bin').read_bytes()
    if len(mirror) != 8 or struct.unpack('<Q', mirror)[0] != 3:
        raise ValueError('first batch mirror mask differs from the seeded generator')
    curves = [json.loads(line) for line in (model / 'curves.jsonl').read_text().splitlines()]
    if (len(curves) != 2 or [r.get('epoch') for r in curves] != [0, 1] or
            [r.get('optimizerSteps') for r in curves] != [0, 1] or
            any(r.get('maxOptimizerSteps') != 1 for r in curves)):
        raise ValueError('smoke did not complete exactly one update')
    for row in curves:
        for key in ('trainingLoss', 'validationLoss', 'mapValidationLoss', 'gradientNorm'):
            value = row.get(key)
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError(f'invalid {key}')
    if (type(curves[1].get('mapTrainingLoss')) not in (int, float) or
            not math.isfinite(curves[1]['mapTrainingLoss']) or curves[1]['gradientNorm'] <= 0):
        raise ValueError('nonfinite map training loss or empty gradient')
    checks = {name: checkpoint(model / name) for name in
              ('initial.bin', 'first-gradients.bin', 'first-after.bin', 'last.bin', 'epoch-1.bin')}
    if (len({item['tableSHA256'] for item in checks.values()}) != 1 or
            not checks['first-gradients.bin']['nonzero'] or checks['first-gradients.bin']['actorBias'] is None or
            checks['first-after.bin']['sha256'] == checks['initial.bin']['sha256'] or
            checks['first-after.bin']['sha256'] != checks['last.bin']['sha256'] or
            checks['last.bin']['sha256'] != checks['epoch-1.bin']['sha256']):
        raise ValueError('gradient, update or checkpoint differs')
    return {'arm': arm, 'receiptSHA256': sha(model / 'receipt.json'), 'checkpoints': checks,
            'firstBatch': list(order[:2]), 'mirrorMask': struct.unpack('<Q', mirror)[0],
            'curves': curves}


def compare(control, treatment):
    if (control['arm'] != 'control' or treatment['arm'] != 'treatment' or
            control['firstBatch'] != treatment['firstBatch'] or control['mirrorMask'] != treatment['mirrorMask']):
        raise ValueError('smoke arm order or augmentation differs')
    if control['checkpoints']['first-gradients.bin']['actorBias'] == treatment['checkpoints']['first-gradients.bin']['actorBias']:
        raise ValueError('label intervention produced no observed actor bias gradient difference')
    return {'status': 'one_step_diagnostic_only', 'control': control, 'treatment': treatment,
            'gradientHashesDiffer': True,
            'scope': 'one update only; no full-epoch, selection, held-out or physical proof'}
