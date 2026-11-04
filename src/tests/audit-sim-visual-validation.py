#!/usr/bin/env python3
"""Post-run evaluation of a fixed multi-scene simulated visual-stop suite.

Usage: audit-sim-visual-validation.py SUITE_DIRECTORY
Pose is used only here, never by the actor. Stationarity is not a collision or
obstruction label. Windows within a game are correlated, not independent runs.
"""
import importlib.util
import json
import math
import tempfile
import re
import struct
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec=importlib.util.spec_from_file_location(name,path); result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result


visual = load('visual', ROOT/'flex/tests/audit-sim-visual-stop.py')
hidden = load('hidden', ROOT/'flex/tests/run-physical-hidden-trial.py')
generator = load('generator', ROOT/'flex/tests/prepare-sim-visual-validation.py')


def truth_class(poses):
    first=poses[0]
    displacement=max(math.dist(first[:2], p[:2]) for p in poses)
    turn=max(abs((p[2]-first[2]+math.pi)%(2*math.pi)-math.pi) for p in poses)
    if displacement < .01 and turn < math.radians(2): label='stationary'
    elif displacement >= .05 or turn >= math.radians(10): label='moving'
    else: label='ambiguous'
    return label, displacement, turn


def truth_trace(path):
    poses={}
    with path.open() as stream:
        for line in stream:
            row=json.loads(line); tick=row['totalSteps']; pose=row['pose']
            if (type(tick) is not int or tick<0 or tick in poses or not isinstance(pose,list) or len(pose)!=3
                    or any(type(v) not in (int,float) or not math.isfinite(v) for v in pose)):
                raise ValueError('invalid trace tick or pose')
            poses[tick]=pose
    return poses


def window_truth(poses,start,end):
    try: return truth_class([poses[t] for t in range(start,end+1)])
    except KeyError as error: raise ValueError('missing truth tick') from error


def retrospective_stationary_ticks(poses,lower,end):
    anchor=poses[end]; onset=end
    while onset>lower:
        if onset-1 not in poses: raise ValueError('missing truth tick for stationary timing')
        pose=poses[onset-1]
        if math.dist(anchor[:2],pose[:2])>=.01 or abs((pose[2]-anchor[2]+math.pi)%(2*math.pi)-math.pi)>=math.radians(2): break
        onset-=1
    return end-onset


def periodic_score(image):
    # Diagnostic visual similarity only; camera perspective/occlusion can hide
    # repeated panel geometry. It is not proof that physical movement aliases.
    image=image.astype(np.int16)
    return min(float(np.abs(image[:,:,shift:]-image[:,:,:-shift]).mean()) for shift in range(2,22))


def initial_censor(baseline_rows,enabled_rows,baseline_actions,enabled_actions):
    return (not baseline_rows or not enabled_rows or baseline_rows[0].get('rgbDetections')!=0 or enabled_rows[0].get('rgbDetections')!=0
            or baseline_actions==0 or enabled_actions==0)


def require_arm_environment(env,arm,home,runtime):
    expected={'PATH':'/usr/bin:/bin','HOME':home,'SDL_VIDEODRIVER':'offscreen','LD_LIBRARY_PATH':str(Path(runtime).parent),
              'PUPPYBOT_PHYSICAL_NAV_LIMIT':'90','PUPPYBOT_PHYSICAL_POLL_LIMIT':'1499','PUPPYBOT_SIM_VISUAL_STOP':'1' if arm=='enabled' else '0'}
    if env!=expected: raise ValueError('suite environment differs')


def require_spawn_match(env_file, baseline_rows, enabled_rows, baseline_poses, enabled_poses):
    raw=env_file.read_bytes()
    if raw[:8]!=b'PBENV001' or len(raw)<120: raise ValueError('invalid pinned environment')
    spawn=struct.unpack_from('<3d',raw,96)
    if not all(math.isfinite(v) for v in spawn): raise ValueError('invalid pinned spawn')
    actual=[]
    for rows, poses in ((baseline_rows,baseline_poses),(enabled_rows,enabled_poses)):
        tick=rows[0].get('totalSteps')
        if type(tick) is not int or tick not in poses: raise ValueError('missing initial simulator pose')
        pose=poses[tick];distance=math.dist(spawn[:2],pose[:2]);angle=abs((pose[2]-spawn[2]+math.pi)%(2*math.pi)-math.pi)
        if distance>=.01 or angle>=math.radians(1): raise ValueError('actual initial pose differs from pinned spawn')
        actual.append(pose)
    if math.dist(actual[0][:2],actual[1][:2])>=.01 or abs((actual[0][2]-actual[1][2]+math.pi)%(2*math.pi)-math.pi)>=math.radians(1):
        raise ValueError('paired initial poses differ')
    return actual


