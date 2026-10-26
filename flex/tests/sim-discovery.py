#!/usr/bin/env python3
"""Check unknown-map initialization, stereo geometry and recorded exploration."""
import argparse
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile

sys.path = [p for p in sys.path if Path(p).resolve() != Path(__file__).resolve().parent]
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('discovery', ROOT/'flex/vision/discovery.py')
mapping = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mapping)


def isolation():
    source = (ROOT/'flex/sim/main.flex').read_text().replace('fn main(argc, argv)', 'fn ps_application_main(argc, argv)')
    source = re.sub(r'^import "([^"]+)";', lambda m: 'import '+json.dumps(str(ROOT/'flex/sim'/m[1]))+';', source, flags=re.MULTILINE)
    source += r'''
fn main() {
    if !pl_init() {return 1;}ps_discovery_enabled=1;ps_environment=1;ps_environment_start=1;ps_environment_count=99999;
    ps_x=f64_from_i64(99);ps_y=f64_from_i64(-99);ps_heading=PB_PI;ps_local_reset();
    if ps_local_mode!=2 || ps_pose_x() || ps_pose_y() || ps_pose_heading() || !ps_nav_init() {return 2;}
    if ps_nav_cells!=40000 || ps_nav_cell(0,0)!=20100 || ps_nav_cell(f64_from_i64(-11),0)>=0 {return 3;}
    let i=0;while i<40000 {if load8(ps_nav_map+i)!=1 {return 4;}i=i+1;}
    if ps_nav_plan(ps_number(36,100),0,0) || ps_crumb_ground_heading() || ps_crumb_axis_known {return 5;}
    let y=93;while y<=107 {let x=93;while x<=107 {store8(ps_nav_map+y*200+x,0);store8(ps_discovery_observed+y*200+x,0);x=x+1;}y=y+1;}
    if !ps_nav_plan(ps_number(36,100),0,0) {return 6;}let count=ps_nav_path_count;let first=load64(ps_nav_path);
    ps_environment=0;ps_environment_start=0;ps_environment_count=0;ps_x=f64_from_i64(-50);ps_y=f64_from_i64(50);ps_heading=0;
    if !ps_nav_plan(ps_number(36,100),0,0) || ps_nav_path_count!=count || load64(ps_nav_path)!=first {return 7;}
    // A frontier is a position, not a required parking orientation. In a
    // narrow observed corridor the wrist can scan after a straight arrival.
    i=0;while i<40000 {store8(ps_nav_map+i,1);store8(ps_discovery_observed+i,1);i=i+1;}
    y=99;while y<=101 {let x=98;while x<=110 {store8(ps_nav_map+y*200+x,0);store8(ps_discovery_observed+y*200+x,0);x=x+1;}y=y+1;}
    ps_local_y=ps_number(5,100);let angle=f64_div(PB_PI,f64_from_i64(4));
    if ps_nav_clear(ps_number(36,100),ps_local_y,angle) || !ps_nav_plan(ps_number(36,100),ps_local_y,angle) {return 8;}
    // Reverse arrival must still look toward the unknown side of the
    // frontier, rather than back along the rover's chassis heading.
    ps_local_x=0;ps_local_y=0;ps_local_heading=PB_HALF_PI;let frontier=alloc(24);store64(frontier+8,pb_neg(PB_ONE));store64(frontier+16,pb_neg(PB_HALF_PI));ps_discovery_frontier_focus(frontier);
    if f64_gt(f64_magnitude(f64_add(ps_discovery_scan_bearing(),PB_HALF_PI)),ps_number(1,1000000)) {return 9;}
    ps_x=f64_from_i64(77);ps_y=f64_from_i64(-88);ps_heading=0;
    if f64_gt(f64_magnitude(f64_add(ps_discovery_scan_bearing(),PB_HALF_PI)),ps_number(1,1000000)) {return 10;}
    pl_print(1,"Discovery isolation passed: entirely unknown initial grid, local origin, poisoned/missing world map and bounds, no known-wall compass, unchanged observed-grid plan and frontier-directed scans after reverse arrival\n");return 0;
}
'''
    with tempfile.TemporaryDirectory(prefix='discovery-isolation-', dir=ROOT/'build/flex/sim') as temporary:
        directory = Path(temporary)
        entry, binary = directory/'probe.flex', directory/'probe'
        entry.write_text(source)
        subprocess.run([os.environ.get('FLEXSCRIPT_COMPILER', str(ROOT/'build/flex/pup-compiler')), str(entry), '-o', str(binary)], check=True, cwd=ROOT)
        subprocess.run([str(binary)], check=True, cwd=ROOT)


