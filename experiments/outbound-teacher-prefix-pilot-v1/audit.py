#!/usr/bin/env python3
"""Read saved pilot shards and apply the predeclared quality screen.

No files are modified, no model is trained, and saved local evidence does not
attest runtime execution, teacher correctness or hardware behavior.
"""
import hashlib
import importlib.util
import json
import math
import struct
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


screen = load('outbound_screen', HERE / 'screen.py')
plan = screen.plan
prior = load('outbound_pair_pilot', ROOT / 'experiments/l5-teacher-rollin-pilot-v1/pilot.py')
outbound = load('outbound_prior_metrics', ROOT / 'experiments/outbound-teacher-audit-v1/audit.py')


def validate_clock(initial, rows, action_seconds):
    if type(action_seconds) not in (int, float) or action_seconds != 60.0:
        raise ValueError('incorrect 300-action time boundary')
    previous = initial
    for row in rows:
        state = row.get('state', {})
        if (type(row.get('step')) is not int or type(state.get('totalSteps')) is not int or
                type(state.get('timeMs')) is not int or type(previous.get('totalSteps')) is not int or
                type(previous.get('timeMs')) is not int or state['totalSteps'] != row['step'] or
                state['totalSteps'] != previous['totalSteps'] + 10 or state['timeMs'] != previous['timeMs'] + 200):
            raise ValueError('inconsistent simulated clock or step')
        previous = state


def label_evidence(root, arm, games):
    """Check every raw teacher label against finite action and saved result."""
    disagreements = 0
    with (root / 'data.bin').open('rb') as stream:
        for episode, game in enumerate(games):
            stream.seek(32 + episode * plan.HORIZON * 21212 + plan.HORIZON * 21168)
            episode_disagreements = 0
            for row in game['rows']:
                packed = stream.read(44)
                if len(packed) != 44:
                    raise ValueError('short label row')
                action = struct.unpack_from('<2f', packed, 28)
                weight = struct.unpack_from('<f', packed, 40)[0]
                if not all(math.isfinite(v) and abs(v) <= 1 for v in action) or weight != 1:
                    raise ValueError('invalid label or supervision weight')
                differs = struct.pack('<2f', *action) != struct.pack('<2f', *row['action'])
                if arm == 'teacher' and differs:
                    raise ValueError('teacher action and saved teacher label differ')
                episode_disagreements += int(differs)
            if (type(game['result'].get('teacherDisagreements')) is not int or
                    game['result']['teacherDisagreements'] != episode_disagreements):
                raise ValueError('saved disagreement count differs')
            disagreements += episode_disagreements
    return {'checkedRows': len(games) * plan.HORIZON, 'teacherStudentDisagreements': disagreements if arm == 'student' else None}


def audit_arm(root, arm, inputs):
    root = Path(root); student = arm == 'student'
    expected_weights = inputs['modelFiles'][str(plan.MODEL / 'weights.bin')]
    n, fit = prior.shards.audit(root, student, expected_weights, plan.MODEL, 7800000, set(), hashlib.sha256())
    if (n, fit) != (plan.GAMES, plan.FITTING):
        raise ValueError('wrong shard dimensions or split')
    report = json.loads((root / 'report.json').read_text())
    declarations = {'teacherUsesCameraDetections': True, 'teacherUsesReferenceGeometryForWallsOnly': True,
                    'teacherUsesTargetCoordinates': False, 'actorUsesReferencePose': False,
                    'actorUsesTargetCoordinates': False}
    if any(report.get(key) is not value for key, value in declarations.items()):
        raise ValueError('unexpected recorded teacher or actor declarations')
    games = []
    for row in plan.design()['rows']:
        index, seed = row['index'], row['seed']
        game = root / f'expert-{index}'; catalog = plan.CATALOG / str(index)
        for name in ('case.json', 'environment.bin'):
            if prior.sha(game / 'scene' / name) != inputs['scenes'][index]['files'][name]:
                raise ValueError('saved scene differs from source')
            if prior.sha(catalog / name) != inputs['scenes'][index]['files'][name]:
                raise ValueError('catalog differs from source')
        result = json.loads((game / 'result.json').read_text())
        expected = {'seed': seed, 'steps': plan.HORIZON, 'game': 'fetch', 'level': 5,
                    'levelPlacement': 'other room', 'controller': ('native neural policy with exploring fetch teacher labels' if student else 'exploring fetch teacher'),
                    'exploreTeacher': True, 'sweepTeacher': False, 'farBricks': False,
                    'blackout': False, 'suppliedMap': False, 'taskEventHint': False, 'carryCue': True,
                    'maximumBrickDistanceM': .35, 'policyWeightsSHA256': expected_weights if student else None}
        for key, value in expected.items():
            if key not in result or (result[key] is not value if type(value) is bool or value is None else result[key] != value):
                raise ValueError('saved game declaration differs: ' + key)
        prior.teacher.qualification.reject_interventions(result, game)
        rows = prior.read_jsonl(game / 'decisions.jsonl'); events = prior.read_jsonl(game / 'chase.jsonl')
        if len(rows) != plan.HORIZON or not events or events[0].get('event') != 'start':
            raise ValueError('incomplete game')
        initial_bytes = (game / 'initial.json').read_bytes(); initial = json.loads(initial_bytes)
        data = (catalog / 'environment.bin').read_bytes()
        if len(data) < 256 or data[:8] != b'PBENV001':
            raise ValueError('invalid catalog environment')
        spawn = struct.unpack_from('<3d', data, 96)
        prior.validate_initial_and_sequences(initial, rows, events, spawn)
        validate_clock(initial, rows, result.get('actionSeconds'))
        if any(row['state'].get('trainingOracle', {}).get('enabled') is not False or
               row['state']['trainingOracle'].get('queries') != 0 for row in rows):
            raise ValueError('unexpected oracle activity')
        prior.teacher.validate_transitions(result, rows, events, game)
        if prior.teacher.heldout.backforth_steps(rows, events[0]['robot']) != result['backForthSteps']:
            raise ValueError('saved back-and-forth differs')
        values = prior.metrics.game(result, rows, events)
        first = values['firstVirtualConsumptionAction']
        marked = outbound.reversal_marks(rows, events[0]['robot'])
        before = sum(index < (first - 1 if first is not None else plan.HORIZON) for index in marked)
        with (game / 'chase.jsonl').open('rb') as stream:
            start_line = stream.readline()
        games.append({'result': result, 'rows': rows, 'first': first, 'before': before,
                      'initial': hashlib.sha256(initial_bytes).hexdigest(),
                      'start': hashlib.sha256(start_line).hexdigest()})
    return games, label_evidence(root, arm, games)


