#!/usr/bin/env python3
"""Independently audit one opt-in simulated visual-stop run after completion.

Recomputes fixed integer image checks and acknowledged command echoes. This
is not evidence of real hardware stopping or a diagnosis of obstruction.
"""
import hashlib
import json
import math
import re
import struct
import sys
from pathlib import Path

import numpy as np


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def classify(images):
    if len(images) != 10 or any(x.shape != (3, 84, 84) or x.dtype != np.uint8 for x in images):
        raise ValueError('invalid image window')
    for image in images:
        gray = image.astype(np.uint16).sum(axis=0).reshape(-1)
        ordered = np.sort(gray)
        if int(ordered[6349]) + int(ordered[6350]) - int(ordered[705]) - int(ordered[706]) <= 72:
            return 3
    for a, b in zip(images, images[1:]):
        delta = b.astype(np.int16) - a.astype(np.int16)
        residual2 = 0
        for channel in delta:
            ordered = np.sort(channel.reshape(-1)); center2 = int(ordered[3527]) + int(ordered[3528])
            residual2 += int(np.abs(channel.astype(np.int32)*2 - center2).sum())
        if residual2 * 2 >= 21168:
            return 0
    return 2


def audit(run):
    run = Path(run); result = json.loads((run / 'result.json').read_text())
    if (result.get('visualStopEnabled') is not True or result.get('handoff') is not False
            or result.get('stopCommandAcknowledged') is not True or result.get('outcome') != 'unverified'
            or result.get('visualStopReason') not in (2, 3)):
        raise ValueError('not a completed visual-stop-only result')
    if result.get('traceSHA256') != sha(run / 'trace.jsonl'):
        raise ValueError('trace differs from result')
    with (run / 'physical-agent.jsonl').open() as stream:
        rows = [json.loads(line) for line in stream]
    if not rows or [r.get('sequence') for r in rows] != list(range(1, len(rows)+1)):
        raise ValueError('missing or unordered observations')
    end = rows[-1]
    if end.get('owner') != 2 or end.get('ack') != 7 or end.get('driveCommand') != [0, 0, 90]:
        raise ValueError('no valid simulated stop acknowledgment')
    names = []
    for path in (run / 'actors').glob('visual-*.rgb'):
        match = re.fullmatch(r'visual-(\d+)\.rgb', path.name)
        if not match: raise ValueError('invalid visual file name')
        names.append(int(match.group(1)))
    names.sort(); actions = result.get('policyActions')
    if type(actions) is not int or actions < 9 or names != list(range(1, actions+2)) or len(rows) != actions+2:
        raise ValueError('incomplete or unexpected observation history')
    images = []; ticks = []; speeds = []
    for i, seq in enumerate(names):
        row = rows[seq-1]; tick = row.get('totalSteps')
        if (type(tick) is not int or tick < 0 or row.get('owner') != 0 or row.get('imageValid') is not True
                or row.get('cameraDriving') is not True or row.get('cameraStill') is not True or row.get('cameraFrame') != tick):
            raise ValueError('invalid camera observation')
        if i and (row.get('ack') != 1 or tick != ticks[-1]+10):
            raise ValueError('unacknowledged or stale drive')
        raw = (run / 'actors' / f'visual-{seq}.rgb').read_bytes()
        if len(raw) != 21168: raise ValueError('invalid visual image size')
        if i < actions:
            if (run / 'actors' / f'actor-{seq}.rgb').read_bytes() != raw:
                raise ValueError('recorded policy and detector images differ')
            action = (run / 'actors' / f'actor-{seq}.action').read_bytes()
            if len(action) != 8: raise ValueError('invalid action size')
            steering, speed = struct.unpack('<2f', action)
            if not all(math.isfinite(v) and abs(v) <= 1 for v in (steering, speed)):
                raise ValueError('invalid policy action')
            # The native client's conversion rounds the float to thousandths.
            s, v = round(steering*1000), round(speed*1000)
            throttle = math.trunc(v*60/1000) if abs(v) >= 80 else 0
            drive = [throttle, throttle, 90+math.trunc(math.trunc(s/10)*45/100)]
            if rows[seq].get('driveCommand') != drive:
                raise ValueError('drive echo differs from policy command')
            speeds.append(v)
        images.append(np.frombuffer(raw, dtype=np.uint8).reshape(3,84,84)); ticks.append(tick)
    first = None
    for end_index in range(9, len(images)):
        if any(abs(v) < 80 for v in speeds[end_index-9:end_index]):
            continue
        reason = classify(images[end_index-9:end_index+1])
        if reason:
            first = (end_index, reason); break
    if first != (len(images)-1, result['visualStopReason']):
        raise ValueError('reported stop does not match first eligible visual window')
    return {'status': 'verified_simulated_stop_record', 'reason': result['visualStopReason'],
            'startTick': ticks[-10], 'endTick': ticks[-1], 'policyActions': actions,
            'traceSHA256': sha(run / 'trace.jsonl'), 'journalSHA256': sha(run / 'physical-agent.jsonl'),
            'scope': 'reconstructed actor images and command echoes, plus simulated stop ack; no independent camera authenticity, hardware stop, or obstruction proof'}


if __name__ == '__main__':
    if len(sys.argv) != 2: raise SystemExit(__doc__)
    try:
        print(json.dumps(audit(Path(sys.argv[1])), sort_keys=True))
    except (OSError, KeyError, ValueError, TypeError, struct.error) as error:
        raise SystemExit(f'Invalid simulated visual stop: {error}')
