// Native comparison: detector and actuators are stubs; the state machine and
// failure stop use the copied simulator's real code.
global probe_commands = 0;
global probe_opens = 0;
global probe_surveys = 0;
global probe_stages = 0;
global probe_stows = 0;
global probe_settled = 1;
global probe_samples = 0;
global probe_sample_mode = 0;
global probe_patched = @@PATCHED@@;

fn probe_setup() {
    ps_robot = alloc(8192); pb_robot_init(ps_robot, 0);
    ps_app = alloc(2048); pb_zero(ps_app, 2048); store64(ps_app, ps_robot);
    ps_pickup_targets = alloc(32); ps_case_drop_ticks = alloc(32);
    ps_dock_frame = alloc(128); ps_case_drop_frame = alloc(128);
    pb_zero(ps_dock_frame, 128); pb_zero(ps_case_drop_frame, 128);
    store64(ps_dock_frame, PB_ONE); store64(ps_case_drop_frame, PB_ONE);
    ps_total = 100; ps_time = 100; ps_dock_seen = 1; ps_dock_valid = 0; ps_dock_stable = 3;
    ps_brick_frame = ps_total; ps_case_camera = 2; ps_collect_enabled = 1;
    ps_gripper_held = 1; ps_case_drop_timeout = 1000; ps_case_stage = 8; ps_case_steps = 2; ps_case_drop_turning = 1;
    ps_case_drop_reacquire_started = -1; ps_case_drop_reacquire_last = -1;
    probe_commands = 0; probe_opens = 0; probe_surveys = 0; probe_stages = 0; probe_stows = 0;
    probe_settled = 1; probe_samples = 0; probe_sample_mode = 0; return 1;
}
fn probe_check_stop() {
    let i = 0; while i < 4 {
        if pb_j(pb_joint(ps_robot, i), PB_J_TARGET_VALID) || pb_j(pb_joint(ps_robot, i), PB_J_SPEED) { return 0; }
        i = i + 1;
    }
    return ps_gripper_held && !probe_opens && !pb_vget(pb_robot_drive(ps_robot), 9);
}
fn main(argc, argv) {
    if !pl_init() { return 1; } probe_setup();
    // With the same settled invalid observation the immediate guard stops;
    // the candidate begins waiting, sends no target and retains the payload.
    let first = ps_case_update();
    if !probe_patched {
        if first || ps_case_stage != 13 || probe_commands || !probe_check_stop() { return 10; }
        pl_print(1, "turn reacquisition probe passed\n"); return 0;
    }
    if !first || ps_case_stage != 8 || ps_case_drop_reacquire_started != 100 ||
       ps_dock_stable || probe_commands || probe_opens || !ps_gripper_held { return 11; }
    // Normal scheduled samples rebuild stability. Before the third sample,
    // no second arm command or open command is issued.
    probe_sample_mode = 1; let i = 1;
    while i <= 28 {
        ps_total = 100 + i;
        if !ps_case_update() { return 12; }
        if i < 28 && (probe_commands || probe_opens || ps_case_stage != 8) { return 13; }
        i = i + 1;
    }
    if probe_samples != 3 || probe_commands != 1 || probe_opens || ps_case_drop_turning ||
       ps_case_drop_reacquire_started != -1 { return 14; }
    // The later stage-eight release check still rejects both stale and
    // changed observations after the lowering command has been issued.
    ps_total = 129; ps_brick_frame = 129; probe_sample_mode = 2;
    if !ps_case_update() || probe_commands != 1 || probe_opens || probe_stows { return 40; }
    ps_total = 130; ps_brick_frame = 130; ps_dock_valid = 1; ps_dock_seen = 130; ps_dock_stable = 3;
    store64(ps_dock_frame + 96, ps_number(1, 10));
    if !ps_case_update() || probe_commands != 1 || probe_opens || probe_stows != 1 { return 41; }
    // Previously fresh and stable unchanged vision preserves immediate action.
    probe_setup(); ps_dock_valid = 1; ps_dock_seen = 100;
    if !ps_case_update() || probe_commands != 1 || probe_opens || ps_case_drop_reacquire_started != -1 { return 15; }
    // A fresh, confirmed changed box fails, including during later settling
    // flapping; the old target is never reused.
    probe_setup(); if !ps_case_update() { return 16; }
    ps_total = 101; probe_settled = 0; ps_dock_valid = 1; ps_dock_seen = 101; ps_dock_stable = 3;
    store64(ps_dock_frame + 96, ps_number(1, 10));
    if ps_case_update() || ps_case_stage != 13 || probe_commands || !probe_check_stop() { return 17; }
    // Loss of payload fails even before settlement and during a wait.
    probe_setup(); probe_settled = 0; ps_gripper_held = 0;
    if ps_case_update() || ps_case_stage != 13 || probe_commands || probe_opens { return 18; }
    probe_setup(); if !ps_case_update() { return 19; }
    ps_total = 101; ps_gripper_held = 0;
    if ps_case_update() || ps_case_stage != 13 || probe_commands || probe_opens { return 20; }
    // After starting, settlement flapping does not extend the 50-tick cap.
    probe_setup(); if !ps_case_update() { return 21; } probe_settled = 0; i = 1;
    while i < 50 { ps_total = 100 + i; if !ps_case_update() || probe_commands || probe_opens { return 22; } i = i + 1; }
    ps_total = 150; if ps_case_update() || ps_case_stage != 13 || probe_commands || !probe_check_stop() { return 23; }
    // Even a qualifying sample exactly at the deadline cannot extend it.
    probe_setup(); if !ps_case_update() { return 24; }
    ps_total = 149; ps_case_drop_reacquire_last = 149; ps_case_steps = 0; probe_sample_mode = 1; ps_dock_stable = 2;
    ps_total = 150; if ps_case_update() || ps_case_stage != 13 || probe_commands || probe_samples != 1 { return 25; }
    // Clock stagnation and reversal fail closed, with the prior target stopped.
    probe_setup(); if !ps_case_update() { return 26; }
    if ps_case_update() || ps_case_stage != 13 || probe_commands || !probe_check_stop() { return 27; }
    probe_setup(); if !ps_case_update() { return 28; } ps_total = 99;
    if ps_case_update() || ps_case_stage != 13 || probe_commands || !probe_check_stop() { return 29; }
    // A valid frame dated before the wait cannot satisfy it, even if the
    // stability count is somehow restored by another component.
    probe_setup(); if !ps_case_update() { return 30; } ps_total = 101;
    ps_dock_valid = 1; ps_dock_seen = 99; ps_dock_stable = 3;
    if !ps_case_update() || probe_commands || ps_case_drop_reacquire_started != 100 { return 31; }
    // The existing phase timeout can terminate before the new 50-tick cap.
    probe_setup(); ps_case_drop_timeout = 4; if !ps_case_update() { return 32; } ps_total = 101;
    if !ps_case_update() { return 33; } ps_total = 102;
    if ps_case_update() || ps_case_stage != 13 || probe_commands || !probe_check_stop() { return 34; }
    // A new target resets the wait, including a target rejected as not fresh.
    probe_setup(); if !ps_case_update() { return 35; }
    if ps_case_drop_target(180) || ps_case_drop_reacquire_started != -1 || ps_case_drop_reacquire_last != -1 { return 36; }
    // Non-camera cases retain their previous behavior.
    probe_setup(); ps_case_camera = 0;
    if !ps_case_update() || probe_commands != 1 || probe_opens || probe_samples { return 37; }
    // An episode reset clears any abandoned wait and resets detector state.
    probe_setup(); if !ps_case_update() { return 38; } ps_dock_frame = 0;
    ps_case_reset();
    if ps_case_drop_reacquire_started != -1 || ps_case_drop_reacquire_last != -1 || ps_dock_valid { return 39; }
    pl_print(1, "turn reacquisition probe passed\n"); return 0;
}
