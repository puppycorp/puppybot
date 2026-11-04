#!/usr/bin/env python3
"""Measure first level-5 room entry and pickup from complete saved games.

Usage: l5-first-room.py PLAYER_DIR
The partition-side test uses simulator truth only for offline scoring. It is
not an actor input or a complete geometric doorway/collision test.
"""
import glob
import json
import math
import struct
import sys
from collections import defaultdict
from pathlib import Path


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    groups = defaultdict(lambda: {'games': 0, 'entered': 0, 'firstPickup': 0, 'gamesWithDelivery': 0,
                                   'enteredWithoutPickup': 0, 'noPickupWithinOneMetre': 0})
    seeds = set()
    for file in glob.glob(sys.argv[1] + '/**/result.json', recursive=True):
        game = Path(file).parent
        result = json.loads(Path(file).read_text())
        seed = result['seed']
        if seed in seeds or result.get('level') != 5 or result.get('levelPlacement') != 'other room' or result.get('steps') != 300 or result.get('blackout') is not False:
            raise ValueError(f'duplicate or invalid level-5 game: {game}')
        seeds.add(seed)
        data = (game / 'scene/environment.bin').read_bytes()
        count = struct.unpack_from('<q', data, 8)[0]
        walls = {struct.unpack_from('<d', data, 256 + i * 128 + 48)[0] for i in range(count)
                 if data[256 + i * 128:].startswith(b'Wall.partition')}
        if len(walls) != 1:
            raise ValueError(f'expected a single partition plane: {game}')
        wall = next(iter(walls))
        with (game / 'chase.jsonl').open() as f:
            start = json.loads(f.readline())
        if start['event'] != 'start':
            raise ValueError(f'missing start: {game}')
        side = start['brick'][0] > wall
        if side == (start['robot'][0] > wall):
            raise ValueError(f'initial brick is not in the other room: {game}')
        with (game / 'decisions.jsonl').open() as f:
            states = [json.loads(line)['state'] for line in f]
        if len(states) != 300:
            raise ValueError(f'incomplete decisions: {game}')
        entered = any((state['pose'][0] > wall) == side for state in states)
        pickup = next((i for i, state in enumerate(states) if state['findReturn']['phase'] == 'return'), None)
        search = states[:pickup] if pickup is not None else states
        distance = min(math.dist(state['pose'][:2], state['ball'][:2]) for state in search) if search else 0
        row = groups[f'{wall:.3f}']; row['games'] += 1; row['entered'] += entered
        row['firstPickup'] += pickup is not None; row['gamesWithDelivery'] += result['deliveries'] > 0
        row['enteredWithoutPickup'] += entered and pickup is None
        row['noPickupWithinOneMetre'] += pickup is None and distance >= 1
    if not seeds:
        raise ValueError('no games found')
    total = {key: sum(row[key] for row in groups.values()) for key in next(iter(groups.values()))}
    print(json.dumps({'scope': 'offline simulator-truth diagnostic; split by partition x in metres',
                      'total': total, 'byPartitionX': dict(sorted(groups.items())), 'seeds': sorted(seeds)}, sort_keys=True))


if __name__ == '__main__':
    main()
