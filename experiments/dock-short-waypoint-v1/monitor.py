#!/usr/bin/env python3
"""Use the inherited bounded GPU and disk monitor for short waypoints."""
import importlib.util
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


prior=load('waypoint_floor_monitor',ROOT/'experiments/dock-floor-refresh-v1/monitor.py')
base=prior.base;base.__file__=str(HERE/'monitor.py');base.TRIAL=HERE
base.runner=load('waypoint_runner',HERE/'run.py')
old_pins=prior.source_pins


def source_pins():
    result=old_pins()
    for path in (HERE/'run.py',HERE/'audit.py',HERE/'build.py',HERE/'transform.py',
                 ROOT/'experiments/dock-floor-refresh-v1/monitor.py',ROOT/'experiments/dock-floor-refresh-v1/audit.py',
                 ROOT/'experiments/dock-floor-refresh-v1/barrier.py',ROOT/'experiments/dock-floor-refresh-v1/build.py',
                 ROOT/'experiments/dock-floor-refresh-v1/transform.py'):
        result[str(path)]=base.runner.sha(path)
    return result


base.source_pins=source_pins
trial_worker=base.trial_worker;monitor_worker=base.monitor_worker;final_worker=base.final_worker;launch=base.launch


if __name__=='__main__':raise SystemExit('Disabled pending independent review and resource scheduling.')
