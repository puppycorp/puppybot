#!/usr/bin/env python3
"""Offline image-only stagnation candidate for recorded physical-client actions.

Usage: visual-stagnation.py PHYSICAL_CLIENT_RUN_DIRECTORY

This experimental detector uses only recorded actor RGB/action files and the
client's own camera timestamps. Ten frames are required; all nine intervening
commands must request drive and every image pair must remain nearly unchanged
after per-channel additive brightness correction. Low-texture frames and
nonconsecutive timestamps are explicitly unreliable. A stagnant image is not
proof that the robot is blocked, nor permission to move a physical robot.
Thresholds are exploratory, tuned against one simulated selection trace.
"""
import hashlib
import json
import math
import re
import struct
import sys
from pathlib import Path

import numpy as np


WINDOW = 10
MIN_TEXTURE = 12.0  # grayscale p90-p10, measured on 0..255 actor pixels
MAX_RESIDUAL = 0.25  # mean absolute RGB difference, after brightness offset
MIN_COMMAND_MILLI = 80  # rounded model speed magnitude, as in the action deadband


def classify(images, speeds, ticks):
    images = np.asarray(images)
    if images.shape != (WINDOW, 3, 84, 84) or images.dtype != np.uint8:
        raise ValueError('expected ten 84x84 NCHW uint8 actor images')
    if (len(speeds) != WINDOW - 1 or len(ticks) != WINDOW or
            not all(math.isfinite(v) and abs(v) <= 1 for v in speeds) or
            not all(type(t) is int and t >= 0 for t in ticks)):
        raise ValueError('invalid action or camera timestamps')
    if any(b - a != 10 for a, b in zip(ticks, ticks[1:])):
        return {'state': 'unreliable_timing'}
    if any(abs(round(v * 1000)) < MIN_COMMAND_MILLI for v in speeds):
        return {'state': 'not_continuously_commanded'}
    gray = images.astype(np.float32).mean(axis=1)
    texture = [float(np.percentile(frame, 90) - np.percentile(frame, 10)) for frame in gray]
    if min(texture) < MIN_TEXTURE:
        return {'state': 'unreliable_texture', 'minTexture': min(texture)}
    scores = []
    for first, second in zip(images, images[1:]):
        difference = second.astype(np.int16) - first.astype(np.int16)
        offsets = np.median(difference, axis=(1, 2))[:, None, None]
        scores.append(float(np.abs(difference - offsets).mean()))
    return {'state': 'visual_stagnation' if max(scores) < MAX_RESIDUAL else 'no_evidence',
            'maxResidual': max(scores), 'minTexture': min(texture)}


def load(run):
    rows = [json.loads(line) for line in (run / 'physical-agent.jsonl').read_text().splitlines()]
    if not rows or [row['sequence'] for row in rows] != list(range(1, len(rows) + 1)):
        raise ValueError('missing or unordered client observations')
    by_sequence = {row['sequence']: row for row in rows}
    actors = run / 'actors'; names = []
    for path in actors.glob('actor-*.rgb'):
        match = re.fullmatch(r'actor-(\d+)\.rgb', path.name)
        if not match:
            raise ValueError(f'invalid actor filename: {path}')
        names.append(int(match.group(1)))
    frames, speeds, ticks = [], [], []
    for seq in sorted(names):
        row = by_sequence.get(seq)
        applied = by_sequence.get(seq + 1)
        if (not row or row['owner'] != 0 or not row['imageValid'] or not row['cameraDriving'] or
                not row['cameraStill'] or row['cameraFrame'] != row['totalSteps']):
            raise ValueError(f'actor image lacks a valid navigation observation: {seq}')
        if not applied or applied['ack'] != 1 or applied['owner'] != 0 or applied['totalSteps'] != row['totalSteps'] + 10:
            raise ValueError(f'actor action was not acknowledged after ten ticks: {seq}')
        rgb = (actors / f'actor-{seq}.rgb').read_bytes(); action = (actors / f'actor-{seq}.action').read_bytes()
        if len(rgb) != 3 * 84 * 84 or len(action) != 8:
            raise ValueError(f'incomplete actor recording: {seq}')
        steering, speed = struct.unpack('<2f', action)
        if not all(math.isfinite(v) and abs(v) <= 1 for v in (steering, speed)):
            raise ValueError(f'invalid action: {seq}')
        s, v = round(steering * 1000), round(speed * 1000)
        throttle = math.trunc(v * 60 / 1000) if abs(v) >= MIN_COMMAND_MILLI else 0
        expected_drive = [throttle, throttle, 90 + math.trunc(math.trunc(s / 10) * 45 / 100)]
        if applied['driveCommand'] != expected_drive:
            raise ValueError(f'acknowledged drive differs from actor command: {seq}')
        frames.append(np.frombuffer(rgb, dtype=np.uint8).reshape(3, 84, 84)); speeds.append(speed); ticks.append(row['totalSteps'])
    if len(frames) < WINDOW:
        raise ValueError('not enough recorded actor frames')
    return sorted(names), frames, speeds, ticks


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    run = Path(sys.argv[1]); names, frames, speeds, ticks = load(run)
    windows = []
    for i in range(len(frames) - WINDOW + 1):
        entry = classify(frames[i:i + WINDOW], speeds[i:i + WINDOW - 1], ticks[i:i + WINDOW])
        entry.update(startSequence=names[i], endSequence=names[i + WINDOW - 1],
                     startTick=ticks[i], endTick=ticks[i + WINDOW - 1])
        windows.append(entry)
    digest = hashlib.sha256()
    for seq in names:
        for extension in ('rgb', 'action'):
            name = f'actor-{seq}.{extension}'
            digest.update(name.encode() + b'\0' + hashlib.sha256((run / 'actors' / name).read_bytes()).digest())
    inputs = {'actorFilesSHA256': digest.hexdigest(),
              'journalSHA256': hashlib.sha256((run / 'physical-agent.jsonl').read_bytes()).hexdigest(),
              'detectorSHA256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    print(json.dumps({'status': 'diagnostic_only', 'actorFrames': len(frames), 'inputs': inputs,
                      'thresholds': {'windowFrames': WINDOW, 'maxResidual': MAX_RESIDUAL,
                                     'minTexture': MIN_TEXTURE, 'minCommandMilli': MIN_COMMAND_MILLI},
                      'scope': 'actor pixels/actions and camera timestamps only; no simulator truth, no automatic recovery',
                      'windows': windows}, indent=2))


if __name__ == '__main__':
    main()
