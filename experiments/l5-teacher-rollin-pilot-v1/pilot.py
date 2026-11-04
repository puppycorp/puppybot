#!/usr/bin/env python3
"""Disabled paired teacher/student training-scene collection pilot.

Run only within a separately reviewed GPU/disk monitor and dedicated process.
This never trains a model and must not be used for held-out qualification.
"""
import hashlib
import importlib.util
import json
import math
import os
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
LEVELS = ROOT / 'datasets/visual-control/chase-v1/levels'
P = ROOT / 'build/flex/sim/levels-v2/pitch82'
OUTPUT = P / 'l5-teacher-rollin-pilot-v1'
CATALOG_ROOT = P / 'heading-rollin-pilot-catalogs'
CATALOG = CATALOG_ROOT / 'control-L5/catalogs/shard-0'
MODELS = P / 'search-dagger-heading/models'
PACKAGE = MODELS / 'heading-epoch8-pair'
MODEL = PACKAGE / 'treatment'
HORIZON = 300
SEEDS = (6700000, 6700001)


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


base = load('teacher_rollin_base', LEVELS / 'run-route-factorial.py')
shards = load('teacher_rollin_shards', LEVELS / 'audit-shards.py')
metrics = load('teacher_rollin_metrics', LEVELS / 'heading-selection-metrics.py')
teacher = load('teacher_rollin_teacher', ROOT / 'experiments/heading-teacher-audit/audit.py')
standalone = load('teacher_rollin_standalone', ROOT / 'experiments/sim-stop-supervisor/supervisor.py')


def sha(path):
    return base.sha(path)


def catalog_spawn(path):
    data = Path(path).read_bytes()
    if len(data) < 256 or data[:8] != b'PBENV001': raise ValueError('invalid catalog environment')
    spawn = struct.unpack_from('<3d', data, 96)
    if not all(math.isfinite(value) for value in spawn) or any(
            not math.isclose(value, expected, rel_tol=0, abs_tol=1e-12)
            for value, expected in zip(spawn, (-.04, -.04, .42))):
        raise ValueError('catalog spawn differs from fixed pilot design')
    return spawn


def symlink_chain(path):
    """Bind each direct link spelling as well as the resolved file bytes."""
    path = Path(path).absolute(); seen = set(); result = {}
    while path.is_symlink():
        if path in seen or len(seen) >= 16: raise ValueError('runtime symlink cycle')
        seen.add(path); target = os.readlink(path)
        result[str(path)] = 'symlink:' + target
        path = Path(os.path.abspath(path.parent / target))
    if not path.is_file(): raise ValueError('runtime library target missing')
    result[str(path)] = 'sha256:' + sha(path)
    return result


def write_new(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False); stream.write('\n')


def command(arm, output):
    if arm not in ('student', 'teacher'): raise ValueError('unknown arm')
    result = [str(ROOT / 'build/flex/control/control'), 'collect', '--chase', '--scene-catalog', str(CATALOG),
              '--output', str(output), '--episodes', '2', '--validation', '1', '--horizon', '300',
              '--seed', str(SEEDS[0]), '--lean', '--wheel-odometry', '--fetch', '--explore-teacher',
              '--level', '5', '--camera-pitch', '82', '--record-map']
    if arm == 'student': result += ['--policy', str(MODEL)]
    return result


