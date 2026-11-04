#!/usr/bin/env python3
"""CPU-only preflight of frozen physical-agent case/environment compatibility.

This compiles a temporary entry point using the archived simulator source and
calls its real catalog, case and environment parsers. It does not initialize
rendering, physics, a GPU, or a policy. It cannot prove collision-free reset,
actual runtime startup or physical behavior.
"""
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
COMPILER=ROOT/'build/flex/control/compiler'


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def validate_archive(pilot):
    pilot=Path(pilot).absolute();receipt=json.loads((pilot/'inputs.json').read_text());files=receipt['files']
    if receipt.get('schema')!='puppybot.sim-visual-stop-pair.v1' or receipt.get('compilerSHA256')!=sha(COMPILER):raise ValueError('pilot or compiler identity differs')
    source=pilot/'inputs/flex-source';library=pilot/'inputs/build/flex/sim/library'
    for folder in (source,library):
        for path in folder.rglob('*'):
            if path.is_file() and '__pycache__' not in path.parts and path.suffix!='.pyc' and files.get(str(path))!=sha(path):
                raise ValueError('archived simulator input changed: '+str(path))
    dependencies=pilot/'inputs/build/flex/sim/dependencies.flex'
    # dependencies.flex is generated deterministically by the pilot builder and
    # contains absolute archived-library paths; compare exact expected bytes.
    expected=f'import "{library / "libs/render.flex"}";\nimport "{library / "libs/physics/physics.flex"}";\n'
    if dependencies.read_text()!=expected:raise ValueError('archived dependency imports changed')
    if files.get(str(source/'sim/cases/catalog.json'))!=sha(source/'sim/cases/catalog.json'):
        raise ValueError('archived catalog changed')
    return source


def build_probe(pilot,directory):
    source=validate_archive(pilot);directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    path=source/'sim/main.flex';text=path.read_text()
    guard='if ps_agent_physical && (!ps_agent_fd || ps_agent_oracle || ps_external || !ps_collect_enabled || ps_seek_enabled || ps_local_requested == 0)'
    if text.count(guard)!=1 or text.count('fn main(argc, argv) {')!=1:raise ValueError('archived physical-agent gate differs')
    text=text.replace('fn main(argc, argv) {','fn pc_preflight_unused_main(argc, argv) {',1)
    def absolute_import(match):
        return f'import "{source / "sim" / match.group(1)}";'
    text=re.sub(r'^import "([^"/]+\.flex)";',absolute_import,text,flags=re.M)
    text+='''\n// CPU-only entry: parses files and checks the archived physical-mode predicate.
fn main(argc,argv) {
    if !pl_init() || argc!=3 { return 2; }
    if !ps_catalog_load() { pl_print(2,"invalid archived catalog\\n"); return 2; }
    let index=ps_case_file(load64(argv+8));
    if index<0 || !ps_case_load(index) { pl_print(2,"invalid case\\n"); return 2; }
    if !ps_collect_enabled || ps_seek_enabled || !ps_discovery_enabled { pl_print(2,"physical-agent controller incompatible\\n"); return 3; }
    if !ps_environment_load(load64(argv+16)) { pl_print(2,"invalid environment\\n"); return 4; }
    pl_print(1,"CPU case and environment parser accepted physical-discovery mode.\\n"); return 0;
}
'''
    probe=directory/'probe.flex';probe.write_text(text);binary=directory/'probe'
    subprocess.run([str(COMPILER),str(probe),'-o',str(binary)],cwd=ROOT,check=True,timeout=60,capture_output=True)
    catalog=directory/'flex/sim/cases/catalog.json';catalog.parent.mkdir(parents=True)
    catalog.write_bytes((source/'sim/cases/catalog.json').read_bytes())
    return binary


def check(probe,case,environment):
    result=subprocess.run([str(Path(probe).absolute()),str(Path(case).absolute()),str(Path(environment).absolute())],
                          cwd=Path(probe).parent,capture_output=True,text=True,timeout=15)
    return {'accepted':result.returncode==0,'returnCode':result.returncode,'stdout':result.stdout.strip(),'stderr':result.stderr.strip()}


if __name__=='__main__':
    import sys
    if len(sys.argv)!=4:raise SystemExit('Usage: physical-case-preflight.py PILOT CASE_JSON ENVIRONMENT_BIN')
    with tempfile.TemporaryDirectory(prefix='puppy-physical-preflight-') as tmp:
        result=check(build_probe(Path(sys.argv[1]),tmp),Path(sys.argv[2]),Path(sys.argv[3]));print(json.dumps(result,sort_keys=True))
        if not result['accepted']:raise SystemExit(1)
