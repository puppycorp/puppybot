#!/usr/bin/env python3
"""Audit full fixed-epoch models and build read-only epoch-1 packages."""
import json
import math
import os
import shutil
import struct
import subprocess
from pathlib import Path


def read(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError('missing or linked full-pair file: ' + str(path))
    return json.loads(path.read_text())


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def clone_evidence(plan, arm):
    source = plan.smoke.plan.DATA / arm / 'data.bin'; target = plan.OUTPUT / arm / 'data.bin'
    if source.is_symlink() or target.is_symlink() or not source.is_file() or not target.is_file():
        raise ValueError('missing or linked dataset copy')
    before, copied = source.stat(), target.stat()
    if (before.st_dev != copied.st_dev or before.st_ino == copied.st_ino or before.st_nlink != 1 or copied.st_nlink != 1 or
            before.st_size != copied.st_size or plan.sha(source) != plan.smoke.audit.DATA[arm] or
            plan.sha(target) != plan.smoke.audit.DATA[arm]):
        raise ValueError('training data copy bytes or inode differ')
    rows = subprocess.run(['/usr/bin/btrfs', 'filesystem', 'du', '--raw', '-s', str(source), str(target)],
                          capture_output=True, text=True, check=True, timeout=300).stdout.splitlines()
    if len(rows) != 3:
        raise ValueError('invalid Btrfs extent output')
    extents = []
    for row in rows[1:]:
        fields = row.split(maxsplit=3)
        if len(fields) != 4 or not all(item.isdigit() for item in fields[:3]):
            raise ValueError('invalid Btrfs extent row')
        extents.append(dict(zip(('total', 'exclusive', 'shared'), map(int, fields[:3]))))
    return {'sourceInode': before.st_ino, 'targetInode': copied.st_ino, 'device': before.st_dev,
            'size': before.st_size, 'sourceExtents': extents[0], 'targetExtents': extents[1],
            'scope': 'supplementary Btrfs totals; not proof of pairwise extent identity'}


def model(plan, arm):
    if arm not in ('control', 'treatment'):
        raise ValueError('unknown model arm')
    directory = plan.OUTPUT / arm; receipt = read(directory / 'receipt.json')
    expected = {'dataSHA256': plan.smoke.audit.DATA[arm], 'memoryMapTargetsSHA256': plan.smoke.audit.MAP,
                'initialWeightsSHA256': plan.smoke.audit.PARENT, 'seed': 7120000, 'epochs': 1, 'batch': 2,
                'learningRateMicros': 100, 'checkpointEveryEpochs': 1, 'sequenceMirrorAugmentation': True,
                'carryCue': True, 'speedTransitionLossWeight': 1, 'stopLossWeight': 5,
                'actionCodec': 'joint-seven-v1', 'memoryWidth': 128, 'phaseSupervisionFromValidFrames': False,
                'taskFeedback': False, 'trainingRuntime': 'Flexscript/Pup HIP (RDNA)',
                'fromScratch': False, 'imageSide': 84, 'focusCopiesPerEpoch': 0, 'focusHistory': None,
                'phaseGatedNavigation': False, 'cameraEventAuxiliary': False, 'memoryPoseAuxiliary': False,
                'targetHeatmapAuxiliary': False, 'targetPositionAuxiliary': False,
                'heatmapAbsenceSupervision': False, 'heatmapActorFeatures': False,
                'heatmapActorGradientDetached': False, 'controlLoss': 'weighted joint action cross entropy'}
    for key, value in expected.items():
        if type(receipt.get(key)) is not type(value) or receipt[key] != value:
            raise ValueError('full-epoch receipt differs: ' + key)
    if 'maxOptimizerSteps' in receipt and (type(receipt['maxOptimizerSteps']) is not int or receipt['maxOptimizerSteps'] != 0):
        raise ValueError('optimizer-step cap is not allowed')
    if ((directory / 'backend.txt').read_bytes() != b'hip' or
            plan.sha(directory / 'data.bin') != expected['dataSHA256'] or
            plan.sha(directory / 'seed.bin') != expected['initialWeightsSHA256'] or
            plan.sha(directory / 'initial.bin') != expected['initialWeightsSHA256']):
        raise ValueError('HIP backend, input or initial weights differ')
    parent = plan.smoke.plan.design.parent_receipt()
    for key, name in (('weightsSHA256', 'weights.bin'), ('binarySHA256', 'policy'), ('graphSHA256', 'model.pup')):
        if receipt.get(key) != plan.sha(directory / name):
            raise ValueError('training output hash differs: ' + key)
    if (receipt.get('binarySHA256') != parent.get('binarySHA256') or
            receipt.get('graphSHA256') != parent.get('graphSHA256') or receipt.get('kernels') != parent.get('kernels')):
        raise ValueError('trained inference runtime differs from parent')
    for name, digest in receipt['kernels'].items():
        if Path(name).name != name or plan.sha(directory / 'kernels' / name) != digest:
            raise ValueError('trained inference kernel differs')
    curves = [json.loads(line) for line in (directory / 'curves.jsonl').read_text().splitlines()]
    if (len(curves) != 2 or [row.get('epoch') for row in curves] != [0, 1] or
            [row.get('optimizerSteps') for row in curves] != [0, 468]):
        raise ValueError('full epoch did not execute exactly 468 optimizer steps')
    for row in curves:
        if any(not finite(row.get(key)) for key in ('trainingLoss', 'validationLoss', 'mapValidationLoss', 'gradientNorm')):
            raise ValueError('nonfinite loss or gradient norm')
    if not finite(curves[1].get('mapTrainingLoss')) or curves[1]['gradientNorm'] <= 0:
        raise ValueError('invalid training map loss or empty gradient')
    checks = {name: plan.smoke.audit.checkpoint(directory / name) for name in
              ('initial.bin', 'first-gradients.bin', 'first-after.bin', 'last.bin', 'epoch-1.bin')}
    if (len({item['tableSHA256'] for item in checks.values()}) != 1 or
            not checks['first-gradients.bin']['nonzero'] or checks['first-gradients.bin']['actorBias'] is None or
            checks['initial.bin']['sha256'] == checks['first-after.bin']['sha256'] or
            checks['initial.bin']['sha256'] == checks['epoch-1.bin']['sha256'] or
            checks['epoch-1.bin']['sha256'] != checks['last.bin']['sha256']):
        raise ValueError('first gradient, update or fixed checkpoint differs')
    return {'arm': arm, 'receiptSHA256': plan.sha(directory / 'receipt.json'),
            'epoch1SHA256': checks['epoch-1.bin']['sha256'], 'checks': checks,
            'dataCopy': clone_evidence(plan, arm), 'curves': curves}


def create_package(plan, arm):
    directory, package = plan.OUTPUT / arm, plan.OUTPUT / ('fixed-' + arm)
    if package.exists() or package.is_symlink():
        raise FileExistsError('fixed-epoch package exists')
    receipt = read(directory / 'receipt.json'); package.mkdir(); (package / 'kernels').mkdir()
    shutil.copyfile(directory / 'epoch-1.bin', package / 'weights.bin')
    for name in ('policy', 'model.pup', 'factory.flex'):
        shutil.copyfile(directory / name, package / name)
    for name in receipt['kernels']:
        if Path(name).name != name: raise ValueError('invalid kernel name')
        shutil.copyfile(directory / 'kernels' / name, package / 'kernels' / name)
    shutil.copyfile(directory / 'receipt.json', package / 'training-receipt.json')
    derived = dict(receipt)
    derived.update({'checkpointSourceWeightsSHA256': receipt['weightsSHA256'],
                    'weightsSHA256': plan.sha(directory / 'epoch-1.bin'),
                    'checkpointSHA256': plan.sha(directory / 'epoch-1.bin'), 'checkpointEpoch': 1,
                    'checkpointSelection': 'fixed epoch, not validation selected',
                    'sourceTrainingReceiptSHA256': plan.sha(directory / 'receipt.json')})
    with (package / 'receipt.json').open('x') as stream:
        json.dump(derived, stream, indent=2, sort_keys=True, allow_nan=False); stream.write('\n')
        stream.flush(); os.fsync(stream.fileno())
    for path in package.rglob('*'):
        if path.is_file(): path.chmod(0o555 if path.name == 'policy' else 0o444)
    (package / 'kernels').chmod(0o555); package.chmod(0o555)
    return verify_package(plan, arm)


def verify_package(plan, arm):
    directory, package = plan.OUTPUT / arm, plan.OUTPUT / ('fixed-' + arm)
    if package.is_symlink() or not package.is_dir() or package.stat().st_mode & 0o222:
        raise ValueError('fixed package must be a read-only directory')
    receipt = read(directory / 'receipt.json'); derived = dict(receipt)
    derived.update({'checkpointSourceWeightsSHA256': receipt['weightsSHA256'],
                    'weightsSHA256': plan.sha(directory / 'epoch-1.bin'),
                    'checkpointSHA256': plan.sha(directory / 'epoch-1.bin'), 'checkpointEpoch': 1,
                    'checkpointSelection': 'fixed epoch, not validation selected',
                    'sourceTrainingReceiptSHA256': plan.sha(directory / 'receipt.json')})
    if ({p.name for p in package.iterdir()} != {'weights.bin', 'policy', 'model.pup', 'factory.flex', 'receipt.json', 'training-receipt.json', 'kernels'} or
            read(package / 'receipt.json') != derived or read(package / 'training-receipt.json') != receipt or
            plan.sha(package / 'weights.bin') != derived['checkpointSHA256']):
        raise ValueError('fixed package metadata or checkpoint differs')
    for name in ('policy', 'model.pup', 'factory.flex'):
        if plan.sha(package / name) != plan.sha(directory / name):
            raise ValueError('fixed package inference runtime differs')
    if {p.name for p in (package / 'kernels').iterdir()} != set(receipt['kernels']):
        raise ValueError('fixed package kernel inventory differs')
    for name, digest in receipt['kernels'].items():
        if plan.sha(package / 'kernels' / name) != digest:
            raise ValueError('fixed package kernel differs')
    if any(path.is_symlink() or path.stat().st_mode & 0o222 for path in package.rglob('*')):
        raise ValueError('fixed package contains writable or linked files')
    return {'weightsSHA256': plan.sha(package / 'weights.bin'),
            'trainingReceiptSHA256': plan.sha(directory / 'receipt.json'),
            'checkpointRule': 'fixed epoch-1; not validation-selected'}


def schedules(plan):
    paths = []
    for arm in ('control', 'treatment'):
        root = plan.OUTPUT / arm
        paths.extend((root / 'batch-schedule.bin', root / 'first-order.bin', root / 'final-order.bin'))
    result = plan.journal.verify(*paths)
    expected = plan.smoke.audit.order_for_seed(7120000)
    for path in (paths[1], paths[2], paths[4], paths[5]):
        raw = plan.journal.read_regular(path)
        if len(raw) != 1031 * 8 or struct.unpack('<1031Q', raw) != expected:
            raise ValueError('saved order differs from registered shuffle seed')
    return result
