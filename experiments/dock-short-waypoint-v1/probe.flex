global probe_plan_calls = 0;
global probe_stage_calls = 0;
global probe_fails = 0;
global probe_route = 0;
global probe_deadline_fault = 0;
global probe_travel_ok = 1;
global probe_fresh = 0;
global probe_endpoint_x = 0;
global probe_path_count = 0;

fn probe_reset() {
    ps_dock_search_reset(); ps_dock_search_goal = alloc(24); ps_dock_search_anchor = alloc(32);
    store64(ps_dock_search_anchor, ps_number(1, 1)); store64(ps_dock_search_anchor + 8, 0);
    ps_local_mode = 1; ps_local_x = 0; ps_local_y = 0; ps_local_heading = 0;
    ps_dock_waypoint_enabled = 1; ps_dock_floor_retry_enabled = 1; ps_dock_floor_retry_attempted = 1;
    ps_dock_floor_retry_mapping = 0; ps_collect_local_map = 1; ps_dock_search_index = 36;
    ps_agent_physical = 1; ps_collect_enabled = 1; ps_gripper_held = 1;
    ps_dock_seen = 1; ps_dock_stable = 0; ps_case_stage = 24; ps_dock_diag_dir = 0;
    probe_plan_calls = 0; probe_stage_calls = 0; probe_fails = 0; probe_route = 1;
    probe_deadline_fault = 0; probe_travel_ok = 1; probe_fresh = 0;
    probe_endpoint_x = ps_number(2, 10); probe_path_count = 4; ps_nav_wall_deadline = 0; return 1;
}
fn main(argc, argv) {
    if !pl_init() { return 1; }
    // Successful route triggers ordinary travel mode, never a release stage.
    probe_reset();
    if !ps_dock_search_next() || !ps_dock_waypoint_attempted || !ps_dock_waypoint_accepted ||
       ps_dock_waypoint_plans != 1 || probe_plan_calls != 1 || probe_stage_calls || probe_fails ||
       ps_dock_search_index != 0 || ps_dock_search_mode != 1 || ps_dock_search_staged || ps_nav_wall_deadline { return 10; }
    // Repeated exhaustion cannot start another approach in this search.
    ps_dock_search_index = 36; ps_case_stage = 24;
    if ps_dock_search_next() || probe_plan_calls != 1 || probe_fails != 1 { return 11; }
    // The episode reset restores the once-only latch.
    ps_dock_search_reset(); if ps_dock_waypoint_attempted || ps_dock_waypoint_accepted || ps_dock_waypoint_plans { return 12; }
    // No route attempts when any safety or mode prerequisite is missing.
    let variant = 0; while variant < 8 {
        probe_reset(); if variant == 0 { ps_dock_waypoint_enabled = 0; }
        if variant == 1 { ps_agent_physical = 0; } if variant == 2 { ps_collect_enabled = 0; }
        if variant == 3 { ps_gripper_held = 0; } if variant == 4 { ps_dock_seen = -1; }
        if variant == 5 { ps_dock_floor_retry_enabled = 0; }
        if variant == 6 { ps_dock_floor_retry_mapping = 1; } if variant == 7 { ps_collect_local_map = 0; }
        if ps_dock_search_next() || probe_plan_calls || ps_dock_waypoint_accepted || probe_fails != 1 { return 13; }
        variant = variant + 1;
    }
    // Stable fresh box observations keep the normal stage flow.
    probe_reset(); probe_fresh = 1; ps_dock_stable = 3; ps_dock_search_index = 35; probe_route = 0;
    if ps_dock_search_next() || probe_plan_calls != 1 || !probe_stage_calls || probe_fails != 1 || ps_dock_waypoint_attempted { return 14; }
    // Failed plans, insufficient progress, and excessive paths fail stopped.
    variant = 0; while variant < 3 {
        probe_reset(); if variant == 0 { probe_route = 0; }
        if variant == 1 { probe_endpoint_x = ps_number(5, 100); } if variant == 2 { probe_path_count = 9; }
        if ps_dock_search_next() || probe_plan_calls != 9 || probe_fails != 1 || ps_nav_path_count || ps_nav_wall_deadline { return 15; }
        variant = variant + 1;
    }
    // Deadline errors and travel-pose failures do not authorize motion.
    probe_reset(); probe_deadline_fault = 1;
    if ps_dock_search_next() || probe_plan_calls != 1 || probe_fails != 1 || ps_nav_path_count || ps_nav_wall_deadline { return 16; }
    probe_reset(); probe_travel_ok = 0;
    if ps_dock_search_next() || probe_plan_calls != 1 || probe_fails != 1 || ps_dock_waypoint_accepted { return 17; }
    pl_print(1, "short waypoint state checks passed\n"); return 0;
}
