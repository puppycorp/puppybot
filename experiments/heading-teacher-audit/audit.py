#!/usr/bin/env python3
"""Audit saved training-layout teacher/student games; no evaluation is run.

Import audit_task(name, teacher_task_root, student_task_root, model_paths) and
audit_pool(task_reports). Callers must independently freeze inputs and verify
monitored execution; this module checks saved artifacts, not execution identity.
"""
import hashlib
import importlib.util
import json
import math
import os
import re
import struct
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
LEVELS=ROOT/'datasets/visual-control/chase-v1/levels'
BASE=7800000
GAMES=32
HORIZON=300
ARMS=('control','treatment')
LAYOUT={1:'in view',2:'just off view',3:'same room out of view',4:'doorway drill',5:'other room'}


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


selection=load('teacher_selection_checks',LEVELS/'audit-selection.py')
qualification=load('teacher_strict_checks',LEVELS/'qualify-selection.py')
heldout=load('teacher_backforth_helper',LEVELS/'audit-heldout.py')


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def finite_vector(value,n):
    return isinstance(value,list) and len(value)==n and all(type(x) in (int,float) and math.isfinite(x) for x in value)


def jsonl(path):
    with path.open() as stream:return [json.loads(line) for line in stream]


def validate_transitions(result,rows,events,directory):
    if len(rows)!=HORIZON or not events or events[0].get('event')!='start' or any(event.get('event')!='delivery' for event in events[1:]):raise ValueError(f'invalid task event sequence: {directory}')
    steps=[event.get('step') for event in events[1:]]
    if (len(steps)!=result['deliveries'] or any(type(t) is not int or not 0<t<=HORIZON for t in steps) or steps!=sorted(set(steps))):raise ValueError(f'invalid delivery event timing: {directory}')
    consumed_any=False
    for action,row in enumerate(rows,1):
        task=row['state']['findReturn'];phase=task.get('phase');index=task.get('consumedIndex');count=task.get('deliveries')
        if (phase not in ('search','return','delivered','docked') or type(index) is not int or index< -1 or (phase=='search')!=(index<0)
                or type(count) is not int or count!=sum(t<=action for t in steps) or (phase=='delivered')!=(action in steps)):
            raise ValueError(f'delivery event disagrees with saved state: {directory}')
        consumed_any=consumed_any or index>=0
    if type(result.get('reaches')) is not int or (result['reaches']>0)!=consumed_any:raise ValueError(f'virtual consumption differs from saved states: {directory}')


def doorway_cases(events,wall):
    cases=completed=zero_time=0
    for i,event in enumerate(events):
        if not finite_vector(event.get('robot'),3) or not finite_vector(event.get('brick'),2):raise ValueError('invalid doorway event pose')
        if (event['robot'][0]>wall)!=(event['brick'][0]>wall):
            cases+=1;completed+=int(i+1<len(events) and events[i+1].get('event')=='delivery')
            zero_time+=int(i+1==len(events) and event.get('step')==HORIZON)
    return cases,completed,cases-completed,zero_time


def doorway(game):
    data=(game['directory']/'scene/environment.bin').read_bytes()
    if len(data)<256 or data[:8]!=b'PBENV001':raise ValueError('invalid doorway environment')
    count=struct.unpack_from('<q',data,8)[0]
    if count<1 or count>128 or len(data)<256+count*128:raise ValueError('invalid doorway collider count')
    walls={struct.unpack_from('<d',data,256+i*128+48)[0] for i in range(count) if data[256+i*128:256+i*128+48].startswith(b'Wall.partition')}
    if len(walls)!=1 or not all(math.isfinite(value) for value in walls):raise ValueError('missing or ambiguous doorway partition')
    return doorway_cases(game['events'],next(iter(walls)))


