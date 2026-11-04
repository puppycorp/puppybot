#!/usr/bin/env python3
"""Independently inspect a completed three-arm simulated hint experiment.

Outcome and timing come from simulator truth AFTER each run. No hardware,
causality, policy-navigation success or safety certification is established.
"""
import importlib.util
import json
import math
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result


runner=load('hint_runner',ROOT/'flex/tests/run-physical-handoff-hint.py')
sha=runner.sha


def trace_metrics(path,enabled,handoff_step=None,initial_step=None):
    last_step=-1;blocked=0;seen_hint=False;captured=used=0;first_capture=first_use=None;initial=None
    with Path(path).open() as stream:
        for line in stream:
            row=json.loads(line);step=row.get('step')
            if type(step) is not int or step<0 or step<=last_step:raise ValueError('invalid or unordered trace steps')
            last_step=step
            if step==initial_step:
                def vector(value,size):
                    if not isinstance(value,list) or len(value)!=size or any(type(x) not in (int,float) or not math.isfinite(x) for x in value):raise ValueError('invalid initial truth pose')
                    return value
                case=row['case'];objects=case['objects'];container=case['container']
                if not isinstance(objects,list) or not objects or any(not isinstance(obj.get('id'),str) for obj in objects):raise ValueError('invalid initial objects')
                initial={'pose':vector(row['pose'],3),'objects':[{'id':obj['id'],'position':vector(obj['position'],3),'quaternion':vector(obj['quaternion'],4)} for obj in objects],
                         'container':{'position':vector(container['position'],3),'quaternion':vector(container['quaternion'],4)}}
            if type(row.get('blocked')) is not bool or type(row.get('physicsFault')) is not int:raise ValueError('missing trace fault or block state')
            if row['physicsFault']!=0:raise ValueError('simulator physics fault')
            blocked+=int(row['blocked'])
            hint=row.get('handoffHint')
            if enabled:
                if not isinstance(hint,dict) or set(hint)!={'captures','uses'}:raise ValueError('missing hint diagnostics')
                a,b=hint['captures'],hint['uses']
                if type(a) is not int or type(b) is not int or not captured<=a<=1 or not used<=b<=a:raise ValueError('invalid hint counters')
                if (a or b) and (handoff_step is None or step<=handoff_step):raise ValueError('hint counter predates handoff')
                if a>captured:first_capture=step
                if b>used:first_use=step
                captured,used=a,b;seen_hint=True
            elif hint is not None:raise ValueError('disabled arm emitted hint diagnostics')
    if last_step<0 or (enabled and not seen_hint):raise ValueError('empty or uninstrumented trace')
    if initial_step is not None and initial is None:raise ValueError('missing initial observation trace tick')
    return {'lastStep':last_step,'blockedTicks':blocked,'hintCaptures':captured,'hintUses':used,'firstHintCaptureStep':first_capture,'firstHintUseStep':first_use,
            'counterEventsIndependentlyOrdered':bool(first_capture is not None and first_use is not None and first_capture<first_use),'initialTruth':initial}