def control():
    """Check exploration recovery with explicit synthetic sensor coverage."""
    source=(ROOT/'flex/sim/main.flex').read_text().replace('fn main(argc, argv)','fn ps_application_main(argc, argv)')
    source=re.sub(r'^import "([^"]+)";',lambda m:'import '+json.dumps(str(ROOT/'flex/sim'/m[1]))+';',source,flags=re.MULTILINE)
    source+=r'''

fn contact_memory() {
    // A failed reverse turn permits one untried straight command. If that
    // command also fails, its own record forbids another straight retry.
    ps_local_x=ps_number(366107857,1000000000);ps_local_y=ps_number(-2739267753,1000000000);ps_local_heading=ps_number(2520312873,1000000000);
    let r=ps_nav_contacts;ps_nav_contact_count=1;store64(r,ps_local_x);store64(r+8,ps_local_y);store64(r+16,ps_local_heading);store64(r+24,-1);
    let angle=pb_radians(f64_from_i64(27));store64(r+32,pb_neg(f64_div(f64_sin(angle),f64_mul(ps_number(18,100),f64_cos(angle)))));
    let move=ps_number(-6,1000);let x=f64_add(ps_local_x,f64_mul(move,f64_cos(ps_local_heading)));let y=f64_add(ps_local_y,f64_mul(move,f64_sin(ps_local_heading)));
    if !ps_nav_contact_clear(x,y,ps_local_heading,ps_local_x,ps_local_y,ps_local_heading) {return 0;}
    pb_copy(r+40,r,40);store64(r+40+32,0);ps_nav_contact_count=2;
    if ps_nav_contact_clear(x,y,ps_local_heading,ps_local_x,ps_local_y,ps_local_heading) {return 0;}
    ps_nav_contact_count=1;
    x=f64_sub(ps_local_x,f64_mul(move,f64_cos(ps_local_heading)));y=f64_sub(ps_local_y,f64_mul(move,f64_sin(ps_local_heading)));
    if !ps_nav_contact_clear(x,y,ps_local_heading,ps_local_x,ps_local_y,ps_local_heading) {return 0;}
    ps_collect_busy=1;x=f64_add(ps_local_x,f64_mul(move,f64_cos(ps_local_heading)));y=f64_add(ps_local_y,f64_mul(move,f64_sin(ps_local_heading)));
    if !ps_nav_contact_clear(x,y,ps_local_heading,ps_local_x,ps_local_y,ps_local_heading) {return 0;}
    // Recorded v35 retry: turn around and reverse into the same blocked
    // direction. Changing body heading and gear must preserve the memory.
    ps_collect_busy=0;store64(r,ps_number(-777980438,1000000000));store64(r+8,ps_number(1780335589,1000000000));store64(r+16,ps_number(2149061524,1000000000));store64(r+24,1);store64(r+32,0);
    ps_local_x=ps_number(-775359265,1000000000);ps_local_y=ps_number(1763478084,1000000000);ps_local_heading=ps_number(-868217296,1000000000);
    x=f64_add(ps_local_x,f64_mul(move,f64_cos(ps_local_heading)));y=f64_add(ps_local_y,f64_mul(move,f64_sin(ps_local_heading)));
    if ps_nav_contact_clear(x,y,ps_local_heading,ps_local_x,ps_local_y,ps_local_heading) {return 0;}
    let turned=pb_wrap_pi(f64_add(ps_local_heading,PB_PI));
    if ps_nav_contact_clear(x,y,turned,ps_local_x,ps_local_y,turned) {return 0;}
    x=f64_sub(ps_local_x,f64_mul(move,f64_cos(ps_local_heading)));y=f64_sub(ps_local_y,f64_mul(move,f64_sin(ps_local_heading)));
    if !ps_nav_contact_clear(x,y,ps_local_heading,ps_local_x,ps_local_y,ps_local_heading) {return 0;}
    ps_collect_busy=1;x=f64_add(ps_local_x,f64_mul(move,f64_cos(ps_local_heading)));y=f64_add(ps_local_y,f64_mul(move,f64_sin(ps_local_heading)));
    if !ps_nav_contact_clear(x,y,ps_local_heading,ps_local_x,ps_local_y,ps_local_heading) {return 0;}
    // Recorded v37 trap: reverse straight and forward turning both failed.
    // The untried forward straight primitive still fits observed floor.
    ps_collect_busy=0;ps_local_x=0;ps_local_y=0;ps_local_heading=0;ps_nav_contact_count=2;
    pb_zero(r,80);store64(r+24,-1);store64(r+40+24,1);store64(r+40+32,ps_number(-283,100));
    if !ps_nav_contact_clear(ps_number(24,1000),0,0,0,0,0) || ps_nav_contact_clear(ps_number(-24,1000),0,0,0,0,0) {return 0;}
    if ps_nav_contact_clear(ps_number(24,1000),0,ps_number(-68,1000),0,0,0) || ps_discovery_escape() {return 0;}
    // Use the same heading association for the broad failure and its
    // untried-straight exception. A recorded failed straight stays forbidden.
    let shifted=ps_number(3,10);
    if !ps_nav_straight_escape(0,0,shifted,1) || ps_nav_straight_escape(0,0,shifted,-1) {return 0;}
    let row=98;while row<=102 {let col=98;while col<=102 {store8(ps_discovery_observed+row*200+col,0);col=col+1;}row=row+1;}
    if !ps_discovery_escape() || ps_nav_path_count!=1 || load64(ps_nav_path)!=1 || f64_gt(f64_magnitude(f64_sub(load64(ps_nav_goal),ps_number(12,100))),ps_number(1,1000000)) {return 0;}
    if ps_discovery_escape_count!=2 || ps_discovery_escape_unvisited(0,0) || ps_discovery_escape_unvisited(ps_number(12,100),0) {return 0;}
    ps_discovery_escape_count=0;ps_discovery_escape_next=0;
    store8(ps_discovery_observed+100*200+102,1);if ps_discovery_escape() {return 0;}
    store8(ps_discovery_observed+100*200+102,0);
    pb_zero(r+80,40);store64(r+80+24,1);ps_nav_contact_count=3;
    if ps_discovery_escape() || ps_nav_contact_clear(ps_number(24,1000),0,0,0,0,0) {return 0;}
    if ps_nav_straight_escape(0,0,shifted,1) {return 0;}
    // Recorded v45 doorway trap: only the forward curved failure remains
    // within 18 cm after a safe straight move. Losing the opposite failure
    // must not forbid an untried straight in the observed corridor.
    pb_zero(r,80);ps_nav_contact_count=2;
    store64(r,ps_number(282147876,100000000));store64(r+8,ps_number(71596539,100000000));store64(r+16,ps_number(187452045,100000000));store64(r+24,1);store64(r+32,ps_number(55556,10000));
    store64(r+40,ps_number(282787022,100000000));store64(r+48,ps_number(68949022,100000000));store64(r+56,ps_number(172412357,100000000));store64(r+64,-1);store64(r+72,ps_number(-283,100));
    let corridor_x=ps_number(282834507,100000000);let corridor_y=ps_number(88502651,100000000);let corridor_heading=ps_number(153808539,100000000);
    if !ps_nav_straight_escape(corridor_x,corridor_y,corridor_heading,1) {return 0;}
    // Turning the body around and changing gear preserves a failed
    // straight even when a matching curved failure would allow an escape.
    pb_copy(r+80,r,40);store64(r+80+16,pb_wrap_pi(f64_add(corridor_heading,PB_PI)));store64(r+80+24,-1);store64(r+80+32,0);ps_nav_contact_count=3;
    if ps_nav_straight_escape(corridor_x,corridor_y,corridor_heading,1) {return 0;}
    // A successful escape must not become a two-pose forward/reverse loop.
    // Both visited endpoints remain excluded after retracing to the origin.
    ps_discovery_escape_remember(0,0);ps_discovery_escape_remember(ps_number(12,100),0);
    ps_nav_contact_count=0;ps_local_x=ps_number(12,100);ps_local_y=0;
    if ps_discovery_escape_unvisited(0,0) || ps_discovery_escape_unvisited(ps_local_x,0) || !ps_discovery_escape_unvisited(ps_number(24,100),0) {return 0;}
    pb_zero(r,80);store64(r+24,1);store64(r+40+24,-1);store64(r+40+32,ps_number(-283,100));ps_nav_contact_count=2;
    if ps_discovery_escape() {return 0;}
    // Completed-path recovery distinguishes a turn from a failed straight
    // command. Ordinary exploration retains its broader direction memory.
    ps_local_x=0;ps_local_y=0;ps_local_heading=0;ps_nav_contact_count=1;pb_zero(r,40);store64(r+24,1);
    if ps_nav_contact_clear(ps_number(24,1000),0,ps_number(-68,1000),0,0,0) || !ps_nav_contact_clear_mode(ps_number(24,1000),0,ps_number(-68,1000),0,0,0,0) {return 0;}
    store64(r+32,ps_number(-283,100));
    if ps_nav_contact_clear_mode(ps_number(24,1000),0,ps_number(-68,1000),0,0,0,0) {return 0;}
    if ps_nav_contact_clear_mode(ps_number(24,1000),0,ps_number(-68,1000),0,0,0,2) {return 0;}
    // A nearby failure cannot erase a different section of a completed
    // route. Matching the same command within two centimetres still rejects it.
    store64(r,ps_number(5,100));
    if ps_nav_contact_clear_mode(ps_number(24,1000),0,ps_number(-68,1000),0,0,0,0) || !ps_nav_contact_clear_mode(ps_number(24,1000),0,ps_number(-68,1000),0,0,0,2) {return 0;}
    store64(r,ps_number(1,100));
    if ps_nav_contact_clear_mode(ps_number(24,1000),0,ps_number(-68,1000),0,0,0,2) {return 0;}
    ps_nav_contact_count=0;ps_local_x=0;ps_discovery_escape_count=0;ps_discovery_escape_next=0;return 1;
}

fn failed_frontiers() {
    let saved=alloc(1080000);pb_copy(saved,ps_nav_map,40000);pb_copy(saved+40000,ps_discovery_observed,40000);pb_copy(saved+80000,ps_discovery_detail,1000000);
    let path=ps_nav_path_count;let goal_x=load64(ps_nav_goal);let goal_y=load64(ps_nav_goal+8);
    let world_x=ps_x;let world_y=ps_y;let world_heading=ps_heading;let environment=ps_environment;let environment_count=ps_environment_count;
    ps_x=f64_nan();ps_y=f64_nan();ps_heading=f64_nan();ps_environment=1;ps_environment_count=99999;
    ps_nav_path_count=1;store64(ps_nav_goal,ps_number(5,10));store64(ps_nav_goal+8,ps_number(5,10));
    if !ps_discovery_frontier_failed() || ps_discovery_failed_count!=1 || ps_discovery_frontier_failed() {return 0;}
    if ps_discovery_frontier_allowed(ps_number(5,10),ps_number(5,10)) || ps_discovery_frontier_allowed(ps_number(7,10),ps_number(5,10)) || !ps_discovery_frontier_allowed(ps_number(9,10),ps_number(5,10)) {return 0;}
    // Rejecting this frontier leaves arm-view selection and the floor maps
    // unchanged. A failed transit is not a reason to erase a valid route.
    if !ps_discovery_pose_allowed(ps_number(5,10),ps_number(5,10)) {return 0;}
    store64(ps_nav_goal,ps_number(9,10));ps_collect_busy=1;if ps_discovery_frontier_failed() {return 0;}ps_collect_busy=0;
    ps_gripper_held=1;if ps_discovery_frontier_failed() {return 0;}ps_gripper_held=0;
    ps_discovery_retrace=1;if ps_discovery_frontier_failed() {return 0;}ps_discovery_retrace=0;
    ps_nav_path_count=0;if ps_discovery_frontier_failed() {return 0;}ps_nav_path_count=1;
    let i=0;while i<20 {store64(ps_nav_goal,ps_number(i,2));store64(ps_nav_goal+8,PB_ONE);if !ps_discovery_frontier_failed() {return 0;}i=i+1;}
    if ps_discovery_failed_count!=16 || !ps_discovery_frontier_allowed(0,PB_ONE) || ps_discovery_frontier_allowed(ps_number(19,2),PB_ONE) {return 0;}
    i=0;while i<40000 {if load8(saved+i)!=load8(ps_nav_map+i) || load8(saved+40000+i)!=load8(ps_discovery_observed+i) {return 0;}i=i+1;}
    i=0;while i<1000000 {if load8(saved+80000+i)!=load8(ps_discovery_detail+i) {return 0;}i=i+1;}
    ps_discovery_failed_count=0;ps_discovery_failed_next=0;ps_nav_path_count=path;store64(ps_nav_goal,goal_x);store64(ps_nav_goal+8,goal_y);
    ps_x=world_x;ps_y=world_y;ps_heading=world_heading;ps_environment=environment;ps_environment_count=environment_count;return 1;
}

fn motion_history() {
    let total=ps_total;let d=pb_robot_drive(ps_robot);ps_discovery_motion_clear();let i=0;
    let world_x=ps_x;let world_y=ps_y;let world_heading=ps_heading;let environment=ps_environment;let environment_count=ps_environment_count;
    ps_x=f64_nan();ps_y=f64_nan();ps_heading=f64_nan();ps_environment=1;ps_environment_count=99999;
    // A drive stop can back away in an already matching, idle posture.
    // Starting another wrist sweep here caused the recorded sofa failure.
    let camera=ps_camera_drive_mode;let phase=ps_discovery_phase;ps_camera_drive_mode=1;
    ps_total=ps_total+1;pb_drive_steer(d,30,0,ps_time);if !ps_discovery_motion_record() {return 0;}pb_drive_stop(d,ps_time);
    if !ps_discovery_retrace_begin() || ps_discovery_phase!=5 || ps_discovery_pending_phase || pb_a(ps_robot,PB_A_MODE) || ps_discovery_retrace!=1 {return 0;}
    if !ps_discovery_retrace_tick() || load64(d+48)!=-30 || pb_a(ps_robot,PB_A_MODE) {return 0;}
    pb_drive_stop(d,ps_time);ps_discovery_motion_clear();
    // Matching feedback alone cannot bypass a still-active arm command.
    ps_total=ps_total+1;pb_drive_steer(d,30,0,ps_time);ps_discovery_motion_record();pb_drive_stop(d,ps_time);pb_as(ps_robot,PB_A_MODE,2);
    if !ps_discovery_retrace_begin() || ps_discovery_phase || ps_discovery_pending_phase!=4 {return 0;}
    pb_arm_stop(ps_robot,ps_time);ps_discovery_pending_phase=0;ps_discovery_pending_turn=0;ps_camera_drive_mode=camera;ps_discovery_phase=phase;ps_discovery_motion_clear();
    while i<70 {ps_total=ps_total+1;pb_drive_steer(d,30,100,ps_time);
        if !ps_discovery_motion_record() || ps_discovery_motion_record() || ps_discovery_motion_count!=pb_min(i+1,64) {return 0;}i=i+1;}
    let count=ps_discovery_motion_count;ps_total=ps_total+1;ps_blocked=1;if ps_discovery_motion_record() || ps_discovery_motion_count!=count {return 0;}ps_blocked=0;
    ps_gripper_held=1;if ps_discovery_retrace_begin() {return 0;}ps_gripper_held=0;ps_collect_busy=1;if ps_discovery_retrace_begin() {return 0;}ps_collect_busy=0;
    ps_discovery_motion_clear();ps_total=ps_total+1;pb_drive_steer(d,60,60,ps_time);ps_discovery_motion_record();
    ps_total=ps_total+1;pb_drive_steer(d,30,-100,ps_time);ps_discovery_motion_record();pb_drive_stop(d,ps_time);
    ps_discovery_retrace=2;ps_discovery_retrace_issued=0;
    if !ps_discovery_retrace_tick() || load64(d+48)!=-30 || load64(d+64)!=45 || ps_discovery_motion_count!=2 {return 0;}
    if !ps_discovery_retrace_tick() || ps_discovery_motion_count!=2 {return 0;}ps_total=ps_total+1;
    if !ps_discovery_retrace_tick() || load64(d+48)!=-60 || load64(d+64)!=117 || ps_discovery_motion_count!=1 {return 0;}
    ps_total=ps_total+1;
    if !ps_discovery_retrace_tick() || load64(d+48) || ps_discovery_motion_count || ps_discovery_phase!=1 || !ps_discovery_full || ps_discovery_retrace_begin() {return 0;}
    // An interrupted command cannot consume history or issue the next inverse.
    ps_discovery_motion_count=2;ps_discovery_motion_next=2;ps_discovery_retrace=2;ps_discovery_retrace_issued=0;
    if !ps_discovery_retrace_tick() {return 0;}pb_drive_stop(d,ps_time);ps_total=ps_total+1;
    if !ps_discovery_retrace_tick() || ps_discovery_motion_count || load64(d+48) {return 0;}
    // Only exactly representable native drive commands form this history.
    ps_total=ps_total+1;pb_drive_steer(d,30,10,ps_time);
    if ps_discovery_motion_record() || ps_discovery_motion_count {return 0;}pb_drive_stop(d,ps_time);
    // An earlier failed reverse command still forbids retracing into it.
    ps_local_x=0;ps_local_y=0;ps_local_heading=0;ps_nav_contact_count=1;pb_zero(ps_nav_contacts,40);store64(ps_nav_contacts+24,-1);
    ps_discovery_motion_count=1;ps_discovery_motion_next=1;store64(ps_discovery_motion,30);store64(ps_discovery_motion+8,0);ps_discovery_retrace=1;
    if !ps_discovery_retrace_tick() || ps_discovery_motion_count || load64(d+48) {return 0;}
    // A new physical stop consumes the recovery and the ordinary stop budget.
    ps_nav_contact_count=0;ps_discovery_motion_count=1;ps_discovery_motion_next=1;ps_discovery_retrace=1;ps_discovery_retrace_issued=1;
    ps_discovery_stops=11;ps_blocked=1;pb_drive_steer(d,-30,0,ps_time);
    if !ps_discovery_retrace_tick() || ps_discovery_stops!=12 || ps_discovery_motion_count || ps_nav_contact_count!=1 || load64(d+48) {return 0;}
    ps_blocked=0;ps_discovery_stops=0;ps_nav_contact_count=0;ps_discovery_motion_count=1;
    ps_discovery_escape_remember(0,0);
    if !ps_collect_search_begin() || ps_discovery_motion_count || ps_discovery_escape_count || ps_discovery_escape_next {return 0;}
    ps_x=world_x;ps_y=world_y;ps_heading=world_heading;ps_environment=environment;ps_environment_count=environment_count;
    ps_total=total;ps_discovery_motion_clear();return 1;
}
fn main() {
    if !pl_init() || !ps_catalog_load() || !ps_case_load(ps_case_find("discover-house-blocks-into-box")) || !ps_environment_load("build/flex/sim/environments/apartment/apartment.bin") || !ps_model_load("build/flex/sim/puppybot.bin") {return 1;}
    ps_robot=alloc(8192);ps_system=alloc(2048);ps_config=alloc(448);ps_app=alloc(2048);ps_bus=alloc(16384);ps_plant=alloc(2048);ps_trace=alloc(69632);pb_config_default(ps_config);pb_vset(ps_config+40,2,5);
    if !ps_reset() {return 2;}ps_case_phase(26);ps_total=2;ps_camera_drive_mode=1;if !contact_memory() {return 10;}if !failed_frontiers() {return 14;}if !motion_history() {return 13;}
    let y=90;while y<111 {let x=90;while x<121 {store8(ps_nav_map+y*200+x,0);store8(ps_discovery_observed+y*200+x,0);x=x+1;}y=y+1;}
    if !ps_nav_plan(ps_number(14,10),0,0) {return 3;}ps_local_x=ps_number(81,100);ps_local_distance=ps_local_x;ps_discovery_distance=0;ps_discovery_phase=5;
    ps_environment=1;ps_environment_start=1;ps_environment_count=99999;ps_x=f64_nan();ps_y=f64_nan();ps_heading=f64_nan();
    if !ps_discovery_update() || ps_discovery_phase!=5 || ps_discovery_distance!=ps_local_distance || !ps_nav_path_count || ps_nav_path_count>6 || load64(ps_nav_goal)!=ps_number(14,10) {return 4;}
    let d=pb_robot_drive(ps_robot);if load64(d+48) || load64(d+56) {return 5;}
    let i=0;while i<40000 {store8(ps_nav_map+i,1);store8(ps_discovery_observed+i,1);i=i+1;}
    // Only the presently observed footprint remains; the old destination is
    // unknown. A failed route refresh must stop and request a new scan.
    y=98;while y<103 {let x=106;while x<111 {store8(ps_nav_map+y*200+x,0);store8(ps_discovery_observed+y*200+x,0);x=x+1;}y=y+1;}
    ps_discovery_distance=0;ps_discovery_phase=5;ps_nav_remaining=20;pb_drive_steer(d,60,0,ps_time);
    if !ps_discovery_update() || ps_discovery_phase!=1 || load64(d+48) || load64(d+56) || ps_nav_path_count {return 6;}
    ps_collect_enabled=0;ps_discovery_phase=5;ps_nav_remaining=20;ps_nav_path_count=10;ps_nav_path_index=0;pb_drive_steer(d,60,0,ps_time);
    if !ps_discovery_update() || ps_discovery_phase!=1 || load64(d+48) || load64(d+56) {return 7;}
    ps_collect_enabled=1;ps_collect_busy=0;ps_discovery_phase=2;ps_gripper_held=0;
    if !ps_discovery_arm_stop() || ps_discovery_bad_count!=1 || ps_discovery_pose_allowed(ps_pose_x(),ps_pose_y()) || !ps_discovery_pose_allowed(f64_add(ps_pose_x(),ps_number(31,100)),ps_pose_y()) {return 8;}
    let target=load64(ps_plant+144+3*64);let k=0;while k<4 {store64(ps_pickup_targets+k*8,load64(ps_plant+144+k*64));k=k+1;}store64(ps_pickup_targets+24,target+9);
    pb_arm_stop(ps_robot,ps_time);pb_as(ps_robot,PB_A_MODE,0);ps_discovery_retries=0;ps_pickup_stable=0;
    store64(ps_plant+128+3*64+8,1);if ps_discovery_settled() || ps_discovery_retries {return 9;}store64(ps_plant+128+3*64+8,0);
    if gs_reached(ps_plant,ps_pickup_targets) || ps_discovery_settled() || ps_discovery_retries!=1 || pb_a(ps_robot,PB_A_MODE)!=2 || gs_reached(ps_plant,ps_pickup_targets) {return 9;}
    // A missing exit requests new camera geometry, never a free-space edit.
    // The poisoned scene inputs above remain inaccessible to both retries.
    ps_collect_enabled=0;ps_discovery_bad_count=0;ps_discovery_goal_count=0;ps_discovery_scans=0;ps_discovery_limit=10;ps_discovery_rescans=0;ps_discovery_full=1;let retry=0;
    while retry<2 {
        ps_discovery_sector=8;ps_discovery_tilt=1;
        if !ps_discovery_next_sector() || ps_discovery_rescans!=retry+1 || ps_discovery_phase!=2 || ps_discovery_height<375+retry*5 {return 11;}retry=retry+1;
    }
    ps_discovery_sector=8;ps_discovery_tilt=1;if ps_discovery_next_sector() || ps_discovery_phase!=7 || ps_discovery_rescans!=2 {return 12;}
    pl_print(1,"Transit/control bounds passed: observed-floor route refresh, bounded completed-motion recovery, interrupted/failed-command rejection, unknown-route stop/scan and poisoned world inputs\n");return 0;
}

'''
    with tempfile.TemporaryDirectory(prefix='discovery-control-',dir=ROOT/'build/flex/sim') as temporary:
        directory=Path(temporary);entry,binary=directory/'probe.flex',directory/'probe';entry.write_text(source)
        subprocess.run([os.environ.get('FLEXSCRIPT_COMPILER',str(ROOT/'build/flex/pup-compiler')),str(entry),'-o',str(binary)],cwd=ROOT,check=True)
        subprocess.run([str(binary)],cwd=ROOT,check=True)