def validate_shard(part,part_index):
    report=json.loads((part/'report.json').read_text())
    expected={'complete':True,'studentDriven':False,'teacher':'exploring fetch teacher','episodes':8,'trainingEpisodes':7,
              'validationEpisodes':1,'sequenceLength':HORIZON,'seed':BASE+part_index*8,
              'teacherUsesCameraDetections':True,'teacherUsesReferenceGeometryForWallsOnly':True,
              'teacherUsesTargetCoordinates':False,'actorUsesReferencePose':False,'actorUsesTargetCoordinates':False}
    if any(type(report.get(k)) is not type(v) or report.get(k)!=v for k,v in expected.items()):raise ValueError(f'invalid teacher shard report: {part}')
    data=part/'data.bin'
    with data.open('rb') as stream:header=stream.read(32)
    if (len(header)!=32 or header[:8]!=b'PVDATA01' or struct.unpack('<qqq',header[8:])!=(8,7,HORIZON)
            or data.stat().st_size!=32+8*HORIZON*21212 or digest(data)!=report.get('dataSHA256')):raise ValueError(f'invalid teacher data: {part}')
    if {p.name for p in part.glob('expert-*')}!={f'expert-{i}' for i in range(8)}:raise ValueError(f'missing or extra teacher game: {part}')
    log=part.parent/(part.name+'.log')
    if re.search(r'\btimed out\b|\btimeout\b',log.read_text(errors='replace'),re.I):raise ValueError(f'teacher timeout log: {log}')


def teacher_game(directory,seed,level):
    result=json.loads((directory/'result.json').read_text())
    expected={'seed':seed,'game':'fetch','controller':'exploring fetch teacher','steps':HORIZON,'actionSeconds':60,
              'level':level,'blackout':False,'exploreTeacher':True,'sweepTeacher':False,
              'farBricks':False,'suppliedMap':False,'taskEventHint':False,'carryCue':True,'maximumBrickDistanceM':0.35,
              'policyWeightsSHA256':None}
    for key,value in expected.items():
        found=result.get(key)
        if isinstance(value,bool):
            if found is not value:raise ValueError(f'invalid teacher {key}: {directory}')
        elif value is None:
            if key not in result or found is not None:raise ValueError(f'invalid teacher {key}: {directory}')
        elif key=='actionSeconds':
            if type(found) not in (int,float) or found!=value:raise ValueError(f'invalid teacher {key}: {directory}')
        elif type(found) is not type(value) or found!=value:raise ValueError(f'invalid teacher {key}: {directory}')
    if level and result.get('levelPlacement')!=LAYOUT[level]:raise ValueError(f'invalid teacher placement: {directory}')
    if not level and 'levelPlacement' in result:raise ValueError(f'unexpected standard placement: {directory}')
    qualification.reject_interventions(result,directory)
    if type(result.get('deliveries')) is not int or result['deliveries']<0 or type(result.get('backForthSteps')) is not int or not 0<=result['backForthSteps']<=HORIZON:raise ValueError(f'invalid teacher metrics: {directory}')
    if type(result.get('deliveriesPerMinute')) not in (int,float) or not math.isfinite(result['deliveriesPerMinute']) or abs(result['deliveriesPerMinute']-result['deliveries'])>1e-9:raise ValueError(f'invalid teacher delivery rate: {directory}')
    if (type(result.get('reaches')) is not int or result['reaches']<0 or any(type(result.get(k)) is not int or not 0<=result[k]<=HORIZON for k in ('contactSteps','pingPongSteps'))
            or any(type(result.get(k)) not in (int,float) or not math.isfinite(result[k]) or result[k]<0 for k in ('pathM','reachesPerMinute'))
            or abs(result['reachesPerMinute']-result['reaches'])>1e-9):raise ValueError(f'invalid teacher score inputs: {directory}')
    rows=jsonl(directory/'decisions.jsonl');events=jsonl(directory/'chase.jsonl')
    if len(rows)!=HORIZON or not events or events[0].get('event')!='start' or events[0].get('step')!=0:raise ValueError(f'incomplete teacher decisions or start: {directory}')
    first=events[0]
    if not finite_vector(first.get('robot'),3) or not finite_vector(first.get('brick'),2):raise ValueError(f'invalid teacher start: {directory}')
    if any(type(row.get('sequence')) is not int or type(row.get('step')) is not int or not finite_vector(row.get('action'),2) or any(abs(a)>1 for a in row['action']) for row in rows):raise ValueError(f'invalid teacher decision: {directory}')
    deliveries=[event for event in events if event.get('event')=='delivery']
    delivery_steps=[event.get('step') for event in deliveries]
    if (len(events)!=len(deliveries)+1 or len(deliveries)!=result['deliveries'] or any(type(t) is not int or not 0<t<=HORIZON for t in delivery_steps)
            or delivery_steps!=sorted(set(delivery_steps)) or any(not finite_vector(event.get('robot'),3) or not finite_vector(event.get('brick'),2) for event in deliveries)):
        raise ValueError(f'teacher delivery events differ: {directory}')
    validate_transitions(result,rows,events,directory)
    # A delivery causes an extra simulator placement command before the next
    # action, so its following observation sequence legitimately advances by 2.
    if any(rows[i]['step']!=rows[0]['step']+10*i or (i and rows[i]['sequence']!=rows[i-1]['sequence']+1+(i in delivery_steps)) for i in range(HORIZON)):raise ValueError(f'missing or replayed teacher decision: {directory}')
    if heldout.backforth_steps(rows,first['robot'])!=result['backForthSteps']:raise ValueError(f'teacher back-and-forth differs: {directory}')
    log=(directory/'native.log').read_text(errors='replace')
    if re.search(r'\btimed out\b|\btimeout\b',log,re.I):raise ValueError(f'teacher native timeout: {directory}')
    scene=tuple(digest(directory/'scene'/name) for name in ('case.json','environment.bin'))
    return {'result':result,'rows':rows,'events':events,'scene':scene,'directory':directory}


