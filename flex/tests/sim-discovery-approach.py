#!/usr/bin/env python3
"""Replay a recorded RGB pickup approach, parking and physical grasp."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import struct
import subprocess

ROOT=Path(__file__).resolve().parents[2]


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result)
    return result


def word(value):return hex(struct.unpack('<Q',struct.pack('<d',value))[0])


def physical_body(obj):
    identifier=obj['body'];source='{let body=ph_body(ps_physics,'+str(identifier)+');'
    for i,value in enumerate(obj['position']):source+=f'store64(body+{8+i*8},pb_f64_to_f32({word(value)}));store64(body+{64+i*8},0);store64(body+{88+i*8},0);'
    source+=f'ph_body_quaternion(ps_physics,{identifier},'+','.join(f'pb_f64_to_f32({word(value)})' for value in obj['quaternion'])+');ph_cache_body(body);'
    if identifier==13:
        # Observations expose the box base; its physical body uses its COM.
        for i in range(3):source+=f'store64(body+{8+i*8},pb_f64_to_f32(f64_add(pb_f32_to_f64(load64(body+{8+i*8})),f64_mul(pb_f32_to_f64(load64(body+{304+i*8})),load64(ps_case_bin+72)))));'
        source+='ph_cache_body(body);'
    return source+'}'


def replay(path,frame,out):
    state=None
    for line in path.open('rb'):
        marker=b'"totalSteps":';start=line.find(marker)+len(marker)
        if start>=len(marker) and int(line[start:line.find(b',',start)])==frame:state=json.loads(line);break
    assert state and not state['gripper']['held'] and state['case']['phase']=='navigating rooms'
    assert state['case']['id']=='discover-house-blocks-into-box' and state['discovery']['pickup']['busy']
    out.mkdir(parents=True,exist_ok=False);(out/'sensor').mkdir()
    (out/'replay-input.json').write_text(json.dumps(state,indent=2)+'\n')
    docking=module('dock_fixture',ROOT/'flex/tests/sim-discovery-dock.py');docking.restore_map(path.parent,out/'map/episode-0',frame)
    source=(ROOT/'flex/sim/main.flex').read_text().replace('fn main(argc, argv)','fn ps_application_main(argc, argv)')
    source=re.sub(r'^import "([^"]+)";',lambda m:'import '+json.dumps(str(ROOT/'flex/sim'/m[1]))+';',source,flags=re.M)+NATIVE
    source=source.replace('SPAWN',json.dumps(json.dumps(state['pose']))).replace('OUT',str(out.resolve()))
    source=source.replace('LOCAL',''.join(f'{name}={word(value)};' for name,value in zip(['ps_local_x','ps_local_y','ps_local_heading'],state['localization']['pose'])))
    encoder=''
    for i,tick in enumerate(state['ticks']):encoder+=f'store64(ps_plant+{128+i*64},{tick*1000});store64(ps_plant+{136+i*64},0);store64(ps_plant+{144+i*64},{tick});pb_fake_servo(ps_bus,load64(ps_plant+{152+i*64}),{tick});pb_arm_feedback(ps_robot,{i},{tick},ps_time);'
    source=source.replace('ENCODER',encoder).replace('GAP',str(round(state['gripper']['openingMm']*1000)))
    for label,value in [('GRASPS',state['gripper']['grasps']),('RELEASES',state['gripper']['releases']),('PLACED',state['case']['placed'])]:source=source.replace(label,str(value))
    # Physical checkpoint data only initializes fixture bodies. Controller
    # targets retain their recorded RGB estimates and their arbitrary frame.
    source=source.replace('BODIES',''.join(physical_body(obj) for obj in [*state['case']['objects'],state['case']['container']]))
    source=source.replace('TARGET',''.join(f'store64(ps_case_target+{i*8},{word(value)});' for i,value in enumerate(state['case']['pickupTargetM'])))
    entry,binary=out/'probe.flex',out/'probe';entry.write_text(source)
    files=[*ROOT.glob('flex/sim/*.flex'),ROOT/'flex/core/kinematics.flex',ROOT/'build/flex/sim/puppybot.bin']
    manifest={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    (out/'source-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    subprocess.run([os.environ.get('FLEXSCRIPT_COMPILER',str(ROOT/'build/flex/pup-compiler')),str(entry),'-o',str(binary)],cwd=ROOT,check=True)
    result=subprocess.run([str(binary)],cwd=ROOT,capture_output=True,text=True,timeout=300)
    (out/'run.log').write_text(result.stdout+result.stderr)
    assert result.returncode==0,(result.returncode,result.stdout[-1500:],result.stderr)
    audit(out/'trace.jsonl',state)


def audit(path,checkpoint):
    pickup=module('pickup_geometry',ROOT/'flex/tests/sim-discovery-pickup.py');judge=pickup.HeldGeometry()
    geometry=module('case_geometry',ROOT/'flex/tests/sim-cases.py')
    definition=json.loads((ROOT/'flex/sim/cases/discover-house-blocks-into-box.json').read_text())
    previous=last=None;capture=[];refinement=None;camera_frames=0
    for line in path.open():
        state=json.loads(line);judge.check(state)
        assert state['case']['required']==6 and state['case']['navigation']['coverageCount']==0
        assert not state['discovery']['suppliedMap'] and not state['discovery']['worldPoseInput']
        assert not state['blocked'] and not state['collision']['armBlocked'] and not state['physicsFault'] and not state['vehicle']['queryFault']
        if state['case']['perception']['frameId']==state['step']:
            metadata=json.loads((path.parent/'sensor'/f'frame-{state["step"]}.png.camera.json').read_text())
            eye,axis=pickup.camera_frame_error(state,state['case']['perception']['calibration'],metadata)
            assert eye<.003 and axis<.00003;camera_frames+=1
        if previous:
            if state['case']['visualRefinements']>previous['case']['visualRefinements']:refinement=(state['step'],state['pose'])
            if state['gripper']['held'] and not previous['gripper']['held']:
                assert refinement and state['step']-refinement[0]<=1500 and state['pose']==refinement[1]
                assert state['gripper']['captureContactMask']==3 and state['case']['visualRefinements']>=2
                capture.append(state['gripper']['body'])
        last=previous=state
    assert camera_frames>=2 and judge.frames>0 and last['gripper']['maxHeldBallHeight']>.3
    assert len(capture)==1 and last['gripper']['held'] and last['case']['phase']=='idle' and last['camera']['armSettled']
    assert last['case']['placed']==checkpoint['case']['placed'] and last['gripper']['grasps']==checkpoint['gripper']['grasps']+1
    prior={obj['body'] for obj in checkpoint['case']['objects'] if obj['inside']}
    for obj in last['case']['objects']:
        if obj['body'] in prior:geometry.contained(obj,definition,last['case']['container'])
    manifest=json.loads((path.parent/'source-manifest.json').read_text())
    assert all(hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest for name,digest in manifest.items())
    result=dict(schema='puppybot.discovery-approach-replay.v1',passed=True,checkpointReplayOnly=True,fullMissionVerified=False,capturedBodies=capture,heldFramesChecked=judge.frames,cameraFramesChecked=camera_frames,priorDeliveriesContained=len(prior),maxHeldHeightM=last['gripper']['maxHeldBallHeight'],sourceManifestMatches=True)
    (path.parent/'approach-audit.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))


NATIVE = r'''

fn main(argc,argv) {
 if !pl_init() {return 1;}h_environment(argc,argv);
 if !ps_catalog_load() || !ps_case_load(ps_case_find("discover-house-blocks-into-box")) || !ps_environment_load("build/flex/sim/environments/apartment/apartment.bin") || !ps_model_load("build/flex/sim/puppybot.bin") || !ps_environment_spawn(SPAWN) {return 1;}
 ps_robot=alloc(8192);ps_system=alloc(2048);ps_config=alloc(448);ps_app=alloc(2048);ps_bus=alloc(16384);ps_plant=alloc(2048);ps_trace=alloc(69632);ps_json=alloc(16384);ps_builder=alloc(32);pb_config_default(ps_config);pb_vset(ps_config+40,2,5);
 if !ps_reset() {return 2;}ps_case_phase(0);ps_discovery_phase=6;ps_collect_busy=1;ps_house_ready=1;ps_gripper_auto=1;ps_house_returning=3;ps_crumb_enabled=0;let i=0;LOCAL
 ENCODER
 ps_gripper_gap=GAP;ps_gripper_goal=GAP;ps_gripper_grasps=GRASPS;ps_gripper_releases=RELEASES;ps_case_placed=PLACED;
 ps_model_update(ps_robot,ps_plant,ps_x,ps_y,ps_heading,ps_wheel);ps_gripper_frame_update(ps_robot,ps_plant);ps_arm_proxy_update(1);
 i=0;while i<3 {let body=ph_body(ps_physics,5+i);let k=0;while k<3 {store64(body+8+k*8,pb_f64_to_f32(load64(ps_gripper_targets+i*24+k*8)));store64(body+64+k*8,0);k=k+1;}ph_body_quaternion(ps_physics,5+i,load64(ps_gripper_quat),load64(ps_gripper_quat+8),load64(ps_gripper_quat+16),load64(ps_gripper_quat+24));ph_cache_body(body);i=i+1;}
 BODIES
 if pl_read_file("OUT/map/episode-0/observed.bin",ps_discovery_observed,40000)!=40000 || pl_read_file("OUT/map/episode-0/safe.bin",ps_nav_map,40000)!=40000 || pl_read_file("OUT/map/episode-0/observed-detail.bin",ps_discovery_detail,1000000)!=1000000 {return 3;}ps_discovery_detail_ready=1;
 TARGET
 ps_output=syscall(2,"OUT/trace.jsonl",0x800c1,384,0,0,0);let goal=alloc(24);
 let planned=ps_collect_plan_pick();pb_copy(goal,ps_nav_goal,24);ps_case_phase(0);let end=alloc(24);ps_nav_end_pose(end);let copy=alloc(24);pb_copy(copy,end,24);
 pl_print(1,"planned/path/parking-clear=");pl_print(1,h_int(planned));pl_print(1,",");pl_print(1,h_int(ps_nav_path_count));pl_print(1,",");pl_print(1,h_int(ps_house_parking_clear(copy,goal)));pl_print(1,"\n");
 if !planned {return 6;}let ticks=0;
 while ticks<2000 && !ps_nav_tick() {if !ps_tick(0) || ps_blocked || ps_arm_blocked {ps_observation();pl_print(1,ps_json);return 4;}ticks=ticks+1;}
 if ticks==2000 {return 7;}ps_house_parking=0;let done=0;
 while ticks<4000 && !done {let result=ps_house_park_to(goal);if result==2 {done=1;}else {if !ps_tick(0) || ps_blocked || ps_arm_blocked || ps_case_stage==13 {ps_observation();pl_print(1,ps_json);return 5;}}ticks=ticks+1;}
 pl_print(1,"actual parked ticks=");pl_print(1,h_int(ticks));pl_print(1,"\n");if !done {return 8;}ps_discovery_phase=0;ps_brick_output="OUT/sensor";ps_render_init(1);
 if !ps_collect_staging_inspect() {return 9;}let grasp_ticks=0;
 while grasp_ticks<10000 && !(ps_gripper_held && ps_case_stage==19) && ps_case_stage!=13 && ps_collect_busy {if !ps_tick(0) || ps_blocked || ps_arm_blocked {ps_observation();pl_print(1,ps_json);return 10;}grasp_ticks=grasp_ticks+1;}
 if !ps_gripper_held || ps_case_stage!=19 {ps_observation();pl_print(1,ps_json);return 11;}
 ps_case_phase(0);let stow_ticks=0;while stow_ticks<1500 && !ps_pickup_settled() {if !ps_tick(0) || ps_blocked || ps_arm_blocked {return 12;}stow_ticks=stow_ticks+1;}
 ps_observation();pl_print(1,ps_json);syscall(3,ps_output,0,0,0,0,0);ps_render_close();return !ps_gripper_held || !ps_pickup_settled();
}

'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recorded',type=Path,required=True);parser.add_argument('--frame',type=int,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();replay(args.recorded,args.frame,args.output)


if __name__=='__main__':main()
