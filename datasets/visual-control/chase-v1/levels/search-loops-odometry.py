#!/usr/bin/env python3
"""Measure candidate long search loops using the recorded wheel odometry.

Usage: search-loops-odometry.py GAME_ROOT [GAME_ROOT ...]

A loop is a 50-action search window ending within 0.4 m and 45 degrees of
its start after travelling at least 0.75 m. Adjacent flagged windows are
unioned, so shares do not double-count. These thresholds are a diagnostic,
not evidence that an automatic recovery action is safe or effective.
"""

import glob
import json
import math
import sys
from pathlib import Path

WINDOW = 50
DISTANCE = 0.4
ANGLE = math.pi / 4
PATH = 0.75


def flags(poses, search):
    marked = set()
    windows = 0
    for end in range(WINDOW, len(poses)):
        begin = end - WINDOW
        if not all(search[begin:end + 1]):
            continue
        first, last = poses[begin], poses[end]
        displacement = math.dist(first[:2], last[:2])
        heading = abs(math.atan2(math.sin(last[2] - first[2]), math.cos(last[2] - first[2])))
        traveled = sum(math.dist(poses[i - 1][:2], poses[i][:2]) for i in range(begin + 1, end + 1))
        if displacement < DISTANCE and heading < ANGLE and traveled >= PATH:
            windows += 1
            marked.update(range(begin, end))
    return marked, windows


def measure(path):
    result = json.loads((path.parent / 'result.json').read_text())
    with path.open() as f:
        states = [json.loads(line)['state'] for line in f]
    if len(states) != result['steps']:
        raise ValueError(f'incomplete game: {path}')
    poses = []
    search = []
    for state in states:
        localization = state.get('localization', {})
        pose = localization.get('pose')
        if localization.get('mode') != 'wheel-drift' or not isinstance(pose, list) or len(pose) != 3 or not all(isinstance(x, (int, float)) and math.isfinite(x) for x in pose):
            raise ValueError(f'missing or invalid wheel odometry: {path}')
        poses.append(pose)
        search.append(state['findReturn']['phase'] == 'search')
    estimated, windows = flags(poses, search)
    truth, _ = flags([state['pose'] for state in states], search)
    return result['seed'], len(states), sum(search), len(estimated), windows, len(truth), len(estimated & truth), len(estimated - truth), len(truth - estimated)


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    for root in sys.argv[1:]:
        paths = sorted(Path(p) for p in glob.glob(f'{root}/**/decisions.jsonl', recursive=True))
        if not paths:
            raise ValueError(f'no games: {root}')
        games = [measure(p) for p in paths]
        if len({g[0] for g in games}) != len(games):
            raise ValueError(f'duplicate seeds: {root}')
        search_steps = sum(g[2] for g in games)
        loop_steps = sum(g[3] for g in games)
        print(json.dumps({'root': root, 'games': len(games), 'window': WINDOW,
                          'searchSteps': search_steps, 'loopSteps': loop_steps,
                          'loopShareOfSearch': loop_steps / search_steps if search_steps else None,
                          'gamesWithLoop': sum(g[3] > 0 for g in games),
                          'truthLoopSteps': sum(g[5] for g in games),
                          'overlapSteps': sum(g[6] for g in games),
                          'odometryOnlySteps': sum(g[7] for g in games),
                          'truthOnlySteps': sum(g[8] for g in games),
                          'seedsWithLoops': [g[0] for g in games if g[3] > 0]}, sort_keys=True))


if __name__ == '__main__':
    main()
