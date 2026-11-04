#!/usr/bin/env python3
"""Disabled registration of a teacher-selection plan before any teacher game.

Registration uses the shared pitch82 lock, requires a completed monitored
student selection, and creates the fixed plan exclusively. It never runs a
policy, teacher, simulator, or GPU task.
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


draft = load('teacher_draft', S / 'heading-teacher-plan-v1.py')
selection = draft.runner.audit
base = draft.runner.base
P = draft.plan_tool.P
PLAN = draft.plan_tool.MODELS / 'heading-teacher-plan-v1.json'
OUTPUT = draft.TEACHER_ROOT
MONITORED = P / 'heading-teacher-selection-monitored-v1'
AUDIT = PROJECT / 'experiments/heading-teacher-audit/audit.py'
RUNNER = S / 'run-heading-teacher-v1.py'
WORKER = S / 'heading-teacher-worker-v1.py'
MONITOR = PROJECT / 'flex/tests/monitored-heading-teacher-v1.py'
RECEIPT = S / 'heading-teacher-receipt-v1.py'
GIB = 1024 ** 3


def pins():
    files = (Path(__file__), S / 'heading-teacher-plan-v1.py', AUDIT, RUNNER, WORKER, MONITOR, RECEIPT,
             S / 'audit-selection.py', S / 'qualify-selection.py', S / 'audit-heldout.py', S / 'goal-report.py',
             S / 'heading-selection-receipt.py', S / 'heading-selection-audit.py',
             Path(sys.executable), *(Path('/usr/bin') / name for name in ('bash', 'jq', 'find', 'sort', 'env', 'nice', 'ln', 'mkdir')),
             PROJECT / 'flex/tests/monitored-visual-v4-smoke.py',
             PROJECT / 'flex/tests/run-physical-hidden-trial.py',
             PROJECT / 'flex/tests/run-physical-rescan-trial.py',
             PROJECT / 'flex/tests/run-physical-hybrid-trial.py')
    return {str(path): base.sha(path) for path in files}


def current_plan():
    selection.monitored_receipt.verify()
    student, _ = selection.validate_plan(draft.plan_tool.PLAN, 'standard')
    if student['tasks'] != draft.plan_tool.selection_design(): raise ValueError('student task design differs')
    return {'schema': 'puppybot.heading-teacher-selection-plan.v1', 'status': 'frozen_before_teacher',
            'draft': draft.draft(), 'studentPlanSHA256': base.sha(draft.plan_tool.PLAN),
            'studentCompletionSHA256': base.sha(selection.monitored_receipt.MONITORED / 'completion.json'),
            'sourcePins': pins(), 'storage': {'floorBytes': 32 * GIB, 'launchMinimumBytes': 38 * GIB,
                'runtimeAbortBytes': 34 * GIB, 'datasetBytes': 1221811968,
                'headroomScope': 'remaining launch headroom allows datasets and traces but cannot guarantee protection against unrelated rapid writes'},
            'scope': 'frozen training-layout teacher comparison intent only; no teacher performance or held-out, physical, or execution attestation'}


def verify():
    saved = json.loads(PLAN.read_text())
    if saved != current_plan(): raise ValueError('teacher plan, source or student evidence changed')
    return saved


def freeze():
    with base.acquire_lock(draft.plan_tool.LOCK):
        for path in (PLAN, OUTPUT, MONITORED): base.require_new_output(path)
        base.require_capacity(P, 38 * GIB)
        registration = current_plan()
        for path in (PLAN, OUTPUT, MONITORED): base.require_new_output(path)
        if registration != current_plan(): raise ValueError('teacher inputs changed while registering')
        with PLAN.open('x') as stream:
            json.dump(registration, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
        directory = os.open(PLAN.parent, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(directory)
        finally: os.close(directory)
        return registration


if __name__ == '__main__':
    raise SystemExit('Disabled pending independent review; no teacher plan or GPU run authorized.')
