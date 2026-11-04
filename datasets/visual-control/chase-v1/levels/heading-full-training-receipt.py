#!/usr/bin/env python3
"""Verify monitored full-training completion; not a model promotion."""
import hashlib
import importlib.util
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
S = ROOT / 'datasets/visual-control/chase-v1/levels'
P = ROOT / 'build/flex/sim/levels-v2/pitch82'
OUTPUT = P / 'search-dagger-heading'
MODELS = OUTPUT / 'models'
MONITORED = P / 'heading-full-training-monitored-v1'
MONITOR_SCRIPT = ROOT / 'flex/tests/monitored-heading-full-training.py'
RUNNER = S / 'run-heading-training.py'
BUILD = P / 'search-dagger-heading-trainer-build'
PARENT = P / 'search-dagger-l4-matched/epoch8-pair/treatment'
GIB = 1024**3
AUDITOR = S / 'audit-matched-training.py'
spec = importlib.util.spec_from_file_location('matched_training_auditor', AUDITOR)
matched_training = importlib.util.module_from_spec(spec); spec.loader.exec_module(matched_training)
spec = importlib.util.spec_from_file_location('full_training_verifier', RUNNER)
training = importlib.util.module_from_spec(spec); spec.loader.exec_module(training)


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as file:
        for block in iter(lambda: file.read(1024 * 1024), b''): h.update(block)
    return h.hexdigest()


def source_pins():
    paths = {'monitor': MONITOR_SCRIPT, 'receipt': Path(__file__).resolve(), 'runner': RUNNER,
             'telemetry': ROOT / 'flex/tests/monitored-visual-v4-smoke.py',
             'supervisor': ROOT / 'flex/tests/run-physical-hidden-trial.py',
             'rescan': ROOT / 'flex/tests/run-physical-rescan-trial.py',
             'cleanup': ROOT / 'flex/tests/run-physical-hybrid-trial.py',
             'matchedAudit': AUDITOR, 'parentWeights': PARENT / 'weights.bin'}
    return {f'source.{name}': digest(path) for name, path in paths.items()}


def clean_status(path):
    row = json.loads(path.read_text())
    if (type(row.get('clientExit')) is not int or row['clientExit'] != 0 or
            'signal' not in row or row['signal'] is not None or row.get('timedOut') is not False or
            row.get('remainingWorkersTerminated') is not False or
            type(row.get('processGroup')) is not int or row['processGroup'] <= 0):
        raise ValueError(f'unclean training supervisor: {path}')


def samples(path):
    rows = [json.loads(line) for line in path.read_text().splitlines()]; previous = -1.0
    for row in rows:
        if (not isinstance(row, dict) or 'error' in row or
                any(type(row.get(k)) not in (int, float) or not math.isfinite(row[k]) for k in ('monotonicSeconds', 'unixSeconds')) or
                row['monotonicSeconds'] <= previous): raise ValueError(f'invalid telemetry time or error: {path}')
        previous = row['monotonicSeconds']
    return rows


def validate_telemetry():
    rows = samples(MONITORED / 'telemetry.jsonl'); phases = [r.get('phase') for r in rows]
    baseline = [r for r in rows if r.get('phase') == 'baseline']; active = [r for r in rows if r.get('phase') == 'training']
    if (len(baseline) < 2 or not active or phases != ['baseline'] * len(baseline) + ['training'] * len(active) + ['after-training'] or
            baseline[-1]['monotonicSeconds'] - baseline[0]['monotonicSeconds'] < 30):
        raise ValueError('incomplete GPU baseline, active or final samples')
    consecutive = 0
    for row in rows:
        if (any(type(row.get(k)) is not int for k in ('busyPercent', 'totalBytes', 'usedBytes', 'freeBytes')) or
                not 0 <= row['busyPercent'] <= 100 or row['totalBytes'] <= 0 or
                not 0 <= row['usedBytes'] <= row['totalBytes'] or row['freeBytes'] != row['totalBytes'] - row['usedBytes']):
            raise ValueError('invalid GPU telemetry')
        if row['freeBytes'] < (6 if row['phase'] == 'baseline' else 2) * GIB: raise ValueError('GPU memory guard exceeded')
        if row['phase'] == 'baseline':
            consecutive = consecutive + 1 if row['busyPercent'] > 10 else 0
            if consecutive >= 5: raise ValueError('GPU baseline busy guard exceeded')
    disk = samples(MONITORED / 'disk.jsonl'); phases = [r.get('phase') for r in disk]
    active_disk = [r for r in disk if r.get('phase') == 'training']
    if (not active_disk or len(active_disk) != len(active) or
            phases != ['pre-baseline', 'post-baseline'] + ['training'] * len(active_disk) + ['after-training'] or
            disk[0]['monotonicSeconds'] > baseline[0]['monotonicSeconds'] or
            disk[1]['monotonicSeconds'] < baseline[-1]['monotonicSeconds'] or
            disk[-1]['monotonicSeconds'] < rows[-1]['monotonicSeconds']):
        raise ValueError('incomplete or inconsistent disk samples')
    if any(type(row.get('freeBytes')) is not int or row['freeBytes'] < 34 * GIB for row in disk):
        raise ValueError('disk headroom guard exceeded')


def expected_command(arm):
    return [str(BUILD / 'control'), 'train', '--output', str(MODELS / f'{arm}-s0'), '--seed', '6900000',
            '--data', str(OUTPUT / f'aggregate-{arm}/data.bin'), '--memory-map', str(OUTPUT / f'aggregate-{arm}/map.bin'),
            '--transition-weight-one', '--policy', str(PARENT), '--categorical', '--mirror-augment',
            '--carry-cue', '--epochs', '8', '--batch', '2', '--checkpoint-every', '8']


