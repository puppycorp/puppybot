// Branch tests for the copied state machine with sensor and actuator stubs.
global probe_plans = 0;
global probe_stages = 0;
global probe_maps = 0;
global probe_sectors = 0;
global probe_surveys = 0;
global probe_fails = 0;
global probe_fresh = 0;
global probe_stage_ok = 0;
global probe_map_mode = 0;

fn probe_reset() {
    ps_dock_search_reset(); ps_dock_search_goal = alloc(24); pb_zero(ps_dock_search_goal, 24);
    ps_dock_search_index = 0; ps_case_stage = 24; ps_agent_physical = 1;
    ps_collect_enabled = 1; ps_gripper_held = 1; ps_dock_seen = 5; ps_dock_stable = 0;
    ps_dock_diag_dir = 0; ps_dock_floor_retry_enabled = 1; ps_collect_mapping = 0;
    probe_plans = 0; probe_stages = 0; probe_maps = 0; probe_sectors = 0;
    probe_surveys = 0; probe_fails = 0; probe_fresh = 0; probe_stage_ok = 0; probe_map_mode = 0;
    return 1;
}
fn main(argc, argv) {
    if !pl_init() { return 1; }
    // Default/disabled failure path consumes the same 36 plans and fails.
    probe_reset(); ps_dock_floor_retry_enabled = 0;
    if ps_dock_search_next() || probe_plans != 36 || probe_maps || probe_fails != 1 || ps_dock_floor_retry_attempted { return 10; }
    // Exhausted viewpoints cause one mapping request; they never issue a
    // chassis path or use the old box as a staging authorization.
    probe_reset();
    if !ps_dock_search_next() || probe_plans != 36 || probe_maps != 1 || probe_stages || probe_fails ||
       !ps_dock_floor_retry_attempted || !ps_dock_floor_retry_mapping || ps_dock_search_index != 0 { return 11; }
    // An old box pose during mapping cannot reach the staging planner.
    if !ps_collect_map_finish() || probe_stages || probe_sectors != 1 { return 12; }
    // A fresh but unstable observation also cannot reach staging.
    probe_fresh = 1; ps_dock_stable = 2;
    if !ps_collect_map_finish() || probe_stages || probe_sectors != 2 { return 13; }
    // Fresh stable evidence may run the existing stage gates, whose success
    // only returns to the ordinary survey after ending stationary mapping.
    ps_dock_stable = 3; probe_stage_ok = 1; ps_collect_mapping = 1;
    if !ps_collect_map_finish() || probe_stages != 1 || probe_surveys != 1 || ps_dock_floor_retry_mapping || ps_collect_mapping { return 14; }
    // If nothing changes, another exhausted sweep ends in failure, not a
    // second retry. The original failure/report path is retained.
    probe_fresh = 0; probe_stage_ok = 0; ps_dock_search_index = 0; ps_case_stage = 24;
    if ps_dock_search_next() || probe_maps != 1 || probe_fails != 1 || ps_dock_search_index != 36 { return 15; }
    // No retry is permitted without physical-agent mode, collection, held
    // payload, or a previously learned visual box.
    let variant = 0;
    while variant < 4 {
        probe_reset();
        if variant == 0 { ps_agent_physical = 0; }
        if variant == 1 { ps_collect_enabled = 0; }
        if variant == 2 { ps_gripper_held = 0; }
        if variant == 3 { ps_dock_seen = -1; }
        if ps_dock_search_next() || probe_maps || !probe_fails { return 16; }
        variant = variant + 1;
    }
    // A fresh but unstable estimate also remains only a scan bearing.
    probe_reset(); probe_fresh = 1; ps_dock_stable = 2;
    if !ps_dock_search_next() || probe_maps != 1 || probe_stages || !ps_dock_floor_retry_mapping { return 19; }
    // Diagnostic sweep numbering advances only for an accepted retry so
    // per-viewpoint records do not overwrite the first exhausted sweep.
    probe_reset(); ps_dock_diag_dir = "probe"; ps_dock_diag_searches = 1;
    // The probe replaces the diagnostic writer itself; the real writer is
    // exercised separately in the saved-run integration.
    if !ps_dock_search_next() || ps_dock_diag_searches != 2 { return 24; }
    // A map setup error remains terminal, without resetting the exhausted
    // search or overwriting the existing failure.
    probe_reset(); probe_map_mode = 1;
    if ps_dock_search_next() || probe_maps != 1 || probe_fails != 1 || ps_case_stage != 13 ||
       ps_dock_search_index != 36 || ps_dock_floor_retry_mapping { return 17; }
    // Reset the latch between episodes.
    ps_dock_search_reset(); if ps_dock_floor_retry_attempted || ps_dock_floor_retry_mapping { return 18; }
    pl_print(1, "dock floor refresh branch checks passed\n"); return 0;
}
