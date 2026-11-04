#!/usr/bin/env python3
"""Fixed one-update paired GPU smoke plan; registration is separate from execution."""
import importlib.util
import json
import os
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
P = ROOT / 'build/flex/sim/levels-v2/pitch82'
DATA = P / 'parent-route-paired-aggregate-v1'
DATA_MONITOR = P / 'parent-route-paired-aggregate-monitored-v1'
BUILD = P / 'parent-route-paired-trainer-build-v1'
PARENT = P / 'search-dagger-l35-4workers/student-s1'
PLAN = P / 'parent-route-paired-smoke-plan-v1.json'
OUTPUT = P / 'parent-route-paired-smoke-v1'
GIB = 1024 ** 3
WALL = 7200


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


audit = load('pair_smoke_audit', HERE / 'audit.py')
build = load('pair_smoke_build', ROOT / 'experiments/parent-route-paired-trainer-v1/build.py')
paired = load('pair_smoke_data_supervisor', ROOT / 'experiments/parent-route-paired-aggregate-v1/supervise.py')
design = load('pair_smoke_parent', ROOT / 'experiments/outbound-five-trainer-v1/design.py')
sha = audit.sha


def command(arm):
    if arm not in audit.DATA: raise ValueError('unknown smoke arm')
    return [str(BUILD / 'control'), 'train', '--output', str(OUTPUT / arm), '--seed', str(audit.SEED),
            '--learning-rate-micros', '100', '--data', str(DATA / arm / 'data.bin'),
            '--memory-map', str(DATA / arm / 'map.bin'), '--transition-weight-one', '--policy', str(PARENT),
            '--categorical', '--mirror-augment', '--carry-cue', '--epochs', '1', '--batch', '2',
            '--checkpoint-every', '1', '--max-optimizer-steps', '1']


def environment():
    return {'PATH': '/usr/bin:/bin', 'HOME': str(Path.home()), 'PUPPYBOT_PROJECT': str(ROOT),
            'LD_LIBRARY_PATH': str(ROOT / 'build/flex/rocm-runtime'), 'SDL_VIDEODRIVER': 'offscreen'}


