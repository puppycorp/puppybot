#!/usr/bin/env python3
"""Build the isolated retry simulator with low-priority bounded supervision."""
import importlib.util
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
P = ROOT / 'build/flex/sim/levels-v2/pitch82'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


old = load('floor_retry_barrier_build_supervisor', ROOT / 'experiments/dock-barrier-rendered-v1/build-supervisor.py')
base = old.base
base.__file__ = str(HERE / 'build-supervisor.py')
base.HERE = HERE
base.BUILD = P / 'dock-floor-refresh-build-v1'
base.MONITOR = P / 'dock-floor-refresh-build-cpu-monitor-v1'
base.runner = load('floor_retry_build_runner', HERE / 'run.py')
old_sources = old.sources


def sources():
    result = old_sources()
    for path in (HERE / 'build.py', HERE / 'run.py', HERE / 'transform.py',
                 ROOT / 'experiments/observed-footprint-matched-v1/build.py',
                 ROOT / 'flex/sim/navigation.flex',
                 ROOT / 'experiments/dock-barrier-rendered-v1/build.py'):
        result[str(path)] = base.base.sha(path)
    return result


base.sources = sources
worker = base.worker
launch = base.launch


if __name__ == '__main__':
    raise SystemExit('Disabled pending independent review and resource scheduling.')
