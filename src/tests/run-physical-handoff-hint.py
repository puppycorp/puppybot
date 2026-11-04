#!/usr/bin/env python3
"""Stage a bounded three-arm physical-simulation handoff-hint comparison.

`--check` is CPU-only. GPU execution is hard-disabled pending review. Planned
arms: original, candidate disabled, candidate enabled; same client, model,
visible selection case and 29,980 collector-tick cap. Three 300-second
watchdogs give a 15-minute arm ceiling plus setup and auditing. This tests a
heuristic collector with zero-action handoff expected, not learned navigation.
"""
import fcntl
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/'build/flex/sim/levels-v2/pitch82'
BUILD=BASE/'physical-handoff-hint-build-v3'
REFERENCE=BASE/'physical-hybrid-visible-trial'
LOCK=BASE/'.l4-matched.lock'


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result


prepare=load('hint_build',ROOT/'flex/tests/prepare-physical-handoff-hint.py')
hidden=load('hidden',ROOT/'flex/tests/run-physical-hidden-trial.py')
sha=prepare.rescan.sha


def check():
    report=json.loads((BUILD/'build.json').read_text());prepare.verify(BUILD,report)
    reference=json.loads((REFERENCE/'run/inputs.json').read_text())
    expected={'caseSHA256':REFERENCE/'case.json','environmentSHA256':hidden.ENVIRONMENT,
              'weightsSHA256':hidden.MODEL/'weights.bin','policySHA256':hidden.MODEL/'policy',
              'receiptSHA256':hidden.MODEL/'receipt.json','robotAssetSHA256':hidden.ASSET}
    for key,path in expected.items():
        if reference.get(key)!=sha(path):raise ValueError('visible selection input changed: '+key)
    hidden.rescan.verify_model(hidden.MODEL)
    if not os.access(BUILD/'inputs/client',os.X_OK) or not os.access(BUILD/'inputs/simulator',os.X_OK) or not os.access(BUILD/'simulator-hint',os.X_OK):raise ValueError('isolated executable missing')
    return report,reference