def recovery():
    """Replay rejected views with real joint commands and collision guards."""
    source=(ROOT/'flex/sim/main.flex').read_text().replace('fn main(argc, argv)','fn ps_application_main(argc, argv)')
    source=re.sub(r'^import "([^"]+)";',lambda m:'import '+json.dumps(str(ROOT/'flex/sim'/m[1]))+';',source,flags=re.MULTILINE)
    source+=r'''
fn main() {
    if !pl_init() || !ps_catalog_load() || !ps_case_load(ps_case_find("discover-house-blocks-into-box")) || !ps_environment_load("build/flex/sim/environments/apartment/apartment.bin") || !ps_model_load("build/flex/sim/puppybot.bin") || !ps_environment_spawn(FIXTURE_SPAWN) {return 1;}
    ps_robot=alloc(8192);ps_system=alloc(2048);ps_config=alloc(448);ps_app=alloc(2048);ps_bus=alloc(16384);ps_plant=alloc(2048);ps_trace=alloc(69632);pb_config_default(ps_config);pb_vset(ps_config+40,2,5);
    ps_json=alloc(16384);ps_builder=alloc(32);ps_collect_enabled=0;if !ps_reset() {return 2;}ps_case_phase(0);
    // Only the fixture initializes the recorded physical state. Recovery
    // receives local encoders and a rejected-view event, never the sofa pose.
    let ticks=alloc(32);FIXTURE_TICKS let positions=alloc(32);FIXTURE_POSITIONS let i=0;
    while i<4 {let j=ps_plant+128+i*64;let tick=load64(ticks+i*8);store64(j,load64(positions+i*8));store64(j+8,0);store64(j+16,tick);pb_fake_servo(ps_bus,load64(j+24),tick);pb_arm_feedback(ps_robot,i,tick,ps_time);i=i+1;}
    ps_gripper_gap=0;ps_gripper_goal=0;ps_model_update(ps_robot,ps_plant,ps_x,ps_y,ps_heading,ps_wheel);ps_gripper_frame_update(ps_robot,ps_plant);ps_arm_proxy_update(1);
    if !ps_solid_free(ps_x,ps_y,ps_heading) {return 3;}let speed=ps_trace+1400;store64(speed,200);pr_apply(ps_app,1,speed,ps_time);
    FIXTURE_LOCAL
    ps_discovery_enabled=0;i=0;while i<FIXTURE_WARM {if !ps_tick(0)||ps_arm_blocked {return 13;}i=i+1;}ps_discovery_enabled=1;
    ps_discovery_raised_only=!FIXTURE_GUARD;ps_discovery_phase=2;ps_discovery_sector=FIXTURE_SECTOR;ps_discovery_tilt=FIXTURE_TILT;ps_discovery_side=1;ps_discovery_bearing=FIXTURE_BEARING;
    if ps_discovery_elbow_first()!=FIXTURE_ELBOW {return 5;}
    let local_x=ps_local_x;let local_y=ps_local_y;let local_h=ps_local_heading;ps_local_x=f64_from_i64(7);ps_local_y=f64_from_i64(-4);ps_local_heading=ps_number(17,10);
    if ps_discovery_elbow_first()!=FIXTURE_ELBOW {return 5;}ps_local_x=local_x;ps_local_y=local_y;ps_local_heading=local_h;
    if FIXTURE_GUARD {
        // Replay the original yaw command and let the real guard dispatch
        // recovery. Fractional positions restore only the physical fixture.
        let aim=alloc(32);pb_copy(aim,ticks,32);store64(aim,3578);
        if pr_apply(ps_app,5,aim,ps_time) || pb_fake_cycle(ps_system,ps_bus,ps_time,ps_trace,1024)<0 {return 14;}store64(ps_plant+136,200);
        if !ps_tick(0) || !ps_arm_blocked || ps_discovery_arm_stops!=1 || ps_discovery_phase {return 14;}
    } else if !ps_discovery_next_sector() || ps_discovery_phase {return 4;}
    if FIXTURE_ELBOW && (load64(ps_pickup_targets)!=load64(ticks) || load64(ps_pickup_targets+8)!=load64(ticks+8) || load64(ps_pickup_targets+24)!=load64(ticks+24) || load64(ps_pickup_targets+16)<=load64(ticks+16)) {return 5;}
    if !FIXTURE_ELBOW && (load64(ps_pickup_targets)!=load64(ticks) || load64(ps_pickup_targets+16)!=load64(ticks+16) || load64(ps_pickup_targets+24)!=load64(ticks+24) || load64(ps_pickup_targets+8)<=load64(ticks+8)) {return 5;}
    i=0;while i<4000 && !ps_discovery_phase {if !ps_tick(0) || ps_arm_blocked {return 6;}i=i+1;}if ps_discovery_phase!=2 {return 7;}
    ps_discovery_enabled=0;i=0;while i<1500 && !ps_pickup_settled() {if !ps_tick(0) || ps_arm_blocked {return 8;}i=i+1;}if i==1500 {return 9;}
    ps_discovery_enabled=1;let point=alloc(24);ps_camera_compact_point(point,ps_pose_heading(),ps_number(16,1000));
    if !ps_arm_solve(point,370,75) || !ps_discovery_stage(4) {return 10;}
    i=0;while i<4000 && ps_discovery_phase!=5 {if !ps_tick(0) || ps_arm_blocked || ps_discovery_phase>=6 {return 11;}i=i+1;}
    if i==4000 || ps_discovery_arm_stops!=FIXTURE_GUARD || !ps_camera_drive_mode || !gs_reached(ps_plant,ps_pickup_targets) {return 12;}
    return 0;
}
'''
    with tempfile.TemporaryDirectory(prefix='discovery-recovery-',dir=ROOT/'build/flex/sim') as temporary:
        directory=Path(temporary)
        fixtures=[('forward',[.46363614427472577,1.6217462717844668,2.912222047755445],[427,299,3033,2843],2,1,-.148714346,1),
            ('extended',[1.0389609928118564,1.615460837039049,1.4265828085312355],[1144,346,3120,2636],0,0,.1913371793459644,1),
            ('folded',[.6328043558,1.6175698248,1.4681610251],[2804,267,3121,2521],0,0,math.pi,0)]
        # Reintegrating the recorded speeds through gs_step matches every
        # integer tick and restores these physical fractions after the stop.
        # Recovery itself still receives only ordinary integer encoders.
        for name,warm in [('doorway',0),('doorway-poll',3)]:
            fixtures.append((name,[2.8125024415750923,1.2135353733084275,1.6860331673396112],[1697,253,3105,2560],0,0,-.7351094731481503,0,[2.8219412242282464,1.1355924291272088,1.636348120772115],[1697320,253000,3105980,2560960],warm,1))
        for fixture in fixtures:
            name,pose,ticks,sector,tilt,bearing,elbow=fixture[:7]
            local=fixture[7] if len(fixture)>7 else [0,0,0];positions=fixture[8] if len(fixture)>8 else [t*1000 for t in ticks];warm=fixture[9] if len(fixture)>9 else 0
            guard=fixture[10] if len(fixture)>10 else 0
            text=source.replace('FIXTURE_SPAWN',json.dumps(json.dumps(pose))).replace('FIXTURE_TICKS',''.join(f'store64(ticks+{i*8},{t});' for i,t in enumerate(ticks)))
            text=text.replace('FIXTURE_POSITIONS',''.join(f'store64(positions+{i*8},{t});' for i,t in enumerate(positions))).replace('FIXTURE_WARM',str(warm)).replace('FIXTURE_GUARD',str(guard))
            text=text.replace('FIXTURE_LOCAL',''.join(f'{n}={hex(struct.unpack("<Q",struct.pack("<d",v))[0])};' for n,v in zip(['ps_local_x','ps_local_y','ps_local_heading'],local)))
            for key,value in [('SECTOR',str(sector)),('TILT',str(tilt)),('BEARING',hex(struct.unpack('<Q',struct.pack('<d',bearing))[0])),('ELBOW',str(elbow))]:text=text.replace('FIXTURE_'+key,value)
            entry,binary=directory/(name+'.flex'),directory/name;entry.write_text(text)
            subprocess.run([os.environ.get('FLEXSCRIPT_COMPILER',str(ROOT/'build/flex/pup-compiler')),str(entry),'-o',str(binary)],cwd=ROOT,check=True)
            subprocess.run([str(binary)],cwd=ROOT,check=True)
    print('Rejected-view recoveries passed: finger/forearm retraction and fractional doorway poses return to driving without another arm stop')


