#!/usr/bin/env python3
"""Register fixed full-epoch matched training only after verified smoke."""
import importlib.util
import json
import os
import sys
from pathlib import Path
from unittest import mock


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
P = ROOT / 'build/flex/sim/levels-v2/pitch82'
PLAN = P / 'parent-route-full-pair-plan-v1.json'
OUTPUT = P / 'parent-route-full-pair-v1'
BUILD = P / 'parent-route-mirror-journal-trainer-build-v1'
BUILD_SHA256 = 'dc705355cad7d71675e6cd98cc7663bd8d3f1b77910723d77612079b16095d57'
TRAINER_SHA256 = '5e716e9caa80b97b69efdf5750afbb4c8540da757be22241803aabe699d78c1f'
CONTROL_SHA256 = 'cb567af95ad410e3d06f830f45576974add02074a9d90f797b9049e26fa8b6d6'
SMOKE_OUTPUT = P / 'parent-route-paired-smoke-v1'
WALL = 7200
GIB = 1024 ** 3


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


smoke = load('full_pair_prior_smoke_monitor', ROOT / 'experiments/parent-route-paired-smoke-v1/monitor.py')
builder = load('full_pair_journal_build', ROOT / 'experiments/parent-route-mirror-journal-v1/build.py')
journal = load('full_pair_schedule_audit', ROOT / 'experiments/parent-route-mirror-journal-v1/audit.py')
sha = smoke.audit.sha


def read(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError('missing or linked full-pair evidence: ' + str(path))
    return json.loads(path.read_text())


def smoke_evidence():
    """Require a completed, independently reconstructible one-update smoke."""
    complete_path = SMOKE_OUTPUT / 'completion.json'
    complete = read(complete_path)
    if complete.get('status') != 'one_step_diagnostic_only':
        raise ValueError('one-update smoke is incomplete or failed')
    frozen = smoke.plan.verify(); plan_hash = sha(smoke.plan.PLAN)
    links = {'planSHA256': smoke.plan.PLAN, 'coordinatorSHA256': SMOKE_OUTPUT / 'coordinator-result.json',
             'guardianResultSHA256': SMOKE_OUTPUT / 'guardian-result.json',
             'guardianTelemetrySHA256': SMOKE_OUTPUT / 'guardian-telemetry.jsonl'}
    if any(complete.get(key) != sha(path) for key, path in links.items()):
        raise ValueError('one-update smoke completion links differ')
    launch, guardian = read(SMOKE_OUTPUT / 'launcher.json'), read(SMOKE_OUTPUT / 'guardian-launch.json')
    if (launch.get('planSHA256') != plan_hash or launch.get('environment') != smoke.plan.environment() or
            not isinstance(launch.get('argv'), list) or not launch['argv'] or
            type(guardian.get('parentPID')) is not int or launch['argv'][-1] != str(guardian['parentPID']) or
            type(guardian.get('guardianPID')) is not int):
        raise ValueError('smoke launcher/guardian identity differs')
    # The old local verifier compares to its original parent pid. Reuse it
    # against the recorded pid without claiming that historical process lives.
    with mock.patch.object(smoke.plan.paired.os, 'getpid', return_value=guardian['parentPID']):
        smoke.verify_guardian(guardian['guardianPID'])
    coordinator = read(SMOKE_OUTPUT / 'coordinator-result.json')
    hashes = smoke.evidence_hashes()
    for name in ('invocation.json', 'supervisor-result.json', 'client.log'):
        hashes[f'supervisor-final/{name}'] = sha(SMOKE_OUTPUT / 'supervisor-final' / name)
    final = read(SMOKE_OUTPUT / 'final-result.json')
    final_supervisor = SMOKE_OUTPUT / 'supervisor-final'
    if (read(final_supervisor / 'invocation.json') != {'argv': smoke.command('final_check'),
            'environment': smoke.plan.environment(), 'wallSeconds': 2400} or
            not smoke.clean(read(final_supervisor / 'supervisor-result.json'))):
        raise ValueError('smoke final supervisor differs')
    if (coordinator.get('status') != 'one_step_diagnostic_only' or coordinator.get('planSHA256') != plan_hash or
            coordinator.get('evidenceSHA256') != hashes or final.get('status') != 'one_step_diagnostic_only' or
            final.get('planSHA256') != plan_hash or final.get('inventory') != smoke.inventory() or
            final.get('report') != smoke.verify_arms() or smoke.plan.verify() != frozen or sha(smoke.plan.PLAN) != plan_hash):
        raise ValueError('smoke evidence or final audit differs')
    return {'completionSHA256': sha(complete_path), 'planSHA256': plan_hash,
            'finalResultSHA256': sha(SMOKE_OUTPUT / 'final-result.json'),
            'launcherSHA256': sha(SMOKE_OUTPUT / 'launcher.json'),
            'guardianLaunchSHA256': sha(SMOKE_OUTPUT / 'guardian-launch.json'),
            'baselineMarkerSHA256': sha(SMOKE_OUTPUT / 'baseline-passed.json'),
            'scope': 'local retained smoke consistency, not historical process or device attestation'}


def command(arm):
    if arm not in ('control', 'treatment'):
        raise ValueError('unknown full-pair arm')
    return [str(BUILD / 'control'), 'train', '--output', str(OUTPUT / arm), '--seed', '7120000',
            '--learning-rate-micros', '100', '--data', str(smoke.plan.DATA / arm / 'data.bin'),
            '--memory-map', str(smoke.plan.DATA / arm / 'map.bin'), '--transition-weight-one',
            '--policy', str(smoke.plan.PARENT), '--categorical', '--mirror-augment', '--carry-cue',
            '--epochs', '1', '--batch', '2', '--checkpoint-every', '1']


def stable_sha(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError('missing or linked aggregate input: ' + str(path))
    before = path.stat(); digest = sha(path); after = path.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_nlink) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_nlink):
        raise ValueError('aggregate input changed while hashing: ' + str(path))
    return digest


