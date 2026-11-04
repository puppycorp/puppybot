#!/usr/bin/env python3
"""Stage an opt-in bounded, stationary dock-floor refresh in a copied simulator."""


def once(source, old, new):
    if source.count(old) != 1:
        raise ValueError('unexpected copied simulator source anchor')
    return source.replace(old, new, 1)


def transform(dock, collect, main):
    dock = once(dock, 'global ps_dock_search_active = 0;',
        '''// Experimental simulator-only recovery; default path remains unchanged.
global ps_dock_floor_retry_enabled = 0;
global ps_dock_floor_retry_attempted = 0;
global ps_dock_floor_retry_mapping = 0;
global ps_dock_search_active = 0;''')
    dock = once(dock, '    ps_dock_search_active = 0; ps_dock_search_index = 0;',
        '    ps_dock_floor_retry_attempted = 0; ps_dock_floor_retry_mapping = 0;\n'
        '    ps_dock_search_active = 0; ps_dock_search_index = 0;')
    dock = once(dock,
        '    if ps_dock_fresh() && ps_dock_stable >= 3 { return ps_case_fail("box observed but no mapped arm-feasible docking pose found"); }',
        '''    // A remembered visual box is a scan bearing only, never a release
    // target. A single bounded stationary stereo rescan may recover mapped
    // floor after the initial viewpoints were all rejected. The map's own
    // scan budget and full fresh-box/stage gates still apply.
    if ps_dock_floor_retry_enabled && ps_agent_physical && ps_collect_enabled && ps_gripper_held &&
       ps_dock_seen >= 0 && (!ps_dock_fresh() || ps_dock_stable < 3) && !ps_dock_floor_retry_attempted {
        ps_dock_floor_retry_attempted = 1; ps_dock_floor_retry_mapping = 1;
        if ps_collect_map_begin() {
            // The retry is a new diagnostic sweep. Otherwise candidate files
            // from the first 36 plans would be overwritten by the same names.
            if ps_dock_diag_dir { ps_dock_diag_searches = ps_dock_diag_searches + 1; }
            ps_dock_search_index = 0; return 1;
        }
        ps_dock_floor_retry_mapping = 0;
        if ps_case_stage == 13 { return 0; }
    }
    if ps_dock_fresh() && ps_dock_stable >= 3 { return ps_case_fail("box observed but no mapped arm-feasible docking pose found"); }''')
    dock = once(dock, '        pl_text(b, ",\\\"stageDiagnostic\\\":{\\\"coarseSuccesses\\\":");',
        '''        if ps_dock_floor_retry_enabled {
            pl_text(b, ",\\\"floorRetry\\\":{\\\"attempted\\\":"); pj_bool_text(b, ps_dock_floor_retry_attempted);
            pl_text(b, ",\\\"mapping\\\":"); pj_bool_text(b, ps_dock_floor_retry_mapping); pl_char(b, 125);
        }
        pl_text(b, ",\\\"stageDiagnostic\\\":{\\\"coarseSuccesses\\\":");''')
    collect = once(collect,
        '    ps_collect_mapping = 0; ps_discovery_phase = 0;\n    // Two surrounding scans',
        '    ps_collect_mapping = 0; ps_discovery_phase = 0; ps_dock_floor_retry_mapping = 0;\n    // Two surrounding scans')
    collect = once(collect,
        '    if ps_dock_seen >= 0 && ps_dock_search_stage() { return ps_collect_map_end(); }',
        '''    // The extra stale-box scan only refreshes floor. Do not plan a
    // release stage from an old box estimate while the scan is running.
    if ps_dock_seen >= 0 && (!ps_dock_floor_retry_mapping || (ps_dock_fresh() && ps_dock_stable >= 3)) && ps_dock_search_stage() { return ps_collect_map_end(); }''')
    anchor = '    let observed_v2 = pl_environment(argc, argv, "PUPPYBOT_SIM_OBSERVED_FOOTPRINT_V2");'
    main = once(main, anchor, '''    let floor_retry = pl_environment(argc, argv, "PUPPYBOT_SIM_DOCK_FLOOR_RETRY");
    if floor_retry {
        if !pl_equal(floor_retry, "0") && !pl_equal(floor_retry, "1") { pl_print(2, "Invalid dock floor retry option.\\n"); return 2; }
        ps_dock_floor_retry_enabled = pl_equal(floor_retry, "1");
    }
''' + anchor)
    return dock, collect, main