def stereo():
    with tempfile.TemporaryDirectory(prefix='discovery-stereo-', dir=ROOT/'build/flex/sim') as temporary:
        directory = Path(temporary)
        rng = np.random.default_rng(7)
        left = np.repeat(rng.integers(0, 256, (480,640,1), np.uint8),3,axis=2)
        right = np.zeros_like(left);right[:,:-42] = left[:,42:]
        frames = []
        for i,image in enumerate((left,right)):
            path=directory/f'{i}.rgb';path.write_bytes(image.tobytes())
            frames.append(dict(rgb=str(path),calibration=[0,.04-i*.08,.25,1,0,0,0,-1,0,0,0,-1]))
        cloud,_=mapping.cloud(frames)
        assert len(cloud)>1000 and abs(float(np.median(cloud[:,0]))-415.692*.08/42)<.02
        vertical=np.zeros_like(left);vertical[:-42]=left[42:];vframes=[]
        for i,image in enumerate((left,vertical)):
            path=directory/f'v{i}.rgb';path.write_bytes(image.tobytes())
            vframes.append(dict(rgb=str(path),calibration=[0,0,.29-i*.08,1,0,0,0,-1,0,0,0,-1]))
        vcloud,_=mapping.cloud(vframes)
        assert len(vcloud)>1000 and abs(float(np.median(vcloud[:,0]))-415.692*.08/42)<.02
        # Radial overhead views can give stereoRectify a negative alpha scale.
        # Ordering by projection translation alone then reconstructs the floor
        # above the camera. A rendered metric plane must work in either order.
        import cv2
        texture=rng.integers(30,225,(2048,2048),np.uint8)
        forward=np.array([-.4,0,-np.sqrt(.84)]);right_axis=np.array([0,-1,0]);down=np.cross(forward,right_axis)
        rotation=np.column_stack((right_axis,down,forward));yy,xx=np.indices((480,640))
        rays=np.stack(((xx-320)/415.6921938,(yy-240)/415.6921938,np.ones_like(xx)),axis=2)@rotation.T;radial=[]
        for i in range(2):
            eye=np.array([.011-i*.046,-.07,.462]);ground=eye+rays*(-eye[2]/rays[:,:,2,None]);uv=(ground[:,:,:2]*800+1024).astype(np.float32)
            image=np.repeat(cv2.remap(texture,uv[:,:,0],uv[:,:,1],cv2.INTER_LINEAR)[:,:,None],3,axis=2)
            path=directory/f'radial{i}.rgb';path.write_bytes(image.tobytes())
            radial.append(dict(rgb=str(path),calibration=[*eye,*forward,*right_axis,*down]))
        for pair in (radial,radial[::-1]):
            _,metrics=mapping.cloud(pair);assert metrics['verifiedFloorPixels']>5000
        # Identical periodic views can satisfy the ground homography at one
        # complete texture period despite having no measurable stereo depth.
        # The former photo-only rule falsely returned thousands of floor pixels.
        tile=rng.integers(30,225,(64,64),np.uint8)
        repeated=np.repeat(np.tile(tile,(8,10))[:480,:640,None],3,axis=2);aliases=[]
        for i in range(2):
            path=directory/f'alias{i}.rgb';path.write_bytes(repeated.tobytes())
            aliases.append(dict(rgb=str(path),calibration=[i*.08,0,415.6921938*.08/64,0,0,-1,1,0,0,0,-1,0]))
        ambiguous,metrics=mapping.cloud(aliases)
        assert len(ambiguous)==metrics['verifiedFloorPixels']==0
        for frame in frames:frame['calibration'][0]+=2;frame['calibration'][1]-=1
        shifted,_=mapping.cloud(frames)
        assert np.max(np.abs(shifted-cloud-[2,-1,0]))<1e-5
        for frame in frames:Path(frame['rgb']).write_bytes(bytes(480*640*3))
        result=mapping.run(dict(frames=frames,pose=[0,0,0],frameId=1,newScan=True),directory/'blackout')
        assert result['consistentPixels']==result['occupiedCells']==0 and result['goals']==[]
        assert result['freeCells']<=16 and result['safeCells']<=4
        cyan=np.zeros_like(left);cyan[:,:,1]=left[:,:,0];cyan[:,:,2]=left[:,:,0]
        for frame in frames:Path(frame['rgb']).write_bytes(cyan.tobytes())
        assert len(mapping.cloud(frames)[0])==0
        # A teal scene surface must survive when encoder FK says it is not
        # part of the rover. The same pixels inside a known robot box do not.
        for i,frame in enumerate(frames):
            frame['calibration'][0]-=2;frame['calibration'][1]+=1
            frame['robot']=[]
            image=np.zeros_like(cyan);image[:,:,1]=left[:,:,0];image[:,:,2]=left[:,:,0]
            if i:image[:,:-42]=image[:,42:]
            Path(frame['rgb']).write_bytes(image.tobytes())
        assert len(mapping.cloud(frames)[0])>1000
        box=[.8,0,.25,1,0,0,0,1,0,0,0,1,.1,1,1]
        for frame in frames:frame['robot']=[box]
        assert len(mapping.cloud(frames)[0])==0
        free=np.zeros((mapping.CELLS,mapping.CELLS),np.int32);occupied=np.zeros_like(free);detail=np.zeros((mapping.CELLS*5,mapping.CELLS*5),np.int16);height_seen=np.zeros(detail.shape,np.uint32);height_confirmed=np.zeros_like(height_seen)
        obstacle=np.repeat([[.65,.05,.12]],8,axis=0)
        mapping.update(free,occupied,obstacle,[0,0,0],detail,height_seen,height_confirmed)
        assert not mapping.navigation(free,occupied,[0,0,0],[])[2].any()
        mapping.update(free,occupied,obstacle,[0,0,0],detail,height_seen,height_confirmed)
        safe,known,blocked,_=mapping.navigation(free,occupied,[0,0,0],[])
        assert blocked.sum()==1 and not (safe & blocked).any() and not (known & blocked).any()
        # A stale vote at a rotated footprint corner must not imprison the
        # rover in its own map; a remote confirmed obstacle stays blocked.
        pose=[-.2658660887,-.6810288556,-2.5954533104]
        c,s=math.cos(pose[2]),math.sin(pose[2]);corner=np.array(pose[:2])+np.array([[c,-s],[s,c]])@np.array([-.14,.11])
        col,row=mapping.cell(corner);occupied[row,col]=2;detail[row*5:(row+1)*5,col*5:(col+1)*5]=2;height_seen[row*5:(row+1)*5,col*5:(col+1)*5]=1;height_confirmed[row*5:(row+1)*5,col*5:(col+1)*5]=1
        mapping.update(free,occupied,np.empty((0,3)),pose,detail,height_seen,height_confirmed)
        assert occupied[row,col]==0 and mapping.navigation(free,occupied,pose,[])[1][row,col]
        assert occupied[mapping.cell([.65,.05])[1],mapping.cell([.65,.05])[0]]==2
        # Floor in another part of the same navigation cell cannot erase a
        # leg. Only direct floor observations contradict its fine location.
        col,row=mapping.cell([.65,.05]);nearby=np.repeat([[.61,.01,0]],8,axis=0)
        for _ in range(4):mapping.update(free,occupied,nearby,[0,0,0],detail,height_seen,height_confirmed)
        for _ in range(4):mapping.update(free,occupied,np.empty((0,3)),[0,0,0],detail,height_seen,height_confirmed)
        assert occupied[row,col]==2
        direct=np.repeat([[.65,.05,0]],8,axis=0)
        for _ in range(2):mapping.update(free,occupied,direct,[0,0,0],detail,height_seen,height_confirmed)
        assert occupied[row,col]==0 and mapping.navigation(free,occupied,[0,0,0],[])[1][row,col]
        mixed=np.vstack((direct,obstacle))
        for _ in range(2):mapping.update(free,occupied,mixed,[0,0,0],detail,height_seen,height_confirmed)
        assert occupied[row,col]==2
        free[:]=0;occupied[:]=0;detail[:]=0;height_seen[:]=0;height_confirmed[:]=0
        raised=np.repeat([[.65,.05,.18]],8,axis=0)
        mapping.update(free,occupied,obstacle,[0,0,0],detail,height_seen,height_confirmed)
        mapping.update(free,occupied,raised,[0,0,0],detail,height_seen,height_confirmed)
        assert occupied[row,col]==0
        mapping.update(free,occupied,raised,[0,0,0],detail,height_seen,height_confirmed)
        assert occupied[row,col]>=2
    print('Stereo checks passed: metric baseline reconstruction, coordinate equivariance, periodic aliases and blackout preserve unknown space')


