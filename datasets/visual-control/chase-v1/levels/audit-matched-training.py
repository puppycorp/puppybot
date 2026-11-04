#!/usr/bin/env python3
"""Compare recorded training artifacts; this is not complete RNG attestation."""
import hashlib
import json
import struct
import sys
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(parent, control, treatment):
    names = ('initial.bin', 'first-order.bin', 'final-order.bin', 'first-mirror-mask.bin')
    hashes = {}
    for name in names:
        hashes[name] = digest(control / name)
        if hashes[name] != digest(treatment / name):
            raise ValueError(f'mismatched recorded artifact: {name}')
    if hashes['initial.bin'] != digest(parent / 'weights.bin'):
        raise ValueError('initial artifact differs from parent weights')
    for name in ('first-order.bin', 'final-order.bin'):
        data = (control / name).read_bytes()
        if len(data) != 1024 * 8:
            raise ValueError(f'invalid order length: {name}')
        order = struct.unpack('<1024Q', data)
        if sorted(order[:928]) != list(range(928)) or order[928:] != tuple(range(928, 1024)):
            raise ValueError(f'invalid fitting permutation or validation order: {name}')
    mask = (control / 'first-mirror-mask.bin').read_bytes()
    if len(mask) != 8 or struct.unpack('<Q', mask)[0] > 3:
        raise ValueError('invalid first batch mirror mask')
    curves = []
    for arm in (control, treatment):
        rows = [json.loads(line) for line in (arm / 'curves.jsonl').read_text().splitlines()]
        if any(type(r['epoch']) is not int for r in rows) or [r['epoch'] for r in rows] != list(range(9)):
            raise ValueError(f'incomplete or duplicate epochs: {arm}')
        if any(type(r['optimizerSteps']) is not int for r in rows) or [r['optimizerSteps'] for r in rows] != [464 * i for i in range(9)]:
            raise ValueError(f'unexpected optimizer counts: {arm}')
        counts = [r['mirroredTrainingSequences'] for r in rows]
        if any(type(x) is not int or x < 0 or x > 928 * i
               or (i > 0 and x < counts[i - 1]) for i, x in enumerate(counts)):
            raise ValueError(f'invalid mirror counts: {arm}')
        curves.append(counts)
    if curves[0] != curves[1]:
        raise ValueError('recorded mirror counts differ')
    return {'status': 'passed', 'artifactSHA256': hashes, 'optimizerSteps': 3712,
            'mirroredSequencesByEpoch': curves[0],
            'scope': 'recorded initial weights, first and final ordering, first mirror mask and per-epoch aggregate mirror counts; intermediate ordering and individual later masks are not attested'}


def main():
    if len(sys.argv) != 4:
        raise SystemExit('Expected PARENT CONTROL TREATMENT')
    print(json.dumps(audit(*(Path(p) for p in sys.argv[1:])), sort_keys=True))


if __name__ == '__main__':
    main()
