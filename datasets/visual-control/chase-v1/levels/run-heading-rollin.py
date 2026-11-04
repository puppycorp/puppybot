#!/usr/bin/env python3
"""Run paired heading-distribution DAgger pilot, collection, preparation, or training.

Usage: run-heading-rollin.py pilot|collect|prepare|train
Prepare the corresponding pilot/full catalogs first. No stage overwrites output
or removes partial work. Run only on an otherwise idle GPU; `prepare` is CPU.
These are training-layout selection experiments, not held-out qualification.
"""
import hashlib
import importlib.util
import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[4]
S = PROJECT / 'datasets/visual-control/chase-v1/levels'
P = PROJECT / 'build/flex/sim/levels-v2/pitch82'
B = P / 'search-dagger-4workers'
M = P / 'search-dagger-l35-4workers'
PREVIOUS = P / 'search-dagger-l4-matched'
PARENT = PREVIOUS / 'epoch8-pair/treatment'
PILOT = P / 'search-dagger-heading-pilot'
OUTPUT = P / 'search-dagger-heading'
PILOT_CATALOGS = P / 'heading-rollin-pilot-catalogs'
FULL_CATALOGS = P / 'heading-rollin-full-catalogs'
AGGREGATOR = P / '../../levels-v1/map-aggregate'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    obj = importlib.util.module_from_spec(spec); spec.loader.exec_module(obj)
    return obj


catalogs = load('heading_catalogs', S / 'prepare-heading-rollin.py')
pairs = load('heading_pairs', S / 'audit-heading-pairs.py')
shards = load('heading_shards', S / 'audit-shards.py')
base = load('route_runner', S / 'run-route-factorial.py')
overlay = load('heading_overlay', S / 'heading-reflink-overlay.py')


def sha(path):
    return base.sha(path)


def critical(catalog_root, manifest):
    files = [Path(__file__), S / 'prepare-heading-rollin.py', S / 'prepare-route-factorial.py',
             S / 'prepare-bias-validation.py', S / 'audit-heading-pairs.py', S / 'audit-shards.py',
             S / 'audit-multi-shards.py', S / 'audit-student-labels.py', S / 'audit-mixed-students.py',
             S / 'audit-matched-l4.py', S / 'audit-matched-training.py', S / 'mask-stuck.py',
             S / 'heading-reflink-overlay.py',
             PROJECT / 'flex/tests/run-physical-hidden-trial.py', PROJECT / 'flex/tests/run-physical-rescan-trial.py',
             PROJECT / 'flex/tests/run-physical-hybrid-trial.py',
             PROJECT / 'build/flex/control/control', PROJECT / 'build/flex/control/simulator',
             PROJECT / 'build/flex/control/compiler', PROJECT / 'build/flex/control/trainer',
             PROJECT / 'build/flex/rocm-runtime/libamdhip64.so', PROJECT / 'build/flex/sim/puppybot.bin',
             PROJECT / 'puppybot.json', AGGREGATOR, PREVIOUS / 'training-inputs.sha256',
             PREVIOUS / 'training-match.json', PREVIOUS / 'data/data.bin', PREVIOUS / 'data/map.bin',
             catalog_root / 'catalogs.json', PREVIOUS / 'epoch8-pair/manifest.json']
    for name in ('weights.bin', 'policy', 'receipt.json', 'training-receipt.json'):
        files.append(PARENT / name)
    if manifest.get('mode') == 'pilot':
        teacher = P / 'kturn-L4/shard-4'
        files.extend(teacher / name for name in ('data.bin', 'map.bin', 'report.json'))
        for i in range(32):
            game = teacher / f'expert-{i}'
            files.extend(game / name for name in ('chase.jsonl', 'decisions.jsonl', 'scene/case.json'))
    files.extend(sorted((PARENT / 'kernels').iterdir()))
    files.extend(Path(path) for path in manifest['sourceInventorySHA256'])
    for row in manifest['rows']:
        for arm in ('control', 'treatment'):
            scene = catalog_root / f'{arm}-L5/catalogs' / f'shard-{row["shard"]}' / str(row['index'])
            files.extend(scene / name for name in ('case.json', 'environment.bin', 'layout.json'))
    return {str(path): sha(path) for path in files}


