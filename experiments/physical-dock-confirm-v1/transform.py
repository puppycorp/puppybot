#!/usr/bin/env python3
"""Isolated opt-in simulator experiment; never edits an existing source tree."""

GLOBALS = '''global ps_dock_confirm_enabled = 0;
global ps_dock_confirm_active = 0;
global ps_dock_confirm_start = 0;
global ps_dock_confirm_last = 0;
global ps_dock_confirm_attempts = 0;
global ps_dock_confirm_runs = 0;
global ps_dock_confirm_reason = 0;
global ps_dock_confirm_distance = 0;
global ps_dock_confirm_heading = 0;
'''

HOOKS = '''// A simulation-only RGB confirmation. Distinct ticks are not statistically
// independent images and zero commanded drive is not proof of a hardware stop.
fn ps_dock_confirm_begin() {
    if !ps_dock_confirm_enabled || ps_dock_confirm_runs >= 3 || !ps_agent_physical || ps_physical_owner != 1 || !ps_local_mode || ps_agent_oracle || ps_nav_training_oracle || !ps_collect_enabled || !ps_discovery_enabled || ps_seek_enabled || ps_house_ready || ps_blocked || !ps_camera_drive_mode || !ps_camera_still() || !ps_dock_valid || ps_dock_stable < 1 || ps_dock_stable >= 3 || ps_dock_seen != ps_total || ps_brick_frame != ps_total { return 0; }
    let drive = pb_robot_drive(ps_robot); pb_drive_stop(drive, ps_time);
    if pb_vget(drive, 6) || pb_vget(drive, 7) { ps_dock_confirm_reason = 5; return -1; }
    // Count only this fresh first frame; do not inherit prior repeated frames.
    ps_dock_stable = 1; ps_dock_confirm_active = 1; ps_dock_confirm_start = ps_total; ps_dock_confirm_runs = ps_dock_confirm_runs + 1; ps_dock_confirm_reason = 0;
    ps_dock_confirm_last = ps_total; ps_dock_confirm_attempts = 0;
    ps_dock_confirm_distance = ps_local_distance; ps_dock_confirm_heading = ps_pose_heading(); return 1;
}
fn ps_dock_confirm_tick() {
    if !ps_dock_confirm_active { return 0; }
    let drive = pb_robot_drive(ps_robot); pb_drive_stop(drive, ps_time);
    if pb_vget(drive, 6) || pb_vget(drive, 7) { ps_dock_confirm_active = 0; ps_dock_stable = 0; ps_dock_confirm_reason = 5; return -1; }
    if !ps_agent_physical || ps_physical_owner != 1 || !ps_local_mode || ps_agent_oracle || ps_nav_training_oracle || !ps_collect_enabled || !ps_discovery_enabled || ps_seek_enabled || ps_blocked || !ps_camera_drive_mode || !ps_camera_still() || f64_gt(f64_magnitude(f64_sub(ps_local_distance, ps_dock_confirm_distance)), ps_number(1, 1000)) || f64_gt(f64_magnitude(pb_wrap_pi(f64_sub(ps_pose_heading(), ps_dock_confirm_heading))), ps_number(5, 1000)) {
        ps_dock_confirm_active = 0; ps_dock_stable = 0; ps_dock_confirm_reason = 1; return 1;
    }
    if ps_total <= ps_dock_confirm_last || ps_total - ps_dock_confirm_start > 25 || ps_dock_confirm_attempts >= 4 {
        ps_dock_confirm_active = 0; ps_dock_stable = 0; ps_dock_confirm_reason = 2; return 1;
    }
    if !ps_rgb_sample() || ps_brick_frame != ps_total { ps_dock_confirm_active = 0; ps_dock_stable = 0; ps_dock_confirm_reason = 5; return -1; }
    ps_dock_confirm_last = ps_total; ps_dock_confirm_attempts = ps_dock_confirm_attempts + 1;
    ps_collect_observe();
    // Preserve the existing travel rule: a newly observed obstacle cancels
    // the route and requests a scan before any further navigation.
    if ps_floor_changed { ps_floor_changed = 0; ps_dock_confirm_active = 0; ps_dock_stable = 0; ps_dock_confirm_reason = 6; if !ps_collect_search_begin() { return -1; } return 1; }
    if !ps_dock_valid || ps_dock_seen != ps_total { ps_dock_confirm_active = 0; ps_dock_stable = 0; ps_dock_confirm_reason = 3; return 1; }
    if ps_house_ready { ps_dock_confirm_active = 0; ps_dock_confirm_reason = 4; }
    else if ps_dock_confirm_attempts >= 4 { ps_dock_confirm_active = 0; ps_dock_stable = 0; ps_dock_confirm_reason = 2; }
    return 1;
}
'''


