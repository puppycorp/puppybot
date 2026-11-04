#!/usr/bin/env python3
"""Disabled fixed-plan registration; no GPU or held-out evaluation."""
import importlib.util
import json
import os
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


plan=load('hys_register_plan',HERE/'plan.py')
prepare=load('hys_register_prepare',HERE/'prepare.py')
old=load('hys_old_scene_validation',ROOT/'experiments/l5-steering-kick-v1/register.py')
old.plan=plan
base=prepare.base
MANIFEST=plan.MANIFEST
HISTORY=old.HISTORY+(plan.P/'l5-steering-kick-diagnostic-v1',)


def source_paths():
    # The old helper binds all of its own audit dependencies; its plan global
    # is this separately named draft, so its build paths point to this build.
    paths=old.source_paths()+[HERE/name for name in ('plan.py','transform.py','native-test-probe.flex','prepare.py','build-supervisor.py','register.py','register-supervisor.py','runner.py','audit.py','monitor.py')]
    if len({str(path) for path in paths})!=len(paths):raise ValueError('duplicate registered source path')
    return sorted(paths)


def current(include_history=True):
    build=prepare.verify();models=plan.MODEL.parent.parent;base.package.verify(models/'control-s0',models/'treatment-s0',plan.MODEL.parent)
    paths=source_paths()
    if len({str(x) for x in paths})!=len(paths) or any(not x.is_file() or x.is_symlink() for x in paths):raise ValueError('missing or symlinked input')
    identities={str(p):base.sha(p) for p in paths}
    history=old.historical_inventory(roots=HISTORY,excluded=(plan.OUTPUT,plan.BUILD),require_known=True) if include_history else None
    return {'schema':'puppybot.l5-steering-hysteresis-plan.v1','status':'frozen_before_play','design':plan.design(),'build':build,
            'files':identities,'runtime':old.runtime_chain(),'scenes':old.scene_rows(),'history':history,
            'scope':'named historical metadata only; post-hoc simulator intervention in new training-family cases; local pins do not prove runtime execution or hardware safety'}


def verify():
    saved=json.loads(plan.MANIFEST.read_text())
    if saved!=current():raise ValueError('registered inputs changed')
    return saved


def freeze():
    with base.acquire_lock(plan.P/'.l4-matched.lock'):
        for path in (plan.MANIFEST,plan.OUTPUT):base.require_new_output(path)
        base.require_capacity(plan.P,36*1024**3);frozen=current()
        if current()!=frozen:raise ValueError('registration inputs changed')
        base.require_capacity(plan.P,36*1024**3)
        for path in (plan.MANIFEST,plan.OUTPUT):base.require_new_output(path)
        with plan.MANIFEST.open('x') as stream:json.dump(frozen,stream,sort_keys=True,indent=2,allow_nan=False);stream.write('\n');stream.flush();os.fsync(stream.fileno())
        fd=os.open(plan.MANIFEST.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)
        return frozen


if __name__=='__main__':raise SystemExit('Disabled pending independent review and monitored registration.')
