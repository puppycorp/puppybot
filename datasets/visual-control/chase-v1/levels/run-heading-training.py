#!/usr/bin/env python3
"""Train two matched heading-distribution models only after both pilots pass.

This staged prototype requires the separately revalidated full pair receipt,
small matched stock/FICLONE trainer pilot, idle GPU and sufficient disk. It
creates new outputs only and retains every partial. Training-layout results
are not held-out qualification or physical-robot evidence.
"""
import json
import os
import sys
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[4]
S = PROJECT / 'datasets/visual-control/chase-v1/levels'
P = PROJECT / 'build/flex/sim/levels-v2/pitch82'
OUTPUT = P / 'search-dagger-heading'
RESULT = OUTPUT / 'models'


def load(name, path):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, path)
    obj = importlib.util.module_from_spec(spec); spec.loader.exec_module(obj)
    return obj


small = load('small_pilot', S / 'run-heading-trainer-pilot.py')
builder = small.builder
base = small.base
collection_receipt = load('collection_receipt', S / 'heading-collection-receipt.py')
resource = load('overlay_resource_verify', S / 'heading-overlay-resource-verify.py')


def verify_full_receipt(model, data_sha, map_sha, parent_sha):
    receipt = json.loads((model / 'receipt.json').read_text())
    expected = {'dataSHA256': data_sha, 'memoryMapTargetsSHA256': map_sha, 'initialWeightsSHA256': parent_sha,
                'seed': 6900000, 'epochs': 8, 'batch': 2, 'checkpointEveryEpochs': 8,
                'sequenceMirrorAugmentation': True, 'carryCue': True, 'speedTransitionLossWeight': 1,
                'actionCodec': 'joint-seven-v1'}
    if any((receipt.get(k) is not v if type(v) is bool else receipt.get(k) != v) for k, v in expected.items()):
        raise ValueError('full-training receipt parameters differ')
    if base.sha(model / 'data.bin') != data_sha: raise ValueError('trainer input clone bytes differ')
    for key, name in (('weightsSHA256', 'weights.bin'), ('binarySHA256', 'policy'), ('graphSHA256', 'model.pup')):
        if receipt.get(key) != base.sha(model / name): raise ValueError('published model receipt differs')
    if not isinstance(receipt.get('kernels'), dict) or not receipt['kernels']: raise ValueError('model kernels missing')
    for name, expected_sha in receipt['kernels'].items():
        if Path(name).name != name or base.sha(model / 'kernels' / name) != expected_sha: raise ValueError('model kernel differs')


def sources():
    paths = [Path(__file__), S / 'prepare-heading-trainer.py', S / 'run-heading-trainer-pilot.py',
             builder.BUILD / 'inputs.json', builder.BUILD / 'control', builder.BUILD / 'control-stock',
             OUTPUT / 'pair-ready.json', small.RESULT / 'inputs.json', small.RESULT / 'comparison.json',
             small.PARENT / 'weights.bin', small.PILOT / 'pilot-report.json',
             collection_receipt.MONITORED / 'completion.json', S / 'heading-collection-receipt.py',
             collection_receipt.MONITOR_SCRIPT, S / 'heading-overlay-resource-verify.py',
             OUTPUT / 'resource-control.json', OUTPUT / 'resource-treatment.json']
    for arm in ('control', 'treatment'):
        paths.extend(OUTPUT / f'aggregate-{arm}' / name for name in ('data.bin', 'map.bin', 'manifest.json'))
    return {str(path): base.sha(path) for path in paths}


def publish_training_report(report):
    collection_receipt.verify()
    resource.verify_ready(json.loads((OUTPUT / 'pair-ready.json').read_text()))
    builder.pair.publish_new(RESULT / 'training-report.json', report)


