#!/usr/bin/env python3
"""Build the selectable footprint simulator under the bounded CPU supervisor."""
import importlib.util
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
P = ROOT / 'build/flex/sim/levels-v2/pitch82'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


old = load('footprint_barrier_build_supervisor', ROOT / 'experiments/dock-barrier-rendered-v1/build-supervisor.py')
base = old.base
base.__file__ = str(HERE / 'build-supervisor.py')
base.HERE = HERE
base.BUILD = P / 'observed-footprint-matched-build-v2'
base.MONITOR = P / 'observed-footprint-matched-build-cpu-monitor-v2'
base.runner = load('footprint_matched_build_runner', HERE / 'run.py')
old_sources = old.sources


def sources():
    result = old_sources()
    for path in (HERE / 'build.py', HERE / 'run.py', ROOT / 'flex/sim/navigation.flex',
                 ROOT / 'experiments/dock-barrier-rendered-v1/build.py'):
        result[str(path)] = base.base.sha(path)
    return result


base.sources = sources
worker = base.worker
launch = base.launch


if __name__ == '__main__':
    raise SystemExit('Disabled pending independent review and resource scheduling.')
