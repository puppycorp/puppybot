#!/usr/bin/env python3
"""Inclusive-final-window variant of the provisional held-out saved-game audit.

Usage: audit-heldout-inclusive.py HOLDOUT_CATALOG MODEL EVALUATION_DIR

A future registration must pin this file as well as the original auditor. The
original remains available for archived legacy scores. No held-out runner is
enabled by this module.
"""
import importlib.util
import contextlib
import io
import json
import math
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('heldout_legacy', HERE / 'audit-heldout.py')
legacy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(legacy)
METRIC = 'pose20-final-inclusive-v2'
_original_load_games = legacy.load_games


def backforth_steps(rows, start):
    poses = [start] + [row['state']['pose'] for row in rows]
    drive = []
    for row in rows:
        action = row['action']
        if len(action) != 2 or any(isinstance(x, bool) or not isinstance(x, (int, float)) or
                                   not math.isfinite(x) for x in action):
            raise ValueError('invalid action in decisions')
        drive.append((action[1] > 0) - (action[1] < 0))
    if any(len(pose) != 3 or any(isinstance(x, bool) or not isinstance(x, (int, float)) or
                                 not math.isfinite(x) for x in pose) for pose in poses):
        raise ValueError('invalid pose in decisions')
    steps, marked = 0, -1
    for t in range(20, len(rows) + 1):
        flips = sum(drive[k] * drive[k - 1] < 0 for k in range(t - 19, t))
        turn = abs((poses[t][2] - poses[t - 20][2] + math.pi) % (2 * math.pi) - math.pi)
        if flips >= 4 and math.dist(poses[t][:2], poses[t - 20][:2]) < 0.25 and turn < math.radians(45):
            steps += t - max(marked, t - 20)
            marked = t
    return steps


def validate_games(games):
    for seed, (result, rows, events, directory) in games.items():
        count = result.get('backForthSteps')
        if (result.get('backForthMetric') != METRIC or type(count) is not int or
                count < 0 or count > len(rows) or count != backforth_steps(rows, events[0]['robot'])):
            raise ValueError(f'missing or invalid inclusive back-and-forth metric: {directory} seed {seed}')
    return games


def load_games(root, expected, model, level, helpers):
    # The legacy reader validates model candidates using its own function;
    # substitute the inclusive implementation before invoking it. Then also
    # validate teacher counts, which the legacy reader did not check.
    original = legacy.backforth_steps
    legacy.backforth_steps = backforth_steps
    try:
        games = _original_load_games(root, expected, model, level, helpers)
    finally:
        legacy.backforth_steps = original
    return validate_games(games)


def main():
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    output = Path(sys.argv[3])
    # This wrapper changes the verifier, so its source must be registered
    # before play alongside every source already required by the old auditor.
    legacy.require_pinned(legacy.input_hashes(output / 'inputs.sha256'), Path(__file__))
    original = legacy.load_games
    legacy.load_games = load_games
    try:
        output_stream = io.StringIO()
        with contextlib.redirect_stdout(output_stream):
            legacy.main()
    finally:
        legacy.load_games = original
    report = json.loads(output_stream.getvalue())
    report['backForthMetric'] = METRIC
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError) as error:
        raise SystemExit(f'Invalid inclusive held-out comparison: {error}')