def snapshot():
    """Recheck the prior frozen chain, actual data bytes, private trainer and runtime."""
    completion = DATA_MONITOR / 'completion.json'
    if sha(completion) != 'fd8ff0ecb716b50fbc3f196aff1da313cf0e8850b447c2b3e1e7b88154cf56ab':
        raise ValueError('paired data completion differs')
    completed = json.loads(completion.read_text())
    if completed.get('status') != 'candidate_data_only' or completed.get('trainingAuthorized') is not False:
        raise ValueError('paired data completion is not diagnostic')
    frozen = paired.plan.verify_plan(); pair_plan_hash = sha(paired.plan.PLAN)
    result = json.loads((DATA_MONITOR / 'coordinator-result.json').read_text())
    links = {'coordinatorSHA256': 'coordinator-result.json', 'guardianLaunchSHA256': 'guardian-launch.json',
             'guardianResultSHA256': 'guardian-result.json', 'guardianTelemetrySHA256': 'guardian-telemetry.jsonl'}
    if (completed.get('planSHA256') != pair_plan_hash or
            any(completed.get(key) != sha(DATA_MONITOR / name) for key, name in links.items()) or
            result.get('status') != 'candidate_data_only' or result.get('trainingAuthorized') is not False or
            result.get('planSHA256') != pair_plan_hash or
            result.get('workerSHA256') != sha(DATA_MONITOR / 'worker-result.json') or
            result.get('finalSHA256') != sha(DATA_MONITOR / 'final-result.json') or
            result.get('supervisorSHA256') != paired.supervisor_hashes()):
        raise ValueError('paired guardian or coordinator lineage differs')
    paired.verify_phase_results()
    paired.verify_post_guard(frozen, pair_plan_hash, result)
    final = json.loads((DATA_MONITOR / 'final-result.json').read_text())
    if final.get('verification') != paired.verify_outputs():
        raise ValueError('paired aggregate independent byte reconstruction differs')
    for arm, expected in audit.DATA.items():
        if sha(DATA / arm / 'data.bin') != expected or sha(DATA / arm / 'map.bin') != audit.MAP:
            raise ValueError('paired input hash differs')
    trainer = build.verify(); parent = design.parent_receipt()
    if (sha(BUILD / 'build.json') != '33a941d231adb3be54e41e736f192d7842c0daf0833da60f50d3aaaa07ad4bca' or
            trainer.get('dimensions') != [1031, 935, 300] or trainer.get('auxiliaryMaskEpisodeRange') != [928, 935] or
            trainer.get('binaries', {}).get('trainer') != '1e64ccb918d9ff53c0ccea1b8cf98d0125cdff91d80dedc276a83b9079bfcbe3' or
            parent.get('weightsSHA256') != audit.PARENT):
        raise ValueError('trainer or parent differs')
    if (sha(ROOT / 'build/flex/control/policy-categorical') != parent['binarySHA256'] or
            sha(ROOT / 'flex/control/model-categorical.pup') != parent['graphSHA256'] or
            any(sha(ROOT / 'build/flex/control/kernels' / name) != digest
                for name, digest in parent['kernels'].items())):
        raise ValueError('current runtime differs from parent')
    paths = [HERE / 'plan.py', HERE / 'audit.py', HERE / 'monitor.py',
             ROOT / 'experiments/parent-route-paired-trainer-v1/build.py',
             ROOT / 'experiments/parent-route-paired-trainer-v1/transform.py',
             ROOT / 'experiments/outbound-five-trainer-v1/design.py', Path(sys.executable).resolve(),
             Path('/usr/bin/nice'), Path('/usr/bin/ionice'), Path('/usr/bin/btrfs'),
             BUILD / 'build.json', BUILD / 'control', BUILD / 'trainer',
             ROOT / 'build/flex/rocm-runtime/libamdhip64.so', ROOT / 'build/flex/control/policy-categorical',
             ROOT / 'flex/control/model-categorical.pup', ROOT / 'build/flex/pixel-control-categorical-model.flex',
             DATA_MONITOR / 'completion.json',
             DATA_MONITOR / 'coordinator-result.json', DATA_MONITOR / 'final-result.json', DATA / 'report.json',
             PARENT / 'receipt.json', PARENT / 'weights.bin', PARENT / 'policy', PARENT / 'model.pup']
    paths += sorted((ROOT / 'build/flex/control/kernels').glob('*'))
    paths += sorted((PARENT / 'kernels').glob('*'))
    if any(not p.is_file() for p in paths): raise ValueError('missing smoke input')
    pins = paired.plan.source_chain()
    pins.update({str(path): sha(path) for path in paths})
    return {'files': pins, 'pairPlanSHA256': pair_plan_hash, 'pairCompletionSHA256': sha(completion),
            'trainerBuildSHA256': sha(BUILD / 'build.json'), 'parentWeightsSHA256': audit.PARENT,
            'dataSHA256': dict(audit.DATA), 'mapSHA256': audit.MAP,
            'datasetShape': [1031, 935, 300], 'auxiliaryMaskRange': [928, 935]}


def specification():
    return {'schema': 'puppybot.parent-route-paired-smoke-plan.v1', 'inputs': snapshot(),
            'commands': {arm: command(arm) for arm in ('control', 'treatment')},
            'environment': environment(), 'wallSecondsPerArm': WALL,
            'arms': ['control', 'treatment'], 'seed': audit.SEED,
            'firstBatch': [203, 934], 'optimizer': 'fresh Adam; one update; original parent weights',
            'scope': 'one-update diagnostic only; no selection, promotion, held-out or physical claim'}


def freeze():
    if PLAN.exists() or PLAN.is_symlink() or OUTPUT.exists() or OUTPUT.is_symlink():
        raise FileExistsError('existing smoke plan or output; retain it')
    value = specification()
    with PLAN.open('x') as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False); stream.write('\n')
        stream.flush(); os.fsync(stream.fileno())
    return value


def verify():
    if PLAN.is_symlink() or not PLAN.is_file(): raise ValueError('missing smoke registration')
    frozen = json.loads(PLAN.read_text())
    if frozen != specification(): raise ValueError('smoke plan or inputs changed')
    return frozen


if __name__ == '__main__':
    raise SystemExit('Disabled pending independent review and scheduling; no GPU launch authorized.')
