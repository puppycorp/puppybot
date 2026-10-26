#!/usr/bin/env python3
"""Replay a blocked RGB map using completed motion, then fresh wrist stereo."""
import argparse
from collections import deque
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[2]


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result)
    return result


def checkpoint(path,frame,escape_origin_frame=None):
    history=deque(maxlen=64);contacts=deque(maxlen=16);previous=None;state=None;escape_origin=None
    for line in path.open():
        state=json.loads(line)
        if state['step']==escape_origin_frame:escape_origin=state['localization']['pose'][:2]
        if state['discovery']['pickup']['busy']:history.clear()
        if previous:
            drive=previous['controller']['drive'];speed=(drive['leftSpeed']+drive['rightSpeed'])//2
            if previous['discovery']['phase']==5 and not previous['discovery']['pickup']['busy'] and speed and not state['blocked']:
                history.append(dict(speed=speed,steering=(drive['steeringAngleDeg']-90)*100//45,ticks=state['ticks'],before=previous['pose'],after=state['pose'],step=state['step']))
            if state['discovery']['protectiveStops']>previous['discovery']['protectiveStops']:
                contacts.append([*state['localization']['pose'],1 if speed>0 else -1,-math.tan(math.radians(drive['steeringAngleDeg']-90))/.18])
        if state['step']==frame:break
        previous=state
    assert state and state['step']==frame and history
    assert not state['gripper']['held'] and not state['discovery']['pickup']['busy']
    assert state['case']['id']=='discover-house-blocks-into-box'
    assert escape_origin_frame is None or escape_origin is not None
    return state,list(history),list(contacts),escape_origin


def replay(path,frame,out,escape_origin_frame=None,initial_map=None,controller=None):
    state,history,contacts,escape_origin=checkpoint(path,frame,escape_origin_frame);out.mkdir(parents=True,exist_ok=False);(out/'sensor').mkdir()
    (out/'replay-input.json').write_text(json.dumps(dict(state=state,history=history,contacts=contacts,escapeOrigin=escape_origin,initialMap=str(initial_map) if initial_map else None),indent=2)+'\n')
    approach=module('approach_fixture',ROOT/'flex/tests/sim-discovery-approach.py');word=approach.word
    episode=out/'map/episode-0';names=['map.json','evidence.npz','observed.bin','safe.bin','observed-detail.bin']
    if initial_map:
        archived=json.loads((initial_map/'snapshot-manifest.json').read_text());assert archived['frameId']==state['discovery']['mapFrameId']
        assert all(hashlib.sha256((initial_map/name).read_bytes()).hexdigest()==archived['files'][name] for name in names)
        episode.mkdir(parents=True)
        for name in ['observed','safe','observed-detail']:
            assert (initial_map/f'{name}.bin').read_bytes()==(path.parent/f'map/episode-0/{name}-{archived["frameId"]}.bin').read_bytes()
        for name in names:shutil.copyfile(initial_map/name,episode/name)
    else:
        docking=module('dock_fixture',ROOT/'flex/tests/sim-discovery-dock.py');docking.restore_map(path.parent,episode,frame)
    saved=json.loads((episode/'map.json').read_text());assert saved['frameId']==state['discovery']['mapFrameId']
    archive=out/'initial-map';archive.mkdir()
    for name in names:shutil.copyfile(episode/name,archive/name)
    (archive/'snapshot-manifest.json').write_text(json.dumps(dict(frameId=saved['frameId'],files={name:hashlib.sha256((archive/name).read_bytes()).hexdigest() for name in names}),indent=2)+'\n')
    controller=(controller or ROOT/'flex/sim').resolve()
    source=(controller/'main.flex').read_text().replace('fn main(argc, argv)','fn ps_application_main(argc, argv)')
    source=re.sub(r'^import "([^"]+)";',lambda m:'import '+json.dumps(str((controller/m[1]).resolve()))+';',source,flags=re.M)+NATIVE
    source=source.replace('SPAWN',json.dumps(json.dumps(state['pose']))).replace('OUT',str(out.resolve()))
    source=source.replace('LOCAL',''.join(f'{name}={word(value)};' for name,value in zip(['ps_local_x','ps_local_y','ps_local_heading'],state['localization']['pose'])))
    encoder=''
    for i,tick in enumerate(state['ticks']):encoder+=f'store64(ps_plant+{128+i*64},{tick*1000});store64(ps_plant+{136+i*64},0);store64(ps_plant+{144+i*64},{tick});pb_fake_servo(ps_bus,load64(ps_plant+{152+i*64}),{tick});pb_arm_feedback(ps_robot,{i},{tick},ps_time);'
    source=source.replace('ENCODER',encoder)
    source=source.replace('BODIES',''.join(approach.physical_body(obj) for obj in [*state['case']['objects'],state['case']['container']]))
    motion=f'ps_discovery_motion_count={len(history)};ps_discovery_motion_next={len(history)};'
    for i,item in enumerate(history):
        for k,value in enumerate([item['speed'],item['steering'],*item['ticks']]):motion+=f'store64(ps_discovery_motion+{i*48+k*8},{value});'
    source=source.replace('MOTION',motion)
    escape=''
    if escape_origin is not None:
        for position in [escape_origin,state['localization']['pose'][:2]]:
            escape+='ps_discovery_escape_remember('+','.join(word(v) for v in position)+');'
        escape+='if ps_discovery_escape() {return 7;}'
    source=source.replace('ESCAPE_MEMORY',escape)
    records=f'ps_nav_contact_count={len(contacts)};ps_nav_contact_next={len(contacts)};'
    for i,record in enumerate(contacts):
        for k,value in enumerate(record):records+=f'store64(ps_nav_contacts+{i*40+k*8},'+(str(value) if k==3 else word(value))+');'
    source=source.replace('CONTACTS',records)
    dock=state['case']['dockVision'];restored='ps_identity(ps_dock_frame);ps_dock_seen=0;ps_dock_yaw='+word(dock['yawRad'])+';'
    for offset,value in [(0,math.cos(dock['yawRad'])),(8,math.sin(dock['yawRad'])),(32,-math.sin(dock['yawRad'])),(40,math.cos(dock['yawRad'])),(96,dock['positionM'][0]),(104,dock['positionM'][1])]:restored+=f'store64(ps_dock_frame+{offset},{word(value)});'
    source=source.replace('DOCK',restored)
    values=dict(PLACED=state['case']['placed'],GRASPS=state['gripper']['grasps'],RELEASES=state['gripper']['releases'],SCANS=state['discovery']['scans'],STOPS=state['discovery']['protectiveStops'],ARM_STOPS=state['discovery']['armProtectiveStops'],FREE=saved['freeCells'],OCCUPIED=saved['occupiedCells'],SAFE=saved['safeCells'],MAP_FRAME=saved['frameId'])
    # Replace longer tokens first so ARM_STOPS retains its own counter.
    for name,value in sorted(values.items(),key=lambda pair:-len(pair[0])):source=source.replace(name,str(value))
    goals=saved['goals'];goal_data=f'ps_discovery_goal_count={len(goals)};'
    for i,goal in enumerate(goals):
        for k,value in enumerate(goal):goal_data+=f'store64(ps_discovery_goals+{i*24+k*8},{word(value)});'
    source=source.replace('GOALS',goal_data)
    entry,binary=out/'probe.flex',out/'probe';entry.write_text(source)
    worker=controller/'worker.py'
    if not worker.exists():worker=ROOT/'flex/vision/discovery.py'
    files=[*controller.glob('*.flex'),ROOT/'flex/core/kinematics.flex',worker,Path(__file__).resolve(),ROOT/'flex/tests/sim-discovery-approach.py',ROOT/'flex/tests/sim-discovery-dock.py',ROOT/'flex/tests/sim-discovery-pickup.py',ROOT/'flex/tests/sim-cases.py',ROOT/'flex/sim/cases/discover-house-blocks-into-box.json',ROOT/'build/flex/sim/puppybot.bin',ROOT/'build/flex/sim/environments/apartment/apartment.bin']
    manifest={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files};(out/'source-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    subprocess.run([os.environ.get('FLEXSCRIPT_COMPILER',str(ROOT/'build/flex/pup-compiler')),str(entry),'-o',str(binary)],cwd=ROOT,check=True)
    result=subprocess.run([str(binary)],cwd=ROOT,capture_output=True,text=True,timeout=900);(out/'run.log').write_text(result.stdout+result.stderr)
    assert result.returncode==0,(result.returncode,result.stdout[-1500:],result.stderr)
    audit(out/'trace.jsonl',state,history)


def audit(path,checkpoint,history):
    pickup=module('pickup_geometry',ROOT/'flex/tests/sim-discovery-pickup.py');geometry=module('case_geometry',ROOT/'flex/tests/sim-cases.py')
    definition=json.loads((ROOT/'flex/sim/cases/discover-house-blocks-into-box.json').read_text())
    requests=[json.loads(p.read_text()) for p in (path.parent/'map/episode-0').glob('input-*.json')]
    # Prefix reconstruction also saves old requests. Only newly captured
    # replay RGB can authorize movement in the replay's local clock.
    requests=[r for r in requests if all(Path(f['rgb']).resolve().parent==(path.parent/'map/episode-0').resolve() for f in r['frames'])]
    assert requests
    frames={frame['frameId']:frame for request in requests for frame in request['frames']};needed=set(frames);checked=set()
    previous=last=None;retraced=0;retrace_end=None;onward=0.;camera=0;max_error=0.;batches=0;batch_steps=0
    for line in path.open():
        state=json.loads(line);assert not state['blocked'] and not state['collision']['armBlocked'] and not state['physicsFault'] and not state['vehicle']['queryFault']
        if previous is None and state['discovery']['motionHistory']['retraceSteps']:batches=1
        assert not state['discovery']['suppliedMap'] and not state['discovery']['worldPoseInput'] and state['case']['navigation']['coverageCount']==0
        if state['case']['perception']['frameId']==state['step']:
            metadata=json.loads((path.parent/'sensor'/f'frame-{state["step"]}.png.camera.json').read_text());eye,axis=pickup.camera_frame_error(state,state['case']['perception']['calibration'],metadata)
            assert eye<.003 and axis<.00003;camera+=1
        if state['step'] in needed:
            item=frames[state['step']];assert item['calibration']==state['case']['perception']['calibration'];checked.add(state['step'])
        if previous:
            if state['discovery']['motionHistory']['retraceSteps'] and not previous['discovery']['motionHistory']['retraceSteps']:
                if retrace_end is not None:assert any(request['frameId']<state['step'] and request['frames'][0]['frameId']>retrace_end for request in requests)
                batches+=1;batch_steps=0
            drive=previous['controller']['drive'];moving=bool(drive['leftSpeed'] or drive['rightSpeed'])
            if previous['discovery']['motionHistory']['retraceSteps'] and moving:
                batch_steps+=1;assert batch_steps<=20 and retraced<len(history)
                old=history[-1-retraced];assert drive['leftSpeed']==drive['rightSpeed']==-old['speed'] and drive['steeringAngleDeg']==90+old['steering']*45//100
                error=math.dist(state['pose'][:2],old['before'][:2]);assert error<.003;max_error=max(max_error,error);retraced+=1;retrace_end=state['step']
            elif moving and retrace_end is not None:
                assert any(request['frameId']<state['step'] and request['frames'][0]['frameId']>retrace_end for request in requests)
                onward+=math.dist(state['pose'][:2],previous['pose'][:2])
        last=previous=state
    assert 0<retraced<=len(history) and onward>.2 and checked==needed
    assert last['case']['placed']==checkpoint['case']['placed'] and not last['gripper']['held'] and last['discovery']['scans']>checkpoint['discovery']['scans']
    for obj in last['case']['objects']:
        if obj['inside']:geometry.contained(obj,definition,last['case']['container'])
    manifest=json.loads((path.parent/'source-manifest.json').read_text());assert all(hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest for name,digest in manifest.items())
    result=dict(schema='puppybot.discovery-retrace-replay.v1',passed=True,checkpointReplayOnly=True,fullMissionVerified=False,retracedSteps=retraced,retraceBatches=batches,maxRetraceErrorM=max_error,onwardDistanceM=onward,stereoInputsChecked=len(requests),cameraFramesChecked=camera,priorDeliveriesContained=last['case']['inside'],sourceManifestMatches=True)
    (path.parent/'retrace-audit.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))


NATIVE=r'''
fn main(argc,argv) {
 if !pl_init() {return 1;}h_environment(argc,argv);
 if !ps_catalog_load() || !ps_case_load(ps_case_find("discover-house-blocks-into-box")) || !ps_environment_load("build/flex/sim/environments/apartment/apartment.bin") || !ps_model_load("build/flex/sim/puppybot.bin") || !ps_environment_spawn(SPAWN) {return 2;}
 ps_robot=alloc(8192);ps_system=alloc(2048);ps_config=alloc(448);ps_app=alloc(2048);ps_bus=alloc(16384);ps_plant=alloc(2048);ps_trace=alloc(69632);ps_json=alloc(16384);ps_builder=alloc(32);pb_config_default(ps_config);pb_vset(ps_config+40,2,5);
 if !ps_reset() {return 3;}ps_case_phase(26);ps_discovery_phase=6;ps_collect_busy=0;ps_house_ready=1;ps_crumb_enabled=0;ps_gripper_auto=1;LOCAL
 ENCODER
 ps_gripper_gap=0;ps_gripper_goal=0;ps_gripper_grasps=GRASPS;ps_gripper_releases=RELEASES;ps_case_placed=PLACED;
 ps_model_update(ps_robot,ps_plant,ps_x,ps_y,ps_heading,ps_wheel);ps_gripper_frame_update(ps_robot,ps_plant);ps_arm_proxy_update(1);
 let i=0;while i<3 {let body=ph_body(ps_physics,5+i);let k=0;while k<3 {store64(body+8+k*8,pb_f64_to_f32(load64(ps_gripper_targets+i*24+k*8)));store64(body+64+k*8,0);k=k+1;}ph_body_quaternion(ps_physics,5+i,load64(ps_gripper_quat),load64(ps_gripper_quat+8),load64(ps_gripper_quat+16),load64(ps_gripper_quat+24));ph_cache_body(body);i=i+1;}
 BODIES
 if pl_read_file("OUT/map/episode-0/observed.bin",ps_discovery_observed,40000)!=40000 || pl_read_file("OUT/map/episode-0/safe.bin",ps_nav_map,40000)!=40000 || pl_read_file("OUT/map/episode-0/observed-detail.bin",ps_discovery_detail,1000000)!=1000000 {return 4;}ps_discovery_detail_ready=1;
 MOTION
 CONTACTS
 DOCK
 ESCAPE_MEMORY
 ps_discovery_initialized=1;ps_discovery_root="OUT/map";ps_discovery_directory="OUT/map/episode-0";ps_discovery_limit=100;
 ps_discovery_scans=SCANS-1;ps_discovery_stops=STOPS;ps_discovery_arm_stops=ARM_STOPS;ps_discovery_free=FREE;ps_discovery_occupied=OCCUPIED;ps_discovery_safe=SAFE;ps_discovery_map_frame=MAP_FRAME;
 ps_discovery_sector=8;ps_discovery_tilt=1;ps_discovery_full=1;ps_discovery_rescans=2;GOALS
 ps_brick_output="OUT/sensor";ps_render_init(1);ps_output=syscall(2,"OUT/trace.jsonl",0x800c1,384,0,0,0);
 if !ps_discovery_next_sector() || !ps_discovery_retrace {return 5;}
 let resumed=0;let start=0;let ticks=0;
 while ticks<100000 && !(resumed && ps_discovery_scans>SCANS && ps_discovery_phase==1 && f64_gt(start,ps_number(3,10))) {
  let recovering=ps_discovery_retrace;let distance=ps_local_distance;
  if !ps_tick(0) || ps_blocked || ps_arm_blocked || ps_discovery_phase==7 {ps_observation();pl_print(1,ps_json);return 6;}
  if resumed && !recovering {start=f64_add(start,f64_sub(ps_local_distance,distance));}
  if !resumed && !ps_discovery_retrace && ps_discovery_phase==1 {resumed=1;}ticks=ticks+1;
 }
 ps_observation();pl_print(1,ps_json);syscall(3,ps_output,0,0,0,0,0);ps_render_close();return ticks==100000;
}
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--recorded',type=Path,required=True);parser.add_argument('--frame',type=int,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--escape-origin-frame',type=int,help='restore both odometry endpoints of the previous escape and require cycle rejection')
    parser.add_argument('--initial-map',type=Path,help='reuse a hash-checked earlier RGB map archive matching the recorded checkpoint')
    args=parser.parse_args();replay(args.recorded,args.frame,args.output,args.escape_origin_frame,args.initial_map)


if __name__=='__main__':main()
