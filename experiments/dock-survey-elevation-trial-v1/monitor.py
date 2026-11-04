#!/usr/bin/env python3
"""Use the established GPU/disk monitor for the elevated survey diagnostic."""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


base = load('elevation_survey_monitor', ROOT / 'experiments/dock-survey-trial-v1/monitor.py')
base.base.__file__ = str(HERE / 'monitor.py')
base.base.TRIAL = HERE
base.base.runner = load('elevation_trial_runner', HERE / 'run.py')
original_source_pins = base.base.source_pins


def source_pins():
    result = original_source_pins()
    for path in (HERE / 'build.py', ROOT / 'experiments/dock-survey-trial-v1/monitor.py',
                 ROOT / 'experiments/dock-survey-trial-v1/run.py',
                 ROOT / 'experiments/dock-survey-trial-v1/audit.py',
                 ROOT / 'experiments/dock-survey-elevation-v1/transform.py'):
        result[str(path)] = base.base.runner.sha(path)
    return result


base.base.source_pins = source_pins
trial_worker = base.base.trial_worker
monitor_worker = base.base.monitor_worker
final_worker = base.base.final_worker
launch = base.base.launch


if __name__ == '__main__': raise SystemExit('Disabled pending independent review and scheduling.')
