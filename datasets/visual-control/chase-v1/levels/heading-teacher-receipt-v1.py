#!/usr/bin/env python3
"""Verify monitored saved teacher comparison, not held-out qualification."""
import importlib.util
import json
import os
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[4]
S = PROJECT / 'datasets/visual-control/chase-v1/levels'
spec = importlib.util.spec_from_file_location('teacher_frozen', S / 'heading-teacher-frozen-v1.py')
frozen = importlib.util.module_from_spec(spec); spec.loader.exec_module(frozen)
base = frozen.base
spec = importlib.util.spec_from_file_location('selection_receipt', S / 'heading-selection-receipt.py')
selection_receipt = importlib.util.module_from_spec(spec); spec.loader.exec_module(selection_receipt)
spec = importlib.util.spec_from_file_location('teacher_audit_pool', frozen.AUDIT)
teacher_audit = importlib.util.module_from_spec(spec); spec.loader.exec_module(teacher_audit)


def inventory():
    files = {}
    for path in sorted(frozen.OUTPUT.rglob('*')):
        name = str(path.relative_to(frozen.OUTPUT))
        if name == 'teacher-summary.json': continue
        if path.is_symlink(): files[name] = {'symlink': os.readlink(path)}
        elif path.is_file(): files[name] = {'sha256': base.sha(path)}
        elif not path.is_dir(): raise ValueError(f'unexpected teacher output: {path}')
    return files


def invocation(directory, argv, env, limit):
    selection_receipt.clean_status(directory / 'supervisor-result.json')
    expected = {'argv': argv, 'cwd': str(PROJECT), 'environment': env, 'wallSeconds': limit}
    if json.loads((directory / 'invocation.json').read_text()) != expected:
        raise ValueError(f'teacher invocation differs: {directory}')


def snapshot():
    plan = frozen.verify(); monitor = frozen.MONITORED
    launch = json.loads((monitor / 'launch.json').read_text()); argv = launch.get('command')
    if not isinstance(argv, list) or not argv or not Path(argv[0]).is_absolute() or not Path(argv[0]).is_file():
        raise ValueError('invalid monitor interpreter')
    python = argv[0]
    code = ('import importlib.util,sys;'
            's=importlib.util.spec_from_file_location("teacher_monitor",sys.argv[1]);'
            'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.monitor_worker(sys.argv[2])')
    env = {'PATH': '/usr/bin:/bin', 'HOME': str(Path.home()), 'SDL_VIDEODRIVER': 'offscreen',
           'LD_LIBRARY_PATH': str(PROJECT / 'build/flex/rocm-runtime')}
    if (argv != [python, '-I', '-c', code, str(frozen.MONITOR), str(monitor)] or
            launch.get('environment') != env or launch.get('wallSeconds') != 32600 or
            launch.get('sourcePins') != plan['sourcePins']):
        raise ValueError('monitor launch intent differs')
    worker_code = ('import importlib.util,sys;'
                   's=importlib.util.spec_from_file_location("teacher_runner",sys.argv[1]);'
                   'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.run()')
    if json.loads((monitor / 'worker-invocation.json').read_text()) != {
            'argv': [python, '-I', '-c', worker_code, str(frozen.RUNNER)], 'cwd': str(PROJECT)}:
        raise ValueError('teacher worker launch intent differs')
    selection_receipt.MONITORED = monitor
    selection_receipt.validate_telemetry()
    disk = selection_receipt.read_samples(monitor / 'disk.jsonl')
    if (len(disk) < 4 or any(type(row.get('freeBytes')) is not int or row['freeBytes'] < 34 * frozen.GIB for row in disk) or
            any(row['freeBytes'] < 38 * frozen.GIB for row in disk[:2])):
        raise ValueError('teacher disk headroom guard exceeded')
    if json.loads((monitor / 'monitor-result.json').read_text()).get('status') != 'passed':
        raise ValueError('teacher GPU monitor did not pass')
    selection_receipt.clean_status(monitor / 'outer-monitor/supervisor-result.json')
    root = frozen.OUTPUT
    summary = json.loads((root / 'teacher-summary.json').read_text())
    if summary.get('status') != 'teacher_comparison_diagnostic_only' or (root / 'teacher.partial.json').exists():
        raise ValueError('completed teacher diagnostic required')
    tasks = plan['draft']['tasks']
    if set(summary.get('tasks', {})) != {task['name'] for task in tasks}: raise ValueError('teacher tasks differ')
    runner_launch = json.loads((root / 'launch.json').read_text())
    if runner_launch.get('planSHA256') != base.sha(frozen.PLAN) or runner_launch.get('tasks') != tasks:
        raise ValueError('teacher launch intent differs')
    for task in tasks:
        name = task['name']; item = summary['tasks'][name]; evidence = root / f'evidence-{name}'
        if (item.get('status') != 'complete_diagnostic' or item.get('audit', {}).get('status') != 'complete_diagnostic' or
                item['audit'].get('task') != name or type(item['audit'].get('level')) is not int or
                item['audit'].get('level') != task['level']):
            raise ValueError(f'censored teacher task: {name}')
        invocation(evidence / 'run', task['argv'], task['environment'], 3600)
        invocation(evidence / 'audit', [python, '-I', str(frozen.WORKER), name], task['environment'], 600)
        if json.loads((evidence / 'audit/client.log').read_text()) != item['audit']:
            raise ValueError('teacher task audit differs')
    pool = root / 'evidence-pool/audit'; env = tasks[0]['environment']
    invocation(pool, [python, '-I', str(frozen.WORKER), 'pool'], env, 600)
    if (json.loads((pool / 'client.log').read_text()) != summary.get('pool') or
            summary['pool'].get('status') != 'complete_diagnostic' or
            summary['pool'].get('levels') != ['L1', 'L2', 'L3', 'L4', 'L5']):
        raise ValueError('teacher pooled audit differs')
    reports = {task['name']: summary['tasks'][task['name']]['audit'] for task in tasks if task['level'] in range(1, 6)}
    if teacher_audit.audit_pool(reports) != summary['pool']:
        raise ValueError('teacher pooled audit disagrees with task reports')
    if summary.get('inventory') != inventory(): raise ValueError('teacher inventory changed')
    if frozen.verify() != plan: raise ValueError('teacher plan or student evidence changed')
    paths = {'plan': frozen.PLAN, 'summary': root / 'teacher-summary.json', 'monitorLaunch': monitor / 'launch.json',
             'monitorResult': monitor / 'monitor-result.json', 'outerStatus': monitor / 'outer-monitor/supervisor-result.json',
             'telemetry': monitor / 'telemetry.jsonl', 'disk': monitor / 'disk.jsonl',
             'workerInvocation': monitor / 'worker-invocation.json'}
    return {key: base.sha(path) for key, path in paths.items()}


def verify():
    receipt = json.loads((frozen.MONITORED / 'completion.json').read_text())
    if receipt.get('status') != 'complete_diagnostic' or receipt.get('hashes') != snapshot():
        raise ValueError('monitored teacher receipt differs')
    if type(receipt.get('freeBytesBeforeReceipt')) is not int or receipt['freeBytesBeforeReceipt'] < 32 * frozen.GIB:
        raise ValueError('teacher receipt disk floor was not met')
    return receipt
