#!/usr/bin/env python3
"""Separately versioned v4 paired simulation; requires reviewed startup smoke.

Usage: run-sim-visual-validation-v4.py PILOT V4_INPUTS SMOKE_DIRECTORY NEW_OUTPUT
This is a diagnostic plan; do not run before review, smoke and an idle-GPU
check. Twelve pairs have a 300-second watchdog per arm (120-minute ceiling).
"""
import fcntl
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
LOCK=ROOT/'build/flex/sim/levels-v2/pitch82/.l4-matched.lock'


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result


base=load('v3_base',ROOT/'flex/tests/run-sim-visual-validation.py')
metadata=load('v4_metadata',ROOT/'flex/tests/verify-sim-visual-validation-v4-metadata.py')
reset=load('v4_reset',ROOT/'flex/tests/verify-sim-visual-validation-v4-reset.py')
sha=base.sha


def check_matrix(pilot,matrix):
    pilot=Path(pilot).absolute();matrix=Path(matrix).absolute();plan=json.loads((matrix/'conditions.json').read_text())
    v3=Path(plan['sourceV3']);report=Path(str(matrix)+'-reset-report.json')
    if plan.get('pilot')!=str(pilot) or not v3.is_absolute() or plan.get('schema')!='puppybot.visual-stop-validation-plan.v4':raise ValueError('v4 pilot/source identity differs')
    receipt,original=base.check_matrix(pilot,v3)
    metadata.audit(v3,matrix,report)
    # Re-execute the archived CPU-only reset for all scenes; a self-reported
    # historic success alone is insufficient for a new run.
    with tempfile.TemporaryDirectory(prefix='puppy-v4-reset-recheck-') as tmp:
        freshly=reset.verify(pilot,v3,matrix,Path(tmp)/'report.json')
    saved=json.loads(report.read_text())
    if freshly!=saved or freshly.get('status')!='all_cpu_resets_accepted':raise ValueError('v4 CPU reset recheck differs')
    return receipt,{'conditions':plan['conditions']}


def pin_files(pilot,matrix,output,receipt,conditions):
    files=base.pin_files(pilot,matrix,output,receipt,conditions)
    plan=json.loads((matrix/'conditions.json').read_text());v3=Path(plan['sourceV3'])
    extra=[Path(__file__),ROOT/'flex/tests/audit-sim-visual-validation-v4.py',
           ROOT/'flex/tests/verify-sim-visual-validation-v4-metadata.py',
           ROOT/'flex/tests/verify-sim-visual-validation-v4-reset.py',
           ROOT/'flex/tests/physical-case-preflight.py',ROOT/'flex/tests/physical-reset-preflight.py',
           ROOT/'flex/tests/prepare-sim-visual-validation-v4.py',
           ROOT/'flex/tests/sim-visual-v4-smoke.py',Path(str(matrix)+'-reset-report.json'),v3/'conditions.json']
    for row in plan['conditions']:
        extra += [v3/row['name']/'case.json',v3/row['name']/'environment.bin']
    for path in extra:files[str(path)]=sha(path)
    return files


