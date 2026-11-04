#!/usr/bin/env python3
"""Reuse the existing resource supervisor with this trial in fresh processes."""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


base = load('visual_matched_base_monitor', ROOT / 'experiments/physical-search-fallback-monitor-v1/monitor.py')
base.__file__ = str(HERE / 'monitor.py')
base.TRIAL = HERE
base.runner = load('visual_matched_runner', HERE / 'run.py')
original_source_pins = base.source_pins


def source_pins():
    result = original_source_pins()
    for path in (HERE / 'build.py', ROOT / 'experiments/physical-search-fallback-monitor-v1/monitor.py',
                 ROOT / 'experiments/physical-search-fallback-trial-v1/run.py',
                 ROOT / 'experiments/physical-search-fallback-trial-v1/audit.py',
                 ROOT / 'experiments/visual-search-recovery-v1/transform.py',
                 ROOT / 'experiments/visual-search-recovery-v1/audit.py',
                 ROOT / 'experiments/visual-exact-stall-v1/visual-stall.flex'):
        result[str(path)] = base.runner.sha(path)
    return result


base.source_pins = source_pins
trial_worker = base.trial_worker
monitor_worker = base.monitor_worker
final_worker = base.final_worker
launch = base.launch


if __name__ == '__main__': raise SystemExit('Disabled pending independent review and monitored scheduling.')
