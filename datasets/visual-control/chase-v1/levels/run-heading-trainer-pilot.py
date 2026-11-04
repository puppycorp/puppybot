#!/usr/bin/env python3
"""One-epoch matched stock-vs-FICLONE training pilot; training layouts only.

Requires the independently audited small roll-in pilot and private stock/FICLONE
controls built from the same source. A mismatch retains
both models and a diagnostic comparison, never a training-ready receipt.
Run only after review on an otherwise idle GPU.
"""
import json
import math
import os
import re
import struct
import subprocess
import sys
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[4]
S = PROJECT / 'datasets/visual-control/chase-v1/levels'
P = PROJECT / 'build/flex/sim/levels-v2/pitch82'
OUTPUT = P / 'search-dagger-heading'
BUILD = P / 'search-dagger-heading-trainer-build'
PILOT = P / 'search-dagger-heading-pilot'
PARENT = P / 'search-dagger-l4-matched/epoch8-pair/treatment'
RESULT = P / 'search-dagger-heading-trainer-pilot'
MONITORED = P / 'heading-trainer-pilot-monitored-v1'
MONITOR_SCRIPT = PROJECT / 'flex/tests/monitored-heading-trainer.py'


def load(name, path):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, path)
    obj = importlib.util.module_from_spec(spec); spec.loader.exec_module(obj)
    return obj


builder = load('heading_builder', S / 'prepare-heading-trainer.py')
base = builder.pair.rollin.base


def physical_map(path):
    text = subprocess.run(['filefrag', '-v', str(path)], capture_output=True, text=True, check=True).stdout
    spans = []
    for line in text.splitlines():
        match = re.match(r'^\s*\d+:\s*(\d+)\.\.\s*(\d+):\s*(\d+)\.\.\s*(\d+):', line)
        if not match: continue
        a, b, c, d = map(int, match.groups())
        if c <= 0 or b - a != d - c: raise ValueError('source physical mapping is unavailable')
        if spans and spans[-1][1] + 1 == a and spans[-1][3] + 1 == c:
            spans[-1] = (spans[-1][0], b, spans[-1][2], d)
        else: spans.append((a, b, c, d))
    if not spans: raise ValueError('source physical mapping is empty')
    return spans


def extent_numbers(path):
    result = subprocess.run(['btrfs', 'filesystem', 'du', '--raw', '-s', str(path)], capture_output=True, text=True, check=True)
    lines = result.stdout.strip().splitlines()
    if len(lines) != 2: raise ValueError('unexpected Btrfs extent output')
    fields = lines[1].split(maxsplit=3)
    if len(fields) != 4 or not all(x.isdigit() for x in fields[:3]): raise ValueError('invalid Btrfs extent values')
    return {'total': int(fields[0]), 'exclusive': int(fields[1]), 'shared': int(fields[2])}