def main():
    if len(sys.argv) != 1: raise SystemExit(__doc__)
    os.chdir(PROJECT)
    with base.acquire_lock(P / '.l4-matched.lock'):
        collection_receipt.verify()
        base.require_new_output(RESULT); base.require_capacity(P, 34 * 1024**3)
        build = json.loads((builder.BUILD / 'inputs.json').read_text()); builder.verify(builder.BUILD, build)
        small.verify_small_pilot()
        pair_receipt = builder.verify_ready()
        resource.verify_ready(pair_receipt)
        parent_sha = base.sha(small.PARENT / 'weights.bin')
        pinned = sources()
        physical = {arm: small.physical_map(OUTPUT / f'aggregate-{arm}/data.bin') for arm in ('control', 'treatment')}
        RESULT.mkdir(); (RESULT / 'inputs.json').write_text(json.dumps(pinned, sort_keys=True, indent=2) + '\n')
        env = {'PATH': '/usr/bin:/bin', 'HOME': str(Path.home()), 'PUPPYBOT_PROJECT': str(PROJECT),
               'LD_LIBRARY_PATH': str(PROJECT / 'build/flex/rocm-runtime'), 'SDL_VIDEODRIVER': 'offscreen'}
        reports = {}
        for arm in ('control', 'treatment'):
            base.require_capacity(P, 34 * 1024**3)
            if sources() != pinned: raise ValueError('training input changed before arm')
            builder.verify(builder.BUILD, build)
            data = OUTPUT / f'aggregate-{arm}'; model = RESULT / f'{arm}-s0'; base.require_new_output(model)
            monitor = RESULT / f'monitor-{arm}'; monitor.mkdir()
            command = [str(builder.BUILD / 'control'), 'train', '--output', str(model), '--seed', '6900000',
                       '--data', str(data / 'data.bin'), '--memory-map', str(data / 'map.bin'),
                       '--transition-weight-one', '--policy', str(small.PARENT), '--categorical',
                       '--mirror-augment', '--carry-cue', '--epochs', '8', '--batch', '2', '--checkpoint-every', '8']
            (monitor / 'command.json').write_text(json.dumps(command, indent=2) + '\n')
            status = base.hidden.supervise(command, monitor, env, 3600); base.require_success(status, monitor)
            verify_full_receipt(model, pinned[str(data / 'data.bin')], pinned[str(data / 'map.bin')], parent_sha)
            if sources() != pinned: raise ValueError('training input changed after arm')
            builder.verify(builder.BUILD, build)
            if small.physical_map(data / 'data.bin') != physical[arm]: raise ValueError('source aggregate physical mapping changed')
            extent = small.extent_numbers(model / 'data.bin')
            if extent['total'] <= 0 or extent['exclusive'] > 4 * 1024**2 or extent['shared'] < extent['total'] - 4 * 1024**2:
                raise ValueError('model data clone is not predominantly shared')
            base.require_capacity(P, 32 * 1024**3)
            reports[arm] = {'weightsSHA256': base.sha(model / 'weights.bin'), 'dataExtents': extent,
                            'receiptSHA256': base.sha(model / 'receipt.json')}
        small.verify_small_pilot()
        if builder.verify_ready() != pair_receipt: raise ValueError('paired input receipt changed during training')
        resource.verify_ready(pair_receipt)
        matched = base.training.audit(small.PARENT, RESULT / 'control-s0', RESULT / 'treatment-s0')
        # No fixed-epoch package or model is promoted by this input/training receipt.
        report = {'status': 'training_diagnostic_only', 'arms': reports, 'matchedArtifacts': matched,
                  'pairReadySHA256': base.sha(OUTPUT / 'pair-ready.json'),
                  'smallPilotSHA256': base.sha(small.RESULT / 'comparison.json'),
                  'scope': 'one training seed; simulator-derived carry cue; fixed-epoch evaluation and held-out qualification not established'}
        publish_training_report(report)
        print(json.dumps({'status': report['status'], 'output': str(RESULT)}))


if __name__ == '__main__': main()