def once(text, old, new):
    if text.count(old) != 1:
        raise ValueError('unexpected source shape; refusing transformation')
    return text.replace(old, new, 1)


def transform(collect, discovery, main):
    if 'ps_dock_confirm_enabled' in collect or 'PUPPYBOT_DOCK_CONFIRM' in main:
        raise ValueError('source already contains confirmation experiment')
    collect = once(collect, 'fn ps_collect_reset() {', GLOBALS + '\nfn ps_collect_reset() {')
    collect = once(collect, 'fn ps_collect_travel_observe() {', HOOKS + '\nfn ps_collect_travel_observe() {')
    collect = once(collect, 'fn ps_collect_reset() {\n',
        'fn ps_collect_reset() {\n    ps_dock_confirm_active = 0; ps_dock_confirm_runs = 0; ps_dock_confirm_attempts = 0; ps_dock_confirm_reason = 0;\n')
    collect = once(collect,
        '    ps_collect_observe(); ps_brick_mark(); ps_brick_caption = ps_text_upload(ps_brick_caption, "RGB TCP - DISCOVERY TRAVEL");',
        '    ps_collect_observe(); if !ps_floor_changed { let confirm = ps_dock_confirm_begin(); if confirm < 0 { return -1; } if confirm { return 1; } }\n'
        '    ps_brick_mark(); ps_brick_caption = ps_text_upload(ps_brick_caption, "RGB TCP - DISCOVERY TRAVEL");')
    discovery = once(discovery, '    if ps_discovery_phase == 5 {\n        if ps_discovery_retrace',
        '    if ps_discovery_phase == 5 {\n        let confirming = ps_dock_confirm_tick(); if confirming < 0 { return ps_discovery_finish("dock confirmation sensor or stop failure", 1); } if confirming { return 1; }\n'
        '        if ps_discovery_retrace')
    discovery = once(discovery, '    pl_text(b, ",\\"mapFrameId\\":"); pl_int(b, ps_discovery_map_frame);',
        '    if ps_dock_confirm_enabled { pl_text(b, ",\\"dockConfirm\\":{\\"active\\":"); pj_bool_text(b, ps_dock_confirm_active); pl_text(b, ",\\"runs\\":"); pl_int(b, ps_dock_confirm_runs); pl_text(b, ",\\"attempts\\":"); pl_int(b, ps_dock_confirm_attempts); pl_text(b, ",\\"reason\\":"); pl_int(b, ps_dock_confirm_reason); pl_text(b, "}"); }\n'
        '    pl_text(b, ",\\"mapFrameId\\":"); pl_int(b, ps_discovery_map_frame);')
    marker = '    let search = pl_environment(argc, argv, "PUPPYBOT_PHYSICAL_SEARCH_FALLBACK");'
    main = once(main, marker,
        '    let confirm = pl_environment(argc, argv, "PUPPYBOT_DOCK_CONFIRM");\n'
        '    if confirm { if !pl_equal(confirm, "0") && !pl_equal(confirm, "1") { return 2; } ps_dock_confirm_enabled = pl_equal(confirm, "1"); }\n' + marker)
    return collect, discovery, main