def runtime_chain(path):
    """Record each exact HIP symlink and final target, rejecting cycles."""
    path = Path(path); seen = set(); chain = {}
    while path.is_symlink():
        if str(path) in seen:
            raise ValueError('GPU runtime symlink cycle')
        seen.add(str(path)); target = os.readlink(path); chain[str(path)] = 'link:' + target
        path = (path.parent / target) if not os.path.isabs(target) else Path(target)
    if not path.is_file():
        raise ValueError('GPU runtime target missing')
    chain[str(path)] = 'sha256:' + stable_sha(path)
    return chain


def smoke_small_inventory(expected):
    """Check every smoke output name and small hash; defer data clones to deep checks."""
    if not isinstance(expected, dict):
        raise ValueError('smoke inventory missing')
    observed = {}; skipped = {'control/data.bin', 'treatment/data.bin'}
    def walk_error(error):
        raise error
    for arm in ('control', 'treatment'):
        root = SMOKE_OUTPUT / arm
        if root.is_symlink() or not root.is_dir():
            raise ValueError('smoke model output missing or linked')
        for directory, children, names in os.walk(root, followlinks=False, onerror=walk_error):
            parent = Path(directory)
            for name in children:
                child = parent / name
                if child.is_symlink() or not child.is_dir():
                    raise ValueError('unsafe smoke directory')
            for name in names:
                path = parent / name; relative = str(path.relative_to(SMOKE_OUTPUT))
                if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1:
                    raise ValueError('unsafe smoke file')
                entry = expected.get(relative)
                if not isinstance(entry, dict) or path.stat().st_size != entry.get('size'):
                    raise ValueError('smoke output name or size changed')
                if relative not in skipped and stable_sha(path) != entry.get('sha256'):
                    raise ValueError('smoke non-data output changed')
                observed[relative] = entry
    if observed != expected or not skipped.issubset(observed):
        raise ValueError('smoke output inventory changed')
    return {'files': len(observed), 'deferredFullDataHashes': sorted(skipped)}


def verify_smoke_data_copies(frozen):
    """Close a deep boundary by hashing both clones against the sealed smoke inventory."""
    final_path = SMOKE_OUTPUT / 'final-result.json'
    seal = frozen['smoke']['finalResultSHA256']
    if stable_sha(final_path) != seal:
        raise ValueError('sealed smoke final result changed')
    inventory = read(final_path).get('inventory')
    if not isinstance(inventory, dict):
        raise ValueError('sealed smoke inventory missing')
    for arm in ('control', 'treatment'):
        root = SMOKE_OUTPUT / arm; path = root / 'data.bin'
        entry = inventory.get(f'{arm}/data.bin')
        if (root.is_symlink() or not root.is_dir() or path.is_symlink() or not path.is_file() or
                path.stat().st_nlink != 1 or not isinstance(entry, dict) or
                path.stat().st_size != entry.get('size') or stable_sha(path) != entry.get('sha256')):
            raise ValueError('sealed smoke data copy changed: ' + arm)
    if stable_sha(final_path) != seal:
        raise ValueError('sealed smoke final result changed during data check')


