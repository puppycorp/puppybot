#!/usr/bin/env python3
"""Freeze read-only input provenance for paired aggregate construction."""
import importlib.util
import json
import os
import sys
import types
from pathlib import Path
from unittest import mock


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
P = ROOT / 'build/flex/sim/levels-v2/pitch82'
PLAN = P / 'parent-route-paired-aggregate-plan-v1.json'
OUTPUT = P / 'parent-route-paired-aggregate-v1'
MONITOR = P / 'parent-route-paired-aggregate-monitored-v1'
BASE = P / 'outbound-five-aggregate-v1'
COLLECTION = P / 'parent-route-instrumented-collector-v1'
SELECTED = ((0, 163, 7820010), (0, 189, 7820025))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


builder = load('parent_pair_builder', HERE / 'build.py')
verify = load('parent_pair_verifier', HERE / 'verify.py')
collector = load('parent_pair_collection_runner', ROOT / 'experiments/parent-route-actor-boundary-v1/runner.py')
train = load('parent_pair_prior_training', ROOT / 'experiments/outbound-five-trainer-v1/train.py')
guardian = load('parent_pair_guardian', ROOT / 'experiments/dock-turn-rendered-probe-v1/guardian.py')
sha = collector.registration.sha


def read(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f'missing or linked evidence: {path}')
    return json.loads(path.read_text())


def source_specs():
    result = []
    for shard, (episode, cutoff, seed) in enumerate(SELECTED):
        root = COLLECTION / f'shard-{shard}'; game = root / f'expert-{episode}'
        result.append({'seed': seed, 'episode': episode, 'cutoff': cutoff,
                       'data': str(root / 'data.bin'), 'map': str(root / 'map.bin'),
                       'actor': str(game / 'actor-boundary.bin'), 'boundary': str(game / 'map-label-boundary.bin'),
                       'decisions': str(game / 'decisions.jsonl'), 'events': str(game / 'chase.jsonl')})
    return result


def source_chain():
    pending = [builder, verify, collector, train, guardian]; seen = set(); paths = set()
    while pending:
        module = pending.pop()
        if not isinstance(module, types.ModuleType) or id(module) in seen:
            continue
        seen.add(id(module)); name = getattr(module, '__file__', None)
        if name:
            path = Path(name).resolve()
            if path.suffix == '.py' and path.is_relative_to(ROOT):
                paths.add(path); pending.extend(value for value in vars(module).values() if isinstance(value, types.ModuleType))
    paths.update((Path(__file__).resolve(), HERE / 'build.py', HERE / 'verify.py', HERE / 'supervise.py',
                  Path(sys.executable).resolve(), Path('/usr/bin/nice'), Path('/usr/bin/ionice')))
    return {str(path): sha(path) for path in sorted(paths)}


def baseline_evidence():
    report = read(BASE / 'report.json')
    if (report.get('schema') != 'puppybot.outbound-five-aggregate.v1' or
            report.get('status') != 'candidate_data_only' or report.get('trainingAuthorized') is not False):
        raise ValueError('baseline aggregate is not diagnostic-only')
    train.dataset_supervision(report)
    if sha(BASE / 'data.bin') != report['dataSHA256'] or sha(BASE / 'map.bin') != report['mapSHA256']:
        raise ValueError('baseline data changed')
    prior = train.aggregate
    selected = [(item['episode'], item['firstConsumptionAction']) for item in report['selectedTeacherEpisodes']]
    if selected != [(3, 162), (4, 107), (5, 171), (6, 43), (8, 38)]:
        raise ValueError('baseline teacher prefixes changed')
    measured = prior.verify.verify(prior.BASE / 'data.bin', prior.BASE / 'map.bin',
                                  prior.PILOT / 'teacher/data.bin', prior.PILOT / 'teacher/map.bin',
                                  BASE / 'data.bin', BASE / 'map.bin', selected)
    if measured != report['verification']:
        raise ValueError('baseline byte/order reconstruction differs')
    return {'dataSHA256': report['dataSHA256'], 'mapSHA256': report['mapSHA256'],
            'reportSHA256': sha(BASE / 'report.json'),
            'supervisionSHA256': sha(train.aggregate_supervisor.MONITOR / 'result.json')}


def collection_receipts(plan, completion):
    """Require coordinator, worker and final-check receipts to agree."""
    coordinator = read(COLLECTION / 'coordinator-result.json')
    worker = read(COLLECTION / 'worker-result.json')
    final = read(COLLECTION / 'final-supervisor/client.log')
    hashes = {'planSHA256': sha(collector.registration.PLAN),
              'workerSHA256': sha(COLLECTION / 'worker-result.json'),
              'reportSHA256': sha(COLLECTION / 'report.json'),
              'inventorySHA256': sha(COLLECTION / 'inventory.json')}
    if (coordinator.get('status') != 'collection_diagnostic_only' or
            worker.get('status') != 'collection_diagnostic_only' or
            final.get('status') != 'final_inventory_verified' or
            completion.get('planSHA256') != hashes['planSHA256'] or
            completion.get('workerSHA256') != hashes['workerSHA256'] or
            any(coordinator.get(key) != value for key, value in hashes.items()) or
            any(final.get(key) != value for key, value in hashes.items()) or
            worker.get('reportSHA256') != hashes['reportSHA256'] or
            worker.get('inventorySHA256') != hashes['inventorySHA256']):
        raise ValueError('collector coordinator, worker or final receipt differs')
    collector.verify_supervisor_hashes(coordinator)
    for name, function, seconds in (('worker-supervisor', 'worker', 4000),
                                    ('final-supervisor', 'final_check', 1200)):
        directory = COLLECTION / name
        expected = {'argv': collector.worker_command(function), 'environment': plan['environment'], 'wallSeconds': seconds}
        if (read(directory / 'invocation.json') != expected or
                not collector.clean(read(directory / 'supervisor-result.json'))):
            raise ValueError('collector supervisor invocation or status differs')
    return hashes


