#!/usr/bin/env python3
"""Prepare fixed-slot paired training overlays from audited roll-ins.

This is staged but not production-qualified. It requires the completed paired
collection and a separately successful pilot. It creates only new outputs and
never deletes a partial. Run with an idle GPU and no concurrent data writers.
"""
import json
import os
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
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, path)
    obj = importlib.util.module_from_spec(spec); spec.loader.exec_module(obj)
    return obj


rollin = load('rollin', S / 'run-heading-rollin.py')
slots = load('slots', S / 'heading-slot-plan.py')
overlay = load('overlay', S / 'heading-reflink-overlay.py')
verify = load('pair_verify', S / 'verify-heading-overlay-pair.py')
collection_receipt = load('collection_receipt', S / 'heading-collection-receipt.py')
resource = load('overlay_resource_verify', S / 'heading-overlay-resource-verify.py')


def source_maps(directory):
    return {name: [list(span) for span in overlay.physical_map(directory / name)] for name in ('data.bin', 'map.bin')}


def extent_numbers(path):
    output = subprocess.run(['btrfs', 'filesystem', 'du', '--raw', '-s', str(path)],
                            check=True, text=True, capture_output=True, timeout=60).stdout.strip().splitlines()
    if len(output) != 2: raise ValueError('unexpected Btrfs extent output')
    fields = output[1].split(maxsplit=3)
    if len(fields) != 4 or not all(value.isdigit() for value in fields[:3]) or fields[3] != str(path):
        raise ValueError('invalid Btrfs extent output')
    total, exclusive, shared = map(int, fields[:3])
    if total <= 0 or exclusive > total or shared > total:
        raise ValueError('invalid Btrfs extent values')
    return {'total': total, 'exclusive': exclusive, 'shared': shared}


def measured_overlay(original, target, expected_maps, create, floor_bytes):
    before = source_maps(original)
    if before != expected_maps: raise ValueError('source physical mapping changed before overlay')
    free_before = shutil.disk_usage(target.parent).free
    source_before = {name: extent_numbers(original / name) for name in ('data.bin', 'map.bin')}
    result = create()
    after = source_maps(original)
    if after != expected_maps: raise ValueError('source physical mapping changed during overlay')
    free_after = shutil.disk_usage(target.parent).free
    if free_after < floor_bytes: raise ValueError('disk floor crossed after overlay')
    source_after = {name: extent_numbers(original / name) for name in ('data.bin', 'map.bin')}
    target_extents = {name: extent_numbers(target / name) for name in ('data.bin', 'map.bin')}
    if target_extents['data.bin']['shared'] <= 0:
        raise ValueError('new overlay data has no reported shared extents')
    return result, {'freeBefore': free_before, 'freeAfter': free_after,
                    'sourcePhysicalMapBefore': before, 'sourcePhysicalMapAfter': after,
                    'sourceExtentsBefore': source_before, 'sourceExtentsAfter': source_after,
                    'targetExtents': target_extents,
                    'scope': 'point-in-time filesystem measurements; free space is not reserved'}


def main():
    if len(sys.argv) != 1: raise SystemExit(__doc__)
    os.chdir(PROJECT)
    with rollin.base.acquire_lock(P / '.l4-matched.lock'):
        collection_receipt.verify()
        pinned_tools = verify.tool_pins()
        rollin.base.require_capacity(P, 34 * 1024**3)
        for path in ('aggregate-control', 'aggregate-treatment', 'slot-plan.json', 'pair-ready.json',
                     'resource-control.json', 'resource-treatment.json'):
            rollin.base.require_new_output(OUTPUT / path)
        subprocess.run(['/usr/bin/sha256sum', '-c', str(PREVIOUS / 'training-inputs.sha256')], cwd=PROJECT, check=True, stdout=subprocess.DEVNULL)
        rollin.base.package.verify(PREVIOUS / 'control-s0', PREVIOUS / 'treatment-s0', PREVIOUS / 'epoch8-pair')
        catalogs = json.loads((CATALOGS / 'catalogs.json').read_text())
        rollin.catalogs.verify(CATALOGS, catalogs)
        if rollin.critical(CATALOGS, catalogs) != json.loads((OUTPUT / 'inputs.json').read_text()):
            raise ValueError('collection inputs changed')
        report = json.loads((OUTPUT / 'collection-report.json').read_text())
        if report.get('status') != 'passed' or report.get('reports') != rollin.validate_matched(OUTPUT, 'full', catalogs):
            raise ValueError('paired collection audit differs')
        plan = slots.fixed_plan()
        with (OUTPUT / 'slot-plan.json').open('x') as file:
            json.dump(plan, file, sort_keys=True, indent=2); file.write('\n'); file.flush(); os.fsync(file.fileno())
        original = PREVIOUS / 'data'
        initial_maps = source_maps(original); resources = {}
        for arm in ('control', 'treatment'):
            rollin.base.require_capacity(P, 34 * 1024**3)
            shard_paths = [OUTPUT / f'{arm}-L5/shard-{i}' for i in range(4)]
            if len(shard_paths) != 4: raise ValueError('production requires four shards per arm')
            target = OUTPUT / f'aggregate-{arm}'
            peer = OUTPUT / 'aggregate-control' if arm == 'treatment' else None
            def create():
                return overlay.overlay(original, shard_paths, target, plan['fitOffset'], plan['validationOffset'],
                                       32 * 1024**3, validation_peer=peer)
            result, resources[arm] = measured_overlay(original, target, initial_maps, create, 32 * 1024**3)
            if result['unchangedGames'] != 896 or result['replacedFittingGames'] != 120 or result['replacedValidationGames'] != 8:
                raise ValueError('unexpected overlay game counts')
            with (OUTPUT / f'resource-{arm}.json').open('x') as file:
                json.dump(resources[arm], file, sort_keys=True, indent=2); file.write('\n'); file.flush(); os.fsync(file.fileno())
        left = [OUTPUT / f'control-L5/shard-{i}' for i in range(4)]
        right = [OUTPUT / f'treatment-L5/shard-{i}' for i in range(4)]
        ready = verify.check_pair(original, OUTPUT / 'aggregate-control', OUTPUT / 'aggregate-treatment', left, right, plan)
        ready['catalogsSHA256'] = rollin.sha(CATALOGS / 'catalogs.json')
        ready['collectionReportSHA256'] = rollin.sha(OUTPUT / 'collection-report.json')
        ready['slotPlanSHA256'] = rollin.sha(OUTPUT / 'slot-plan.json')
        if verify.tool_pins() != pinned_tools: raise ValueError('overlay tools changed during preparation')
        collection_receipt.verify()
        if source_maps(original) != initial_maps: raise ValueError('source physical mapping changed before pair receipt')
        for arm in ('control', 'treatment'):
            if json.loads((OUTPUT / f'resource-{arm}.json').read_text()) != resources[arm]:
                raise ValueError('recorded overlay resource evidence changed')
        ready['toolSHA256'] = pinned_tools
        ready['resourceEvidence'] = resources
        ready['resourceEvidenceSHA256'] = {arm: rollin.sha(OUTPUT / f'resource-{arm}.json') for arm in ('control', 'treatment')}
        resource.verify_ready(ready)
        rollin.base.require_capacity(P, 32 * 1024**3)
        ready['freeBytesBeforeReceipt'] = shutil.disk_usage(P).free
        verify.publish_new(OUTPUT / 'pair-ready.json', ready)
        print(json.dumps({'status': 'paired_inputs_only', 'validationGames': ready['aggregateValidation']['validationGames']}))


if __name__ == '__main__': main()
