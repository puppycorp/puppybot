#!/usr/bin/env python3
"""Saved-record checks for the isolated L5 steering probe; no evaluation."""
import math
import struct
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LEVELS = ROOT / 'datasets/visual-control/chase-v1/levels'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


metrics = load('steering_saved_metrics', LEVELS / 'heading-selection-metrics.py')
heldout_helper = load('steering_saved_backforth', LEVELS / 'audit-heldout.py')
qualification = load('steering_saved_qualification', LEVELS / 'qualify-selection.py')


def bits(value):
    return struct.unpack('<I', struct.pack('<f', value))[0]


def value(word):
    if type(word) is not int or not 0 <= word <= 0xffffffff: raise ValueError('invalid float32 word')
    out = struct.unpack('<f', struct.pack('<I', word))[0]
    if not math.isfinite(out): raise ValueError('nonfinite float32')
    return out


def pair(value_, count):
    if not isinstance(value_, list) or len(value_) != count: raise ValueError('invalid vector')
    return [value(word) for word in value_]


def sign_flip(word):
    return word ^ 0x80000000 if value(word) != 0 else word


def audit_stream(rows, decisions, mode):
    if mode not in (1, 2) or len(rows) != 300 or len(decisions) != 300:
        raise ValueError('incomplete or invalid probe stream')
    previous = [0, 0]; previous_hidden = None; trigger = None; cancelled = False; changed = 0
    carrying = False; deliveries = 0; contacts = 0
    expected_fields = {'step','mode','trigger','cancelled','proposed','applied','feedback','previousApplied',
                       'command1000','echo','imageSHA256','hiddenBeforeSHA256','hiddenAfterSHA256'}
    for index, (row, decision) in enumerate(zip(rows, decisions)):
        if (set(row) != expected_fields or type(row['step']) is not int or row['step'] != index + 1 or
                type(row['mode']) is not int or row['mode'] != mode):
            raise ValueError('invalid probe record shape, mode or step')
        proposed = pair(row['proposed'], 2); applied = pair(row['applied'], 2); feedback = pair(row['feedback'], 7)
        pair(row['previousApplied'], 2)
        if any(abs(v) > 1 for v in proposed + applied): raise ValueError('out-of-range action')
        if row['feedback'][:2] != previous or row['previousApplied'] != row['applied']:
            raise ValueError('previous-action feedback does not match applied action')
        if index:
            prior = decisions[index - 1]['state']['controller']['drive']
            expected_drive = [bits(prior['leftSpeed'] / 100), bits(prior['rightSpeed'] / 100),
                              bits((prior['steeringAngleDeg'] - 90) / 45)]
            if row['feedback'][2:5] != expected_drive:
                raise ValueError('feedback does not match preceding simulator drive')
        if index == 0 and row['hiddenBeforeSHA256'] != hashlib.sha256(bytes(128 * 4)).hexdigest():
            raise ValueError('initial recurrent state is not zero')
        if row['feedback'][6] not in (bits(0.), bits(1.)):
            raise ValueError('invalid simulator carry cue')
        if row['feedback'][5] not in (bits(0.), bits(1.)):
            raise ValueError('invalid contact feedback')
        contacts += int(row['feedback'][5] == bits(1.))
        if row['feedback'][6] != bits(float(carrying)):
            raise ValueError('carry cue differs from preceding task transitions')
        if row['feedback'][6] == bits(1.): cancelled = True
        if index == 0: trigger = not cancelled and proposed[0] <= -.5 and proposed[1] <= -.8
        if type(row['trigger']) is not bool or row['trigger'] != trigger or type(row['cancelled']) is not bool or row['cancelled'] != cancelled:
            raise ValueError('trigger or carry cancellation differs')
        expected = list(row['proposed'])
        if mode == 2 and trigger and not cancelled and index < 3: expected[0] = sign_flip(expected[0])
        if row['applied'] != expected: raise ValueError('applied action does not follow fixed intervention')
        changed += int(row['applied'] != row['proposed'])
        if [bits(v) for v in decision['action']] != row['applied']:
            raise ValueError('saved action differs from applied action')
        if (not isinstance(row['command1000'], list) or len(row['command1000']) != 2 or
                any(type(v) is not int for v in row['command1000']) or
                not isinstance(row['echo'], list) or len(row['echo']) != 3 or any(type(v) is not int for v in row['echo'])):
            raise ValueError('invalid command or drive echo')
        cmd = [round(v * 1000) for v in applied]
        if row['command1000'] != cmd: raise ValueError('quantized command differs')
        throttle = math.trunc(cmd[1] * 60 / 1000) if abs(cmd[1]) >= 80 else 0
        echo = [throttle, throttle, 90 + math.trunc(math.trunc(cmd[0] / 10) * 45 / 100)]
        if row['echo'] != echo: raise ValueError('motor echo differs')
        drive = decision['state']['controller']['drive']
        if [drive['leftSpeed'], drive['rightSpeed'], drive['steeringAngleDeg']] != echo:
            raise ValueError('saved simulator drive differs')
        for name in ('imageSHA256','hiddenBeforeSHA256','hiddenAfterSHA256'):
            text = row[name]
            if not isinstance(text, str) or len(text) != 64 or any(c not in '0123456789abcdef' for c in text):
                raise ValueError('invalid actor digest')
        if previous_hidden is not None and row['hiddenBeforeSHA256'] != previous_hidden:
            raise ValueError('recurrent-state continuity differs')
        previous_hidden = row['hiddenAfterSHA256']; previous = row['applied']
        task = decision['state']['findReturn']; consumed = task.get('consumedIndex'); total = task.get('deliveries')
        if (type(consumed) is not int or consumed < -1 or type(total) is not int or
                total < deliveries or total > deliveries + 1):
            raise ValueError('invalid virtual-fetch task transition')
        if not carrying and consumed >= 0: carrying = True
        if total > deliveries: carrying = False
        deliveries = total
    return {'triggered': trigger, 'changedActions': changed, 'carryingCancelled': cancelled,
            'contactActions': contacts}


