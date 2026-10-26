#!/usr/bin/env python3
"""Verify pickup policy isolation from floorplans and audit complete missions."""
import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import subprocess
import struct
import sys
import tempfile

sys.path = [p for p in sys.path if Path(p).resolve() != Path(__file__).resolve().parent]
import numpy as np

ROOT = Path(__file__).resolve().parents[2]


def camera_frame_error(state, calibration, metadata):
    """Compare independent rendered and estimated calibration in body frames."""
    def body_frame(vectors, pose):
        result=np.array(vectors,dtype=float).reshape(4,3).copy();result[0]-=[*pose[:2],0]
        c,s=math.cos(pose[2]),math.sin(pose[2])
        return result@np.array([[c,-s,0],[s,c,0],[0,0,1]])
    actual=body_frame([metadata[key] for key in ('eyeM','forward','right','down')],state['pose'])
    estimated=body_frame(calibration,state['localization']['pose'])
    return float(np.linalg.norm(actual[0]-estimated[0])),float(np.linalg.norm(actual[1:]-estimated[1:],axis=1).max())


def check_scene_start(state, definition):
    """Require the actual original scene, rather than merely six task entries."""
    objects={obj['id']:obj for obj in state['case']['objects']}
    assert set(objects)=={obj['id'] for obj in definition['objects']}
    for expected in definition['objects']:
        actual=objects[expected['id']]
        assert actual['kind']==expected['kind'] and math.dist(actual['initialPosition'],expected['position'])<1e-12
        assert abs(actual['initialYawRad']-math.radians(expected.get('yawDegrees',0)))<1e-12
        assert math.dist(actual['position'][:2],expected['position'][:2])<1e-5
    assert math.dist(state['case']['container']['position'][:2],definition['container']['position'][:2])<1e-4
    assert state['environment']['sensorCameras']==['tcp']


