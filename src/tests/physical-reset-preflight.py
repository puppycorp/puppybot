#!/usr/bin/env python3
"""CPU-only archived simulator parser and pre-render physics reset check.

Builds a temporary shim from the frozen simulator source, loads a case,
environment and pinned robot asset, then calls the same pre-render ps_reset
and its spawn collision query. It does not create a graphics device, start a
policy, call ps_case_start, or establish rendered/real-hardware behavior.
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('case_preflight',ROOT/'flex/tests/physical-case-preflight.py')
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)


def build_probe(pilot,directory):
    pilot=Path(pilot).absolute();directory=Path(directory)
    receipt=json.loads((pilot/'inputs.json').read_text());asset=Path(receipt['paths']['asset'])
    if not asset.is_absolute() or receipt['files'].get(str(asset))!=base.sha(asset):raise ValueError('pilot robot asset changed')
    base.build_probe(pilot,directory)
    source=directory/'probe.flex';text=source.read_text().replace('if !pl_init() || argc!=3 { return 2; }','if !pl_init() || argc!=4 { return 2; }')
    anchor='    pl_print(1,"CPU case and environment parser accepted physical-discovery mode.\\n"); return 0;'
    if text.count(anchor)!=1:raise ValueError('unexpected parser probe shape')
    code='''    if !ps_model_load(load64(argv+24)) { pl_print(2,"invalid robot asset\\n"); return 5; }
    ps_robot=alloc(8192);ps_system=alloc(2048);ps_config=alloc(448);ps_app=alloc(2048);ps_bus=alloc(16384);ps_plant=alloc(2048);
    ps_trace=alloc(69632);ps_json=alloc(16384);ps_builder=alloc(32);pb_config_default(ps_config);pb_vset(ps_config+40,2,5);
    ps_local_requested=2;ps_agent_fd=3;ps_agent_physical=1;ps_camera_pitch=82;
    if !ps_reset() { pl_print(2,"CPU simulator reset failed\\n"); return 6; }
    pl_print(1,"CPU pre-render simulator reset accepted.\\n");return 0;'''
    source.write_text(text.replace(anchor,code));binary=directory/'reset-probe'
    subprocess.run([str(base.COMPILER),str(source),'-o',str(binary)],cwd=ROOT,check=True,timeout=60,capture_output=True)
    if receipt['files'][str(asset)]!=base.sha(asset):raise ValueError('robot asset changed during build')
    return binary,asset


def check(probe,asset,case,environment):
    result=subprocess.run([str(Path(probe).absolute()),str(Path(case).absolute()),str(Path(environment).absolute()),str(Path(asset).absolute())],
                          cwd=Path(probe).parent,capture_output=True,text=True,timeout=20)
    return {'accepted':result.returncode==0,'returnCode':result.returncode,'stdout':result.stdout.strip(),'stderr':result.stderr.strip()}


if __name__=='__main__':
    import tempfile
    if len(sys.argv)!=4:raise SystemExit('Usage: physical-reset-preflight.py PILOT CASE_JSON ENVIRONMENT_BIN')
    with tempfile.TemporaryDirectory(prefix='puppy-reset-preflight-') as tmp:
        binary,asset=build_probe(Path(sys.argv[1]),Path(tmp));result=check(binary,asset,sys.argv[2],sys.argv[3]);print(json.dumps(result,sort_keys=True))
        if not result['accepted']:raise SystemExit(1)
