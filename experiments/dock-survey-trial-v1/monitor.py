#!/usr/bin/env python3
"""Reuse the bounded GPU/disk monitor for the survey-recording trial."""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


base = load('survey_search_monitor', ROOT / 'experiments/physical-search-fallback-monitor-v1/monitor.py')
base.__file__ = str(HERE / 'monitor.py')
base.TRIAL = HERE
base.runner = load('survey_trial_runner', HERE / 'run.py')
original_source_pins = base.source_pins


def source_pins():
    result = original_source_pins()
    paths = (ROOT / 'experiments/physical-search-fallback-monitor-v1/monitor.py',
             ROOT / 'experiments/physical-search-fallback-trial-v1/run.py',
             ROOT / 'experiments/physical-search-fallback-trial-v1/audit.py',
             ROOT / 'experiments/physical-dock-confirm-trial-v1/run.py',
             ROOT / 'experiments/physical-dock-confirm-trial-v1/audit.py',
             ROOT / 'experiments/physical-dock-confirm-v1/build.py',
             ROOT / 'experiments/physical-dock-confirm-v1/transform.py',
             ROOT / 'experiments/dock-survey-diagnostic-v1/build.py',
             ROOT / 'experiments/dock-survey-diagnostic-v1/transform.py')
    for path in paths: result[str(path)] = base.runner.sha(path)
    return result


base.source_pins = source_pins
trial_worker = base.trial_worker
monitor_worker = base.monitor_worker
final_worker = base.final_worker
launch = base.launch


if __name__ == '__main__':
    raise SystemExit('Disabled pending independent review and resource scheduling.')
