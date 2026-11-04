#!/usr/bin/env python3
"""Prospective, seed-aware virtual selection metrics for pre-audited games.

Callers must independently verify the scene, executable, model, worker,
runtime and complete game provenance. This module does not launch games.
"""
import hashlib
import importlib.util
import math
import re
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


protocol = load('fresh_selection_contract', HERE / 'protocol.py')
previous = load('fresh_selection_previous_metrics', ROOT / 'experiments/outbound-five-selection-metrics-v1/metrics.py')


def long_search_100(rows, initial):
    """Union 100-transition search-return windows over all saved actions.

    This matches the held-out protocol's 0.3 m/45 degree search condition and
    includes stationary periods and explicitly includes the initial and
    final windows. It differs from the older helper that omitted the initial
    state. It is not a complete loop detector and is reported separately from
    the 50-action travel test.
    """
    states = [initial] + [row['state'] for row in rows]
    marked, windows = set(), 0
    for end in range(100, len(states)):
        segment = states[end - 100:end + 1]
        if any(state['findReturn']['phase'] != 'search' for state in segment):
            continue
        first, last = segment[0]['pose'], segment[-1]['pose']
        if (not isinstance(first, list) or not isinstance(last, list) or
                len(first) != 3 or len(last) != 3 or
                any(type(value) not in (int, float) or not math.isfinite(value) for value in first + last)):
            raise ValueError('invalid long-search pose')
        heading = abs((last[2] - first[2] + math.pi) % (2 * math.pi) - math.pi)
        if math.dist(first[:2], last[:2]) < .3 and heading < math.radians(45):
            windows += 1
            marked.update(range(end - 100, end))
    return {'actions': len(marked), 'windows': windows,
            'scope': '100-transition truth-pose search return; includes stationary periods and misses other loops'}


