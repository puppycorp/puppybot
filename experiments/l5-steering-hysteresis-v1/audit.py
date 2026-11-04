#!/usr/bin/env python3
"""Saved three-arm simulator diagnostic; no policy or GPU execution."""
import importlib.util
import hashlib
import json
import math
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


kick=load('hys_legacy_kick_audit',ROOT/'experiments/l5-steering-kick-v1/audit.py')
plan=load('hys_plan',HERE/'plan.py')


def local_pose(state):
    loc=state.get('localization',{})
    if loc.get('mode')!='wheel-drift' or loc.get('source')!='wheel-steering-command-integration':raise ValueError('nonlocal or missing odometry')
    value=loc.get('pose')
    if not isinstance(value,list) or len(value)!=3 or any(type(x) not in (int,float) or not math.isfinite(x) for x in value):raise ValueError('invalid local pose')
    camera=state.get('camera',{});case=state.get('case',{});frame=state.get('totalSteps');step=state.get('step')
    frame_id=case.get('perception',{}).get('frameId')
    if type(frame) is not int or type(step) is not int or frame<0 or frame!=step or camera.get('pose')!='driving' or camera.get('armSettled') is not True or type(frame_id) is not int or frame_id!=frame:raise ValueError('stale or invalid camera frame')
    return value