def evidence_persistence():
    """Replay sensor points through fresh workers to check saved map evidence."""
    with tempfile.TemporaryDirectory(prefix='discovery-evidence-',dir=ROOT/'build/flex/sim') as temporary:
        directory=Path(temporary)
        def step(points,frame,output=directory):
            worker=importlib.util.module_from_spec(spec);spec.loader.exec_module(worker)
            worker.cloud=lambda frames:(np.asarray(points).reshape(-1,3),{})
            return worker.run(dict(frames=[{},{}],pose=[0,0,0],frameId=frame,newScan=False),output)
        obstacle=np.repeat([[.65,.05,.12]],8,axis=0)
        assert step(obstacle,1)['occupiedCells']==0
        assert step(obstacle,2)['occupiedCells']==1
        with np.load(directory/'evidence.npz') as saved:
            assert saved['detail'].shape==(1000,1000) and saved['detail'].dtype==np.int16
            assert saved['heightSeen'].dtype==saved['heightConfirmed'].dtype==np.uint32 and saved['heightConfirmed'].any()
            legacy=directory/'legacy';legacy.mkdir()
            np.savez_compressed(legacy/'evidence.npz',free=saved['free'],occupied=saved['occupied'],visits=saved['visits'])
        assert step([],3,legacy)['occupiedCells']==1
        assert step(np.repeat([[.61,.01,0]],8,axis=0),3)['occupiedCells']==1
        fine=np.frombuffer((directory/'observed-detail.bin').read_bytes(),np.uint8).reshape(1000,1000)
        assert fine[500,530]==0 and fine[502,532]==1 and fine[504,534]==1
        assert step([],4)['occupiedCells']==1
        assert (directory/'observed-detail.bin').read_bytes()==fine.tobytes()
        assert step(np.repeat([[.65,.05,0]],8,axis=0),5)['occupiedCells']==0
        fine=np.frombuffer((directory/'observed-detail.bin').read_bytes(),np.uint8).reshape(1000,1000)
        assert fine[502,532]==0 and fine[504,534]==1
        assert step([],6,legacy)['occupiedCells']==1
        assert np.frombuffer((legacy/'observed-detail.bin').read_bytes(),np.uint8).reshape(1000,1000)[500,530]==1
        heights=directory/'heights'
        assert step(obstacle,1,heights)['occupiedCells']==0
        raised=np.repeat([[.65,.05,.18]],8,axis=0)
        assert step(raised,2,heights)['occupiedCells']==0
        assert step(raised,3,heights)['occupiedCells']==1
    print('Map evidence checks passed: fresh workers retain unseen obstacles, preserve legs beside floor, clear direct contradictions and read legacy maps conservatively')


