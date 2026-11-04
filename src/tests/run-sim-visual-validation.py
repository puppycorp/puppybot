#!/usr/bin/env python3
"""Run frozen paired visual-stop selection diagnostics; no hardware claim.

Usage: run-sim-visual-validation.py PILOT INPUT_MATRIX NEW_OUTPUT
Do not run before independent review and an idle-GPU scheduling decision.
Twelve scene conditions, two 90-action arms each, 300 s watchdog per arm;
the worst-case watchdog budget is 120 minutes plus preparation/audit. Failed
or partial results are retained. No thresholds are tuned here.
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
LOCK=ROOT/'build/flex/sim/levels-v2/pitch82/.l4-matched.lock'


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result


hidden=load('hidden',ROOT/'flex/tests/run-physical-hidden-trial.py')
generator=load('generator',ROOT/'flex/tests/prepare-sim-visual-validation.py')
visual=load('visual',ROOT/'flex/tests/audit-sim-visual-stop.py')
sha=visual.sha


def verify_pilot_audit(pilot,oldfiles):
    audit_path=ROOT/'flex/tests/audit-sim-visual-stop-pair.py'
    stop_path=ROOT/'flex/tests/audit-sim-visual-stop.py'
    build_receipt=pilot/'inputs/visual-build/build.json'
    helpers=[ROOT/'flex/tests/run-physical-hidden-trial.py',ROOT/'flex/tests/run-physical-rescan-trial.py',ROOT/'flex/tests/run-physical-hybrid-trial.py']
    for path in (audit_path,stop_path,build_receipt,*helpers):
        if oldfiles.get(str(path))!=sha(path): raise ValueError('pilot auditor or build receipt changed')
    previous=load('previous_pair_audit',audit_path).audit(pilot)
    saved=json.loads((pilot/'audit.json').read_text())
    if previous!=saved or previous.get('status')!='diagnostic_only' or previous.get('commonActorBytesMatch') is not True or previous.get('visualStop',{}).get('reason')!=2:
        raise ValueError('pilot audit missing, changed, or not the validated pair')


def check_matrix(pilot,matrix):
    original=(pilot/'inputs/environment.bin').read_bytes();case=(pilot/'inputs/case.json').read_bytes()
    receipt=json.loads((pilot/'inputs.json').read_text());oldfiles=receipt['files'];paths=receipt['paths']
    if receipt.get('schema')!='puppybot.sim-visual-stop-pair.v1' or oldfiles.get(str(pilot/'inputs/environment.bin'))!=generator.digest(original) or oldfiles.get(str(pilot/'inputs/case.json'))!=generator.digest(case):
        raise ValueError('pilot input snapshot changed')
    verify_pilot_audit(pilot,oldfiles)
    for key in ('client','simulator','case','environment','asset','config','runtime'):
        path=Path(paths[key]);
        if not path.is_absolute() or oldfiles.get(str(path))!=sha(path): raise ValueError('pilot runtime pin changed: '+key)
    model=Path(paths['model']);hidden.rescan.verify_model(model)
    for path in [model/'policy',model/'weights.bin',model/'receipt.json',*sorted((model/'kernels').iterdir())]:
        if oldfiles.get(str(path))!=sha(path): raise ValueError('pilot model input changed')
    data=json.loads((matrix/'conditions.json').read_text())
    if (data.get('schema')!='puppybot.visual-stop-validation-inputs.v1' or data.get('generatorSHA256')!=sha(Path(generator.__file__))
            or data.get('sourceEnvironmentSHA256')!=generator.digest(original) or data.get('sourceCaseSHA256')!=generator.digest(case)):
        raise ValueError('validation generator/source differs from frozen matrix')
    expected={f'{family}-yaw-{heading:+.2f}' for family in generator.FAMILIES for heading in generator.HEADINGS}|{f'room-{n}' for n in generator.ROOM_LAYOUTS}
    conditions=data.get('conditions'); rooms={entry['layout']:entry for entry in data.get('roomSources',[])}
    if not isinstance(conditions,list) or len(conditions)!=12 or {c['name'] for c in conditions}!=expected or set(rooms)!=set(generator.ROOM_LAYOUTS):
        raise ValueError('validation matrix is incomplete or duplicated')
    for condition in conditions:
        name=condition['name'];directory=matrix/name;env=(directory/'environment.bin').read_bytes();case_bytes=(directory/'case.json').read_bytes()
        if generator.digest(env)!=condition['environmentSHA256'] or generator.digest(case_bytes)!=condition['caseSHA256']:
            raise ValueError('validation scene bytes differ')
        if name.startswith('room-'):
            layout=condition.get('layout');source=rooms[layout]
            if source.get('environmentPath')!=str((generator.ROOMS/str(layout)/'1/environment.bin').absolute()) or source.get('casePath')!=str((generator.ROOMS/str(layout)/'1/case.json').absolute()): raise ValueError('unexpected training-room source')
            if condition.get('family')!='natural-room' or env!=Path(source['environmentPath']).read_bytes() or case_bytes!=Path(source['casePath']).read_bytes() or generator.digest(env)!=source['environmentSHA256'] or generator.digest(case_bytes)!=source['caseSHA256']:
                raise ValueError('training room source changed')
        else:
            heading=condition['spawnHeading'];family=condition['family']
            if name!=f'{family}-yaw-{heading:+.2f}' or heading not in generator.HEADINGS or family not in generator.FAMILIES or env!=generator.variant(original,heading,family) or case_bytes!=case:
                raise ValueError('validation scene transformation differs')
    return receipt,data


def pin_files(pilot,matrix,output,receipt,conditions):
    paths=receipt['paths']; files=[pilot/'inputs.json',pilot/'audit.json',matrix/'conditions.json',output/'worker-inputs.json',Path(__file__),
        ROOT/'flex/tests/prepare-sim-visual-validation.py',ROOT/'flex/tests/audit-sim-visual-validation.py',
        ROOT/'flex/tests/audit-sim-visual-stop.py',ROOT/'flex/tests/run-physical-hidden-trial.py',
        ROOT/'flex/tests/run-physical-rescan-trial.py',ROOT/'flex/tests/run-physical-hybrid-trial.py']
    files += [Path(paths[k]) for k in ('client','simulator','asset','config','runtime','case','environment')]
    model=Path(paths['model']);files += [model/'policy',model/'weights.bin',model/'receipt.json',*sorted((model/'kernels').iterdir())]
    for condition in conditions:
        files += [matrix/condition['name']/'case.json',matrix/condition['name']/'environment.bin']
    for folder in (pilot/'inputs/flex-source',pilot/'inputs/visual-build/flex',pilot/'inputs/build/flex/sim/library'):
        for path in sorted(folder.rglob('*')):
            if path.is_file() and '__pycache__' not in path.parts and path.suffix!='.pyc':
                if receipt['files'].get(str(path))!=sha(path): raise ValueError('pilot archived source changed')
                files.append(path)
    build_receipt=pilot/'inputs/visual-build/build.json'
    if receipt['files'].get(str(build_receipt))!=sha(build_receipt): raise ValueError('pilot build receipt changed')
    files += [build_receipt,ROOT/'flex/tests/audit-sim-visual-stop-pair.py']
    return {str(path):sha(path) for path in files}


def run(pilot,matrix,output):
    pilot=Path(pilot).absolute();matrix=Path(matrix).absolute();output=Path(output).absolute()
    with LOCK.open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if shutil.disk_usage(output.parent).free<12*1024**3: raise ValueError('insufficient space before suite')
        receipt,data=check_matrix(pilot,matrix);paths=receipt['paths'];conditions=data['conditions']
        output.mkdir(parents=False,exist_ok=False)
        env={'PATH':'/usr/bin:/bin','HOME':str(Path.home()),'SDL_VIDEODRIVER':'offscreen',
             'LD_LIBRARY_PATH':str(ROOT/'build/flex/rocm-runtime'),
             'PUPPYBOT_PHYSICAL_NAV_LIMIT':'90','PUPPYBOT_PHYSICAL_POLL_LIMIT':'1499'}
        worker=hidden.supervisor.worker_snapshot(env)
        (output/'worker-inputs.json').write_text(json.dumps(worker,sort_keys=True,indent=2)+'\n')
        pins=pin_files(pilot,matrix,output,receipt,conditions)
        manifest={'schema':'puppybot.sim-visual-validation.v1','conditions':conditions,'files':pins,'paths':paths,
                  'pilot':str(pilot),'matrix':str(matrix),'navigationLimit':90,'wallSecondsPerArm':300,'home':env['HOME'],
                  'scope':'predeclared training scenes, no hardware or held-out claim'}
        (output/'inputs.json').write_text(json.dumps(manifest,sort_keys=True,indent=2)+'\n')
        for condition in conditions:
            for arm in ('disabled','enabled'):
                if shutil.disk_usage(output).free<8*1024**3: raise ValueError('insufficient space during suite')
                if pin_files(pilot,matrix,output,receipt,conditions)!=pins: raise ValueError('pinned suite input changed')
                parent=output/'cases'/condition['name']/arm; parent.mkdir(parents=True); monitor=parent/'monitor';monitor.mkdir()
                command=[paths['client'],paths['simulator'],paths['model'],str(matrix/condition['name']/'case.json'),
                         str(matrix/condition['name']/'environment.bin'),str(parent/'run'),'--allow-zero-contact']
                (parent/'command.json').write_text(json.dumps(command,indent=2)+'\n')
                arm_env=dict(env,PUPPYBOT_SIM_VISUAL_STOP='1' if arm=='enabled' else '0')
                (parent/'environment.json').write_text(json.dumps(arm_env,sort_keys=True,indent=2)+'\n')
                status=hidden.supervise(command,monitor,arm_env,300)
                if status['signal'] is not None or status['timedOut'] or status['clientExit']!=0 or status['remainingWorkersTerminated']:
                    auditor=ROOT/'flex/tests/audit-sim-visual-validation.py'
                    partial=subprocess.run([sys.executable,'-I',str(auditor),str(output)],cwd=ROOT,capture_output=True,text=True,timeout=300)
                    (output/'audit.partial.log').write_text(partial.stderr)
                    if partial.returncode==0: (output/'audit.partial.json').write_text(partial.stdout)
                    raise RuntimeError('suite arm failed or required cleanup; partial evidence retained')
                if pin_files(pilot,matrix,output,receipt,conditions)!=pins: raise ValueError('pinned suite input changed')
                launch=shutil.which('python3',path=arm_env['PATH'])
                if not launch or Path(launch).absolute()!=Path(worker['launchPath']) or Path(launch).resolve()!=Path(worker['executable']): raise ValueError('worker interpreter path changed')
                hidden.supervisor.verify_worker(worker);hidden.rescan.verify_model(Path(paths['model']))
        auditor=ROOT/'flex/tests/audit-sim-visual-validation.py'
        completed=subprocess.run([sys.executable,'-I',str(auditor),str(output)],cwd=ROOT,capture_output=True,text=True,timeout=300)
        (output/'audit.log').write_text(completed.stderr)
        if completed.returncode: raise RuntimeError('suite audit failed; partial evidence retained')
        (output/'audit.json').write_text(completed.stdout)
        print(json.dumps({'status':'diagnostic_only','cases':len(conditions),'audit':str(output/'audit.json')}))


if __name__=='__main__':
    if len(sys.argv)!=4: raise SystemExit(__doc__)
    run(*sys.argv[1:])
