#!/usr/bin/env python3
"""Freeze a separate collector design; this never launches a collector."""
import importlib.util
import copy
import json
import os
import sys
import types
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASE = ROOT / 'build/flex/sim/levels-v2/pitch82'
ORIGINAL = BASE / 'parent-route-collector-plan-v1/plan.json'
PRIOR = BASE / 'parent-route-collector-plan-v2/plan.json'
PRIOR_RECEIPT = BASE / 'parent-route-collector-plan-v2/lineage-audit.json'
PLAN = BASE / 'parent-route-instrumented-collector-plan-v1.json'
OUTPUT = BASE / 'parent-route-instrumented-collector-v1'
COMPANION = ROOT / 'experiments/parent-route-companion-audit-v1/audit.py'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = load('parent_instrumented_builder', HERE / 'build.py')
lineage = load('parent_prior_lineage', ROOT / 'experiments/parent-route-collector-plan-v1/audit.py')


def sha(path):
    return builder.digest(path)


def commands(prior):
    result = []
    for shard, old in enumerate(prior['commands']):
        if not isinstance(old, list) or not old or not all(isinstance(value, str) for value in old):
            raise ValueError('invalid prior command')
        command = list(old)
        command[0] = str(builder.OUTPUT / 'control')
        for flag, path in (('--scene-catalog', OUTPUT / 'catalogs' / str(shard)),
                           ('--output', OUTPUT / f'shard-{shard}')):
            if command.count(flag) != 1:
                raise ValueError('ambiguous prior command')
            command[command.index(flag) + 1] = str(path)
        result.append(command)
    if len(result) != 2:
        raise ValueError('exactly two shards required')
    return result


def local_pins():
    files = {Path(__file__).resolve(), HERE / 'runner.py', HERE / 'game-audit.py', HERE / 'audit.py',
             HERE / 'build.py', HERE / 'transform.py', HERE / 'parent-boundary.flex', COMPANION,
             Path(os.__file__).resolve(), Path(sys.executable).resolve()}
    # Traverse the eagerly loaded local helpers used in fresh worker processes.
    pending = [builder, lineage, load('parent_route_pin_runner', HERE / 'runner.py')]
    seen = set()
    while pending:
        module = pending.pop()
        if not isinstance(module, types.ModuleType) or id(module) in seen:
            continue
        seen.add(id(module)); path = getattr(module, '__file__', None)
        if path:
            path = Path(path).resolve()
            if path.suffix == '.py' and path.is_relative_to(ROOT):
                files.add(path)
                pending.extend(value for value in vars(module).values() if isinstance(value, types.ModuleType))
    return {str(path): sha(path) for path in sorted(files)}


def snapshot():
    prior_bytes = PRIOR.read_bytes()
    prior = json.loads(prior_bytes)
    checked = lineage.audit(prior)
    receipt = json.loads(PRIOR_RECEIPT.read_text())
    original = json.loads(ORIGINAL.read_text())
    comparable = copy.deepcopy(prior)
    document = str(ROOT / 'diary/128-parent-retention-feasibility.md')
    comparable['inputSHA256'][document] = original['inputSHA256'][document]
    if (comparable != original or sha(ORIGINAL) != receipt.get('oldPlanSHA256') or
            any(receipt.get(key) != checked.get(key) for key in ('status', 'fit', 'companionOnly')) or
            receipt.get('auditSourceSHA256') != sha(ROOT / 'experiments/parent-route-collector-plan-v1/audit.py') or
            receipt.get('planSHA256') != sha(PRIOR) or receipt.get('changedPath') != document or
            receipt.get('oldDocumentSHA256') != original['inputSHA256'][document] or
            receipt.get('newDocumentSHA256') != prior['inputSHA256'][document]):
        raise ValueError('prior frozen lineage audit differs')
    build = builder.verify()
    sources = local_pins()
    if PRIOR.read_bytes() != prior_bytes:
        raise ValueError('prior plan changed during registration')
    return {'schema': 'puppybot.parent-route-instrumented-collector-plan.v1',
            'status': 'registered_before_collection', 'priorPlan': str(PRIOR),
            'priorPlanSHA256': sha(PRIOR), 'priorReceiptSHA256': sha(PRIOR_RECEIPT),
            'originalPlanSHA256': sha(ORIGINAL),
            'privateBuild': str(builder.OUTPUT), 'buildSHA256': sha(builder.OUTPUT / 'build.json'),
            'privateControlSHA256': build['controlSHA256'], 'commands': commands(prior),
            'environment': prior['environment'], 'rows': prior['rows'], 'localPins': sources,
            'thresholds': {'startupGiB': 38, 'activeGiB': 34, 'emergencyGiB': 32,
                           'baselineFreeVramGiB': 6, 'activeFreeVramGiB': 2,
                           'baselineSeconds': 30, 'perShardSeconds': 1800},
            'scope': ('instrumented private binary on reused fitting-family scenes; '
                      'no training, independent selection, held-out or physical claim')}


def verify():
    frozen = json.loads(PLAN.read_text())
    if snapshot() != frozen:
        raise ValueError('registered collector inputs changed')
    return frozen


def freeze():
    if PLAN.exists() or PLAN.is_symlink() or OUTPUT.exists() or OUTPUT.is_symlink():
        raise FileExistsError('plan or output exists; retain evidence')
    value = snapshot()
    if snapshot() != value:
        raise ValueError('collector inputs changed during registration')
    with PLAN.open('x') as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False); stream.write('\n')
    if verify() != value:
        raise ValueError('registered plan readback differs')
    return value


if __name__ == '__main__':
    raise SystemExit('Disabled pending complete runner, tests and independent review.')
