#!/usr/bin/env python3
"""Replay a held-brick return using recorded RGB; not a full mission."""
import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys

sys.path=[p for p in sys.path if Path(p).resolve()!=Path(__file__).resolve().parent]
import cv2
import numpy as np

ROOT=Path(__file__).resolve().parents[2]


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result)
    return result


def restore_map(original,episode,frame):
    evidence=original/'map/episode-0'
    if json.loads((evidence/'map.json').read_text())['frameId']>frame:
        # A still-running recording may have newer evidence. Rebuild only
        # the checkpoint's actual RGB prefix; never feed it future floor.
        mapper=module('checkpoint_mapper',ROOT/'flex/vision/discovery.py')
        requests=sorted((p for p in evidence.glob('input-*.json') if int(p.stem.split('-')[-1])<=frame),key=lambda p:int(p.stem.split('-')[-1]))
        assert requests
        for i,path in enumerate(requests):
            request=json.loads(path.read_text());mapper.run(request,episode)
            for name in ['safe','observed','observed-detail']:
                assert (episode/f'{name}.bin').read_bytes()==(evidence/f'{name}-{request["frameId"]}.bin').read_bytes(), (path,name)
            if i%50==0:print(f'Restored RGB map prefix: {i+1}/{len(requests)}',flush=True)
        return
    episode.mkdir(parents=True)
    for name in ['safe.bin','observed.bin']:shutil.copyfile(evidence/name,episode/name)
    shutil.copyfile(evidence/'map.json',episode/'map.json')
    with np.load(evidence/'evidence.npz') as saved:arrays={key:saved[key] for key in saved.files}
    if 'floorDetail' not in arrays:
        # Recover missing fine floor from the saved real stereo images. A
        # legacy coarse free cell never becomes an invented fine floor prior.
        mapper=module('discovery_mapper',ROOT/'flex/vision/discovery.py')
        floor=np.zeros((1000,1000),np.int32)
        for path in sorted(evidence.glob('input-*.json'),key=lambda p:int(p.stem.split('-')[-1])):
            request=json.loads(path.read_text());assert request['frameId']<=frame
            points,_=mapper.cloud(request['frames'])
            mapper.update(arrays['free'].copy(),arrays['occupied'].copy(),points,request['pose'],arrays['detail'].copy(),arrays['heightSeen'].copy(),arrays['heightConfirmed'].copy(),floor)
        arrays['floorDetail']=floor
    np.savez_compressed(episode/'evidence.npz',**arrays)
    blocked=(arrays['floorDetail']<3)|((arrays['heightConfirmed']!=0)&(arrays['detail']>=2))
    (episode/'observed-detail.bin').write_bytes(blocked.astype(np.uint8).tobytes())