def metrics(games,level):
    values=[game['result'] for game in games.values()];deliveries=sum(row['deliveries'] for row in values)
    delivered=sum(row['deliveries']>0 for row in values);backforth=sum(row['backForthSteps'] for row in values)/(GAMES*HORIZON)
    first_return=sum(any(row['state']['findReturn']['phase']=='return' for row in game['rows']) for game in games.values())
    output={'games':GAMES,'simulatedMinutes':GAMES,'deliveries':deliveries,'deliveriesPerMinute':deliveries/GAMES,
            'gamesWithDelivery':delivered,'fractionGamesWithDelivery':delivered/GAMES,
            'deliveryReliabilityAtLeast90Percent':delivered>=29,'firstReturnGamesProxy':first_return,
            'firstReturnProxyAtLeast90Percent':first_return>=29 if level==3 else None,
            'backForthShare':backforth,'backForthBelow2Percent':backforth<0.02}
    if level==4:
        counts=[doorway(game) for game in games.values()]
        attempts=sum(row[0] for row in counts);completed=sum(row[1] for row in counts)
        output['doorway']={'placements':attempts,'delivered':completed,'rightCensoredAtHorizon':sum(row[2] for row in counts),
                           'zeroTimePlacements':sum(row[3] for row in counts),
                           'deliveredByHorizonFraction':completed/attempts if attempts else None,
                           'scope':'unresolved placements are right-censored, including those created at action 300; delivered-by-horizon fraction includes them'}
    return output


