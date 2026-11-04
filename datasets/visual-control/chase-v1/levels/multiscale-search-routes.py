#!/usr/bin/env python3
"""Exploratory offline closed-route diagnostics; never a recovery controller."""
import json
import math
import sys
from pathlib import Path

# Fixed before evaluating the motivating saved route. Each window measures
# displacement, not final heading; a deliberate return can also be flagged.
WINDOWS = (100, 150, 200, 250)
MAX_DISPLACEMENT_M = .75
MIN_PATH_M = 2.0
MAX_DISPLACEMENT_PATH_RATIO = .20


def vector(value):
    if (not isinstance(value, list) or len(value) < 3 or
            any(type(x) not in (int, float) or not math.isfinite(x) for x in value[:3])):
        raise ValueError('invalid recorded pose')
    return value[:3]


def action_ranges(marked):
    ranges = []
    for index in sorted(marked):
        action = index + 1
        if ranges and ranges[-1][1] + 1 == action:
            ranges[-1][1] = action
        else:
            ranges.append([action, action])
    return ranges


def analyze(poses, search):
    if len(poses) != len(search): raise ValueError('pose and phase lengths differ')
    poses = [vector(pose) for pose in poses]
    if any(type(flag) is not bool for flag in search): raise ValueError('invalid search flag')
    distance = [0.0]
    for left, right in zip(poses, poses[1:]):
        distance.append(distance[-1] + math.dist(left[:2], right[:2]))
    nonsearch = [0]
    for flag in search: nonsearch.append(nonsearch[-1] + int(not flag))
    all_marked = set(); result = {}
    for window in WINDOWS:
        marked = set(); hits = 0; example = None
        for end in range(window, len(poses)):
            begin = end - window
            if nonsearch[end + 1] != nonsearch[begin]: continue
            traveled = distance[end] - distance[begin]
            displacement = math.dist(poses[begin][:2], poses[end][:2])
            if traveled >= MIN_PATH_M and displacement <= MAX_DISPLACEMENT_M and displacement / traveled <= MAX_DISPLACEMENT_PATH_RATIO:
                # A displacement between post-action states belongs to the
                # actions after the first pose, through the last pose.
                hits += 1; marked.update(range(begin + 1, end + 1))
                candidate = {'firstPoseAction': begin + 1, 'lastPoseAction': end + 1,
                             'pathM': traveled, 'displacementM': displacement}
                if example is None or traveled > example['pathM']: example = candidate
        all_marked.update(marked)
        result[str(window)] = {'matchingWindows': hits, 'markedActions': len(marked),
                               'markedActionRanges': action_ranges(marked), 'example': example}
    return {'byWindow': result, 'unionMarkedActions': len(all_marked), 'unionActionRanges': action_ranges(all_marked)}


def game(directory):
    directory = Path(directory)
    result = json.loads((directory / 'result.json').read_text())
    rows = [json.loads(line) for line in (directory / 'decisions.jsonl').read_text().splitlines()]
    if (type(result.get('seed')) is not int or type(result.get('steps')) is not int or
            result['steps'] != len(rows) or not rows): raise ValueError('incomplete recorded game')
    if (any(type(row.get('step')) is not int for row in rows) or
            any(b['step'] != a['step'] + 10 for a, b in zip(rows, rows[1:]))):
        raise ValueError('nonconsecutive saved action states')
    estimated = []; truth = []; search = []
    for row in rows:
        state = row['state']; localization = state.get('localization', {})
        if localization.get('mode') != 'wheel-drift': raise ValueError('wheel odometry missing')
        estimated.append(vector(localization.get('pose'))); truth.append(vector(state.get('pose')))
        phase = state['findReturn'].get('phase')
        if phase not in ('search', 'return', 'delivered', 'docked'): raise ValueError('unknown phase')
        search.append(phase == 'search')
    return {'seed': result['seed'], 'steps': len(rows), 'searchActions': sum(search),
            'thresholds': {'windowsActions': list(WINDOWS), 'maximumDisplacementM': MAX_DISPLACEMENT_M,
                           'minimumPathM': MIN_PATH_M, 'maximumDisplacementPathRatio': MAX_DISPLACEMENT_PATH_RATIO},
            'wheelOdometry': analyze(estimated, search), 'simulatorTruth': analyze(truth, search),
            'scope': 'exploratory position-only closed-route windows in virtual search; a flag can be deliberate, a zero can miss longer or non-closing loops; simulator truth is offline comparison, not actor input or physical proof'}


def main():
    if len(sys.argv) != 2: raise SystemExit('usage: multiscale-search-routes.py SAVED_GAME_DIRECTORY')
    print(json.dumps(game(sys.argv[1]), sort_keys=True, allow_nan=False))


if __name__ == '__main__': main()
