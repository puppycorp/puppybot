#!/usr/bin/env python3
"""Build a copied diagnostic client accepting a supervisor-owned socket."""
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('failure_build',ROOT/'experiments/physical-failure-report/prepare.py')
failure=importlib.util.module_from_spec(spec);spec.loader.exec_module(failure)


def patched_text(original):
    text=failure.transform(original)
    text=failure.once(text,'pc_process = vc_spawn(args, vc_path(pc_output, "native.log"), 0, 1);',
'''let proxy=pl_environment(argc,argv,"PUPPYBOT_SIM_SUPERVISOR_FD");pc_require(proxy,"missing simulated supervisor channel");
    let proxy_fd=pl_integer(proxy,pl_size(proxy));pc_require(!pl_bad_number && proxy_fd>=3 && proxy_fd<1048576,"invalid simulated supervisor channel");
    pc_process=alloc(16);store64(pc_process,0);store64(pc_process+8,proxy_fd);''')
    text=failure.once(text,'    vc_finish(pc_process, 10000); vc_finish(ve_policy, 10000); return 0;',
                      '    syscall(3,load64(pc_process+8),0,0,0,0,0);store64(pc_process+8,-1); vc_finish(ve_policy, 10000); return 0;')
    return text


def prepare(output):
    output=Path(output).absolute();output.mkdir(parents=False,exist_ok=False)
    source=output/'flex';before=failure.hashes(failure.ARCHIVE)
    shutil.copytree(failure.ARCHIVE,source,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    if failure.hashes(source)!=before or failure.hashes(failure.ARCHIVE)!=before:raise ValueError('archive changed while copying')
    compiler=failure.digest(failure.COMPILER);client=source/'control/physical-client.flex';text=patched_text(client.read_text())
    client.write_text(text);patched=failure.hashes(source)
    if any(before[k]!=patched[k] for k in before if k!='control/physical-client.flex'):raise ValueError('unexpected source changes')
    subprocess.run([str(failure.COMPILER),str(client),'-o',str(output/'client')],cwd=ROOT,check=True,timeout=120,capture_output=True)
    if failure.digest(failure.COMPILER)!=compiler or failure.hashes(source)!=patched or failure.hashes(failure.ARCHIVE)!=before:raise ValueError('build inputs changed')
    report={'schema':'puppybot.sim-stop-client-build.v1','compilerSHA256':compiler,'archiveSource':before,'clientSource':patched,
            'clientSHA256':failure.digest(output/'client'),'scope':'isolated simulated socket client; not physical stopping'}
    (output/'build.json').write_text(json.dumps(report,sort_keys=True,indent=2)+'\n');return report


if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit(__doc__)
    report=prepare(sys.argv[1]);print(json.dumps({'status':'isolated_build_only','clientSHA256':report['clientSHA256']}))