def validate_shard(root, mode, arm, manifest, shard):
    rows = [row for row in manifest['rows'] if row['shard'] == shard]
    path = root / f'{arm}-L5' / f'shard-{shard}'
    checksum = sha(PARENT / 'weights.bin'); provenance = hashlib.sha256()
    n, fit = shards.audit(path, True, checksum, PARENT, 7800000, set(), provenance)
    if (n, fit) != ((2, 1) if mode == 'pilot' else (32, 30)):
        raise ValueError('unexpected shard split')
    declaration = json.loads((path / 'report.json').read_text())
    required = {'teacherUsesCameraDetections': True, 'teacherUsesReferenceGeometryForWallsOnly': True,
                'teacherUsesTargetCoordinates': False, 'actorUsesReferencePose': False,
                'actorUsesTargetCoordinates': False}
    if any(declaration.get(key) is not value for key, value in required.items()):
        raise ValueError('collector source declarations differ')
    result = subprocess.run([sys.executable, '-I', str(S / 'audit-student-labels.py'), str(path)],
                            cwd=PROJECT, check=True, text=True, capture_output=True, timeout=180)
    label_report = json.loads(result.stdout)
    if label_report.get('games') != n or label_report.get('teacherStudentDisagreementSteps', 0) < 1:
        raise ValueError('student label disagreement missing')
    starts = []
    for row in rows:
        game = path / f'expert-{row["index"]}'
        for filename, key in (('case.json', 'caseSHA256'), ('environment.bin', f'{arm}EnvironmentSHA256')):
            if sha(game / 'scene' / filename) != row[key]: raise ValueError('collected scene differs from catalog')
        report = json.loads((game / 'result.json').read_text())
        expected = {'seed': row['seed'], 'game': 'fetch', 'controller': 'native neural policy with exploring fetch teacher labels',
                    'level': 5, 'levelPlacement': 'other room', 'maximumBrickDistanceM': .35,
                    'blackout': False, 'policyWeightsSHA256': checksum, 'exploreTeacher': True,
                    'sweepTeacher': False, 'suppliedMap': False, 'taskEventHint': False, 'carryCue': True}
        if any((report.get(k) is not v if type(v) is bool else report.get(k) != v) for k, v in expected.items()):
            raise ValueError('unexpected rollout declaration')
        forbidden = ('straightBiasHundredths', 'straightAfterSteps', 'doorPass', 'doorEarly', 'sampledActions',
                     'actionNoisePercent', 'ensembleMembers', 'ensembleUntilSteps')
        if any(key in report for key in forbidden): raise ValueError('unexpected rollout intervention')
        with (game / 'chase.jsonl').open() as stream: start = json.loads(stream.readline())
        wanted = [-.04, -.04, row[f'{arm}Yaw']]
        if (start.get('event') != 'start' or len(start['robot']) != 3 or
                any(not math.isclose(a, b, rel_tol=0, abs_tol=1e-6) for a, b in zip(start['robot'], wanted))):
            raise ValueError('actual starting pose differs')
        states = [json.loads(line)['state'] for line in (game / 'decisions.jsonl').open()]
        if len(states) != 300 or any(s.get('trainingOracle', {}).get('enabled') is not False or
                                     s['trainingOracle'].get('queries') != 0 for s in states):
            raise ValueError('incomplete observations or oracle activity')
        starts.append({'seed': row['seed'], 'robot': start['robot'], 'brick': start['brick']})
    return {'games': n, 'fittingGames': fit, 'labels': label_report, 'starts': starts}


def collect_one(root, catalog_root, mode, arm, shard, env):
    rows = catalogs.design(mode); matching = [row for row in rows if row['shard'] == shard]
    path = root / f'{arm}-L5'; path.mkdir(exist_ok=True)
    out = path / f'shard-{shard}'
    if out.exists() or out.is_symlink(): raise ValueError('partial or complete shard exists; preserve it')
    monitor = path / f'monitor-{shard}'; monitor.mkdir()
    command = [str(PROJECT / 'build/flex/control/control'), 'collect', '--chase', '--scene-catalog',
               str(catalog_root / f'{arm}-L5/catalogs' / f'shard-{shard}'), '--output', str(out),
               '--episodes', str(len(matching)), '--validation', '1' if mode == 'pilot' else '2',
               '--horizon', '300', '--seed', str(matching[0]['seed']), '--lean', '--wheel-odometry',
               '--policy', str(PARENT), '--fetch', '--explore-teacher', '--level', '5', '--camera-pitch', '82', '--record-map']
    (monitor / 'command.json').write_text(json.dumps(command, indent=2) + '\n')
    status = base.hidden.supervise(command, monitor, env, 600 if mode == 'pilot' else 3600)
    base.require_success(status, monitor)
    shutil.copyfile(monitor / 'client.log', path / f'shard-{shard}.log')