def run(pilot,matrix,smoke,output):
    pilot=Path(pilot).absolute();matrix=Path(matrix).absolute();smoke=Path(smoke).absolute();output=Path(output).absolute()
    with LOCK.open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if shutil.disk_usage(output.parent).free<12*1024**3:raise ValueError('insufficient space before suite')
        receipt,data=check_matrix(pilot,matrix);paths=receipt['paths'];conditions=data['conditions']
        smoke_module=load('v4_smoke',ROOT/'flex/tests/sim-visual-v4-smoke.py')
        checked=smoke_module.audit(smoke,pilot,matrix)
        if checked.get('status')!='simulated_rendered_startup_observed':raise ValueError('v4 smoke did not establish simulated startup')
        output.mkdir(parents=False,exist_ok=False)
        env={'PATH':'/usr/bin:/bin','HOME':str(Path.home()),'SDL_VIDEODRIVER':'offscreen',
             'LD_LIBRARY_PATH':str(ROOT/'build/flex/rocm-runtime'),'PUPPYBOT_PHYSICAL_NAV_LIMIT':'90','PUPPYBOT_PHYSICAL_POLL_LIMIT':'1499'}
        worker=base.hidden.supervisor.worker_snapshot(env)
        (output/'worker-inputs.json').write_text(json.dumps(worker,sort_keys=True,indent=2)+'\n')
        pins=pin_files(pilot,matrix,output,receipt,conditions)
        for path in smoke_module.evidence_files(smoke):pins[str(path)]=sha(path)
        manifest={'schema':'puppybot.sim-visual-validation.v1','version':'v4','conditions':conditions,'files':pins,'paths':paths,
                  'pilot':str(pilot),'matrix':str(matrix),'smoke':str(smoke),'navigationLimit':90,'wallSecondsPerArm':300,'home':env['HOME'],
                  'scope':'v4 predeclared training scenes; physical-discovery controller; no hardware or held-out claim'}
        (output/'inputs.json').write_text(json.dumps(manifest,sort_keys=True,indent=2)+'\n')
        def current_pins():
            current=pin_files(pilot,matrix,output,receipt,conditions)
            for path in smoke_module.evidence_files(smoke):current[str(path)]=sha(path)
            return current
        for condition in conditions:
            for arm in ('disabled','enabled'):
                if shutil.disk_usage(output).free<8*1024**3:raise ValueError('insufficient space during suite')
                if current_pins()!=pins:raise ValueError('pinned suite input changed')
                parent=output/'cases'/condition['name']/arm;parent.mkdir(parents=True);monitor=parent/'monitor';monitor.mkdir()
                command=[paths['client'],paths['simulator'],paths['model'],str(matrix/condition['name']/'case.json'),str(matrix/condition['name']/'environment.bin'),str(parent/'run'),'--allow-zero-contact']
                (parent/'command.json').write_text(json.dumps(command,indent=2)+'\n')
                arm_env=dict(env,PUPPYBOT_SIM_VISUAL_STOP='1' if arm=='enabled' else '0')
                (parent/'environment.json').write_text(json.dumps(arm_env,sort_keys=True,indent=2)+'\n')
                status=base.hidden.supervise(command,monitor,arm_env,300)
                if status['signal'] is not None or status['timedOut'] or status['clientExit']!=0 or status['remainingWorkersTerminated']:
                    auditor=ROOT/'flex/tests/audit-sim-visual-validation-v4.py'
                    partial=subprocess.run([sys.executable,'-I',str(auditor),str(output)],cwd=ROOT,capture_output=True,text=True,timeout=300)
                    (output/'audit.partial.log').write_text(partial.stderr)
                    if partial.returncode==0:(output/'audit.partial.json').write_text(partial.stdout)
                    raise RuntimeError('suite arm failed or required cleanup; partial evidence retained')
                if current_pins()!=pins:raise ValueError('pinned suite input changed')
                launch=shutil.which('python3',path=arm_env['PATH'])
                if not launch or Path(launch).absolute()!=Path(worker['launchPath']) or Path(launch).resolve()!=Path(worker['executable']):raise ValueError('worker interpreter path changed')
                base.hidden.supervisor.verify_worker(worker);base.hidden.rescan.verify_model(Path(paths['model']))
        auditor=ROOT/'flex/tests/audit-sim-visual-validation-v4.py'
        completed=subprocess.run([sys.executable,'-I',str(auditor),str(output)],cwd=ROOT,capture_output=True,text=True,timeout=300)
        (output/'audit.log').write_text(completed.stderr)
        if completed.returncode:raise RuntimeError('v4 suite audit failed; partial evidence retained')
        (output/'audit.json').write_text(completed.stdout)
        print(json.dumps({'status':'diagnostic_only','cases':len(conditions),'audit':str(output/'audit.json')}))


if __name__=='__main__':
    raise SystemExit('Disabled pending independent review; no GPU launch is authorized by this scaffold.')
