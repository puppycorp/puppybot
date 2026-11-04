#!/usr/bin/env python3
"""Build a copied control with mandatory synthetic-reservation scene guard.

Usage: prepare.py NEW_DIRECTORY. No GPU or simulator is started here. This
experimental binary is not the active control and does not enable holdout.
"""
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
ARCHIVE=ROOT/'build/flex/sim/levels-v2/pitch82/physical-handoff-hint-build-v3/inputs/flex-source'
COMPILER=ROOT/'build/flex/control/compiler'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def hashes(root):
    return {str(p.relative_to(root)):sha(p) for p in sorted(root.rglob('*')) if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc'}


def once(text,old,new):
    if text.count(old)!=1:raise ValueError('unexpected source shape')
    return text.replace(old,new,1)


def prepare(output):
    output=Path(output).absolute();output.mkdir(parents=False,exist_ok=False)
    source=output/'flex';original=hashes(ARCHIVE);shutil.copytree(ARCHIVE,source,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    if hashes(source)!=original or hashes(ARCHIVE)!=original:raise ValueError('archived source changed while copying')
    guard=(HERE/'guard.flex').read_bytes();compiler=sha(COMPILER)
    subprocess.run([str(COMPILER),str(source/'control/main.flex'),'-o',str(output/'baseline')],cwd=ROOT,check=True,timeout=120,capture_output=True)
    module=source/'control/holdout-scene-guard.flex'
    if module.exists():raise ValueError('guard module already exists')
    module.write_bytes(guard)
    env=source/'control/environment.flex';text=env.read_text()
    text=once(text,'import "scene.flex";','import "scene.flex";\nimport "holdout-scene-guard.flex";')
    text=once(text,'''    ve_directory=output;vc_mkdir(output);let world=vc_path(output,"scene");vc_mkdir(world);ve_hidden=hidden;
    if scene {vc_copy_file(vc_path(scene,"case.json"),vc_path(world,"case.json"));vc_copy_file(vc_path(scene,"environment.bin"),vc_path(world,"environment.bin"));}
    else {vc_environment(vc_path(world,"environment.bin"),hidden);vc_case(vc_path(world,"case.json"),template,seed,hidden);}
    ve_reference(scene,vc_path(world,"environment.bin"),hidden);''',
'''    let guarded_scene=sg_snapshot(scene);
    ve_directory=output;vc_mkdir(output);let world=vc_path(output,"scene");vc_mkdir(world);ve_hidden=hidden;
    sg_write(world,guarded_scene);
    ve_reference(world,vc_path(world,"environment.bin"),hidden);''')
    env.write_text(text)
    main=source/'control/main.flex';text=main.read_text()
    text=once(text,'    ve_open_buffers();if vw_chase && pl_equal(command,"collect")',
'''    if pl_equal(command,"collect") || pl_equal(command,"run") || pl_equal(command,"correct") {
        sg_init(pl_environment(argc,argv,"PUPPYBOT_RESERVED_MANIFEST"),pl_environment(argc,argv,"PUPPYBOT_RESERVED_MANIFEST_SHA256"));
    }
    ve_open_buffers();if vw_chase && pl_equal(command,"collect")''')
    main.write_text(text);patched=hashes(source)
    allowed={'control/main.flex','control/environment.flex','control/holdout-scene-guard.flex'}
    if set(patched)-set(original)!={'control/holdout-scene-guard.flex'} or any(original[k]!=patched[k] for k in original if k not in allowed):raise ValueError('unexpected source changes')
    subprocess.run([str(COMPILER),str(main),'-o',str(output/'control-guarded')],cwd=ROOT,check=True,timeout=120,capture_output=True)
    if sha(COMPILER)!=compiler or (HERE/'guard.flex').read_bytes()!=guard or hashes(source)!=patched or hashes(ARCHIVE)!=original:raise ValueError('build inputs changed')
    receipt={'schema':'puppybot.isolated-scene-ingestion-guard.v1','sourceArchive':original,'guardedSource':patched,
             'compilerSHA256':compiler,'baselineSHA256':sha(output/'baseline'),'guardedSHA256':sha(output/'control-guarded'),
             'scope':'guarded explicit scene ingestion only; no old binary, existing dataset, semantic similarity or holdout qualification claim'}
    (output/'build.json').write_text(json.dumps(receipt,sort_keys=True,indent=2)+'\n');return receipt


if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit(__doc__)
    report=prepare(sys.argv[1]);print(json.dumps({'status':'isolated_build_only','guardedSHA256':report['guardedSHA256'],'scope':report['scope']}))
