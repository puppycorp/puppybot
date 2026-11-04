#!/usr/bin/env python3
"""Stage a three-arm simulator search experiment; GPU launch is disabled."""
import fcntl
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/'build/flex/sim/levels-v2/pitch82'
REFERENCE=BASE/'physical-hybrid-hidden-v1'
LOCK=BASE/'.l4-matched.lock'
ARMS=('baseline','candidate-disabled','candidate-search')


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


prepare=load('search_build',ROOT/'experiments/physical-search-fallback-v1/prepare.py')
hidden=load('search_hidden_run',ROOT/'flex/tests/run-physical-hidden-trial.py')
sha=prepare.sha


def check_build(build):
    build=Path(build);report=json.loads((build/'build.json').read_text());archive=prepare.ARCHIVE
    original=json.loads((archive/'build.json').read_text())
    if report.get('schema')!='puppybot.physical-search-fallback-build.v1' or report.get('originalSource')!=original['originalSource']:raise ValueError('unexpected build receipt')
    for name,key in (('baseline-client','baselineClientSHA256'),('baseline-simulator','baselineSimulatorSHA256'),('client','clientSHA256'),('simulator','simulatorSHA256')):
        if sha(build/name)!=report[key] or not os.access(build/name,os.X_OK):raise ValueError('build executable changed')
    if sha(build/'baseline-client')!=original['clientSHA256'] or sha(build/'baseline-simulator')!=original['baselineSimulatorSHA256']:raise ValueError('baseline differs from archive')
    source=build/'source';current=prepare.hashes(source)
    if current!=report['patchedSource'] or prepare.hashes(build/'build/flex/sim/library')!=report['library']:raise ValueError('build sources changed')
    source_base=archive/'inputs/flex-source';changes={'sim/physical-agent-gate.flex':prepare.gate,'sim/agent.flex':prepare.agent,'sim/main.flex':prepare.main_sim,'control/physical-sensor-gate.flex':prepare.sensor_gate,'control/physical-client.flex':prepare.client}
    for name,expected in report['originalSource'].items():
        original_path=archive/'original-source'/Path(name).name if name in ('sim/agent.flex','sim/collect.flex','sim/main.flex') else source_base/name
        if sha(original_path)!=expected:raise ValueError('archived original source differs')
        if name in changes:
            if (source/name).read_text()!=changes[name](original_path.read_text()):raise ValueError('candidate source transform differs')
        elif current.get(name)!=expected:raise ValueError('unrelated candidate source changed')
    return report


def env_for(flag):
    return {'PATH':'/usr/bin:/bin','HOME':str(Path.home()),'SDL_VIDEODRIVER':'offscreen','LD_LIBRARY_PATH':str(ROOT/'build/flex/rocm-runtime'),
            'PUPPYBOT_PHYSICAL_NAV_LIMIT':'90','PUPPYBOT_PHYSICAL_POLL_LIMIT':'1499','PUPPYBOT_PHYSICAL_SEARCH_FALLBACK':flag}


def command_for(root,manifest,name):
    build=Path(manifest['build']);client=build/('baseline-client' if name=='baseline' else 'client');sim=build/('baseline-simulator' if name=='baseline' else 'simulator')
    return [str(client),str(sim),manifest['model'],manifest['case'],manifest['environment'],str(root/name/'run'),'--allow-zero-contact']