def light_inputs():
    """Boundary recheck: actual training data once, all pinned small evidence."""
    smoke_plan = read(smoke.plan.PLAN); inputs = smoke_plan.get('inputs', {})
    files = inputs.get('files')
    if not isinstance(files, dict) or not files:
        raise ValueError('smoke pinned sources missing')
    for name, digest in files.items():
        path = Path(name)
        if not path.is_file() or sha(path) != digest:
            raise ValueError('smoke source or runtime changed: ' + name)
    prior = smoke.plan.paired.plan.collector.registration.PRIOR
    prior_runtime = read(prior).get('runtime')
    chain = runtime_chain(ROOT / 'build/flex/rocm-runtime/libamdhip64.so')
    if not isinstance(prior_runtime, dict) or chain != prior_runtime:
        raise ValueError('registered HIP runtime chain changed')
    data = {}
    for arm, expected in smoke.audit.DATA.items():
        data[arm] = {}
        for name, digest in (('data.bin', expected), ('map.bin', smoke.audit.MAP)):
            path = smoke.plan.DATA / arm / name; actual = stable_sha(path)
            if actual != digest:
                raise ValueError('paired training input changed: ' + str(path))
            data[arm][name] = actual
    build = read(BUILD / 'build.json')
    source = BUILD / 'flex-source'
    entries = tuple(source / 'control' / name for name in ('main.flex', 'train.flex', 'reflink-probe.flex'))
    builder.require_local_tree(source)
    link = BUILD / 'build'
    if (build.get('sourcePins') != builder.pins() or build.get('privateSource') != builder.tree(source) or
            build.get('imports') != builder.imports(entries) or
            build.get('compilerSHA256') != stable_sha(builder.COMPILER) or
            not link.is_symlink() or link.resolve(strict=True) != (ROOT / 'build').resolve(strict=True) or
            build.get('binaries') != {name: stable_sha(BUILD / name) for name in ('control', 'trainer', 'reflink-probe')}):
        raise ValueError('journal trainer source, compiler or binaries changed')
    if (build.get('status') != 'cpu_build_only' or build.get('dimensions') != [1031, 935, 300] or
            build.get('auxiliaryMaskEpisodeRange') != [928, 935] or sha(BUILD / 'build.json') != BUILD_SHA256 or
            build.get('binaries', {}).get('trainer') != TRAINER_SHA256 or
            build.get('binaries', {}).get('control') != CONTROL_SHA256):
        raise ValueError('journal trainer dimensions, mask or binary differ')
    smoke_final = read(SMOKE_OUTPUT / 'final-result.json')
    output_check = smoke_small_inventory(smoke_final.get('inventory'))
    evidence = smoke.evidence_hashes()
    for name in ('invocation.json', 'supervisor-result.json', 'client.log'):
        evidence[f'supervisor-final/{name}'] = stable_sha(SMOKE_OUTPUT / 'supervisor-final' / name)
    refs = (smoke.plan.PLAN, SMOKE_OUTPUT / 'completion.json', SMOKE_OUTPUT / 'coordinator-result.json',
            SMOKE_OUTPUT / 'guardian-launch.json', SMOKE_OUTPUT / 'guardian-result.json',
            SMOKE_OUTPUT / 'guardian-telemetry.jsonl', SMOKE_OUTPUT / 'launcher.json',
            SMOKE_OUTPUT / 'baseline-passed.json', smoke.plan.paired.plan.PLAN,
            smoke.plan.paired.plan.collector.registration.PRIOR,
            smoke.plan.paired.plan.collector.registration.PRIOR_RECEIPT,
            smoke.plan.paired.plan.collector.registration.PLAN)
    refs = {str(path): stable_sha(path) for path in refs}
    paths = (Path(__file__).resolve(), HERE / 'audit.py', HERE / 'monitor.py',
             ROOT / 'experiments/parent-route-mirror-journal-v1/build.py',
             ROOT / 'experiments/parent-route-mirror-journal-v1/transform.py',
             ROOT / 'experiments/parent-route-mirror-journal-v1/audit.py',
             Path(sys.executable).resolve(), BUILD / 'build.json', BUILD / 'trainer', BUILD / 'control')
    pins = {str(path): stable_sha(path) for path in paths}
    return {'smokePlanSHA256': sha(smoke.plan.PLAN), 'smokeEvidenceSHA256': evidence,
            'smokeOutputInventory': output_check, 'lineageReceiptSHA256': refs,
            'runtimeChain': chain, 'dataSHA256': data, 'journalBuildSHA256': sha(BUILD / 'build.json'),
            'privateBinaries': build['binaries'], 'sourcePins': pins,
            'scope': ('all paired training data, exact runtime links, small smoke files and pinned sources; '
                      'smoke data-copy bytes are checked at deep registration/final boundaries')}


