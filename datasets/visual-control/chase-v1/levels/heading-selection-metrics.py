#!/usr/bin/env python3
"""Post-run virtual-fetch diagnostics from already-audited selection games.

Loop flags are observational, not a validated recovery signal. Pickup here
means the simulator's virtual consumption event, not a physical grasp.
"""
import importlib.util
import json
import math
import struct
from pathlib import Path

S = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('search_loops', S / 'search-loops-odometry.py')
loops = importlib.util.module_from_spec(spec); spec.loader.exec_module(loops)


def vector(value, length):
    if (not isinstance(value, list) or len(value) < length or
            any(type(x) not in (int, float) or not math.isfinite(x) for x in value[:length])):
        raise ValueError('invalid recorded position or pose')
    return value


def partition(data):
    if len(data) < 256 or data[:8] != b'PBENV001': raise ValueError('invalid environment header')
    count = struct.unpack_from('<q', data, 8)[0]
    if count < 1 or len(data) < 256 + count * 128: raise ValueError('invalid environment collider count')
    walls = {struct.unpack_from('<d', data, 256 + i * 128 + 48)[0] for i in range(count)
             if data[256 + i * 128:256 + i * 128 + 48].startswith(b'Wall.partition')}
    if len(walls) != 1 or not all(math.isfinite(wall) for wall in walls):
        raise ValueError('missing or ambiguous doorway partition')
    return next(iter(walls))


def doorway_cases(events, wall):
    cases = delivered = zero_time = 0
    for i, event in enumerate(events):
        robot = vector(event.get('robot'), 3); brick = vector(event.get('brick'), 2)
        if (robot[0] > wall) != (brick[0] > wall):
            cases += 1
            delivered += int(i + 1 < len(events) and events[i + 1]['event'] == 'delivery')
            zero_time += int(i + 1 == len(events) and event['step'] == 300)
    return cases, delivered, cases - delivered, zero_time


def trajectory(poses):
    if not poses: return None
    travelled = sum(math.dist(a[:2], b[:2]) for a, b in zip(poses, poses[1:]))
    displacement = math.dist(poses[0][:2], poses[-1][:2])
    return {'observations': len(poses), 'pathM': travelled, 'netDisplacementM': displacement,
            'pathToDisplacement': travelled / displacement if displacement > 0 else None}


