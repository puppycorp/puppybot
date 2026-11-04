// Test the real transformed clearance and staging functions with deterministic
// stand-ins for map, IK and route inputs. No real simulator is started.
fn dc_assert(value, text) { if !value { pl_print(2, text); pl_print(2, "\n"); syscall(60, 1, 0, 0, 0, 0, 0); } }
fn dc_reset() {
    ps_dc_scope = 0; ps_dc_last_reason = 0; ps_dc_stage_runs = 0;
    ps_dc_stage_total = 0; ps_dc_stage_near = 0; ps_dc_stage_clear = 0;
    ps_dc_stage_floor = 0; ps_dc_stage_observed = 0; ps_dc_stage_box = 0;
    ps_dc_stage_target = 0; ps_dc_stage_other = 0;
    ps_dc_drop_pass = 0; ps_dc_drop_fail = 0; ps_dc_route_pass = 0; ps_dc_route_fail = 0;
    dc_floor_calls = 0; dc_observed_calls = 0; dc_box_calls = 0; dc_drop_calls = 0; dc_route_calls = 0;
    return 1;
}
fn dc_counted() {
    return ps_dc_stage_near + ps_dc_stage_clear + ps_dc_stage_floor + ps_dc_stage_observed + ps_dc_stage_box + ps_dc_stage_target + ps_dc_stage_other;
}
fn main(argc, argv) {
    if !pl_init() || argc != 2 { return 1; }
    ps_dock_search_anchor = alloc(32); pb_zero(ps_dock_search_anchor, 32);
    ps_dock_frame = alloc(128); pb_zero(ps_dock_frame, 128);
    ps_dock_search_goal = alloc(24); ps_nav_goal = alloc(24); ps_case_target = alloc(24);
    ps_local_mode = 1; ps_local_x = f64_from_i64(3); ps_local_y = 0; ps_local_heading = 0;
    ps_collect_enabled = 1; ps_house_ready = 1; ps_discovery_enabled = 1;
    ps_collect_busy = 0; ps_house_returning = 0; ps_nav_training_oracle = 0;
    dc_floor = 0; dc_observed = 1; dc_gap = 1; dc_drop = 1; dc_route = 1;
    ps_dock_diag_dir = 0; dc_reset();
    dc_assert(!ps_dock_search_stage(), "disabled stage unexpectedly succeeded");
    dc_assert(!ps_dc_stage_total && !ps_dc_stage_runs && dc_floor_calls == 2304 && !dc_observed_calls, "disabled changed guard calls");
    ps_dock_diag_dir = 1; dc_reset();
    dc_assert(!ps_dock_search_stage(), "floor-obstacle stage unexpectedly succeeded");
    dc_assert(ps_dc_stage_runs == 1 && ps_dc_stage_total == 2304 && ps_dc_stage_floor == 2304 && dc_counted() == 2304, "floor count mismatch");
    dc_assert(dc_floor_calls == 2304 && !dc_observed_calls, "floor short circuit changed");
    dc_floor = 1; dc_observed = 0; dc_reset();
    dc_assert(!ps_dock_search_stage(), "observed-floor stage unexpectedly succeeded");
    dc_assert(ps_dc_stage_observed == 2304 && dc_counted() == 2304 && dc_floor_calls == 2304 && dc_observed_calls == 2304, "observed-floor count mismatch");
    dc_observed = 1; dc_gap = -1; dc_reset();
    dc_assert(!ps_dock_search_stage(), "box-margin stage unexpectedly succeeded");
    dc_assert(ps_dc_stage_box == 2304 && dc_counted() == 2304 && dc_box_calls == 2304, "box-margin count mismatch");
    dc_gap = 1; ps_collect_busy = 1; ps_house_returning = 3; dc_reset(); ps_dc_scope = 1;
    dc_assert(!ps_nav_clear(0, 0, 0) && ps_dc_stage_target == 1, "target exclusion not counted");
    dc_floor = 0; dc_reset(); ps_dc_scope = 1;
    dc_assert(!ps_nav_clear(0, 0, 0) && ps_dc_stage_floor == 1 && !ps_dc_stage_target, "first-failure order changed");
    ps_dc_scope = 0; dc_floor = 1; ps_collect_busy = 0; ps_house_returning = 0;
    ps_discovery_enabled = 0; ps_nav_map = alloc(1); store8(ps_nav_map, 1); dc_reset(); ps_dc_scope = 1;
    dc_assert(!ps_nav_clear(0, 0, 0) && ps_dc_stage_other == 1 && ps_dc_last_reason == 5, "non-discovery map rejection mismatch");
    ps_dc_scope = 0; ps_discovery_enabled = 1; ps_local_x = ps_number(28, 100); dc_floor = 0; dc_reset();
    dc_assert(!ps_dock_search_stage() && ps_dc_stage_near > 0 && dc_counted() == 2304, "near-candidate accounting mismatch");
    ps_local_x = f64_from_i64(3); dc_floor = 1;
    dc_gap = 1; dc_drop = 1; dc_route = 1; dc_reset();
    dc_assert(ps_dock_search_stage(), "clear stage unexpectedly failed");
    dc_assert(ps_dc_stage_clear == 2304 && dc_counted() == 2304 && ps_dc_drop_pass >= 1 && ps_dc_route_pass >= 1, "clear or route count mismatch");
    let saved_floor = dc_floor_calls; let saved_observed = dc_observed_calls; let saved_drop = dc_drop_calls; let saved_route = dc_route_calls;
    ps_dock_diag_dir = 0; dc_reset();
    dc_assert(ps_dock_search_stage(), "disabled clear stage unexpectedly failed");
    dc_assert(dc_floor_calls == saved_floor && dc_observed_calls == saved_observed && dc_drop_calls == saved_drop && dc_route_calls == saved_route, "enabled/disabled guard calls differ");
    dc_assert(!ps_dc_stage_total && !ps_dc_drop_pass && !ps_dc_route_pass, "disabled emitted counters");
    ps_dock_diag_dir = 1; dc_drop = 0; dc_route = 1; dc_reset();
    dc_assert(!ps_dock_search_stage(), "unreachable drop stage unexpectedly succeeded");
    dc_assert(ps_dc_stage_clear == 2304 && ps_dc_drop_fail == 2304 && !ps_dc_drop_pass && !dc_route_calls, "drop-clearance count mismatch");
    saved_drop = dc_drop_calls; ps_dock_diag_dir = 0; dc_reset();
    dc_assert(!ps_dock_search_stage() && dc_drop_calls == saved_drop && !dc_route_calls, "disabled drop behavior differs");
    ps_dock_diag_dir = 1; dc_drop = 1; dc_route = 0; dc_reset();
    dc_assert(!ps_dock_search_stage(), "unreachable route stage unexpectedly succeeded");
    dc_assert(ps_dc_drop_pass == 2304 && ps_dc_route_fail == 2304 && !ps_dc_route_pass, "route-failure count mismatch");
    saved_drop = dc_drop_calls; saved_route = dc_route_calls; ps_dock_diag_dir = 0; dc_reset();
    dc_assert(!ps_dock_search_stage() && dc_drop_calls == saved_drop && dc_route_calls == saved_route, "disabled route behavior differs");
    // Run the real planner entry path: an observed-floor rejection must keep
    // the original planner reason and add a detailed reason, without stage counts.
    ps_dock_diag_dir = 1; dc_reset(); dc_observed = 0; ps_collect_busy = 1;
    dc_assert(!ps_nav_plan(0, 0, 0), "goal unexpectedly planned");
    dc_assert(ps_dock_diag_plan_reason == 3 && ps_dc_last_reason == 2 && !ps_dc_stage_observed && !ps_dc_scope, "viewpoint reason mismatch");
    ps_dock_diag_dir = load64(argv + 8); ps_dock_diag_searches = 1; ps_total = 123;
    ps_dock_diag_plan_reason = 3; ps_nav_expanded = 0;
    pb_zero(ps_dock_search_goal, 24); ps_dock_diag_candidate(2, ps_dock_search_goal, 0);
    dc_assert(!ps_dock_diag_write_errors, "viewpoint diagnostic write failed");
    ps_dock_hint = alloc(24); pb_zero(ps_dock_hint, 24);
    ps_dock_calibration = alloc(96); pb_zero(ps_dock_calibration, 96);
    ps_dock_corners = alloc(32); pb_zero(ps_dock_corners, 32);
    let text = alloc(8192); let b = alloc(32); pl_builder(b, text, 8192); pl_text(b, "{\"prefix\":1");
    ps_dock_observation(b); pl_text(b, "}\n"); pl_print(1, text);
    return 0;
}