def rescan_evidence(directory):
    """Recorded RGB floor cells from the v26 reverse-view scan, not scene truth."""
    rows=['############','######...###','#####....###','##........##',
        '###.......##','####........','####....#...','####.......#',
        '##.........#','##.........#','##.......###','######.#####']
    observed=np.ones((200,200),np.uint8)
    observed[94:106,94:106]=np.array([[c!='.' for c in row] for row in rows[::-1]],np.uint8)
    observed[99,106]=0
    assert int((observed==0).sum())==71
    free=(observed==0).astype(np.int32)*3;occupied=np.zeros_like(free);visits=np.zeros((1,3))
    safe,known,_,goals=mapping.navigation(free,occupied,[0,0,0],visits.tolist())
    assert goals and np.array_equal(known,observed==0)
    directory.mkdir(parents=True,exist_ok=False)
    np.savez_compressed(directory/'evidence.npz',free=free,occupied=occupied,visits=visits,
        detail=np.zeros((1000,1000),np.int16),heightSeen=np.zeros((1000,1000),np.uint32),heightConfirmed=np.zeros((1000,1000),np.uint32))
    (directory/'observed.bin').write_bytes(observed.tobytes())
    (directory/'safe.bin').write_bytes((~safe).astype(np.uint8).tobytes())
    (directory/'goals.bin').write_bytes(struct.pack('<Q',len(goals))+np.asarray(goals,dtype='<f8').tobytes())