def compare_models(stock, clone, parent):
    names = ('initial.bin', 'first-order.bin', 'final-order.bin', 'first-mirror-mask.bin',
             'first-gradients.bin', 'first-after.bin', 'epoch-1.bin', 'last.bin', 'weights.bin',
             'policy', 'model.pup', 'factory.flex')
    diffs = [name for name in names if base.sha(stock / name) != base.sha(clone / name)]
    if base.sha(stock / 'initial.bin') != base.sha(parent / 'weights.bin'): diffs.append('parent initial weights')
    for model in (stock, clone):
        if base.sha(model / 'epoch-1.bin') != base.sha(model / 'last.bin'):
            raise ValueError('one-epoch checkpoint differs from final snapshot')
        for name in ('first-order.bin', 'final-order.bin'):
            data = (model / name).read_bytes()
            if len(data) != 34 * 8: raise ValueError('small-pilot order has incorrect size')
            order = struct.unpack('<34Q', data)
            if sorted(order[:31]) != list(range(31)) or order[31:] != tuple(range(31, 34)):
                raise ValueError('small-pilot order is not a fitting permutation plus validation suffix')
        mask = (model / 'first-mirror-mask.bin').read_bytes()
        if len(mask) != 8 or struct.unpack('<Q', mask)[0] > 3:
            raise ValueError('small-pilot initial mirror mask is invalid')
    kernels = [{p.name: base.sha(p) for p in (model / 'kernels').iterdir() if p.is_file()} for model in (stock, clone)]
    if not kernels[0] or kernels[0] != kernels[1]: diffs.append('published policy kernels')
    curves = []
    for model in (stock, clone):
        rows = [json.loads(line) for line in (model / 'curves.jsonl').read_text().splitlines()]
        if (any(type(r.get('epoch')) is not int or type(r.get('optimizerSteps')) is not int for r in rows)
                or [r.get('epoch') for r in rows] != [0, 1] or [r.get('optimizerSteps') for r in rows] != [0, 16]):
            raise ValueError('unexpected small-pilot epoch or optimizer count')
        for i, row in enumerate(rows):
            if (type(row.get('mirroredTrainingSequences')) is not int or not 0 <= row['mirroredTrainingSequences'] <= 31 * i or
                    type(row.get('selected')) is not bool or any(type(row.get(k)) not in (int, float) or not math.isfinite(row[k])
                    for k in ('trainingLoss', 'validationLoss'))):
                raise ValueError('invalid small-pilot metrics')
        curves.append([{k: r[k] for k in ('epoch', 'optimizerSteps', 'mirroredTrainingSequences', 'trainingLoss', 'validationLoss', 'selected')} for r in rows])
    if curves[0] != curves[1]: diffs.append('epoch metrics')
    return diffs


def verify_model_receipt(model, data_sha, map_sha, parent_sha):
    receipt = json.loads((model / 'receipt.json').read_text())
    if (receipt.get('dataSHA256') != data_sha or receipt.get('memoryMapTargetsSHA256') != map_sha or
            receipt.get('initialWeightsSHA256') != parent_sha or receipt.get('seed') != 7110000 or
            receipt.get('epochs') != 1 or receipt.get('batch') != 2 or receipt.get('checkpointEveryEpochs') != 1 or
            receipt.get('sequenceMirrorAugmentation') is not True or receipt.get('carryCue') is not True or
            receipt.get('speedTransitionLossWeight') != 1 or receipt.get('actionCodec') != 'joint-seven-v1' or
            base.sha(model / 'data.bin') != data_sha):
        raise ValueError('training receipt or copied data differs')
    for key, name in (('weightsSHA256', 'weights.bin'), ('binarySHA256', 'policy'), ('graphSHA256', 'model.pup')):
        if receipt.get(key) != base.sha(model / name): raise ValueError('published model receipt differs')
    if not isinstance(receipt.get('kernels'), dict) or not receipt['kernels']:
        raise ValueError('published model kernels are missing')
    for name, expected in receipt['kernels'].items():
        if Path(name).name != name or base.sha(model / 'kernels' / name) != expected:
            raise ValueError('published model kernel differs')


def supervisor_statuses():
    hashes = {}
    for arm in ('stock', 'reflink'):
        monitor = RESULT / f'monitor-{arm}'
        path = monitor / 'supervisor-result.json'
        status = json.loads(path.read_text())
        if (type(status.get('clientExit')) is not int or status['clientExit'] != 0 or
                'signal' not in status or status['signal'] is not None or status.get('timedOut') is not False or
                status.get('remainingWorkersTerminated') is not False or
                type(status.get('processGroup')) is not int or status['processGroup'] <= 0):
            raise ValueError(f'unclean supervisor status for {arm}')
        hashes[arm] = base.sha(path)
    return hashes


def publish_comparison(report):
    base.require_capacity(P, 32 * 1024**3)
    with (RESULT / 'comparison.json').open('x') as output:
        output.write(json.dumps(report, indent=2, sort_keys=True) + '\n')