def verify_enabled_no_stop(run,result,rows):
    if result.get('handoff') is not False: raise ValueError('handoff is outside no-stop audit')
    actors=run/'actors';names=set()
    for path in actors.iterdir():
        if re.fullmatch(r'actor-\d+\.(rgb|action|hidden|feedback)',path.name): names.add(path.name)
        elif not re.fullmatch(r'visual-\d+\.rgb',path.name): raise ValueError('unexpected enabled actor artifact')
    seqs=sorted(int(re.fullmatch(r'actor-(\d+)\.rgb',name).group(1)) for name in names if re.fullmatch(r'actor-\d+\.rgb',name))
    if len(seqs)!=result.get('policyActions'): raise ValueError('enabled actor count differs from result')
    expected={f'actor-{seq}.{ext}' for seq in seqs for ext in ('rgb','feedback','hidden','action')}
    if names!=expected: raise ValueError('enabled actor artifacts incomplete')
    visuals={p.name for p in actors.glob('visual-*.rgb')}
    if visuals!={f'visual-{seq}.rgb' for seq in seqs}: raise ValueError('enabled visual artifacts incomplete or unsupported')
    for seq in seqs:
        if (actors/f'visual-{seq}.rgb').read_bytes()!=(actors/f'actor-{seq}.rgb').read_bytes(): raise ValueError('visual/policy image mismatch')
    # Reuse the independent protocol/feedback audit without exposing the
    # extra detector files as actor decision artifacts. No source files move.
    with tempfile.TemporaryDirectory(prefix='puppy-actor-audit-') as tmp:
        projection=Path(tmp); target=projection/'actors';target.mkdir()
        for name in names: (target/name).symlink_to((actors/name).absolute())
        hidden.check_actor_inputs(projection,result,rows)
    # Recompute the guard on every fully observed no-stop window. A client
    # that silently continues after a qualifying window is not a valid run.
    for i in range(len(seqs)-9):
        window=seqs[i:i+10]
        if any(b!=a+1 for a,b in zip(window,window[1:])): continue
        ticks=[rows[n-1]['totalSteps'] for n in window]
        if any(b!=a+10 for a,b in zip(ticks,ticks[1:])): continue
        speeds=[round(struct.unpack('<2f',(actors/f'actor-{n}.action').read_bytes())[1]*1000) for n in window[:-1]]
        if any(abs(v)<80 for v in speeds): continue
        images=[np.frombuffer((actors/f'visual-{n}.rgb').read_bytes(),dtype=np.uint8).reshape(3,84,84) for n in window]
        if visual.classify(images): raise ValueError('unreported qualifying visual stop in enabled run')
    return seqs


def censor_count(episodes,reason):
    return sum(any(item.get('reason')==reason for item in episode.get('censoring',[])) for episode in episodes)


def compare_observation_prefix(left,right,seqs):
    differences=[]
    for seq in seqs:
        if seq<1 or seq>len(left) or seq>len(right) or left[seq-1]!=right[seq-1]: differences.append(f'observation-{seq}')
    return differences


def compare_actor_prefix(left,right,seqs,trigger_seq=None):
    differences=[]
    for number in seqs:
        for ext in ('rgb','feedback','hidden','action'):
            name=f'actor-{number}.{ext}'
            if not (left/name).is_file() or not (right/name).is_file() or (left/name).read_bytes()!=(right/name).read_bytes(): differences.append(name)
    if trigger_seq is not None:
        baseline=left/f'actor-{trigger_seq}.rgb';trigger=right/f'visual-{trigger_seq}.rgb'
        if not baseline.is_file() or not trigger.is_file(): differences.append('missing trigger image')
        elif baseline.read_bytes()!=trigger.read_bytes(): differences.append('trigger image differs')
    return differences


