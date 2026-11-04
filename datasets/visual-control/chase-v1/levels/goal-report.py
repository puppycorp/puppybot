#!/usr/bin/env python3
# Diagnostic comparison of matched level 1-5 games against the proposed fetch
# targets. This does not certify a goal pass: existing game files do not prove
# which simulator binaries produced them, or freeze a held-out benchmark.
# Example: python3 -I goal-report.py STUDENT_ROOT STUDENT TEACHER_ROOT TEACHER
import glob
import hashlib
import json
import math
import struct
import sys
from pathlib import Path


def load(root, name, level):
    games = {}
    for file in glob.glob(f'{root}/eval-L{level}/{name}/**/result.json', recursive=True):
        path = Path(file).parent
        result = json.loads(Path(file).read_text())
        seed = result['seed']
        if seed in games:
            raise ValueError(f'duplicate seed {seed}: {path}')
        if result['level'] != level or result['steps'] != 300 or result['actionSeconds'] != 60 or result['blackout']:
            raise ValueError(f'unexpected level, horizon, or blackout: {path}')
        if level == 4 and result.get('levelPlacement') != 'doorway drill':
            raise ValueError(f'level 4 is not the doorway drill: {path}')
        with (path / 'decisions.jsonl').open() as f:
            rows = [json.loads(line) for line in f]
        with (path / 'chase.jsonl').open() as f:
            events = [json.loads(line) for line in f]
        if len(rows) != result['steps'] or not events or events[0]['event'] != 'start':
            raise ValueError(f'incomplete decisions or events: {path}')
        if sum(e['event'] == 'delivery' for e in events) != result['deliveries']:
            raise ValueError(f'delivery event count mismatch: {path}')
        hashes = tuple(hashlib.sha256((path / 'scene' / f).read_bytes()).hexdigest()
                       for f in ('case.json', 'environment.bin'))
        games[seed] = (result, rows, events, hashes, path)
    if set(games) != set(range(990000, 990032)):
        raise ValueError(f'expected exactly seeds 990000-990031 at level {level} in {root}/{name}, got {sorted(games)}')
    return games


def long_search_share(rows):
    # A separate, deliberately conservative long-loop indicator: a search
    # segment returning within 0.3 m and 45 degrees after 100 actions. It also
    # catches long stationary periods; it does not detect all search loops.
    marked = set()
    states = [r['state'] for r in rows]
    for end in range(100, len(states)):
        segment = states[end - 100:end + 1]
        if any(s['findReturn']['phase'] != 'search' for s in segment):
            continue
        a, b = segment[0]['pose'], segment[-1]['pose']
        turn = abs((b[2] - a[2] + math.pi) % (2 * math.pi) - math.pi)
        if math.dist(a[:2], b[:2]) < 0.3 and turn < math.radians(45):
            marked.update(range(end - 100, end))
    return len(marked) / len(rows)


def doorway(events, path):
    data = (path / 'scene' / 'environment.bin').read_bytes()
    count = struct.unpack_from('<q', data, 8)[0]
    walls = {struct.unpack_from('<d', data, 256 + i * 128 + 48)[0] for i in range(count)
             if data[256 + i * 128:].startswith(b'Wall.partition')}
    if len(walls) != 1:
        raise ValueError(f'expected one partition: {path}')
    wall = next(iter(walls))
    cases = [(i, e) for i, e in enumerate(events)
             if e['event'] in ('start', 'delivery') and (e['brick'][0] > wall) != (e['robot'][0] > wall)]
    return len(cases), sum(i + 1 < len(events) and events[i + 1]['event'] == 'delivery' for i, _ in cases)


def report(student_root, student, teacher_root, teacher):
    report = {'status': 'diagnostic_only',
              'reason': 'Saved game records do not certify simulator identity or a frozen, untouched held-out benchmark.',
              'protocol': {'seeds': '990000-990031', 'horizon_actions': 300, 'levels': [1, 2, 3, 4, 5],
                           'long_search_indicator': '100 search actions returning within 0.3 m and 45 degrees; includes stationary periods'},
              'levels': {}}
    for level in range(1, 6):
        a, b = load(student_root, student, level), load(teacher_root, teacher, level)
        for seed in a:
            x, y = a[seed], b[seed]
            if x[3] != y[3] or x[2][0] != y[2][0] or x[0].get('levelPlacement') != y[0].get('levelPlacement'):
                raise ValueError(f'unmatched scene, start, or placement at level {level}, seed {seed}')
            if 'backForthSteps' not in x[0]:
                raise ValueError(f'missing backForthSteps: {x[4]}')
        games = list(a.values())
        delivered = sum(g[0]['deliveries'] > 0 for g in games)
        student_deliveries = sum(g[0]['deliveries'] for g in games)
        teacher_deliveries = sum(g[0]['deliveries'] for g in b.values())
        first_return = sum(any(row['state']['findReturn']['phase'] == 'return' for row in g[1]) for g in games)
        backforth = sum(g[0]['backForthSteps'] for g in games) / sum(g[0]['steps'] for g in games)
        entry = {'games': len(games), 'games_with_delivery': delivered, 'delivery_game_fraction': delivered / len(games),
                 'first_return_games': first_return, 'first_return_fraction': first_return / len(games),
                 'deliveries_per_minute': student_deliveries / len(games), 'teacher_deliveries_per_minute': teacher_deliveries / len(games),
                 'mean_backforth_share': backforth, 'mean_long_search_return_share': sum(long_search_share(g[1]) for g in games) / len(games),
                 'delivery_game_target_met': delivered / len(games) >= .90,
                 'teacher_rate_target_met': student_deliveries >= teacher_deliveries,
                 'backforth_target_met': backforth < .02}
        if level == 3:
            entry['level3_first_pickup_target_met'] = first_return / len(games) >= .90
        if level == 4:
            pairs = [doorway(g[2], g[4]) for g in games]
            total, done = sum(p[0] for p in pairs), sum(p[1] for p in pairs)
            entry.update({'doorway_cases': total, 'doorway_delivered': done,
                          'doorway_delivery_fraction': done / total if total else None,
                          'doorway_target_met': done / total >= .80 if total else False})
        report['levels'][str(level)] = entry
    return report


def main():
    if len(sys.argv) != 5:
        raise SystemExit('usage: goal-report.py STUDENT_ROOT STUDENT TEACHER_ROOT TEACHER')
    try:
        print(json.dumps(report(*sys.argv[1:]), indent=2))
    except (ValueError, KeyError, OSError, struct.error) as e:
        raise SystemExit(f'Invalid comparison: {e}')


if __name__ == '__main__':
    main()
