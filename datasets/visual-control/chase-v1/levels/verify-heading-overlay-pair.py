#!/usr/bin/env python3
"""Validate paired heading-roll-in overlays; never generate or train data.

Production uses only fixed historical L5 slots. A passing report is a
training-input diagnostic, not held-out qualification or model promotion.
"""
import ctypes
import importlib.util
import json
import os
import secrets
import shutil
import subprocess
import sys
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[4]
S = PROJECT / 'datasets/visual-control/chase-v1/levels'
P = PROJECT / 'build/flex/sim/levels-v2/pitch82'
PREVIOUS = P / 'search-dagger-l4-matched'
OUTPUT = P / 'search-dagger-heading'
CATALOGS = P / 'heading-rollin-full-catalogs'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    obj = importlib.util.module_from_spec(spec); spec.loader.exec_module(obj)
    return obj


slots = load('slots', S / 'heading-slot-plan.py')
overlay = load('overlay', S / 'heading-reflink-overlay.py')
pairs = load('pairs', S / 'audit-heading-pairs.py')
rollin = load('rollin', S / 'run-heading-rollin.py')
collection_receipt = load('collection_receipt', S / 'heading-collection-receipt.py')
resource = load('overlay_resource_verify', S / 'heading-overlay-resource-verify.py')


def tool_pins():
    paths = [S / name for name in ('prepare-heading-overlays.py', 'heading-slot-plan.py', 'heading-reflink-overlay.py',
             'verify-heading-overlay-pair.py', 'audit-heading-pairs.py', 'prepare-heading-rollin.py',
             'run-heading-rollin.py', 'audit-shards.py', 'audit-student-labels.py',
             'prepare-route-factorial.py', 'prepare-bias-validation.py', 'heading-collection-receipt.py',
             'heading-overlay-resource-verify.py')]
    paths.append(PROJECT / 'flex/tests/monitored-heading-collection.py')
    return {str(path): overlay.digest(path) for path in paths}


def verify_tool_pins(report):
    if report.get('toolSHA256') != tool_pins():
        raise ValueError('pair verification tools changed')


def expected_mapping(shards, fit_offset, validation_offset, games, fitting):
    mapping = {}; a, b = fit_offset, validation_offset
    for shard in shards:
        for i in range(games):
            if i < fitting:
                target = a; a += 1
            else:
                target = b; b += 1
            if target in mapping: raise ValueError('duplicate target slot')
            mapping[target] = (shard, i)
    return mapping


def check_arm(base, output, shards, plan, shard_games=32, shard_fitting=30):
    manifest_path = output / 'manifest.json'; manifest = json.loads(manifest_path.read_text())
    for shard in shards:
        if (overlay.header(shard / 'data.bin', b'PVDATA01', overlay.OLD_WIDTH) != (shard_games, shard_fitting) or
                overlay.header(shard / 'map.bin', b'PVMAP001', overlay.MAP_WIDTH) != (shard_games, shard_fitting)):
            raise ValueError('source shard dimensions differ')
    mapping = expected_mapping(shards, plan['fitOffset'], plan['validationOffset'], shard_games, shard_fitting)
    if 'replacedSlots' in plan and sorted(mapping) != plan['replacedSlots']:
        raise ValueError('replacement mapping is not the authorized slot set')
    expected = [{'target': index, 'sourceShard': str(shard), 'sourceEpisode': episode}
                for index, (shard, episode) in sorted(mapping.items())]
    if (manifest.get('status') != 'prototype_only' or manifest.get('games') != plan['totalGames']
            or manifest.get('fittingGames') != plan['fittingGames'] or manifest.get('unchangedGames') != plan['unaffectedGames']
            or manifest.get('replacedFittingGames') != len(shards) * shard_fitting
            or manifest.get('replacedValidationGames') != len(shards) * (shard_games - shard_fitting)
            or manifest.get('slotMapping') != expected):
        raise ValueError('overlay manifest or slot authorization differs')
    paths = [base / name for name in ('data.bin', 'map.bin')] + [shard / name for shard in shards for name in ('data.bin', 'map.bin', 'report.json')]
    pins = manifest.get('inputPins')
    if not isinstance(pins, dict) or set(pins) != {str(path) for path in paths}:
        raise ValueError('overlay source inventory differs')
    for path in paths:
        pin = pins[str(path)]
        if list(overlay.signature(path)) != pin.get('stat') or overlay.digest(path) != pin.get('sha256'):
            raise ValueError(f'overlay source changed: {path}')
    for name, field in (('data.bin', 'dataSHA256'), ('map.bin', 'mapSHA256')):
        if overlay.digest(output / name) != manifest.get(field): raise ValueError('overlay output changed')
    overlay.audit(base, output, mapping, plan['totalGames'])
    for path in paths:
        pin = pins[str(path)]
        if list(overlay.signature(path)) != pin.get('stat') or overlay.digest(path) != pin.get('sha256'):
            raise ValueError(f'overlay source changed while checking: {path}')
    for name, field in (('data.bin', 'dataSHA256'), ('map.bin', 'mapSHA256')):
        if overlay.digest(output / name) != manifest.get(field): raise ValueError('overlay output changed while checking')
    return {'manifestSHA256': overlay.digest(manifest_path), 'dataSHA256': manifest['dataSHA256'], 'mapSHA256': manifest['mapSHA256']}


