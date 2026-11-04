#!/usr/bin/env python3
"""Audit recorded search-transfer evidence; simulator truth is post-run only."""
import hashlib
import importlib.util
import json
import math
import subprocess
import struct
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
ARMS=('baseline','candidate-disabled','candidate-search')


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


hidden=load('search_hidden',ROOT/'flex/tests/run-physical-hidden-trial.py')


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for part in iter(lambda:stream.read(1024*1024),b''):h.update(part)
    return h.hexdigest()


def rows(path):
    with Path(path).open() as stream:return [json.loads(line) for line in stream]


def protocol(run,enabled):
    run=Path(run);result=json.loads((run/'result.json').read_text());journal=rows(run/'physical-agent.jsonl')
    if not journal or any(type(r.get('sequence')) is not int or r['sequence']!=i+1 for i,r in enumerate(journal)):raise ValueError('invalid observation sequence')
    if result.get('navigationActionLimit')!=90 or result.get('collectorPollLimit')!=1499 or type(result.get('policyActions')) is not int or not 1<=result['policyActions']<=90:raise ValueError('invalid limits or actor count')
    if (result.get('stoppedRescanEnabled') is not False or type(result.get('stoppedRescanAttempts')) is not int or result['stoppedRescanAttempts']!=0 or result.get('stoppedRescanHandoff') is not False or type(result.get('stoppedRescanStopReason')) is not int or result['stoppedRescanStopReason']!=0 or result.get('stoppedRescanStopReasonText')!='none' or type(result.get('handoff')) is not bool or result.get('outcome')!='unverified'):raise ValueError('invalid result scope')
    client=json.loads((run/'inputs.json').read_text())
    if enabled:
        if client.get('searchFallbackEnabled') is not True or type(result.get('searchFallbackStarted')) is not bool:raise ValueError('missing search opt-in result')
        requests=rows(run/'search-requests.jsonl')
        if len(requests)!=len(journal):raise ValueError('missing or dangling request intent')
    else:
        if 'searchFallbackEnabled' in client or 'searchFallbackStarted' in result or (run/'search-requests.jsonl').exists():raise ValueError('disabled path emitted opt-in state')
        requests=[]
        for row in journal:
            command={0:1,1:2,2:6,3:6,4:7,5:7,7:3}.get(row.get('ack'))
            requests.append({'sequence':row.get('sequence'),'command':command,'steering':0,'speed':0,'hold':10 if command==2 else 20 if command==7 else 0})
    searches=handoffs=polls=0;search_step=handoff_step=None;terminal=False;actions=0
    for i,(row,request) in enumerate(zip(journal,requests)):
        if set(request)!={'sequence','command','steering','speed','hold'} or any(type(request[k]) is not int for k in request) or request['sequence']!=i+1:raise ValueError('invalid request intent')
        if any(type(row.get(k)) is not int or row[k]<0 for k in ('step','totalSteps','timeMs','sequence','owner','ack')) or row['step']!=row['totalSteps']:raise ValueError('invalid observation integers')
        if row.get('schema')!='puppybot.physical-agent.v1' or type(row.get('imageValid')) is not bool:raise ValueError('invalid observation schema')
        command=request['command'];ack=row['ack'];owner=row['owner'];drive=row.get('driveCommand')
        if not isinstance(drive,list) or len(drive)!=3 or any(type(x) is not int for x in drive):raise ValueError('invalid drive echo')
        if i:
            prior=journal[i-1];delta=row['totalSteps']-prior['totalSteps']
            if delta<0 or row['timeMs']-prior['timeMs']!=20*delta:raise ValueError('clock or tick mismatch')
        else:prior=None;delta=0
        if command==1:
            if i!=0 or ack!=0 or owner!=0 or drive!=[0,0,90] or any(request[k] for k in ('steering','speed','hold')):raise ValueError('invalid reset')
        elif command==2:
            if not prior or prior['owner']!=0 or ack!=1 or owner!=0 or delta!=10 or request['hold']!=10:raise ValueError('invalid navigation action')
            if enabled and (abs(request['steering'])>1000 or abs(request['speed'])>1000):raise ValueError('invalid drive intent')
            if enabled:
                throttle=math.trunc(request['speed']*60/1000) if abs(request['speed'])>=80 else 0
                steering=90+math.trunc(math.trunc(request['steering']/10)*45/100)
                if drive!=[throttle,throttle,steering]:raise ValueError('drive intent and echo differ')
                action=(run/'actors'/f"actor-{prior['sequence']}.action").read_bytes()
                if len(action)!=8:raise ValueError('missing actor action')
                steer,speed=struct.unpack('<2f',action)
                if not all(math.isfinite(v) for v in (steer,speed)) or (request['steering'],request['speed'])!=(round(steer*1000),round(speed*1000)):raise ValueError('actor action and drive intent differ')
            actions+=1
        elif command in (6,8):
            if not prior or prior['owner']!=0 or delta!=2 or drive!=[0,0,90] or any(request[k] for k in ('steering','speed','hold')):raise ValueError('invalid stopped handoff')
            if command==8:
                searches+=1
                if not enabled or searches>1 or actions!=90 or ack not in (2,8):raise ValueError('invalid search request')
                if ack==8:
                    if owner!=1 or row['imageValid'] or row.get('rgbDetections') is not None or row.get('cameraFrame')!=-1 or row.get('cameraDriving') is not False or row.get('cameraStill') is not False or row.get('jointTicks')!=prior.get('jointTicks'):raise ValueError('invalid search ownership')
                    search_step=row['step']
                elif owner!=0 or type(row.get('rgbDetections')) is not int or row['rgbDetections']<=0:raise ValueError('invalid search rejection')
            elif type(prior.get('rgbDetections')) is not int or prior['rgbDetections']<=0:raise ValueError('handoff lacks preceding fresh detection')
            elif ack==3:
                if owner!=1 or row['imageValid']:raise ValueError('invalid handoff')
                handoffs+=1;handoff_step=row['step']
            elif ack!=2 or owner!=0:raise ValueError('invalid ordinary handoff reply')
            if command==8 and ack==2:
                if i+1>=len(requests) or requests[i+1]['command']!=6:raise ValueError('missing retry after search rejection')
        elif command==7:
            if not prior or prior['owner']!=1 or terminal or request['hold']!=20 or request['steering'] or request['speed'] or ack not in (4,5) or owner!=(2 if ack==5 else 1) or row['imageValid'] or not (0<=delta<=20 if ack==5 else delta==20):raise ValueError('invalid collector poll')
            terminal=ack==5;polls+=1
        elif command==3:
            if i!=len(journal)-1 or ack!=7 or owner!=2 or drive!=[0,0,90] or request['steering'] or request['speed'] or request['hold'] or delta!=0:raise ValueError('invalid final stop')
        else:raise ValueError('unexpected command')
        if owner==0 and (row['imageValid'] is not True or type(row.get('rgbDetections')) is not int or row['rgbDetections']<0 or type(row.get('cameraFrame')) is not int or row['cameraFrame']!=row['totalSteps'] or row.get('cameraDriving') is not True or row.get('cameraStill') is not True):raise ValueError('invalid navigation camera fields')
        if owner in (1,2) and (row['imageValid'] is not False or row.get('rgbDetections') is not None or row.get('cameraFrame')!=-1 or row.get('cameraDriving') is not False or row.get('cameraStill') is not False):raise ValueError('contradictory collector camera fields')
        if i and prior['owner']==1 and command not in (7,3):raise ValueError('collector ownership lost')
        if command!=3:
            if i+1>=len(requests):raise ValueError('missing next command')
            if command in (1,2):
                detections=row.get('rgbDetections')
                if type(detections) is not int or detections<0:raise ValueError('invalid navigation detection')
                if actions<90:expected=6 if detections else 2
                elif enabled:expected=6 if detections else 8
                else:expected=3
            elif command==6:
                if ack==3:expected=7
                elif actions<90:expected=2
                elif enabled and i and requests[i-1]['command']==8:expected=3
                elif enabled:expected=8
                else:raise ValueError('disabled handoff after action budget')
            elif command==8:expected=7 if ack==8 else 6
            elif command==7:expected=3 if terminal or polls==1499 else 7
            else:raise ValueError('unexpected command progression')
            if requests[i+1]['command']!=expected:raise ValueError('invalid client branch progression')
    if requests[-1]['command']!=3 or polls>1499 or handoffs>1 or result.get('handoff')!=bool(handoffs) or type(result.get('collectorTerminal')) is not bool or result['collectorTerminal']!=terminal or result.get('stopCommandAcknowledged') is not True:raise ValueError('result differs from protocol')
    if enabled and result['searchFallbackStarted']!=(search_step is not None):raise ValueError('search result differs from protocol')
    if (search_step is not None or handoff_step is not None) and not terminal and polls!=1499:raise ValueError('collector polling ended before its limit')
    actor=hidden.check_actor_inputs(run,result,journal)
    if actions!=result['policyActions']:raise ValueError('policy count differs')
    return {'journal':journal,'requests':requests,'actor':actor,'searchStep':search_step,'handoffStep':handoff_step,'terminal':terminal,'actions':actions}