def audit_pair(control, intervention):
    c, cd = control; t, td = intervention
    a = audit_stream(c, cd, 1); b = audit_stream(t, td, 2)
    first_change = next((i for i, (x, y) in enumerate(zip(c, t)) if x['applied'] != y['applied']), None)
    through = 300 if first_change is None else first_change + 1
    for i in range(through):
        for key in ('proposed', 'feedback', 'imageSHA256', 'hiddenBeforeSHA256', 'hiddenAfterSHA256'):
            if c[i][key] != t[i][key]: raise ValueError('pre-divergence actor boundary differs')
        if i < through - 1 and c[i]['applied'] != t[i]['applied']:
            raise ValueError('earlier unreported intervention')
    if first_change is None and (a['triggered'] != b['triggered'] or b['changedActions']):
        raise ValueError('unmatched no-op or action intervention')
    return {'control': a, 'intervention': b, 'firstChangedAction': None if first_change is None else first_change + 1,
            'preDivergenceObservations': through,
            'scope': 'saved local input digests and command records only; no OS or actor-computation attestation'}


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b''): digest.update(data)
    return digest.hexdigest()


def saved_game(root, seed, expected):
    """Read one game against caller-frozen identities, never an execution claim."""
    root = Path(root); result = json.loads((root / 'result.json').read_text())
    required = {'seed': seed, 'steps': 300, 'game': 'fetch', 'level': 5, 'levelPlacement': 'other room',
                'controller': 'native neural policy', 'blackout': False, 'farBricks': False,
                'exploreTeacher': False, 'sweepTeacher': False, 'suppliedMap': False,
                'taskEventHint': False, 'carryCue': True, 'maximumBrickDistanceM': .35,
                'policyWeightsSHA256': expected['weightsSHA256']}
    for key, value_ in required.items():
        if key not in result or type(result[key]) is not type(value_) or result[key] != value_:
            raise ValueError(f'game result differs: {key}')
    qualification.reject_interventions(result, root)
    for name in ('case.json', 'environment.bin'):
        if sha(root / 'scene' / name) != expected[name]: raise ValueError('scene snapshot differs')
    with (root / 'chase.jsonl').open('rb') as stream:
        start_bytes = stream.readline()
    with (root / 'chase.jsonl').open() as stream: events = [json.loads(line) for line in stream]
    with (root / 'decisions.jsonl').open() as stream: decisions = [json.loads(line) for line in stream]
    with (root / 'steer-probe.jsonl').open() as stream: probe = [json.loads(line) for line in stream]
    if len(decisions) != 300 or any(row['state'].get('trainingOracle', {}).get('enabled') is not False or
                                    type(row['state']['trainingOracle'].get('queries')) is not int or
                                    row['state']['trainingOracle']['queries'] != 0 for row in decisions):
        raise ValueError('incomplete decisions or privileged oracle activity')
    initial_bytes = (root / 'initial.json').read_bytes(); initial = json.loads(initial_bytes)
    environment = (root / 'scene/environment.bin').read_bytes()
    if len(environment) < 256 or environment[:8] != b'PBENV001': raise ValueError('invalid scene environment')
    spawn = struct.unpack_from('<3d', environment, 96)
    start = events[0]; robot = metrics.vector(start.get('robot'), 3); brick = metrics.vector(start.get('brick'), 2)
    pose = metrics.vector(initial.get('pose'), 3); first_ball = metrics.vector(decisions[0]['state'].get('ball'), 3)
    if (not all(math.isfinite(v) for v in spawn) or any(abs(a-b) > 1e-6 for a, b in zip(robot, spawn)) or
            any(abs(a-b) > 1e-5 for a, b in zip(pose, robot)) or
            any(abs(a-b) > 1e-5 for a, b in zip(first_ball[:2], brick)) or
            decisions[0]['state'].get('findReturn', {}).get('consumedIndex') != -1 or
            type(initial.get('step')) is not int or decisions[0].get('step') != initial['step'] + 10 or
            type(decisions[0].get('sequence')) is not int or decisions[0]['sequence'] != 3):
        raise ValueError('spawn, placed brick or first action differs')
    delivery_steps = [e.get('step') for e in events[1:] if e.get('event') == 'delivery']
    if any(type(row.get('sequence')) is not int for row in decisions) or any(
            decisions[i]['sequence'] != decisions[i-1]['sequence'] + 1 + (i in delivery_steps)
            for i in range(1, 300)):
        raise ValueError('missing or replayed action sequence')
    drive = initial['controller']['drive']
    if probe[0]['feedback'][2:5] != [bits(drive['leftSpeed']/100), bits(drive['rightSpeed']/100),
                                      bits((drive['steeringAngleDeg']-90)/45)]:
        raise ValueError('initial own-drive feedback differs')
    backforth = heldout_helper.backforth_steps(decisions, events[0]['robot'])
    if type(result.get('backForthSteps')) is not int or result['backForthSteps'] != backforth:
        raise ValueError('back-and-forth trace differs from result')
    diagnostic = metrics.game(result, decisions, events)
    diagnostic['firstSearchPathScope'] = ('post-action search poses only; excludes initial-to-first-action and '
                                          'the transition into first virtual consumption')
    wall = metrics.partition(environment)
    target_side = brick[0] > wall
    if (robot[0] > wall) == target_side: raise ValueError('target is not in the other room')
    diagnostic['firstRoomEntryAction'] = next((i + 1 for i, row in enumerate(decisions)
                                               if (row['state']['pose'][0] > wall) == target_side), None)
    first = diagnostic['firstVirtualConsumptionAction']
    diagnostic['firstConsumptionCappedAction'] = first if first is not None else 301
    return {'result': result, 'metrics': diagnostic, 'probe': probe, 'decisions': decisions,
            'startBytes': start_bytes, 'initialBytes': initial_bytes,
            'backForthSteps': backforth}


