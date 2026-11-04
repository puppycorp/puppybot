#!/usr/bin/env python3
"""Verify monitored saved-selection completion; never qualify held-out results."""
import hashlib
import json
import math
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
S = ROOT / 'datasets/visual-control/chase-v1/levels'
P = ROOT / 'build/flex/sim/levels-v2/pitch82'
OUTPUT = P / 'search-dagger-heading'
SELECTION = OUTPUT / 'selection-epoch8'
PLAN = OUTPUT / 'models/heading-epoch8-selection-plan.json'
MONITORED = P / 'heading-selection-monitored-v1'
MONITOR_SCRIPT = ROOT / 'flex/tests/monitored-heading-selection.py'
TASKS = ('standard', 'L1', 'L2', 'L3', 'L4', 'L5')
GIB = 1024**3
EVALUATE = S.parent / 'evaluate.sh'
RUNNER = S / 'run-heading-selection-v1.py'
WORKER = S / 'heading-selection-runner-audit.py'
PACKAGE = OUTPUT / 'models/heading-epoch8-pair'


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as file:
        for block in iter(lambda: file.read(1024 * 1024), b''): h.update(block)
    return h.hexdigest()


def source_pins():
    paths = {'monitor': MONITOR_SCRIPT, 'receipt': Path(__file__).resolve(),
             'telemetry': ROOT / 'flex/tests/monitored-visual-v4-smoke.py',
             'supervisor': ROOT / 'flex/tests/run-physical-hidden-trial.py',
             'rescan': ROOT / 'flex/tests/run-physical-rescan-trial.py',
             'cleanup': ROOT / 'flex/tests/run-physical-hybrid-trial.py',
             'runner': S / 'run-heading-selection-v1.py',
             'audit': S / 'heading-selection-audit.py',
             'auditWorker': S / 'heading-selection-runner-audit.py',
             'plan': S / 'heading-epoch8-selection.py',
             'evaluator': S.parent / 'evaluate.sh'}
    return {f'source.{name}': digest(path) for name, path in paths.items()}


def clean_status(path):
    value = json.loads(path.read_text())
    if (type(value.get('clientExit')) is not int or value['clientExit'] != 0 or
            'signal' not in value or value['signal'] is not None or value.get('timedOut') is not False or
            value.get('remainingWorkersTerminated') is not False or
            type(value.get('processGroup')) is not int or value['processGroup'] <= 0):
        raise ValueError(f'unclean selection supervisor: {path}')


def inventory():
    files = {}
    for path in sorted(SELECTION.rglob('*')):
        name = str(path.relative_to(SELECTION))
        if name == 'selection-summary.json': continue
        if path.is_symlink(): files[name] = {'symlink': os.readlink(path)}
        elif path.is_file(): files[name] = {'sha256': digest(path)}
        elif not path.is_dir(): raise ValueError(f'unexpected selection output: {path}')
    return files


def environment(task):
    return {'PATH': '/usr/bin:/bin', 'HOME': str(Path.home()), 'PUPPYBOT_PROJECT': str(ROOT),
            'SDL_VIDEODRIVER': 'offscreen', 'LD_LIBRARY_PATH': str(ROOT / 'build/flex/rocm-runtime'),
            'PUPPYBOT_EVAL_SELECTION': '1', 'PUPPYBOT_EVAL_SELECTION_SEED': '7800000',
            'PUPPYBOT_EVAL_TWO_ROOM': '1' if task['twoRoom'] else '0',
            'PUPPYBOT_CHASE_PARTS': '4', 'PUPPYBOT_CHASE_HORIZON': '300', 'PUPPYBOT_CHASE_FULL': '0'}


def arm_command(task, arm):
    return ['/usr/bin/bash', str(EVALUATE), str(SELECTION / task['name']), arm,
            str(PACKAGE / arm), '--fetch', *task['levelArgs'], '--camera-pitch', '82']