def verify_monitored_completion():
    receipt = json.loads((MONITORED / 'completion.json').read_text())
    paths = {'comparison': RESULT / 'comparison.json', 'monitorResult': MONITORED / 'monitor-result.json',
             'outerSupervisor': MONITORED / 'outer-monitor/supervisor-result.json',
             'telemetry': MONITORED / 'telemetry.jsonl', 'monitorScript': MONITOR_SCRIPT}
    expected = {key: base.sha(path) for key, path in paths.items()}
    if receipt.get('status') != 'passed' or receipt.get('hashes') != expected:
        raise ValueError('monitored trainer completion receipt differs')
    monitor = json.loads(paths['monitorResult'].read_text())
    outer = json.loads(paths['outerSupervisor'].read_text())
    if (monitor.get('status') != 'passed' or type(outer.get('clientExit')) is not int or outer['clientExit'] != 0 or
            'signal' not in outer or outer['signal'] is not None or outer.get('timedOut') is not False or
            outer.get('remainingWorkersTerminated') is not False or
            type(outer.get('processGroup')) is not int or outer['processGroup'] <= 0):
        raise ValueError('monitored trainer supervisor did not complete cleanly')
    return receipt


def verify_small_pilot(require_monitor=True):
    build = json.loads((BUILD / 'inputs.json').read_text()); builder.verify(BUILD, build)
    builder.verify_pilot_data()
    inputs = json.loads((RESULT / 'inputs.json').read_text()); report = json.loads((RESULT / 'comparison.json').read_text())
    dataset = PILOT / 'aggregate-control'
    expected = {'dataSHA256': base.sha(dataset / 'data.bin'), 'mapSHA256': base.sha(dataset / 'map.bin'),
                'parentSHA256': base.sha(PARENT / 'weights.bin'), 'buildSHA256': base.sha(BUILD / 'inputs.json'),
                'pilotReportSHA256': base.sha(PILOT / 'pilot-report.json'), 'scriptSHA256': base.sha(Path(__file__))}
    if any(inputs.get(key) != value for key, value in expected.items()): raise ValueError('small-pilot inputs changed')
    if inputs.get('initialSourcePhysicalMap') != [list(span) for span in physical_map(dataset / 'data.bin')]:
        raise ValueError('small-pilot source physical mapping changed')
    stock, clone = RESULT / 'stock', RESULT / 'reflink'
    for model in (stock, clone): verify_model_receipt(model, expected['dataSHA256'], expected['mapSHA256'], expected['parentSHA256'])
    if compare_models(stock, clone, PARENT): raise ValueError('small-pilot model artifacts differ')
    extents = extent_numbers(clone / 'data.bin')
    if (extents['total'] <= 0 or extents['exclusive'] > 4 * 1024**2 or
            extents['shared'] < extents['total'] - 4 * 1024**2): raise ValueError('small-pilot reflink is not predominantly shared')
    if (report.get('status') != 'passed' or report.get('differences') != [] or report.get('reflinkExtents') != extents or
            report.get('supervisorStatusSHA256') != supervisor_statuses() or
            report.get('dataSHA256') != expected['dataSHA256'] or report.get('mapSHA256') != expected['mapSHA256'] or
            report.get('parentSHA256') != expected['parentSHA256'] or
            report.get('stockWeightsSHA256') != base.sha(stock / 'weights.bin') or
            report.get('reflinkWeightsSHA256') != base.sha(clone / 'weights.bin')):
        raise ValueError('small-pilot report differs')
    if require_monitor:
        verify_monitored_completion()
    return report