class HeldGeometry:
    """Independent OBB/SAT judge, with CAD data but no native collision cache."""
    def __init__(self):
        data=(ROOT/'build/flex/sim/puppybot.bin').read_bytes();header=struct.unpack_from('<8Q',data)
        self.tcp_group=header[3];self.tcp=np.array(struct.unpack_from('<3d',data,64+header[1]*256));self.frame_yaw=struct.unpack_from('<d',data,64+header[1]*256+64)[0]
        self.groups=[]
        for i in range(header[1]):
            offset=64+i*256;parent,control=struct.unpack_from('<2q',data,offset)
            matrix=np.array(struct.unpack_from('<16d',data,offset+16)).reshape(4,4).T
            axis=np.array(struct.unpack_from('<3d',data,offset+144));scale,zero=struct.unpack_from('<2d',data,offset+168);self.groups.append((parent,control,matrix,axis,scale,zero))
        self.colliders=[struct.unpack_from('<q6d',data,header[7]+i*56) for i in range(header[6])]
        definition=json.loads((ROOT/'flex/sim/cases/discover-house-blocks-into-box.json').read_text())
        self.halves={o['id']:np.array(o['halfSize']) for o in definition['objects']};self.frames=0

    @staticmethod
    def overlap(a,ar,ah,b,br,bh):
        axes=np.vstack((ar.T,br.T,np.cross(ar.T[:,None,:],br.T[None,:,:]).reshape(-1,3)))
        length=np.linalg.norm(axes,axis=1);axes=axes[length>1e-8]/length[length>1e-8,None]
        gaps=(np.abs(axes@ar)*ah).sum(1)+(np.abs(axes@br)*bh).sum(1)-np.abs(axes@(a-b))
        return float(gaps.min())

    def matrices(self,state,pose=None):
        x,y,h=state['pose'] if pose is None else pose;c,s=math.cos(h),math.sin(h)
        rotation=np.array([[c,-s,0],[s,c,0],[0,0,1]]);base=np.eye(4);base[:3,:3]=rotation;base[:3,3]=[x,y,.032];matrices=[]
        for parent,control,matrix,axis,scale,zero in self.groups:
            result=(base if parent<0 else matrices[parent])@matrix
            angle=state['jointAnglesRad'][control] if 0<=control<4 else 0
            if control==5:angle=math.radians(state['controller']['drive']['steeringAngleDeg']-90)
            angle=angle*scale+zero;c,s=math.cos(angle),math.sin(angle);ax,ay,az=axis
            skew=np.array([[0,-az,ay],[az,0,-ax],[-ay,ax,0]]);turn=np.eye(4)
            turn[:3,:3]=np.eye(3)*c+(1-c)*np.outer(axis,axis)+s*skew;result=result@turn
            matrices.append(result)
        return base,matrices

    def robot_boxes(self,state):
        """Reconstruct the mapper's self model from encoders and local pose."""
        pose=state['localization']['pose'];base,matrices=self.matrices(state,pose);boxes=[]
        def box(matrix,centre,half):
            boxes.append(np.r_[matrix[:3,:3]@centre+matrix[:3,3],matrix[:3,:3].T.ravel(),half].tolist())
        for collider in self.colliders:box(matrices[collider[0]],collider[1:4],collider[4:7])
        box(base,[0,0,.058],[.14,.11,.06])
        joints=state['jointAnglesRad'];f64=lambda v:struct.unpack('<d',v.to_bytes(8,'little'))[0]
        yaw=pose[2]+self.frame_yaw+joints[0]+f64(0x3ff70be937858458)
        pitch=joints[1]-joints[2]+joints[3]-f64(0x40095e2a7b8b5d8d)+math.pi/2
        cy,sy,cp,sp=math.cos(yaw),math.sin(yaw),math.cos(pitch),math.sin(pitch)
        gripper=np.eye(4);gripper[:3,:3]=[[-sy,cy*cp,cy*sp],[cy,sy*cp,sy*sp],[0,sp,-cp]]
        gripper[:3,3]=matrices[self.tcp_group][:3,:3]@self.tcp+matrices[self.tcp_group][:3,3]
        box(gripper,[0,0,-.006],[.055,.015,.006])
        for sign in [-1,1]:box(gripper,[sign*(state['gripper']['openingMm']/2000+.005),0,.04],[.005,.015,.04])
        attachment=state.get('discovery',{}).get('pickup',{}).get('attachmentEstimateM')
        if state['gripper']['held'] and attachment is not None:box(gripper,attachment,[.035,.035,.035])
        return boxes

    def check(self,state):
        if not state['gripper']['held']:return
        self.frames+=1;x,y,h=state['pose'];base,matrices=self.matrices(state);rotation=base[:3,:3]
        obj=next(o for o in state['case']['objects'] if o['body']==state['gripper']['body'])
        a=np.array(obj['position']);ah=self.halves[obj['id']];qx,qy,qz,qw=obj['quaternion']
        ar=np.array([[1-2*(qy*qy+qz*qz),2*(qx*qy-qz*qw),2*(qx*qz+qy*qw)],
            [2*(qx*qy+qz*qw),1-2*(qx*qx+qz*qz),2*(qy*qz-qx*qw)],
            [2*(qx*qz-qy*qw),2*(qy*qz+qx*qw),1-2*(qx*qx+qy*qy)]])
        values=[('chassis',self.overlap(a,ar,ah,np.array([x,y,.09]),rotation,np.array([.14,.11,.06])))]
        for i,collider in enumerate(self.colliders):
            matrix=matrices[collider[0]];centre=matrix[:3,:3]@collider[1:4]+matrix[:3,3]
            values.append((i,self.overlap(a,ar,ah,centre,matrix[:3,:3],np.array(collider[4:7]))))
        part,penetration=max(values,key=lambda v:v[1])
        assert penetration<=2e-6, (state['step'],part,penetration,state['case']['phase'])
        if state.get('discovery',{}).get('pickup',{}).get('attachmentEstimateM') is not None:
            # Judge the conservative mapper mask against the actual payload,
            # after expressing both in the arbitrary odometry frame. Truth
            # enters this independent audit only, never the perception input.
            corners=np.array([[i,j,k] for i in [-1,1] for j in [-1,1] for k in [-1,1]])*ah
            corners=corners@ar.T+a
            local=state['localization']['pose'];delta=local[2]-h;c,s=math.cos(delta),math.sin(delta)
            rotation=np.array([[c,-s,0],[s,c,0],[0,0,1]])
            corners=(corners-np.array([x,y,0]))@rotation.T+np.array([*local[:2],0])
            mask=np.array(self.robot_boxes(state)[-1]);relative=(corners-mask[:3])@mask[3:12].reshape(3,3).T
            assert np.max(np.abs(relative)-mask[12:])<=.001,(state['step'],'payload outside encoder/RGB self mask')


