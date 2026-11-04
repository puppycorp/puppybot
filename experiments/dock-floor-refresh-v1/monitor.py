#!/usr/bin/env python3
"""Reuse guarded GPU and disk monitoring for dock-floor recovery."""
import importlib.util
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


prior = load('floor_retry_barrier_monitor', ROOT / 'experiments/dock-barrier-rendered-v1/monitor.py')
base = prior.base
base.__file__ = str(HERE / 'monitor.py')
base.TRIAL = HERE
base.runner = load('floor_retry_runner', HERE / 'run.py')
old_pins = prior.source_pins


def source_pins():
    result = old_pins()
    for path in (HERE / 'run.py', HERE / 'audit.py', HERE / 'barrier.py', HERE / 'build.py',
                 HERE / 'transform.py', ROOT / 'experiments/observed-footprint-matched-v1/build.py',
                 ROOT / 'experiments/observed-footprint-matched-v1/audit.py',
                 ROOT / 'experiments/dock-barrier-rendered-v1/run.py',
                 ROOT / 'experiments/dock-barrier-rendered-v1/audit.py',
                 ROOT / 'experiments/dock-barrier-rendered-v1/build.py',
                 ROOT / 'experiments/dock-barrier-rendered-v1/monitor.py',
                 ROOT / 'experiments/dock-barrier-postrun-v1/audit.py'):
        result[str(path)] = base.runner.sha(path)
    return result


base.source_pins = source_pins
trial_worker = base.trial_worker
monitor_worker = base.monitor_worker
final_worker = base.final_worker
launch = base.launch


if __name__ == '__main__':
    raise SystemExit('Disabled pending independent review and resource scheduling.')