def reverse_view(directory, fixtures=None):
    """Render a local frontier behind the chassis on an initially unknown map."""
    directory.mkdir(parents=True,exist_ok=False)
    source=(ROOT/'flex/sim/main.flex').read_text().replace('fn main(argc, argv)','fn ps_application_main(argc, argv)')
    source=re.sub(r'^import "([^"]+)";',lambda m:'import '+json.dumps(str(ROOT/'flex/sim'/m[1]))+';',source,flags=re.MULTILINE)
    source+=r'''
fn main(argc,argv) {
    if !pl_init() {return 1;}h_environment(argc,argv);
    let rescan=argc>2 && pl_equal(load64(argv+16),"reverse-retry");let reverse=argc<=2 || rescan || pl_equal(load64(argv+16),"west-return");
    let spawn="[0.1972920937,-0.7740240372,2.123101798]";if argc>2 {spawn="[2.7602525717,-2.7386502625,2.4976268648]";}
    if rescan {spawn="[0.1972920937,-0.7740240372,2.123101798]";}
    if argc>2 && pl_equal(load64(argv+16),"west") {spawn="[-0.7868559213,1.2499371928,1.9087379759]";}
    if argc>2 && pl_equal(load64(argv+16),"west-tight") {spawn="[-0.8115711197,1.3256880464,1.4331808897]";}
    // The recorded v37 wall trap, starting with no inherited map evidence.
    if argc>2 && pl_equal(load64(argv+16),"west-return") {spawn="[-0.8073159677016064,0.29884270620807946,1.395954840908308]";}
    if argc>2 && pl_equal(load64(argv+16),"sofa") {spawn="[0.0516428192,1.4832048352,0.3226087053]";}
    if argc>2 && pl_equal(load64(argv+16),"sofa-tight") {spawn="[0.6328043558,1.6175698248,1.4681610251]";}
    if argc>2 && pl_equal(load64(argv+16),"sofa-recovery") {spawn="[0.46363614427472577,1.6217462717844668,2.912222047755445]";}
    if argc>2 && pl_equal(load64(argv+16),"sofa-extended") {spawn="[1.0389609928118564,1.615460837039049,1.4265828085312355]";}
    if !ps_catalog_load() || !ps_case_load(ps_case_find("discover-house-blocks-into-box")) || !ps_environment_load("build/flex/sim/environments/apartment/apartment.bin") || !ps_model_load("build/flex/sim/puppybot.bin") || !ps_environment_spawn(spawn) {return 2;}
    ps_robot=alloc(8192);ps_system=alloc(2048);ps_config=alloc(448);ps_app=alloc(2048);ps_bus=alloc(16384);ps_plant=alloc(2048);ps_trace=alloc(69632);ps_json=alloc(16384);ps_builder=alloc(32);pb_config_default(ps_config);pb_vset(ps_config+40,2,5);
    ps_collect_enabled=0;if !ps_reset() {return 3;}ps_case_phase(0);ps_discovery_full=1;ps_discovery_limit=1;if reverse {ps_discovery_limit=4;}ps_discovery_root=h_cat(load64(argv+8),"/map");
    let i=0;while i<40000 {if load8(ps_discovery_observed+i)!=1 {return 4;}i=i+1;}
    // This synthetic local frontier stands for a reverse arrival; it is not
    // a room itinerary, supplied map, or object target.
    let point=alloc(24);store64(point,ps_number(-4,10));store64(point+16,PB_PI);ps_discovery_frontier_focus(point);
    let speed=ps_trace+1400;store64(speed,200);pr_apply(ps_app,1,speed,ps_time);ps_render_init(1);
    if rescan {
        // Restore only recorded sensor evidence. Native planning must reject
        // every proposed exit before the new wrist views are acquired.
        ps_discovery_initialized=1;ps_discovery_directory=h_cat(ps_discovery_root,"/episode-0");
        if pl_read_file(h_cat(ps_discovery_directory,"/observed.bin"),ps_discovery_observed,40000)!=40000 || pl_read_file(h_cat(ps_discovery_directory,"/safe.bin"),ps_nav_map,40000)!=40000 {return 16;}
        let data=alloc(201);let size=pl_read_file(h_cat(ps_discovery_directory,"/goals.bin"),data,200);ps_discovery_goal_count=load64(data);
        if ps_discovery_goal_count<1 || ps_discovery_goal_count>8 || size!=8+ps_discovery_goal_count*24 {return 17;}pb_copy(ps_discovery_goals,data+8,ps_discovery_goal_count*24);i=0;
        while i<ps_discovery_goal_count {let goal=ps_discovery_goals+i*24;if ps_nav_plan(load64(goal),load64(goal+8),load64(goal+16)) {return 18;}i=i+1;}
        ps_discovery_bearing=PB_PI;ps_discovery_sector=8;ps_discovery_tilt=1;
        if !ps_discovery_next_sector() || ps_discovery_rescans!=1 {return 19;}
    }
    if argc>2 && (pl_equal(load64(argv+16),"sofa-recovery") || pl_equal(load64(argv+16),"sofa-extended")) {
        // Resume the recorded rejected-view event in an otherwise unknown
        // local map. All following motion, RGB and geometry are simulated.
        let ticks=alloc(32);store64(ticks,427);store64(ticks+8,299);store64(ticks+16,3033);store64(ticks+24,2843);i=0;
        if pl_equal(load64(argv+16),"sofa-extended") {store64(ticks,1144);store64(ticks+8,346);store64(ticks+16,3120);store64(ticks+24,2636);}
        while i<4 {let j=ps_plant+128+i*64;let tick=load64(ticks+i*8);store64(j,tick*1000);store64(j+8,0);store64(j+16,tick);pb_fake_servo(ps_bus,load64(j+24),tick);pb_arm_feedback(ps_robot,i,tick,ps_time);i=i+1;}
        ps_gripper_gap=0;ps_gripper_goal=0;ps_model_update(ps_robot,ps_plant,ps_x,ps_y,ps_heading,ps_wheel);ps_gripper_frame_update(ps_robot,ps_plant);ps_arm_proxy_update(1);
        if !ps_solid_free(ps_x,ps_y,ps_heading) {return 13;}
        ps_discovery_initialized=1;ps_discovery_directory=h_cat(ps_discovery_root,"/episode-0");
        if syscall(83,ps_discovery_root,493,0,0,0,0) || syscall(83,ps_discovery_directory,493,0,0,0,0) {return 14;}
        ps_discovery_phase=2;ps_discovery_sector=2;ps_discovery_tilt=1;ps_discovery_side=1;ps_discovery_bearing=ps_number(-148714346,1000000000);
        if pl_equal(load64(argv+16),"sofa-extended") {ps_discovery_sector=0;ps_discovery_tilt=0;ps_discovery_side=0;ps_discovery_bearing=ps_number(191337179,1000000000);}
        if !ps_discovery_arm_stop() {return 15;}
    }

    ps_output=syscall(2,h_cat(load64(argv+8),"/trace.jsonl"),0x800c1,384,0,0,0);if ps_output<0 {return 5;}
    i=0;while i<30000 && ps_discovery_phase<6 && (!reverse || ps_discovery_phase!=5) {if !ps_tick(0) {return 6;}i=i+1;}
    if ps_discovery_phase!=6 && !(reverse && ps_discovery_phase==5) {ps_observation();pl_print(1,ps_json);return 7;}
    if reverse {let found=0;i=0;while i<ps_discovery_goal_count && !found {let p=ps_discovery_goals+i*24;found=ps_nav_plan(load64(p),load64(p+8),load64(p+16));i=i+1;}if !found || ps_discovery_phase!=5 {return 8;}
        // The controller has produced a usable exit. Keep the fixture parked
        // while independently checking its forward camera calibration.
        pb_drive_stop(pb_robot_drive(ps_robot),ps_time);ps_discovery_phase=6;
    }
    if ps_discovery_raised_only {
        // Exercise the actual recovery sequence, including its tucked turn
        // and the return from the raised scan to the low driving posture.
        ps_camera_compact_point(point,ps_pose_heading(),ps_number(16,1000));
        if !ps_arm_solve(point,370,75) || !ps_discovery_stage(4) {return 9;}
        i=0;while i<4000 && ps_discovery_phase!=5 {if !ps_tick(0) || ps_arm_blocked || ps_discovery_phase>=6 {return 10;}i=i+1;}if i==4000 {return 11;}
    } else {
        if !ps_camera_drive_target() {return 9;}i=0;while i<1500 && !ps_pickup_settled() {if !ps_tick(0) || ps_arm_blocked {return 10;}i=i+1;}if i==1500 {return 11;}
    }
    if argc>2 && pl_equal(load64(argv+16),"west-return") {
        // Execute the camera-mapped exit, rather than proving only that a
        // planner returned a path beside the recorded wall configuration.
        i=0;while i<2000 && !ps_nav_tick() {if !ps_tick(0) || ps_blocked || ps_arm_blocked {return 20;}i=i+1;}
        if i==2000 || f64_lt(ps_local_distance,ps_number(2,10)) {return 21;}
    }
    ps_brick_output=load64(argv+8);if !ps_rgb_sample() {return 12;}
    ps_observation();pl_print(1,ps_json);syscall(3,ps_output,0,0,0,0,0);ps_render_close();return 0;
}
'''
    entry,binary=directory/'probe.flex',directory/'probe';entry.write_text(source)
    subprocess.run([os.environ.get('FLEXSCRIPT_COMPILER',str(ROOT/'build/flex/pup-compiler')),str(entry),'-o',str(binary)],cwd=ROOT,check=True)
    if fixtures is None:fixtures=[('west-tight',['west-tight']),('west',['west']),('corner',['corner']),('reverse',[]),('west-return',['west-return'])]
    for name,extra in fixtures:
        output=directory/name;output.mkdir()
        if name=='reverse-retry':rescan_evidence(output/'map/episode-0')
        result=subprocess.run([str(binary),str(output.resolve()),*extra],cwd=ROOT,capture_output=True,text=True,timeout=480)
        (output/'run.log').write_text(result.stdout+result.stderr)
        assert result.returncode==0,(name,result.returncode,result.stdout[-2000:],result.stderr)
        state=json.loads(result.stdout.splitlines()[-1]);assert state['discovery']['images']>=4
        if name=='sofa-recovery':assert abs(state['discovery']['scanBearingRad']+.148714346)<1e-9
        elif name=='sofa-extended':assert abs(state['discovery']['scanBearingRad']-.191337179)<1e-9
        else:assert abs(state['discovery']['scanBearingRad'])>3
        assert state['gripper']['openingMm']==0 and not state['gripper']['held']
        episode=output/'map/episode-0';requests=sorted((json.loads(p.read_text()) for p in episode.glob('input-*.json')),key=lambda r:r['frameId'])
        assert requests and sum(r['newScan'] for r in requests)==state['discovery']['scans']-(name=='reverse-retry')
        spec=importlib.util.spec_from_file_location('pickup_geometry',Path(__file__).with_name('sim-discovery-pickup.py'))
        geometry=importlib.util.module_from_spec(spec);spec.loader.exec_module(geometry);judge=geometry.HeldGeometry()
        needed={frame['frameId'] for request in requests for frame in request['frames']};models={};previous=None
        for line in (output/'trace.jsonl').open():
            snapshot=json.loads(line)
            assert not snapshot['physicsFault']
            if name=='reverse-retry':
                assert np.allclose(snapshot['pose'],[.1972920937,-.7740240372,2.123101798],atol=1e-9,rtol=0)
            if snapshot['collision']['armBlocked']:
                assert previous is not None and snapshot['ticks']==previous['ticks'] and snapshot['pose']==previous['pose']
            previous=snapshot
            if snapshot['totalSteps'] in needed:models[snapshot['totalSteps']]=judge.robot_boxes(snapshot)
        for request in requests:
            for frame in request['frames']:assert np.allclose(frame['robot'],models[frame['frameId']],atol=1e-8,rtol=0)
            first,second=(np.array(frame['calibration']).reshape(4,3) for frame in request['frames'])
            assert .025<=np.linalg.norm(first[0]-second[0])<=.15
            assert np.dot(first[1],second[1])>.99
        metadata=json.loads((output/(state['case']['perception']['image']+'.camera.json')).read_text())
        assert metadata['imageRotationDeg']==180 and metadata['down'][2]<-.5
        x,y,heading=state['pose'];c,s=math.cos(heading),math.sin(heading);rotation=np.array([[c,-s,0],[s,c,0],[0,0,1]])
        actual=np.array([metadata[key] for key in ('eyeM','forward','right','down')]);actual[0]-=[x,y,0];actual=actual@rotation
        estimated=np.array(state['case']['perception']['calibration']).reshape(4,3)
        lx,ly,lh=state['localization']['pose'];c,s=math.cos(lh),math.sin(lh);local_rotation=np.array([[c,-s,0],[s,c,0],[0,0,1]])
        estimated[0]-=[lx,ly,0];estimated=estimated@local_rotation
        assert estimated[1,0]>.7,estimated[1]
        assert np.linalg.norm(actual[0]-estimated[0])<.003 and np.max(np.linalg.norm(actual[1:]-estimated[1:],axis=1))<.01
        if extra and name!='reverse-retry':
            if name in ('sofa-recovery','sofa-extended'):assert state['discovery']['armProtectiveStops']==1
            elif name=='sofa-tight':assert state['discovery']['armProtectiveStops']<=1
            else:assert state['discovery']['armProtectiveStops']==0
            if name=='sofa':assert state['discovery']['occupiedCells']>=2,state['discovery']
            if name=='sofa':print('Teal sofa scan passed: encoder-derived self mask retains furniture obstacles and completes scanning/drive-pose transfer without an arm stop')
            elif name in ('sofa-recovery','sofa-extended'):print(f'{name.capitalize()} scan passed: encoder-derived envelope recovery completes the remaining calibrated RGB scan and returns to driving without another arm stop')
            elif name=='sofa-tight':print('Recorded sofa-base scan passed: at most one protected view rejection, calibrated images, completed scan and clear staged return to the forward driving pose')
            elif name=='west-return':
                assert state['discovery']['protectiveStops']==0 and state['localization']['estimatedDistanceM']>.2
                assert state['case']['navigation']['pathIndex']==state['case']['navigation']['pathCount']
                print('Recorded west-wall pose passed: an initially unknown map produces a complete exit, executed without a drive or arm stop, with calibrated wrist images')
            else:print(f'{name.capitalize()} scan passed: compact wrist scans and reaches its calibrated driving pose beside walls without an arm stop')
        else:
            # The first three bearings must still inspect the reverse frontier.
            # A complete surrounding scan must then expose a usable car exit;
            # compact wrist views can leave a chassis shadow in the first arc.
            if name=='reverse-retry':
                # Restored evidence already includes forward floor. Check the
                # new camera bearings rather than counting those old cells.
                assert all(f['calibration'][3]<-.2 for r in requests[:6] for f in r['frames'])
            else:
                observed=np.fromfile(episode/f'observed-{requests[5]["frameId"]}.bin',np.uint8).reshape(200,200)==0;rows,cols=np.nonzero(observed)
                xs=(cols+.5)*.1-10;behind=int((xs<-.25).sum());ahead=int((xs>.25).sum());assert behind>ahead,(behind,ahead)
            assert state['case']['navigation']['pathCount']>0
            assert state['discovery']['scans']<=3 and state['discovery']['phase']==6
            assert state['discovery']['armProtectiveStops']==0
            if name=='reverse-retry':
                assert state['discovery']['scans']>=2 and state['discovery']['freeCells']>71
                print('No-exit rescan passed: recorded RGB map rejects every initial frontier, fresh alternate stereo views expose a reachable car exit without chassis motion or an arm stop')
            else:print(f'Reverse-frontier view passed: {behind} rear floor cells versus {ahead} forward, a reachable car path, and calibrated compact driving view')