def probe():
    source=(ROOT/'flex/sim/main.flex').read_text().replace('fn main(argc, argv)','fn ps_application_main(argc, argv)')
    source=re.sub(r'^import "([^"]+)";',lambda m:'import '+json.dumps(str(ROOT/'flex/sim'/m[1]))+';',source,flags=re.MULTILINE)
    source+=r'''
fn snapshot(out) {
    ps_discovery_raised_only=0;
    if !ps_house_begin(0) || ps_case_stage!=26 {return 0;}
    if !ps_collect_drive_clear(20,0) || !ps_collect_drive_clear(-20,100) {return 0;}
    ps_collect_busy=1;store64(ps_case_target,ps_number(50,100));store64(ps_case_target+8,0);store64(ps_case_target+16,ps_number(12,1000));
    ps_house_returning=3;if ps_nav_clear(ps_number(35,100),0,0) || !ps_nav_clear(ps_number(33,100),ps_number(4,100),0) {return 0;}
    ps_gripper_command(0);if !ps_collect_plan_pick() || ps_gripper_goal!=90000 {return 0;}pb_copy(out,ps_nav_goal,24);store64(out+24,ps_nav_path_count);let i=0;let hash=0;
    while i<ps_nav_path_count {hash=(hash*31+load64(ps_nav_path+i*8))&0xffffffff;i=i+1;}store64(out+32,hash);
    // A separate visual target within the folded-grasp workspace.
    store64(ps_case_target,ps_number(186,1000));store64(ps_case_target+8,ps_number(-4,100));
    if !ps_grasp_solve(ps_case_target,0,-30) {return 0;}pb_copy(out+40,ps_pickup_targets,32);ps_local_camera(out+72);ps_brick_pose=out+72;let self=alloc(24);store64(self,ps_pose_x());store64(self+8,ps_pose_y());store64(self+16,ps_number(12,1000));if !ps_collect_self_target(self) {return 0;}ps_case_attachment_capture();pb_copy(out+168,ps_case_attachment,24);
    let compact=alloc(24);ps_camera_compact_point(compact,ps_pose_heading(),ps_number(16,1000));if !ps_arm_solve(compact,370,75) {return 0;}pb_copy(out+192,ps_pickup_targets,32);
    if !ps_discovery_aim_solve(370,50,0) {return 0;}pb_copy(out+224,ps_pickup_targets,32);
    if !ps_discovery_aim_solve(370,50,1) {return 0;}pb_copy(out+256,ps_pickup_targets,32);
    ps_discovery_robot_frame(0);i=0;hash=0;while i<(ps_arm_collider_count+4)*120 {hash=(hash*31+load8(ps_discovery_robot+i))&0xffffffff;i=i+1;}store64(out+288,hash);
    ps_discovery_raised_only=1;if !ps_discovery_aim() || ps_discovery_phase || ps_discovery_pending_phase!=2 {return 0;}pb_copy(out+296,ps_discovery_pending,32);pb_copy(out+328,ps_pickup_targets,32);pb_copy(out+360,ps_discovery_tuck,32);
    ps_gripper_held=1;ps_discovery_robot_frame(0);i=0;hash=0;
    while i<(ps_arm_collider_count+5)*120 {hash=(hash*31+load8(ps_discovery_robot+i))&0xffffffff;i=i+1;}
    store64(out+392,hash);ps_gripper_held=0;return 1;
}
fn main() {
    if !pl_init() || !ps_catalog_load() || !ps_case_load(ps_case_find("discover-house-blocks-into-box")) || !ps_environment_load("build/flex/sim/environments/apartment/apartment.bin") || !ps_model_load("build/flex/sim/puppybot.bin") {return 1;}
    if !ps_collect_enabled || !ps_discovery_enabled || ps_case_coverage_count {return 2;}
    ps_robot=alloc(8192);ps_system=alloc(2048);ps_config=alloc(448);ps_app=alloc(2048);ps_bus=alloc(16384);ps_plant=alloc(2048);ps_trace=alloc(69632);pb_config_default(ps_config);
    if !ps_reset() || ps_pose_x() || ps_pose_y() || ps_pose_heading() {return 3;}
    let i=0;while i<40000 {if load8(ps_nav_map+i)!=1 || load8(ps_discovery_observed+i)!=1 {return 4;}i=i+1;}
    if ps_collect_drive_clear(20,0) || ps_collect_drive_clear(-20,100) {return 8;}
    // A real wrist observation can be behind the chassis. It still becomes
    // an obstacle after independent frames, without any scene/body lookup.
    ps_brick_records=alloc(128);ps_brick_count=1;store64(ps_brick_records+32,ps_number(-4,10));let sample=0;
    while sample<3 {ps_total=ps_total+1;ps_floor_observe();sample=sample+1;}
    if ps_floor_count!=1 || load64(ps_floor_points+16)!=3 || ps_floor_clear(ps_number(-3,10),0,0) {return 10;}
    ps_floor_reset();ps_brick_count=0;
    // Only this synthetic sensor fixture marks cells observed for the test.
    let y=90;while y<111 {let x=90;while x<121 {store8(ps_nav_map+y*200+x,0);store8(ps_discovery_observed+y*200+x,0);x=x+1;}y=y+1;}
    // The full oriented footprint can fit where the conservative frontier
    // centre grid is inflated. Unknown footprint cells still reject motion.
    store8(ps_nav_map+20100,1);if !ps_collect_drive_clear(20,0) {return 9;}store8(ps_nav_map+20100,0);
    let a=alloc(400);let b=alloc(400);if !snapshot(a) {return 5;}
    ps_environment=1;ps_environment_start=1;ps_environment_count=99999;ps_case_coverage=1;ps_case_coverage_count=99999;
    ps_x=f64_from_i64(77);ps_y=f64_from_i64(-88);ps_heading=PB_PI;
    store64(ps_case_bin,f64_nan());store64(ps_case_bin+8,f64_nan());store64(ps_case_bin+16,f64_nan());
    i=0;while i<ps_case_count {let p=ps_case_objects+i*256+72;store64(p,f64_nan());store64(p+8,f64_nan());store64(p+16,f64_nan());i=i+1;}
    pb_zero(ps_world_matrices,ps_groups*128);pb_zero(ps_gripper_frame,128);pb_zero(ps_tcp,24);
    if !snapshot(b) {return 6;}i=0;while i<400 {if load8(a+i)!=load8(b+i) {return 7;}i=i+1;}
    pl_print(1,"Discovery pickup isolation passed: initially unknown map, no coverage route or spawn prior; corrupted/missing floorplan, object coordinates and world transforms leave navigation, grasp IK, camera and attachment estimate unchanged\n");return 0;
}
'''
    with tempfile.TemporaryDirectory(prefix='discovery-pickup-probe-',dir=ROOT/'build/flex/sim') as temporary:
        p=Path(temporary);entry=p/'probe.flex';binary=p/'probe';entry.write_text(source)
        subprocess.run([os.environ.get('FLEXSCRIPT_COMPILER',str(ROOT/'build/flex/pup-compiler')),str(entry),'-o',str(binary)],cwd=ROOT,check=True)
        subprocess.run([str(binary)],cwd=ROOT,check=True)