def baseline_windows(run, result):
    with (run/'physical-agent.jsonl').open() as stream: rows=[json.loads(line) for line in stream]
    hidden.check_actor_inputs(run,result,rows)
    if result.get('traceSHA256') != visual.sha(run/'trace.jsonl'): raise ValueError('baseline trace hash differs')
    poses=truth_trace(run/'trace.jsonl'); actors=run/'actors'; names=[]
    for path in actors.glob('actor-*.rgb'):
        m=re.fullmatch(r'actor-(\d+)\.rgb',path.name)
        if not m: raise ValueError('invalid actor image name')
        names.append(int(m.group(1)))
    names.sort(); windows=[]
    for i in range(len(names)-9):
        seq=names[i:i+10]
        if any(b!=a+1 for a,b in zip(seq,seq[1:])): continue
        ticks=[rows[x-1]['totalSteps'] for x in seq]
        if any(type(x) is not int for x in ticks) or any(b!=a+10 for a,b in zip(ticks,ticks[1:])): continue
        images=[]; speeds=[]
        for index,number in enumerate(seq):
            data=(actors/f'actor-{number}.rgb').read_bytes()
            if len(data)!=21168: raise ValueError('invalid saved actor image')
            images.append(np.frombuffer(data,dtype=np.uint8).reshape(3,84,84))
            if index<9:
                action=(actors/f'actor-{number}.action').read_bytes()
                if len(action)!=8: raise ValueError('invalid saved action')
                _,speed=struct.unpack('<2f',action)
                if not math.isfinite(speed) or abs(speed)>1: raise ValueError('invalid speed')
                speeds.append(round(speed*1000))
        if any(abs(speed)<80 for speed in speeds): continue
        label, distance, turn=window_truth(poses,ticks[0],ticks[-1]); code=visual.classify(images)
        windows.append({'startTick':ticks[0],'endTick':ticks[-1],'visualCode':code,'truth':label,
                        'maxDisplacementM':distance,'maxHeadingChangeRad':turn,
                        'horizontalPeriodMAD':periodic_score(images[-1])})
    return rows,windows,poses


