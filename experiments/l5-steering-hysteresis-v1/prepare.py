#!/usr/bin/env python3
"""Disabled isolated CPU builder for the simulator-only intervention."""
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
P=ROOT/'build/flex/sim/levels-v2/pitch82'
BUILD=P/'l5-steering-hysteresis-build-v1'
COMPILER=ROOT/'build/flex/control/compiler'


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


transform=load('hys_build_transform',HERE/'transform.py')
base=load('hys_build_base',ROOT/'datasets/visual-control/chase-v1/levels/run-route-factorial.py')


def input_paths():return (COMPILER,HERE/'transform.py',HERE/'native-test-probe.flex',ROOT/'experiments/l5-steering-kick-v1/transform.py',Path(__file__))


def verify(output=BUILD):
    output=Path(output)
    if output!=BUILD or output.is_symlink():raise ValueError('unexpected build path')
    receipt=json.loads((output/'build.json').read_text())
    if receipt.get('schema')!='puppybot.l5-steering-hysteresis-build.v1' or receipt.get('status')!='diagnostic_build_only':raise ValueError('invalid build receipt')
    pins=receipt['inputs'];paths=input_paths()
    if set(pins)!={str(p) for p in paths} or any(base.sha(p)!=pins[str(p)] for p in paths):raise ValueError('build input changed')
    source=output/'flex-source'
    original=receipt['originalSources'];patched=receipt['patchedSources'];probe='control/hysteresis-test-probe.flex'
    if not isinstance(original,dict) or not isinstance(patched,dict) or probe in original or set(patched)!=set(original)|{probe} or any(patched[name]!=digest for name,digest in original.items() if name not in ('control/chase.flex','control/main.flex')):raise ValueError('unrelated candidate source changed')
    if base.hidden.supervisor.source_hashes(source)!=patched or base.hidden.supervisor.source_hashes(ROOT/'flex')!=original:raise ValueError('build source changed')
    orig_chase=(output/'original-chase.flex').read_text();orig_main=(output/'original-main.flex').read_text();chase,main=transform.transform(orig_chase,orig_main)
    if ((ROOT/'flex/control/chase.flex').read_text()!=orig_chase or (ROOT/'flex/control/main.flex').read_text()!=orig_main or
            (source/'control/chase.flex').read_text()!=chase or (source/'control/main.flex').read_text()!=main or
            (source/'control/hysteresis-test-probe.flex').read_bytes()!=(HERE/'native-test-probe.flex').read_bytes() or
            base.sha(output/'control')!=receipt['controlSHA256'] or base.sha(output/'probe')!=receipt['probeSHA256']):raise ValueError('source transform or binary differs')
    return receipt


def prepare(output=BUILD):
    """Require separate reviewed bounded CPU supervision before calling."""
    with base.acquire_lock(P/'.l4-matched.lock'):
        output=Path(output)
        if output!=BUILD:raise ValueError('build path is fixed')
        base.require_new_output(output);base.require_capacity(P,36*1024**3)
        original=base.hidden.supervisor.source_hashes(ROOT/'flex')
        if 'control/hysteresis-test-probe.flex' in original:raise ValueError('probe already exists in original source')
        pins={str(p):base.sha(p) for p in input_paths()}
        output.mkdir();source=output/'flex-source';shutil.copytree(ROOT/'flex',source,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        if base.hidden.supervisor.source_hashes(source)!=original or base.hidden.supervisor.source_hashes(ROOT/'flex')!=original:raise ValueError('source changed while copying')
        chase=source/'control/chase.flex';main=source/'control/main.flex';raw_chase=chase.read_text();raw_main=main.read_text()
        (output/'original-chase.flex').write_text(raw_chase);(output/'original-main.flex').write_text(raw_main)
        new_chase,new_main=transform.transform(raw_chase,raw_main);chase.write_text(new_chase);main.write_text(new_main)
        shutil.copyfile(HERE/'native-test-probe.flex',source/'control/hysteresis-test-probe.flex');patched=base.hidden.supervisor.source_hashes(source)
        for file,name in (('main.flex','control'),('hysteresis-test-probe.flex','probe')):
            subprocess.run([str(COMPILER),str(source/'control'/file),'-o',str(output/name)],cwd=ROOT,check=True,timeout=120,capture_output=True)
        fixture=output/'probe-output';fixture.mkdir();subprocess.run([str(output/'probe'),'normal',str(fixture)],cwd=ROOT,check=True,timeout=10,capture_output=True)
        if any(base.sha(p)!=pins[str(p)] for p in input_paths()) or base.hidden.supervisor.source_hashes(ROOT/'flex')!=original or base.hidden.supervisor.source_hashes(source)!=patched:raise ValueError('build inputs changed')
        base.require_capacity(P,32*1024**3)
        report={'schema':'puppybot.l5-steering-hysteresis-build.v1','status':'diagnostic_build_only','inputs':pins,'originalSources':original,'patchedSources':patched,
                'controlSHA256':base.sha(output/'control'),'probeSHA256':base.sha(output/'probe'),'scope':'isolated simulator source build; no GPU, actor execution, hardware safety or delivery claim'}
        with (output/'build.json').open('x') as stream:json.dump(report,stream,sort_keys=True,indent=2);stream.write('\n')
        if verify(output)!=report:raise ValueError('published build receipt differs')
        return report


if __name__=='__main__':raise SystemExit('Disabled pending independent review and scheduling; no build authorized.')