def pin_inputs():
    base.package.verify(MODELS / 'control-s0', MODELS / 'treatment-s0', PACKAGE)
    if CATALOG.is_symlink() or not CATALOG.is_dir() or {p.name for p in CATALOG.iterdir()} != {'0', '1'}:
        raise ValueError('unexpected pilot catalog directories')
    manifest = json.loads((CATALOG_ROOT / 'catalogs.json').read_text())
    rows = manifest.get('rows')
    if (manifest.get('mode') != 'pilot' or manifest.get('status') != 'diagnostic_inputs_only' or
            not isinstance(rows, list) or len(rows) != 2):
        raise ValueError('unexpected catalog manifest')
    for i, row in enumerate(rows):
        directory = CATALOG / str(i)
        if (directory.is_symlink() or not directory.is_dir() or
                {p.name for p in directory.iterdir()} != {'case.json', 'environment.bin', 'layout.json'}):
            raise ValueError('unexpected pilot scene inventory')
        if (type(row.get('seed')) is not int or row['seed'] != SEEDS[i] or row.get('index') != i or
                row.get('shard') != 0 or row.get('layout') != 15 or row.get('controlYaw') != .42 or
                row.get('fitting') is not (i == 0)):
            raise ValueError('unexpected pilot catalog design')
        for name, key in (('case.json', 'caseSHA256'), ('environment.bin', 'controlEnvironmentSHA256'),
                          ('layout.json', 'layoutSHA256')):
            if sha(CATALOG / str(i) / name) != row.get(key): raise ValueError('catalog bytes differ from manifest')
        catalog_spawn(CATALOG / str(i) / 'environment.bin')
    paths = [Path(__file__), LEVELS / 'run-route-factorial.py', LEVELS / 'audit-shards.py',
             LEVELS / 'heading-selection-metrics.py', LEVELS / 'search-loops-odometry.py',
             LEVELS / 'audit-student-labels.py', LEVELS / 'qualify-selection.py', LEVELS / 'audit-heldout.py',
             LEVELS / 'audit-selection.py', ROOT / 'experiments/heading-teacher-audit/audit.py',
             ROOT / 'experiments/sim-stop-supervisor/supervisor.py', ROOT / 'flex/tests/run-physical-hidden-trial.py',
             ROOT / 'flex/tests/run-physical-rescan-trial.py', ROOT / 'flex/tests/run-physical-hybrid-trial.py',
             ROOT / 'build/flex/control/control', ROOT / 'build/flex/control/simulator',
             ROOT / 'build/flex/sim/puppybot.bin',
             ROOT / 'puppybot.json', Path(sys.executable).resolve(), CATALOG_ROOT / 'catalogs.json',
             PACKAGE / 'manifest.json', LEVELS / 'package-matched-epoch8.py',
             MODEL / 'policy', MODEL / 'weights.bin', MODEL / 'receipt.json']
    paths += sorted((MODEL / 'kernels').iterdir())
    paths += [CATALOG / str(i) / name for i in range(2) for name in ('case.json', 'environment.bin', 'layout.json')]
    if any(not p.is_file() or p.is_symlink() for p in paths): raise ValueError('missing or symlinked pilot input')
    result = {str(path): sha(path) for path in paths}
    result.update(symlink_chain(ROOT / 'build/flex/rocm-runtime/libamdhip64.so'))
    return result


def read_jsonl(path):
    with path.open() as stream: return [json.loads(line) for line in stream]


def validate_initial_and_sequences(initial, rows, events, spawn):
    if len(rows) != HORIZON or not events: raise ValueError('incomplete action records')
    start = events[0]; pose = initial.get('pose'); ball = rows[0].get('state', {}).get('ball')
    if (not teacher.finite_vector(pose, 3) or not teacher.finite_vector(ball, 3) or
            not teacher.finite_vector(start.get('robot'), 3) or not teacher.finite_vector(start.get('brick'), 2) or
            len(spawn) != 3 or not all(math.isfinite(value) for value in spawn) or
            any(abs(a - b) > 1e-6 for a, b in zip(start['robot'], spawn)) or
            rows[0]['state'].get('findReturn', {}).get('consumedIndex') != -1 or
            any(abs(a - b) > 1e-5 for a, b in zip(pose, start['robot'])) or
            any(abs(a - b) > 1e-5 for a, b in zip(ball[:2], start['brick'])) or
            type(initial.get('step')) is not int or type(rows[0].get('step')) is not int or
            rows[0]['step'] != initial['step'] + 10 or rows[0].get('sequence') != 3):
        raise ValueError('initial pose, target or first action differs')
    delivery_steps = [e.get('step') for e in events[1:] if e.get('event') == 'delivery']
    if any(type(row.get('sequence')) is not int for row in rows) or any(
            rows[i]['sequence'] != rows[i - 1]['sequence'] + 1 + (i in delivery_steps)
            for i in range(1, HORIZON)):
        raise ValueError('missing or replayed decision sequence')


