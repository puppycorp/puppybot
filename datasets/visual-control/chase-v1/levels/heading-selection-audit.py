#!/usr/bin/env python3
"""Audit one matched heading selection pair, including standard and L2.

Usage: heading-selection-audit.py PLAN TASK
Reads registered inputs and selection outputs only; never executes policies.
The plan and output provenance are not tamper-proof and do not qualify holdout.
"""
import importlib.util
import json
import os
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[4]
S = PROJECT / 'datasets/visual-control/chase-v1/levels'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


plan_tool = load('heading_plan', S / 'heading-epoch8-selection.py')
selection = load('selection_audit', S / 'audit-selection.py')
qualification = load('selection_checks', S / 'qualify-selection.py')
heldout_helpers = load('backforth_helpers', S / 'audit-heldout.py')
metrics = load('heading_metrics', S / 'heading-selection-metrics.py')
monitored_receipt = load('selection_receipt', S / 'heading-selection-receipt.py')


def validate_plan(path, task_name):
    if Path(path).absolute() != plan_tool.PLAN:
        raise ValueError('expected the registered heading selection plan')
    plan = json.loads(Path(path).read_text())
    if plan != plan_tool.make_plan(plan_tool.verify_training()):
        raise ValueError('registered selection plan differs')
    tasks = [task for task in plan['tasks'] if task['name'] == task_name]
    if len(tasks) != 1: raise ValueError('unknown selection task')
    return plan, tasks[0]


def audit_pair(task, root, models):
    if task['level'] not in range(6): raise ValueError('unsupported selection level')
    games = {}
    for arm in ('control', 'treatment'):
        games[arm] = qualification.strict_games(root / arm, models[arm], task['level'], selection, heldout_helpers)
    for seed in games['control']:
        left, right = games['control'][seed], games['treatment'][seed]
        if left[2:] != right[2:] or left[0].get('levelPlacement') != right[0].get('levelPlacement'):
            raise ValueError(f'unmatched scene, start or level placement: {seed}')
    return {'status': 'paired_selection_audit_only', 'task': task['name'], 'level': task['level'],
            'seeds': [selection.BASE, selection.BASE + selection.GAMES - 1],
            'control': selection.summary(games['control']), 'treatment': selection.summary(games['treatment']),
            'diagnostics': {arm: metrics.summarize(root / arm, games[arm], task['level'])
                            for arm in ('control', 'treatment')},
            'scope': 'recorded scene/start/placement and score comparison only; camera pitch, wheel mode and invocation require separately verified execution; firstReturnGames is a return-phase proxy, consumption is virtual, and the mobile-loop indicator is diagnostic; no teacher comparison, no winner or held-out qualification; no runtime or actor-input attestation'}


def main():
    if len(sys.argv) != 3: raise SystemExit(__doc__)
    os.environ['PUPPYBOT_PROJECT'] = str(PROJECT)
    with plan_tool.base.acquire_lock(plan_tool.LOCK):
        monitored_receipt.verify()
        plan, task = validate_plan(sys.argv[1], sys.argv[2])
        root = plan_tool.SELECTION_ROOT / task['name']
        result = audit_pair(task, root, {arm: Path(plan['arms'][arm]) for arm in ('control', 'treatment')})
        validate_plan(sys.argv[1], sys.argv[2])
        monitored_receipt.verify()
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    try: main()
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise SystemExit(f'Invalid heading selection: {error}')
