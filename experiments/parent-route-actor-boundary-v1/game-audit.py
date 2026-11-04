#!/usr/bin/env python3
"""Audit two parent-driven collector shards against sealed selection games.

The original games were already used for development. These checks establish
local saved-record consistency, not camera provenance or a training result.
"""
import hashlib
import importlib.util
import json
import math
import struct
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PLAN_SHA256 = '84f19ef148109105a0be89b41f1aadb81da2180f8821c4b5f9290f79f30d280e'
ORIGINAL_FILES = {'initial.json', 'result.json', 'decisions.jsonl', 'chase.jsonl',
                  'scene/case.json', 'scene/environment.bin'}
EXPECTED = ((0, 0, 'fit', 7820010, 15, 10, 163),
            (0, 1, 'companion_only', 7820011, 17, 11, 223),
            (1, 0, 'fit', 7820025, 15, 9, 189),
            (1, 1, 'companion_only', 7820026, 17, 10, 175))
IMAGE, ROW, MAP, HORIZON = 21168, 44, 144, 300


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


boundary = load('parent_fit_boundary_audit', HERE / 'audit.py')
windows = load('parent_bounded_windows', ROOT / 'experiments/final-loop-window-v1/audit.py')


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def regular(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f'missing or linked evidence file: {path}')
    return path


def read(path):
    return json.loads(regular(path).read_text())


def lines(path):
    with regular(path).open() as source:
        return [json.loads(line) for line in source]


def fixed_rows(plan):
    rows = plan.get('rows')
    if (plan.get('schema') != 'puppybot.parent-route-collector-plan.v1' or
            plan.get('status') != 'cpu_plan_only' or not isinstance(rows, list) or len(rows) != 4):
        raise ValueError('collector plan schema or rows differ')
    for row, expected in zip(rows, EXPECTED):
        actual = tuple(row.get(key) for key in ('shard', 'episode', 'role', 'seed', 'layout', 'variant', 'firstDeliveryStep'))
        if actual != expected or set(row.get('selectionSHA256', {})) != ORIGINAL_FILES:
            raise ValueError('fixed fitting or companion identity differs')
    return rows


def verify_scene(row):
    scene = Path(row['scene'])
    if not scene.is_absolute() or scene.is_symlink() or not scene.is_dir():
        raise ValueError('invalid source scene directory')
    expected = row['sceneSHA256']
    if set(expected) != {'case.json', 'environment.bin', 'layout.json'}:
        raise ValueError('source scene inventory differs')
    if digest(regular(scene / 'case.json')) != expected['case.json']:
        raise ValueError('source scene case changed')
    for name in ('environment.bin', 'layout.json'):
        path = scene / name
        if (not path.is_symlink() or path.resolve(strict=True) != scene.parent / name or
                digest(path) != expected[name]):
            raise ValueError('source scene link or bytes changed')


def labels(data_path, episode, rows, horizon=HORIZON):
    if len(rows) != horizon:
        raise ValueError('wrong episode horizon')
    disagreement = 0
    with regular(data_path).open('rb') as source:
        source.seek(32 + episode * horizon * (IMAGE + ROW) + horizon * IMAGE)
        for row in rows:
            packed = source.read(ROW)
            if len(packed) != ROW:
                raise ValueError('truncated teacher label row')
            values = struct.unpack('<11f', packed)
            if any(not math.isfinite(value) for value in values) or packed[28:36] not in boundary.CODEC:
                raise ValueError('invalid teacher label or feedback')
            if packed[36:44] != struct.pack('<2f', 0, 1):
                raise ValueError('invalid collector phase or mask')
            action = row.get('action')
            if not isinstance(action, list) or len(action) != 2:
                raise ValueError('invalid executed action')
            actual = struct.pack('<2f', *action)
            if actual not in boundary.CODEC:
                raise ValueError('executed action outside seven-action codec')
            disagreement += packed[28:36] != actual
    return disagreement