def game(result, rows, events, environment=None):
    steps = result.get('steps'); seed = result.get('seed'); deliveries = result.get('deliveries')
    if (type(seed) is not int or type(steps) is not int or steps != 300 or len(rows) != steps or
            type(deliveries) is not int or deliveries < 0 or type(result.get('reaches')) is not int or result['reaches'] < 0):
        raise ValueError('invalid game result or action count')
    if (not events or events[0].get('event') != 'start' or
            any(event.get('event') != 'delivery' for event in events[1:]) or len(events) != deliveries + 1):
        raise ValueError('invalid delivery event sequence')
    event_steps = [event.get('step') for event in events]
    if (event_steps[0] != 0 or any(type(x) is not int or not 0 <= x <= steps for x in event_steps) or
            any(b <= a for a, b in zip(event_steps, event_steps[1:]))):
        raise ValueError('invalid delivery event timing')
    states = [row['state'] for row in rows]
    if any(type(row.get('step')) is not int for row in rows) or any(b['step'] != a['step'] + 10 for a, b in zip(rows, rows[1:])):
        raise ValueError('nonconsecutive action states')
    estimated, truth, search, consumed = [], [], [], []
    for action, state in enumerate(states, 1):
        localization = state.get('localization', {})
        if localization.get('mode') != 'wheel-drift': raise ValueError('wheel odometry missing')
        estimated.append(vector(localization.get('pose'), 3)[:3]); truth.append(vector(state.get('pose'), 3)[:3])
        task = state['findReturn']; phase = task.get('phase'); index = task.get('consumedIndex')
        if (phase not in ('search', 'return', 'delivered', 'docked') or type(index) is not int or index < -1 or
                (phase == 'search') != (index < 0)):
            raise ValueError('invalid virtual-fetch state')
        observed_deliveries = task.get('deliveries')
        if (type(observed_deliveries) is not int or
                observed_deliveries != sum(step <= action for step in event_steps[1:]) or
                (phase == 'delivered') != (action in event_steps[1:])):
            raise ValueError('delivery event timing disagrees with states')
        search.append(phase == 'search'); consumed.append(index >= 0)
    first = next((i + 1 for i, value in enumerate(consumed) if value), None)
    if (first is not None) != (result['reaches'] > 0):
        raise ValueError('virtual consumption disagrees with result reaches')
    marked, windows = loops.flags(estimated, search); truth_marked, truth_windows = loops.flags(truth, search)
    # Saved poses follow actions; the transition from pose i to i+1 belongs to
    # the latter pose's action. The legacy flagger uses the preceding index.
    marked = {i + 1 for i in marked}; truth_marked = {i + 1 for i in truth_marked}
    search_steps = sum(search)
    first_end = next((i for i, active in enumerate(search) if not active), len(search))
    entry = {'seed': seed, 'deliveries': deliveries, 'completedDelivery': deliveries > 0,
             'firstVirtualConsumptionAction': first, 'searchActions': search_steps,
             'odometryLoopActions': len(marked), 'odometryLoopWindows': windows,
             'truthLoopActions': len(truth_marked), 'truthLoopWindows': truth_windows,
             'overlapActions': len(marked & truth_marked),
             'firstSearchOdometry': trajectory(estimated[:first_end]),
             'firstSearchTruth': trajectory(truth[:first_end]),
             'odometryLoopShareOfSearch': len(marked) / search_steps if search_steps else None}
    if environment is not None:
        total, completed, censored, zero_time = doorway_cases(events, partition(environment))
        entry['doorwayCases'] = total; entry['doorwayDelivered'] = completed
        entry['doorwayCensoredAtHorizon'] = censored; entry['doorwayZeroTimePlacements'] = zero_time
    return entry


def summarize(root, games, level):
    files = list(root.glob('*/[0-9]*/result.json'))
    paths = {}
    for file in files:
        result = json.loads(file.read_text()); seed = result.get('seed')
        if seed in paths: raise ValueError('duplicate game seed')
        paths[seed] = file.parent
    if set(paths) != set(games): raise ValueError('metric paths differ from audited games')
    entries = []
    for seed in sorted(games):
        result, rows, _, _ = games[seed]; directory = paths[seed]
        events = [json.loads(line) for line in (directory / 'chase.jsonl').read_text().splitlines()]
        environment = (directory / 'scene/environment.bin').read_bytes() if level == 4 else None
        entries.append(game(result, rows, events, environment))
    searches = sum(x['searchActions'] for x in entries)
    total = sum(x.get('doorwayCases', 0) for x in entries)
    delivered = sum(x.get('doorwayDelivered', 0) for x in entries)
    censored = sum(x.get('doorwayCensoredAtHorizon', 0) for x in entries)
    zero_time = sum(x.get('doorwayZeroTimePlacements', 0) for x in entries)
    return {'games': entries, 'completedGames': sum(x['completedDelivery'] for x in entries),
            'firstVirtualConsumptionGames': sum(x['firstVirtualConsumptionAction'] is not None for x in entries),
            'odometryLoopActions': sum(x['odometryLoopActions'] for x in entries),
            'odometryLoopShareOfSearch': sum(x['odometryLoopActions'] for x in entries) / searches if searches else None,
            'doorwayCases': total if level == 4 else None, 'doorwayDelivered': delivered if level == 4 else None,
            'doorwayCensoredAtHorizon': censored if level == 4 else None,
            'doorwayZeroTimePlacements': zero_time if level == 4 else None,
            'doorwayDeliveredByHorizonFraction': delivered / total if level == 4 and total else None,
            'scope': 'virtual consumption is not a physical pickup; doorway counts each opposite-side placement through the next delivery; unresolved placements are right-censored at the horizon, and the delivered-by-horizon fraction includes those placements; 50-action mobile loop and first-search path versus displacement are diagnostics based on recorded post-action states, with simulator truth for comparison; they are not a validated recovery or goal pass'}
