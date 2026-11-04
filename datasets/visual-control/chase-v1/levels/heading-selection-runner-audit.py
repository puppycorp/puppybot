#!/usr/bin/env python3
"""Bounded worker for saved heading-selection arm and pair audits only."""
import importlib.util
import json
import os
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[4]
S = PROJECT / 'datasets/visual-control/chase-v1/levels'
spec = importlib.util.spec_from_file_location('heading_audit', S / 'heading-selection-audit.py')
audit = importlib.util.module_from_spec(spec); spec.loader.exec_module(audit)


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in ('control', 'treatment', 'pair'):
        raise ValueError('expected arm or pair and fixed task name')
    arm, name = sys.argv[1:]
    tasks = [item for item in audit.plan_tool.selection_design() if item['name'] == name]
    if len(tasks) != 1: raise ValueError('unknown task')
    task = tasks[0]; root = audit.plan_tool.SELECTION_ROOT / name
    models = {a: audit.plan_tool.PACKAGE / a for a in ('control', 'treatment')}
    os.environ['PUPPYBOT_PROJECT'] = str(PROJECT)
    if arm == 'pair':
        result = audit.audit_pair(task, root, models)
    else:
        games = audit.qualification.strict_games(root / arm, models[arm], task['level'], audit.selection, audit.heldout_helpers)
        result = {'status': 'saved_arm_audit_only', 'task': name, 'arm': arm,
                  'summary': audit.selection.summary(games)}
    print(json.dumps(result, sort_keys=True, allow_nan=False))


if __name__ == '__main__':
    try: main()
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise SystemExit(f'Invalid saved selection: {error}')