def pins(output):
    paths=[BUILD/'build.json',BUILD/'inputs/simulator',BUILD/'simulator-hint',BUILD/'inputs/client',BUILD/'inputs/build/flex/sim/dependencies.flex',
           prepare.rescan.COMPILER,REFERENCE/'run/inputs.json',REFERENCE/'case.json',hidden.ENVIRONMENT,
           output/'inputs/case.json',output/'inputs/environment.bin',output/'worker-inputs.json',
           ROOT/'puppybot.json',hidden.ASSET,ROOT/'build/flex/rocm-runtime/libamdhip64.so',
           Path(__file__),ROOT/'flex/tests/prepare-physical-handoff-hint.py',ROOT/'flex/tests/audit-physical-handoff-hint.py',
           ROOT/'flex/tests/run-physical-hidden-trial.py',ROOT/'flex/tests/run-physical-rescan-trial.py',ROOT/'flex/tests/run-physical-hybrid-trial.py']
    model=output/'inputs/model';paths += [model/'policy',model/'weights.bin',model/'receipt.json',*sorted((model/'kernels').iterdir())]
    for folder in (BUILD/'inputs/flex-source',BUILD/'inputs/build/flex/sim/library',BUILD/'original-source'):
        paths += [p for p in sorted(folder.rglob('*')) if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc']
    return {str(path):sha(path) for path in paths}


def partial_audit(output):
    auditor=ROOT/'flex/tests/audit-physical-handoff-hint.py'
    try:
        result=subprocess.run([sys.executable,'-I',str(auditor),str(output)],cwd=ROOT,capture_output=True,text=True,timeout=300)
        (output/'audit.partial.log').write_text(result.stderr)
        if result.returncode==0:(output/'audit.partial.json').write_text(result.stdout)
    except (OSError,subprocess.SubprocessError) as error:
        (output/'audit.partial.log').write_text(str(error)+'\n')


def run(output):
    output=Path(output).absolute()
    with LOCK.open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if output.exists() or output.is_symlink():raise ValueError('output exists; retain it')
        if shutil.disk_usage(output.parent).free<12*1024**3:raise ValueError('insufficient free space before trial')
        build,reference=check();output.mkdir(parents=False,exist_ok=False);inputs=output/'inputs';inputs.mkdir()
        for src,name in ((REFERENCE/'case.json','case.json'),(hidden.ENVIRONMENT,'environment.bin')):
            shutil.copyfile(src,inputs/name)
            if sha(src)!=sha(inputs/name):raise ValueError('scene changed while snapshotting')
        shutil.copytree(hidden.MODEL,inputs/'model');hidden.rescan.verify_model(inputs/'model')
        if any(sha(inputs/'model'/name)!=sha(hidden.MODEL/name) for name in ('policy','weights.bin','receipt.json')):raise ValueError('model snapshot differs')
        env={'PATH':'/usr/bin:/bin','HOME':str(Path.home()),'SDL_VIDEODRIVER':'offscreen',
             'LD_LIBRARY_PATH':str(ROOT/'build/flex/rocm-runtime'),'PUPPYBOT_PHYSICAL_NAV_LIMIT':'30','PUPPYBOT_PHYSICAL_POLL_LIMIT':'1499'}
        worker=hidden.supervisor.worker_snapshot(env);(output/'worker-inputs.json').write_text(json.dumps(worker,sort_keys=True,indent=2)+'\n')
        pinned=pins(output)
        manifest={'schema':'puppybot.physical-handoff-hint-trial.v1','build':str(BUILD),'case':str(inputs/'case.json'),
                  'environment':str(inputs/'environment.bin'),'model':str(inputs/'model'),'asset':str(hidden.ASSET),
                  'original':str(BUILD/'inputs/simulator'),'candidate':str(BUILD/'simulator-hint'),'client':str(BUILD/'inputs/client'),
                  'files':pinned,'home':env['HOME'],'navigationLimit':30,'collectorPollLimit':1499,'wallSecondsPerArm':300,
                  'scope':'single visible-brick physical simulation selection case; no learned-navigation, hardware or held-out claim'}
        (output/'inputs.json').write_text(json.dumps(manifest,sort_keys=True,indent=2)+'\n')
        arms=(('original',manifest['original'],'0'),('candidate-disabled',manifest['candidate'],'0'),('candidate-enabled',manifest['candidate'],'1'))
        for name,sim,flag in arms:
            if shutil.disk_usage(output).free<8*1024**3:raise ValueError('insufficient space during trial')
            prepare.verify(BUILD,build)
            if pins(output)!=pinned:raise ValueError('trial inputs changed')
            parent=output/name;parent.mkdir();monitor=parent/'monitor';monitor.mkdir()
            command=[manifest['client'],sim,manifest['model'],manifest['case'],manifest['environment'],str(parent/'run'),'--allow-zero-contact']
            (parent/'command.json').write_text(json.dumps(command,indent=2)+'\n')
            arm_env=dict(env,PUPPYBOT_PHYSICAL_HANDOFF_HINT=flag)
            (parent/'environment.json').write_text(json.dumps(arm_env,sort_keys=True,indent=2)+'\n')
            try:status=hidden.supervise(command,monitor,arm_env,300)
            except Exception:
                partial_audit(output);raise
            if status['signal'] is not None or status['timedOut'] or status['clientExit']!=0 or status['remainingWorkersTerminated']:
                partial_audit(output)
                raise RuntimeError('trial arm failed or required cleanup; partial evidence retained')
            if pins(output)!=pinned:raise ValueError('trial inputs changed')
            launch=shutil.which('python3',path=env['PATH'])
            if not launch or Path(launch).absolute()!=Path(worker['launchPath']) or Path(launch).resolve()!=Path(worker['executable']):raise ValueError('worker interpreter path changed')
            hidden.supervisor.verify_worker(worker);hidden.rescan.verify_model(inputs/'model')
        auditor=ROOT/'flex/tests/audit-physical-handoff-hint.py'
        result=subprocess.run([sys.executable,'-I',str(auditor),str(output)],cwd=ROOT,capture_output=True,text=True,timeout=300)
        (output/'audit.log').write_text(result.stderr)
        if result.returncode:raise RuntimeError('trial audit failed; evidence retained')
        (output/'audit.json').write_text(result.stdout);print(result.stdout,end='')


if __name__=='__main__':
    if len(sys.argv)==2 and sys.argv[1]=='--check':
        build,reference=check();print(json.dumps({'status':'cpu_preflight_only','candidateSHA256':build['candidateSimulatorSHA256'],'scope':'no GPU or simulator run'}))
    else:raise SystemExit('GPU execution disabled pending independent review and a scheduling decision.')
