#!/usr/bin/env python3
"""Inclusive selection metrics for fully audited virtual-fetch games.

This helper independently reconstructs final-window back-and-forth and the
separate 50-action search-loop indicator. It does not replace the upstream
scene, model, transition, monitor or saved-score audit.
"""
import importlib.util
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASE = 7820000
GAMES = 32
HORIZON = 300
ARMS = ('control', 'treatment', 'teacher')


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


windows = load('outbound_five_inclusive_windows', ROOT / 'experiments/final-loop-window-v1/audit.py')
metrics = load('outbound_five_selection_metrics', ROOT / 'datasets/visual-control/chase-v1/levels/heading-selection-metrics.py')


def load_games(root, arm):
    """Read known arm layout; caller must separately run the strict audit."""
    if arm not in ARMS:
        raise ValueError('unknown arm')
    root = Path(root)
    games = []
    for index in range(GAMES):
        seed = BASE + index
        part = root / arm / str(index // 8)
        game = part / (f'expert-{index % 8}' if arm == 'teacher' else str(seed))
        result = json.loads((game / 'result.json').read_text())
        rows = [json.loads(line) for line in (game / 'decisions.jsonl').read_text().splitlines()]
        events = [json.loads(line) for line in (game / 'chase.jsonl').read_text().splitlines()]
        if result.get('seed') != seed:
            raise ValueError('unexpected seed or game order')
        games.append({'result': result, 'rows': rows, 'events': events,
                      'environmentPath': game / 'scene/environment.bin'})
    return games


def summarize(games, level):
    """Summarize exactly 32 complete games after strict upstream verification."""
    if type(level) is not int or not 1 <= level <= 5 or len(games) != GAMES:
        raise ValueError('invalid level or game count')
    seeds = set(); items = []
    for game in games:
        result, rows, events = game['result'], game['rows'], game['events']
        seed = result.get('seed')
        if type(seed) is not int or seed in seeds or result.get('steps') != HORIZON or len(rows) != HORIZON:
            raise ValueError('duplicate seed or incomplete horizon')
        seeds.add(seed)
        if not events or events[0].get('event') != 'start' or events[0].get('step') != 0:
            raise ValueError('missing initial event')
        old = windows.marks(rows, events[0]['robot'], False)
        inclusive = windows.marks(rows, events[0]['robot'], True)
        if type(result.get('backForthSteps')) is not int or len(old) != result['backForthSteps'] or not old <= inclusive:
            raise ValueError('legacy and reconstructed back-and-forth counts differ')
        environment = Path(game['environmentPath']).read_bytes() if level == 4 else None
        entry = metrics.game(result, rows, events, environment)
        entry['legacyBackForthActions'] = len(old)
        entry['inclusiveBackForthActions'] = len(inclusive)
        entry['finalWindowAdditionalActions'] = len(inclusive - old)
        items.append(entry)
    if seeds != set(range(BASE, BASE + GAMES)):
        raise ValueError('missing or unexpected selection seeds')
    actions = GAMES * HORIZON
    flagged = sum(item['inclusiveBackForthActions'] for item in items)
    search_actions = sum(item['searchActions'] for item in items)
    loop_actions = sum(item['odometryLoopActions'] for item in items)
    deliveries = sum(item['deliveries'] for item in items)
    first_pickups = sum(item['firstVirtualConsumptionAction'] is not None for item in items)
    delivered_games = sum(item['completedDelivery'] for item in items)
    output = {'games': GAMES, 'actions': actions, 'deliveries': deliveries,
              'deliveriesPerMinute': deliveries / GAMES,
              'gamesWithDelivery': delivered_games,
              'deliveryReliabilityAtLeast90Percent': delivered_games * 10 >= GAMES * 9,
              'firstVirtualConsumptionGames': first_pickups,
              'firstVirtualConsumptionAtLeast90Percent': first_pickups * 10 >= GAMES * 9 if level == 3 else None,
              'legacyBackForthActions': sum(item['legacyBackForthActions'] for item in items),
              'inclusiveBackForthActions': flagged,
              'inclusiveBackForthShare': flagged / actions,
              'inclusiveBackForthBelow2Percent': flagged * 50 < actions,
              'searchActions': search_actions, 'longSearchLoopActions': loop_actions,
              'longSearchLoopShareOfSearch': loop_actions / search_actions if search_actions else None,
              'longSearchLoopWindows': sum(item['odometryLoopWindows'] for item in items),
              'truthLongSearchLoopActions': sum(item['truthLoopActions'] for item in items),
              'perGame': items,
              'scope': ('virtual task events, legacy-saved scores plus independently reconstructed inclusive '
                        '20-action heuristic and 50-action odometry search indicator; not physical or held-out proof')}
    if level == 4:
        placements = sum(item['doorwayCases'] for item in items)
        delivered = sum(item['doorwayDelivered'] for item in items)
        output['doorway'] = {'placements': placements, 'delivered': delivered,
                             'rightCensoredAtHorizon': sum(item['doorwayCensoredAtHorizon'] for item in items),
                             'zeroTimePlacements': sum(item['doorwayZeroTimePlacements'] for item in items),
                             'deliveredByHorizonFraction': delivered / placements if placements else None,
                             'atLeast80PercentDeliveredByHorizon': delivered * 5 >= placements * 4 if placements else None,
                             'scope': 'opposite-side placements; unresolved placements remain in the denominator'}
    return output


def compare(arms):
    """Report matched rate and game-count comparisons without promotion."""
    if set(arms) != set(ARMS):
        raise ValueError('all three selection arms are required')
    control, candidate, teacher = (arms[name] for name in ARMS)
    if any(arm['games'] != GAMES or arm['actions'] != GAMES * HORIZON for arm in arms.values()):
        raise ValueError('incomparable game or time horizons')
    return {'candidateDeliveryRateAtLeastTeacher': candidate['deliveries'] >= teacher['deliveries'],
            'candidateDeliveredGamesAtLeastControl': candidate['gamesWithDelivery'] >= control['gamesWithDelivery'],
            'candidateDeliveredGamesAtLeastTeacher': candidate['gamesWithDelivery'] >= teacher['gamesWithDelivery'],
            'scope': ('equal recorded game horizons; per-arm doorway placement sets may differ; '
                      'not a held-out or promotion decision')}


def audit_existing(root):
    """Replay the complete archived selection; its original monitor failed."""
    expected = ROOT / 'build/flex/sim/levels-v2/pitch82/fresh-policy-selection-v2'
    root = Path(root).absolute()
    if root != expected or root.is_symlink():
        raise ValueError('expected the fixed archived v2 selection root')
    monitor = expected.parent / 'fresh-policy-selection-monitored-v2/monitor-result.json'
    if monitor.is_symlink() or json.loads(monitor.read_text()) != {
            'status': 'failed', 'reason': 'unsafe or vanished output directory'}:
        raise ValueError('archived original monitor status differs')
    saved = json.loads((root / 'report.json').read_text())
    results = {}
    for level in range(1, 6):
        task = f'L{level}'; results[task] = {}
        for arm in ARMS:
            current = summarize(load_games(root / task, arm), level)
            old = saved['tasks'][task]['results'][arm]
            if (current['gamesWithDelivery'] != old['gamesWithDelivery'] or
                    current['deliveries'] != old['deliveries'] or
                    current['legacyBackForthActions'] != round(old['backForthShare'] * GAMES * HORIZON)):
                raise ValueError('archived aggregate differs from saved report')
            results[task][arm] = current
    return {'status': 'read_only_training_family_diagnostic', 'archivedMonitor': 'failed',
            'metrics': results, 'comparisons': {task: compare(arms) for task, arms in results.items()},
            'scope': 'saved local data only; no monitor pass or actor execution attestation'}


if __name__ == '__main__':
    import sys
    if len(sys.argv) != 2:
        raise SystemExit('Expected archived selection root')
    print(json.dumps(audit_existing(sys.argv[1]), sort_keys=True, allow_nan=False))
