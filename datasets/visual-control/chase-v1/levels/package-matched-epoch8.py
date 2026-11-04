#!/usr/bin/env python3
"""Create or verify separate read-only epoch-8 inference copies.

Usage: package-matched-epoch8.py create|verify CONTROL TREATMENT OUTPUT
The derived receipts are not original training receipts. Read-only permissions
and hashes detect accidental changes, not an attacker with owner privileges.
"""
import ctypes
import fcntl
import hashlib
import json
import os
import shutil
import struct
import sys
import tempfile
from pathlib import Path


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def source_info(source):
    receipt = json.loads((source / 'receipt.json').read_text())
    if receipt.get('epochs') != 8 or receipt.get('checkpointEveryEpochs') != 8:
        raise ValueError('not a completed epoch-8 training configuration')
    for field, name in (('weightsSHA256', 'weights.bin'), ('binarySHA256', 'policy'), ('graphSHA256', 'model.pup')):
        if receipt.get(field) != digest(source / name):
            raise ValueError(f'original receipt mismatch: {name}')
    kernels = receipt.get('kernels')
    if not isinstance(kernels, dict) or not kernels:
        raise ValueError('missing kernel hashes')
    for name, checksum in kernels.items():
        if Path(name).name != name or checksum != digest(source / 'kernels' / name):
            raise ValueError(f'invalid kernel: {name}')
    curves = [json.loads(line) for line in (source / 'curves.jsonl').read_text().splitlines()]
    if [r['epoch'] for r in curves] != list(range(9)) or curves[-1]['optimizerSteps'] != 3712:
        raise ValueError('incomplete epoch-8 curve')
    selected, epoch = (source / 'weights.bin').read_bytes(), (source / 'epoch-8.bin').read_bytes()
    if digest(source / 'epoch-8.bin') != digest(source / 'last.bin'):
        raise ValueError('epoch-8 differs from the final training snapshot')
    if len(selected) != len(epoch) or len(epoch) < 32 or epoch[:8] != b'PUPV0001':
        raise ValueError('invalid checkpoint')
    count = struct.unpack_from('<Q', epoch, 8)[0]
    end = 32 + count * 256
    if not 0 < count <= 4096 or end > len(epoch) or selected[:end] != epoch[:end]:
        raise ValueError('checkpoint architecture differs from the selected model')
    return receipt


def derived_receipt(receipt, epoch_hash, receipt_hash):
    result = dict(receipt)
    result.update(checkpointSourceWeightsSHA256=receipt['weightsSHA256'], weightsSHA256=epoch_hash,
                  checkpointSHA256=epoch_hash, checkpointEpoch=8, checkpointSelection='fixed epoch, not validation selected',
                  sourceTrainingReceiptSHA256=receipt_hash)
    return result


def verify_one(source, package):
    receipt = source_info(source)
    if (package / 'training-receipt.json').read_bytes() != (source / 'receipt.json').read_bytes():
        raise ValueError('original training receipt differs')
    epoch_hash = digest(source / 'epoch-8.bin')
    expected = derived_receipt(receipt, epoch_hash, digest(source / 'receipt.json'))
    if json.loads((package / 'receipt.json').read_text()) != expected:
        raise ValueError('derived receipt differs')
    if digest(package / 'weights.bin') != epoch_hash:
        raise ValueError('packaged weights differ from epoch-8')
    for name in ('policy', 'model.pup', 'factory.flex'):
        if digest(package / name) != digest(source / name):
            raise ValueError(f'packaged file differs: {name}')
    if {p.name for p in (package / 'kernels').iterdir()} != set(receipt['kernels']):
        raise ValueError('packaged kernel set differs')
    for name in receipt['kernels']:
        if digest(package / 'kernels' / name) != receipt['kernels'][name]:
            raise ValueError(f'packaged kernel differs: {name}')
    required = {'weights.bin', 'policy', 'model.pup', 'factory.flex', 'receipt.json', 'training-receipt.json', 'kernels'}
    if {p.name for p in package.iterdir()} != required:
        raise ValueError('unexpected package files')
    for path in [package, package / 'kernels', *(p for p in package.rglob('*') if p.is_file())]:
        if path.is_symlink() or path.stat().st_mode & 0o222:
            raise ValueError(f'package is not read-only: {path}')
    if not os.access(package / 'policy', os.X_OK):
        raise ValueError('policy is not executable')
    return {'weightsSHA256': epoch_hash, 'selectedWeightsSHA256': receipt['weightsSHA256'],
            'sourceReceiptSHA256': digest(source / 'receipt.json'),
            'sourceCurvesSHA256': digest(source / 'curves.jsonl'),
            'sourceFinalSnapshotSHA256': digest(source / 'last.bin')}