def protocol(run,result):
    with (Path(run)/'physical-agent.jsonl').open() as stream:
        rows=[json.loads(line) for line in stream]
    if not rows or [row.get('sequence') for row in rows]!=list(range(1,len(rows)+1)):raise ValueError('physical protocol sequence incomplete')
    first=rows[0];last=rows[-1]
    if any(row.get('schema')!='puppybot.physical-agent.v1' or type(row.get('step')) is not int or type(row.get('totalSteps')) is not int or row['step']!=row['totalSteps'] for row in rows):raise ValueError('invalid protocol tick or schema')
    if any(rows[i]['totalSteps']<rows[i-1]['totalSteps'] for i in range(1,len(rows))):raise ValueError('protocol tick regression')
    if type(first.get('rgbDetections')) is not int or first['rgbDetections']<0:raise ValueError('invalid initial detection count')
    if (first.get('owner')!=0 or first.get('ack')!=0 or first.get('imageValid') is not True or first.get('cameraDriving') is not True
            or first.get('cameraStill') is not True or first.get('cameraFrame')!=first.get('totalSteps')):raise ValueError('invalid first camera observation')
    if last.get('owner')!=2 or last.get('ack')!=7 or last.get('driveCommand')!=[0,0,90] or result.get('stopCommandAcknowledged') is not True:raise ValueError('missing simulated stop acknowledgement')
    handoffs=[row for row in rows if row.get('ack')==3]
    if bool(handoffs)!=result.get('handoff') or len(handoffs)>1:raise ValueError('handoff result differs from protocol')
    if handoffs:
        handoff=handoffs[0];index=rows.index(handoff)
        if (not index or handoff.get('owner')!=1 or handoff.get('driveCommand')!=[0,0,90] or handoff.get('imageValid') is not False
                or handoff['totalSteps']!=rows[index-1]['totalSteps']+2):raise ValueError('invalid handoff ownership, stop or tick advancement')
    if type(result.get('policyActions')) is not int or result['policyActions']<0:raise ValueError('invalid policy action count')
    if result['policyActions']==0 and handoffs:
        if len(rows)<3 or rows[1] is not handoffs[0]:raise ValueError('unexpected zero-action handoff sequence')
        polls=rows[2:-1]
        if len(polls)>result.get('collectorPollLimit',-1):raise ValueError('collector poll count exceeded')
        for i,row in enumerate(polls):
            terminal=row.get('ack')==5
            if row.get('ack') not in (4,5) or row.get('owner')!=(2 if terminal else 1) or row.get('imageValid') is not False:raise ValueError('invalid collector poll')
            advance=row['totalSteps']-rows[i+1]['totalSteps']
            if (terminal and (not 0<=advance<=20 or i!=len(polls)-1)) or (not terminal and advance!=20):raise ValueError('invalid collector tick progression')
        if type(result.get('collectorTerminal')) is not bool or result['collectorTerminal']!=bool(polls and polls[-1].get('ack')==5):raise ValueError('terminal result differs from collector protocol')
        if any(Path(run,'actors').iterdir()):raise ValueError('zero-action run contains actor artifacts')
    return {'initialDetection':first.get('rgbDetections'),'handoffStep':handoffs[0]['step'] if handoffs else None,
            'policyActions':result['policyActions'],'initialObservation':first,'acknowledgedStop':True}


