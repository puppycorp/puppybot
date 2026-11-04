#!/usr/bin/env python3
"""Audit paired, pre-registered virtual-fetch holdout games.

Usage: audit-heldout.py HOLDOUT_CATALOG MODEL EVALUATION_DIR

The report is provisional: it verifies recorded game/scene/model identities
and a frozen input manifest, but cannot prove exhaustive model ancestry or
physical grasp/release. Never use it to select a candidate on these games.
"""
import hashlib
import importlib.util
import json
import math
import re
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[4]


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def input_hashes(path):
    values = {}
    for line in path.read_text().splitlines():
        if line.startswith('\\') or '  ' not in line:
            raise ValueError('unsupported or malformed checksum record')
        checksum, name = line.split('  ', 1)
        if not re.fullmatch('[0-9a-f]{64}', checksum) or not Path(name).is_absolute():
            raise ValueError('input checksums require absolute paths and SHA256')
        resolved = str(Path(name).resolve())
        if resolved in values and values[resolved] != checksum:
            raise ValueError(f'conflicting input hashes: {name}')
        values[resolved] = checksum
    return values


def require_pinned(values, path):
    path = path.resolve()
    if values.get(str(path)) != digest(path):
        raise ValueError(f'input absent or changed in pre-run manifest: {path}')


def load_helpers():
    helpers = {}
    for name, file in [('selection', 'audit-selection.py'), ('goal', 'goal-report.py')]:
        spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(file))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        helpers[name] = module
    return helpers


def backforth_steps(rows, start):
    poses = [start] + [row['state']['pose'] for row in rows[:-1]]
    drive = []
    for row in rows:
        action = row['action']
        if len(action) != 2 or any(not isinstance(x, (int, float)) or not math.isfinite(x) for x in action):
            raise ValueError('invalid action in decisions')
        drive.append((action[1] > 0) - (action[1] < 0))
    if any(len(pose) != 3 or any(not isinstance(x, (int, float)) or not math.isfinite(x) for x in pose) for pose in poses):
        raise ValueError('invalid pose in decisions')
    steps, marked = 0, -1
    for t in range(20, len(rows)):
        flips = sum(drive[k] * drive[k - 1] < 0 for k in range(t - 19, t))
        turn = abs((poses[t][2] - poses[t - 20][2] + math.pi) % (2 * math.pi) - math.pi)
        if flips >= 4 and math.dist(poses[t][:2], poses[t - 20][:2]) < 0.25 and turn < math.radians(45):
            steps += t - max(marked, t - 20)
            marked = t
    return steps