def verify(control, treatment, output):
    if output.is_symlink() or output.stat().st_mode & 0o222:
        raise ValueError('package root is not read-only')
    if {p.name for p in output.iterdir()} != {'control', 'treatment', 'manifest.json'}:
        raise ValueError('unexpected package root files')
    arms = {name: verify_one(source, output / name) for name, source in (('control', control), ('treatment', treatment))}
    manifest = json.loads((output / 'manifest.json').read_text())
    if manifest != {'schema': 'puppybot.fixed-epoch-pair.v1', 'epoch': 8, 'arms': arms,
                    'scope': 'read-only derived copies, not original training receipts; hashes and permissions do not provide tamper-proof attestation'}:
        raise ValueError('package manifest mismatch')
    if (output / 'manifest.json').is_symlink() or (output / 'manifest.json').stat().st_mode & 0o222:
        raise ValueError('package manifest is writable')
    return manifest


def create(control, treatment, output):
    for source in (control, treatment):
        source_info(source)
    if output.exists() or output.is_symlink():
        raise ValueError('package output already exists')
    stage = Path(tempfile.mkdtemp(prefix=f'.{output.name}.partial-', dir=output.parent))
    for name, source in (('control', control), ('treatment', treatment)):
        target = stage / name; target.mkdir(); (target / 'kernels').mkdir()
        receipt = source_info(source)
        for old, new in (('epoch-8.bin', 'weights.bin'), ('policy', 'policy'), ('model.pup', 'model.pup'),
                         ('factory.flex', 'factory.flex'), ('receipt.json', 'training-receipt.json')):
            shutil.copyfile(source / old, target / new)
        for kernel in receipt['kernels']:
            shutil.copyfile(source / 'kernels' / kernel, target / 'kernels' / kernel)
        derived = derived_receipt(receipt, digest(target / 'weights.bin'), digest(target / 'training-receipt.json'))
        (target / 'receipt.json').write_text(json.dumps(derived, sort_keys=True, indent=2) + '\n')
        for path in target.rglob('*'):
            if path.is_file(): path.chmod(0o555 if path.name == 'policy' else 0o444)
        (target / 'kernels').chmod(0o555); target.chmod(0o555)
    arms = {name: verify_one(source, stage / name) for name, source in (('control', control), ('treatment', treatment))}
    manifest = {'schema': 'puppybot.fixed-epoch-pair.v1', 'epoch': 8, 'arms': arms,
                'scope': 'read-only derived copies, not original training receipts; hashes and permissions do not provide tamper-proof attestation'}
    (stage / 'manifest.json').write_text(json.dumps(manifest, sort_keys=True, indent=2) + '\n')
    (stage / 'manifest.json').chmod(0o444); stage.chmod(0o555)
    verify(control, treatment, stage)
    # Atomic no-replace publication even if another process creates the target.
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.renameat2(-100, os.fsencode(stage), -100, os.fsencode(output), 1) != 0:
        raise OSError(ctypes.get_errno(), f'cannot publish; partial package retained at {stage}')
    return verify(control, treatment, output)


def main():
    if len(sys.argv) != 5 or sys.argv[1] not in ('create', 'verify'):
        raise SystemExit(__doc__)
    control, treatment, output = (Path(x).absolute() for x in sys.argv[2:])
    if control.parent != treatment.parent or output.parent != control.parent:
        raise ValueError('models and package must share their experiment directory')
    # Same lock as training/selection; persistent file is not a running marker.
    with (output.parent.parent / '.l4-matched.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = create(control, treatment, output) if sys.argv[1] == 'create' else verify(control, treatment, output)
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