def audit_hysteresis(probes,decisions,journal):
    if len(probes)!=300 or len(decisions)!=300 or len(journal)!=300:raise ValueError('incomplete hysteresis stream')
    expected_probe={'step','mode','trigger','cancelled','proposed','applied','feedback','previousApplied','command1000','echo','imageSHA256','hiddenBeforeSHA256','hiddenAfterSHA256'}
    expected_hys={'step','trigger','used','disabled','remainingBefore','remainingAfter','heldSign','carryBefore','contactBefore','kick','applied'}
    previous=[0,0];previous_hidden=None;carry=False;deliveries=0;cancelled=False;trigger=None;used=False;disabled=False;remaining=0;held=0;history=[];events=[];contacts=0;last_step=None
    for index,(row,decision,entry) in enumerate(zip(probes,decisions,journal)):
        if set(row)!=expected_probe or set(entry)!=expected_hys or type(row['step']) is not int or row['step']!=index+1 or type(entry['step']) is not int or entry['step']!=index+1 or type(row['mode']) is not int or row['mode']!=2:raise ValueError('invalid journal shape or sequence')
        proposed=kick.pair(row['proposed'],2);applied=kick.pair(row['applied'],2);kick.pair(row['feedback'],7);kick.pair(row['previousApplied'],2);kick.pair(entry['kick'],2);kick.pair(entry['applied'],2)
        if any(abs(x)>1 for x in proposed+applied) or row['feedback'][:2]!=previous or row['previousApplied']!=row['applied']:raise ValueError('invalid action or previous-action feedback')
        if index:
            drive=decisions[index-1]['state']['controller']['drive'];expected_drive=[kick.bits(drive['leftSpeed']/100),kick.bits(drive['rightSpeed']/100),kick.bits((drive['steeringAngleDeg']-90)/45)]
            if row['feedback'][2:5]!=expected_drive:raise ValueError('wheel feedback differs')
        if row['feedback'][5] not in (kick.bits(0.),kick.bits(1.)) or row['feedback'][6] not in (kick.bits(0.),kick.bits(1.)) or row['feedback'][6]!=kick.bits(float(carry)):raise ValueError('invalid contact or carry feedback')
        contact=row['feedback'][5]==kick.bits(1.);contacts+=int(contact)
        if carry:cancelled=True;disabled=True;remaining=0
        if contact and remaining:disabled=True;remaining=0
        if index==0:trigger=not carry and proposed[0]<=-.5 and proposed[1]<=-.8
        if type(row['trigger']) is not bool or row['trigger']!=trigger or type(row['cancelled']) is not bool or row['cancelled']!=cancelled:raise ValueError('kick state differs')
        kick_words=list(row['proposed'])
        if trigger and not cancelled and index<3:kick_words[0]=kick.sign_flip(kick_words[0])
        armed=False
        if not used and not disabled and not contact and trigger and len(history)>=8:
            recent=history[-8:];signs=[x[0] for x in recent];flips=sum(a*b<0 for a,b in zip(signs,signs[1:]))
            a,b=recent[0][1],recent[-1][1];distance=math.dist(a[:2],b[:2]);turn=abs((b[2]-a[2]+math.pi)%(2*math.pi)-math.pi)
            if abs(distance-.15)<1e-10 or abs(turn-math.pi/4)<1e-10:raise ValueError('odometry threshold numerically ambiguous')
            if all(signs) and flips>=6 and distance<.15 and turn<math.pi/4:
                armed=True;used=True;remaining=2;held=signs[-1];events.append(index+1)
        before=remaining;expected=list(kick_words)
        if remaining:
            speed=kick.value(expected[1]);sign=(speed>0)-(speed<0)
            if sign and sign!=held:expected[1]=kick.sign_flip(expected[1])
            remaining-=1
        checks={'trigger':armed,'used':used,'disabled':disabled,'remainingBefore':before,'remainingAfter':remaining,'heldSign':held,
                'carryBefore':carry,'contactBefore':contact,'kick':kick_words,'applied':expected}
        for name,want in checks.items():
            if type(entry[name]) is not type(want) or entry[name]!=want:raise ValueError('hysteresis journal differs: '+name)
        recorded_action=decision.get('action')
        if not isinstance(recorded_action,list) or len(recorded_action)!=2 or any(type(x) not in (int,float) or not math.isfinite(x) or abs(x)>1 for x in recorded_action):raise ValueError('invalid recorded action')
        if row['applied']!=expected or [kick.bits(x) for x in recorded_action]!=expected:raise ValueError('applied action differs')
        if (not isinstance(row['command1000'],list) or len(row['command1000'])!=2 or any(type(v) is not int for v in row['command1000']) or
                not isinstance(row['echo'],list) or len(row['echo'])!=3 or any(type(v) is not int for v in row['echo'])):raise ValueError('invalid command or echo types')
        command=[round(x*1000) for x in applied]
        throttle=math.trunc(command[1]*60/1000) if abs(command[1])>=80 else 0;echo=[throttle,throttle,90+math.trunc(math.trunc(command[0]/10)*45/100)]
        if row['command1000']!=command or row['echo']!=echo:raise ValueError('command or motor echo differs')
        drive=decision['state']['controller']['drive']
        actual=[drive['leftSpeed'],drive['rightSpeed'],drive['steeringAngleDeg']]
        if any(type(x) is not int for x in actual) or actual!=echo:raise ValueError('recorded drive differs')
        for name in ('imageSHA256','hiddenBeforeSHA256','hiddenAfterSHA256'):
            digest=row[name]
            if not isinstance(digest,str) or len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest):raise ValueError('invalid actor digest')
        if index==0 and row['hiddenBeforeSHA256']!=hashlib.sha256(bytes(512)).hexdigest():raise ValueError('initial recurrent state differs')
        if previous_hidden is not None and row['hiddenBeforeSHA256']!=previous_hidden:raise ValueError('recurrent state discontinuity')
        previous_hidden=row['hiddenAfterSHA256'];previous=expected
        state=decision['state'];pose=local_pose(state)
        if last_step is not None and state['step']!=last_step+10:raise ValueError('stale or skipped simulator ticks')
        last_step=state['step'];speed=kick.value(expected[1]);sign=(speed>0)-(speed<0);history.append((sign,pose))
        task=decision['state']['findReturn'];consumed=task.get('consumedIndex');total=task.get('deliveries')
        if type(consumed) is not int or consumed< -1 or type(total) is not int or total<deliveries or total>deliveries+1:raise ValueError('invalid virtual task transition')
        if not carry and consumed>=0:carry=True
        if total>deliveries:carry=False
        deliveries=total
    return {'hysteresisActivations':events,'kickTriggered':trigger,'contactActions':contacts,
            'scope':'action-word and saved-local-odometry reconstruction; no actor execution or physical-motion attestation'}