def main():
    if len(sys.argv) != 1: raise SystemExit(__doc__)
    os.chdir(PROJECT)
    with base.acquire_lock(P / '.l4-matched.lock'):
        base.require_new_output(RESULT); base.require_capacity(P, 34 * 1024**3)
        build = json.loads((BUILD / 'inputs.json').read_text()); builder.verify(BUILD, build)
        pilot = builder.verify_pilot_data()
        dataset = PILOT / 'aggregate-control'; data_sha = base.sha(dataset / 'data.bin'); map_sha = base.sha(dataset / 'map.bin')
        if (builder.pair.overlay.header(dataset / 'data.bin', b'PVDATA04', 21224) != (34, 31) or
                builder.pair.overlay.header(dataset / 'map.bin', b'PVMAP001', 144) != (34, 31)):
            raise ValueError('small-pilot dataset dimensions differ')
        source_extent = physical_map(dataset / 'data.bin'); parent_sha = base.sha(PARENT / 'weights.bin')
        RESULT.mkdir()
        inputs = {'dataSHA256': data_sha, 'mapSHA256': map_sha, 'parentSHA256': parent_sha,
                  'buildSHA256': base.sha(BUILD / 'inputs.json'), 'pilotReportSHA256': base.sha(PILOT / 'pilot-report.json'),
                  'scriptSHA256': base.sha(Path(__file__)),
                  'initialSourcePhysicalMap': source_extent}
        (RESULT / 'inputs.json').write_text(json.dumps(inputs, indent=2, sort_keys=True) + '\n')
        env = {'PATH': '/usr/bin:/bin', 'HOME': str(Path.home()), 'PUPPYBOT_PROJECT': str(PROJECT),
               'LD_LIBRARY_PATH': str(PROJECT / 'build/flex/rocm-runtime'), 'SDL_VIDEODRIVER': 'offscreen'}
        for arm, control in (('stock', BUILD / 'control-stock'), ('reflink', BUILD / 'control')):
            base.require_capacity(P, 34 * 1024**3)
            model = RESULT / arm; base.require_new_output(model)
            monitor = RESULT / f'monitor-{arm}'; monitor.mkdir()
            command = [str(control), 'train', '--output', str(model), '--seed', '7110000', '--data', str(dataset / 'data.bin'),
                       '--memory-map', str(dataset / 'map.bin'), '--transition-weight-one', '--policy', str(PARENT),
                       '--categorical', '--mirror-augment', '--carry-cue', '--epochs', '1', '--batch', '2', '--checkpoint-every', '1']
            (monitor / 'command.json').write_text(json.dumps(command, indent=2) + '\n')
            status = base.hidden.supervise(command, monitor, env, 1800); base.require_success(status, monitor)
            verify_model_receipt(model, data_sha, map_sha, parent_sha)
            builder.verify(BUILD, build)
            if base.sha(dataset / 'data.bin') != data_sha or base.sha(dataset / 'map.bin') != map_sha:
                raise ValueError('pilot dataset changed during training')
            if physical_map(dataset / 'data.bin') != source_extent:
                raise ValueError('pilot source physical extents changed')
        stock, clone = RESULT / 'stock', RESULT / 'reflink'
        extents = extent_numbers(clone / 'data.bin')
        if (extents['total'] <= 0 or extents['exclusive'] > 4 * 1024**2 or
                extents['shared'] < extents['total'] - 4 * 1024**2):
            raise ValueError('trainer output was not predominantly shared')
        differences = compare_models(stock, clone, PARENT)
        report = {'status': 'passed' if not differences else 'nondeterministic_or_mismatch', 'differences': differences,
                  'dataSHA256': data_sha, 'mapSHA256': map_sha, 'parentSHA256': parent_sha,
                  'supervisorStatusSHA256': supervisor_statuses(),
                  'reflinkExtents': extents, 'stockWeightsSHA256': base.sha(stock / 'weights.bin'),
                  'reflinkWeightsSHA256': base.sha(clone / 'weights.bin'),
                  'scope': 'one small matched simulator-training pilot; equality does not prove all future GPU runs deterministic'}
        publish_comparison(report)
        if differences: raise ValueError('stock and reflink training differ; inspect diagnostic comparison')
        print(json.dumps({'status': 'passed', 'weightsSHA256': report['stockWeightsSHA256'], 'output': str(RESULT)}))


if __name__ == '__main__': main()
