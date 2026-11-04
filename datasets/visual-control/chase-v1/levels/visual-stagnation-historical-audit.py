#!/usr/bin/env python3
"""Audit fixed image-stagnation thresholds on a complete historical shard.

Usage: visual-stagnation-historical-audit.py SHARD_DIRECTORY

Uses all student-driven games in the shard. Actor images/actions are scored
without simulator truth. Separately, a post-run diagnostic compares windows
with recorded simulator poses. This is an older virtual-chase training corpus,
not a held-out test, physical robot validation or evidence of safe recovery.
"""
import collections
import hashlib
import importlib.util
import json
import math
import struct
import sys
from pathlib import Path

import numpy as np


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def stationary_delay_ticks(poses, lower, end):
    """Retrospective stable-pose duration relative to the endpoint, in ticks."""
    if lower > end or end not in poses:
        raise ValueError('invalid stationary-onset range')
    anchor = poses[end]; onset = end
    while onset > lower:
        p = poses.get(onset - 1)
        if p is None:
            raise ValueError('missing trace tick while measuring stationary onset')
        angle = abs((p[2] - anchor[2] + math.pi) % (2 * math.pi) - math.pi)
        if math.dist(anchor[:2], p[:2]) >= .01 or angle >= math.radians(2):
            break
        onset -= 1
    return end - onset


