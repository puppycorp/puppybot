#!/usr/bin/env python3
"""Add one guarded short waypoint after a failed stationary dock-floor scan."""


def once(source, old, new):
    if source.count(old) != 1:
        raise ValueError('unexpected saved simulator source')
    return source.replace(old, new, 1)


def transform(dock, main):
    dock = once(dock, 'global ps_dock_search_active = 0;', '''// Isolated simulator-only bounded approach; default is disabled.
global ps_dock_waypoint_enabled = 0;
global ps_dock_waypoint_attempted = 0;
global ps_dock_waypoint_accepted = 0;
global ps_dock_waypoint_plans = 0;
global ps_dock_waypoint_endpoint = 0;
global ps_dock_search_active = 0;''')
    dock = once(dock, '    ps_dock_floor_retry_attempted = 0; ps_dock_floor_retry_mapping = 0;',
        '    ps_dock_waypoint_attempted = 0; ps_dock_waypoint_accepted = 0; ps_dock_waypoint_plans = 0;\n'
        '    ps_dock_floor_retry_attempted = 0; ps_dock_floor_retry_mapping = 0;')
    dock = once(dock, 'fn ps_dock_search_next() {', '''// Cached box geometry supplies only a direction. The original planner checks
// the entire predicted route using its unchanged map and contact constraints.
// A stale box cannot authorize release or a stage pose.
fn ps_dock_waypoint_plan() {
    let dx = f64_sub(load64(ps_dock_search_anchor), ps_pose_x());
    let dy = f64_sub(load64(ps_dock_search_anchor + 8), ps_pose_y());
    let before = f64_sqrt(f64_add(f64_mul(dx, dx), f64_mul(dy, dy)));
    if !f64_is_finite(before) || f64_lt(before, ps_number(4, 10)) { return 0; }
    if !ps_dock_waypoint_endpoint { ps_dock_waypoint_endpoint = alloc(24); }
    let bearing = f64_atan2(dy, dx); let now = pl_now(); if now < 0 { return -1; }
    let deadline = now + 8000; let distance = 20;
    while distance <= 40 {
        let i = 0;
        while i < 3 {
            now = pl_now(); if now < 0 || now >= deadline { ps_nav_path_count = 0; return -1; }
            let offset = 0; if i == 1 { offset = -1; } if i == 2 { offset = 1; }
            let angle = f64_add(bearing, ps_number(offset * 35, 100));
            let x = f64_add(ps_pose_x(), f64_mul(ps_number(distance, 100), f64_cos(angle)));
            let y = f64_add(ps_pose_y(), f64_mul(ps_number(distance, 100), f64_sin(angle)));
            ps_dock_waypoint_plans = ps_dock_waypoint_plans + 1; ps_nav_deadline_fault = 0; ps_nav_wall_deadline = deadline;
            let planned = ps_nav_plan(x, y, ps_pose_heading()); ps_nav_wall_deadline = 0;
            if ps_nav_deadline_fault { ps_nav_path_count = 0; return -1; }
            if planned && ps_nav_path_count > 0 && ps_nav_path_count <= 8 {
                ps_nav_end_pose(ps_dock_waypoint_endpoint); let ex = load64(ps_dock_waypoint_endpoint); let ey = load64(ps_dock_waypoint_endpoint + 8);
                let tx = f64_sub(load64(ps_dock_search_anchor), ex); let ty = f64_sub(load64(ps_dock_search_anchor + 8), ey);
                let after = f64_sqrt(f64_add(f64_mul(tx, tx), f64_mul(ty, ty)));
                let mx = f64_sub(ex, ps_pose_x()); let my = f64_sub(ey, ps_pose_y()); let move = f64_sqrt(f64_add(f64_mul(mx, mx), f64_mul(my, my)));
                if f64_is_finite(after) && f64_is_finite(move) && f64_ge(f64_sub(before, after), ps_number(10, 100)) &&
                   f64_ge(move, ps_number(10, 100)) && f64_le(move, ps_number(5, 10)) &&
                   ps_nav_clear(ex, ey, load64(ps_dock_waypoint_endpoint + 16)) {
                    pb_copy(ps_dock_search_goal, ps_dock_waypoint_endpoint, 24); return 1;
                }
            }
            ps_nav_path_count = 0; i = i + 1;
        } distance = distance + 10;
    }
    return 0;
}
fn ps_dock_search_next() {''')
    anchor = '    if ps_dock_fresh() && ps_dock_stable >= 3 { return ps_case_fail("box observed but no mapped arm-feasible docking pose found"); }'
    dock = once(dock, anchor, '''    // One short mapped approach, only after the bounded stationary retry.
    // Re-survey afterward; do not treat this waypoint as a release pose.
    if ps_dock_waypoint_enabled && ps_agent_physical && ps_collect_enabled && ps_gripper_held &&
       ps_dock_seen >= 0 && (!ps_dock_fresh() || ps_dock_stable < 3) && ps_dock_floor_retry_enabled &&
       ps_dock_floor_retry_attempted && !ps_dock_floor_retry_mapping && ps_collect_local_map && !ps_dock_waypoint_attempted {
        ps_dock_waypoint_attempted = 1; let route = ps_dock_waypoint_plan();
        if route < 0 { return ps_case_fail("short box approach planning timed out"); }
        if route {
            if !ps_case_travel_pose() { return ps_case_fail("cannot aim the TCP camera before short box approach"); }
            if ps_dock_diag_dir { ps_dock_diag_searches = ps_dock_diag_searches + 1; }
            ps_dock_waypoint_accepted = 1; ps_dock_search_index = 0; ps_dock_search_mode = 1; return 1;
        }
    }
''' + anchor)
    dock = once(dock, '        if ps_dock_floor_retry_enabled {', '''        if ps_dock_waypoint_enabled {
            pl_text(b, ",\\\"shortWaypoint\\\":{\\\"attempted\\\":"); pj_bool_text(b, ps_dock_waypoint_attempted);
            pl_text(b, ",\\\"accepted\\\":"); pj_bool_text(b, ps_dock_waypoint_accepted);
            pl_text(b, ",\\\"plans\\\":"); pl_int(b, ps_dock_waypoint_plans); pl_char(b, 125);
        }
        if ps_dock_floor_retry_enabled {''')
    main = once(main, '    let floor_retry = pl_environment(argc, argv, "PUPPYBOT_SIM_DOCK_FLOOR_RETRY");', '''    let waypoint = pl_environment(argc, argv, "PUPPYBOT_SIM_DOCK_SHORT_WAYPOINT");
    if waypoint {
        if !pl_equal(waypoint, "0") && !pl_equal(waypoint, "1") { pl_print(2, "Invalid dock short waypoint option.\\n"); return 2; }
        ps_dock_waypoint_enabled = pl_equal(waypoint, "1");
    }
    let floor_retry = pl_environment(argc, argv, "PUPPYBOT_SIM_DOCK_FLOOR_RETRY");''')
    return dock, main