def game(row, collected, label_differences, horizon=HORIZON):
    """Require exact lean action-boundary parity except checked result metadata."""
    original = Path(row['selectionRun']); collected = Path(collected)
    if original.is_symlink() or collected.is_symlink():
        raise ValueError('game directory is a symlink')
    for name, expected in row['selectionSHA256'].items():
        if digest(regular(original / name)) != expected:
            raise ValueError('sealed original selection record changed')
    for name in ('case.json', 'environment.bin'):
        if (digest(regular(original / 'scene' / name)) != row['sceneSHA256'][name] or
                digest(regular(collected / 'scene' / name)) != row['sceneSHA256'][name]):
            raise ValueError('collected scene differs from sealed scene')
    if read(original / 'initial.json') != read(collected / 'initial.json'):
        raise ValueError('collected initial state differs')
    old_rows, new_rows = lines(original / 'decisions.jsonl'), lines(collected / 'decisions.jsonl')
    if len(old_rows) != horizon or new_rows != old_rows:
        raise ValueError('collected action-boundary decisions or states differ')
    events = lines(original / 'chase.jsonl')
    if not events or events != lines(collected / 'chase.jsonl') or events[0].get('event') != 'start':
        raise ValueError('collected task events differ')
    deliveries = [event.get('step') for event in events[1:]]
    if (any(event.get('event') != 'delivery' for event in events[1:]) or
            any(type(step) is not int or not 1 <= step <= horizon for step in deliveries) or
            deliveries != sorted(set(deliveries)) or not deliveries or deliveries[0] != row['firstDeliveryStep']):
        raise ValueError('delivery sequence or fixed first-delivery boundary differs')
    for index, decision in enumerate(new_rows):
        task = decision['state']['findReturn']
        if (type(task.get('deliveries')) is not int or task['deliveries'] != sum(step <= index + 1 for step in deliveries) or
                (task.get('phase') == 'delivered') != (index + 1 in deliveries)):
            raise ValueError('saved task state and delivery events disagree')
    old, new = read(original / 'result.json'), read(collected / 'result.json')
    if (old.get('seed') != row['seed'] or new.get('seed') != row['seed'] or
            old.get('steps') != horizon or new.get('steps') != horizon or
            old.get('deliveries') != len(deliveries) or new.get('deliveries') != len(deliveries) or
            old.get('controller') != 'native neural policy' or old.get('exploreTeacher') is not False or
            new.get('controller') != 'native neural policy with exploring fetch teacher labels' or
            new.get('exploreTeacher') is not True or type(new.get('coverageMisses')) is not int or
            new['coverageMisses'] < 0 or type(new.get('teacherDisagreements')) is not int or
            new['teacherDisagreements'] != label_differences):
        raise ValueError('game or teacher-label declaration differs')
    legacy = len(windows.marks(old_rows, events[0]['robot'], False))
    inclusive = len(windows.marks(old_rows, events[0]['robot'], True))
    if old.get('backForthSteps') != legacy or new.get('backForthMetric') != 'pose20-final-inclusive-v2' or new.get('backForthSteps') != inclusive:
        raise ValueError('legacy or inclusive back-and-forth does not reconstruct')
    ignored = {'controller', 'exploreTeacher', 'teacherDisagreements', 'coverageMisses', 'backForthSteps', 'backForthMetric'}
    if {k: v for k, v in old.items() if k not in ignored} != {k: v for k, v in new.items() if k not in ignored}:
        raise ValueError('unexpected game result difference')
    return {'seed': row['seed'], 'role': row['role'], 'episode': row['episode'],
            'firstDeliveryStep': deliveries[0], 'teacherDisagreements': label_differences,
            'boundedPrefixBackForthActions': len(windows.marks(old_rows[:deliveries[0]], events[0]['robot'], True)),
            'firstDeliveryPrefixOnlyForFutureFit': row['role'] == 'fit'}, new_rows, new