def validate_matched(root, mode, manifest):
    all_reports = {}; visual_difference = {.35: 0, .49: 0}
    shard_count = 1 if mode == 'pilot' else 4
    for shard in range(shard_count):
        a = validate_shard(root, mode, 'control', manifest, shard)
        b = validate_shard(root, mode, 'treatment', manifest, shard)
        for left, right in zip(a['starts'], b['starts']):
            if left['seed'] != right['seed'] or left['brick'] != right['brick'] or left['robot'][:2] != right['robot'][:2]:
                raise ValueError('matched roll-in start, seed or target differs')
        chosen = [row for row in manifest['rows'] if row['shard'] == shard and row['treatmentYaw'] != row['controlYaw']]
        with (root / 'control-L5' / f'shard-{shard}' / 'data.bin').open('rb') as left, \
                (root / 'treatment-L5' / f'shard-{shard}' / 'data.bin').open('rb') as right:
            for row in chosen:
                offset = 32 + row['index'] * 300 * 21212
                left.seek(offset); right.seek(offset)
                x, y = left.read(21168), right.read(21168)
                if len(x) != 21168 or len(y) != 21168: raise ValueError('incomplete initial actor frame')
                visual_difference[row['treatmentYaw']] += int(x != y)
        indices = [1] if mode == 'pilot' else [i for i in range(32) if i >= 30 or i % 3 == 1]
        checked = pairs.compare_shard(root / 'control-L5' / f'shard-{shard}', root / 'treatment-L5' / f'shard-{shard}',
                                      indices, 2 if mode == 'pilot' else 32, 1 if mode == 'pilot' else 30)
        all_reports[str(shard)] = {'control': a, 'treatment': b, 'sharedHeadingBytes': checked}
    required = (.35,) if mode == 'pilot' else (.35, .49)
    if any(visual_difference[yaw] == 0 for yaw in required):
        raise ValueError('changed headings did not change any initial actor frame')
    all_reports['changedHeadingInitialFrames'] = {str(yaw): visual_difference[yaw] for yaw in required}
    return all_reports