def replay(path,frame,out):
    out.mkdir(parents=True,exist_ok=False)
    previous=False;capture=current=home=None
    for line in path.open():
        state=json.loads(line)
        if home is None and state['discovery']['pickup']['boxLearned']:home=state['localization']['pose']
        if state['gripper']['held'] and not previous:capture=state
        previous=state['gripper']['held']
        if state['step']==frame:current=state;break
    assert capture and current and current['gripper']['held'] and home is not None
    assert capture['gripper']['captureContactMask']==3
    assert current['case']['dockVision']['valid'] and current['case']['dockVision']['stableObservations']>=3
    (out/'replay-input.json').write_text(json.dumps(dict(capture=capture,current=current,home=home),indent=2)+'\n')
    restore_map(path.parent,out/'map/episode-0',frame)
    transit_files=[out/'map/episode-0'/name for name in ('safe.bin','observed.bin','observed-detail.bin','evidence.npz','map.json')]
    transit_hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in transit_files}
    source=(ROOT/'flex/sim/main.flex').read_text().replace('fn main(argc, argv)','fn ps_application_main(argc, argv)')
    source=re.sub(r'^import "([^"]+)";',lambda m:'import '+json.dumps(str(ROOT/'flex/sim'/m[1]))+';',source,flags=re.M)+NATIVE
    def word(value):return hex(struct.unpack('<Q',struct.pack('<d',value))[0])
    def pose(state):
        return ''.join(f'{name}={word(value)};' for name,value in zip(['ps_local_x','ps_local_y','ps_local_heading'],state['localization']['pose']))+''.join(f'store64(ticks+{i*8},{tick});' for i,tick in enumerate(state['ticks']))+'fixture_encoder(ticks);'
    body=current['gripper']['body'];selected=next(i for i,obj in enumerate(current['case']['objects']) if obj['body']==body)
    source=source.replace('HELD_BODY',str(body)).replace('SELECTED',str(selected)).replace('PLACED',str(current['case']['placed'])).replace('GAP',str(round(current['gripper']['openingMm']*1000))).replace('GRASPS',str(current['gripper']['grasps'])).replace('RELEASES',str(current['gripper']['releases']))
    source=source.replace('SPAWN',json.dumps(json.dumps(current['pose']))).replace('CAPTURE',pose(capture)+''.join(f'store64(ps_case_target+{i*8},{word(value)});' for i,value in enumerate(capture['case']['pickupTargetM']))).replace('CURRENT',pose(current))
    def physical_body(identifier,position,quaternion):
        return '{let payload=ph_body(ps_physics,'+str(identifier)+');'+''.join(f'store64(payload+{8+i*8},pb_f64_to_f32({word(value)}));store64(payload+{64+i*8},0);' for i,value in enumerate(position))+f'ph_body_quaternion(ps_physics,{identifier},'+','.join(f'pb_f64_to_f32({word(value)})' for value in quaternion)+');ph_cache_body(payload);}'
    # Restore the complete physical checkpoint, including earlier deliveries.
    # Only fixture setup and the independent judge read these body transforms.
    payload=''
    for i,obj in enumerate(current['case']['objects']):
        payload+=physical_body(obj['body'],obj['position'],obj['quaternion'])
        payload+=f'store64(ps_case_objects+{i*256+192},{int(obj["inside"])});'
    container=current['case']['container'];payload+=physical_body(container['body'],container['position'],container['quaternion'])
    # Observation reports the box's base frame; its physical body is at the
    # centre of mass of the five compound parts, not the bottom surface.
    payload+='{let box=ph_body(ps_physics,'+str(container['body'])+');let axis=0;while axis<3 {store64(box+8+axis*8,pb_f64_to_f32(f64_add(pb_f32_to_f64(load64(box+8+axis*8)),f64_mul(pb_f32_to_f64(load64(box+304+axis*8)),load64(ps_case_bin+72)))));axis=axis+1;}ph_cache_body(box);}'
    source=source.replace('PAYLOAD',payload)
    saved=json.loads((out/'map/episode-0/map.json').read_text())
    source=source.replace('STATS',f'ps_discovery_free={saved["freeCells"]};ps_discovery_occupied={saved["occupiedCells"]};ps_discovery_safe={saved["safeCells"]};ps_discovery_map_frame={saved["frameId"]};')
    centre=current['case']['boxSearch']['centreM'];bearing=math.atan2(home[1]-centre[1],home[0]-centre[0])
    anchor=''.join(f'store64(ps_dock_search_anchor+{i*8},{word(value)});' for i,value in enumerate([*centre,bearing,home[2]]))
    anchor+=''.join(f'store64(ps_house_home+{i*8},{word(value)});' for i,value in enumerate(home))
    source=source.replace('ANCHOR',anchor)
    entry,binary=out/'probe.flex',out/'probe';entry.write_text(source)
    subprocess.run([os.environ.get('FLEXSCRIPT_COMPILER',str(ROOT/'build/flex/pup-compiler')),str(entry),'-o',str(binary)],cwd=ROOT,check=True)
    result=subprocess.run([str(binary),str(out.resolve())],cwd=ROOT,capture_output=True,text=True,timeout=900)
    (out/'run.log').write_text(result.stdout+result.stderr)
    assert result.returncode==0,(result.returncode,result.stderr[-1200:])
    assert all(hashlib.sha256(Path(name).read_bytes()).hexdigest()==digest for name,digest in transit_hashes.items()), 'docking changed the retained transit map'
    (out/'transit-map-audit.json').write_text(json.dumps(dict(passed=True,unchangedFiles=transit_hashes),indent=2)+'\n')
    audit(out/'trace.jsonl')