def saved_pair(control_root, intervention_root, seed, expected):
    control = saved_game(control_root, seed, expected); treatment = saved_game(intervention_root, seed, expected)
    if control['startBytes'] != treatment['startBytes'] or control['initialBytes'] != treatment['initialBytes']:
        raise ValueError('matched start or initial state differs')
    checked = audit_pair((control['probe'], control['decisions']), (treatment['probe'], treatment['decisions']))
    c = control['metrics']; t = treatment['metrics']
    for name, game, diagnostic in (('control', control, c), ('intervention', treatment, t)):
        contacts = checked[name]['contactActions']
        if type(game['result'].get('contactSteps')) is not int or game['result']['contactSteps'] != contacts:
            raise ValueError('contact count differs from actor feedback')
        diagnostic['recordedContactSteps'] = contacts
    def early(item):
        first = item['firstVirtualConsumptionAction']
        return first is not None and first <= 200
    return {'seed': seed, 'triggered': checked['intervention']['changedActions'] > 0,
            'controlEarly': early(c), 'interventionEarly': early(t),
            'controlDelivered': c['completedDelivery'], 'interventionDelivered': t['completedDelivery'],
            'controlMostlyBackForth': control['backForthSteps'] * 5 > 300,
            'interventionMostlyBackForth': treatment['backForthSteps'] * 5 > 300,
            'controlMetrics': c, 'interventionMetrics': t, 'probeAudit': checked}


def screen(pairs):
    """Apply the fixed exploratory screen to all 12 complete matched games."""
    if not isinstance(pairs, list) or len(pairs) != 12: raise ValueError('all 12 games required')
    seeds = set(); totals = {'triggered': 0, 'controlEarly': 0, 'interventionEarly': 0,
                             'controlDelivered': 0, 'interventionDelivered': 0,
                             'controlMostlyBackForth': 0, 'interventionMostlyBackForth': 0}
    for item in pairs:
        seed = item.get('seed')
        if type(seed) is not int or seed in seeds: raise ValueError('duplicate or invalid seed')
        seeds.add(seed)
        for key in ('triggered', 'controlEarly', 'interventionEarly', 'controlDelivered',
                    'interventionDelivered', 'controlMostlyBackForth', 'interventionMostlyBackForth'):
            if type(item.get(key)) is not bool: raise ValueError('missing or censored game metric')
            totals[key] += int(item[key])
    if seeds != set(range(6800100, 6800112)): raise ValueError('fixed game inventory differs')
    passed = (totals['triggered'] >= 6 and totals['interventionEarly'] - totals['controlEarly'] >= 3 and
              totals['interventionDelivered'] >= totals['controlDelivered'] and
              totals['interventionMostlyBackForth'] <= totals['controlMostlyBackForth'])
    return {'status': 'exploratory_screen_passed' if passed else 'exploratory_screen_not_passed',
            'games': 12, 'totals': totals,
            'scope': 'includes no-op games; training-family simulation only; not model promotion or held-out qualification'}