def collection_evidence():
    plan = collector.registration.verify()
    completion = read(COLLECTION / 'completion.json')
    paths = {'baselineSHA256': 'baseline-passed.json', 'coordinatorSHA256': 'coordinator-result.json',
             'guardianLaunchSHA256': 'guardian-launch.json', 'guardianResultSHA256': 'guardian-result.json',
             'guardianTelemetrySHA256': 'guardian-telemetry.jsonl', 'workerSHA256': 'worker-result.json'}
    if completion.get('status') != 'collection_diagnostic_only' or completion.get('planSHA256') != sha(collector.registration.PLAN):
        raise ValueError('collector did not complete as diagnostic-only')
    for key, name in paths.items():
        if completion.get(key) != sha(COLLECTION / name):
            raise ValueError('collector completion evidence changed')
    collection_receipts(plan, completion)
    for name in ('worker-supervisor/supervisor-result.json', 'final-supervisor/supervisor-result.json',
                 'monitor-0/supervisor-result.json', 'monitor-1/supervisor-result.json'):
        if not collector.clean(read(COLLECTION / name)):
            raise ValueError('collector supervisor not clean')
    collector.verify_shards(plan)
    guardian_launch = read(COLLECTION / 'guardian-launch.json'); launcher = read(COLLECTION / 'launcher.json')
    parent = guardian_launch.get('parentPID'); guardian_pid = guardian_launch.get('guardianPID')
    if type(parent) is not int or parent <= 1 or type(guardian_pid) is not int or guardian_pid <= 1:
        raise ValueError('collector guardian identity invalid')
    # Historical verifier expects the original launcher PID; never signal it.
    with mock.patch.object(collector.os, 'getpid', return_value=parent):
        collector.verify_guardian(COLLECTION, launcher, guardian_pid)
    links = collector.catalog(plan)
    if collector.inventory(links) != read(COLLECTION / 'inventory.json'):
        raise ValueError('collector final inventory changed')
    fresh = collector.game_audit.audit(collector.registration.PRIOR, COLLECTION, collector.companion)
    if fresh != read(COLLECTION / 'report.json') or fresh.get('trainingAuthorized') is not False:
        raise ValueError('collector saved-game audit changed')
    fit = [game for game in fresh['games'] if game['role'] == 'fit']
    if ([(game['seed'], game['episode'], game['firstDeliveryStep']) for game in fit] !=
            [(7820010, 0, 163), (7820025, 0, 189)] or
            [game['boundary']['prefixLabelDifferences'] for game in fit] != [35, 31] or
            any(game['boundedPrefixBackForthActions'] != 0 for game in fit)):
        raise ValueError('selected fitting identities or prefix checks differ')
    return {'completionSHA256': sha(COLLECTION / 'completion.json'),
            'reportSHA256': sha(COLLECTION / 'report.json'),
            'inventorySHA256': sha(COLLECTION / 'inventory.json'),
            'collectorPlanSHA256': sha(collector.registration.PLAN)}


def snapshot():
    baseline = baseline_evidence(); collection = collection_evidence(); sources = source_chain()
    paths = {str(BASE / name): sha(BASE / name) for name in ('data.bin', 'map.bin')}
    for spec in source_specs():
        paths.update({str(spec[key]): sha(spec[key]) for key in ('data', 'map', 'actor', 'boundary', 'decisions', 'events')})
    if baseline_evidence() != baseline or collection_evidence() != collection or source_chain() != sources:
        raise ValueError('input evidence changed during paired-data preflight')
    return {'schema': 'puppybot.parent-route-paired-aggregate-plan.v1', 'status': 'registered_before_creation',
            'baseline': baseline, 'collection': collection, 'sources': sources, 'inputSHA256': paths,
            'sourceSpecs': source_specs(), 'selected': [list(item) for item in SELECTED],
            'outputs': {'control': str(OUTPUT / 'control'), 'treatment': str(OUTPUT / 'treatment')},
            'shape': {'episodes': 1031, 'fitting': 935, 'validation': 96, 'length': 300},
            'requirements': {'auxiliaryMaskEpisodeRange': [928, 935], 'maskedSuffixWeight': 0,
                             'requiresSeparateTrainerMaskAudit': True, 'trainingAuthorized': False,
                             'perArmFullLogicalReservation': True, 'reflinkRequired': True},
            'scope': 'previously used fitting-family cases only; no new selection, held-out or physical claim'}


def verify_plan():
    value = read(PLAN)
    if snapshot() != value:
        raise ValueError('paired aggregate inputs changed since registration')
    return value


def freeze():
    if PLAN.exists() or PLAN.is_symlink() or OUTPUT.exists() or OUTPUT.is_symlink() or MONITOR.exists() or MONITOR.is_symlink():
        raise FileExistsError('plan or output already exists; retain it')
    value = snapshot()
    if snapshot() != value:
        raise ValueError('paired aggregate inputs changed while registering')
    with PLAN.open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False); stream.write('\n')
        stream.flush(); os.fsync(stream.fileno())
    if verify_plan() != value:
        raise ValueError('paired aggregate plan readback differs')
    return value


if __name__ == '__main__':
    raise SystemExit('Disabled pending independent review and supervised scheduling.')