def summarize(level, games, *, arm, score_version, expected_weights):
    if type(level) is not int or not 1 <= level <= 5 or len(games) != 32:
        raise ValueError('exactly 32 games of one level are required')
    if arm not in ('parent', 'control', 'treatment', 'teacher'):
        raise ValueError('explicit registered arm required')
    if (expected_weights is not None if arm == 'teacher' else
            not isinstance(expected_weights, str) or not re.fullmatch(r'[0-9a-f]{64}', expected_weights)):
        raise ValueError('explicit registered model hash required')
    if score_version not in ('legacy-v1', 'pose20-final-inclusive-v2'):
        raise ValueError('explicit registered score version required')
    expected = {row['seed'] for row in protocol.contract()['rows'] if row['level'] == level}
    seen, records = set(), []
    for game in games:
        result, rows, events, initial = game['result'], game['rows'], game['events'], game['initial']
        seed = result.get('seed')
        if (type(seed) is not int or seed in seen or seed not in expected or result.get('steps') != 300 or
                len(rows) != 300 or not events or events[0].get('event') != 'start' or events[0].get('step') != 0):
            raise ValueError('wrong seed, duplicate, missing start or incomplete game')
        placement = {1: 'in view', 2: 'just off view', 3: 'same room out of view',
                     4: 'doorway drill', 5: 'other room'}[level]
        teacher = arm == 'teacher'
        policy_sha = result.get('policyWeightsSHA256')
        if (result.get('game') != 'fetch' or type(result.get('level')) is not int or result['level'] != level or
                result.get('levelPlacement') != placement or result.get('actionSeconds') != 60.0 or
                result.get('blackout') is not False or result.get('farBricks') is not False or
                result.get('suppliedMap') is not False or result.get('taskEventHint') is not False or
                result.get('carryCue') is not True or result.get('sweepTeacher') is not False or
                result.get('exploreTeacher') is not teacher or result.get('ensembleMembers', 1) != 1 or
                result.get('controller') != ('exploring fetch teacher' if teacher else 'native neural policy') or
                policy_sha != expected_weights):
            raise ValueError('saved game mode, time horizon, teacher or policy identity differs')
        seen.add(seed)
        if (initial.get('findReturn', {}).get('phase') != 'search' or
                initial['findReturn'].get('consumedIndex') != -1 or
                initial['findReturn'].get('deliveries') != 0 or initial.get('pose') != events[0]['robot']):
            raise ValueError('initial search state or event pose differs')
        scene = game.get('scene')
        if (not isinstance(scene, dict) or set(scene) != {'case.json', 'environment.bin', 'layout.json'} or
                any(not isinstance(data, bytes) or not data for data in scene.values())):
            raise ValueError('explicit saved scene bytes required')
        scene_hashes = {name: hashlib.sha256(data).hexdigest() for name, data in scene.items()}
        start_robot = previous.metrics.vector(events[0].get('robot'), 3)[:3]
        start_brick = previous.metrics.vector(events[0].get('brick'), 2)[:2]
        old = previous.windows.marks(rows, events[0]['robot'], False)
        full = previous.windows.marks(rows, events[0]['robot'], True)
        marker = result.get('backForthMetric')
        if marker != (None if score_version == 'legacy-v1' else score_version):
            raise ValueError('saved 20-action metric version differs from registered binary')
        expected_saved = len(old) if score_version == 'legacy-v1' else len(full)
        if type(result.get('backForthSteps')) is not int or expected_saved != result['backForthSteps'] or not old <= full:
            raise ValueError('saved score disagrees with reconstructed 20-action metric')
        environment = scene['environment.bin'] if level == 4 else None
        entry = previous.metrics.game(result, rows, events, environment)
        entry['sceneSHA256'] = scene_hashes
        entry['startRobot'] = start_robot
        entry['startBrick'] = start_brick
        entry['inclusiveBackForthActions'] = len(full)
        entry['longSearch100'] = long_search_100(rows, initial)
        records.append(entry)
    if seen != expected:
        raise ValueError('missing registered seed')
    delivered = sum(item['completedDelivery'] for item in records)
    pickups = sum(item['firstVirtualConsumptionAction'] is not None for item in records)
    deliveries = sum(item['deliveries'] for item in records)
    backforth = sum(item['inclusiveBackForthActions'] for item in records)
    long100 = sum(item['longSearch100']['actions'] for item in records)
    search50 = sum(item['odometryLoopActions'] for item in records)
    search_actions = sum(item['searchActions'] for item in records)
    value = {'level': level, 'arm': arm, 'scoreVersion': score_version, 'weightsSHA256': expected_weights,
             'games': 32, 'actions': 9600, 'gamesWithDelivery': delivered,
             'deliveryReliabilityAtLeast90Percent': delivered >= 29,
             'firstVirtualConsumptionGames': pickups,
             'level3FirstPickupAtLeast90Percent': pickups >= 29 if level == 3 else None,
             'deliveries': deliveries, 'deliveriesPerMinute': deliveries / 32,
             'inclusiveBackForthActions': backforth, 'inclusiveBackForthShare': backforth / 9600,
             'inclusiveBackForthBelow2Percent': backforth * 50 < 9600,
             'searchActions': search_actions, 'longSearch50OdometryActions': search50,
             'longSearch100TruthActions': long100,
             'longSearch100ShareOfAllActions': long100 / 9600,
             'perGame': records,
             'scope': ('virtual task events and saved-pose diagnostics; separately audit execution/scene provenance; '
                       'not held-out or physical proof')}
    if level == 4:
        placements = sum(item['doorwayCases'] for item in records)
        delivered_cases = sum(item['doorwayDelivered'] for item in records)
        value['doorway'] = {'placements': placements, 'delivered': delivered_cases,
                            'rightCensoredAtHorizon': sum(item['doorwayCensoredAtHorizon'] for item in records),
                            'zeroTimePlacements': sum(item['doorwayZeroTimePlacements'] for item in records),
                            'atLeast80PercentDeliveredByHorizon': delivered_cases * 5 >= placements * 4 if placements else None}
    return value


