// State checks with real transition code and stubbed planner/actuators.
global probe_route = 1;
global probe_plans = 0;
global probe_surveys = 0;
global probe_travel = 1;

fn probe_reset() {
    ps_robot = alloc(8192); pb_robot_init(ps_robot, 0);
    ps_agent_physical = 1; ps_collect_enabled = 1; ps_collect_local_map = 1;
    ps_gripper_held = 1; ps_dock_seen = 5; ps_dock_stable = 0;
    ps_dock_extra_enabled = 1; ps_dock_extra_accepted = 0; ps_dock_extra_attempted = 0;
    ps_dock_extra_waiting = 0; ps_dock_extra_arrived = 0; ps_dock_extra_arrival_step = -1;
    ps_dock_waypoint_enabled = 1; ps_dock_waypoint_attempted = 0; ps_dock_waypoint_accepted = 0;
    ps_dock_floor_retry_enabled = 1; ps_dock_floor_retry_attempted = 1; ps_dock_floor_retry_mapping = 0;
    ps_dock_search_index = 36; ps_dock_search_started = 10; ps_dock_search_active = 1; ps_dock_search_staged = 0;
    ps_collect_mapping = 0; ps_case_stage = 24; ps_total = 100; ps_blocked = 0;
    ps_dock_diag_dir = 0; probe_route = 1; probe_plans = 0; probe_surveys = 0; probe_travel = 1;
    return 1;
}
fn probe_mapping() {
    ps_collect_mapping = 1; ps_collect_map_started = 110; ps_discovery_map_frame = 111;
    ps_discovery_sector = 3; ps_discovery_tilt = 1; ps_discovery_full = 0;
    ps_total = 200; ps_case_stage = 35; return 1;
}
fn main(argc, argv) {
    if !pl_init() { return 1; } probe_reset();
    // Original first waypoint counts against the episode limit.
    if !ps_dock_search_next() || ps_dock_extra_accepted != 1 || !ps_dock_extra_waiting || probe_plans != 1 { return 10; }
    // The first route must really finish before a new scan can qualify.
    probe_mapping(); if ps_dock_extra_waypoint() || probe_plans != 1 { return 11; }
    ps_case_stage = 24; ps_total = 100;
    if !ps_dock_search_update() || !ps_dock_extra_arrived || ps_dock_extra_waiting || probe_surveys != 1 { return 12; }
    probe_mapping();
    if !ps_discovery_next_sector() || ps_dock_extra_accepted != 2 || !ps_dock_extra_attempted ||
       ps_collect_mapping || ps_case_stage != 24 || ps_dock_search_mode != 1 || probe_plans != 2 { return 13; }
    probe_mapping(); if ps_dock_extra_waypoint() || probe_plans != 2 { return 14; }
    // Resetting an individual search does not reset the episode-wide cap.
    ps_dock_search_reset(); ps_dock_search_index = 36; ps_dock_floor_retry_attempted = 1;
    if ps_dock_search_next() || probe_plans != 2 || ps_case_stage != 13 { return 15; }
    // A map from before the actual arrival is not a new post-move scan.
    probe_reset(); ps_dock_extra_accepted = 1; ps_dock_extra_arrived = 1; ps_dock_extra_arrival_step = 110;
    probe_mapping(); if ps_dock_extra_waypoint() || probe_plans { return 16; }
    ps_dock_extra_arrival_step = 100; ps_discovery_map_frame = 109;
    if ps_dock_extra_waypoint() || probe_plans { return 17; }
    // A blocked first path cannot qualify a second attempt.
    probe_reset(); ps_dock_extra_accepted = 1; ps_dock_extra_waiting = 1; ps_blocked = 1;
    if !ps_dock_search_update() || ps_dock_extra_waiting || ps_dock_extra_arrived { return 18; }
    // Missing payload, disabled feature and rejected route cannot command it.
    probe_reset(); ps_dock_extra_accepted = 1; ps_dock_extra_arrived = 1; ps_dock_extra_arrival_step = 100;
    probe_mapping(); ps_gripper_held = 0; if ps_dock_extra_waypoint() || probe_plans { return 19; }
    ps_gripper_held = 1; ps_dock_extra_enabled = 0; if ps_dock_extra_waypoint() || probe_plans { return 20; }
    ps_dock_extra_enabled = 1; probe_route = 0;
    if ps_dock_extra_waypoint() || probe_plans != 1 || !ps_dock_extra_attempted || ps_dock_extra_accepted != 1 { return 21; }
    // Planner timeout fails closed and does not allow motion.
    probe_reset(); ps_dock_extra_accepted = 1; ps_dock_extra_arrived = 1; ps_dock_extra_arrival_step = 100;
    probe_mapping(); probe_route = -1;
    if ps_dock_extra_waypoint() != -1 || ps_case_stage != 13 || ps_dock_extra_accepted != 1 { return 22; }
    pl_print(1, "second waypoint transition checks passed\n"); return 0;
}