def travel_view(directory):
    """A forward wrist observation must interrupt travel before a pickup plan."""
    directory.mkdir(parents=True,exist_ok=False)
    source=(ROOT/'flex/sim/main.flex').read_text().replace('fn main(argc, argv)','fn ps_application_main(argc, argv)')
    source=re.sub(r'^import "([^"]+)";',lambda m:'import '+json.dumps(str(ROOT/'flex/sim'/m[1]))+';',source,flags=re.MULTILINE)
    source+=r'''
fn main(argc,argv) {
    if !pl_init() {return 1;}h_environment(argc,argv);
    if !ps_catalog_load() || !ps_case_load(ps_case_find("discover-house-blocks-into-box")) || !ps_environment_load("build/flex/sim/environments/apartment/apartment.bin") || !ps_model_load("build/flex/sim/puppybot.bin") || !ps_environment_spawn("[0.25,0.15,0]") {return 2;}
    ps_robot=alloc(8192);ps_system=alloc(2048);ps_config=alloc(448);ps_app=alloc(2048);ps_bus=alloc(16384);ps_plant=alloc(2048);ps_trace=alloc(69632);ps_json=alloc(16384);ps_builder=alloc(32);pb_config_default(ps_config);pb_vset(ps_config+40,2,5);
    if !ps_reset() {return 3;}ps_case_phase(0);ps_discovery_phase=0;ps_crumb_enabled=1;ps_collect_map_until=0;ps_discovery_scans=1;ps_render_init(1);ps_brick_output=load64(argv+8);
    if argc>2 {let i=0;while i<ps_case_count {let k=0;while k<3 {store64(ps_case_objects+i*256+160+k*8,f64_from_i64(40));k=k+1;}i=i+1;}}
    let speed=ps_trace+1400;store64(speed,200);pr_apply(ps_app,1,speed,ps_time);ps_gripper_command(0);
    if !ps_camera_drive_target() {return 4;}let i=0;while i<1500 && (!ps_pickup_settled() || ps_gripper_gap!=ps_gripper_goal) {if !ps_tick(0) || ps_arm_blocked {return 5;}i=i+1;}if i==1500 {return 6;}
    // This short observed-floor fixture isolates travel perception; the full
    // mission still starts with an entirely unknown map and no route.
    let y=90;while y<111 {let x=90;while x<121 {store8(ps_nav_map+y*200+x,0);store8(ps_discovery_observed+y*200+x,0);x=x+1;}y=y+1;}
    let goal=ps_number(7,10);if argc>2 {goal=ps_number(14,10);}
    if !ps_nav_plan(goal,0,0) {return 7;}ps_floor_changed=0;ps_discovery_distance=ps_local_distance;ps_discovery_phase=5;
    ps_output=syscall(2,h_cat(ps_brick_output,"/trace.jsonl"),0x800c1,384,0,0,0);if ps_output<0 {return 8;}
    let limit=80;if argc>2 {limit=180;}
    i=0;while i<limit && ps_discovery_phase==5 {if !ps_tick(0) {return 9;}i=i+1;}
    if ps_gripper_held || ps_gripper_grasps || f64_lt(ps_local_distance,ps_number(1,100)) {return 10;}
    if argc>2 {if ps_collect_count || ps_discovery_phase!=5 {return 11;}}
    else {if !ps_collect_count || load64(ps_collect_points+32)<3 || ps_discovery_phase!=1 || ps_case_stage!=26 {return 12;}}
    ps_observation();pl_print(1,ps_json);syscall(3,ps_output,0,0,0,0,0);ps_render_close();return 0;
}
'''
    entry,binary=directory/'probe.flex',directory/'probe';entry.write_text(source)
    subprocess.run([os.environ.get('FLEXSCRIPT_COMPILER',str(ROOT/'build/flex/pup-compiler')),str(entry),'-o',str(binary)],cwd=ROOT,check=True)
    for name,extra in [('visible',[]),('unavailable',['unavailable'])]:
        output=directory/name;output.mkdir()
        result=subprocess.run([str(binary),str(output.resolve()),*extra],cwd=ROOT,capture_output=True,text=True,timeout=120)
        (output/'run.log').write_text(result.stdout+result.stderr)
        assert result.returncode==0,(name,result.returncode,result.stdout[-2500:],result.stderr)
        state=json.loads(result.stdout.splitlines()[-1]);drive=state['controller']['drive']
        assert state['case']['perception']['view']=='tcp' and state['case']['perception']['samples']>=3
        if extra:
            assert not state['discovery']['pickup']['observedTargets'] and drive['active']
            assert state['localization']['estimatedDistanceM']>.95 and state['discovery']['images']==0
            assert state['breadcrumbs']['samples']>5 and state['breadcrumbs']['corrections']>0
        else:
            assert state['discovery']['pickup']['observedTargets'] and not drive['active']
            assert state['case']['phase']=='discovering space' and state['case']['visualRefinements']==0
    print('Travel-view checks passed: a confirmed wrist RGB brick stops driving for a scan; an unavailable target does not interrupt travel or authorize a grasp')


