#!/usr/bin/env python3
"""Run three identically barrier-enabled dock arms under the existing monitor."""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


base = load('clearance_barrier_trial', ROOT / 'experiments/dock-clearance-diagnostic-v1/run.py')
builder = load('barrier_rendered_builder', HERE / 'build.py')
base.HERE = HERE
base.builder = builder
base.base.__file__ = str(HERE / 'run.py')
original_env_for = base.env_for
original_required = base.required


def env_for(root, name):
    env = original_env_for(root, name)
    env['PUPPYBOT_SIM_WORKER_BARRIER'] = '1'
    return env


def required(root, build):
    # The clearance wrapper resolves its transform relative to HERE.
    files = original_required(root, build)
    files = [ROOT / 'experiments/dock-clearance-diagnostic-v1/transform.py'
             if path == HERE / 'transform.py' else path for path in files]
    return files + [Path(__file__), HERE / 'monitor.py', HERE / 'audit.py',
                    ROOT / 'experiments/dock-clearance-diagnostic-v1/run.py',
                    ROOT / 'experiments/dock-clearance-diagnostic-v1/build.py',
                    ROOT / 'experiments/dock-clearance-diagnostic-v1/audit.py']


base.env_for = env_for
base.required = required
base.base.env_for = lambda flag: env_for('/unused', 'baseline')
base.base.required = required
ARMS = base.ARMS
sha = base.sha
hidden = base.hidden
check_build = base.check_build
check_manifest = base.check_manifest
check_invocation = base.check_invocation
launch = base.launch


if __name__ == '__main__': raise SystemExit('Disabled pending independent review and resource scheduling.')