def label_evidence(root, arm, decisions, results):
    data = root / 'data.bin'; disagreements = 0; count = 0
    with data.open('rb') as stream:
        for episode, rows in enumerate(decisions):
            stream.seek(32 + episode * HORIZON * 21212 + HORIZON * 21168)
            episode_disagreements = 0
            for row in rows:
                packed = stream.read(44)
                if len(packed) != 44: raise ValueError('short label row')
                action = struct.unpack_from('<2f', packed, 28)
                weight = struct.unpack_from('<f', packed, 40)[0]
                if not all(math.isfinite(v) and abs(v) <= 1 for v in action) or weight != 1:
                    raise ValueError('invalid teacher label or supervision weight')
                equal = struct.pack('<2f', *action) == struct.pack('<2f', *row['action'])
                if arm == 'teacher' and not equal: raise ValueError('teacher label differs from executed teacher action')
                episode_disagreements += int(not equal); count += 1
            if (type(results[episode].get('teacherDisagreements')) is not int or
                    episode_disagreements != results[episode]['teacherDisagreements']):
                raise ValueError('recorded teacher disagreement count differs')
            disagreements += episode_disagreements
    if count != 2 * HORIZON: raise ValueError('incomplete label rows')
    return {'checkedRows': count, 'teacherStudentActionDisagreements': disagreements if arm == 'student' else None,
            'scope': 'saved labels and actions only; teacher correctness and runtime execution are not attested'}


def audit_arm(root, arm, pinned):
    root = Path(root); student = arm == 'student'; expected_weights = pinned[str(MODEL / 'weights.bin')]
    n, fit = shards.audit(root, student, expected_weights, MODEL, 7800000, set(), hashlib.sha256())
    if (n, fit) != (2, 1): raise ValueError('pilot shard split differs')
    report = json.loads((root / 'report.json').read_text())
    declarations = {'teacherUsesCameraDetections': True, 'teacherUsesReferenceGeometryForWallsOnly': True,
                    'teacherUsesTargetCoordinates': False, 'actorUsesReferencePose': False,
                    'actorUsesTargetCoordinates': False}
    if any(report.get(k) is not value for k, value in declarations.items()): raise ValueError('teacher declarations differ')
    games = []; all_rows = []; results = []
    for index, seed in enumerate(SEEDS):
        game = root / f'expert-{index}'
        for name in ('case.json', 'environment.bin'):
            if sha(game / 'scene' / name) != pinned[str(CATALOG / str(index) / name)]:
                raise ValueError('saved game scene differs from pinned catalog')
        result = json.loads((game / 'result.json').read_text())
        expected = {'seed': seed, 'steps': HORIZON, 'game': 'fetch', 'level': 5, 'levelPlacement': 'other room',
                    'controller': ('native neural policy with exploring fetch teacher labels' if student else 'exploring fetch teacher'),
                    'exploreTeacher': True, 'sweepTeacher': False, 'farBricks': False,
                    'blackout': False, 'suppliedMap': False, 'taskEventHint': False, 'carryCue': True,
                    'maximumBrickDistanceM': .35, 'policyWeightsSHA256': expected_weights if student else None}
        for key, value in expected.items():
            if key not in result or (result[key] is not value if type(value) is bool or value is None else result[key] != value):
                raise ValueError(f'game declaration differs: {key}')
        teacher.qualification.reject_interventions(result, game)
        rows = read_jsonl(game / 'decisions.jsonl'); events = read_jsonl(game / 'chase.jsonl')
        if len(rows) != HORIZON or not events or events[0].get('event') != 'start': raise ValueError('incomplete game')
        initial = json.loads((game / 'initial.json').read_text())
        validate_initial_and_sequences(initial, rows, events, catalog_spawn(CATALOG / str(index) / 'environment.bin'))
        if any(row['state'].get('trainingOracle', {}).get('enabled') is not False or
               row['state']['trainingOracle'].get('queries') != 0 for row in rows): raise ValueError('oracle activity')
        teacher.validate_transitions(result, rows, events, game)
        if teacher.heldout.backforth_steps(rows, events[0]['robot']) != result['backForthSteps']:
            raise ValueError('back-and-forth differs')
        values = metrics.game(result, rows, events)
        with (game / 'chase.jsonl').open('rb') as stream: start_bytes = stream.readline()
        games.append({'seed': seed, 'start': events[0], 'startLineSHA256': hashlib.sha256(start_bytes).hexdigest(),
                      'initialStateSHA256': sha(game / 'initial.json'),
                      'metrics': values})
        all_rows.append(rows); results.append(result)
    return {'games': games, 'labels': label_evidence(root, arm, all_rows, results)}