def outer_launch():
    launch = json.loads((MONITORED / 'launch.json').read_text())
    argv = launch.get('command')
    if not isinstance(argv, list) or not argv or not Path(argv[0]).is_absolute() or not Path(argv[0]).is_file():
        raise ValueError('monitor interpreter path differs')
    python = argv[0]
    code = ('import importlib.util,sys;'
            's=importlib.util.spec_from_file_location("monitored",sys.argv[1]);'
            'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);'
            'm.monitor_worker(sys.argv[2])')
    env = {'PATH': '/usr/bin:/bin', 'HOME': str(Path.home()), 'SDL_VIDEODRIVER': 'offscreen',
           'LD_LIBRARY_PATH': str(ROOT / 'build/flex/rocm-runtime')}
    if (argv != [python, '-I', '-c', code, str(MONITOR_SCRIPT), str(MONITORED)] or
            launch.get('environment') != env or launch.get('wallSeconds') != 65400):
        raise ValueError('monitor launch intent differs')
    return launch, python


def expected_runner_pins(python):
    files = (RUNNER, WORKER, Path(python), ROOT / 'flex/tests/run-physical-hidden-trial.py',
             ROOT / 'flex/tests/run-physical-rescan-trial.py', ROOT / 'flex/tests/run-physical-hybrid-trial.py')
    return {str(path): digest(path) for path in files}


def read_samples(path):
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    previous = -1.0
    for row in rows:
        if (not isinstance(row, dict) or 'error' in row or
                any(type(row.get(k)) not in (int, float) or not math.isfinite(row[k]) for k in ('monotonicSeconds', 'unixSeconds')) or
                row['monotonicSeconds'] <= previous):
            raise ValueError(f'invalid telemetry time or error: {path}')
        previous = row['monotonicSeconds']
    return rows


def validate_telemetry():
    rows = read_samples(MONITORED / 'telemetry.jsonl')
    phases = [row.get('phase') for row in rows]
    if not rows or phases[-1] != 'after-selection' or phases.count('after-selection') != 1:
        raise ValueError('GPU final sample missing')
    baseline = [row for row in rows if row.get('phase') == 'baseline']
    active = [row for row in rows if row.get('phase') == 'selection']
    if (len(baseline) < 2 or not active or phases != ['baseline'] * len(baseline) + ['selection'] * len(active) + ['after-selection'] or
            baseline[-1]['monotonicSeconds'] - baseline[0]['monotonicSeconds'] < 30):
        raise ValueError('GPU baseline or active samples incomplete')
    consecutive = 0
    for row in rows:
        if (any(type(row.get(key)) is not int for key in ('busyPercent', 'totalBytes', 'usedBytes', 'freeBytes')) or
                not 0 <= row['busyPercent'] <= 100 or row['totalBytes'] <= 0 or
                not 0 <= row['usedBytes'] <= row['totalBytes'] or row['freeBytes'] != row['totalBytes'] - row['usedBytes']):
            raise ValueError('invalid GPU telemetry values')
        minimum = 6 * GIB if row['phase'] == 'baseline' else 2 * GIB
        if row['freeBytes'] < minimum: raise ValueError('GPU free memory below guard')
        if row['phase'] == 'baseline':
            consecutive = consecutive + 1 if row['busyPercent'] > 10 else 0
            if consecutive >= 5: raise ValueError('GPU baseline busy guard exceeded')
    disk = read_samples(MONITORED / 'disk.jsonl')
    phases = [row.get('phase') for row in disk]
    active_disk = [row for row in disk if row.get('phase') == 'selection']
    if not active_disk or phases != ['pre-baseline', 'post-baseline'] + ['selection'] * len(active_disk) + ['after-selection']:
        raise ValueError('disk samples incomplete')
    if (len(active_disk) != len(active) or disk[0]['monotonicSeconds'] > baseline[0]['monotonicSeconds'] or
            disk[1]['monotonicSeconds'] < baseline[-1]['monotonicSeconds'] or
            disk[-1]['monotonicSeconds'] < rows[-1]['monotonicSeconds']):
        raise ValueError('GPU and disk sample timing differs')
    if any(type(row.get('freeBytes')) is not int or row['freeBytes'] < 33 * GIB for row in disk):
        raise ValueError('disk headroom guard exceeded')


