#!/usr/bin/env python3
"""Replay a first exploration stop with its recorded goal and wrist state."""
from pathlib import Path
import argparse,hashlib,importlib.util,json,math,mmap,re,sys
sys.path = [p for p in sys.path if Path(p).resolve() != Path(__file__).resolve().parent]
import cv2
import numpy as np
ROOT=Path(__file__).resolve().parents[2]


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def audit(path,checkpoint=None,history=None,arm_speed=200):
    path=Path(path);out=path.parent;data=json.loads((out/'replay-input.json').read_text());checkpoint=data['state'];history=data['history'];pickup=module('pickup_audit',ROOT/'flex/tests/sim-discovery-pickup.py');geom=module('case_audit',ROOT/'flex/tests/sim-cases.py');definition=json.loads((ROOT/'flex/sim/cases/discover-house-blocks-into-box.json').read_text());self_model=pickup.HeldGeometry();prev=None;ordinary=0.;backoff=0.;retraced=0;max_error=0.;last_inverse=None;first_ordinary=None;camera=set();states={};guard=[]
    for line in path.open():
        s=json.loads(line);states[s['step']]=s
        assert not s['collision']['armBlocked'] and not s['physicsFault'] and not s['vehicle']['queryFault']
        assert not s['discovery']['suppliedMap'] and not s['discovery']['worldPoseInput'] and s['case']['navigation']['coverageCount']==0
        if s['blocked']:
            assert s['step']==1 and s['pose']==checkpoint['pose'];guard.append(1)
        if prev and s['step']!=prev['step']:
            d=prev['controller']['drive'];ds=(d['leftSpeed']+d['rightSpeed'])/20000;h=(prev['pose'][2]-ds/.18*math.tan(math.radians(d['steeringAngleDeg']-90))+math.pi)%(2*math.pi)-math.pi;xy=[prev['pose'][0]+ds*math.cos(h),prev['pose'][1]+ds*math.sin(h)];assert math.dist(s['pose'][:2],xy)<1e-7;assert abs((s['pose'][2]-h+math.pi)%(2*math.pi)-math.pi)<1e-7
            distance=math.dist(s['pose'][:2],prev['pose'][:2])
            if ds and prev['discovery']['motionHistory']['retraceSteps']:
                old=history[-1-retraced];assert d['leftSpeed']==d['rightSpeed']==-old['speed'] and d['steeringAngleDeg']==90+old['steering']*45//100
                assert s['ticks']==checkpoint['ticks'];error=math.dist(s['pose'][:2],old['before'][:2]);assert error<.003;max_error=max(max_error,error);backoff+=distance;retraced+=1;last_inverse=s['step']
            elif ds:ordinary+=distance;first_ordinary=first_ordinary or s['step']
        elif prev:assert s['pose']==prev['pose']
        if s['case']['perception']['frameId']==s['step'] and s['step'] not in camera:
            meta=json.loads((out/'sensor'/f'frame-{s["step"]}.png.camera.json').read_text());eye,axis=pickup.camera_frame_error(s,s['case']['perception']['calibration'],meta);assert eye<.003 and axis<.00003;camera.add(s['step'])
        prev=s
    assert guard==[1] and 0<retraced<=20 and ordinary>.3 and s['case']['inside']==s['case']['placed']==checkpoint['case']['placed']
    assert s['discovery']['protectiveStops']==checkpoint['discovery']['protectiveStops']+1 and s['discovery']['armProtectiveStops']==checkpoint['discovery']['armProtectiveStops']
    requests=[json.loads(p.read_text()) for p in (out/'map/episode-0').glob('input-*.json')];requests=[r for r in requests if all(Path(f['rgb']).resolve().parent==(out/'map/episode-0').resolve() for f in r['frames'])];assert requests and first_ordinary and last_inverse
    assert any(last_inverse<r['frames'][0]['frameId']<r['frameId']<first_ordinary for r in requests)
    first=min(requests,key=lambda r:r['frameId']);first_state=states[first['frameId']];goal=checkpoint['case']['navigation']['goal'];focus=[goal[0]+.4*math.cos(goal[2]),goal[1]+.4*math.sin(goal[2])];pose=first_state['localization']['pose'];bearing=math.atan2(focus[1]-pose[1],focus[0]-pose[0]);assert abs((first_state['discovery']['scanBearingRad']-bearing+math.pi)%(2*math.pi)-math.pi)<1e-8
    for r in requests:
        assert set(r)=={'schema','frameId','newScan','pose','frames'} and r['pose']==states[r['frameId']]['localization']['pose']
        for f in r['frames']:
            st=states[f['frameId']];assert f['calibration']==st['case']['perception']['calibration'];assert np.allclose(f['robot'],self_model.robot_boxes(st),atol=1e-8,rtol=0)
            rgb=cv2.cvtColor(cv2.imread(str(out/'sensor'/f'frame-{f["frameId"]}.png')),cv2.COLOR_BGR2RGB);assert Path(f['rgb']).read_bytes()==rgb.tobytes()
    for obj in s['case']['objects']:
        if obj['inside']:geom.contained(obj,definition,s['case']['container'])
    manifest=json.loads((out/'source-manifest.json').read_text());assert all(hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest for name,digest in manifest.items())
    report={'passed':True,'checkpointReplayOnly':True,'fullMissionVerified':False,'recordedCheckpoint':checkpoint['step'],'originalDriveStopReproduced':True,'retracedSteps':retraced,'backoffDistanceM':backoff,'maxRetracePositionErrorM':max_error,'ordinaryOnwardDistanceM':ordinary,'wristStayedInRecordedDrivingPostureDuringBackoff':True,'cameraFramesChecked':len(camera),'freshStereoPairs':len(requests),'rgbAndOwnGeometryVerified':True,'recordedScanFocusVerified':True,'discoveryArmSpeedTicksPerSecond':arm_speed,'additionalDriveStops':0,'additionalArmStops':0,'priorDeliveriesContained':s['case']['inside'],'sourceManifestMatches':True};(out/'backoff-audit.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2));return report


TAIL=r"""
 ps_discovery_phase=5;
 pb_drive_steer(pb_robot_drive(ps_robot),SPEED,STEERING,ps_time);
 if !ps_tick(0) || !ps_blocked || ps_discovery_stops!=STOPS+1 || ps_discovery_failed_count!=1 {ps_observation();pl_print(1,ps_json);return 5;}
 let ordinary=0;let n=0;
 while n<60000 && !(f64_gt(ordinary,ps_number(4,10)) && ps_discovery_phase==1 && ps_discovery_scans>SCANS) {
  let recovering=ps_discovery_retrace;let before=ps_local_distance;
  if !ps_tick(0) || ps_blocked || ps_arm_blocked || ps_discovery_phase==7 {ps_observation();pl_print(1,ps_json);return 6;}
  if !recovering {ordinary=f64_add(ordinary,f64_sub(ps_local_distance,before));}n=n+1;
 }
 ps_observation();pl_print(1,ps_json);syscall(3,ps_output,0,0,0,0,0);ps_render_close();return n==60000;
}
"""


def recorded_context(path,frame,state):
    """Recover controller-owned stop history and the seeded odometry state."""
    bad=[];seed=state['localization']['seed'];draws=0
    with path.open('rb') as stream:
        data=mmap.mmap(stream.fileno(),0,access=mmap.ACCESS_READ)
        index=data.find(f'"totalSteps":{frame},'.encode());assert index>=0
        end=data.rfind(b'\n',0,index)+1
        for number in range(1,state['discovery']['armProtectiveStops']+1):
            at=data.find(f'"armProtectiveStops":{number},'.encode(),0,end);assert at>=0
            a=data.rfind(b'\n',0,at)+1;b=data.find(b'\n',at);event=json.loads(data[a:b]);point=event['localization']['pose'][:2]
            if all(math.dist(point,p)>=.3 for p in bad):bad.append(point)
        for match in re.compile(rb'"leftSpeed":(-?\d+),"rightSpeed":(-?\d+)').finditer(data,0,end):
            left,right=map(int,match.groups());assert left==right
            if left:seed=(seed*1664525+1013904223)&0xffffffff;draws+=1
    assert draws or not state['localization']['estimatedDistanceM']
    return bad,seed,draws


def run(path,frame,out,initial_map,plant_state=None):
    builder=module('retrace_fixture',ROOT/'flex/tests/sim-discovery-retrace.py')
    state,history,contacts,escape=builder.checkpoint(path,frame)
    assert state['discovery']['phase']==5 and state['controller']['arm']['mode']=='Idle' and state['camera']['pose']=='driving' and state['camera']['armSettled']
    assert not contacts and not state['discovery']['protectiveStops'] and not state['discovery'].get('failedFrontiers',0)
    assert history[-1]['ticks']==state['ticks'] and escape is None
    builder.checkpoint=lambda *args:(state,history,contacts,None)
    approach=module('approach_fixture',ROOT/'flex/tests/sim-discovery-approach.py');word=approach.word
    bad,random_state,draws=recorded_context(path,frame,state)
    # The UI speed is a selection value; autonomy sets the arm directly.
    # Restore its declared setting from the archived controller source.
    speed_source=path.parent/'source-snapshot/flex/sim/collect.flex'
    manifest=json.loads((path.parent/'source-manifest.json').read_text())
    expected=next(v for k,v in manifest.items() if str(k).endswith('flex/sim/collect.flex'))
    assert hashlib.sha256(speed_source.read_bytes()).hexdigest()==expected
    section=speed_source.read_text().split('fn ps_collect_search_begin()',1)[1].split('fn ps_collect_attention()',1)[0]
    arm_speed=int(re.search(r'store64\(speed,\s*(\d+)\)',section)[1])
    positions=[t*1000 for t in state['ticks']]
    if plant_state:
        plant=json.loads(plant_state.read_text());assert plant['step']==frame and plant['velocityTicksPerSecond']==[0]*4
        positions=plant['positionsMilliTick'];assert [p//1000 for p in positions]==state['ticks']
    native=builder.NATIVE[:builder.NATIVE.index(' if !ps_discovery_next_sector()')]
    assert native.count('ps_discovery_scans=SCANS-1;')==1
    native=native.replace('ps_discovery_scans=SCANS-1;','ps_discovery_scans=SCANS;')
    native=native.replace('ENCODER','ENCODER\n'+''.join(f'store64(ps_plant+{128+i*64},{v});' for i,v in enumerate(positions)))
    native+=''.join(f'store64(ps_nav_goal+{i*8},{word(v)});' for i,v in enumerate(state['case']['navigation']['goal']))
    native+=f'ps_nav_path_count={state["case"]["navigation"]["pathCount"]};ps_nav_path_index={state["case"]["navigation"]["pathIndex"]};'
    native+='ps_discovery_frontier_focus(ps_nav_goal);ps_camera_drive_mode=1;'
    native+=f'ps_local_random={random_state};ps_local_distance={word(state["localization"]["estimatedDistanceM"])};'
    native+=f'ps_discovery_bad_count={len(bad)};ps_discovery_bad_next={len(bad)};'
    for i,point in enumerate(bad):
        for k,value in enumerate(point):native+=f'store64(ps_discovery_bad_poses+{i*16+k*8},{word(value)});'
    native+=f'let rate=ps_trace+1400;store64(rate,{arm_speed});if pr_apply(ps_app,1,rate,ps_time)||pb_a(ps_robot,PB_A_SPEED)!={arm_speed}{{return 15;}}'
    drive=state['controller']['drive'];assert drive['leftSpeed']==drive['rightSpeed']
    steering=(drive['steeringAngleDeg']-90)*100//45;assert 90+steering*45//100==drive['steeringAngleDeg']
    builder.NATIVE=native+TAIL.replace('SPEED',str(drive['leftSpeed'])).replace('STEERING',str(steering))
    builder.audit=lambda path,checkpoint,history:audit(path,checkpoint,history,arm_speed)
    try:builder.replay(path,frame,out,initial_map=initial_map)
    finally:
        if out.exists():
            setup=dict(frame=frame,selectedGoal=state['case']['navigation']['goal'],scanFocusRestored=True,armSpeed=arm_speed,armSpeedSource=str(speed_source),badViewPoses=bad,odometryRandom=random_state,odometryDraws=draws,positionsMilliTick=positions,exactFractionalPlant=plant_state is not None,source=str(path),fullMissionVerified=False)
            (out/'backoff-setup.json').write_text(json.dumps(setup,indent=2)+'\n')
            files=[Path(__file__).resolve(),out/'probe.flex']
            (out/'setup-source-manifest.json').write_text(json.dumps({str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files if p.exists()},indent=2)+'\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recorded',type=Path,required=True);parser.add_argument('--frame',type=int,required=True)
    parser.add_argument('--initial-map',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--plant-state',type=Path,help='optional reconstructed stationary actuator fractions')
    args=parser.parse_args();run(args.recorded,args.frame,args.output,args.initial_map,args.plant_state)


if __name__=='__main__':main()