def shard(report_path, shard_root, model, input_hashes, shard_number):
    report = read(report_path)
    expected = {'complete': True, 'game': 'chase', 'runtime': 'Flexscript', 'pythonRequired': False,
                'teacher': 'exploring fetch teacher', 'studentDriven': True,
                'teacherUsesCameraDetections': True, 'teacherUsesReferenceGeometryForWallsOnly': True,
                'teacherUsesTargetCoordinates': False, 'actorUsesReferencePose': False,
                'actorUsesTargetCoordinates': False, 'seed': (7820010, 7820025)[shard_number],
                'episodes': 2, 'trainingEpisodes': 1, 'validationEpisodes': 1, 'sequenceLength': HORIZON}
    if any(report.get(key) is not value if type(value) is bool else report.get(key) != value for key, value in expected.items()):
        raise ValueError('collector report, split or source declarations differ')
    for name, magic, width, key in (('data.bin', b'PVDATA01', IMAGE + ROW, 'dataSHA256'),
                                    ('map.bin', b'PVMAP001', MAP, 'mapSHA256')):
        path = regular(shard_root / name)
        with path.open('rb') as source:
            if source.read(32) != struct.pack('<8s3q', magic, 2, 1, HORIZON):
                raise ValueError('collector dataset header or fitting split differs')
        if path.stat().st_size != 32 + 2 * HORIZON * width or digest(path) != report.get(key):
            raise ValueError('collector dataset size or receipt digest differs')
    model = Path(model); snapshot = shard_root / 'policy'
    receipt = read(model / 'receipt.json')
    names = ['receipt.json', 'weights.bin', 'policy'] + [f'kernels/{name}' for name in sorted(receipt['kernels'])]
    for name in names:
        source = model / name; copied = snapshot / name
        expected_hash = input_hashes.get(str(source))
        if not expected_hash or digest(regular(source)) != expected_hash or digest(regular(copied)) != expected_hash:
            raise ValueError('collector model snapshot differs from frozen parent')
    return report


def audit(plan_path, collection_root, companion_module):
    plan_path = regular(plan_path)
    if digest(plan_path) != PLAN_SHA256:
        raise ValueError('fixed pre-collection plan hash differs')
    plan = read(plan_path); rows = fixed_rows(plan); root = Path(collection_root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('invalid collector output root')
    model = plan['commands'][0][-1]
    if plan['commands'][1][-1] != model:
        raise ValueError('shards use different parent policies')
    results = []
    for shard_number in (0, 1):
        shard_root = root / f'shard-{shard_number}'
        if shard_root.is_symlink() or not shard_root.is_dir():
            raise ValueError('missing or linked shard')
        report = shard(shard_root / 'report.json', shard_root, model, plan['inputSHA256'], shard_number)
        reaches = 0
        for row in rows[2 * shard_number:2 * shard_number + 2]:
            verify_scene(row)
            episode = row['episode']; game_root = shard_root / f'expert-{episode}'
            decisions = lines(game_root / 'decisions.jsonl')
            differences = labels(shard_root / 'data.bin', episode, decisions, HORIZON)
            result, decisions, saved_result = game(row, game_root, differences, HORIZON)
            reaches += saved_result['reaches']
            args = (shard_root / 'data.bin', shard_root / 'map.bin', game_root / 'actor-boundary.bin',
                    game_root / 'map-label-boundary.bin', row['seed'], episode, decisions)
            if row['role'] == 'fit':
                result['boundary'] = boundary.audit(*args, row['firstDeliveryStep'])
            else:
                result['boundary'] = companion_module.audit(*args, saved_result)
            results.append(result)
        if type(report.get('reaches')) is not int or report['reaches'] != reaches:
            raise ValueError('shard reach total differs from games')
    return {'status': 'collected_diagnostic_only', 'fittingEpisodes': 2, 'companionEpisodes': 2,
            'planSHA256': PLAN_SHA256, 'games': results, 'trainingAuthorized': False,
            'scope': ('exact saved original-game parity and same-process buffer checks; prior selection is fitting data; '
                      'not independent camera/map truth, model execution, held-out or physical evidence')}


if __name__ == '__main__':
    raise SystemExit('Disabled: invoke only from a separately reviewed supervised collector.')
