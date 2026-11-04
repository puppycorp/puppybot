#!/usr/bin/env python3
"""Reuse the established guarded GPU/disk monitor for the barrier diagnostic."""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


clearance = load('clearance_barrier_monitor', ROOT / 'experiments/dock-clearance-diagnostic-v1/monitor.py')
base = clearance.base.base
base.__file__ = str(HERE / 'monitor.py')
base.TRIAL = HERE
base.runner = load('barrier_rendered_runner', HERE / 'run.py')
original_source_pins = base.source_pins


def source_pins():
    result = original_source_pins()
    for path in (HERE / 'run.py', HERE / 'audit.py', HERE / 'build.py',
                 ROOT / 'experiments/discovery-worker-barrier-v1/transform.py',
                 ROOT / 'experiments/dock-clearance-diagnostic-v1/run.py',
                 ROOT / 'experiments/dock-clearance-diagnostic-v1/audit.py',
                 ROOT / 'experiments/dock-clearance-diagnostic-v1/build.py',
                 ROOT / 'experiments/dock-clearance-diagnostic-v1/monitor.py'):
        result[str(path)] = base.runner.sha(path)
    return result


base.source_pins = source_pins
trial_worker = base.trial_worker
monitor_worker = base.monitor_worker
final_worker = base.final_worker
launch = base.launch


if __name__ == '__main__': raise SystemExit('Disabled pending independent review and scheduling.')
