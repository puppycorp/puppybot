#!/usr/bin/env python3
"""Exercise docking-refinement safety gates with deterministic CPU-only mocks."""
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def function(source, name):
    match = re.search(r'\bfn\s+' + re.escape(name) + r'\s*\(', source)
    if not match:
        raise ValueError(f'missing {name}')
    begin = source.index('{', match.start())
    depth = 1
    end = begin + 1
    quoted = False
    escaped = False
    while depth:
        char = source[end]
        if quoted:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
        end += 1
    return source[match.start():end]


def main():
    original = (ROOT / 'flex/sim/dock-search.flex').read_text()
    physical_reply = function((ROOT / 'flex/sim/agent.flex').read_text(), 'ps_physical_observe')
    if 'ps_observation(' in physical_reply or 'stageDiagnostic' in physical_reply:
        raise ValueError('physical actor reply must not include trace diagnostics')
    selected = '\n'.join(function(original, name) for name in
                         ('ps_dock_refine_allowed', 'ps_dock_refine_alive', 'ps_dock_refine_abort', 'ps_dock_refine_success', 'ps_dock_coarse_success', 'ps_dock_search_refine', 'ps_dock_search_next', 'ps_dock_search_observation'))
    selected += '\n' + function(original, 'ps_dock_search_stage').replace('fn ps_dock_search_stage(', 'fn tested_stage(')
    selected += '\n' + function((ROOT / 'flex/sim/collect.flex').read_text(), 'ps_collect_map_finish')
    selected += '\n' + function((ROOT / 'flex/sim/navigation.flex').read_text(), 'ps_nav_before_deadline')
    for old, new in {'pl_now': 'mock_now', 'ps_pose_x': 'mock_pose_x', 'ps_pose_y': 'mock_pose_y', 'ps_pose_heading': 'mock_pose_heading',
                     'ps_nav_clear': 'mock_nav_clear', 'ps_case_drop_clearance': 'mock_drop_clearance',
                     'ps_nav_plan_release': 'mock_plan_release', 'ps_nav_end_pose': 'mock_end_pose',
                     'ps_house_parking_clear': 'mock_parking_clear', 'ps_case_fail': 'mock_case_fail',
                     'ps_dock_fresh': 'mock_fresh', 'ps_dock_search_stage': 'mock_stage_failure',
                     'ps_case_travel_pose': 'mock_travel_pose', 'ps_collect_map_begin': 'mock_map_begin',
                     'ps_dock_search_candidate': 'mock_candidate', 'ps_nav_plan': 'mock_nav_plan',
                     'ps_case_drop_find': 'mock_drop_find',
                     'ps_collect_map_end': 'mock_map_end', 'ps_discovery_next_sector': 'mock_next_sector',
                     'pb_robot_drive': 'mock_robot_drive', 'pb_drive_stop': 'mock_drive_stop'}.items():
        selected = re.sub(r'\b' + old + r'\s*\(', new + '(', selected)
    source = 'import ' + json.dumps(str(ROOT / 'flex/control/host.flex')) + ';\n'
    source += r'''
global ps_nav_wall_deadline=0;global ps_nav_deadline_fault=0;global ps_nav_path_count=0;global ps_nav_path_index=0;global ps_nav_remaining=0;
global ps_dock_refine_plans=0;global ps_robot=0;global ps_time=0;global ps_dock_search_endpoint=0;global ps_dock_search_goal=0;global ps_nav_goal=0;
global ps_dock_coarse_successes=0;global ps_dock_refine_entries=0;global ps_dock_refine_successes=0;global ps_dock_refine_empty=0;global ps_dock_refine_timeouts=0;global ps_dock_refine_clock_faults=0;global ps_dock_refine_budget_faults=0;global ps_dock_refine_fault=0;global ps_dock_refine_last=0;
global ps_agent_physical=1;global ps_collect_enabled=1;global ps_case_stage=0;global ps_dock_search_staged=0;global ps_dock_search_index=0;global ps_dock_stable=3;global ps_dock_search_mode=0;global ps_dock_seen=0;
global ps_dock_search_candidates=0;global ps_dock_search_anchor=0;global ps_dock_frame=0;
global ps_dock_search_blocks=0;global ps_dock_search_maps=0;global ps_dock_search_active=0;global ps_output=-1;
global mock_clock=0;global mock_nav=1;global mock_ik=1;global mock_route=1;global mock_end_nav=1;global mock_end_ik=1;global mock_park=0;global mock_clock_on_plan=0;global mock_stop_count=0;global mock_map_count=0;global mock_move_count=0;global mock_hint_count=0;global mock_fresh_value=1;
global mock_find_value=1;global mock_clock_transient=0;
fn ps_number(n,d) {return f64_div(f64_from_i64(n),f64_from_i64(d));}
fn mock_now() {return mock_clock;} fn mock_pose_x() {return 0;} fn mock_pose_y() {return 0;} fn mock_pose_heading() {return 0;}
fn mock_nav_clear(x,y,h) {if f64_gt(x,f64_from_i64(5)) {return mock_end_nav;}return mock_nav;}
fn mock_drop_clearance(height,x,y,h) {if f64_gt(x,f64_from_i64(5)) {return mock_end_ik;}return mock_ik;}
fn mock_plan_release(x,y,h) {if mock_clock_transient {mock_clock_transient=0;mock_clock=-1;ps_nav_before_deadline();mock_clock=0;return 0;}if mock_clock_on_plan {mock_clock=100;}store64(ps_nav_goal,x);store64(ps_nav_goal+8,y);store64(ps_nav_goal+16,h);return mock_route;}
fn mock_end_pose(out) {store64(out,f64_from_i64(9));store64(out+8,0);store64(out+16,0);return 1;}
fn mock_parking_clear(end,goal) {return mock_park;}
fn mock_case_fail(reason) {ps_case_stage=13;mock_stop_count=mock_stop_count+1;return 0;}
fn mock_fresh() {return mock_fresh_value;} fn mock_stage_failure() {return mock_case_fail("injected timeout");}
fn mock_travel_pose() {mock_move_count=mock_move_count+1;return 1;} fn mock_map_begin() {mock_map_count=mock_map_count+1;return 1;}
fn mock_candidate(index,out) {return 1;} fn mock_nav_plan(x,y,h) {mock_move_count=mock_move_count+1;return 1;}
fn mock_map_end() {mock_map_count=mock_map_count+1;return 1;} fn mock_next_sector() {mock_move_count=mock_move_count+1;return 1;}
fn mock_robot_drive(robot) {return 0;} fn mock_drive_stop(drive,now) {mock_stop_count=mock_stop_count+1;return 0;}
fn mock_drop_find(height,x,y,h) {mock_hint_count=mock_hint_count+1;if !mock_find_value {return 0;}mock_ik=1;return 1;}
'''
    source += selected
    source += r'''
fn main(argc,argv) {
 vc_init(argc,argv);ps_dock_search_endpoint=alloc(24);ps_dock_search_goal=alloc(24);ps_nav_goal=alloc(24);let seed=alloc(32);store64(seed,ps_number(2,10));
 ps_nav_wall_deadline=0;ps_nav_deadline_fault=77;mock_clock=-1;vc_require(ps_nav_before_deadline() && ps_nav_deadline_fault==77,"legacy planner changed without deadline");
 ps_nav_wall_deadline=100;ps_nav_deadline_fault=0;vc_require(!ps_nav_before_deadline() && ps_nav_deadline_fault==2,"planner accepted failed clock");mock_clock=99;vc_require(!ps_nav_before_deadline() && ps_nav_deadline_fault==2,"planner forgot a transient clock fault");
 ps_nav_deadline_fault=0;vc_require(ps_nav_before_deadline(),"planner rejected valid deadline");mock_clock=100;vc_require(!ps_nav_before_deadline() && ps_nav_deadline_fault==1,"planner accepted expired deadline");mock_clock=0;vc_require(!ps_nav_before_deadline() && ps_nav_deadline_fault==1,"planner forgot an expired deadline");ps_nav_wall_deadline=0;
 vc_require(ps_dock_refine_allowed(1,1,1,3) && !ps_dock_refine_allowed(1,0,1,3) && !ps_dock_refine_allowed(1,1,0,3) && !ps_dock_refine_allowed(1,1,1,2) && !ps_dock_refine_allowed(0,1,1,3),"physical opt-in or fresh RGB gate failed");
 mock_nav=0;vc_require(!ps_dock_search_refine(seed,100) && !ps_dock_refine_plans,"unknown/blocked floor accepted");
 mock_nav=1;mock_ik=0;vc_require(!ps_dock_search_refine(seed,100) && !ps_dock_refine_plans,"unreachable release accepted");
 mock_ik=1;mock_route=0;vc_require(!ps_dock_search_refine(seed,100) && ps_dock_refine_plans==2 && ps_dock_refine_budget_faults==1 && ps_dock_refine_last==7,"failed route or plan budget accepted or misreported");
 ps_dock_refine_plans=0;mock_route=1;mock_end_nav=0;mock_park=0;vc_require(!ps_dock_search_refine(seed,100) && ps_dock_refine_plans==2,"unsafe arrival accepted");
 ps_dock_refine_plans=0;mock_end_nav=1;mock_end_ik=1;vc_require(ps_dock_search_refine(seed,100) && f64_eq(load64(ps_dock_search_goal),f64_from_i64(9)) && ps_dock_refine_successes==1 && ps_dock_refine_last==3,"safe arrival rejected or misreported");
 ps_dock_refine_plans=0;mock_end_nav=0;mock_park=1;vc_require(ps_dock_search_refine(seed,100) && f64_lt(load64(ps_dock_search_goal),PB_ONE),"checked parking correction rejected");
 ps_dock_refine_plans=0;mock_clock=100;ps_nav_path_count=3;vc_require(!ps_dock_search_refine(seed,100) && !ps_nav_path_count && mock_stop_count && ps_dock_refine_timeouts==1 && ps_dock_refine_last==5,"expired deadline failed to stop or was misreported");
 ps_dock_refine_plans=0;mock_clock=-1;ps_nav_path_count=3;vc_require(!ps_dock_search_refine(seed,100) && !ps_nav_path_count && !ps_nav_wall_deadline && ps_dock_refine_clock_faults==1 && ps_dock_refine_last==6,"failed clock accepted or misreported");
 ps_dock_refine_plans=0;mock_clock=0;mock_clock_on_plan=1;ps_nav_path_count=3;vc_require(!ps_dock_search_refine(seed,100) && !ps_nav_path_count && !ps_nav_wall_deadline,"late planner result accepted");
 ps_case_stage=24;ps_dock_refine_plans=0;ps_dock_refine_fault=0;mock_clock=0;mock_clock_on_plan=0;mock_clock_transient=1;mock_nav=1;mock_ik=1;mock_route=1;mock_end_nav=1;mock_end_ik=1;ps_nav_path_count=3;
 vc_require(!ps_dock_search_refine(seed,100) && ps_case_stage==13 && ps_dock_refine_plans==1 && ps_dock_refine_fault==2 && !ps_nav_path_count && !ps_nav_wall_deadline,"transient planner clock fault did not stop before another plan");
 ps_case_stage=24;mock_map_count=0;mock_move_count=0;vc_require(!ps_dock_search_next() && ps_case_stage==13 && !mock_map_count && !mock_move_count,"latched failure started a new map or route");
 ps_case_stage=35;mock_map_count=0;mock_move_count=0;vc_require(!ps_collect_map_finish() && ps_case_stage==13 && !mock_map_count && !mock_move_count,"latched failure advanced mapping or moved the arm");
 ps_case_stage=24;mock_clock=0;mock_clock_on_plan=0;mock_nav=1;mock_ik=0;mock_route=0;mock_hint_count=0;ps_dock_search_anchor=alloc(32);ps_dock_frame=alloc(128);store64(ps_dock_frame+96,PB_ONE);
 ps_agent_physical=0;vc_require(!tested_stage() && !mock_hint_count && ps_case_stage==24,"legacy controller entered physical refinement");
 ps_agent_physical=1;mock_fresh_value=0;vc_require(!tested_stage() && !mock_hint_count && ps_case_stage==24,"stale observation entered refinement");
 mock_fresh_value=1;mock_clock=-1;vc_require(!tested_stage() && !mock_hint_count && ps_case_stage==13,"failed clock did not latch failure");
 ps_case_stage=24;mock_clock=0;
 vc_require(!tested_stage() && ps_case_stage==13 && mock_hint_count==1 && ps_dock_refine_plans==2,"latched seed failure continued to another seed");
 ps_case_stage=24;mock_clock=0;mock_ik=1;mock_route=1;mock_end_nav=1;mock_end_ik=1;mock_park=0;
 vc_require(tested_stage() && ps_dock_coarse_successes==1 && ps_dock_refine_last==1,"coarse stage success not recorded");
 ps_case_stage=24;mock_ik=0;mock_find_value=0;let entries=ps_dock_refine_entries;
 vc_require(!tested_stage() && ps_dock_refine_entries==entries+1 && ps_dock_refine_empty==1 && ps_dock_refine_last==4,"empty refinement not recorded");
 let b=alloc(32);let text=alloc(4096);pl_builder(b,text,4096);pl_text(b,"{\"prefix\":0");ps_output=1;ps_dock_search_observation(b);pl_char(b,125);
 let root=pj_parse(text,load64(b+8));let box=pj_get(root,"boxSearch");let diagnostic=pj_get(box,"stageDiagnostic");
 vc_require(diagnostic && pj_value(pj_get(diagnostic,"coarseSuccesses"))==1 && pj_value(pj_get(diagnostic,"refinementNoSolution"))==1,"trace diagnostic missing or invalid");
 pl_builder(b,text,4096);pl_text(b,"{\"prefix\":0");ps_output=-1;ps_dock_search_observation(b);pl_char(b,125);root=pj_parse(text,load64(b+8));
 vc_require(!pj_get(pj_get(root,"boxSearch"),"stageDiagnostic"),"diagnostic exposed without recording");
 pl_builder(b,text,4096);pl_text(b,"{\"prefix\":0");ps_output=1;ps_agent_physical=0;ps_dock_search_observation(b);pl_char(b,125);root=pj_parse(text,load64(b+8));
 vc_require(!pj_get(pj_get(root,"boxSearch"),"stageDiagnostic"),"legacy recording changed");
 pl_print(1,"Dock refinement gate, planner budget and deadline mocks passed.\n");return 0;
}
'''
    with tempfile.TemporaryDirectory(prefix='puppy-dock-refine-') as directory:
        entry, binary = Path(directory) / 'test.flex', Path(directory) / 'test'
        entry.write_text(source)
        compiler = os.environ.get('FLEXSCRIPT_COMPILER', str(ROOT / 'build/flex/control/compiler'))
        subprocess.run([compiler, str(entry), '-o', str(binary)], cwd=ROOT, check=True)
        subprocess.run([str(binary)], cwd=ROOT, check=True, timeout=15)


if __name__ == '__main__':
    main()
