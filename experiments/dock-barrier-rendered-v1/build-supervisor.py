#!/usr/bin/env python3
"""Run the isolated barrier build under the existing bounded CPU supervisor."""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
P = ROOT / 'build/flex/sim/levels-v2/pitch82'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


base = load('barrier_build_supervisor', ROOT / 'experiments/dock-survey-trial-v1/build-supervisor.py')
base.__file__ = str(HERE / 'build-supervisor.py')
base.HERE = HERE
base.BUILD = P / 'dock-barrier-rendered-build-v1'
base.MONITOR = P / 'dock-barrier-rendered-build-cpu-monitor-v1'
base.runner = load('barrier_build_runner', HERE / 'run.py')
original_sources = base.sources


def sources():
    result = original_sources()
    for path in (HERE / 'build.py', HERE / 'run.py',
                 ROOT / 'experiments/discovery-worker-barrier-v1/transform.py',
                 ROOT / 'experiments/dock-clearance-diagnostic-v1/build.py',
                 ROOT / 'experiments/dock-clearance-diagnostic-v1/transform.py',
                 ROOT / 'experiments/dock-clearance-diagnostic-v1/run.py'):
        result[str(path)] = base.base.sha(path)
    return result


base.sources = sources
worker = base.worker
launch = base.launch


if __name__ == '__main__': raise SystemExit('Disabled pending independent review and scheduling.')