def audit(path):
    pickup=module('held_geometry',ROOT/'flex/tests/sim-discovery-pickup.py');judge=pickup.HeldGeometry()
    geometry=module('case_geometry',ROOT/'flex/tests/sim-cases.py')
    definition=json.loads((ROOT/'flex/sim/cases/discover-house-blocks-into-box.json').read_text())
    requests=[json.loads(p.read_text()) for p in (path.parent/'map/episode-0').rglob('input-*.json')]
    by_request={request['frameId']:request for request in requests}
    for request in requests:
        assert set(request)=={'schema','frameId','newScan','pose','frames'} and request['schema']=='puppybot.discovery-input.v1'
        assert len(request['frames'])==2
        for frame in request['frames']:assert set(frame)=={'rgb','frameId','calibration','robot'}
    frames={frame['frameId']:frame for request in requests for frame in request['frames']}
    previous=first=last=None;mapping_pose=None;releases=[];checked=set();local_seen=local_unknown=False;camera_frames=0
    for line in path.open():
        state=json.loads(line);case=state['case'];judge.check(state)
        if first is None:first=state
        if state['discovery']['pickup'].get('localDockMap'):
            local_seen=True
            if not state['discovery']['mapFrameId']:
                assert state['discovery']['freeCells']==state['discovery']['occupiedCells']==state['discovery']['safeCells']==0
                local_unknown=True
        assert case['required']==6 and case['navigation']['coverageCount']==0
        assert not state['discovery']['suppliedMap'] and not state['discovery']['worldPoseInput']
        assert not state['physicsFault'] and not state['vehicle']['queryFault'] and not state['collision']['armBlocked'] and not state['blocked']
        if state['discovery']['pickup']['mappingHeldFloor']:
            assert state['gripper']['held']
            if mapping_pose is None:mapping_pose=state['pose']
            assert state['pose']==mapping_pose
        else:mapping_pose=None
        if state['step'] in frames:
            frame=frames[state['step']];assert frame['calibration']==case['perception']['calibration']
            assert np.allclose(frame['robot'],judge.robot_boxes(state),atol=1e-8,rtol=0)
            image=cv2.imread(str(path.parent/'sensor'/f'frame-{state["step"]}.png'));assert image is not None
            assert Path(frame['rgb']).read_bytes()==cv2.cvtColor(image,cv2.COLOR_BGR2RGB).tobytes();checked.add(state['step'])
        if case['perception']['frameId']==state['totalSteps']:
            metadata=json.loads((path.parent/'sensor'/f'frame-{state["totalSteps"]}.png.camera.json').read_text())
            eye_error,axis_error=pickup.camera_frame_error(state,case['perception']['calibration'],metadata)
            assert eye_error<.003 and axis_error<.00003,(state['step'],eye_error,axis_error)
            camera_frames+=1
        if state['step'] in by_request:assert by_request[state['step']]['pose']==state['localization']['pose']
        if previous and previous['gripper']['held'] and not state['gripper']['held']:
            dock=case['dockVision'];assert dock['valid'] and dock['stableObservations']>=3 and dock['frameId']==dock['releaseFrameId']==state['step']
            releases.append(state['step'])
        previous=last=state
    assert first and last and len(releases)==1 and last['case']['placed']==first['case']['placed']+1
    obj=next(obj for obj in last['case']['objects'] if obj['body']==first['gripper']['body'])
    assert obj['inside'];geometry.contained(obj,definition,last['case']['container'])
    expected={obj['body'] for obj in first['case']['objects'] if obj['inside']}|{first['gripper']['body']}
    assert {obj['body'] for obj in last['case']['objects'] if obj['inside']}==expected
    assert last['case']['inside']==last['case']['placed']
    for obj in last['case']['objects']:
        if obj['inside']:geometry.contained(obj,definition,last['case']['container'])
    if first['case']['placed']+1<6:assert not last['discovery']['pickup'].get('localDockMap',False)
    if local_seen:assert local_unknown
    assert checked==set(frames)
    result=dict(schema='puppybot.discovery-dock-replay.v1',checkpointReplayOnly=True,fullMissionVerified=False,passed=True,heldFramesChecked=judge.frames,stereoInputsChecked=len(requests),cameraFramesChecked=camera_frames,releases=releases,usedFreshLocalDockMap=local_seen,localMapInitiallyUnknown=local_unknown,transitMapRestored=not last['discovery']['pickup'].get('localDockMap',False))
    (path.parent/'dock-replay-audit.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))


NATIVE=r'''
fn fixture_encoder(ticks) {
 let i=0;while i<4 {let j=ps_plant+128+i*64;let tick=load64(ticks+i*8);store64(j,tick*1000);store64(j+8,0);store64(j+16,tick);pb_fake_servo(ps_bus,load64(j+24),tick);pb_arm_feedback(ps_robot,i,tick,ps_time);i=i+1;}return 1;
}
fn main(argc,argv) {
 if !pl_init() {return 1;}h_environment(argc,argv);
 if !ps_catalog_load() || !ps_case_load(ps_case_find("discover-house-blocks-into-box")) || !ps_environment_load("build/flex/sim/environments/apartment/apartment.bin") || !ps_model_load("build/flex/sim/puppybot.bin") || !ps_environment_spawn(SPAWN) {return 2;}
 ps_robot=alloc(8192);ps_system=alloc(2048);ps_config=alloc(448);ps_app=alloc(2048);ps_bus=alloc(16384);ps_plant=alloc(2048);ps_trace=alloc(69632);ps_json=alloc(16384);ps_builder=alloc(32);pb_config_default(ps_config);pb_vset(ps_config+40,2,5);
 if !ps_reset() {return 3;}ps_case_phase(0);ps_discovery_phase=0;ps_collect_busy=1;let ticks=alloc(32);
 // Rebuild the controller's grasp estimate from its captured RGB target and
 // encoders. The physical checkpoint below is separate fixture state.
 CAPTURE
 ps_case_attachment_capture();CURRENT
 ps_gripper_body=HELD_BODY;ps_gripper_gap=GAP;ps_gripper_goal=GAP;ps_model_update(ps_robot,ps_plant,ps_x,ps_y,ps_heading,ps_wheel);ps_gripper_frame_update(ps_robot,ps_plant);ps_arm_proxy_update(1);
 let i=0;while i<3 {let body=ph_body(ps_physics,5+i);let k=0;while k<3 {store64(body+8+k*8,pb_f64_to_f32(load64(ps_gripper_targets+i*24+k*8)));store64(body+64+k*8,0);k=k+1;}ph_body_quaternion(ps_physics,5+i,load64(ps_gripper_quat),load64(ps_gripper_quat+8),load64(ps_gripper_quat+16),load64(ps_gripper_quat+24));ph_cache_body(body);i=i+1;}
 PAYLOAD
 store64(ps_physics+32,0);ph_weld(ps_physics,5,HELD_BODY);ps_gripper_held=1;ps_gripper_witnesses=3;ps_gripper_grasps=GRASPS;ps_gripper_releases=RELEASES;ps_case_selected=SELECTED;ps_case_placed=PLACED;ps_house_ready=1;ps_house_returning=1;
 ps_discovery_initialized=1;ps_discovery_root=h_cat(load64(argv+8),"/map");ps_discovery_directory=h_cat(ps_discovery_root,"/episode-0");
 STATS
 if pl_read_file(h_cat(ps_discovery_directory,"/safe.bin"),ps_nav_map,40000)!=40000 || pl_read_file(h_cat(ps_discovery_directory,"/observed.bin"),ps_discovery_observed,40000)!=40000 {return 4;}
 if pl_read_file(h_cat(ps_discovery_directory,"/observed-detail.bin"),ps_discovery_detail,1000000)!=1000000 {return 10;}ps_discovery_detail_ready=1;ps_dock_search_anchor=alloc(32);ps_dock_search_goal=alloc(24);ANCHOR
 ps_dock_search_active=1;ps_dock_search_index=0;ps_dock_search_started=0;ps_brick_output=h_cat(load64(argv+8),"/sensor");ps_render_init(1);
 let speed=ps_trace+1400;store64(speed,200);pr_apply(ps_app,1,speed,ps_time);ps_camera_drive_mode=0;let k=0;while k<4 {store64(ps_pickup_targets+k*8,load64(ticks+k*8));k=k+1;}
 ps_output=syscall(2,h_cat(load64(argv+8),"/trace.jsonl"),0x800c1,384,0,0,0);if ps_output<0 {return 5;}
 i=0;while i<3 {if !ps_tick(0) || !ps_dock_sample() {return 6;}i=i+1;}
 if ps_dock_stable<3 {ps_observation();pl_print(1,ps_json);return 7;}
 if !ps_dock_search_next() {return 8;}
 i=0;while i<30000 && (ps_case_placed==PLACED || (ps_collect_local_map && !ps_case_passed)) && ps_case_stage!=13 {if !ps_tick(0) || ps_arm_blocked || ps_blocked {ps_observation();pl_print(1,ps_json);return 9;}i=i+1;}
 ps_observation();pl_print(1,ps_json);syscall(3,ps_output,0,0,0,0,0);ps_render_close();return ps_case_placed!=PLACED+1;
}
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recorded',type=Path);parser.add_argument('--frame',type=int);parser.add_argument('--output',type=Path);parser.add_argument('--trace',type=Path)
    args=parser.parse_args()
    if args.recorded:
        if args.frame is None or args.output is None:parser.error('--recorded requires --frame and --output')
        replay(args.recorded,args.frame,args.output)
    elif args.trace:audit(args.trace)
    else:parser.error('choose --recorded TRACE --frame STEP --output NEW_DIRECTORY or --trace FILE')


if __name__=='__main__':main()