def snapshot():
    launch, python = outer_launch()
    validate_telemetry()
    plan = json.loads(PLAN.read_text())
    tasks = plan.get('tasks')
    if not isinstance(tasks, list) or len(tasks) != len(TASKS):
        raise ValueError('selection plan tasks differ')
    for level, task in enumerate(tasks):
        if (task.get('name') != TASKS[level] or type(task.get('level')) is not int or task['level'] != level or
                task.get('levelArgs') != ([] if level == 0 else ['--level', str(level)]) or
                task.get('twoRoom') is not (level >= 4)):
            raise ValueError('selection plan task configuration differs')
    runner_launch = json.loads((SELECTION / 'launch.json').read_text())
    expected_tasks = [{'task': task['name'], 'arms': [{'argv': arm_command(task, arm), 'environment': environment(task)}
                       for arm in ('control', 'treatment')]} for task in tasks]
    if (runner_launch.get('planSHA256') != digest(PLAN) or runner_launch.get('files') != expected_runner_pins(python) or
            runner_launch.get('tasks') != expected_tasks):
        raise ValueError('runner launch intent or source pins differ')
    summary = json.loads((SELECTION / 'selection-summary.json').read_text())
    if summary.get('status') != 'selection_comparison_only' or set(summary.get('tasks', {})) != set(TASKS):
        raise ValueError('complete six-task selection summary required')
    if (SELECTION / 'selection.partial.json').exists():
        raise ValueError('selection partial evidence exists')
    for task in tasks:
        name = task['name']; item = summary['tasks'][name]
        if item.get('status') != 'paired_saved_audit' or set(item.get('arms', {})) != {'control', 'treatment'}:
            raise ValueError(f'incomplete selection task: {name}')
        for arm in ('control', 'treatment'):
            audit = item['arms'][arm]
            if audit.get('status') != 'saved_arm_audit_only' or audit.get('task') != name or audit.get('arm') != arm:
                raise ValueError(f'arm audit differs: {name} {arm}')
        if item.get('pair', {}).get('status') != 'paired_selection_audit_only' or item['pair'].get('task') != name:
            raise ValueError(f'pair audit differs: {name}')
        for mode in ('run-control', 'run-treatment', 'audit-control', 'audit-treatment', 'audit-pair'):
            directory = SELECTION / f'evidence-{name}' / mode
            clean_status(directory / 'supervisor-result.json')
            kind, which = mode.split('-', 1)
            argv = arm_command(task, which) if kind == 'run' else [python, '-I', str(WORKER), which, name]
            expected = {'argv': argv, 'environment': environment(task), 'wallSeconds': 3600 if kind == 'run' else 600}
            if json.loads((directory / 'invocation.json').read_text()) != expected:
                raise ValueError(f'selection invocation intent differs: {name} {mode}')
            if kind == 'audit':
                expected_result = item['pair'] if which == 'pair' else item['arms'][which]
                if json.loads((directory / 'client.log').read_text()) != expected_result:
                    raise ValueError(f'saved audit output differs: {name} {mode}')
    if summary.get('inventory') != inventory():
        raise ValueError('selection inventory changed')
    if json.loads((MONITORED / 'monitor-result.json').read_text()).get('status') != 'passed':
        raise ValueError('GPU monitor did not pass')
    clean_status(MONITORED / 'outer-monitor/supervisor-result.json')
    files = {'selectionSummary': SELECTION / 'selection-summary.json', 'plan': PLAN,
             'monitorResult': MONITORED / 'monitor-result.json',
             'outerStatus': MONITORED / 'outer-monitor/supervisor-result.json',
             'telemetry': MONITORED / 'telemetry.jsonl', 'disk': MONITORED / 'disk.jsonl',
             'launch': MONITORED / 'launch.json'}
    result = {name: digest(path) for name, path in files.items()}
    result.update(source_pins())
    return result


def verify():
    receipt = json.loads((MONITORED / 'completion.json').read_text())
    if receipt.get('status') != 'passed' or receipt.get('hashes') != snapshot():
        raise ValueError('monitored selection receipt differs')
    if type(receipt.get('freeBytesBeforeReceipt')) is not int or receipt['freeBytesBeforeReceipt'] < 32 * GIB:
        raise ValueError('selection receipt disk floor was not met')
    launch = json.loads((MONITORED / 'launch.json').read_text())
    if launch.get('sourcePins') != source_pins():
        raise ValueError('selection monitoring sources changed')
    return receipt