def audit(path):
    first=last=previous=None;distance=0;stops=0;random=None
    for line in path.open():
        state=json.loads(line);d=state['discovery'];local=state['localization']
        if first is None:first=state;random=local['seed']
        assert state['case'] is None and not d['suppliedMap'] and not d['worldPoseInput']
        assert local['initialPrior']=='local-origin' and local['cameraCalibration']=='estimated-base-and-joint-feedback'
        assert not state.get('breadcrumbs',{}).get('groundHeading',{}).get('mapAxisKnown',False)
        assert state['physicsFault']==state['vehicle']['queryFault']==0
        if previous:
            movement=math.dist(state['pose'][:2],previous['pose'][:2]);assert movement<.010001
            if state['blocked']:assert movement<1e-9
            if state['collision']['armBlocked']:assert state['ticks']==previous['ticks'] and movement<1e-9
            drive=previous['controller']['drive']
            travelled=(drive['leftSpeed']+drive['rightSpeed'])/20000
            assert movement<=abs(travelled)+1e-9
            if not state['blocked']:
                x,y,heading=previous['pose']
                heading=(heading-travelled/.18*math.tan(math.radians(drive['steeringAngleDeg']-90))+math.pi)%(2*math.pi)-math.pi
                expected=[x+travelled*math.cos(heading),y+travelled*math.sin(heading),heading]
                assert math.dist(state['pose'][:2],expected[:2])<1e-8
                assert abs((state['pose'][2]-heading+math.pi)%(2*math.pi)-math.pi)<1e-8
            if 'breadcrumbs' in state:
                steering=math.radians(drive['steeringAngleDeg']-90)
                if travelled and local['mode']=='wheel-drift':
                    random=(random*1664525+1013904223)&0xffffffff
                    travelled*=1+local['driftPermille']/1000*(1+(random%2001-1000)/5000)
                    steering+=math.radians(local['driftPermille']/50)
                x,y,heading=previous['localization']['pose']
                heading=(heading-travelled/.18*math.tan(steering)+math.pi)%(2*math.pi)-math.pi
                expected=np.array([x+travelled*math.cos(heading),y+travelled*math.sin(heading),heading])+state['breadcrumbs']['correctionDelta']
                assert math.dist(local['pose'][:2],expected[:2])<1e-8
                assert abs((local['pose'][2]-expected[2]+math.pi)%(2*math.pi)-math.pi)<1e-8
            distance+=movement
        stops+=bool(state['blocked']);last=previous=state
    assert first['discovery']['freeCells']==first['discovery']['occupiedCells']==first['discovery']['safeCells']==0
    assert last['discovery']['phase']==6 and last['discovery']['scans']>=2
    assert distance>.15 and last['discovery']['freeCells']>30
    report=dict(last['discovery'],schema='puppybot.discovery-audit.v1',passed=True,steps=last['step'],distanceM=distance,protectiveStopFrames=stops)
    (path.parent/'discovery-audit.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


def frontier_selection():
    free=np.zeros((200,200),np.int32);occupied=np.zeros_like(free)
    free[90:111,95:121]=10
    safe,known,blocked,goals=mapping.navigation(free,occupied,[0,0,0],[])
    expected=np.zeros_like(known);expected[91:110,96:120]=True
    assert np.array_equal(safe,expected) and np.array_equal(known,free>0) and not blocked.any()
    assert len(goals)==8
    cells=[mapping.cell(goal[:2]) for goal in goals]
    assert all(97<=x<=118 and 92<=y<=108 for x,y in cells[:6])
    assert all(not (97<=x<=118 and 92<=y<=108) for x,y in cells[6:])
    # A passage with no five-cell clearance must retain its ordinary
    # frontiers and the original three-cell traversability grid.
    free[:]=0;free[99:102,95:141]=10
    safe,known,blocked,goals=mapping.navigation(free,occupied,[.05,.05,0],[])
    expected[:]=False;expected[100,96:140]=True
    assert goals and np.array_equal(safe,expected) and np.array_equal(known,free>0) and not blocked.any()
    assert all(safe[tuple(mapping.cell(goal[:2])[::-1])] for goal in goals)
    # A frontier visited before forty later scans must remain less novel.
    # This only changes ranking; the floor and collision masks stay intact.
    free[:]=0;free[90:111,90:111]=3;pose=[.05,.05,0];recent=[pose]*40
    before=mapping.navigation(free,occupied,pose,recent);old=before[3][0]
    after=mapping.navigation(free,occupied,pose,[old]*4+recent)
    assert all(np.array_equal(a,b) for a,b in zip(before[:3],after[:3]))
    assert math.dist(old[:2],after[3][0][:2])>.5
    print('Frontier selection passed: room to steer, narrow passages and older scan visits are retained without changing binary map evidence')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--trace',type=Path);parser.add_argument('--reverse-view',type=Path,help='run the local reverse-frontier RGB fixture in a new directory');parser.add_argument('--sofa-view',type=Path,help='check that teal furniture remains observable beside the rover');parser.add_argument('--rescan-view',type=Path,help='recover a reachable exit from recorded RGB evidence with alternate wrist views');args=parser.parse_args()
    isolation();control();recovery();stereo();evidence_persistence();frontier_selection()
    if args.reverse_view:reverse_view(args.reverse_view)
    if args.sofa_view:reverse_view(args.sofa_view,[('sofa-extended',['sofa-extended']),('sofa-recovery',['sofa-recovery']),('sofa-tight',['sofa-tight']),('sofa',['sofa'])])
    if args.rescan_view:reverse_view(args.rescan_view,[('reverse-retry',['reverse-retry'])])
    if args.trace:audit(args.trace)


if __name__=='__main__':main()