def audit(root):
    root=Path(root).absolute();manifest=json.loads((root/'inputs.json').read_text())
    if manifest.get('schema')!='puppybot.physical-handoff-hint-trial.v1' or manifest.get('build')!=str(runner.BUILD):raise ValueError('unexpected hint trial manifest')
    build,_=runner.check()
    if runner.pins(root)!=manifest['files']:raise ValueError('hint trial pinned input changed')
    if manifest.get('navigationLimit')!=30 or manifest.get('collectorPollLimit')!=1499 or manifest.get('wallSecondsPerArm')!=300:raise ValueError('hint trial limits differ')
    if (manifest['original']!=str(runner.BUILD/'inputs/simulator') or manifest['candidate']!=str(runner.BUILD/'simulator-hint')
            or manifest['client']!=str(runner.BUILD/'inputs/client') or manifest['case']!=str(root/'inputs/case.json')
            or manifest['environment']!=str(root/'inputs/environment.bin') or manifest['model']!=str(root/'inputs/model')):raise ValueError('hint trial paths differ')
    arms=[]
    for name,sim,flag in (('original',manifest['original'],'0'),('candidate-disabled',manifest['candidate'],'0'),('candidate-enabled',manifest['candidate'],'1')):
        parent=root/name;monitor=parent/'monitor/supervisor-result.json'
        if not monitor.is_file():arms.append({'arm':name,'status':'censored','reason':'not_started_or_no_supervisor'});continue
        status=json.loads(monitor.read_text())
        if type(status.get('clientExit')) is not int or status['clientExit']!=0 or status.get('timedOut') is not False or status.get('signal') is not None or status.get('remainingWorkersTerminated') is not False:
            arms.append({'arm':name,'status':'censored','reason':'supervisor_failure','supervisor':status});continue
        run=parent/'run'
        if not (run/'result.json').is_file():arms.append({'arm':name,'status':'censored','reason':'missing_result'});continue
        command=json.loads((parent/'command.json').read_text())
        if command!=[manifest['client'],sim,manifest['model'],manifest['case'],manifest['environment'],str(run),'--allow-zero-contact']:raise ValueError('arm command differs')
        env=json.loads((parent/'environment.json').read_text());expected={'PATH':'/usr/bin:/bin','HOME':manifest['home'],'SDL_VIDEODRIVER':'offscreen','LD_LIBRARY_PATH':str(ROOT/'build/flex/rocm-runtime'),'PUPPYBOT_PHYSICAL_NAV_LIMIT':'30','PUPPYBOT_PHYSICAL_POLL_LIMIT':'1499','PUPPYBOT_PHYSICAL_HANDOFF_HINT':flag}
        if env!=expected:raise ValueError('arm environment differs')
        result=json.loads((run/'result.json').read_text());client=json.loads((run/'inputs.json').read_text())
        if (result.get('traceSHA256')!=sha(run/'trace.jsonl') or result.get('outcome')!='unverified' or result.get('stoppedRescanEnabled') is not False
                or result.get('navigationActionLimit')!=30 or result.get('collectorPollLimit')!=1499):raise ValueError('arm result invalid')
        expected_client={'simulatorSHA256':manifest['files'][sim],'caseSHA256':manifest['files'][manifest['case']],
                         'environmentSHA256':manifest['files'][manifest['environment']],'weightsSHA256':manifest['files'][str(Path(manifest['model'])/'weights.bin')],
                         'policySHA256':manifest['files'][str(Path(manifest['model'])/'policy')],'receiptSHA256':manifest['files'][str(Path(manifest['model'])/'receipt.json')],
                         'robotAssetSHA256':manifest['files'][manifest['asset']]}
        if any(client.get(k)!=v for k,v in expected_client.items()):raise ValueError('arm client input identity differs')
        p=protocol(run,result);t=trace_metrics(run/'trace.jsonl',name=='candidate-enabled',p['handoffStep'],p['initialObservation']['step'])
        script=runner.BUILD/'inputs/flex-source/exploration/manipulation_audit.py'
        done=subprocess.run([sys.executable,'-I',str(script),manifest['case'],str(run/'trace.jsonl')],cwd=ROOT,capture_output=True,text=True,timeout=120)
        if done.returncode:raise ValueError('independent manipulation audit failed: '+name+': '+done.stderr[-1000:])
        manipulation=json.loads(done.stdout)
        if manipulation.get('caseSHA256')!=manifest['files'][manifest['case']]:raise ValueError('manipulation case hash differs')
        eligible=p['initialDetection']>0 and p['policyActions']==0 and p['handoffStep'] is not None
        pickup=manipulation.get('captures',[])
        elapsed=pickup[0]['step']-p['handoffStep'] if eligible and pickup else None
        if elapsed is not None and elapsed<0:raise ValueError('capture precedes handoff')
        arms.append({'arm':name,'status':'completed' if eligible else 'censored','reason':None if eligible else 'visible_zero_action_handoff_not_observed',
                     'protocol':p,'trace':t,'manipulation':manipulation,'handoffToFirstCaptureTicks':elapsed,'collectorTerminal':result.get('collectorTerminal')})
    by={a['arm']:a for a in arms};a=by['original'];b=by['candidate-disabled'];c=by['candidate-enabled'];parity=None
    if a['status']=='completed' and b['status']=='completed':
        def outcome(x):
            m=x['manipulation'];return ([r['object'] for r in m['captures']],[(r['object'],r['overBox']) for r in m['releases']],m['settledDeliveries'],m['settledAtEnd'],m['traceMeetsManipulationCriteria'],x['collectorTerminal'])
        parity=(a['protocol']['initialObservation']==b['protocol']['initialObservation'] and a['trace']['initialTruth']==b['trace']['initialTruth'] and outcome(a)==outcome(b))
    exposure=c.get('trace',{}).get('hintUses',0)>0
    initial_match=None
    if all(arm['status']=='completed' for arm in arms):
        initial_match=all(arm['protocol']['initialObservation']==a['protocol']['initialObservation'] and arm['trace']['initialTruth']==a['trace']['initialTruth'] for arm in arms)
    return {'status':'diagnostic_only','arms':arms,'originalVsDisabledOutcomeAndInitialObservationMatch':parity,
            'allInitialMetadataAndTruthMatch':initial_match,'comparisonCensorReason':'initial_metadata_or_truth_mismatch' if initial_match is False else None,
            'candidateHintUsed':exposure,'comparisonEligible':bool(parity and initial_match and exposure),
            'scope':'one visible selection case, simulated collector and post-run truth; initial camera pixels were not recorded or compared; asynchronous mapping may differ; no exact parity, causality, learned-navigation, held-out or physical-hardware claim'}


if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit(__doc__)
    try:print(json.dumps(audit(Path(sys.argv[1])),sort_keys=True))
    except (OSError,ValueError,KeyError,TypeError,json.JSONDecodeError) as error:raise SystemExit(f'Invalid handoff hint trial: {error}')
