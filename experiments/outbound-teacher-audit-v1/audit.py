#!/usr/bin/env python3
"""Read-only comparison of saved L5 outbound trajectories; no training or rollout."""
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
P = ROOT / 'build/flex/sim/levels-v2/pitch82'
OLD = P / 'search-dagger-l35-4workers/selection-L5/student-s1'
OLD_MODEL = P / 'search-dagger-l35-4workers/student-s1'
OLD_MANIFEST = OLD.parent / 'pair-s1.inputs.sha256'
HEADING = P / 'search-dagger-heading/selection-epoch8/L5/treatment'
HEADING_MODEL = P / 'search-dagger-heading/models/heading-epoch8-pair/treatment'
TEACHER = P / 'search-dagger-heading/teacher-selection-v1'
TEACHER_PLAN = P / 'search-dagger-heading/models/heading-teacher-plan-v1.json'
SELECTION_PLAN = P / 'search-dagger-heading/models/heading-epoch8-selection-plan.json'
SEEDS = tuple(range(7800000, 7800032))
CLUSTER = (7800000, 7800003, 7800006, 7800009, 7800021, 7800024)


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


teacher_audit = load('outbound_teacher_audit', ROOT / 'experiments/heading-teacher-audit/audit.py')
selection = teacher_audit.selection
metrics = load('outbound_metrics', ROOT / 'datasets/visual-control/chase-v1/levels/heading-selection-metrics.py')


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def old_manifest():
    result = {}
    for line in OLD_MANIFEST.read_text().splitlines():
        if line.startswith('\\') or '  ' not in line:
            raise ValueError('unsupported old manifest entry')
        sha, name = line.split('  ', 1)
        path = Path(name)
        path = path if path.is_absolute() else ROOT / path
        if len(sha) != 64 or any(c not in '0123456789abcdef' for c in sha):
            raise ValueError('invalid old manifest checksum')
        key = str(path)
        if key in result and result[key] != sha:
            raise ValueError('conflicting old manifest checksum')
        result[key] = sha
    return result


def verify_recorded_inputs():
    old = old_manifest()
    selection_plan = json.loads(SELECTION_PLAN.read_text())
    teacher_plan = json.loads(TEACHER_PLAN.read_text())
    launch = json.loads((TEACHER / 'launch.json').read_text())
    if (teacher_plan.get('status') != 'frozen_before_teacher' or
            teacher_plan.get('studentPlanSHA256') != digest(SELECTION_PLAN) or
            launch.get('planSHA256') != digest(TEACHER_PLAN)):
        raise ValueError('teacher and student plan chain differs')
    checked = {}
    for path in (ROOT / 'build/flex/control/control', ROOT / 'build/flex/control/simulator',
                 ROOT / 'datasets/visual-control/chase-v1/levels/audit-selection.py'):
        checksum = digest(path)
        if old.get(str(path)) != checksum or selection_plan['files'].get(str(path)) != checksum:
            raise ValueError('shared recorded input changed or missing: ' + str(path))
        checked[str(path.relative_to(ROOT))] = checksum
    for model, manifest in ((OLD_MODEL, old), (HEADING_MODEL, selection_plan['files'])):
        _, files = teacher_audit.qualification.model_files(model)
        for path in files:
            if manifest.get(str(path)) != digest(path):
                raise ValueError('model file absent or changed in recorded manifest: ' + str(path))
    audit_source = ROOT / 'experiments/heading-teacher-audit/audit.py'
    if teacher_plan['sourcePins'].get(str(audit_source)) != digest(audit_source):
        raise ValueError('teacher audit source differs from recorded pin')
    return checked


def first_consumption(rows):
    return next((i for i, row in enumerate(rows, 1)
                 if row['state']['findReturn']['consumedIndex'] >= 0), None)


def reversal_marks(rows, start):
    """Reconstruct the existing 20-action detector on pre-action truth poses."""
    poses = [start] + [row['state']['pose'] for row in rows[:-1]]
    velocity = [(row['action'][1] > 0) - (row['action'][1] < 0) for row in rows]
    marked = set()
    for t in range(20, len(rows)):
        flips = sum(velocity[k] * velocity[k - 1] < 0 for k in range(t - 19, t))
        turn = abs((poses[t][2] - poses[t - 20][2] + math.pi) % (2 * math.pi) - math.pi)
        if flips >= 4 and math.dist(poses[t][:2], poses[t - 20][:2]) < 0.25 and turn < math.radians(45):
            marked.update(range(t - 20, t))
    return marked


def common_prefix(games):
    """Compare recorded actions and post-action truth poses across the cluster."""
    baseline = games[CLUSTER[0]]['rows']
    return next((i for i in range(300) if any(
        games[seed]['rows'][i]['action'] != baseline[i]['action'] or
        games[seed]['rows'][i]['state']['pose'] != baseline[i]['state']['pose']
        for seed in CLUSTER[1:])), 300)