def plan_fields(first, light):
    refs = light['lineageReceiptSHA256']
    links = {'completionSHA256': SMOKE_OUTPUT / 'completion.json',
             'launcherSHA256': SMOKE_OUTPUT / 'launcher.json',
             'guardianLaunchSHA256': SMOKE_OUTPUT / 'guardian-launch.json',
             'baselineMarkerSHA256': SMOKE_OUTPUT / 'baseline-passed.json'}
    if (any(first[key] != refs[str(path)] for key, path in links.items()) or
            first['planSHA256'] != light['smokePlanSHA256'] or
            first['finalResultSHA256'] != light['smokeEvidenceSHA256']['final-result.json']):
        raise ValueError('smoke evidence changed during registration')
    return {'schema': 'puppybot.parent-route-full-pair-plan.v1', 'status': 'registered_before_training',
            'smoke': first, 'lightInputs': light,
            'commands': {arm: command(arm) for arm in ('control', 'treatment')},
            'environment': smoke.plan.environment(), 'arms': ['control', 'treatment'],
            'shape': {'episodes': 1031, 'fitting': 935, 'validation': 96, 'horizon': 300},
            'training': {'seed': 7120000, 'epochs': 1, 'batch': 2, 'learningRateMicros': 100,
                         'optimizer': 'fresh Adam per arm; original parent weights only', 'optimizerSteps': 468,
                         'carryCue': True, 'categorical': True, 'mirrorAugment': True, 'memoryMap': True,
                         'checkpointRule': 'fixed epoch-1; not validation-selected'},
            'thresholds': {'startupGiB': 38, 'activeGiB': 34, 'emergencyGiB': 32,
                           'baselineFreeVramGiB': 6, 'activeFreeVramGiB': 2,
                           'baselineSecondsPerArm': 30, 'perArmSeconds': WALL, 'pairOverallSeconds': 7500},
            'scope': 'matched exploratory training on reused development data; no automatic promotion, held-out or physical claim'}



def snapshot():
    first = smoke_evidence()
    verified_build = builder.verify()
    light = light_inputs()
    if verified_build.get('binaries') != light['privateBinaries']:
        raise ValueError('journal build changed during registration')
    return plan_fields(first, light)


def freeze():
    if PLAN.exists() or PLAN.is_symlink() or OUTPUT.exists() or OUTPUT.is_symlink():
        raise FileExistsError('existing full-pair plan or output; retain it')
    value = snapshot()
    if plan_fields(value['smoke'], light_inputs()) != value:
        raise ValueError('full-pair inputs changed during registration')
    with PLAN.open('x') as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False); stream.write('\n')
        stream.flush(); os.fsync(stream.fileno())
    if verify() != value:
        raise ValueError('full-pair registration readback differs')
    verify_smoke_data_copies(value)
    return value


def verify():
    frozen = read(PLAN)
    if plan_fields(frozen['smoke'], light_inputs()) != frozen:
        raise ValueError('full-pair plan or inputs changed')
    return frozen


def deep_check(frozen):
    if smoke_evidence() != frozen['smoke']:
        raise ValueError('deep smoke evidence changed')


if __name__ == '__main__':
    raise SystemExit('Disabled pending completed smoke and independent review.')