def visual_grasp(directory):
    """Exercise the production approach with actual RGB on a local floor fixture.

    The small observed-floor grid is a synthetic sensor fixture. This does not
    replace the complete unknown-house mission audit below.
    """
    directory.mkdir(parents=True,exist_ok=False)
    source=(ROOT/'flex/sim/main.flex').read_text().replace('fn main(argc, argv)','fn ps_application_main(argc, argv)')
    source=re.sub(r'^import "([^"]+)";',lambda m:'import '+json.dumps(str(ROOT/'flex/sim'/m[1]))+';',source,flags=re.MULTILINE)
    source+=r'''
fn fixture_settled() {let n=0;while n<1500 && !ps_pickup_settled() {if !ps_tick(0) {return 0;}n=n+1;}return n<1500;}
fn main(argc,argv) {
    if !pl_init() {return 1;}h_environment(argc,argv);
    let spawn="[0.764,0.54,0]";if argc>2 {spawn=load64(argv+16);}
    if !ps_catalog_load() || !ps_case_load(ps_case_find("discover-house-blocks-into-box")) || !ps_environment_load("build/flex/sim/environments/apartment/apartment.bin") || !ps_model_load("build/flex/sim/puppybot.bin") || !ps_environment_spawn(spawn) {return 2;}
    ps_robot=alloc(8192);ps_system=alloc(2048);ps_config=alloc(448);ps_app=alloc(2048);ps_bus=alloc(16384);ps_plant=alloc(2048);ps_trace=alloc(69632);ps_json=alloc(16384);ps_builder=alloc(32);pb_config_default(ps_config);pb_vset(ps_config+40,2,5);
    if !ps_reset() {return 3;}ps_case_phase(0);ps_discovery_phase=0;ps_collect_busy=1;ps_gripper_auto=1;ps_house_returning=3;ps_render_init(1);ps_brick_output=load64(argv+8);
    ps_output=syscall(2,h_cat(ps_brick_output,"/trace.jsonl"),0x800c1,384,0,0,0);if ps_output<0 {return 4;}
    let y=90;while y<111 {let x=90;while x<111 {store8(ps_nav_map+y*200+x,0);store8(ps_discovery_observed+y*200+x,0);x=x+1;}y=y+1;}
    let speed=ps_trace+1400;store64(speed,200);pr_apply(ps_app,1,speed,ps_time);
    if !ps_camera_drive_pose(1) || !fixture_settled() || !ps_brick_sample() {return 5;}
    let chosen=-1;let area=0;let i=0;while i<ps_brick_count {let r=ps_brick_records+i*128;let size=load64(r+88);if load64(r+64)==1 && size>area {chosen=i;area=size;}i=i+1;}
    if chosen<0 {return 6;}let record=ps_brick_records+chosen*128;pb_copy(ps_case_target,record+32,24);ps_case_target_colour=load64(record+64);
    // Negative control: make the old target unavailable to colour perception
    // after observing it. Geometry, mass and the remembered target stay intact.
    if argc>3 {i=0;while i<ps_case_count {let k=0;while k<3 {store64(ps_case_objects+i*256+160+k*8,f64_from_i64(40));k=k+1;}i=i+1;}}
    if !ps_collect_staging_inspect() {return 7;}i=0;
    while i<8000 && ps_case_stage!=19 && ps_case_stage!=13 && ps_case_stage!=26 {if !ps_tick(0) {return 8;}i=i+1;}
    if argc>3 {
        if ps_case_stage!=26 || ps_gripper_held || ps_gripper_grasps {return 11;}
        ps_observation();pl_print(1,ps_json);syscall(3,ps_output,0,0,0,0,0);ps_render_close();return 0;
    }
    if ps_case_stage!=19 {ps_observation();pl_print(1,ps_json);return 9;}
    ps_case_phase(0);if !fixture_settled() || !ps_gripper_held {return 10;}
    ps_observation();pl_print(1,ps_json);syscall(3,ps_output,0,0,0,0,0);ps_render_close();return 0;
}
'''
    entry,binary=directory/'probe.flex',directory/'probe';entry.write_text(source)
    subprocess.run([os.environ.get('FLEXSCRIPT_COMPILER',str(ROOT/'build/flex/pup-compiler')),str(entry),'-o',str(binary)],cwd=ROOT,check=True)
    angle=.789367265992572
    rotated=[1.15-.386*math.cos(angle)-.04*math.sin(angle),.5-.386*math.sin(angle)+.04*math.cos(angle),angle]
    for name,extra in [('visible',[]),('rotated',[json.dumps(rotated)]),('unavailable',['[0.764,0.54,0]','unavailable'])]:
        output=directory/name;output.mkdir()
        result=subprocess.run([str(binary),str(output.resolve()),*extra],cwd=ROOT,capture_output=True,text=True,timeout=180)
        (output/'run.log').write_text(result.stdout+result.stderr)
        assert result.returncode==0,(name,result.returncode,result.stdout[-3000:],result.stderr)
        judge=HeldGeometry();last=None
        for line in (output/'trace.jsonl').open():
            state=json.loads(line);judge.check(state);last=state
        if name=='unavailable':
            assert not last['gripper']['held'] and last['gripper']['grasps']==last['case']['visualRefinements']==0
            assert last['case']['phase']=='discovering space'
            print('Unavailable-target control passed: a remembered RGB target cannot authorize a blind approach or grasp')
        else:
            assert last['gripper']['held'] and last['gripper']['captureContactMask']==3 and last['case']['visualRefinements']>=2
            assert last['case']['required']==6 and last['gripper']['maxHeldBallHeight']>.3 and judge.frames>0
            print('Local camera-grasp fixture passed: actual RGB targeting, two visual refinements, production straight approach, bilateral capture and clear loaded transfer')


