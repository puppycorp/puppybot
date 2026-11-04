// Native state-machine probe. Sensor and actuator command dependencies are
// stubs; the existing failure/stop implementation and joint state are real.
global probe_commands = 0;
global probe_opens = 0;
global probe_surveys = 0;
global probe_stages = 0;
global probe_settled = 1;
global probe_patched = @@PATCHED@@;

fn probe_setup() {
    ps_robot = alloc(8192); pb_robot_init(ps_robot, 0);
    ps_app = alloc(2048); pb_zero(ps_app, 2048); store64(ps_app, ps_robot);
    ps_pickup_targets = alloc(32); ps_case_drop_ticks = alloc(32);
    ps_dock_frame = alloc(128); ps_case_drop_frame = alloc(128);
    pb_zero(ps_dock_frame, 128); pb_zero(ps_case_drop_frame, 128);
    store64(ps_dock_frame, PB_ONE); store64(ps_case_drop_frame, PB_ONE);
    ps_dock_seen = 1; ps_total = 100; ps_dock_valid = 0; ps_dock_stable = 3;
    ps_brick_frame = ps_total; ps_case_camera = 2; ps_collect_enabled = 1;
    ps_gripper_held = 1; ps_case_drop_timeout = 1000; ps_time = 100;
    probe_commands = 0; probe_opens = 0; probe_surveys = 0; probe_stages = 0;
    probe_settled = 1;
    return 1;
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
    // A successful stage based on old coordinates ends mapping and asks for
    // a survey; it does not itself command movement or open the gripper.
    ps_collect_mapping = 1; ps_dock_floor_retry_mapping = 0; ps_case_stage = 35;
    if !ps_collect_map_finish() || probe_stages != 1 || probe_surveys != 1 || ps_collect_mapping || probe_opens || probe_commands { return 10; }
    ps_case_stage = 18; ps_case_steps = 2;
    if !ps_case_return_update() || probe_commands || probe_opens { return 11; }
    // Ordinary non-turning release stages refuse a stale observation.
    ps_total = 20; ps_dock_seen = 1;
    ps_case_stage = 7; ps_case_steps = 2; ps_case_drop_turning = 0;
    if !ps_case_update() || probe_commands || probe_opens { return 12; }
    ps_case_stage = 8; ps_case_steps = 2; ps_brick_frame = ps_total;
    if !ps_case_update() || probe_commands || probe_opens { return 13; }
    // An already-commanded yaw turn is still active when freshness expires.
    ps_total = 100; ps_case_stage = 8; ps_case_steps = 2; ps_case_drop_turning = 1;
    pb_js(pb_joint(ps_robot, 0), PB_J_TARGET_VALID, 1); pb_js(pb_joint(ps_robot, 0), PB_J_SPEED, 20);
    pb_drive_steer(pb_robot_drive(ps_robot), 10, 0, ps_time);
    let result = ps_case_update();
    if probe_patched {
        if result || ps_case_stage != 13 || probe_commands || !probe_check_stop() { return 14; }
        // Fail closed for unstable evidence too, without waiting for yaw.
        probe_setup(); ps_dock_valid = 1; ps_dock_seen = 100; ps_dock_stable = 2;
        ps_case_stage = 7; ps_case_steps = 2; ps_case_drop_turning = 1;
        if ps_case_update() || ps_case_stage != 13 || probe_commands || !probe_check_stop() { return 15; }
        // Fresh stable unchanged observations still allow the existing turn.
        probe_setup(); ps_dock_valid = 1; ps_dock_seen = 100;
        ps_case_stage = 8; ps_case_steps = 2; ps_case_drop_turning = 1;
        if !ps_case_update() || probe_commands != 1 || probe_opens { return 16; }
        // A changed destination fails before any lowering command.
        probe_setup(); ps_dock_valid = 1; ps_dock_seen = 100;
        store64(ps_dock_frame + 96, ps_number(1, 10));
        ps_case_stage = 8; ps_case_steps = 2; ps_case_drop_turning = 1;
        if ps_case_update() || ps_case_stage != 13 || probe_commands || !probe_check_stop() { return 17; }
        // Even a valid but expired reading stops an in-progress turn before
        // waiting for arm settlement or issuing another arm target.
        probe_setup(); ps_dock_valid = 1; ps_dock_seen = 1; probe_settled = 0;
        ps_case_stage = 7; ps_case_steps = 2; ps_case_drop_turning = 1;
        pb_js(pb_joint(ps_robot, 0), PB_J_TARGET_VALID, 1); pb_js(pb_joint(ps_robot, 0), PB_J_SPEED, 20);
        if ps_case_update() || ps_case_stage != 13 || probe_commands || !probe_check_stop() { return 19; }
    } else {
        if !result || probe_commands != 1 || ps_case_drop_turning || probe_opens { return 18; }
    }
    pl_print(1, "turn freshness probe passed\n"); return 0;
}