def saved_score(root,player,games):
    score=json.loads((root/('score-'+player+'.json')).read_text())
    rows=[games[BASE+i]['result'] for i in range(GAMES)];ordered=[row['deliveries'] for row in rows];reaches=[row['reaches'] for row in rows]
    for row in rows:
        if (any(type(row.get(k)) is not int or row[k]<0 for k in ('reaches','deliveries','contactSteps','pingPongSteps','backForthSteps'))
                or any(row[k]>HORIZON for k in ('contactSteps','pingPongSteps','backForthSteps'))
                or any(type(row.get(k)) not in (int,float) or not math.isfinite(row[k]) or row[k]<0 for k in ('pathM','reachesPerMinute','deliveriesPerMinute'))
                or abs(row['reachesPerMinute']-row['reaches'])>1e-9 or abs(row['deliveriesPerMinute']-row['deliveries'])>1e-9):
            raise ValueError(f'invalid saved score inputs: {player}')
    expected={'player':player,'games':GAMES,'reaches':sum(reaches),'gamesWithAReach':sum(x>0 for x in reaches),
              'reachesBySeed':reaches,'deliveries':sum(ordered),'gamesWithADelivery':sum(x>0 for x in ordered),'deliveriesBySeed':ordered,
              'gamesMostlyPingPong':sum(row['pingPongSteps']*5>HORIZON for row in rows),
              'gamesMostlyBackForth':sum(row['backForthSteps']*5>HORIZON for row in rows)}
    if any(type(score.get(k)) is not type(v) or score.get(k)!=v for k,v in expected.items()):raise ValueError(f'{player} score totals differ')
    means={'meanDeliveriesPerMinute':sum(ordered)/GAMES,'meanReachesPerMinute':sum(reaches)/GAMES,
           'meanContactSteps':sum(row['contactSteps'] for row in rows)/GAMES,'meanPathM':sum(row['pathM'] for row in rows)/GAMES,
           'meanPingPongShare':sum(row['pingPongSteps']/HORIZON for row in rows)/GAMES,
           'meanBackForthShare':sum(row['backForthSteps']/HORIZON for row in rows)/GAMES}
    if any(type(score.get(k)) not in (int,float) or not math.isfinite(score[k]) or not math.isclose(score[k],v,rel_tol=0,abs_tol=1e-12) for k,v in means.items()):raise ValueError(f'{player} score means differ')


def _audit_task(task_name,teacher_root,student_root,models):
    if task_name=='standard':level=0
    elif task_name in tuple(f'L{i}' for i in range(1,6)):level=int(task_name[1:])
    else:raise ValueError('unknown fixed task')
    if set(models)!=set(ARMS):raise ValueError('expected both model arms')
    teacher_root=Path(teacher_root);student_root=Path(student_root)
    old=os.environ.get('PUPPYBOT_PROJECT');os.environ['PUPPYBOT_PROJECT']=str(ROOT)
    try:students={arm:qualification.strict_games(student_root/arm,Path(models[arm]),level,selection,heldout) for arm in ARMS}
    finally:
        if old is None:os.environ.pop('PUPPYBOT_PROJECT',None)
        else:os.environ['PUPPYBOT_PROJECT']=old
    if any(set(students[arm])!=set(range(BASE,BASE+GAMES)) for arm in ARMS):raise ValueError('student seeds incomplete')
    teacher={};normalized={arm:{} for arm in ARMS}
    for part in range(4):
        folder=teacher_root/'teacher'/str(part);validate_shard(folder,part)
        for index in range(8):
            i=part*8+index;seed=BASE+i;game=teacher_game(folder/f'expert-{index}',seed,level);teacher[seed]=game
            for arm in ARMS:
                student_dir=student_root/arm/str(part)/str(seed)
                if not (student_dir/'result.json').is_file():raise ValueError(f'missing student part/game: {student_dir}')
                result,rows,start,scene=students[arm][seed];initial=game['events'][0]
                if (not finite_vector(start.get('robot'),3) or not finite_vector(start.get('brick'),2) or start.get('event')!='start'
                        or start.get('step')!=0 or start['robot']!=initial['robot'] or start['brick']!=initial['brick'] or tuple(scene)!=game['scene']):
                    raise ValueError(f'unmatched teacher/student initial scene or placement: {task_name} {arm} {seed}')
                events=jsonl(student_dir/'chase.jsonl')
                if not events or events[0]!=start or sum(event.get('event')=='delivery' for event in events)!=result['deliveries']:
                    raise ValueError(f'student event journal changed: {student_dir}')
                if any(not finite_vector(event.get('robot'),3) or not finite_vector(event.get('brick'),2) for event in events if event.get('event') in ('start','delivery')):
                    raise ValueError(f'invalid student event pose: {student_dir}')
                validate_transitions(result,rows,events,student_dir)
                normalized[arm][seed]={'result':result,'rows':rows,'events':events,'directory':student_dir}
    saved_score(teacher_root,'teacher',teacher)
    for arm in ARMS:saved_score(student_root,arm,normalized[arm])
    results={'teacher':metrics(teacher,level),**{arm:metrics(normalized[arm],level) for arm in ARMS}}
    teacher_rate=results['teacher']['deliveriesPerMinute']
    return {'status':'complete_diagnostic','task':task_name,'level':level,'results':results,
            'studentToTeacherRateRatio':{arm:results[arm]['deliveriesPerMinute']/teacher_rate if teacher_rate else None for arm in ARMS},
            'scope':'saved training-layout simulated fetch only; ratio N/A at zero teacher rate; return phase is a proxy; frozen inputs and execution require separate verification; no hardware or held-out proof'}


