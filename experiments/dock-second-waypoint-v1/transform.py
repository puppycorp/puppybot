#!/usr/bin/env python3
"""Private opt-in second mapped waypoint after a full new floor scan."""


def once(source, old, new):
    if source.count(old) != 1:
        raise ValueError('unexpected saved simulator source')
    return source.replace(old, new, 1)


def transform(dock, discovery, case, main):
    dock = once(dock, 'global ps_dock_search_active = 0;', '''// Episode-wide bounds are reset by ps_case_reset, not search reuse.
global ps_dock_extra_enabled = 0;
global ps_dock_extra_accepted = 0;
global ps_dock_extra_attempted = 0;
global ps_dock_extra_waiting = 0;
global ps_dock_extra_arrived = 0;
global ps_dock_extra_arrival_step = -1;
global ps_dock_search_active = 0;''')
    needle = '       ps_dock_floor_retry_attempted && !ps_dock_floor_retry_mapping && ps_collect_local_map && !ps_dock_waypoint_attempted {'
    dock = once(dock, needle, '''       ps_dock_floor_retry_attempted && !ps_dock_floor_retry_mapping && ps_collect_local_map && !ps_dock_waypoint_attempted &&
       (!ps_dock_extra_enabled || !ps_dock_extra_accepted) {''')
    needle = '            ps_dock_waypoint_accepted = 1; ps_dock_search_index = 0; ps_dock_search_mode = 1; return 1;'
    dock = once(dock, needle, '''            if ps_dock_extra_enabled { ps_dock_extra_accepted = 1; ps_dock_extra_waiting = 1; }
            ps_dock_waypoint_accepted = 1; ps_dock_search_index = 0; ps_dock_search_mode = 1; return 1;''')
    dock = once(dock, '    if ps_blocked { ps_dock_search_blocks = ps_dock_search_blocks + 1;',
        '    if ps_blocked { ps_dock_extra_waiting = 0; ps_dock_search_blocks = ps_dock_search_blocks + 1;')
    needle = '    if ps_dock_search_staged { ps_house_parking = 0; ps_dock_search_mode = 4; return 1; }'
    dock = once(dock, needle, '''    if ps_dock_extra_waiting {
        ps_dock_extra_waiting = 0; ps_dock_extra_arrived = 1; ps_dock_extra_arrival_step = ps_total;
    }
''' + needle)
    dock = once(dock, 'fn ps_dock_search_attention() {', '''// Called only when a full mapping sweep has ended. A prior completed
// waypoint and a later applied map are both required. The old box is only a
// bearing; the unchanged planner and its full swept checks authorize travel.
fn ps_dock_extra_waypoint() {
    if !ps_dock_extra_enabled || ps_dock_extra_accepted != 1 || ps_dock_extra_attempted ||
       !ps_dock_extra_arrived || !ps_dock_search_active || !ps_agent_physical || !ps_collect_enabled || !ps_collect_mapping ||
       !ps_collect_local_map || !ps_gripper_held || ps_dock_seen < 0 ||
       ps_collect_map_started <= ps_dock_extra_arrival_step || ps_discovery_map_frame < ps_collect_map_started { return 0; }
    ps_dock_extra_attempted = 1; let route = ps_dock_waypoint_plan();
    if route < 0 { ps_case_fail("additional box approach planning timed out"); return -1; }
    if !route { return 0; }
    if !ps_case_travel_pose() { ps_case_fail("cannot aim the TCP camera before additional box approach"); return -1; }
    ps_dock_extra_accepted = 2; ps_collect_mapping = 0; ps_discovery_phase = 0;
    ps_dock_search_started = ps_dock_search_started + ps_total - ps_collect_map_started;
    ps_dock_search_staged = 0; ps_dock_search_index = 0; ps_dock_search_mode = 1;
    ps_case_phase(24); return 1;
}
fn ps_dock_search_attention() {''')
    dock = once(dock, '        if ps_dock_waypoint_enabled {', '''        if ps_dock_extra_enabled {
            pl_text(b, ",\\\"secondWaypoint\\\":{\\\"acceptedCount\\\":"); pl_int(b, ps_dock_extra_accepted);
            pl_text(b, ",\\\"attempted\\\":"); pj_bool_text(b, ps_dock_extra_attempted);
            pl_text(b, ",\\\"firstArrived\\\":"); pj_bool_text(b, ps_dock_extra_arrived); pl_char(b, 125);
        }
        if ps_dock_waypoint_enabled {''')
    discovery = once(discovery, '    if ps_collect_mapping { return ps_collect_map_end(); }', '''    if ps_collect_mapping {
        let extra = ps_dock_extra_waypoint(); if extra { return extra > 0; }
        return ps_collect_map_end();
    }''')
    case = once(case, 'fn ps_case_reset() {', '''fn ps_case_reset() {
    ps_dock_extra_accepted = 0; ps_dock_extra_attempted = 0; ps_dock_extra_waiting = 0;
    ps_dock_extra_arrived = 0; ps_dock_extra_arrival_step = -1;''')
    needle = '    let waypoint = pl_environment(argc, argv, "PUPPYBOT_SIM_DOCK_SHORT_WAYPOINT");'
    main = once(main, needle, '''    let extra = pl_environment(argc, argv, "PUPPYBOT_SIM_DOCK_SECOND_WAYPOINT");
    if extra {
        if !pl_equal(extra, "0") && !pl_equal(extra, "1") { pl_print(2, "Invalid dock second waypoint option.\\n"); return 2; }
        ps_dock_extra_enabled = pl_equal(extra, "1");
    }
''' + needle)
    return dock, discovery, case, main
