// The caller supplies stubs for IK, arm command and failure. This probes
// dispatch, not the real collision guard or physical wrist motion.
fn high_reset() {
    ps_survey_high_enabled = 0; ps_survey_high_attempts = 0; ps_survey_high_accepted = 0;
    ps_survey_high_ik_rejected = 0; ps_survey_high_move_rejected = 0;
    ps_survey_high_request_id = 0; ps_survey_high_settled_step = -1;
    ps_agent_physical = 1; ps_collect_enabled = 1; ps_gripper_held = 1;
    ps_case_camera = 2; ps_dock_seen = 0; ps_dock_hint_seen = -1; ps_total = 100;
    ps_dock_search_active = 0; ps_dock_search_blocks = 1; ps_case_survey_index = 0;
    ps_case_stage = 0; ps_camera_drive_mode = 1;
    test_solve_calls = 0; test_apply_calls = 0; test_high_ok = 1;
    test_move_ticks = 200; test_apply_error = 0; test_failure = 0;
}
fn main() {
    if !pl_init() { return 1; }
    ps_asset = alloc(1024); ps_groups = 1; ps_case_point = alloc(24); ps_dock_frame = alloc(128);
    ps_pickup_targets = alloc(32); ps_plant = alloc(2048); ps_bus = alloc(16384);
    store64(ps_plant + 8, ps_bus); ps_local_mode = 1;
    ps_local_x = 0; ps_local_y = 0; ps_local_heading = 0;
    store64(ps_dock_frame + 96, f64_from_i64(1)); store64(ps_dock_frame + 104, 0);
    high_reset();
    if !ps_case_tcp_survey() || test_solve_calls != 1 || test_pitch0 != 60 || test_height0 != 340 || ps_survey_high_attempts { return 2; }
    if f64_gt(f64_magnitude(f64_sub(test_radius0, ps_number(14, 100))), ps_number(1, 1000000)) { return 3; }
    high_reset(); ps_survey_high_enabled = 1;
    if !ps_case_tcp_survey() || test_solve_calls != 1 || test_height0 != 380 || test_pitch0 != 80 ||
       ps_survey_high_attempts != 1 || ps_survey_high_accepted != 1 || test_apply_calls != 1 ||
       ps_case_stage != 20 || ps_camera_drive_mode || ps_case_survey_timeout != 1234 { return 4; }
    if f64_gt(f64_magnitude(f64_sub(test_radius0, ps_number(4, 100))), ps_number(1, 1000000)) { return 5; }
    high_reset(); ps_survey_high_enabled = 1; test_high_ok = 0;
    if !ps_case_tcp_survey() || test_solve_calls != 2 || test_height1 != 340 || test_pitch1 != 60 ||
       ps_survey_high_ik_rejected != 1 || ps_survey_high_accepted || test_apply_calls != 1 { return 6; }
    if f64_gt(f64_magnitude(f64_sub(test_radius1, ps_number(14, 100))), ps_number(1, 1000000)) { return 7; }
    high_reset(); ps_survey_high_enabled = 1; test_move_ticks = 2049;
    if !ps_case_tcp_survey() || test_solve_calls != 2 || ps_survey_high_move_rejected != 1 || test_apply_calls != 1 { return 8; }
    high_reset(); ps_survey_high_enabled = 1; test_apply_error = 1;
    if ps_case_tcp_survey() || test_solve_calls != 1 || test_apply_calls != 1 || !test_failure || ps_case_stage != 13 { return 9; }
    high_reset(); ps_survey_high_enabled = 1; ps_gripper_held = 0;
    if !ps_case_tcp_survey() || test_solve_calls != 1 || test_pitch0 != 60 || ps_survey_high_attempts { return 10; }
    high_reset(); ps_survey_high_enabled = 1; ps_agent_physical = 0;
    if !ps_case_tcp_survey() || test_solve_calls != 1 || test_pitch0 != 60 || ps_survey_high_attempts { return 11; }
    high_reset(); ps_survey_high_enabled = 1; ps_collect_enabled = 0;
    if !ps_case_tcp_survey() || test_solve_calls != 1 || test_pitch0 != 60 || ps_survey_high_attempts { return 12; }
    // The existing 15-sample settling transition must be reached before a
    // matching high pose can be associated with survey frames.
    high_reset(); ps_survey_high_enabled = 1; ps_house_ready = 1;
    if !ps_case_tcp_survey() || ps_survey_high_request_id != 1 || ps_survey_high_settled_step != -1 { return 13; }
    let i = 0; while i < 4 { store64(ps_plant + 128 + i * 64 + 16, 100 + i * 100); i = i + 1; }
    i = 0; while i < 14 { ps_total = ps_total + 1; ps_case_update(); i = i + 1; }
    if ps_case_stage != 20 || ps_survey_high_settled_step != -1 || ps_case_high_arm_still_matching() { return 14; }
    ps_total = ps_total + 1; ps_case_update();
    if ps_case_stage != 18 || ps_survey_high_settled_step != ps_total || !ps_case_high_arm_still_matching() { return 15; }
    store64(ps_plant + 128 + 16, 109); if ps_case_high_arm_still_matching() { return 16; }
    store64(ps_plant + 128 + 16, 100); ps_camera_drive_mode = 1;
    if ps_case_high_arm_still_matching() { return 17; } ps_camera_drive_mode = 0;
    store64(ps_pickup_targets, 999); if ps_case_high_arm_still_matching() { return 18; }
    store64(ps_pickup_targets, 100); if !ps_case_high_arm_still_matching() { return 19; }
    store64(ps_plant + 128 + 8, 1); if ps_case_high_arm_still_matching() { return 26; }
    store64(ps_plant + 128 + 8, 0); store64(ps_bus + 24, 1);
    if ps_case_high_arm_still_matching() { return 27; } store64(ps_bus + 24, 0);
    ps_gripper_held = 0; if ps_case_high_arm_still_matching() { return 28; } ps_gripper_held = 1;
    let b = alloc(32); let text = alloc(512); pl_builder(b, text, 512); pl_text(b, "{\"prefix\":0");
    ps_survey_high_enabled = 0; if ps_case_high_survey_observation(b) { return 20; }
    ps_survey_high_enabled = 1; ps_survey_high_attempts = 3; ps_survey_high_accepted = 1;
    ps_survey_high_ik_rejected = 1; ps_survey_high_move_rejected = 1;
    if !ps_case_high_survey_observation(b) { return 21; } pl_char(b, 125);
    let json = pj_parse(text, load64(b + 8)); let high = pj_get(json, "surveyHigh");
    if !json || !high || pj_integer(high, "attempts", 0, 10) != 3 ||
       pj_integer(high, "accepted", 0, 10) != 1 || pj_integer(high, "ikRejected", 0, 10) != 1 ||
       pj_integer(high, "moveRejected", 0, 10) != 1 || pj_integer(high, "requestId", 0, 10) != 1 ||
       pj_integer(high, "settledStep", 0, 1000) != ps_total || !pj_boolean(high, "armStillMatching") ||
       pj_count(pj_get(high, "targetTicks")) != 4 { return 22; }
    ps_case_phase(24);
    if ps_survey_high_request_id || ps_survey_high_settled_step != -1 || ps_case_high_arm_still_matching() { return 23; }
    high_reset(); ps_survey_high_enabled = 1;
    if !ps_case_tcp_survey() || !ps_survey_high_request_id { return 24; }
    test_high_ok = 0;
    if !ps_case_tcp_survey() || ps_survey_high_request_id || ps_survey_high_settled_step != -1 { return 25; }
    pl_print(1, "High survey dispatch checks passed.\n"); return 0;
}