def compare(parent, control, treatment, teacher, *, score_version, expected_models):
    if (not isinstance(expected_models, dict) or set(expected_models) != {'parent', 'control', 'treatment', 'teacher'} or
            expected_models['teacher'] is not None or
            any(not isinstance(expected_models[name], str) or not re.fullmatch(r'[0-9a-f]{64}', expected_models[name])
                for name in ('parent', 'control', 'treatment'))):
        raise ValueError('registered model hashes required')
    for name, arm in (('parent', parent), ('control', control), ('treatment', treatment), ('teacher', teacher)):
        if (arm.get('games') != 32 or arm.get('actions') != 9600 or arm.get('arm') != name or
                arm.get('scoreVersion') != score_version or arm.get('weightsSHA256') != expected_models[name]):
            raise ValueError('incomparable selection arms')
    if score_version not in ('legacy-v1', 'pose20-final-inclusive-v2'):
        raise ValueError('explicit registered score version required')
    if not parent['level'] == control['level'] == treatment['level'] == teacher['level']:
        raise ValueError('selection levels differ')
    parent_by_seed = {game['seed']: game for game in parent['perGame']}
    control_by_seed = {game['seed']: game for game in control['perGame']}
    treatment_by_seed = {game['seed']: game for game in treatment['perGame']}
    teacher_by_seed = {game['seed']: game for game in teacher['perGame']}
    if (len(parent_by_seed) != 32 or len(control_by_seed) != 32 or len(treatment_by_seed) != 32 or
            len(teacher_by_seed) != 32 or set(parent_by_seed) != set(control_by_seed) or
            set(control_by_seed) != set(treatment_by_seed) or set(control_by_seed) != set(teacher_by_seed)):
        raise ValueError('selection arms are not seed matched')
    for seed in control_by_seed:
        for other in (parent_by_seed[seed], treatment_by_seed[seed], teacher_by_seed[seed]):
            if any(other.get(key) != control_by_seed[seed].get(key)
                   for key in ('sceneSHA256', 'startRobot', 'startBrick')):
                raise ValueError('selection scene or initial placement differs across arms')
    wins = sum(treatment_by_seed[seed]['completedDelivery'] and not control_by_seed[seed]['completedDelivery']
               for seed in control_by_seed)
    losses = sum(control_by_seed[seed]['completedDelivery'] and not treatment_by_seed[seed]['completedDelivery']
                 for seed in control_by_seed)
    parent_wins = sum(treatment_by_seed[seed]['completedDelivery'] and not parent_by_seed[seed]['completedDelivery']
                      for seed in parent_by_seed)
    parent_losses = sum(parent_by_seed[seed]['completedDelivery'] and not treatment_by_seed[seed]['completedDelivery']
                        for seed in parent_by_seed)
    return {'parentRateAtLeastTeacher': parent['deliveries'] >= teacher['deliveries'],
            'treatmentRateAtLeastTeacher': treatment['deliveries'] >= teacher['deliveries'],
            'controlRateAtLeastTeacher': control['deliveries'] >= teacher['deliveries'],
            'studentWeightsDiffer': expected_models['control'] != expected_models['treatment'],
            'treatmentDeliveredGamesAtLeastParent': treatment['gamesWithDelivery'] >= parent['gamesWithDelivery'],
            'treatmentDeliveredGamesMinusParent': treatment['gamesWithDelivery'] - parent['gamesWithDelivery'],
            'matchedTreatmentWinsVersusParent': parent_wins, 'matchedTreatmentLossesVersusParent': parent_losses,
            'treatmentDeliveredGamesAtLeastControl': treatment['gamesWithDelivery'] >= control['gamesWithDelivery'],
            'treatmentDeliveredGamesMinusControl': treatment['gamesWithDelivery'] - control['gamesWithDelivery'],
            'matchedTreatmentWins': wins, 'matchedTreatmentLosses': losses,
            'scope': 'matched simulated horizon; rate comparison does not replace reliability and loop gates'}


if __name__ == '__main__':
    raise SystemExit('Disabled: caller must provide independently audited saved games.')