def compare(student, teacher_arm):
    if len(student['games']) != 2 or len(teacher_arm['games']) != 2: raise ValueError('missing matched games')
    differences = []
    for a, b in zip(student['games'], teacher_arm['games']):
        left = a['start']; right = b['start']
        if (a['seed'] != b['seed'] or left.get('event') != 'start' or right.get('event') != 'start' or
                left.get('step') != 0 or right.get('step') != 0 or
                a['startLineSHA256'] != b['startLineSHA256'] or
                a['initialStateSHA256'] != b['initialStateSHA256'] or
                left.get('robot') != right.get('robot') or left.get('brick') != right.get('brick') or
                not teacher.finite_vector(left.get('robot'), 3) or not teacher.finite_vector(left.get('brick'), 2)):
            raise ValueError('paired start or brick differs')
        sa = a['metrics']['firstVirtualConsumptionAction']; ta = b['metrics']['firstVirtualConsumptionAction']
        earlier = (None if ta is None and sa is None else False if ta is None else sa is None or ta < sa)
        differences.append({'seed': a['seed'], 'studentFirstConsumptionAction': sa,
                            'teacherFirstConsumptionAction': ta,
                            'teacherEarlier': earlier,
                            'studentFirstSearchTruth': a['metrics'].get('firstSearchTruth'),
                            'teacherFirstSearchTruth': b['metrics'].get('firstSearchTruth'),
                            'studentDeliveries': a['metrics'].get('deliveries'),
                            'teacherDeliveries': b['metrics'].get('deliveries')})
    if len(differences) != 2: raise ValueError('missing matched games')
    comparisons = [row['teacherEarlier'] for row in differences]
    any_earlier = True if True in comparisons else False if all(value is False for value in comparisons) else None
    return {'status': 'diagnostic_only', 'pairs': differences,
            'teacherEarlierInAnyGame': any_earlier,
            'studentLabels': student['labels'],
            'teacherLabels': teacher_arm['labels'],
            'scope': 'two previously used training-pilot games, not a selection, model training, held-out or physical result; start and scene bytes matched; runtime identity not attested'}


def run():
    standalone.require_dedicated_process()
    with base.acquire_lock(P / '.l4-matched.lock'):
        base.require_new_output(OUTPUT); base.require_capacity(P, 36 * 1024**3)
        inputs = pin_inputs()
        OUTPUT.mkdir(); write_new(OUTPUT / 'inputs.json', {'files': inputs, 'seeds': SEEDS, 'scope': 'diagnostic training pilot'})
        env = {'PATH': '/usr/bin:/bin', 'HOME': str(Path.home()), 'SDL_VIDEODRIVER': 'offscreen',
               'LD_LIBRARY_PATH': str(ROOT / 'build/flex/rocm-runtime')}
        try:
            reports = {}
            for arm in ('student', 'teacher'):
                base.require_capacity(P, 34 * 1024**3)
                if pin_inputs() != inputs: raise ValueError('pilot inputs changed')
                monitor = OUTPUT / f'monitor-{arm}'; monitor.mkdir()
                argv = command(arm, OUTPUT / arm)
                write_new(monitor / 'invocation.json', {'argv': argv, 'environment': env, 'wallSeconds': 600})
                status = base.hidden.supervise(argv, monitor, env, 600)
                if (type(status.get('clientExit')) is not int or status['clientExit'] != 0 or
                        status.get('timedOut') is not False or status.get('signal') is not None or
                        status.get('remainingWorkersTerminated') is not False or
                        type(status.get('processGroup')) is not int or status['processGroup'] <= 0):
                    raise RuntimeError('run failed or required cleanup')
                if pin_inputs() != inputs: raise ValueError('pilot inputs changed during collection')
                reports[arm] = audit_arm(OUTPUT / arm, arm, inputs)
            paired = compare(reports['student'], reports['teacher'])
            if pin_inputs() != inputs: raise ValueError('pilot inputs changed during audit')
            base.require_capacity(P, 32 * 1024**3)
            write_new(OUTPUT / 'report.json', paired)
            return paired
        except BaseException as error:
            if not (OUTPUT / 'report.json').exists():
                write_new(OUTPUT / 'partial.json', {'status': 'censored', 'reason': str(error)})
            raise


if __name__ == '__main__':
    raise SystemExit('Disabled pending independent review and external GPU/disk monitor.')
