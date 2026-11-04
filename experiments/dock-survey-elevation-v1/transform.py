#!/usr/bin/env python3
"""Stage an opt-in high wrist survey on a copied simulator source tree."""


def once(source, old, new):
    if source.count(old) != 1:
        raise ValueError('archived simulator source differs from expected anchor')
    return source.replace(old, new, 1)


def transform(case, main):
    case = once(case, 'global ps_case_survey_index = 0;',
                'global ps_case_survey_index = 0;\n'
                'global ps_survey_high_enabled = 0;\n'
                'global ps_survey_high_attempts = 0;\n'
                'global ps_survey_high_accepted = 0;\n'
                'global ps_survey_high_ik_rejected = 0;\n'
                'global ps_survey_high_move_rejected = 0;\n'
                'global ps_survey_high_request_id = 0;\n'
                'global ps_survey_high_settled_step = -1;\n'
                'global ps_survey_high_target_ticks = 0;')
    case = once(case, '    ps_case_survey_index = 0; ps_case_survey_timeout = 1000;',
                '    ps_case_survey_index = 0; ps_case_survey_timeout = 1000;\n'
                '    ps_survey_high_attempts = 0; ps_survey_high_accepted = 0;\n'
                '    ps_survey_high_ik_rejected = 0; ps_survey_high_move_rejected = 0;\n'
                '    ps_survey_high_request_id = 0; ps_survey_high_settled_step = -1;')
    case = once(case, 'fn ps_case_phase(stage) { ps_case_stage = stage; ps_case_steps = 0; ps_case_stable = 0; ps_pickup_stable = 0; return 0; }',
                '''fn ps_case_phase(stage) {
    if ps_survey_high_enabled && stage != 20 && stage != 18 {
        ps_survey_high_request_id = 0; ps_survey_high_settled_step = -1;
    }
    ps_case_stage = stage; ps_case_steps = 0; ps_case_stable = 0; ps_pickup_stable = 0; return 0;
}''')
    case = once(case, 'fn ps_case_tcp_survey() {', '''fn ps_case_high_targets_match() {
    if !ps_survey_high_target_ticks || !ps_pickup_targets { return 0; }
    let i = 0; while i < 4 {
        if load64(ps_survey_high_target_ticks + i * 8) != load64(ps_pickup_targets + i * 8) { return 0; }
        i = i + 1;
    } return 1;
}
fn ps_case_high_mark_settled() {
    if ps_survey_high_enabled && ps_survey_high_request_id && ps_case_high_targets_match() &&
       gs_reached(ps_plant, ps_survey_high_target_ticks) && gs_stopped(ps_plant) {
        ps_survey_high_settled_step = ps_total; return 1;
    } return 0;
}
fn ps_case_high_arm_still_matching() {
    return ps_survey_high_enabled && ps_survey_high_request_id && ps_survey_high_settled_step >= 0 &&
        ps_total >= ps_survey_high_settled_step && ps_case_stage == 18 && ps_gripper_held &&
        !ps_camera_drive_mode && ps_case_high_targets_match() &&
        gs_reached(ps_plant, ps_survey_high_target_ticks) && gs_stopped(ps_plant);
}
fn ps_case_high_survey_observation(b) {
    if !ps_survey_high_enabled { return 0; }
    pl_text(b, ",\\\"surveyHigh\\\":{\\\"attempts\\\":"); pl_int(b, ps_survey_high_attempts);
    pl_text(b, ",\\\"accepted\\\":"); pl_int(b, ps_survey_high_accepted);
    pl_text(b, ",\\\"ikRejected\\\":"); pl_int(b, ps_survey_high_ik_rejected);
    pl_text(b, ",\\\"moveRejected\\\":"); pl_int(b, ps_survey_high_move_rejected);
    pl_text(b, ",\\\"requestId\\\":"); pl_int(b, ps_survey_high_request_id);
    pl_text(b, ",\\\"settledStep\\\":"); pl_int(b, ps_survey_high_settled_step);
    pl_text(b, ",\\\"armStillMatching\\\":"); pj_bool_text(b, ps_case_high_arm_still_matching());
    pl_text(b, ",\\\"targetTicks\\\":");
    if !ps_survey_high_request_id { pl_text(b, "null"); }
    else { pl_char(b, 91); let i = 0; while i < 4 { if i { pl_char(b, 44); } pl_int(b, load64(ps_survey_high_target_ticks + i * 8)); i = i + 1; } pl_char(b, 93); }
    pl_char(b, 125); return 1;
}
// This simulator-only probe uses the same estimated bearing and IK path as
// the existing survey. It does not use truth, authorize a base move or release.
// The existing simulator arm collision guard and failure path still apply.
fn ps_case_high_survey(x, y, angle) {
    ps_survey_high_attempts = ps_survey_high_attempts + 1;
    let point = ps_case_point;
    store64(point, f64_add(x, f64_mul(ps_number(4, 100), f64_cos(angle))));
    store64(point + 8, f64_add(y, f64_mul(ps_number(4, 100), f64_sin(angle))));
    if !ps_arm_solve(point, 380, 80) { ps_survey_high_ik_rejected = ps_survey_high_ik_rejected + 1; return 0; }
    if ps_arm_move_ticks() > 2048 { ps_survey_high_move_rejected = ps_survey_high_move_rejected + 1; return 0; }
    ps_case_survey_timeout = ps_arm_move_timeout();
    if !ps_survey_high_target_ticks { ps_survey_high_target_ticks = alloc(32); }
    pb_copy(ps_survey_high_target_ticks, ps_pickup_targets, 32);
    if pr_apply(ps_app, 5, ps_pickup_targets, ps_time) { ps_case_fail("cannot command high TCP survey pose"); return -1; }
    ps_survey_high_accepted = ps_survey_high_accepted + 1;
    ps_survey_high_request_id = ps_survey_high_accepted; ps_survey_high_settled_step = -1;
    ps_camera_drive_mode = 0; ps_case_phase(20); return 1;
}
fn ps_case_tcp_survey() {
    if ps_survey_high_enabled { ps_survey_high_request_id = 0; ps_survey_high_settled_step = -1; }''')
    case = once(case, '        store64(point, f64_add(x, f64_mul(ps_number(14, 100), f64_cos(angle)))); store64(point + 8, f64_add(y, f64_mul(ps_number(14, 100), f64_sin(angle)))); height = 340;',
                '''        if ps_survey_high_enabled && ps_agent_physical && ps_collect_enabled && ps_gripper_held {
            let high = ps_case_high_survey(x, y, angle);
            if high > 0 { return 1; } if high < 0 { return 0; }
        }
        store64(point, f64_add(x, f64_mul(ps_number(14, 100), f64_cos(angle)))); store64(point + 8, f64_add(y, f64_mul(ps_number(14, 100), f64_sin(angle)))); height = 340;''')
    case = once(case, '        ps_brick_observation(b); ps_dock_observation(b); ps_house_observation(b);',
                '''        ps_brick_observation(b); ps_dock_observation(b);
        ps_case_high_survey_observation(b); ps_house_observation(b);''')
    case = once(case, '    if ps_case_stage == 20 && ps_pickup_settled() { if ps_house_enabled() && !ps_house_ready { ps_case_phase(23); return 1; } ps_case_return_direction = -1; ps_case_phase(18); return 1; }',
                '''    if ps_case_stage == 20 && ps_pickup_settled() {
        ps_case_high_mark_settled();
        if ps_house_enabled() && !ps_house_ready { ps_case_phase(23); return 1; }
        ps_case_return_direction = -1; ps_case_phase(18); return 1;
    }''')
    main = once(main, '    ps_dock_diag_dir = pl_environment(argc, argv, "PUPPYBOT_DOCK_DIAG_DIRECTORY");',
                '''    let high_survey = pl_environment(argc, argv, "PUPPYBOT_DOCK_HIGH_SURVEY");
    if high_survey {
        if !pl_equal(high_survey, "0") && !pl_equal(high_survey, "1") { pl_print(2, "Invalid high survey option.\\n"); return 2; }
        ps_survey_high_enabled = pl_equal(high_survey, "1");
    }
    ps_dock_diag_dir = pl_environment(argc, argv, "PUPPYBOT_DOCK_DIAG_DIRECTORY");''')
    return case, main
