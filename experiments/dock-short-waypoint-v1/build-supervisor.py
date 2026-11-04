#!/usr/bin/env python3
"""Build the copied waypoint simulator under the bounded CPU supervisor."""
import importlib.util
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
P=ROOT/'build/flex/sim/levels-v2/pitch82'


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


prior=load('waypoint_floor_build_supervisor',ROOT/'experiments/dock-floor-refresh-v1/build-supervisor.py')
base=prior.base;base.__file__=str(HERE/'build-supervisor.py');base.HERE=HERE
base.BUILD=P/'dock-short-waypoint-build-v1';base.MONITOR=P/'dock-short-waypoint-build-cpu-monitor-v1'
base.runner=load('waypoint_build_runner',HERE/'run.py');old_sources=prior.sources


def sources():
    result=old_sources()
    for path in (HERE/'build.py',HERE/'run.py',HERE/'transform.py',ROOT/'experiments/dock-floor-refresh-v1/build.py',
                 ROOT/'experiments/dock-floor-refresh-v1/transform.py'):
        result[str(path)]=base.base.sha(path)
    return result


base.sources=sources;worker=base.worker;launch=base.launch


if __name__=='__main__':raise SystemExit('Disabled pending independent review and resource scheduling.')