def validate_launch():
    launch = json.loads((MONITORED / 'launch.json').read_text()); argv = launch.get('command')
    if not isinstance(argv, list) or not argv or not Path(argv[0]).is_absolute() or not Path(argv[0]).is_file():
        raise ValueError('monitor interpreter path differs')
    code = ('import importlib.util,sys;'
            's=importlib.util.spec_from_file_location("monitored",sys.argv[1]);'
            'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);'
            'm.monitor_worker(sys.argv[2])')
    env = {'PATH': '/usr/bin:/bin', 'HOME': str(Path.home()), 'SDL_VIDEODRIVER': 'offscreen',
           'LD_LIBRARY_PATH': str(ROOT / 'build/flex/rocm-runtime')}
    if (argv != [argv[0], '-I', '-c', code, str(MONITOR_SCRIPT), str(MONITORED)] or
            launch.get('environment') != env or launch.get('wallSeconds') != 15000):
        raise ValueError('training monitor launch intent differs')
    if json.loads((MONITORED / 'worker-invocation.json').read_text()) != {'argv': [argv[0], '-I', str(RUNNER)], 'cwd': str(ROOT)}:
        raise ValueError('training worker intent differs')


def snapshot():
    validate_launch()
    validate_telemetry()
    report = json.loads((MODELS / 'training-report.json').read_text())
    if report.get('status') != 'training_diagnostic_only' or set(report.get('arms', {})) != {'control', 'treatment'}:
        raise ValueError('full training report is incomplete')
    inputs = json.loads((MODELS / 'inputs.json').read_text())
    if (training.sources() != inputs or report.get('pairReadySHA256') != digest(OUTPUT / 'pair-ready.json') or
            report.get('smallPilotSHA256') != digest(training.small.RESULT / 'comparison.json')):
        raise ValueError('full training input provenance differs')
    matched = matched_training.audit(PARENT, MODELS / 'control-s0', MODELS / 'treatment-s0')
    if report.get('matchedArtifacts') != matched:
        raise ValueError('matched training artifact comparison differs')
    if json.loads((MONITORED / 'monitor-result.json').read_text()).get('status') != 'passed':
        raise ValueError('GPU monitor did not pass')
    clean_status(MONITORED / 'outer-monitor/supervisor-result.json')
    paths = {'trainingReport': MODELS / 'training-report.json', 'inputs': MODELS / 'inputs.json',
             'pairReady': OUTPUT / 'pair-ready.json', 'monitorResult': MONITORED / 'monitor-result.json',
             'outerStatus': MONITORED / 'outer-monitor/supervisor-result.json',
             'telemetry': MONITORED / 'telemetry.jsonl', 'disk': MONITORED / 'disk.jsonl',
             'launch': MONITORED / 'launch.json', 'workerInvocation': MONITORED / 'worker-invocation.json'}
    for arm in ('control', 'treatment'):
        monitor = MODELS / f'monitor-{arm}'; model = MODELS / f'{arm}-s0'
        data = OUTPUT / f'aggregate-{arm}'
        training.verify_full_receipt(model, inputs[str(data / 'data.bin')], inputs[str(data / 'map.bin')], digest(PARENT / 'weights.bin'))
        clean_status(monitor / 'supervisor-result.json')
        if json.loads((monitor / 'command.json').read_text()) != expected_command(arm):
            raise ValueError(f'training command intent differs: {arm}')
        for name in ('command.json', 'supervisor-result.json', 'client.log'):
            paths[f'{arm}.monitor.{name}'] = monitor / name
        for name in ('data.bin', 'weights.bin', 'initial.bin', 'first-order.bin', 'final-order.bin',
                     'first-mirror-mask.bin', 'epoch-8.bin', 'last.bin', 'policy', 'model.pup',
                     'factory.flex', 'receipt.json', 'curves.jsonl'):
            paths[f'{arm}.model.{name}'] = model / name
        kernels = sorted(path for path in (model / 'kernels').iterdir() if path.is_file())
        if not kernels: raise ValueError(f'missing model kernels: {arm}')
        for kernel in kernels: paths[f'{arm}.kernel.{kernel.name}'] = kernel
    result = {name: digest(path) for name, path in paths.items()}
    for arm in ('control', 'treatment'):
        model_receipt = json.loads((MODELS / f'{arm}-s0/receipt.json').read_text())
        if (report['arms'][arm].get('weightsSHA256') != result[f'{arm}.model.weights.bin'] or
                report['arms'][arm].get('receiptSHA256') != result[f'{arm}.model.receipt.json'] or
                model_receipt.get('dataSHA256') != result[f'{arm}.model.data.bin'] or
                model_receipt.get('weightsSHA256') != result[f'{arm}.model.weights.bin'] or
                result[f'{arm}.model.epoch-8.bin'] != result[f'{arm}.model.last.bin']):
            raise ValueError(f'training report or model receipt differs: {arm}')
    result.update(source_pins())
    return result


def verify():
    receipt = json.loads((MONITORED / 'completion.json').read_text())
    if receipt.get('status') != 'passed' or receipt.get('hashes') != snapshot():
        raise ValueError('monitored full-training receipt differs')
    if type(receipt.get('freeBytesBeforeReceipt')) is not int or receipt['freeBytesBeforeReceipt'] < 32 * GIB:
        raise ValueError('training receipt disk floor was not met')
    launch = json.loads((MONITORED / 'launch.json').read_text())
    if launch.get('sourcePins') != source_pins(): raise ValueError('training monitoring sources changed')
    return receipt