def load_games(root, expected, model, level, helpers):
    games, parts = {}, set()
    files = sorted(root.glob('*/[0-9]*/result.json' if model else '*/expert-*/result.json'))
    for file in files:
        directory, part = file.parent, file.parent.parent
        result = json.loads(file.read_text())
        seed = result['seed']
        if seed in games or seed not in expected:
            raise ValueError(f'duplicate or unexpected seed {seed}: {directory}')
        if part not in parts:
            if model:
                helpers['selection'].snapshot(part / 'policy', model)
            else:
                report = json.loads((part / 'report.json').read_text())
                if (report.get('complete') is not True or report.get('studentDriven') is not False
                        or report.get('teacher') != 'exploring fetch teacher' or report.get('episodes') != 8
                        or report.get('sequenceLength') != 300 or report.get('seed') != seed - expected[seed]['index'] % 8
                        or report.get('teacherUsesCameraDetections') is not True or report.get('teacherUsesTargetCoordinates') is not False):
                    raise ValueError(f'invalid teacher shard report: {part}')
            for log in (root / (part.name + '.log'), part / 'policy.log') if model else (root / (part.name + '.log'),):
                if not log.is_file() or re.search(r'\btimed out\b|\btimeout\b', log.read_text(errors='replace'), re.I):
                    raise ValueError(f'missing log or timeout: {log}')
            parts.add(part)
        if (result.get('game') != 'fetch' or result['steps'] != 300 or result['actionSeconds'] != 60 or result['level'] != level
                or result['blackout'] is not False or result.get('suppliedMap') is not False
                or result.get('taskEventHint') is not False or result.get('carryCue') is not True
                or result.get('maximumBrickDistanceM') != 0.35):
            raise ValueError(f'invalid task, horizon or actor inputs: {directory}')
        if type(result.get('deliveries')) is not int or result['deliveries'] < 0:
            raise ValueError(f'invalid delivery count: {directory}')
        expected_name = {1: 'in view', 2: 'just off view', 3: 'same room out of view', 4: 'doorway drill', 5: 'other room'}[level]
        if result.get('levelPlacement') != expected_name:
            raise ValueError(f'wrong level placement: {directory}')
        if model:
            receipt = json.loads((model / 'receipt.json').read_text())
            if (result.get('controller') != 'native neural policy' or result.get('policyWeightsSHA256') != receipt['weightsSHA256']
                    or result.get('exploreTeacher') is not False or result.get('ensembleMembers', 1) != 1):
                raise ValueError(f'wrong candidate policy: {directory}')
        elif result.get('controller') != 'exploring fetch teacher' or result.get('exploreTeacher') is not True:
            raise ValueError(f'wrong teacher: {directory}')
        row = expected[seed]
        if part.name != str(row['index'] // 8) or directory.name != (str(seed) if model else f'expert-{row["index"] % 8}'):
            raise ValueError(f'game is in the wrong catalog part: {directory}')
        for name, field in (('case.json', 'caseSHA256'), ('environment.bin', 'environmentSHA256')):
            if digest(directory / 'scene' / name) != row[field]:
                raise ValueError(f'scene mismatch: {directory}/{name}')
        with (directory / 'decisions.jsonl').open() as stream:
            decisions = [json.loads(line) for line in stream]
        with (directory / 'chase.jsonl').open() as stream:
            events = [json.loads(line) for line in stream]
        if len(decisions) != 300 or not events or events[0].get('event') != 'start' or sum(e.get('event') == 'delivery' for e in events) != result['deliveries']:
            raise ValueError(f'incomplete or inconsistent trace: {directory}')
        start, planned = events[0].get('robot'), row.get('startPose')
        if (not isinstance(start, list) or not isinstance(planned, list) or len(start) != 3 or len(planned) != 3
                or any(not math.isfinite(float(a)) or not math.isfinite(float(b)) or abs(a - b) > 1e-5 for a, b in zip(start, planned))):
            raise ValueError(f'initial robot pose differs from catalog: {directory}')
        if model and (not isinstance(result.get('backForthSteps'), int) or isinstance(result['backForthSteps'], bool)
                      or not 0 <= result['backForthSteps'] <= 300 or result['backForthSteps'] != backforth_steps(decisions, start)):
            raise ValueError(f'invalid or inconsistent back-and-forth metric: {directory}')
        native = directory / 'native.log'
        if not native.is_file() or re.search(r'\btimed out\b|\btimeout\b', native.read_text(errors='replace'), re.I):
            raise ValueError(f'missing native log or timeout: {directory}')
        games[seed] = (result, decisions, events, directory)
    if set(games) != set(expected) or len(parts) != 4:
        raise ValueError(f'expected 32 games in four parts: {root}')
    return games


def main():
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    catalog, model, output = map(Path, sys.argv[1:])
    manifest = json.loads((catalog / 'manifest.json').read_text())
    registration = json.loads((output / 'registration.json').read_text())
    if manifest.get('status') != 'reserved_not_evaluated' or manifest.get('task') != 'virtual-fetch':
        raise ValueError('not a reserved virtual-fetch catalog')
    if len(manifest.get('rows', [])) != 160:
        raise ValueError('held-out catalog must contain 160 rows')
    for level in range(1, 6):
        rows = [row for row in manifest['rows'] if row.get('level') == level]
        if len(rows) != 32 or {row.get('index') for row in rows} != set(range(32)):
            raise ValueError(f'invalid held-out indices for level {level}')
        for row in rows:
            index = row['index']
            layout = 226 + index if level < 4 else 227 + 2 * index
            if (row.get('seed') != 1700000000 + level * 100 + index or row.get('layoutId') != layout
                    or row.get('scene') != f'generated/{layout}/{index % 16}'):
                raise ValueError(f'unexpected held-out mapping at level {level}, index {index}')
    if (registration.get('registeredBeforePlay') is not True or registration.get('catalogSHA256') != digest(catalog / 'manifest.json')
            or registration.get('inputsSHA256') != digest(output / 'inputs.sha256')):
        raise ValueError('registered manifest changed')
    if registration.get('candidateWeightsSHA256') != digest(model / 'weights.bin'):
        raise ValueError('registered candidate changed')
    subprocess.run(['sha256sum', '-c', str((output / 'inputs.sha256').resolve())], check=True, stdout=subprocess.DEVNULL)
    inputs = input_hashes(output / 'inputs.sha256')
    required = [catalog / 'manifest.json', model / 'receipt.json', model / 'weights.bin', model / 'policy',
                PROJECT / 'build/flex/control/control', PROJECT / 'build/flex/control/simulator',
                PROJECT / 'build/flex/rocm-runtime/libamdhip64.so', Path(__file__),
                Path(__file__).with_name('evaluate-heldout.sh'), Path(__file__).with_name('audit-selection.py'),
                Path(__file__).with_name('goal-report.py')]
    receipt = json.loads((model / 'receipt.json').read_text())
    kernels = receipt.get('kernels')
    if not isinstance(kernels, dict) or not kernels or any(Path(name).name != name for name in kernels):
        raise ValueError('invalid candidate kernel manifest')
    required.extend(model / 'kernels' / name for name in kernels)
    for path in required:
        require_pinned(inputs, path)
    helpers = load_helpers()
    results = {}
    for level in range(1, 6):
        rows = [row for row in manifest['rows'] if row['level'] == level]
        expected = {row['seed']: row for row in rows}
        if len(rows) != 32 or len(expected) != 32:
            raise ValueError(f'bad catalog count for level {level}')
        for row in rows:
            source = catalog / row['scene']
            if catalog.resolve() not in source.resolve().parents:
                raise ValueError(f'catalog scene escapes catalog: {source}')
            metadata = json.loads((source / 'layout.json').read_text())
            if (metadata.get('layoutId') != row['layoutId'] or metadata.get('fit') is not False
                    or metadata.get('reservedHeldOut') is not True or metadata.get('startPose') != row['startPose']
                    or len(metadata.get('rooms', [])) != 1 + row['layoutId'] % 2):
                raise ValueError(f'invalid reserved scene metadata: {source}')
            for name, key in (('case.json', 'caseSHA256'), ('environment.bin', 'environmentSHA256'), ('layout.json', 'layoutSHA256')):
                if digest(source / name) != row[key]:
                    raise ValueError(f'catalog input changed: {source}/{name}')
                require_pinned(inputs, source / name)
        candidate = load_games(output / f'L{level}' / 'candidate', expected, model, level, helpers)
        teacher = load_games(output / f'L{level}' / 'teacher', expected, None, level, helpers)
        for seed in expected:
            if candidate[seed][2][0] != teacher[seed][2][0]:
                raise ValueError(f'teacher and candidate starts differ: {seed}')
        games = list(candidate.values())
        delivered = sum(g[0]['deliveries'] > 0 for g in games)
        first = sum(any(r['state']['findReturn']['phase'] == 'return' for r in g[1]) for g in games)
        deliveries = sum(g[0]['deliveries'] for g in games)
        teacher_deliveries = sum(g[0]['deliveries'] for g in teacher.values())
        backforth = sum(g[0]['backForthSteps'] for g in games) / (32 * 300)
        entry = {'games': 32, 'gamesWithDelivery': delivered, 'firstReturnGames': first,
                 'deliveriesPerMinute': deliveries / 32, 'teacherDeliveriesPerMinute': teacher_deliveries / 32,
                 'backForthShare': backforth,
                 'longSearchReturnShare': sum(helpers['goal'].long_search_share(g[1]) for g in games) / 32,
                 'deliveryThresholdMet': delivered >= 29, 'teacherRateThresholdMet': deliveries >= teacher_deliveries,
                 'backForthThresholdMet': backforth < 0.02}
        if level == 3:
            entry['firstPickupThresholdMet'] = first >= 29
        if level == 4:
            door = [helpers['goal'].doorway(g[2], g[3]) for g in games]
            total, done = sum(x[0] for x in door), sum(x[1] for x in door)
            entry.update({'doorwayCases': total, 'doorwayDelivered': done,
                          'doorwayThresholdMet': bool(total) and done / total >= 0.8})
        results[str(level)] = entry
    checks = [v for entry in results.values() for k, v in entry.items() if k.endswith('ThresholdMet')]
    print(json.dumps({'status': 'provisional_virtual_only', 'numericThresholdsMet': all(checks), 'levels': results,
                      'limitations': ['physical grasp/release not measured', 'model ancestry and semantic scene independence not proven',
                                      'long search return-to-pose is a partial diagnostic, not a complete loop detector']}, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
        raise SystemExit(f'Invalid held-out comparison: {error}')
