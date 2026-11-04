#!/usr/bin/env python3
"""Offline-only worker for one teacher audit or completed level pool."""
import importlib.util
import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[4]
S = PROJECT / 'datasets/visual-control/chase-v1/levels'
spec = importlib.util.spec_from_file_location('teacher_audit', PROJECT / 'experiments/heading-teacher-audit/audit.py')
audit = importlib.util.module_from_spec(spec); spec.loader.exec_module(audit)
spec = importlib.util.spec_from_file_location('teacher_draft', S / 'heading-teacher-plan-v1.py')
draft = importlib.util.module_from_spec(spec); spec.loader.exec_module(draft)


def main():
    if len(sys.argv) != 2: raise ValueError('expected a fixed task name or pool')
    name = sys.argv[1]; names = [task['name'] for task in draft.plan_tool.selection_design()]
    if name == 'pool':
        reports = {level: json.loads((draft.TEACHER_ROOT / f'evidence-{level}/audit/client.log').read_text())
                   for level in names[1:]}
        result = audit.audit_pool(reports)
    elif name in names:
        models = {arm: draft.plan_tool.PACKAGE / arm for arm in ('control', 'treatment')}
        result = audit.audit_task(name, draft.TEACHER_ROOT / name, draft.plan_tool.SELECTION_ROOT / name, models)
    else: raise ValueError('unknown teacher task')
    print(json.dumps(result, sort_keys=True, allow_nan=False))


if __name__ == '__main__': main()
