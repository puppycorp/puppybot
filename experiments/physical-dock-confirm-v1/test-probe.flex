// Appended only to a disposable simulator source copy. RGB, camera and floor
// acquisition are mocked; the real collector, dock stability and dispatch run.
fn dc_require(ok, message) { if !ok { pl_print(2, message); pl_print(2, "\n"); syscall(231, 1, 0, 0, 0, 0, 0); } return 0; }
fn main(argc, argv) {
    if !pl_init() || argc != 2 { return 2; } let mode = load64(argv + 8);
    ps_robot = alloc(8192); ps_house_home = alloc(24); ps_total = 100; ps_time = 2000;
    ps_agent_physical = 1; ps_physical_owner = 1; ps_collect_enabled = 1; ps_discovery_enabled = 1;
    ps_seek_enabled = 0; ps_local_mode = 2; ps_camera_drive_mode = 1; ps_discovery_phase = 5;
    ps_dock_confirm_enabled = !pl_equal(mode, "disabled"); ps_brick_frame = ps_total;
    ps_dock_reset(); ps_dock_pose(0, 0, PB_ONE, 0, 4);
    let drive = pb_robot_drive(ps_robot); pb_vset(drive, 6, 30); pb_vset(drive, 7, 30);
    if pl_equal(mode, "no-local") { ps_local_mode = 0; } if pl_equal(mode, "oracle") { ps_nav_training_oracle = 1; } if pl_equal(mode, "runs-limit") { ps_dock_confirm_runs = 3; }
    if pl_equal(mode, "travel") { ps_total = 101; ps_brick_frame = 101; ps_dock_seen = 101; }
    let began = 0; if pl_equal(mode, "travel") { began = ps_collect_travel_observe(); } else { began = ps_dock_confirm_begin(); }
    if pl_equal(mode, "disabled") || pl_equal(mode, "no-local") || pl_equal(mode, "oracle") || pl_equal(mode, "runs-limit") { dc_require(!began && pb_vget(drive, 6) == 30, "disabled, budget or privileged behavior changed"); return 0; }
    dc_require(began == 1 && ps_dock_confirm_active && !pb_vget(drive, 6) && !pb_vget(drive, 7) && ps_dock_stable == 1, "confirmation did not stop and initialize");
    if pl_equal(mode, "duplicate") { dc_require(ps_dock_confirm_tick() == 1 && !ps_dock_confirm_active && !ps_house_ready && !dc_samples, "duplicate tick accepted"); return 0; }
    if pl_equal(mode, "timeout") { ps_total = 126; dc_require(ps_dock_confirm_tick() == 1 && !ps_dock_confirm_active && !ps_house_ready && !dc_samples, "timeout accepted"); return 0; }
    if pl_equal(mode, "movement") { ps_local_distance = ps_number(2, 1000); }
    if pl_equal(mode, "blocked") { ps_blocked = 1; }
    if pl_equal(mode, "camera") { dc_still = 0; }
    if pl_equal(mode, "stale") { dc_stale = 1; }
    if pl_equal(mode, "dropout") { dc_dropout = 1; }
    if pl_equal(mode, "sensor-fail") { dc_fail = 1; }
    if pl_equal(mode, "new-floor") { dc_floor = 1; }
    if pl_equal(mode, "floor-on-confirm") { dc_floor = 2; }
    if pl_equal(mode, "stop-fail") { dc_stop_fail = 1; pb_vset(drive, 6, 30); }
    if pl_equal(mode, "jitter") || pl_equal(mode, "budget") { dc_jitter = 1; }
    let i = 0;
    while i < 4 && ps_dock_confirm_active {
        ps_total = ps_total + 1; ps_time = ps_time + 20;
        if pl_equal(mode, "stale") || pl_equal(mode, "sensor-fail") || pl_equal(mode, "stop-fail") {
            dc_require(!ps_discovery_update() && dc_finished == 1 && !ps_house_ready, "failure was accepted by discovery dispatch"); return 0;
        }
        dc_require(ps_discovery_update() == 1, "real discovery dispatch failed");
        if i == 0 && pl_equal(mode, "normal") { dc_require(ps_dock_stable == 2 && !ps_house_ready, "two frames confirmed early"); }
        i = i + 1;
    }
    if pl_equal(mode, "normal") || pl_equal(mode, "travel") { let expected = 2; if pl_equal(mode, "travel") { expected = 3; } dc_require(ps_house_ready && ps_dock_stable >= 3 && dc_samples == expected && ps_dock_confirm_reason == 4, "three distinct observations did not confirm"); }
    else if pl_equal(mode, "floor-on-confirm") { dc_require(ps_house_ready && !ps_dock_confirm_active && dc_replans == 1 && !ps_floor_changed && ps_dock_confirm_reason == 6, "simultaneous home and obstacle handling failed"); }
    else { dc_require(!ps_house_ready && !ps_dock_confirm_active, "invalid confirmation succeeded"); }
    if pl_equal(mode, "budget") { dc_require(dc_samples == 4 && ps_dock_confirm_reason == 2, "sample budget not enforced"); }
    if pl_equal(mode, "new-floor") { dc_require(dc_replans == 1 && !ps_floor_changed && ps_dock_confirm_reason == 6, "new floor observation did not replan"); }
    return 0;
}