def verify_collection_evidence(root):
    root = Path(root).absolute()
    manifest = json.loads((root / 'catalog.json').read_text())
    frozen = json.loads((root / 'launch-plan.json').read_text())
    inputs = manifest.get('inputs')
    if manifest.get('status') != 'catalog_inputs_only' or not isinstance(inputs, dict):
        raise ValueError('invalid catalog receipt')
    if (frozen.get('schema') != 'puppybot.outbound-teacher-prefix-pilot-launch.v1' or
            frozen.get('status') != 'frozen_before_play' or frozen.get('inputs') != inputs or
            frozen.get('catalogSHA256') != prior.sha(root / 'catalog.json') or
            frozen.get('commands') != {arm: plan.command(arm, root / arm) for arm in plan.design()['arms']} or
            frozen.get('environment') != plan.environment() or frozen.get('wallSecondsPerArm') != 3600):
        raise ValueError('frozen launch intent differs')
    if plan.preflight() != inputs:
        raise ValueError('recorded input preflight changed')
    plan.verify_catalog(inputs)
    for arm in plan.design()['arms']:
        monitor = root / f'monitor-{arm}'
        expected = {'argv': plan.command(arm, root / arm), 'environment': plan.environment(), 'wallSeconds': 3600}
        if json.loads((monitor / 'invocation.json').read_text()) != expected:
            raise ValueError('arm invocation differs')
        status = json.loads((monitor / 'supervisor-result.json').read_text())
        if ('signal' not in status or type(status.get('clientExit')) is not int or status['clientExit'] != 0 or
                status.get('timedOut') is not False or status.get('signal') is not None or
                status.get('remainingWorkersTerminated') is not False or
                type(status.get('processGroup')) is not int or status['processGroup'] <= 0):
            raise ValueError('unclean arm supervisor')
    return inputs


def audit(root=plan.OUTPUT):
    root = Path(root).absolute()
    if root != plan.OUTPUT or root.is_symlink():
        raise ValueError('unexpected pilot output root')
    inputs = verify_collection_evidence(root)
    student, student_labels = audit_arm(root / 'student', 'student', inputs)
    teacher, teacher_labels = audit_arm(root / 'teacher', 'teacher', inputs)
    records = []
    for row, a, b in zip(plan.design()['rows'], student, teacher):
        if a['initial'] != b['initial'] or a['start'] != b['start']:
            raise ValueError('matched initial state or start differs')
        records.append({key: row[key] for key in ('index', 'seed', 'layout', 'fitting')} | {
            'sceneMatched': True, 'initialMatched': True, 'completeHorizon': True, 'labelsVerified': True,
            'studentFirstConsumptionAction': a['first'], 'teacherFirstConsumptionAction': b['first'],
            'teacherOutboundBackForthActions': b['before']})
    result = screen.evaluate(records)
    result['studentLabels'] = student_labels; result['teacherLabels'] = teacher_labels
    result['scope'] = ('matched saved local inputs, labels and decisions only; no execution attestation, '
                       'teacher correctness, training, held-out, physical or promotion claim')
    return result


if __name__ == '__main__':
    raise SystemExit('Disabled pending a frozen, supervised two-arm collection.')
