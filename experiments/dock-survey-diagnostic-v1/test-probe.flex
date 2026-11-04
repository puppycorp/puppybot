// Diagnostic I/O probe appended to a disposable copy of the simulator.
fn sd_require(ok, message) { if !ok { pl_print(2, message); pl_print(2, "\n"); syscall(231, 1, 0, 0, 0, 0, 0); } return 0; }
fn main(argc, argv) {
    if !pl_init() || argc != 3 { return 2; }
    let mode = load64(argv + 8); let path = load64(argv + 16);
    ps_case_stage = 18; ps_gripper_held = 1; ps_dock_samples = 7; ps_total = 70;
    ps_brick_samples = 1; ps_brick_frame = 70; ps_brick_time = 1400;
    ps_brick_rgb = alloc(640 * 480 * 3); pb_zero(ps_brick_rgb, 640 * 480 * 3); ps_brick_pose = alloc(96); pb_zero(ps_brick_pose, 96);
    let goal = alloc(24); pb_zero(goal, 24);
    if pl_equal(mode, "off") {
        sd_require(ps_dock_diag_survey() && ps_dock_diag_candidate(4, goal, 0), "disabled hook failed");
        sd_require(!ps_dock_diag_survey_count && !ps_dock_diag_plan_count && !ps_dock_diag_write_errors, "disabled hook wrote output"); return 0;
    }
    ps_dock_diag_dir = path; ps_dock_diag_searches = 2; ps_nav_expanded = 17;
    ps_dock_diag_survey(); sd_require(ps_dock_diag_survey_count == 1, "survey count missing");
    ps_dock_diag_reason(3); ps_dock_diag_candidate(4, goal, 0);
    sd_require(ps_dock_diag_plan_count == 1, "candidate count missing");
    if pl_equal(mode, "bad-path") { sd_require(ps_dock_diag_write_errors == 2, "missing write failures"); }
    else { sd_require(!ps_dock_diag_write_errors, "unexpected write failure"); }
    ps_dock_hint = alloc(24); pb_zero(ps_dock_hint, 24);
    ps_dock_frame = alloc(120); pb_zero(ps_dock_frame, 120);
    ps_dock_calibration = alloc(96); pb_zero(ps_dock_calibration, 96);
    ps_dock_corners = alloc(32); pb_zero(ps_dock_corners, 32);
    let text = alloc(8192); let builder = alloc(32); pl_builder(builder, text, 8192);
    pl_text(builder, "{\"probe\":true"); ps_dock_observation(builder); pl_text(builder, "}");
    sd_require(!load64(builder + 24), "observation serialization failed");
    syscall(1, 1, text, load64(builder + 8), 0, 0, 0);
    return 0;
}
