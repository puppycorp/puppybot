#!/usr/bin/env python3
"""Staged fixed-plan selection runner. CLI deliberately disabled pending review.

Must run under an independent absolute-deadline subreaper and GPU resource
monitor. Records intended commands and saved-data checks, not proof of actual
OS execution, actor input, source ancestry, held-out success or a winner.
"""
import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[4]
S = PROJECT / 'datasets/visual-control/chase-v1/levels'
spec = importlib.util.spec_from_file_location('heading_audit', S / 'heading-selection-audit.py')
audit = importlib.util.module_from_spec(spec); spec.loader.exec_module(audit)
plan_tool = audit.plan_tool
base = plan_tool.base
EVALUATE = PROJECT / 'datasets/visual-control/chase-v1/evaluate.sh'
WORKER = S / 'heading-selection-runner-audit.py'
ARM_SECONDS = 3600
AUDIT_SECONDS = 600
INITIAL_FREE = 12 * 1024 ** 3
MIN_FREE = 8 * 1024 ** 3


def environment(task):
    return {'PATH': '/usr/bin:/bin', 'HOME': str(Path.home()),
            'PUPPYBOT_PROJECT': str(PROJECT), 'SDL_VIDEODRIVER': 'offscreen',
            'LD_LIBRARY_PATH': str(PROJECT / 'build/flex/rocm-runtime'),
            'PUPPYBOT_EVAL_SELECTION': '1', 'PUPPYBOT_EVAL_SELECTION_SEED': '7800000',
            'PUPPYBOT_EVAL_TWO_ROOM': '1' if task['twoRoom'] else '0',
            'PUPPYBOT_CHASE_PARTS': '4', 'PUPPYBOT_CHASE_HORIZON': '300', 'PUPPYBOT_CHASE_FULL': '0'}


def command(task, arm):
    if arm not in ('control', 'treatment'): raise ValueError('unknown arm')
    return ['/usr/bin/bash', str(EVALUATE), str(plan_tool.SELECTION_ROOT / task['name']), arm,
            str(plan_tool.PACKAGE / arm), '--fetch', *task['levelArgs'], '--camera-pitch', '82']


def write_new(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False); stream.write('\n')


def pins():
    return {str(path): base.sha(path) for path in (Path(__file__), WORKER, Path(sys.executable),
            PROJECT / 'flex/tests/run-physical-hidden-trial.py',
            PROJECT / 'flex/tests/run-physical-rescan-trial.py',
            PROJECT / 'flex/tests/run-physical-hybrid-trial.py')}


def supervised(command_line, directory, env, limit):
    directory.mkdir()
    write_new(directory / 'invocation.json', {'argv': command_line, 'environment': env, 'wallSeconds': limit})
    status = base.hidden.supervise(command_line, directory, env, wall_seconds=limit)
    base.require_success(status, directory)
    plan_tool.clean_status(directory / 'supervisor-result.json')
    return status


def audit_saved(task, mode, evidence, env):
    directory = evidence / f'audit-{mode}'
    supervised([sys.executable, '-I', str(WORKER), mode, task['name']], directory, env, AUDIT_SECONDS)
    result = json.loads((directory / 'client.log').read_text())
    expected = 'paired_selection_audit_only' if mode == 'pair' else 'saved_arm_audit_only'
    if result.get('status') != expected or result.get('task') != task['name']:
        raise ValueError('saved audit result differs')
    if mode != 'pair' and result.get('arm') != mode: raise ValueError('saved audit arm differs')
    return result


def inventory(root):
    files = {}
    for path in sorted(root.rglob('*')):
        name = str(path.relative_to(root))
        if path.is_symlink(): files[name] = {'symlink': os.readlink(path)}
        elif path.is_file(): files[name] = {'sha256': base.sha(path)}
        elif not path.is_dir(): raise ValueError(f'unexpected output type: {path}')
    return files


def run():
    os.environ['PUPPYBOT_PROJECT'] = str(PROJECT)
    with base.acquire_lock(plan_tool.LOCK):
        base.require_new_output(plan_tool.SELECTION_ROOT)
        base.require_capacity(plan_tool.OUTPUT, INITIAL_FREE)
        plan, _ = audit.validate_plan(plan_tool.PLAN, 'standard')
        if plan['tasks'] != plan_tool.selection_design(): raise ValueError('fixed task design differs')
        initial_pins = pins(); plan_hash = base.sha(plan_tool.PLAN)
        root = plan_tool.SELECTION_ROOT; root.mkdir()
        statuses = {t['name']: {'status': 'not_started'} for t in plan['tasks']}
        try:
            write_new(root / 'launch.json', {'planSHA256': plan_hash, 'files': initial_pins,
                      'tasks': [{'task': t['name'], 'arms': [{'argv': command(t, a), 'environment': environment(t)}
                               for a in ('control', 'treatment')]} for t in plan['tasks']],
                      'scope': 'intended commands and saved artifacts only; no independent OS or actor attestation'})
            for task in plan['tasks']:
                name = task['name']; statuses[name] = {'status': 'censored', 'arms': {}}
                task_root = root / name; task_root.mkdir()
                evidence = root / f'evidence-{name}'; evidence.mkdir()
                env = environment(task)
                for arm in ('control', 'treatment'):
                    base.require_capacity(root, MIN_FREE)
                    if pins() != initial_pins or base.sha(plan_tool.PLAN) != plan_hash or plan_tool.plan_inputs(plan['tasks']) != plan['files']:
                        raise ValueError('registered inputs changed')
                    supervised(command(task, arm), evidence / f'run-{arm}', env, ARM_SECONDS)
                    statuses[name]['arms'][arm] = audit_saved(task, arm, evidence, env)
                pair = audit_saved(task, 'pair', evidence, env)
                statuses[name] = {'status': 'paired_saved_audit', 'arms': statuses[name]['arms'], 'pair': pair}
            if pins() != initial_pins or base.sha(plan_tool.PLAN) != plan_hash:
                raise ValueError('runner or plan changed')
            if audit.validate_plan(plan_tool.PLAN, 'standard')[0] != plan:
                raise ValueError('registered plan changed')
            base.require_capacity(root, MIN_FREE)
            write_new(root / 'selection-summary.json', {'status': 'selection_comparison_only', 'tasks': statuses,
                      'inventory': inventory(root), 'scope': 'recorded outputs only; no OS execution attestation, promotion decision, held-out or physical evidence'})
        except BaseException as error:
            write_new(root / 'selection.partial.json', {'status': 'censored', 'tasks': statuses,
                      'error': str(error), 'scope': 'incomplete; retained evidence is not a completed comparison'})
            raise


if __name__ == '__main__':
    raise SystemExit('Disabled pending independent review, external watchdog and GPU resource monitoring.')