def check_pair(base, control, treatment, control_shards, treatment_shards, plan, shard_games=32, shard_fitting=30):
    if len(control_shards) != len(treatment_shards): raise ValueError('arm shard counts differ')
    left = check_arm(base, control, control_shards, plan, shard_games, shard_fitting)
    right = check_arm(base, treatment, treatment_shards, plan, shard_games, shard_fitting)
    shared = pairs.compare_validation(control, treatment, plan['totalGames'], plan['fittingGames'])
    source_equal = []
    for a, b in zip(control_shards, treatment_shards):
        selected = [i for i in range(shard_games) if i >= shard_fitting or i % 3 == 1]
        source_equal.append(pairs.compare_shard(a, b, selected, shard_games, shard_fitting))
    for directory, recorded in ((control, left), (treatment, right)):
        if (overlay.digest(directory / 'manifest.json') != recorded['manifestSHA256'] or
                overlay.digest(directory / 'data.bin') != recorded['dataSHA256'] or
                overlay.digest(directory / 'map.bin') != recorded['mapSHA256']):
            raise ValueError('overlay changed during paired validation')
    return {'status': 'paired_inputs_only', 'plan': plan, 'control': left, 'treatment': right,
            'aggregateValidation': shared, 'sharedHeadingShardBytes': source_equal,
            'scope': 'byte-level pairing only; simulator carry cue is not a physical sensor; no heldout qualification'}


def publish_new(path, data):
    if path.exists() or path.is_symlink(): raise ValueError('pair receipt exists')
    temp = path.parent / f'.{path.name}.partial-{secrets.token_hex(8)}'
    with temp.open('x') as f:
        json.dump(data, f, sort_keys=True, indent=2); f.write('\n'); f.flush(); os.fsync(f.fileno())
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.renameat2(-100, os.fsencode(temp), -100, os.fsencode(path), 1) != 0:
        raise OSError(ctypes.get_errno(), f'pair receipt not published; partial retained at {temp}')
    try:
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try: os.fsync(fd)
        finally: os.close(fd)
    except OSError as error:
        raise RuntimeError(f'pair receipt published at {path}; durability unconfirmed') from error


def main():
    if len(sys.argv) != 1: raise SystemExit(__doc__)
    with rollin.base.acquire_lock(P / '.l4-matched.lock'):
        collection_receipt.verify()
        pinned_tools = tool_pins()
        if not (OUTPUT / 'collection-report.json').is_file(): raise ValueError('collection audit missing')
        manifest = json.loads((CATALOGS / 'catalogs.json').read_text()); rollin.catalogs.verify(CATALOGS, manifest)
        subprocess.run(['/usr/bin/sha256sum', '-c', str(PREVIOUS / 'training-inputs.sha256')], cwd=PROJECT, check=True, stdout=subprocess.DEVNULL)
        if rollin.critical(CATALOGS, manifest) != json.loads((OUTPUT / 'inputs.json').read_text()):
            raise ValueError('collection inputs changed')
        audited = rollin.validate_matched(OUTPUT, 'full', manifest)
        if audited != json.loads((OUTPUT / 'collection-report.json').read_text())['reports']:
            raise ValueError('collection report no longer matches')
        plan = slots.fixed_plan()
        left = [OUTPUT / f'control-L5/shard-{i}' for i in range(4)]
        right = [OUTPUT / f'treatment-L5/shard-{i}' for i in range(4)]
        if len(left) != 4 or len(right) != 4: raise ValueError('production requires four shards per arm')
        result = check_pair(PREVIOUS / 'data', OUTPUT / 'aggregate-control', OUTPUT / 'aggregate-treatment', left, right, plan)
        result['catalogsSHA256'] = overlay.digest(CATALOGS / 'catalogs.json')
        result['collectionReportSHA256'] = overlay.digest(OUTPUT / 'collection-report.json')
        result['resourceEvidence'], result['resourceEvidenceSHA256'] = resource.collect()
        if tool_pins() != pinned_tools: raise ValueError('pair verification tools changed during audit')
        collection_receipt.verify()
        result['toolSHA256'] = pinned_tools
        rollin.base.require_capacity(P, 32 * 1024**3)
        result['freeBytesBeforeReceipt'] = shutil.disk_usage(P).free
        publish_new(OUTPUT / 'pair-ready.json', result)
        print(json.dumps({'status': result['status'], 'validationGames': result['aggregateValidation']['validationGames']}))


if __name__ == '__main__': main()
