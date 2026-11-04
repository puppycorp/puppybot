#!/usr/bin/env python3
"""Fail-closed paired audit for 32 single-policy selection games.

Usage: audit-selection.py LEVEL BASELINE_DIR BASELINE_MODEL STUDENT_DIR STUDENT_MODEL

This verifies the saved runs and snapshots, not whether the selected layouts
or model ancestry are independent. It does not establish simulator identity:
capture and verify a separate simulator binary manifest around the evaluation.
"""
import hashlib
import json
import math
import os
import re
import sys
from pathlib import Path

BASE = 7800000
GAMES = 32
STEPS = 300


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(snapshot, model):
    model_receipt = model / 'receipt.json'
    receipt = json.loads(model_receipt.read_text())
    if (snapshot / 'receipt.json').read_bytes() != model_receipt.read_bytes():
        raise ValueError(f'{snapshot}: receipt differs from current model')
    files = [('weights.bin', receipt['weightsSHA256']), ('policy', receipt['binarySHA256'])]
    kernels = receipt.get('kernels')
    if not isinstance(kernels, dict) or not kernels:
        raise ValueError(f'{snapshot}: missing kernel manifest')
    for name, checksum in kernels.items():
        if Path(name).name != name:
            raise ValueError(f'{snapshot}: invalid kernel name')
        files.append(('kernels/' + name, checksum))
    for name, checksum in files:
        if digest(snapshot / name) != checksum or digest(model / name) != checksum:
            raise ValueError(f'{snapshot}: mismatch for {name}')
    return receipt['weightsSHA256']


def load(root, model, level):
    if not root.is_dir():
        raise ValueError(f'missing player directory: {root}')
    results = sorted(root.glob('*/[0-9]*/result.json'))
    games = {}
    checked_parts = {}
    for file in results:
        directory = file.parent
        part = directory.parent
        if part not in checked_parts:
            checked_parts[part] = snapshot(part / 'policy', model)
            for log in (root / (part.name + '.log'), part / 'policy.log'):
                if not log.is_file():
                    raise ValueError(f'missing log: {log}')
                if re.search(r'\btimed out\b|\btimeout\b', log.read_text(errors='replace'), re.I):
                    raise ValueError(f'timeout recorded in {log}')
        r = json.loads(file.read_text())
        seed = r['seed']
        if seed in games or r['steps'] != STEPS or r['actionSeconds'] != 60 or r['level'] != level or r['blackout'] is not False:
            raise ValueError(f'duplicate or invalid game: {directory}')
        if r.get('policyWeightsSHA256') != checked_parts[part] or r.get('ensembleMembers', 1) != 1:
            raise ValueError(f'wrong policy: {directory}')
        if level == 4 and r.get('levelPlacement') != 'doorway drill':
            raise ValueError(f'wrong level placement: {directory}')
        with (directory / 'decisions.jsonl').open() as f:
            rows = [json.loads(line) for line in f]
        events = [json.loads(line) for line in (directory / 'chase.jsonl').read_text().splitlines()]
        if len(rows) != STEPS or not events or events[0]['event'] != 'start':
            raise ValueError(f'incomplete traces: {directory}')
        if sum(event['event'] == 'delivery' for event in events) != r['deliveries']:
            raise ValueError(f'delivery count mismatch: {directory}')
        native = directory / 'native.log'
        if not native.is_file() or re.search(r'\btimed out\b|\btimeout\b', native.read_text(errors='replace'), re.I):
            raise ValueError(f'missing native log or timeout: {directory}')
        scene = tuple(digest(directory / 'scene' / name) for name in ('case.json', 'environment.bin'))
        g = seed - BASE
        if g < 0 or g >= GAMES:
            raise ValueError(f'unexpected seed: {seed}')
        layout = 12 + g % 6 if level < 4 else 13 + 2 * (g % 3)
        source = Path(os.environ.get('PUPPYBOT_PROJECT', '.')) / 'build/flex/sim/expanded-rooms-v1/scenes' / str(layout) / str(g % 16)
        expected = tuple(digest(source / name) for name in ('case.json', 'environment.bin'))
        if scene != expected:
            raise ValueError(f'{directory}: scene does not match selection catalog')
        games[seed] = (r, rows, events[0], scene)
    if set(games) != set(range(BASE, BASE + GAMES)):
        raise ValueError(f'{root}: expected seeds {BASE} through {BASE + GAMES - 1}')
    return games


def summary(games):
    results = [g[0] for g in games.values()]
    if any('backForthSteps' not in r for r in results):
        raise ValueError('missing back-and-forth metric')
    return {'games': len(results), 'deliveriesPerMinute': sum(r['deliveries'] for r in results) / GAMES,
            'gamesWithDelivery': sum(r['deliveries'] > 0 for r in results),
            'firstReturnGames': sum(any(row['state']['findReturn']['phase'] == 'return' for row in g[1]) for g in games.values()),
            'backForthShare': sum(r['backForthSteps'] for r in results) / (GAMES * STEPS),
            'gamesMostlyBackForth': sum(r['backForthSteps'] * 5 > STEPS for r in results)}


def check_score(root, expected):
    score = json.loads((root.parent / ('score-' + root.name + '.json')).read_text())
    for key, observed in [('games', 'games'), ('meanDeliveriesPerMinute', 'deliveriesPerMinute'),
                          ('gamesWithADelivery', 'gamesWithDelivery'), ('meanBackForthShare', 'backForthShare'),
                          ('gamesMostlyBackForth', 'gamesMostlyBackForth')]:
        if key not in score or not math.isclose(score[key], expected[observed], abs_tol=1e-12):
            raise ValueError(f'{root}: saved score mismatch: {key}')


def main():
    if len(sys.argv) != 6:
        raise SystemExit(__doc__)
    level = int(sys.argv[1])
    if level not in (1, 3, 4, 5):
        raise ValueError('expected selection level 1, 3, 4, or 5')
    left_root, left_model, right_root, right_model = map(Path, sys.argv[2:])
    left, right = load(left_root, left_model, level), load(right_root, right_model, level)
    for seed in left:
        if left[seed][2:] != right[seed][2:] or left[seed][0].get('levelPlacement') != right[seed][0].get('levelPlacement'):
            raise ValueError(f'unmatched scene, start or level placement: {seed}')
    a, b = summary(left), summary(right)
    check_score(left_root, a)
    check_score(right_root, b)
    print(json.dumps({'status': 'paired selection audit passed', 'level': level, 'seeds': [BASE, BASE + GAMES - 1],
                      'baseline': a, 'student': b,
                      'scope': 'training layouts; simulator identity and pretrained ancestry require separate proof'}, sort_keys=True))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        raise SystemExit(f'Invalid selection: {error}')
