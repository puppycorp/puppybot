#!/usr/bin/env python3
"""Disabled teacher-selection runner; requires an independent outer monitor."""
import importlib.util
import json
import os
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[4]
S = PROJECT / 'datasets/visual-control/chase-v1/levels'
spec = importlib.util.spec_from_file_location('teacher_frozen', S / 'heading-teacher-frozen-v1.py')
frozen = importlib.util.module_from_spec(spec); spec.loader.exec_module(frozen)
base = frozen.base
ARM_SECONDS = 3600
AUDIT_SECONDS = 600


def write_new(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False); stream.write('\n')


def supervised(argv, directory, env, limit):
    directory.mkdir()
    write_new(directory / 'invocation.json', {'argv': argv, 'cwd': str(PROJECT), 'environment': env, 'wallSeconds': limit})
    status = base.hidden.supervise(argv, directory, env, wall_seconds=limit)
    base.require_success(status, directory)
    frozen.draft.plan_tool.clean_status(directory / 'supervisor-result.json')


def audit(task, output, env):
    directory = output / 'audit'
    supervised([sys.executable, '-I', str(frozen.WORKER), task], directory, env, AUDIT_SECONDS)
    result = json.loads((directory / 'client.log').read_text())
    if (result.get('status') != 'complete_diagnostic' or
            (task != 'pool' and (result.get('task') != task or type(result.get('level')) is not int or
                                 result.get('level') != (0 if task == 'standard' else int(task[1:])))) or
            (task == 'pool' and result.get('levels') != ['L1', 'L2', 'L3', 'L4', 'L5'])):
        raise ValueError(f'teacher audit censored: {task}')
    return result


def inventory(root):
    files = {}
    for path in sorted(root.rglob('*')):
        name = str(path.relative_to(root))
        if path.is_symlink(): files[name] = {'symlink': os.readlink(path)}
        elif path.is_file(): files[name] = {'sha256': base.sha(path)}
        elif not path.is_dir(): raise ValueError(f'unexpected teacher output type: {path}')
    return files


def run():
    os.environ['PUPPYBOT_PROJECT'] = str(PROJECT)
    with base.acquire_lock(frozen.draft.plan_tool.LOCK):
        base.require_new_output(frozen.OUTPUT)
        base.require_capacity(frozen.P, 38 * frozen.GIB)
        plan = frozen.verify(); plan_sha = base.sha(frozen.PLAN)
        root = frozen.OUTPUT; root.mkdir()
        statuses = {task['name']: {'status': 'not_started'} for task in plan['draft']['tasks']}
        try:
            write_new(root / 'launch.json', {'planSHA256': plan_sha, 'tasks': plan['draft']['tasks'],
                      'scope': 'intended commands only, not OS or actor execution attestation'})
            for task in plan['draft']['tasks']:
                name = task['name']; statuses[name] = {'status': 'censored'}
                base.require_capacity(root, 34 * frozen.GIB)
                if frozen.pins() != plan['sourcePins'] or base.sha(frozen.PLAN) != plan_sha:
                    raise ValueError('teacher plan or source changed')
                task_root = root / name; task_root.mkdir(); evidence = root / f'evidence-{name}'; evidence.mkdir()
                supervised(task['argv'], evidence / 'run', task['environment'], ARM_SECONDS)
                result = audit(name, evidence, task['environment'])
                statuses[name] = {'status': 'complete_diagnostic', 'audit': result}
            evidence = root / 'evidence-pool'; evidence.mkdir()
            # Pool worker sees fixed task audit logs and contains no policy invocation.
            pool = audit('pool', evidence, plan['draft']['tasks'][0]['environment'])
            if frozen.verify() != plan: raise ValueError('teacher inputs changed during evaluation')
            base.require_capacity(root, 32 * frozen.GIB)
            write_new(root / 'teacher-summary.json', {'status': 'teacher_comparison_diagnostic_only',
                      'tasks': statuses, 'pool': pool, 'inventory': inventory(root),
                      'scope': 'training-layout saved outputs only; no held-out, physical or OS execution attestation'})
        except BaseException as error:
            write_new(root / 'teacher.partial.json', {'status': 'censored', 'tasks': statuses, 'error': str(error)})
            raise


if __name__ == '__main__':
    raise SystemExit('Disabled pending independent review and monitored scheduling.')
