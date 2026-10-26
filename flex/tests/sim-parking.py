#!/usr/bin/env python3
"""Verify mapped parking corrections and replay a recorded docking failure."""
import argparse
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[2]


def source():
    text=(ROOT/'flex/sim/main.flex').read_text().replace('fn main(argc, argv)','fn ps_application_main(argc, argv)')
    text=re.sub(r'^import "([^"]+)";',lambda m:'import '+json.dumps(str(ROOT/'flex/sim'/m[1]))+';',text,flags=re.MULTILINE)
    return text+r'''
fn fixture_pose(data,offset,ticks) {
    ps_local_x=load64(data+offset);ps_local_y=load64(data+offset+8);ps_local_heading=load64(data+offset+16);let i=0;
    while i<4 {let tick=load64(data+ticks+i*8);store64(ps_plant+128+i*64,tick*1000);store64(ps_plant+128+i*64+16,tick);pb_arm_feedback(ps_robot,i,tick,ps_time);i=i+1;}return 1;
}
fn fixture_actions() {
    if !ps_environment_spawn("[1.5,0,0]") {return 0;}
    let action=0;while action<12 {
        if !ps_reset() {return 0;}ps_case_phase(0);ps_discovery_phase=0;ps_collect_busy=1;ps_crumb_enabled=0;
        let r=ps_nav_actions+action*128;let i=0;pb_drive_steer(pb_robot_drive(ps_robot),load64(r+8)*load64(r+112),load64(r),ps_time);
        while i<20 {if !ps_tick(0) || ps_blocked {return 0;}i=i+1;}
        if f64_gt(f64_magnitude(f64_sub(f64_sub(ps_x,ps_number(15,10)),load64(r+88))),ps_number(1,1000000)) || f64_gt(f64_magnitude(f64_sub(ps_y,load64(r+96))),ps_number(1,1000000)) || f64_gt(f64_magnitude(pb_wrap_pi(f64_sub(ps_heading,load64(r+16)))),ps_number(1,1000000)) {return 0;}
        action=action+1;
    }return 1;
}
fn fixture_replay(argv) {
    let data=alloc(233);if pl_read_file(load64(argv+8),data,232)!=232 {return 10;}
    fixture_pose(data,0,48);pb_copy(ps_case_target,data+24,24);ps_case_attachment_capture();fixture_pose(data,80,104);
    ps_case_placed=load64(data+160);ps_gripper_held=1;ps_collect_busy=1;ps_house_ready=1;ps_house_returning=1;ps_dock_seen=0;ps_dock_valid=1;ps_dock_stable=3;
    ps_identity(ps_dock_frame);ps_dock_yaw=load64(data+152);store64(ps_dock_frame,f64_cos(ps_dock_yaw));store64(ps_dock_frame+8,f64_sin(ps_dock_yaw));store64(ps_dock_frame+32,pb_neg(f64_sin(ps_dock_yaw)));store64(ps_dock_frame+40,f64_cos(ps_dock_yaw));store64(ps_dock_frame+96,load64(data+136));store64(ps_dock_frame+104,load64(data+144));
    // This is the mapper's recorded RGB output, not a supplied house map.
    if pl_read_file(h_cat(load64(argv+16),"/observed.bin"),ps_discovery_observed,40000)!=40000 || pl_read_file(h_cat(load64(argv+16),"/safe.bin"),ps_nav_map,40000)!=40000 {return 11;}
    ps_x=f64_from_i64(99);ps_y=f64_from_i64(-99);ps_heading=PB_PI;store64(ps_case_bin,ps_x);store64(ps_case_bin+8,ps_y);store64(ps_case_bin+16,ps_x);let end=alloc(24);
    if !ps_nav_plan(load64(data+168),load64(data+176),load64(data+184)) || ps_nav_path_count {return 12;}
    ps_nav_end_pose(end);if ps_house_parking_clear(end,ps_nav_goal) {return 13;}
    ps_dock_search_anchor=alloc(32);ps_dock_search_goal=alloc(24);pb_copy(ps_dock_search_anchor,data+192,16);store64(ps_dock_search_anchor+16,f64_atan2(f64_sub(load64(data+216),load64(data+200)),f64_sub(load64(data+208),load64(data+192))));store64(ps_dock_search_anchor+24,load64(data+224));
    if !ps_dock_search_stage() {return 14;}
    ps_nav_end_pose(end);if !ps_house_parking_clear(end,ps_dock_search_goal) {return 15;}
    if !ps_case_drop_clearance(180,load64(ps_dock_search_goal),load64(ps_dock_search_goal+8),load64(ps_dock_search_goal+16)) {return 16;}
    pl_print(1,"Recorded docking replay passed: coarse arrival rejects an unknown parking arc, an alternate mapped route and complete parking correction reach a release pose, poisoned world pose has no effect\n");return 0;
}
fn main(argc,argv) {
    if !pl_init() || !ps_catalog_load() || !ps_case_load(ps_case_find("discover-house-blocks-into-box")) || !ps_model_load("build/flex/sim/puppybot.bin") || !ps_environment_load("build/flex/sim/environments/apartment/apartment.bin") {return 1;}
    ps_robot=alloc(8192);ps_system=alloc(2048);ps_config=alloc(448);ps_app=alloc(2048);ps_bus=alloc(16384);ps_plant=alloc(2048);ps_trace=alloc(69632);ps_json=alloc(16384);ps_builder=alloc(32);pb_config_default(ps_config);pb_vset(ps_config+40,2,5);ps_local_requested=1;
    if !ps_reset() {return 2;}if argc>2 {return fixture_replay(argv);}
    ps_case_phase(0);ps_discovery_phase=0;ps_collect_busy=1;ps_crumb_enabled=0;let i=0;
    // Synthetic sensor coverage isolates parking geometry from exploration.
    while i<40000 {store8(ps_discovery_observed+i,0);store8(ps_nav_map+i,0);i=i+1;}
    let target=alloc(24);store64(target,ps_number(8,100));store64(target+8,ps_number(3,100));store64(target+16,ps_number(2,10));let predicted=alloc(24);
    if !ps_nav_plan_parking(load64(target),load64(target+8),load64(target+16)) || ps_nav_parking_goal {return 23;}
    ps_nav_end_pose(predicted);if !ps_house_parking_clear(predicted,target) {return 24;}
    pb_zero(predicted,24);
    if !ps_house_parking_clear(predicted,target) {return 3;}i=0;ps_house_parking=0;
    while i<1500 && ps_house_park_to(target)!=2 {if !ps_tick(0) || ps_blocked || ps_case_stage!=0 {return 4;}i=i+1;}
    if i==1500 {return 5;}
    if f64_gt(f64_magnitude(f64_sub(load64(predicted),ps_x)),ps_number(1,1000000)) || f64_gt(f64_magnitude(f64_sub(load64(predicted+8),ps_y)),ps_number(1,1000000)) || f64_gt(f64_magnitude(pb_wrap_pi(f64_sub(load64(predicted+16),ps_heading))),ps_number(1,1000000)) {return 6;}
    // The coarse start and destination fit, but the reverse parking arc does
    // not fit the observed patch. Planning must not certify that correction.
    ps_local_x=0;ps_local_y=0;ps_local_heading=0;i=0;while i<40000 {store8(ps_discovery_observed+i,1);store8(ps_nav_map+i,1);i=i+1;}
    let row=98;while row<=102 {let col=98;while col<=103 {store8(ps_discovery_observed+row*200+col,0);store8(ps_nav_map+row*200+col,0);col=col+1;}row=row+1;}
    if !ps_nav_plan(load64(target),load64(target+8),load64(target+16)) || ps_nav_path_count {return 7;}
    ps_nav_end_pose(predicted);if ps_house_parking_clear(predicted,target) {return 8;}
    // Close parking must distinguish a partially occupied coarse cell from
    // observed fine floor. Unknown fine cells never count as free space.
    i=0;while i<40000 {store8(ps_discovery_observed+i,1);i=i+1;}
    i=0;while i<1000000 {store8(ps_discovery_detail+i,1);i=i+1;}
    ps_discovery_detail_ready=1;
    if ps_nav_observed_clear(0,0,0) {return 17;}
    row=490;while row<510 {let col=490;while col<510 {store8(ps_discovery_detail+row*1000+col,0);col=col+1;}row=row+1;}
    if !ps_nav_observed_clear(0,0,0) || !ps_nav_observed_clear(0,0,ps_number(785398,1000000)) {return 18;}
    // This unknown patch is between the old footprint samples.
    store8(ps_discovery_detail+501*1000+501,1);
    if ps_nav_observed_clear(0,0,0) {return 19;}
    store8(ps_discovery_detail+501*1000+501,0);store8(ps_discovery_detail+502*1000+508,1);
    if !ps_nav_observed_clear(0,0,0) || ps_nav_observed_clear(0,0,ps_number(785398,1000000)) {return 20;}
    ps_discovery_detail_ready=0;if ps_nav_observed_clear(0,0,0) {return 21;}
    if !fixture_actions() {return 22;}
    pl_print(1,"Parking checks passed: prediction and all twelve drive primitives match actual motion; unknown correction arcs and fine floor holes remain blocked\n");return 0;
}
'''


