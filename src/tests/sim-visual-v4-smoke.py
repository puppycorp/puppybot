#!/usr/bin/env python3
"""One bounded rendered v4 startup smoke, not a task-success test.

Usage: sim-visual-v4-smoke.py PILOT V4_INPUTS NEW_OUTPUT
Run only after review and an idle-GPU/disk check. Uses room-13 with one policy
action at most and one collector poll at most. Failed results are retained.
"""
import fcntl
import importlib.util
import json
import shutil
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
LOCK=ROOT/'build/flex/sim/levels-v2/pitch82/.l4-matched.lock'


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result


v4=load('v4_runner',ROOT/'flex/tests/run-sim-visual-validation-v4.py')
sha=v4.sha


def evidence_files(smoke):
    smoke=Path(smoke).absolute();required=[smoke/'inputs.json',smoke/'worker-inputs.json',smoke/'command.json',smoke/'environment.json',
        smoke/'monitor/supervisor-result.json',smoke/'monitor/client.log',smoke/'run/inputs.json',smoke/'run/result.json',
        smoke/'run/trace.jsonl',smoke/'run/physical-agent.jsonl',smoke/'run/native.log',smoke/'run/policy.log',smoke/'report.json']
    if any(not path.is_file() for path in required):raise ValueError('missing startup smoke evidence')
    files=[p for p in sorted(smoke.rglob('*')) if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc']
    return files


def audit(smoke,pilot,matrix):
    smoke=Path(smoke).absolute();pilot=Path(pilot).absolute();matrix=Path(matrix).absolute()
    receipt,data=v4.check_matrix(pilot,matrix);paths=receipt['paths'];manifest=json.loads((smoke/'inputs.json').read_text())
    if (manifest.get('schema')!='puppybot.visual-v4-smoke.v1' or manifest.get('pilot')!=str(pilot) or manifest.get('matrix')!=str(matrix)
            or manifest.get('paths')!=paths or manifest.get('case')!='room-13' or manifest.get('wallSeconds')!=120):raise ValueError('smoke manifest differs')
    files=manifest['files'];expected=v4.pin_files(pilot,matrix,smoke,receipt,data['conditions'])
    if files!=expected:raise ValueError('smoke pinned inputs changed')
    command=json.loads((smoke/'command.json').read_text());run=smoke/'run';case=matrix/'room-13/case.json';environment=matrix/'room-13/environment.bin'
    if command!=[paths['client'],paths['simulator'],paths['model'],str(case),str(environment),str(run),'--allow-zero-contact']:raise ValueError('smoke invocation differs')
    env=json.loads((smoke/'environment.json').read_text());expected_env={'PATH':'/usr/bin:/bin','HOME':manifest['home'],'SDL_VIDEODRIVER':'offscreen',
        'LD_LIBRARY_PATH':str(Path(paths['runtime']).parent),'PUPPYBOT_PHYSICAL_NAV_LIMIT':'1','PUPPYBOT_PHYSICAL_POLL_LIMIT':'1','PUPPYBOT_SIM_VISUAL_STOP':'0'}
    if env!=expected_env:raise ValueError('smoke environment differs')
    worker=json.loads((smoke/'worker-inputs.json').read_text());launch=shutil.which('python3',path=env['PATH'])
    if not launch or Path(launch).absolute()!=Path(worker['launchPath']) or Path(launch).resolve()!=Path(worker['executable']):raise ValueError('smoke worker interpreter path differs')
    v4.base.hidden.supervisor.verify_worker(worker)
    status=json.loads((smoke/'monitor/supervisor-result.json').read_text())
    if (type(status.get('clientExit')) is not int or status['clientExit']!=0 or status.get('timedOut') is not False or status.get('signal') is not None
            or status.get('remainingWorkersTerminated') is not False or type(status.get('processGroup')) is not int or status['processGroup']<=0):raise ValueError('smoke supervisor failed or cleaned descendants')
    result=json.loads((run/'result.json').read_text());client=json.loads((run/'inputs.json').read_text())
    if (result.get('policyActions')!=1 or result.get('handoff') is not False or result.get('navigationActionLimit')!=1 or result.get('collectorPollLimit')!=1
            or result.get('visualStopEnabled') is not False or result.get('stoppedRescanEnabled') is not False
            or result.get('stopCommandAcknowledged') is not True or result.get('outcome')!='unverified'
            or result.get('traceSHA256')!=sha(run/'trace.jsonl')):raise ValueError('smoke did not complete one navigation action and simulated stop')
    expected_client={'simulatorSHA256':files[paths['simulator']],'caseSHA256':files[str(case)],'environmentSHA256':files[str(environment)],
                     'weightsSHA256':files[str(Path(paths['model'])/'weights.bin')],'policySHA256':files[str(Path(paths['model'])/'policy')],
                     'receiptSHA256':files[str(Path(paths['model'])/'receipt.json')],'robotAssetSHA256':files[paths['asset']]}
    if any(client.get(k)!=value for k,value in expected_client.items()):raise ValueError('smoke client input identity differs')
    with (run/'physical-agent.jsonl').open() as stream:rows=[json.loads(line) for line in stream]
    actor=v4.base.hidden.check_actor_inputs(run,result,rows)
    if actor.get('initialDetection')!=0 or len(rows)!=3:raise ValueError('smoke did not record expected navigation sequence')
    audit_v3=load('validation_audit',ROOT/'flex/tests/audit-sim-visual-validation.py')
    poses=audit_v3.truth_trace(run/'trace.jsonl');audit_v3.require_spawn_match(environment,rows,rows,poses,poses)
    report={'status':'simulated_rendered_startup_observed','case':'room-13','policyActions':1,'simulatedStopAcknowledged':True,
            'traceSHA256':sha(run/'trace.jsonl'),'journalSHA256':sha(run/'physical-agent.jsonl'),
            'scope':'one rendered simulated room startup and one policy command; no task success, physical robot, sensor authenticity or GPU runtime identity proof'}
    stored=smoke/'report.json'
    if stored.exists() and json.loads(stored.read_text())!=report:raise ValueError('smoke report changed')
    return report


def run(pilot,matrix,output):
    pilot=Path(pilot).absolute();matrix=Path(matrix).absolute();output=Path(output).absolute()
    with LOCK.open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if output.exists() or output.is_symlink():raise ValueError('smoke destination exists')
        if shutil.disk_usage(output.parent).free<12*1024**3:raise ValueError('insufficient space for startup smoke')
        receipt,data=v4.check_matrix(pilot,matrix);paths=receipt['paths'];output.mkdir(parents=False,exist_ok=False)
        env={'PATH':'/usr/bin:/bin','HOME':str(Path.home()),'SDL_VIDEODRIVER':'offscreen','LD_LIBRARY_PATH':str(ROOT/'build/flex/rocm-runtime'),
             'PUPPYBOT_PHYSICAL_NAV_LIMIT':'1','PUPPYBOT_PHYSICAL_POLL_LIMIT':'1','PUPPYBOT_SIM_VISUAL_STOP':'0'}
        worker=v4.base.hidden.supervisor.worker_snapshot(env)
        (output/'worker-inputs.json').write_text(json.dumps(worker,sort_keys=True,indent=2)+'\n')
        pins=v4.pin_files(pilot,matrix,output,receipt,data['conditions'])
        manifest={'schema':'puppybot.visual-v4-smoke.v1','pilot':str(pilot),'matrix':str(matrix),'paths':paths,'case':'room-13','wallSeconds':120,'home':env['HOME'],'files':pins}
        (output/'inputs.json').write_text(json.dumps(manifest,sort_keys=True,indent=2)+'\n')
        command=[paths['client'],paths['simulator'],paths['model'],str(matrix/'room-13/case.json'),str(matrix/'room-13/environment.bin'),str(output/'run'),'--allow-zero-contact']
        (output/'command.json').write_text(json.dumps(command,indent=2)+'\n');(output/'environment.json').write_text(json.dumps(env,sort_keys=True,indent=2)+'\n')
        monitor=output/'monitor';monitor.mkdir();status=v4.base.hidden.supervise(command,monitor,env,120)
        if status['signal'] is not None or status['timedOut'] or status['clientExit']!=0 or status['remainingWorkersTerminated']:raise RuntimeError('smoke failed or required cleanup; evidence retained')
        if v4.pin_files(pilot,matrix,output,receipt,data['conditions'])!=pins:raise ValueError('smoke input changed')
        launch=shutil.which('python3',path=env['PATH'])
        if not launch or Path(launch).absolute()!=Path(worker['launchPath']) or Path(launch).resolve()!=Path(worker['executable']):raise ValueError('worker interpreter path changed')
        v4.base.hidden.supervisor.verify_worker(worker);v4.base.hidden.rescan.verify_model(Path(paths['model']))
        report=audit(output,pilot,matrix)
        (output/'report.json').write_text(json.dumps(report,sort_keys=True,indent=2)+'\n');print(json.dumps(report,sort_keys=True))


if __name__=='__main__':
    raise SystemExit('Disabled pending independent review; no GPU launch is authorized by this scaffold.')
