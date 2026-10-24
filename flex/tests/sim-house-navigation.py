#!/usr/bin/env python3
"""Reproduce an RGB-box-blocked coverage goal without consulting world truth."""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def main():
    source = (ROOT/'flex/sim/main.flex').read_text().replace('fn main(argc, argv)', 'fn ps_application_main(argc, argv)')
    source = re.sub(r'^import "([^"]+)";', lambda m: 'import '+json.dumps(str(ROOT/'flex/sim'/m[1]))+';', source, flags=re.MULTILINE)
    source += r'''
fn goal_check() {
    let target=alloc(24);store64(target,ps_number(2,10));store64(target+8,ps_number(-5,10));
    if ps_nav_clear(load64(target),load64(target+8),0) {return 0;}
    if !ps_house_plan_view(target) || !ps_nav_clear(load64(ps_nav_goal),load64(ps_nav_goal+8),load64(ps_nav_goal+16)) {return 0;}
    let dx=f64_sub(load64(ps_nav_goal),load64(target));let dy=f64_sub(load64(ps_nav_goal+8),load64(target+8));
    return f64_lt(f64_add(f64_mul(dx,dx),f64_mul(dy,dy)),ps_number(18,100));
}
fn main() {
    if !pl_init() || !ps_catalog_load() || !ps_case_load(ps_case_find("house-blocks-into-box")) || !ps_environment_load("build/flex/sim/environments/apartment/apartment.bin") || !ps_model_load("build/flex/sim/puppybot.bin") {return 1;}
    ps_robot=alloc(8192);ps_system=alloc(2048);ps_config=alloc(448);ps_app=alloc(2048);ps_bus=alloc(16384);ps_plant=alloc(2048);ps_trace=alloc(69632);
    pb_config_default(ps_config);pb_vset(ps_config+40,2,5);ps_local_requested=1;if !ps_reset() {return 2;}
    // Reproduce the long limited-yaw scan that used to exhaust 1000 steps.
    // Use the unchanged controller, encoder plant and 15-frame settle rule.
    ps_pickup_targets=alloc(32);store64(ps_plant+128,441000);store64(ps_plant+136,0);store64(ps_plant+144,441);pb_fake_servo(ps_bus,1,441);
    let warm=0;while warm<20 {gs_step(ps_plant);if pb_fake_cycle(ps_system,ps_bus,ps_time,ps_trace,1024)<0 {return 13;}ps_time=ps_time+20;warm=warm+1;}
    let i=0;while i<4 {store64(ps_pickup_targets+i*8,load64(ps_plant+144+i*64));i=i+1;}store64(ps_pickup_targets,4090);
    let values=ps_trace+1024;store64(values,220);if pr_apply(ps_app,1,values,ps_time) {return 14;}
    let deadline=ps_arm_move_timeout();if deadline<=1000 || deadline>1500 || pr_apply(ps_app,5,ps_pickup_targets,ps_time) {return 15;}
    let motion=0;let stable=0;while motion<deadline && stable<15 {
        pr_refresh(ps_app,ps_time);gs_step(ps_plant);if pb_fake_cycle(ps_system,ps_bus,ps_time,ps_trace,1024)<0 {return 16;}
        ps_time=ps_time+20;motion=motion+1;if gs_reached(ps_plant,ps_pickup_targets) && gs_stopped(ps_plant) {stable=stable+1;}else{stable=0;}
    }
    if stable<15 || motion<=1000 {return 17;}
    // The movable collection box is a physical obstacle both before and
    // during recovery. Entering search must not change this safety boundary.
    ps_vehicle_refresh();ps_dock_search_active=0;
    if ps_vehicle_free(load64(ps_case_bin),load64(ps_case_bin+8),0) {return 18;}
    ps_dock_search_active=1;if ps_vehicle_free(load64(ps_case_bin),load64(ps_case_bin+8),0) {return 19;}ps_dock_search_active=0;
    ps_local_x=ps_number(164,1000);ps_local_y=ps_number(759,1000);ps_local_heading=ps_number(29,10);
    ps_house_ready=1;ps_dock_seen=7646;ps_dock_yaw=ps_number(-176,1000);
    store64(ps_dock_frame,f64_cos(ps_dock_yaw));store64(ps_dock_frame+8,f64_sin(ps_dock_yaw));store64(ps_dock_frame+96,ps_number(259,1000));store64(ps_dock_frame+104,ps_number(-283,1000));
    if !goal_check() {return 3;}let saved=alloc(24);pb_copy(saved,ps_nav_goal,24);let count=ps_nav_path_count;
    ps_x=f64_from_i64(50);ps_y=f64_from_i64(-50);ps_heading=PB_PI;ps_physics=0;ps_gripper_frame=0;ps_tcp=0;
    if !goal_check() || ps_nav_path_count!=count {return 4;}
    i=0;while i<3 {if load64(saved+i*8)!=load64(ps_nav_goal+i*8) {return 5;}i=i+1;}
    // A small RGB uncertainty can put a physically stationary start just
    // inside the inflated box footprint. Only an outward escape is permitted.
    ps_local_x=ps_number(18,100);ps_local_y=ps_number(103,10000);ps_local_heading=ps_number(-1965,100000);
    ps_dock_yaw=ps_number(14,1000);store64(ps_dock_frame,f64_cos(ps_dock_yaw));store64(ps_dock_frame+8,f64_sin(ps_dock_yaw));store64(ps_dock_frame+96,ps_number(355,1000));store64(ps_dock_frame+104,ps_number(-218,1000));
    if ps_nav_clear(ps_pose_x(),ps_pose_y(),ps_pose_heading()) || !ps_nav_plan(ps_number(235,100),0,0) || !ps_nav_escape || ps_nav_searching {return 6;}
    if ps_nav_clear(ps_pose_x(),ps_pose_y(),ps_pose_heading()) || ps_nav_plan(ps_number(355,1000),ps_number(-218,1000),0) {return 7;}
    ps_local_x=ps_number(18,100);ps_local_y=ps_number(-118,10000);ps_local_heading=ps_number(12,10000);
    ps_dock_yaw=ps_number(-2524,10000);store64(ps_dock_frame,f64_cos(ps_dock_yaw));store64(ps_dock_frame+8,f64_sin(ps_dock_yaw));store64(ps_dock_frame+96,ps_number(3877,10000));store64(ps_dock_frame+104,ps_number(-2621,10000));
    if !ps_nav_plan(ps_number(235,100),0,0) || !ps_nav_escape || ps_nav_searching {return 8;}
    if ps_nav_plan(ps_number(3877,10000),ps_number(-2621,10000),0) {return 9;}
    if !ps_nav_clear(ps_number(18,100),ps_number(2,100),0) {return 10;}
    ps_pickup_targets=alloc(32);i=0;while i<4 {store64(ps_pickup_targets+i*8,load64(ps_plant+144+i*64));i=i+1;}
    store64(ps_plant+144,441);store64(ps_pickup_targets,4090);if ps_arm_move_ticks()!=3649 {return 11;}
    store64(ps_pickup_targets,977);if ps_arm_move_ticks()!=536 {return 12;}
    // A failed reverse command forbids repeating that approach, but permits
    // retreating forward. Poisoned world geometry must not affect the memory.
    ps_local_x=0;ps_local_y=0;ps_local_heading=0;let d=pb_robot_drive(ps_robot);store64(d+48,-60);store64(d+56,-60);store64(d+64,90);
    if !ps_nav_contact_add() || ps_nav_contact_clear(ps_number(-2,100),0,0,0,0,0) || !ps_nav_contact_clear(ps_number(2,100),0,0,0,0,0) {return 20;}
    ps_x=f64_from_i64(-99);ps_y=f64_from_i64(99);ps_heading=PB_PI;
    if ps_nav_contact_clear(ps_number(-2,100),0,0,0,0,0) || !ps_nav_contact_clear(ps_number(2,100),0,0,0,0,0) {return 21;}
    if !ps_nav_contact_clear(ps_number(98,100),0,0,PB_ONE,0,0) {return 22;}
    if !ps_nav_contact_clear(ps_number(-2,100),ps_number(-6,10000),ps_number(6,100),0,0,0) {return 23;}
    pl_print(1,"House navigation checks passed: safe alternate goals, outward margin escape, physical box exclusion before/during recovery, long wrist scan settles within measured budget, failed-command avoidance and escape ignore world truth\n");return 0;
}
'''
    with tempfile.TemporaryDirectory(prefix='house-navigation-', dir=ROOT/'build/flex/sim') as temporary:
        directory = Path(temporary)
        entry, binary = directory/'probe.flex', directory/'probe'
        entry.write_text(source)
        compiler = os.environ.get('FLEXSCRIPT_COMPILER', str(ROOT/'build/flex/pup-compiler'))
        subprocess.run([compiler, str(entry), '-o', str(binary)], cwd=ROOT, check=True)
        subprocess.run([str(binary)], cwd=ROOT, check=True)


if __name__ == '__main__':
    main()