def replay(binary,directory,path,frame):
    previous=False;capture=None;current=None;home=None
    for line in path.open():
        state=json.loads(line)
        if home is None and state['discovery']['pickup']['boxLearned']:home=state['localization']['pose']
        if state['gripper']['held'] and not previous:capture=state
        if state['step']==frame:current=state;break
        previous=state['gripper']['held']
    assert capture and current and home is not None and current['gripper']['held'] and current['discovery']['pickup']['busy']
    dock=current['case']['dockVision'];assert dock['valid'] and dock['stableObservations']>=3
    data=struct.pack('<6d4q',*capture['localization']['pose'],*capture['case']['pickupTargetM'],*capture['ticks'])
    data+=struct.pack('<3d4q3dq3d',*current['localization']['pose'],*current['ticks'],*dock['positionM'][:2],dock['yawRad'],current['case']['placed'],*current['case']['boxSearch']['goal'])
    data+=struct.pack('<5d',*current['case']['boxSearch']['centreM'],*home)
    fixture=directory/'replay.bin';fixture.write_bytes(data)
    result=subprocess.run([str(binary),str(fixture),str(path.parent/'map/episode-0')],cwd=ROOT,capture_output=True,text=True,check=True)
    (directory/'replay.log').write_text(result.stdout+result.stderr);print(result.stdout,end='')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--recorded',type=Path);parser.add_argument('--frame',type=int);parser.add_argument('--output',type=Path);args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='parking-',dir=ROOT/'build/flex/sim') as temporary:
        directory=args.output or Path(temporary)
        if args.output:directory.mkdir(parents=True,exist_ok=False)
        entry,binary=directory/'probe.flex',directory/'probe';entry.write_text(source())
        subprocess.run([os.environ.get('FLEXSCRIPT_COMPILER',str(ROOT/'build/flex/pup-compiler')),str(entry),'-o',str(binary)],cwd=ROOT,check=True)
        subprocess.run([str(binary)],cwd=ROOT,check=True,timeout=60)
        if args.recorded:
            if args.frame is None:parser.error('--recorded requires --frame')
            replay(binary,directory,args.recorded,args.frame)


if __name__=='__main__':main()
