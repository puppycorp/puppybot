global probe_commands = 0;
global probe_opens = 0;
global probe_candidate = @@CANDIDATE@@;
global probe_duration = @@DURATION@@;

fn main(argc, argv) {
    if !pl_init() { return 1; }
    ps_robot = alloc(8192); pb_robot_init(ps_robot, 0);
    ps_app = alloc(2048); pb_zero(ps_app, 2048); store64(ps_app, ps_robot);
    ps_pickup_targets = alloc(32); ps_case_drop_ticks = alloc(32);
    ps_dock_frame = alloc(128); ps_case_drop_frame = alloc(128);
    pb_zero(ps_dock_frame, 128); pb_zero(ps_case_drop_frame, 128);
    store64(ps_dock_frame, PB_ONE); store64(ps_case_drop_frame, PB_ONE);
    ps_total = 100; ps_time = 100; ps_dock_seen = 100; ps_dock_valid = 1; ps_dock_stable = 3;
    ps_brick_frame = 100; ps_case_camera = 2; ps_collect_enabled = 1;
    ps_gripper_held = 1; ps_case_drop_timeout = 1000; ps_case_stage = 8; ps_case_steps = 2; ps_case_drop_turning = 1;
    let result = ps_case_update();
    if ps_turn_probe_at != 100 { return 10; }
    if !probe_duration {
        if !result || probe_commands != 1 || ps_turn_probe_lower_at != 100 || probe_opens { return 11; }
    } else if !probe_candidate {
        if result || ps_case_stage != 13 || probe_commands || probe_opens { return 12; }
    } else {
        if !result || probe_commands || ps_case_drop_reacquire_started != 100 { return 13; }
        let i = 1;
        while i <= 50 && ps_case_stage != 13 && !probe_commands {
            ps_total = 100 + i; result = ps_case_update(); i = i + 1;
        }
        if probe_duration == 10 {
            if !result || probe_commands != 1 || ps_turn_probe_lower_at <= 110 || ps_turn_probe_lower_at >= 150 || probe_opens { return 14; }
        } else {
            if result || ps_case_stage != 13 || probe_commands || ps_turn_probe_lower_at != -1 || probe_opens { return 15; }
        }
    }
    if probe_duration && !ps_turn_probe_masked { return 16; }
    // A naturally invalid view is not a valid synthetic-fault trigger.
    ps_total = 200; ps_dock_seen = 199; ps_dock_valid = 0; ps_dock_stable = 3;
    ps_case_stage = 8; ps_case_steps = 2; ps_case_drop_turning = 1; ps_gripper_held = 1;
    ps_case_drop_reacquire_started = -1; ps_turn_probe_at = -1; ps_turn_probe_eligible = 0;
    ps_turn_probe_masked = 0; ps_turn_probe_lower_at = -1; probe_commands = 0;
    ps_case_update();
    if ps_turn_probe_at != 200 || ps_turn_probe_eligible || ps_turn_probe_masked || probe_commands { return 17; }
    pl_print(1, "rendered fault probe passed\n"); return 0;
}