def load_game(path, detector):
    result = json.loads((path / 'result.json').read_text())
    if result.get('blackout') is not False or result.get('game') != 'chase' or result.get('steps') != 300:
        raise ValueError(f'unexpected game, horizon or blackout: {path}')
    decision_path = path / 'decisions.jsonl'
    rows = [json.loads(line) for line in decision_path.open()]
    if len(rows) != 300:
        raise ValueError(f'incomplete action journal: {path}')
    images, speeds, ticks = [], [], []
    input_hash = hashlib.sha256()
    for row in rows:
        tick, state = row['step'], row['state']
        action = row['action']; camera = state['camera']; perception = state['case']['perception']
        if (type(tick) is not int or tick < 0 or state['totalSteps'] != tick or
                camera['pose'] != 'driving' or not camera['armSettled'] or perception['frameId'] != tick):
            raise ValueError(f'stale camera or timing: {path}, {tick}')
        if len(action) != 2 or not all(type(v) in (int, float) and math.isfinite(v) and abs(v) <= 1 for v in action):
            raise ValueError(f'invalid action: {path}, {tick}')
        steering, speed = action; s, v = round(steering * 1000), round(speed * 1000)
        throttle = math.trunc(v * 60 / 1000) if abs(v) >= detector.MIN_COMMAND_MILLI else 0
        expected = 90 + math.trunc(math.trunc(s / 10) * 45 / 100)
        drive = state['controller']['drive']; angle = drive['steeringAngleDeg']
        completed_stop = bool(state['case'].get('passed')) and not throttle and angle == 90
        if drive['leftSpeed'] != throttle or drive['rightSpeed'] != throttle or (angle != expected and not completed_stop):
            raise ValueError(f'action/drive mismatch: {path}, {tick}')
        image_path = path / f'actor-{tick}.rgb'; image = image_path.read_bytes()
        if len(image) != 21168 or hashlib.sha256(image).hexdigest() != row.get('actorSHA256'):
            raise ValueError(f'actor image hash mismatch: {image_path}')
        input_hash.update(str(tick).encode() + b'\0' + hashlib.sha256(image).digest() + struct.pack('<2f', *action))
        images.append(np.frombuffer(image, dtype=np.uint8).reshape(3, 84, 84)); speeds.append(speed); ticks.append(tick)
    if any(b - a != 10 for a, b in zip(ticks, ticks[1:])):
        raise ValueError(f'nonconsecutive action observations: {path}')
    poses = {}; trace_hash = hashlib.sha256()
    with (path / 'trace.jsonl').open('rb') as stream:
        for line in stream:
            trace_hash.update(line); state = json.loads(line); tick = state['totalSteps']; pose = state['pose']
            if (type(tick) is not int or tick < 0 or not isinstance(pose, list) or len(pose) != 3 or
                    not all(type(v) in (int, float) and math.isfinite(v) for v in pose)):
                raise ValueError(f'invalid trace tick or pose: {path}')
            if tick in poses:
                raise ValueError(f'duplicate trace tick: {path}, {tick}')
            poses[tick] = pose
    for row in rows:
        if poses.get(row['step']) != row['state']['pose']:
            raise ValueError(f'decision and trace pose mismatch: {path}, {row["step"]}')
    # Actor image at t is the observation after that step; the action in the
    # *next* decision advances it toward the next recorded image.
    gray = np.stack(images).astype(np.float32).mean(axis=1)
    texture = [float(np.percentile(frame, 90) - np.percentile(frame, 10)) for frame in gray]
    residual = []
    for a, b in zip(images, images[1:]):
        diff = b.astype(np.int16) - a.astype(np.int16)
        residual.append(float(np.abs(diff - np.median(diff, axis=(1, 2))[:, None, None]).mean()))
    counts = collections.Counter(); abstention_truth = collections.Counter()
    first_flag = None; first_flag_end = None; first_flag_stationary_delay = None
    for i in range(len(images) - detector.WINDOW + 1):
        command = speeds[i + 1:i + detector.WINDOW]
        if any(abs(round(v * 1000)) < detector.MIN_COMMAND_MILLI for v in command):
            state = 'not_continuously_commanded'
        elif min(texture[i:i + detector.WINDOW]) < detector.MIN_TEXTURE:
            state = 'unreliable_texture'
        else:
            state = 'visual_stagnation' if max(residual[i:i + detector.WINDOW - 1]) < detector.MAX_RESIDUAL else 'no_evidence'
        # Cross-check the optimized, per-frame calculation against the actual
        # fixed detector on deterministic positions, without choosing by score.
        if i in (0, (len(images) - detector.WINDOW) // 2, len(images) - detector.WINDOW):
            reference = detector.classify(images[i:i + detector.WINDOW], command, ticks[i:i + detector.WINDOW])
            if reference['state'] != state:
                raise ValueError(f'detector calculation mismatch: {path}, {i}')
        start, end = ticks[i], ticks[i + detector.WINDOW - 1]
        try:
            segment = [poses[t] for t in range(start, end + 1)]
        except KeyError as e:
            raise ValueError(f'missing trace tick: {path}') from e
        origin = segment[0]
        distance = max(math.dist(origin[:2], p[:2]) for p in segment)
        rotation = max(abs((p[2] - origin[2] + math.pi) % (2 * math.pi) - math.pi) for p in segment)
        still = distance < .01 and rotation < math.radians(2)
        if state == 'visual_stagnation':
            counts['stagnantAndStationary' if still else 'stagnantAndMoving'] += 1
            if first_flag is None:
                first_flag, first_flag_end = start, end
                if still:
                    # Retrospective pose-based onset estimate, not an actor
                    # input or proof of physical contact. Compare every prior
                    # tick with the flagged window's final pose.
                    first_flag_stationary_delay = stationary_delay_ticks(poses, ticks[0], end)
        elif state == 'no_evidence':
            counts['noEvidenceAndStationary' if still else 'noEvidenceAndMoving'] += 1
        else:
            counts[state] += 1
            abstention_truth[state + ('AndStationary' if still else 'AndMoving')] += 1
    return {'seed': result['seed'], 'modelWeightsSHA256': result['policyWeightsSHA256'],
            'windows': sum(counts.values()), 'counts': dict(counts), 'abstentionTruth': dict(abstention_truth),
            'firstFlagStartTick': first_flag, 'firstFlagEndTick': first_flag_end,
            'firstFlagStationaryDelayTicks': first_flag_stationary_delay,
            'recordingSHA256': input_hash.hexdigest(), 'decisionSHA256': sha(decision_path),
            'traceSHA256': trace_hash.hexdigest(), 'resultSHA256': sha(path / 'result.json'),
            'sceneCaseSHA256': sha(path / 'scene/case.json'), 'sceneEnvironmentSHA256': sha(path / 'scene/environment.bin')}


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    shard = Path(sys.argv[1]); source = json.loads((shard / 'report.json').read_text())
    if source.get('studentDriven') is not True or source.get('episodes') != 32 or source.get('sequenceLength') != 300:
        raise ValueError('expected a complete 32-game student-driven shard')
    detector_path = Path(__file__).with_name('visual-stagnation.py')
    spec = importlib.util.spec_from_file_location('visual_stagnation', detector_path)
    detector = importlib.util.module_from_spec(spec); spec.loader.exec_module(detector)
    games = [load_game(shard / f'expert-{i}', detector) for i in range(32)]
    if len({game['seed'] for game in games}) != 32 or {game['seed'] for game in games} != set(range(source['seed'], source['seed'] + 32)):
        raise ValueError('shard game seeds differ from its report')
    total, abstention_truth = collections.Counter(), collections.Counter()
    for game in games:
        total.update(game['counts']); abstention_truth.update(game['abstentionTruth'])
    print(json.dumps({'status': 'diagnostic_only', 'games': len(games), 'windows': sum(total.values()), 'counts': dict(total),
                      'abstentionTruth': dict(abstention_truth),
                      'truthStationary': 'within 0.01 m and 2 degrees of the start for every tick in the window',
                      'thresholds': {'windowFrames': detector.WINDOW, 'maxResidual': detector.MAX_RESIDUAL,
                                     'minTexture': detector.MIN_TEXTURE, 'minCommandMilli': detector.MIN_COMMAND_MILLI},
                      'shardReportSHA256': sha(shard / 'report.json'), 'detectorSHA256': sha(detector_path),
                      'auditSHA256': sha(Path(__file__)), 'gamesDetail': games,
                      'timingScope': 'first flag delay is retrospective ticks since the last uninterrupted 1 cm/2 degree pose interval; not necessarily contact onset',
                      'scope': 'historical student-driven virtual-chase training games, not held-out or physical-robot evidence; simulator identity not pinned'}, indent=2))


if __name__ == '__main__':
    main()
