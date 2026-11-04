#!/usr/bin/env python3
"""Stage same-binary short-waypoint comparison under external monitoring."""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load(name, path):
    spec=importlib.util.spec_from_file_location(name,path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result


prior=load('waypoint_barrier_runner',ROOT/'experiments/dock-barrier-rendered-v1/run.py')
builder=load('waypoint_builder',HERE/'build.py')
prior.HERE=HERE;prior.base.HERE=HERE;prior.base.builder=builder;prior.base.base.__file__=str(HERE/'run.py')
base_required=prior.required


def env_for(root,name):
    if name not in prior.ARMS: raise ValueError('unknown arm')
    env=prior.original_env_for(root,name)
    env['PUPPYBOT_DOCK_HIGH_SURVEY']='1'
    env['PUPPYBOT_SIM_WORKER_BARRIER']='1'
    env['PUPPYBOT_SIM_OBSERVED_FOOTPRINT_V2']='1'
    env['PUPPYBOT_SIM_DOCK_FLOOR_RETRY']='1'
    env[builder.FLAG]='1' if name=='candidate-search' else '0'
    return env


def required(root,build):
    return base_required(root,build)+[Path(__file__),HERE/'audit.py',HERE/'monitor.py',HERE/'build.py',HERE/'transform.py',
        ROOT/'experiments/dock-floor-refresh-v1/audit.py',ROOT/'experiments/dock-floor-refresh-v1/barrier.py',
        ROOT/'experiments/dock-floor-refresh-v1/build.py',ROOT/'experiments/dock-floor-refresh-v1/transform.py',
        ROOT/'experiments/observed-footprint-matched-v1/build.py',ROOT/'experiments/observed-footprint-matched-v1/audit.py',
        ROOT/'experiments/dock-barrier-rendered-v1/build.py',ROOT/'experiments/dock-barrier-rendered-v1/monitor.py',
        ROOT/'experiments/dock-barrier-postrun-v1/audit.py']


def check_build(path):return builder.verify(path)


prior.base.check_build=check_build;prior.base.env_for=env_for;prior.base.required=required
prior.base.base.check_build=check_build;prior.base.base.env_for=lambda flag:env_for('/unused','baseline');prior.base.base.required=required
ARMS=prior.ARMS;sha=prior.sha;hidden=prior.hidden;check_manifest=prior.base.check_manifest
check_invocation=prior.base.check_invocation;launch=prior.base.launch


if __name__=='__main__':raise SystemExit('Disabled pending independent review and resource scheduling.')