def audit(root):
    root=Path(root).absolute(); manifest=json.loads((root/'inputs.json').read_text()); conditions=manifest['conditions']
    if manifest.get('schema')!='puppybot.sim-visual-validation.v1' or len(conditions)!=12: raise ValueError('invalid suite manifest')
    suite_runner=load('suite_runner',ROOT/'flex/tests/run-sim-visual-validation.py')
    pilot_receipt, verified_matrix=suite_runner.check_matrix(Path(manifest['pilot']),Path(manifest['matrix']))
    if verified_matrix.get('conditions')!=conditions: raise ValueError('matrix does not match generator-verified conditions')
    expected_names={f'{family}-yaw-{heading:+.2f}' for family in generator.FAMILIES for heading in generator.HEADINGS}|{f'room-{n}' for n in generator.ROOM_LAYOUTS}
    if {c['name'] for c in conditions}!=expected_names or len({c['name'] for c in conditions})!=12: raise ValueError('suite condition set differs')
    files=manifest['files']; paths=manifest['paths']; matrix=Path(manifest['matrix'])
    if paths!=pilot_receipt.get('paths'): raise ValueError('suite runtime differs from validated pilot')
    if not matrix.is_absolute() or str(matrix/'conditions.json') not in files or json.loads((matrix/'conditions.json').read_text()).get('conditions')!=conditions: raise ValueError('frozen condition matrix differs')
    if manifest.get('navigationLimit')!=90 or manifest.get('wallSecondsPerArm')!=300: raise ValueError('suite limits differ')
    for key in ('client','simulator','asset','config','runtime'):
        if not Path(paths[key]).is_absolute() or paths[key] not in files: raise ValueError('missing runtime pin')
    model=Path(paths['model']); model_receipt=json.loads((model/'receipt.json').read_text()); kernels=model_receipt['kernels']
    if not model.is_absolute() or not isinstance(kernels,dict) or len(kernels)<5 or any(Path(k).name!=k for k in kernels): raise ValueError('invalid model receipt')
    needed=[model/'policy',model/'weights.bin',model/'receipt.json']+[model/'kernels'/name for name in kernels]
    if any(str(p) not in files for p in needed): raise ValueError('missing model pin')
    if files[str(model/'policy')]!=model_receipt['binarySHA256'] or files[str(model/'weights.bin')]!=model_receipt['weightsSHA256'] or any(files[str(model/'kernels'/name)]!=v for name,v in kernels.items()): raise ValueError('model receipt mismatch')
    for condition in conditions:
        for filename,key in (('case.json','caseSHA256'),('environment.bin','environmentSHA256')):
            if files.get(str(matrix/condition['name']/filename))!=condition[key]: raise ValueError('missing or mismatched scene pin')
    for name,expected in files.items():
        if not Path(name).is_absolute() or visual.sha(Path(name))!=expected: raise ValueError('pinned suite input changed')
    episodes=[]
    for condition in conditions:
        base=root/'cases'/condition['name']; arms={}; envs={}; censored=[]
        for arm in ('disabled','enabled'):
            status_file=base/arm/'monitor/supervisor-result.json'
            if not status_file.is_file(): censored.append({'arm':arm,'reason':'not_completed_or_not_started'}); continue
            status=json.loads(status_file.read_text())
            if status.get('clientExit')!=0 or status.get('timedOut') is not False or status.get('signal') is not None or status.get('remainingWorkersTerminated') is not False:
                censored.append({'arm':arm,'reason':'supervisor_failure_or_cleanup','supervisor':status})
            elif not (base/arm/'run/result.json').is_file(): censored.append({'arm':arm,'reason':'missing_result'})
        if censored:
            episodes.append({'condition':condition['name'],'family':condition['family'],'status':'censored','censoring':censored}); continue
        for arm in ('disabled','enabled'):
            parent=base/arm; status=json.loads((parent/'monitor/supervisor-result.json').read_text());run=parent/'run'
            if status.get('clientExit')!=0 or status.get('timedOut') is not False or status.get('signal') is not None or status.get('remainingWorkersTerminated') is not False: raise ValueError('unclean suite worker')
            command=json.loads((parent/'command.json').read_text()); expected_command=[paths['client'],paths['simulator'],paths['model'],str(matrix/condition['name']/'case.json'),str(matrix/condition['name']/'environment.bin'),str(run),'--allow-zero-contact']
            if command!=expected_command: raise ValueError('suite command differs from pinned inputs')
            arm_env=json.loads((parent/'environment.json').read_text());envs[arm]=arm_env
            require_arm_environment(arm_env,arm,manifest['home'],paths['runtime'])
            result=json.loads((run/'result.json').read_text()); client=json.loads((run/'inputs.json').read_text())
            if type(result.get('policyActions')) is not int or not 0<=result['policyActions']<=90 or result.get('stoppedRescanEnabled') is not False: raise ValueError('invalid action count or recovery option')
            with (run/'physical-agent.jsonl').open() as stream: journal=[json.loads(line) for line in stream]
            if not journal or journal[-1].get('owner')!=2 or journal[-1].get('ack')!=7 or journal[-1].get('driveCommand')!=[0,0,90]: raise ValueError('missing final simulated stop acknowledgement')
            if result.get('visualStopEnabled') is not (arm=='enabled') or result.get('stopCommandAcknowledged') is not True or result.get('outcome')!='unverified' or result.get('traceSHA256')!=visual.sha(run/'trace.jsonl'): raise ValueError('invalid completed result')
            if client.get('caseSHA256')!=condition['caseSHA256'] or client.get('environmentSHA256')!=condition['environmentSHA256']: raise ValueError('client scene differs from predeclared condition')
            arms[arm]=(run,result,client)
        left=dict(envs['disabled']);right=dict(envs['enabled']);left.pop('PUPPYBOT_SIM_VISUAL_STOP');right.pop('PUPPYBOT_SIM_VISUAL_STOP')
        if left!=right: raise ValueError('paired environment differs beyond opt-in flag')
        a,ar,ai=arms['disabled'];b,br,bi=arms['enabled']
        expected_client={'simulatorSHA256':files[paths['simulator']],'weightsSHA256':files[str(model/'weights.bin')],
                         'policySHA256':files[str(model/'policy')],'receiptSHA256':files[str(model/'receipt.json')],
                         'robotAssetSHA256':files[paths['asset']]}
        if any(ai.get(k)!=v or bi.get(k)!=v for k,v in expected_client.items()): raise ValueError('client provenance differs from pinned bytes')
        for key in ('simulatorSHA256','weightsSHA256','policySHA256','receiptSHA256','robotAssetSHA256','cameraPitch','contactFeedback'):
            if ai.get(key) is None or ai.get(key)!=bi.get(key): raise ValueError('paired client provenance differs')
        with (a/'physical-agent.jsonl').open() as stream: baseline_rows=[json.loads(line) for line in stream]
        with (b/'physical-agent.jsonl').open() as stream: enabled_rows=[json.loads(line) for line in stream]
        if initial_censor(baseline_rows,enabled_rows,ar['policyActions'],br['policyActions']):
            episodes.append({'condition':condition['name'],'family':condition['family'],'status':'censored',
                             'censoring':[{'arm':'either','reason':'initial_detection_or_zero_actions'}]}); continue
        if ar['handoff'] or br['handoff']:
            episodes.append({'condition':condition['name'],'family':condition['family'],'status':'censored',
                             'censoring':[{'arm':'either','reason':'collector_handoff'}]}); continue
        if ar['policyActions']!=90 or (br.get('visualStopReason')==0 and br['policyActions']!=90):
            episodes.append({'condition':condition['name'],'family':condition['family'],'status':'censored',
                             'censoring':[{'arm':'either','reason':'unexpected_early_navigation_end'}]}); continue
        rows,windows,poses=baseline_windows(a,ar)
        enabled_poses=truth_trace(b/'trace.jsonl')
        require_spawn_match(matrix/condition['name']/'environment.bin',rows,enabled_rows,poses,enabled_poses)
        actors_a=a/'actors';actors_b=b/'actors';enabled_actor=[]
        for path in actors_b.glob('actor-*.rgb'):
            match=re.fullmatch(r'actor-(\d+)\.rgb',path.name)
            if not match: raise ValueError('invalid enabled actor image name')
            enabled_actor.append(int(match.group(1)))
        enabled_actor.sort()
        if len(enabled_actor)!=br['policyActions']: raise ValueError('enabled actor count differs from result')
        trigger=None
        if br.get('visualStopReason') in (2,3):
            try: checked=visual.audit(b)
            except (ValueError,KeyError,OSError,TypeError) as error:
                episodes.append({'condition':condition['name'],'family':condition['family'],'status':'censored',
                                 'censoring':[{'arm':'enabled','reason':'visual_stop_audit_unsupported_or_failed','details':str(error)}]}); continue
            trigger=enabled_rows[-2]['sequence']
        elif br.get('visualStopReason')==0:
            try: verify_enabled_no_stop(b,br,enabled_rows)
            except (ValueError,KeyError,OSError,TypeError,struct.error) as error:
                episodes.append({'condition':condition['name'],'family':condition['family'],'status':'censored',
                                 'censoring':[{'arm':'enabled','reason':'no_stop_audit_unsupported_or_failed','details':str(error)}]}); continue
        else: raise ValueError('unknown visual-stop reason')
        differences=compare_actor_prefix(actors_a,actors_b,enabled_actor,trigger)
        observed=enabled_actor+([trigger] if trigger is not None else [])
        differences+=compare_observation_prefix(baseline_rows,enabled_rows,observed)
        if differences or not enabled_actor:
            episodes.append({'condition':condition['name'],'family':condition['family'],'status':'censored',
                             'censoring':[{'arm':'pair','reason':'actor_prefix_or_trigger_image_mismatch','details':differences}]}); continue
        counts={f'{truth}_{status}':0 for truth in ('stationary','moving','ambiguous') for status in ('suspicion','no_suspicion','low_texture')}
        for window in windows:
            label={0:'no_suspicion',2:'suspicion',3:'low_texture'}[window['visualCode']]
            counts[window['truth']+'_'+label]+=1
        status='no_visual_stop'; stop=None
        if br.get('visualStopReason') in (2,3):
            try:
                verified=checked
                label, distance, turn=window_truth(enabled_poses,verified['startTick'],verified['endTick'])
                stop={'reason':verified['reason'],'truth':label,'maximumDisplacementM':distance,'maximumHeadingChangeRad':turn,'endTick':verified['endTick']}
                if label=='stationary':
                    stop['retrospectiveStableTicks']=retrospective_stationary_ticks(enabled_poses,min(enabled_poses),verified['endTick'])
                status='audited_visual_stop'
            except (ValueError,KeyError,OSError,TypeError) as error:
                episodes.append({'condition':condition['name'],'family':condition['family'],'status':'censored',
                                 'censoring':[{'arm':'enabled','reason':'visual_stop_audit_unsupported_or_failed','details':str(error)}]}); continue
        elif br.get('visualStopReason')!=0: raise ValueError('unknown visual-stop reason')
        episodes.append({'condition':condition['name'],'family':condition['family'],'status':'completed','baselineActions':ar['policyActions'],
                         'enabledActions':br['policyActions'],'baselineHandoff':ar['handoff'],'enabledHandoff':br['handoff'],
                         'baselineEnd':'handoff' if ar['handoff'] else ('navigation_limit' if ar['policyActions']==90 else 'other'),
                         'enabledEnd':'handoff' if br['handoff'] else ('visual_stop' if br['visualStopReason'] in (2,3) else ('navigation_limit' if br['policyActions']==90 else 'other')),
                         'actorPrefixMatched':not differences and bool(enabled_actor), 'prefixDifferences':differences,
                         'eligibleWindows':len(windows),'windowCounts':counts,'windows':windows,
                         'stopStatus':status,'stop':stop,
                         'episodeEvidence':{'falseSuspicionOnMovingTruth':bool(stop and stop.get('reason')==2 and stop.get('truth')=='moving'),
                                            'stationaryWindowWithoutSuspicion':counts['stationary_no_suspicion']>0,
                                            'stationaryLowTextureAbstention':counts['stationary_low_texture']>0,
                                            'movingLowTextureAbstention':counts['moving_low_texture']>0}})
    completed=[e for e in episodes if e['status']=='completed']
    metrics={'predeclaredCases':len(conditions),'completedPairs':len(completed),'censoredCases':len(episodes)-len(completed),
             'casesWithoutEligibleWindows':sum(e['eligibleWindows']==0 for e in completed),
             'casesWithEligibleWindows':sum(e['eligibleWindows']>0 for e in completed),
             'casesCensoredForPrefixMismatch':censor_count(episodes,'actor_prefix_or_trigger_image_mismatch'),
             'casesCensoredForUnauditableVisualStop':censor_count(episodes,'visual_stop_audit_unsupported_or_failed'),
             'casesCensoredForUnauditableNoStop':censor_count(episodes,'no_stop_audit_unsupported_or_failed'),
             'casesCensoredForInitialDetectionOrZeroActions':censor_count(episodes,'initial_detection_or_zero_actions'),
             'casesCensoredForHandoff':censor_count(episodes,'collector_handoff'),
             'casesCensoredForUnexpectedEarlyEnd':censor_count(episodes,'unexpected_early_navigation_end'),
             'casesWithFalseVisualSuspicionOnMovingTruth':sum(e['episodeEvidence']['falseSuspicionOnMovingTruth'] for e in completed),
             'casesWithStationaryWindowsWithoutSuspicion':sum(e['episodeEvidence']['stationaryWindowWithoutSuspicion'] for e in completed),
             'casesWithStationaryLowTextureAbstention':sum(e['episodeEvidence']['stationaryLowTextureAbstention'] for e in completed),
             'casesWithMovingLowTextureAbstention':sum(e['episodeEvidence']['movingLowTextureAbstention'] for e in completed),
             'casesWithPeriodicVisualIndicator':sum(any(w['visualCode']!=3 and w['horizontalPeriodMAD']<.25 for w in e['windows']) for e in completed)}
    return {'status':'diagnostic_only','metrics':metrics,'episodes':episodes,
            'thresholds':{'initialSpawnTolerance':'each arm and pair within 1 cm and 1 degree',
                          'stationary':'all ticks <1 cm and <2 degrees from window start',
                          'moving':'at least one tick >=5 cm or >=10 degrees from window start',
                          'ambiguous':'between the stationary and moving definitions',
                          'timing':'retrospective stable pose relative to endpoint; not contact onset or wall-clock',
                          'periodicIndicator':'minimum horizontal 2..21-pixel shift MAD <0.25, not proof of motion alias'},
            'scope':'one training apartment with fixed scene variants and three training rooms; disabled-arm windows are retrospective counterfactual checks, not all realized enabled outcomes; truth is post-run only; overlapping windows correlated; no hardware, held-out, collision, or independent camera authenticity claim'}


if __name__=='__main__':
    if len(sys.argv)!=2: raise SystemExit(__doc__)
    try: print(json.dumps(audit(Path(sys.argv[1])),sort_keys=True))
    except (OSError,ValueError,KeyError,TypeError,struct.error) as error: raise SystemExit(f'Invalid visual validation: {error}')
