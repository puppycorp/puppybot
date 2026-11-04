#!/usr/bin/env python3
"""Instrument copied dock staging and viewpoint decisions without changing gates."""


def once(text, old, new):
    if text.count(old) != 1:
        raise ValueError('unexpected archived source shape')
    return text.replace(old, new, 1)


GLOBALS = '''// Opt-in observation of existing checks; these counters never authorize motion.
global ps_dc_scope = 0;
global ps_dc_last_reason = 0;
global ps_dc_stage_runs = 0;
global ps_dc_stage_total = 0;
global ps_dc_stage_near = 0;
global ps_dc_stage_clear = 0;
global ps_dc_stage_floor = 0;
global ps_dc_stage_observed = 0;
global ps_dc_stage_box = 0;
global ps_dc_stage_target = 0;
global ps_dc_stage_other = 0;
global ps_dc_drop_pass = 0;
global ps_dc_drop_fail = 0;
global ps_dc_route_pass = 0;
global ps_dc_route_fail = 0;

// 1 confirmed floor obstacle; 2 observed-floor map (including out of bounds); 3 box margin;
// 4 target exclusion; 5 non-discovery map; 6 training-oracle rejection.
// First failed check only; observed-floor combines unknown, occupied and out of bounds.
fn ps_dc_reject(reason) {
    if !ps_dock_diag_dir || !ps_dc_scope { return 0; }
    ps_dc_last_reason = reason;
    if ps_dc_scope == 1 {
        if reason == 1 { ps_dc_stage_floor = ps_dc_stage_floor + 1; }
        else if reason == 2 { ps_dc_stage_observed = ps_dc_stage_observed + 1; }
        else if reason == 3 { ps_dc_stage_box = ps_dc_stage_box + 1; }
        else if reason == 4 { ps_dc_stage_target = ps_dc_stage_target + 1; }
        else { ps_dc_stage_other = ps_dc_stage_other + 1; }
    }
    return 0;
}
fn ps_dc_observation(b) {
    if !ps_dock_diag_dir { return 1; }
    pl_text(b, ",\\\"clearanceDiagnostic\\\":{\\\"stageRuns\\\":"); pl_int(b, ps_dc_stage_runs);
    pl_text(b, ",\\\"stageCandidates\\\":"); pl_int(b, ps_dc_stage_total);
    pl_text(b, ",\\\"stageNear\\\":"); pl_int(b, ps_dc_stage_near);
    pl_text(b, ",\\\"stageClear\\\":"); pl_int(b, ps_dc_stage_clear);
    pl_text(b, ",\\\"stageFloorObstacle\\\":"); pl_int(b, ps_dc_stage_floor);
    pl_text(b, ",\\\"stageObservedFloor\\\":"); pl_int(b, ps_dc_stage_observed);
    pl_text(b, ",\\\"stageBoxMargin\\\":"); pl_int(b, ps_dc_stage_box);
    pl_text(b, ",\\\"stageTargetExclusion\\\":"); pl_int(b, ps_dc_stage_target);
    pl_text(b, ",\\\"stageOther\\\":"); pl_int(b, ps_dc_stage_other);
    pl_text(b, ",\\\"dropClearancePass\\\":"); pl_int(b, ps_dc_drop_pass);
    pl_text(b, ",\\\"dropClearanceFail\\\":"); pl_int(b, ps_dc_drop_fail);
    pl_text(b, ",\\\"routePass\\\":"); pl_int(b, ps_dc_route_pass);
    pl_text(b, ",\\\"routeFail\\\":"); pl_int(b, ps_dc_route_fail);
    return pl_text(b, "}");
}
'''