def saved_three(control_root,kick_root,hys_root,seed,expected):
    games=[kick.saved_game(path,seed,expected) for path in (control_root,kick_root,hys_root)]
    if any(game['startBytes']!=games[0]['startBytes'] or game['initialBytes']!=games[0]['initialBytes'] for game in games[1:]):raise ValueError('initial placement or state differs')
    control,original,hys=games;baseline=kick.audit_pair((control['probe'],control['decisions']),(original['probe'],original['decisions']))
    journal=[json.loads(line) for line in (Path(hys_root)/'hysteresis.jsonl').read_text().splitlines()]
    third=audit_hysteresis(hys['probe'],hys['decisions'],journal)
    for game,checks in zip(games,(baseline['control'],baseline['intervention'],third)):
        if type(game['result'].get('contactSteps')) is not int or game['result']['contactSteps']!=checks['contactActions']:raise ValueError('contact count differs')
    first=next((i for i,(a,b) in enumerate(zip(original['probe'],hys['probe'])) if a['applied']!=b['applied']),None)
    end=300 if first is None else first+1
    for i in range(end):
        for key in ('proposed','feedback','imageSHA256','hiddenBeforeSHA256','hiddenAfterSHA256'):
            if original['probe'][i][key]!=hys['probe'][i][key]:raise ValueError('kick and hysteresis actor prefix differs')
    return {'seed':seed,'control':control['metrics'],'kick':original['metrics'],'kickHysteresis':hys['metrics'],
            'controlBackForthSteps':control['backForthSteps'],'kickBackForthSteps':original['backForthSteps'],'hysteresisBackForthSteps':hys['backForthSteps'],
            'kickProbe':baseline,'hysteresisProbe':third,'firstHysteresisDifference':None if first is None else first+1,
            'scope':'matched saved actor input digests and simulator metrics; no execution, causality, held-out or physical claim'}


def report(pairs):
    if (not isinstance(pairs,list) or len(pairs)!=12 or any(not isinstance(x,dict) or type(x.get('seed')) is not int for x in pairs) or
            {x['seed'] for x in pairs}!={x['seed'] for x in plan.design()['conditions']}):raise ValueError('all 12 fixed games required')
    for item in pairs:
        for name in ('control','kick','kickHysteresis'):
            metric=item[name];first=metric.get('firstVirtualConsumptionAction')
            if type(metric.get('completedDelivery')) is not bool or (first is not None and (type(first) is not int or not 1<=first<=300)):raise ValueError('invalid game metric')
        for name in ('controlBackForthSteps','kickBackForthSteps','hysteresisBackForthSteps'):
            if type(item.get(name)) is not int or not 0<=item[name]<=300:raise ValueError('invalid oscillation metric')
        activations=item['hysteresisProbe']['hysteresisActivations'];difference=item.get('firstHysteresisDifference')
        if (not isinstance(activations,list) or len(activations)>1 or any(type(x) is not int or not 1<=x<=300 for x in activations) or
                (difference is not None and (type(difference) is not int or not 1<=difference<=300))):raise ValueError('invalid intervention metric')
    totals={}
    for arm,name in (('control','control'),('kick','kick'),('kickHysteresis','kickHysteresis')):
        metrics=[x[name] for x in pairs]
        totals[arm]={'games':len(metrics),'virtualDeliveryGames':sum(int(m['completedDelivery']) for m in metrics),
                     'firstConsumptionBy200':sum(int(m['firstVirtualConsumptionAction'] is not None and m['firstVirtualConsumptionAction']<=200) for m in metrics),
                     'mostlyBackForthGames':sum(int(x[{'control':'controlBackForthSteps','kick':'kickBackForthSteps','kickHysteresis':'hysteresisBackForthSteps'}[name]]*5>300) for x in pairs)}
    totals['hysteresisActivatedGames']=sum(int(bool(x['hysteresisProbe']['hysteresisActivations'])) for x in pairs)
    totals['hysteresisChangedGames']=sum(int(x['firstHysteresisDifference'] is not None) for x in pairs)
    totals['hysteresisNoActivationGames']=len(pairs)-totals['hysteresisActivatedGames']
    return {'schema':'puppybot.l5-steering-hysteresis-comparison.v1','status':'diagnostic_only','pairs':pairs,'totals':totals,
            'scope':'complete training-family simulator cases including no-ops; no prespecified success or promotion rule'}


if __name__=='__main__':raise SystemExit('Disabled; saved-output diagnostics require a separately registered trial.')