def validate_match(games, seed):
    if any(game['scene'] != games[0]['scene'] or game['start'] != games[0]['start'] for game in games[1:]):
        raise ValueError(f'unmatched saved scene or initial placement: {seed}')


def normalized(games, root):
    directories = {int(path.parent.name): path.parent for path in root.glob('*/[0-9]*/result.json')}
    if set(directories) != set(games):
        raise ValueError('student trajectory directories differ')
    return {seed: {'result': result, 'rows': rows, 'start': start, 'scene': scene,
                   'directory': directories[seed],
                   'events': [json.loads(line) for line in (directories[seed] / 'chase.jsonl').open()]}
            for seed, (result, rows, start, scene) in games.items()}


def audit():
    pins = verify_recorded_inputs()
    prior = os.environ.get('PUPPYBOT_PROJECT')
    os.environ['PUPPYBOT_PROJECT'] = str(ROOT)
    try:
        old = normalized(selection.load(OLD, OLD_MODEL, 5), OLD)
        heading = normalized(selection.load(HEADING, HEADING_MODEL, 5), HEADING)
        selection.check_score(OLD, selection.summary({s: (g['result'], g['rows'], g['start'], g['scene']) for s, g in old.items()}))
        selection.check_score(HEADING, selection.summary({s: (g['result'], g['rows'], g['start'], g['scene']) for s, g in heading.items()}))
    finally:
        if prior is None: os.environ.pop('PUPPYBOT_PROJECT', None)
        else: os.environ['PUPPYBOT_PROJECT'] = prior
    teacher = {}
    for part in range(4):
        folder = TEACHER / 'L5/teacher' / str(part)
        teacher_audit.validate_shard(folder, part)
        for index in range(8):
            seed = SEEDS[part * 8 + index]
            game = teacher_audit.teacher_game(folder / f'expert-{index}', seed, 5)
            teacher[seed] = {'result': game['result'], 'rows': game['rows'],
                             'start': game['events'][0], 'scene': game['scene'],
                             'directory': game['directory'], 'events': game['events']}
    if set(old) != set(SEEDS) or set(heading) != set(SEEDS) or set(teacher) != set(SEEDS):
        raise ValueError('missing or extra game seeds')
    results = []
    for seed in SEEDS:
        games = [old[seed], heading[seed], teacher[seed]]
        validate_match(games, seed)
        for game in games:
            if len(game['rows']) != 300:
                raise ValueError('incomplete trajectory')
            teacher_audit.validate_transitions(game['result'], game['rows'], game['events'], game['directory'])
        if seed not in CLUSTER:
            continue
        environment = (games[0]['directory'] / 'scene/environment.bin').read_bytes()
        if not math.isclose(metrics.partition(environment), 1.6, abs_tol=1e-6):
            raise ValueError('selected failure does not belong to recorded x=1.6 group')
        row = {'seed': seed}
        for name, game in zip(('oldStudent', 'heading', 'teacher'), games):
            first = first_consumption(game['rows'])
            marked = reversal_marks(game['rows'], game['start']['robot'])
            if len(marked) != game['result']['backForthSteps']:
                raise ValueError(f'back-forth mismatch: {name} {seed}')
            row[name] = {'firstVirtualConsumptionAction': first,
                         'virtualDeliveries': game['result']['deliveries'],
                         'backForthActions': len(marked),
                         'backForthBeforeFirstConsumption': sum(i < first - 1 for i in marked) if first else None}
        if row['oldStudent']['firstVirtualConsumptionAction'] is not None or row['oldStudent']['virtualDeliveries'] != 0:
            raise ValueError('selected failure cluster changed')
        results.append(row)
    totals = {name: {'firstVirtualConsumptionGames': sum(first_consumption(g['rows']) is not None for g in games.values()),
                     'gamesWithVirtualDelivery': sum(g['result']['deliveries'] > 0 for g in games.values()),
                     'virtualDeliveries': sum(g['result']['deliveries'] for g in games.values())}
              for name, games in (('oldStudent', old), ('heading', heading), ('teacher', teacher))}
    return {'status': 'saved_training_selection_diagnostic', 'matchedGames': len(SEEDS), 'totals': totals,
            'selectedCluster': results, 'commonActionAndPosePrefix': {
                'oldStudent': common_prefix(old), 'teacher': common_prefix(teacher)},
            'sharedRecordedInputSHA256': pins,
            'scope': ('post-hoc correlated training-family cases; virtual pickup only; '
                      'teacher uses reference wall geometry; old full runtime/assets and '
                      'unrecorded ancestry are not established; no execution attestation')}


if __name__ == '__main__':
    print(json.dumps(audit(), indent=2, sort_keys=True, allow_nan=False))