def audit_task(task_name,teacher_root,student_root,models):
    try:return _audit_task(task_name,teacher_root,student_root,models)
    except (OSError,ValueError,KeyError,TypeError,IndexError,AttributeError,OverflowError,struct.error,json.JSONDecodeError) as error:
        return {'status':'censored','task':task_name,'reason':str(error),'scope':'incomplete or invalid saved evidence; no rates or pass/fail'}


def _audit_pool(reports):
    expected={f'L{i}' for i in range(1,6)}
    if not isinstance(reports,dict) or set(reports)!=expected or any(not isinstance(reports[name],dict) or reports[name].get('status')!='complete_diagnostic' or reports[name].get('task')!=name or type(reports[name].get('level')) is not int or reports[name].get('level')!=int(name[1:]) for name in expected):
        return {'status':'censored','reason':'all five fixed levels must have complete matched reports','scope':'no pooled rate'}
    total={}
    for arm in ('teacher',*ARMS):
        rows=[reports[name]['results'][arm] for name in sorted(expected)]
        if any(type(row.get('games')) is not int or row['games']!=GAMES or type(row.get('simulatedMinutes')) is not int or row['simulatedMinutes']!=GAMES or type(row.get('deliveries')) is not int or row['deliveries']<0 or type(row.get('gamesWithDelivery')) is not int or not 0<=row['gamesWithDelivery']<=GAMES or row['deliveries']<row['gamesWithDelivery'] for row in rows):raise ValueError('invalid pooled metric input')
        deliveries=sum(row['deliveries'] for row in rows);delivered=sum(row['gamesWithDelivery'] for row in rows)
        total[arm]={'games':GAMES*5,'simulatedMinutes':GAMES*5,'deliveries':deliveries,'deliveriesPerMinute':deliveries/(GAMES*5),'gamesWithDelivery':delivered,'fractionGamesWithDelivery':delivered/(GAMES*5)}
    teacher_rate=total['teacher']['deliveriesPerMinute']
    return {'status':'complete_diagnostic','levels':sorted(expected),'results':total,
            'studentToTeacherRateRatio':{arm:total[arm]['deliveriesPerMinute']/teacher_rate if teacher_rate else None for arm in ARMS},
            'scope':'160 matched one-simulated-minute games per arm; zero teacher rate has no ratio; no automatic reliability pass, no held-out or physical claim'}


def audit_pool(reports):
    try:return _audit_pool(reports)
    except (ValueError,KeyError,TypeError,IndexError,AttributeError,OverflowError) as error:return {'status':'censored','reason':str(error),'scope':'no pooled rate'}