def required(root,build):
    model=root/'inputs/model'
    paths=[Path(__file__),Path(__file__).with_name('audit.py'),ROOT/'experiments/physical-search-fallback-v1/prepare.py',
           ROOT/'flex/tests/run-physical-hidden-trial.py',ROOT/'flex/tests/run-physical-rescan-trial.py',ROOT/'flex/tests/run-physical-hybrid-trial.py',ROOT/'flex/exploration/manipulation_audit.py',ROOT/'flex/tests/sim-cases.py',ROOT/'flex/tests/sim.py',ROOT/'experiments/sim-stop-supervisor/supervisor.py',
           prepare.ARCHIVE/'build.json',REFERENCE/'run/inputs.json',REFERENCE/'inputs/case.json',REFERENCE/'inputs/environment.bin',REFERENCE/'inputs/model/policy',REFERENCE/'inputs/model/weights.bin',REFERENCE/'inputs/model/receipt.json',
           build/'build.json',build/'baseline-client',build/'baseline-simulator',build/'client',build/'simulator',build/'build/flex/sim/dependencies.flex',
           root/'inputs/case.json',root/'inputs/environment.bin',ROOT/'puppybot.json',hidden.ASSET,ROOT/'build/flex/rocm-runtime/libamdhip64.so',Path(sys.executable),root/'worker-inputs.json',
           model/'policy',model/'weights.bin',model/'receipt.json']
    paths+=sorted(p for p in (model/'kernels').iterdir() if p.is_file())
    for folder in (build/'source',build/'build/flex/sim/library'):
        paths+=sorted(p for p in folder.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc')
    return paths


def pins(root,build):return {str(p):sha(p) for p in required(root,build)}


def check_manifest(root,manifest):
    root=Path(root).absolute();build=Path(manifest['build']);check_build(build)
    if not build.is_absolute() or manifest.get('case')!=str(root/'inputs/case.json') or manifest.get('environment')!=str(root/'inputs/environment.bin') or manifest.get('model')!=str(root/'inputs/model') or manifest.get('wallSecondsPerArm')!=300:raise ValueError('unexpected trial paths or limits')
    if pins(root,build)!=manifest['files']:raise ValueError('trial inputs changed')
    hidden.rescan.verify_model(root/'inputs/model')
    reference=json.loads((REFERENCE/'run/inputs.json').read_text())
    expected={'caseSHA256':REFERENCE/'inputs/case.json','environmentSHA256':REFERENCE/'inputs/environment.bin',
              'policySHA256':REFERENCE/'inputs/model/policy','weightsSHA256':REFERENCE/'inputs/model/weights.bin',
              'receiptSHA256':REFERENCE/'inputs/model/receipt.json','robotAssetSHA256':hidden.ASSET}
    if any(reference.get(k)!=sha(v) for k,v in expected.items()):raise ValueError('recorded reference input changed')
    for source,target in ((REFERENCE/'inputs/case.json',root/'inputs/case.json'),(REFERENCE/'inputs/environment.bin',root/'inputs/environment.bin'),
                          (REFERENCE/'inputs/model/policy',root/'inputs/model/policy'),(REFERENCE/'inputs/model/weights.bin',root/'inputs/model/weights.bin'),(REFERENCE/'inputs/model/receipt.json',root/'inputs/model/receipt.json')):
        if sha(source)!=sha(target):raise ValueError('selection input snapshot differs')
    worker=json.loads((root/'worker-inputs.json').read_text());hidden.supervisor.verify_worker(worker)
    launch=shutil.which('python3',path=env_for('0')['PATH'])
    if not launch or Path(launch).absolute()!=Path(worker['launchPath']) or Path(launch).resolve()!=Path(worker['executable']):raise ValueError('worker launch path changed')


def check_invocation(root,manifest,name):
    parent=root/name
    if json.loads((parent/'command.json').read_text())!=command_for(root,manifest,name) or json.loads((parent/'environment.json').read_text())!=env_for('1' if name=='candidate-search' else '0'):raise ValueError('arm invocation intent differs')


def clean_status(status):
    return ('signal' in status and type(status.get('clientExit')) is int and status['clientExit']==0 and status.get('signal') is None and status.get('timedOut') is False and status.get('remainingWorkersTerminated') is False and type(status.get('processGroup')) is int and status['processGroup']>0)


def partial_audit(output):
    try:
        result=subprocess.run([sys.executable,'-I',str(Path(__file__).with_name('audit.py')),str(output)],cwd=ROOT,capture_output=True,text=True,timeout=300)
        (output/'audit.partial.log').write_text(result.stderr)
        if result.returncode==0:(output/'audit.partial.json').write_text(result.stdout)
    except (OSError,subprocess.SubprocessError) as error:(output/'audit.partial.log').write_text(str(error)+'\n')


def launch(output,build,case,environment,model):
    output,build,case,environment,model=(Path(p).absolute() for p in (output,build,case,environment,model))
    # Direct invocation remains unapproved: a separately reviewed outer GPU,
    # disk and subreaper monitor must own this worker before enabling execution.
    if os.environ.get('PUPPYBOT_SEARCH_TRIAL_REVIEWED_WORKER')!='1':raise RuntimeError('reviewed external monitor required')
    dedicated=load('search_dedicated',ROOT/'experiments/sim-stop-supervisor/supervisor.py');dedicated.require_dedicated_process()
    with LOCK.open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if output.exists() or output.is_symlink():raise ValueError('output exists; preserve it')
        if shutil.disk_usage(output.parent).free<36*1024**3:raise ValueError('insufficient output space')
        check_build(build);hidden.rescan.verify_model(model)
        # Only the previously recorded hidden selection case is allowed.
        for supplied,expected in ((case,REFERENCE/'inputs/case.json'),(environment,REFERENCE/'inputs/environment.bin')):
            if sha(supplied)!=sha(expected):raise ValueError('selection scene differs')
        for name in ('policy','weights.bin','receipt.json'):
            if sha(model/name)!=sha(REFERENCE/'inputs/model'/name):raise ValueError('selection model differs')
        output.mkdir();inputs=output/'inputs';inputs.mkdir()
        try:
            shutil.copyfile(case,inputs/'case.json');shutil.copyfile(environment,inputs/'environment.bin');shutil.copytree(model,inputs/'model')
            if sha(case)!=sha(inputs/'case.json') or sha(environment)!=sha(inputs/'environment.bin'):raise ValueError('scene changed during copy')
            worker=hidden.supervisor.worker_snapshot(env_for('0'));(output/'worker-inputs.json').write_text(json.dumps(worker,sort_keys=True,indent=2)+'\n')
            manifest={'schema':'puppybot.physical-search-fallback-trial.v1','build':str(build),'case':str(inputs/'case.json'),'environment':str(inputs/'environment.bin'),'model':str(inputs/'model'),
                      'navigationLimit':90,'collectorPollLimit':1499,'wallSecondsPerArm':300,'files':pins(output,build),'scope':'simulator selection diagnostic only'}
            (output/'inputs.json').write_text(json.dumps(manifest,sort_keys=True,indent=2)+'\n');check_manifest(output,manifest)
            for name in ARMS:
                if shutil.disk_usage(output).free<34*1024**3:raise ValueError('insufficient space during trial')
                check_manifest(output,manifest);parent=output/name;parent.mkdir();monitor=parent/'monitor';monitor.mkdir();command=command_for(output,manifest,name);env=env_for('1' if name=='candidate-search' else '0')
                (parent/'command.json').write_text(json.dumps(command,indent=2)+'\n');(parent/'environment.json').write_text(json.dumps(env,sort_keys=True,indent=2)+'\n')
                status=hidden.supervise(command,monitor,env,300)
                if not clean_status(status):raise RuntimeError('arm failed; evidence censored')
                check_manifest(output,manifest)
            result=subprocess.run([sys.executable,'-I',str(Path(__file__).with_name('audit.py')),str(output)],cwd=ROOT,capture_output=True,text=True,timeout=300)
            (output/'audit.log').write_text(result.stderr)
            if result.returncode:raise RuntimeError('audit failed')
            check_manifest(output,manifest)
            (output/'audit.json').write_text(result.stdout)
        except Exception:
            partial_audit(output);raise


if __name__=='__main__':raise SystemExit('Simulator launch disabled pending independent review and resource scheduling.')