def actor_prefix(run_a,run_b,count):
    a=Path(run_a)/'actors';b=Path(run_b)/'actors'
    def numbered(root):
        names=sorted((p for p in root.glob('actor-*.action')),key=lambda p:int(p.stem.split('-')[1]))
        return [p.stem for p in names]
    left=numbered(a);right=numbered(b)
    if count<=0 or len(left)<count or len(right)<count:return False
    for x,y in zip(left[:count],right[:count]):
        if x!=y or any((a/(x+s)).read_bytes()!=(b/(y+s)).read_bytes() for s in ('.rgb','.feedback','.hidden','.action')):return False
    return True


def audit(root):
    root=Path(root).absolute();manifest=json.loads((root/'inputs.json').read_text())
    if manifest.get('schema')!='puppybot.physical-search-fallback-trial.v1' or manifest.get('navigationLimit')!=90 or manifest.get('collectorPollLimit')!=1499:raise ValueError('invalid trial manifest')
    runner=load('search_runner',Path(__file__).with_name('run.py'));runner.check_manifest(root,manifest)
    with Path(manifest['environment']).open('rb') as stream:header=stream.read(120)
    if len(header)<120 or header[:8]!=b'PBENV001':raise ValueError('invalid pinned environment header')
    spawn=struct.unpack_from('<3d',header,96)
    if any(not math.isfinite(v) for v in spawn):raise ValueError('invalid pinned environment spawn')
    evidence=[];raw={}
    for name in ARMS:
        parent=root/name;monitor=parent/'monitor/supervisor-result.json'
        if not monitor.is_file():evidence.append({'arm':name,'status':'censored','reason':'missing_supervisor'});continue
        s=json.loads(monitor.read_text())
        if 'signal' not in s or type(s.get('clientExit')) is not int or s['clientExit']!=0 or s.get('timedOut') is not False or s.get('signal') is not None or s.get('remainingWorkersTerminated') is not False or type(s.get('processGroup')) is not int or s['processGroup']<=0:
            evidence.append({'arm':name,'status':'censored','reason':'supervisor_failure'});continue
        if not (parent/'run/result.json').is_file():evidence.append({'arm':name,'status':'censored','reason':'missing_result'});continue
        runner.check_invocation(root,manifest,name)
        run=parent/'run';result=json.loads((run/'result.json').read_text());client=json.loads((run/'inputs.json').read_text())
        build=Path(manifest['build']);model=Path(manifest['model']);sim=build/('baseline-simulator' if name=='baseline' else 'simulator')
        expected={'simulatorSHA256':manifest['files'][str(sim)],'caseSHA256':manifest['files'][manifest['case']],
                  'environmentSHA256':manifest['files'][manifest['environment']],'weightsSHA256':manifest['files'][str(model/'weights.bin')],
                  'policySHA256':manifest['files'][str(model/'policy')],'receiptSHA256':manifest['files'][str(model/'receipt.json')],
                  'robotAssetSHA256':manifest['files'][str(hidden.ASSET)],'cameraPitch':82,'contactFeedback':'unavailable-forced-zero'}
        if any(client.get(k)!=v for k,v in expected.items()):raise ValueError('client input identity differs')
        first=rows(run/'physical-agent.jsonl')
        if not first:raise ValueError('missing initial observation')
        if result.get('policyActions')==0 or first[0].get('rgbDetections',0)>0:
            evidence.append({'arm':name,'status':'censored','reason':'initial_detection_or_zero_actions'});continue
        if result.get('traceSHA256')!=sha(run/'trace.jsonl'):raise ValueError('trace hash mismatch')
        p=protocol(run,name=='candidate-search');initial=p['journal'][0]['step'];last=p['journal'][-1]['step']
        trace=rows(run/'trace.jsonl')
        if not trace or any(type(r.get('step')) is not int for r in trace) or any(a['step']>=b['step'] for a,b in zip(trace,trace[1:])) or trace[-1]['step']!=last:raise ValueError('invalid trace endpoint')
        start=next((r for r in trace if r['step']==initial),None)
        if start is None:raise ValueError('initial trace tick missing')
        pose=start.get('pose');case=start.get('case')
        if not isinstance(pose,list) or len(pose)!=3 or any(type(x) not in (int,float) or not math.isfinite(x) for x in pose) or not isinstance(case,dict) or not isinstance(case.get('objects'),list) or not case['objects'] or not isinstance(case.get('container'),dict):raise ValueError('invalid initial simulator truth')
        if any(abs(a-b)>1e-6 for a,b in zip(pose,spawn)):
            evidence.append({'arm':name,'status':'censored','reason':'start_pose_differs_from_pinned_environment'});continue
        script=ROOT/'flex/exploration/manipulation_audit.py'
        done=subprocess.run([sys.executable,'-I',str(script),manifest['case'],str(run/'trace.jsonl')],capture_output=True,text=True,timeout=120,cwd=ROOT)
        if done.returncode:raise ValueError('manipulation audit failed: '+done.stderr[-1000:])
        m=json.loads(done.stdout)
        if m.get('caseSHA256')!=manifest['files'][manifest['case']]:raise ValueError('manipulation case differs')
        ownership=p['searchStep'] if p['searchStep'] is not None else p['handoffStep']
        if any(type(x.get('step')) is not int or ownership is None or x['step']<=ownership or x['step']>last for key in ('captures','releases') for x in m.get(key,[])):raise ValueError('manipulation event outside collector ownership')
        raw[name]=(p,start,m);evidence.append({'arm':name,'status':'complete','searchStarted':p['searchStep'] is not None,'handoff':p['handoffStep'] is not None,'actor':p['actor'],'manipulation':m})
    matched=False;reason='incomplete_arm'
    if len(raw)==3:
        a,b,c=(raw[n] for n in ARMS);count=c[0]['actions']
        def prefix(x,n):
            indexes=[i for i,r in enumerate(x[0]['journal']) if r['ack']==1]
            if len(indexes)<n or n<=0:return None
            return x[0]['journal'][:indexes[n-1]+1]
        initial=lambda x:{k:x[1].get(k) for k in ('pose','case')}
        def outcome(x):
            m=x[2];return (m.get('captures'),m.get('releases'),m.get('settledDeliveries'),m.get('settledAtEnd'),m.get('traceMeetsManipulationCriteria'),x[0]['terminal'])
        matched=(a[0]['actions']==b[0]['actions'] and b[0]['actions']>=count and a[0]['journal']==b[0]['journal'] and outcome(a)==outcome(b) and prefix(a,count)==prefix(b,count)==prefix(c,count) and initial(a)==initial(b)==initial(c) and actor_prefix(root/ARMS[0]/'run',root/ARMS[1]/'run',a[0]['actions']) and actor_prefix(root/ARMS[1]/'run',root/ARMS[2]/'run',count))
        reason=None if matched else 'saved_prefix_or_initial_truth_mismatch'
        if matched and c[0]['searchStep'] is None:reason='search_not_started'
    eligible=bool(matched and reason is None)
    runner.check_manifest(root,manifest)
    return {'status':'diagnostic_only','arms':evidence,'matchedSavedPrefix':matched,'comparisonEligible':eligible,'censorReason':reason,
            'scope':'single previously used simulated case; request records are pre-send intent; actor records are resized and do not authenticate raw camera or execution; search ACK does not independently expose the no-target frame; simulated truth is post-run only; no held-out, causal, physical stop or hardware pickup claim'}


if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit(__doc__)
    try:print(json.dumps(audit(sys.argv[1]),sort_keys=True))
    except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as error:raise SystemExit('Invalid trial: '+str(error))