def audit(path):
    first=last=previous=None;captures=[];releases=[];distance=0;rooms=set();refinement=None;geometry_judge=HeldGeometry()
    camera_frames=set();max_eye_error=max_axis_error=0
    requests=sorted((path.parent/'map/episode-0').rglob('input-*.json'))
    inputs=[json.loads(p.read_text()) for p in requests];needed={r['frameId'] for r in inputs}
    needed.update(f['frameId'] for r in inputs for f in r['frames']);sensor_states={}
    definition=json.loads((ROOT/'flex/sim/cases/discover-house-blocks-into-box.json').read_text())
    for line in path.open():
        state=json.loads(line);case=state['case'];d=state['discovery'];local=state['localization']
        if first is None:first=state;check_scene_start(state,definition)
        if state['totalSteps'] in needed:sensor_states[state['totalSteps']]=(local['pose'],case['perception']['calibration'],geometry_judge.robot_boxes(state))
        if case['perception']['frameId']==state['totalSteps']:
            metadata=json.loads((path.parent/'sensor'/f'frame-{state["totalSteps"]}.png.camera.json').read_text())
            eye_error,axis_error=camera_frame_error(state,case['perception']['calibration'],metadata)
            assert eye_error<.003 and axis_error<.00003,(state['step'],'rendered/estimated camera mismatch',eye_error,axis_error)
            camera_frames.add(state['totalSteps']);max_eye_error=max(max_eye_error,eye_error);max_axis_error=max(max_axis_error,axis_error)
        geometry_judge.check(state)
        assert case['id']=='discover-house-blocks-into-box' and case['controller']=='rgb-discovery'
        assert not d['suppliedMap'] and not d['worldPoseInput'] and case['navigation']['coverageCount']==0
        assert case['navigation']['mapSource']=='tcp-rgb-active-stereo' and local['initialPrior']=='local-origin'
        assert not state['breadcrumbs']['groundHeading']['mapAxisKnown']
        assert not state['physicsFault'] and not state['vehicle']['queryFault']
        x=state['pose'][0];rooms.add(0 if x<3 else 1 if x<4.4 else 2)
        if previous:
            movement=math.dist(state['pose'][:2],previous['pose'][:2]);assert movement<.010001
            drive=previous['controller']['drive'];travelled=(drive['leftSpeed']+drive['rightSpeed'])/20000
            x,y,heading=previous['pose'];heading=(heading-travelled/.18*math.tan(math.radians(drive['steeringAngleDeg']-90))+math.pi)%(2*math.pi)-math.pi
            expected=[x+travelled*math.cos(heading),y+travelled*math.sin(heading),heading]
            if state['blocked']:expected=previous['pose']
            assert math.dist(state['pose'][:2],expected[:2])<1e-7
            assert abs((state['pose'][2]-expected[2]+math.pi)%(2*math.pi)-math.pi)<1e-7
            if state['collision']['armBlocked']:
                assert not state['gripper']['held'] and case['phase']=='discovering space'
                assert state['ticks']==previous['ticks'] and movement<1e-9
            distance+=movement
            if case['visualRefinements']>previous['case']['visualRefinements']:
                assert case['perception']['frameId']==state['totalSteps'] and case['perception']['view']=='tcp'
                refinement=(state['totalSteps'],state['pose'])
            if state['gripper']['held'] and not previous['gripper']['held']:
                assert state['gripper']['captureContactMask']==3 and case['visualRefinements']>0
                assert refinement and state['totalSteps']-refinement[0]<=1500
                assert math.dist(state['pose'],refinement[1])<1e-7
                captures.append(state['gripper']['body'])
            if not state['gripper']['held'] and previous['gripper']['held']:
                dock=case['dockVision'];assert dock['valid'] and dock['frameId']==dock['releaseFrameId']==state['totalSteps'] and dock['stableObservations']>=3
                releases.append(state['step'])
        last=previous=state
    assert first and first['discovery']['freeCells']==0 and first['localization']['pose']==[0,0,0]
    assert len(captures)==len(set(captures))==len(releases)==6
    assert last['case']['passed'] and last['case']['inside']==last['case']['placed']==6 and all(o['inside'] for o in last['case']['objects'])
    counts=[0,0,0]
    for obj in first['case']['objects']:
        x=obj['initialPosition'][0];counts[0 if x<3 else 1 if x<4.4 else 2]+=1
    assert counts==[2,2,2] and rooms=={0,1,2}
    spec=importlib.util.spec_from_file_location('case_geometry',Path(__file__).with_name('sim-cases.py'))
    geometry=importlib.util.module_from_spec(spec);spec.loader.exec_module(geometry)
    definition=json.loads((ROOT/'flex/sim/cases/discover-house-blocks-into-box.json').read_text())
    assert 'navigation' not in definition
    original=json.loads((ROOT/'flex/sim/cases/house-blocks-into-box.json').read_text())
    for field in ('objects','container','gripper','success'):assert definition[field]==original[field],field
    for obj in last['case']['objects']:geometry.contained(obj,definition,last['case']['container'])
    assert inputs
    for request in inputs:
        assert set(request)=={'schema','frameId','newScan','pose','frames'} and request['pose']==sensor_states[request['frameId']][0]
        for frame in request['frames']:
            assert set(frame)=={'rgb','frameId','calibration','robot'} and frame['calibration']==sensor_states[frame['frameId']][1]
            assert np.allclose(frame['robot'],sensor_states[frame['frameId']][2],atol=1e-8,rtol=0)
            assert Path(frame['rgb']).stat().st_size==640*480*3
    assert needed<=camera_frames
    manifest=json.loads((path.parent/'source-manifest.json').read_text())
    assert all(hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest for name,digest in manifest.items()), 'running source/model manifest does not match the audited checkout'
    result=dict(schema='puppybot.discovery-pickup-audit.v1',passed=True,steps=last['step'],distanceM=distance,capturedBodies=captures,releases=releases,scans=last['discovery']['scans'],heldFramesChecked=geometry_judge.frames,stereoInputsChecked=len(inputs),cameraFramesChecked=len(camera_frames),maxCameraEyeErrorM=max_eye_error,maxCameraAxisError=max_axis_error,sourceManifestMatches=True)
    (path.parent/'pickup-audit.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--probe',action='store_true');p.add_argument('--trace',type=Path);p.add_argument('--grasp',type=Path,help='run the local RGB/approach fixture in a new directory');p.add_argument('--travel',type=Path,help='run the forward wrist observation fixture in a new directory');args=p.parse_args()
    if args.probe:probe()
    if args.grasp:visual_grasp(args.grasp)
    if args.travel:travel_view(args.travel)
    if args.trace:audit(args.trace)
    if not args.probe and not args.trace and not args.grasp and not args.travel:p.error('choose --probe, --grasp NEW_DIRECTORY, --travel NEW_DIRECTORY or --trace FILE')


if __name__=='__main__':main()
