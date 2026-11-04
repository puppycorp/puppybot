#!/usr/bin/env python3
"""Offline search-route coverage for saved virtual fetch games.

Usage: route-coverage.py PLAYER_DIRECTORY
World poses and partition geometry are used only after the run, never as actor
inputs. Counts cover the route through first pickup, or all 300 actions when
there is no pickup. Grid cells are 0.25 m in world axes, not a navigability map.
"""
import hashlib
import json
import math
import struct
import sys
from pathlib import Path


CELL = .25


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def geometry(poses):
    if not poses or any(not isinstance(p, list) or len(p) < 3 or
                        any(type(v) not in (int, float) or not math.isfinite(v) for v in p[:3]) for p in poses):
        raise ValueError('invalid simulator pose')
    cells = [(math.floor(p[0] / CELL), math.floor(p[1] / CELL)) for p in poses]
    seen = {cells[0]}; transitions = revisits = 0
    for previous, current in zip(cells, cells[1:]):
        if current == previous:
            continue
        transitions += 1; revisits += int(current in seen); seen.add(current)
    path = sum(math.dist(a[:2], b[:2]) for a, b in zip(poses, poses[1:]))
    return {'pathM': path, 'netDisplacementM': math.dist(poses[0][:2], poses[-1][:2]),
            'uniqueCells': len(seen), 'cellTransitions': transitions, 'revisitedCellEntries': revisits,
            'revisitedEntryShare': revisits / transitions if transitions else None}


def game(directory):
    result = json.loads((directory / 'result.json').read_text())
    if (result.get('level') != 5 or result.get('levelPlacement') != 'other room' or result.get('steps') != 300
            or result.get('blackout') is not False or result.get('suppliedMap') is not False
            or result.get('taskEventHint') is not False or type(result.get('seed')) is not int):
        raise ValueError(f'invalid game result: {directory}')
    data = (directory / 'scene/environment.bin').read_bytes()
    if len(data) < 256 or data[:8] != b'PBENV001':
        raise ValueError('invalid environment')
    n = struct.unpack_from('<q', data, 8)[0]
    if n < 1 or len(data) < 256 + n * 128:
        raise ValueError('invalid environment collider count')
    wall = {struct.unpack_from('<d', data, 256 + i * 128 + 48)[0] for i in range(n)
            if data[256 + i * 128:256 + i * 128 + 48].startswith(b'Wall.partition')}
    if len(wall) != 1 or not all(math.isfinite(x) for x in wall):
        raise ValueError('ambiguous partition')
    wall = next(iter(wall))
    with (directory / 'chase.jsonl').open() as stream:
        events = [json.loads(line) for line in stream]
    if not events:
        raise ValueError('missing events')
    start = events[0]
    if start.get('event') != 'start':
        raise ValueError('missing start')
    robot, brick = start['robot'], start['brick']
    if (not isinstance(brick, list) or len(brick) < 2 or
            any(type(v) not in (int, float) or not math.isfinite(v) for v in brick[:2])):
        raise ValueError('invalid brick start')
    geometry([robot])
    side = brick[0] > wall
    if (robot[0] > wall) == side:
        raise ValueError('brick not in other room')
    rows = [json.loads(line) for line in (directory / 'decisions.jsonl').read_text().splitlines()]
    if len(rows) != 300:
        raise ValueError('incomplete game')
    states = [row['state'] for row in rows]
    if any(b['step'] != a['step'] + 10 for a, b in zip(rows, rows[1:])):
        raise ValueError('nonconsecutive physical action ticks')
    if (type(result.get('deliveries')) is not int or not 0 <= result['deliveries'] <= 300 or
            type(result.get('backForthSteps')) is not int or not 0 <= result['backForthSteps'] <= 300 or
            sum(e.get('event') == 'delivery' for e in events) != result['deliveries']):
        raise ValueError('delivery events disagree with result')
    if any(s.get('trainingOracle', {}).get('enabled') is not False or s['trainingOracle'].get('queries') != 0 for s in states):
        raise ValueError('oracle instrumentation enabled or queried')
    poses = [robot] + [s['pose'] for s in states]
    geometry(poses)
    entry = next((i + 1 for i, p in enumerate(poses[1:]) if (p[0] > wall) == side), None)
    pickup = next((i + 1 for i, s in enumerate(states) if s['findReturn']['phase'] == 'return'), None)
    end = pickup if pickup is not None else 300
    route = geometry(poses[:end + 1])
    return {'seed': result['seed'], 'partitionX': wall, 'startPose': robot, 'initialBrick': brick,
            'firstEntryAction': entry, 'firstPickupAction': pickup, 'deliveries': result['deliveries'],
            'backForthStepsFullEpisode': result['backForthSteps'], 'searchRoute': route,
            'resultSHA256': digest(directory / 'result.json'), 'decisionsSHA256': digest(directory / 'decisions.jsonl'),
            'startEventsSHA256': digest(directory / 'chase.jsonl'), 'environmentSHA256': digest(directory / 'scene/environment.bin')}


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    root = Path(sys.argv[1]); files = sorted(root.glob('*/[0-9]*/result.json'))
    if not files:
        raise ValueError('no saved games')
    games = [game(p.parent) for p in files]
    if len({g['seed'] for g in games}) != len(games):
        raise ValueError('duplicate game seeds')
    print(json.dumps({'status': 'diagnostic_only', 'cellSizeM': CELL, 'games': games,
                      'scope': 'post-run simulator truth through first pickup, not actor input; repeats are not independent trials'}, sort_keys=True))


if __name__ == '__main__':
    main()