def transform(dock, search, nav):
    if 'ps_dc_scope' in dock or 'ps_dc_scope' in search or 'ps_dc_scope' in nav:
        raise ValueError('already instrumented')
    dock = once(dock, 'fn ps_dock_diag_reason(reason)', GLOBALS + '\nfn ps_dock_diag_reason(reason)')
    dock = once(dock,
        '    pl_text(b, ",\\\"expanded\\\":"); pl_int(b, ps_nav_expanded); pl_text(b, "}\\n");',
        '    pl_text(b, ",\\\"expanded\\\":"); pl_int(b, ps_nav_expanded); pl_text(b, ",\\\"clearanceDetail\\\":"); pl_int(b, ps_dc_last_reason); pl_text(b, "}\\n");')
    dock = once(dock, '    pl_char(b, 93); if ps_dock_diag_dir { pl_text(b, ",\\\"surveyDiagnostic\\\":',
        '    pl_char(b, 93); ps_dc_observation(b); if ps_dock_diag_dir { pl_text(b, ",\\\"surveyDiagnostic\\\":')
    nav = once(nav,
        '    if ps_nav_training_oracle { return ps_vehicle_free(x, y, heading); }',
        '    if ps_nav_training_oracle { let free = ps_vehicle_free(x, y, heading); if !free { return ps_dc_reject(6); } return free; }')
    nav = once(nav,
        '        if !ps_floor_clear(x, y, heading) || !ps_nav_observed_clear(x, y, heading) { return 0; }',
        '        if !ps_floor_clear(x, y, heading) { return ps_dc_reject(1); }\n'
        '        if !ps_nav_observed_clear(x, y, heading) { return ps_dc_reject(2); }')
    nav = once(nav,
        '        if ps_collect_enabled && ps_house_ready && f64_lt(ps_nav_box_gap(x, y, heading), 0) { return 0; }',
        '        if ps_collect_enabled && ps_house_ready && f64_lt(ps_nav_box_gap(x, y, heading), 0) { return ps_dc_reject(3); }')
    nav = once(nav,
        '            if f64_lt(along, ps_number(167, 1000)) && f64_lt(across, ps_number(14, 100)) { return 0; }',
        '            if f64_lt(along, ps_number(167, 1000)) && f64_lt(across, ps_number(14, 100)) { return ps_dc_reject(4); }')
    nav = once(nav,
        '    if !ps_floor_clear(x, y, heading) { return 0; }\n    let cell = ps_nav_cell(x, y); if cell < 0 || load8(ps_nav_map + cell) { return 0; }',
        '    if !ps_floor_clear(x, y, heading) { return ps_dc_reject(1); }\n'
        '    let cell = ps_nav_cell(x, y); if cell < 0 || load8(ps_nav_map + cell) { return ps_dc_reject(5); }')
    nav = once(nav,
        '        if f64_lt(along, ps_number(19, 100)) && f64_lt(across, ps_number(14, 100)) { return 0; }',
        '        if f64_lt(along, ps_number(19, 100)) && f64_lt(across, ps_number(14, 100)) { return ps_dc_reject(4); }')
    nav = once(nav,
        '            if !ps_nav_searching || !ps_nav_escape || f64_lt(gap, ps_nav_escape_gap) { return 0; }\n'
        '            let dx = f64_sub(x, ps_nav_escape_x); let dy = f64_sub(y, ps_nav_escape_y);\n'
        '            if f64_gt(f64_add(f64_mul(dx, dx), f64_mul(dy, dy)), ps_number(144, 10000)) { return 0; }\n'
        '            dx = f64_sub(x, load64(ps_dock_frame + 96)); dy = f64_sub(y, load64(ps_dock_frame + 104));\n'
        '            if f64_lt(f64_add(f64_mul(dx, dx), f64_mul(dy, dy)), ps_nav_escape_distance) { return 0; }',
        '            if !ps_nav_searching || !ps_nav_escape || f64_lt(gap, ps_nav_escape_gap) { return ps_dc_reject(3); }\n'
        '            let dx = f64_sub(x, ps_nav_escape_x); let dy = f64_sub(y, ps_nav_escape_y);\n'
        '            if f64_gt(f64_add(f64_mul(dx, dx), f64_mul(dy, dy)), ps_number(144, 10000)) { return ps_dc_reject(3); }\n'
        '            dx = f64_sub(x, load64(ps_dock_frame + 96)); dy = f64_sub(y, load64(ps_dock_frame + 104));\n'
        '            if f64_lt(f64_add(f64_mul(dx, dx), f64_mul(dy, dy)), ps_nav_escape_distance) { return ps_dc_reject(3); }')
    nav = once(nav, '    if ps_dock_diag_dir { ps_dock_diag_plan_reason = 0; }',
        '    if ps_dock_diag_dir { ps_dock_diag_plan_reason = 0; ps_dc_last_reason = 0; }')
    nav = once(nav,
        '    else if !ps_nav_clear(x, y, heading) { return ps_dock_diag_reason(3); }',
        '    else {\n'
        '        if ps_dock_diag_dir { ps_dc_scope = 2; }\n'
        '        let goal_clear = ps_nav_clear(x, y, heading);\n'
        '        if ps_dock_diag_dir { ps_dc_scope = 0; }\n'
        '        if !goal_clear { return ps_dock_diag_reason(3); }\n'
        '    }')
    search = once(search, 'fn ps_dock_search_stage() {\n',
        'fn ps_dock_search_stage() {\n    if ps_dock_diag_dir { ps_dc_stage_runs = ps_dc_stage_runs + 1; }\n')
    search = once(search,
        '                if f64_gt(distance, ps_number(5, 100)) && ps_nav_clear(x, y, heading) {\n'
        '                    let p = ps_dock_search_candidates + count * 32; store64(p, x); store64(p + 8, y); store64(p + 16, heading); store64(p + 24, score); count = count + 1;\n'
        '                }',
        '                if ps_dock_diag_dir { ps_dc_stage_total = ps_dc_stage_total + 1; }\n'
        '                if f64_gt(distance, ps_number(5, 100)) {\n'
        '                    if ps_dock_diag_dir { ps_dc_scope = 1; }\n'
        '                    let clear = ps_nav_clear(x, y, heading);\n'
        '                    if ps_dock_diag_dir { ps_dc_scope = 0; if clear { ps_dc_stage_clear = ps_dc_stage_clear + 1; } }\n'
        '                    if clear { let p = ps_dock_search_candidates + count * 32; store64(p, x); store64(p + 8, y); store64(p + 16, heading); store64(p + 24, score); count = count + 1; }\n'
        '                } else if ps_dock_diag_dir { ps_dc_stage_near = ps_dc_stage_near + 1; }')
    search = once(search,
        '        if ps_case_drop_clearance(180, x, y, heading) {\n'
        '            if ps_collect_enabled { planned = ps_nav_plan_release(x, y, heading); } else { planned = ps_nav_plan(x, y, heading); }\n'
        '        }\n'
        '        if planned {',
        '        let drop_clear = ps_case_drop_clearance(180, x, y, heading);\n'
        '        if ps_dock_diag_dir { if drop_clear { ps_dc_drop_pass = ps_dc_drop_pass + 1; } else { ps_dc_drop_fail = ps_dc_drop_fail + 1; } }\n'
        '        if drop_clear {\n'
        '            if ps_collect_enabled { planned = ps_nav_plan_release(x, y, heading); } else { planned = ps_nav_plan(x, y, heading); }\n'
        '            if ps_dock_diag_dir { if planned { ps_dc_route_pass = ps_dc_route_pass + 1; } else { ps_dc_route_fail = ps_dc_route_fail + 1; } }\n'
        '        }\n'
        '        if planned {')
    return dock, search, nav