def aggregate_pilot(root):
    teacher = P / 'kturn-L4/shard-4'
    for arm in ('control', 'treatment'):
        base.require_capacity(P, 34 * 1024**3)
        student = root / f'{arm}-L5/shard-0'; out = root / f'aggregate-{arm}'
        subprocess.run([str(AGGREGATOR), str(out), '300', '0', str(teacher / 'data.bin'), str(student / 'data.bin')], cwd=PROJECT, check=True, timeout=300)
        with (out / 'mask.json').open('w') as log:
            subprocess.run([sys.executable, '-I', str(S / 'mask-stuck.py'), str(out / 'data.bin'), '--teacher-only', str(teacher), str(student)], cwd=PROJECT, check=True, stdout=log, timeout=300)
        with (root / f'{arm}-preservation.json').open('w') as log:
            subprocess.run([sys.executable, '-I', str(S / 'audit-mixed-students.py'), str(out), '2', str(teacher), str(student)], cwd=PROJECT, check=True, stdout=log, timeout=300)
        base.require_capacity(P, 32 * 1024**3)
    shared_validation = pairs.compare_validation(root / 'aggregate-control', root / 'aggregate-treatment', 34, 31)
    args = [sys.executable, '-I', str(S / 'audit-matched-l4.py'), str(root / 'aggregate-control'), str(root / 'aggregate-treatment'),
            str(teacher), str(teacher), str(root / 'control-L5/shard-0'), str(root / 'treatment-L5/shard-0')]
    result = subprocess.run(args, cwd=PROJECT, check=True, text=True, capture_output=True, timeout=300)
    unchanged = json.loads(result.stdout)
    if unchanged.get('unchangedGames') != 32 or unchanged.get('replacedGames') != 2:
        raise ValueError('pilot unchanged slot audit differs')
    base.require_capacity(P, 34 * 1024**3)
    source = root / 'aggregate-control'; destination = root / 'overlay-treatment'
    before = {name: overlay.physical_map(source / name) for name in ('data.bin', 'map.bin')}
    free_before = shutil.disk_usage(P).free
    clone_report = overlay.overlay(source, [root / 'treatment-L5/shard-0'], destination, 30, 33,
                                   32 * 1024**3, validation_peer=source)
    after = {name: overlay.physical_map(source / name) for name in ('data.bin', 'map.bin')}
    if before != after: raise ValueError('pilot source physical mappings changed during reflink')
    for name in ('data.bin', 'map.bin'):
        subprocess.run(['/usr/bin/cmp', '-s', str(destination / name), str(root / 'aggregate-treatment' / name)], check=True, timeout=300)
    extents = subprocess.run(['btrfs', 'filesystem', 'du', '--raw', '-s', str(source / 'data.bin'), str(destination / 'data.bin')],
                             cwd=PROJECT, check=True, text=True, capture_output=True).stdout
    base.require_capacity(P, 32 * 1024**3)
    overlay_proof = {'manifestSHA256': sha(destination / 'manifest.json'), 'dataSHA256': sha(destination / 'data.bin'),
                     'mapSHA256': sha(destination / 'map.bin'), 'freeBefore': free_before,
                     'freeAfter': shutil.disk_usage(P).free, 'sourcePhysicalMap': before, 'extents': extents,
                     'validation': clone_report['pairedValidation'],
                     'scope': 'scratch-size pilot matches native aggregation and mask; allocation is not a full-scale guarantee'}
    return {'validation': shared_validation, 'unchanged': unchanged,
            'overlayProof': overlay_proof,
            'aggregateHashes': {arm: {name: sha(root / f'aggregate-{arm}' / name) for name in ('data.bin', 'map.bin')}
                                for arm in ('control', 'treatment')}}


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ('pilot', 'collect', 'prepare', 'train'):
        raise SystemExit(__doc__)
    stage = sys.argv[1]; os.chdir(PROJECT)
    with base.acquire_lock(P / '.l4-matched.lock'):
        base.require_capacity(P, 40 * 1024**3 if stage in ('pilot', 'collect') else 34 * 1024**3)
        if stage in ('prepare', 'train'):
            raise RuntimeError('full aggregation and matched training are not implemented yet')
        root, catalog_root = (PILOT, PILOT_CATALOGS) if stage == 'pilot' else (OUTPUT, FULL_CATALOGS)
        base.require_new_output(root)
        manifest = json.loads((catalog_root / 'catalogs.json').read_text())
        mode = 'pilot' if stage == 'pilot' else 'full'
        if manifest.get('mode') != mode: raise ValueError('wrong catalog mode')
        catalogs.verify(catalog_root, manifest)
        base.package.verify(PREVIOUS / 'control-s0', PREVIOUS / 'treatment-s0', PREVIOUS / 'epoch8-pair')
        subprocess.run(['/usr/bin/sha256sum', '-c', str(PREVIOUS / 'training-inputs.sha256')], cwd=PROJECT, check=True, stdout=subprocess.DEVNULL)
        if stage == 'collect':
            pilot_report = json.loads((PILOT / 'pilot-report.json').read_text())
            if pilot_report.get('status') != 'passed' or pilot_report.get('parentWeightsSHA256') != sha(PARENT / 'weights.bin'):
                raise ValueError('matching pilot has not passed')
            for path, expected in json.loads((PILOT / 'inputs.json').read_text()).items():
                if sha(Path(path)) != expected: raise ValueError('pilot input changed')
            small_training = load('small_training_pilot', S / 'run-heading-trainer-pilot.py')
            small_training.verify_small_pilot()
        inputs = critical(catalog_root, manifest)
        root.mkdir(); (root / 'inputs.json').write_text(json.dumps(inputs, sort_keys=True, indent=2) + '\n')
        env = {'PATH': '/usr/bin:/bin', 'HOME': str(Path.home()), 'PUPPYBOT_PROJECT': str(PROJECT),
               'LD_LIBRARY_PATH': str(PROJECT / 'build/flex/rocm-runtime'), 'SDL_VIDEODRIVER': 'offscreen'}
        for arm in ('control', 'treatment'):
            for shard in range(1 if mode == 'pilot' else 4):
                base.require_capacity(P, 34 * 1024**3)
                if critical(catalog_root, manifest) != inputs: raise ValueError('collection inputs changed before shard')
                collect_one(root, catalog_root, mode, arm, shard, env)
                if critical(catalog_root, manifest) != inputs: raise ValueError('collection inputs changed after shard')
                base.require_capacity(P, 32 * 1024**3)
        reports = validate_matched(root, mode, manifest)
        combined = aggregate_pilot(root) if mode == 'pilot' else None
        catalogs.verify(catalog_root, manifest)
        if critical(catalog_root, manifest) != inputs: raise ValueError('collection inputs changed during final audit')
        base.package.verify(PREVIOUS / 'control-s0', PREVIOUS / 'treatment-s0', PREVIOUS / 'epoch8-pair')
        report = {'status': 'passed', 'mode': mode, 'parentWeightsSHA256': sha(PARENT / 'weights.bin'),
                  'reports': reports, 'pilotAggregate': combined,
                  'scope': 'training-layout roll-ins; actor carries simulator-derived task state; no heldout or physical claim'}
        (root / ('pilot-report.json' if mode == 'pilot' else 'collection-report.json')).write_text(json.dumps(report, sort_keys=True, indent=2) + '\n')
        print(json.dumps({'status': 'passed', 'mode': mode, 'output': str(root)}))


if __name__ == '__main__': main()
