fn main(argc, argv) {
    if !pl_init() { return 1; }
    // The real map-begin code makes a fresh local map in a temporary folder.
    // Camera and base actuation are stubs: this does not run a rendered scan.
    ps_dock_search_reset(); ps_dock_search_goal = alloc(24); pb_zero(ps_dock_search_goal, 24);
    ps_dock_frame = alloc(128); pb_zero(ps_dock_frame, 128);
    ps_collect_global_counts = alloc(32); ps_nav_map = alloc(40000); ps_discovery_observed = alloc(40000);
    ps_discovery_directory = "@@MAP@@"; ps_discovery_job = 0; ps_discovery_detail_ready = 1;
    ps_collect_enabled = 1; ps_gripper_held = 1; ps_agent_physical = 1;
    ps_dock_floor_retry_enabled = 1; ps_dock_seen = 5; ps_case_stage = 24; ps_total = 100;
    ps_dock_search_started = 20; probe_fresh = 0;
    if !ps_dock_search_next() || probe_plans != 36 || !ps_collect_mapping || ps_case_stage != 35 ||
       ps_dock_search_maps != 1 || ps_dock_search_map_index != 36 || ps_dock_search_index != 0 ||
       !ps_dock_floor_retry_mapping || !ps_collect_local_map || !ps_collect_global_map ||
       ps_discovery_detail_ready || load8(ps_nav_map) != 1 || load8(ps_discovery_observed + 39999) != 1 { return 20; }
    // Fresh floor results alone cannot trigger release-stage planning from
    // the remembered box. Once the full scan ends, mapping time is excluded
    // from the existing search timer and the wrist survey is requested.
    if !ps_collect_map_finish() || probe_sectors != 1 || probe_stages { return 21; }
    ps_total = 145;
    if !ps_collect_map_end() || ps_collect_mapping || ps_dock_floor_retry_mapping || probe_surveys != 1 ||
       ps_dock_search_started != 65 || ps_dock_search_index != 0 { return 22; }
    // If a local dock map already exists from an earlier search index, the
    // real mapper reuses it; it does not clear observed cells or reset the
    // already loaded detail flag. Model that distinct prior state explicitly.
    ps_dock_floor_retry_attempted = 0; ps_dock_search_maps = 1; ps_dock_search_map_index = 1;
    ps_case_stage = 24; ps_discovery_detail_ready = 1; store8(ps_nav_map, 0);
    store8(ps_discovery_observed + 39999, 0);
    if !ps_dock_search_next() || probe_plans != 72 || !ps_collect_mapping || ps_dock_search_maps != 2 ||
       ps_dock_search_map_index != 36 || !ps_discovery_detail_ready || load8(ps_nav_map) != 0 ||
       load8(ps_discovery_observed + 39999) != 0 { return 23; }
    pl_print(1, "dock floor refresh map setup passed\n"); return 0;
}
