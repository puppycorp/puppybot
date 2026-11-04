fn check(value, message) {
    if !value { pl_print(2, message); pl_print(2, "\n"); syscall(60, 1, 0, 0, 0, 0, 0); }
    return 1;
}
fn reset_case() {
    ps_discovery_job = alloc(96); store64(ps_discovery_job + 8, -999);
    store64(ps_discovery_job + 40, 4); store64(ps_discovery_job + 48, 5);
    ps_robot = alloc(80); ps_total = 1622; ps_discovery_frame_id = 1621;
    ps_discovery_started = 1000; fake_now = 1000; fake_step = 10;
    fake_camera_still = 1; fake_clock_invalid = 0; fake_failure_count = 0;
    return 1;
}
fn main(argc, argv) {
    pl_init(); reset_case(); fake_finish_at = 1010;
    check(ps_discovery_barrier_wait(), "fast worker failed");
    check(ps_total == 1622 && ps_discovery_barrier_last_tick == 1622 && ps_discovery_barrier_last_frame == 1621 && ps_discovery_barrier_last_wall_ms == 10, "fast timing differs");
    reset_case(); fake_finish_at = 1990;
    check(ps_discovery_barrier_wait(), "slow worker failed");
    check(ps_total == 1622 && ps_discovery_barrier_last_tick == 1622 && ps_discovery_barrier_last_wall_ms == 990, "sim tick depended on worker duration");
    reset_case(); fake_finish_at = 17000;
    check(!ps_discovery_barrier_wait() && fake_failure_count == 1 && ps_total == 1622, "timeout did not fail safely");
    reset_case(); fake_clock_invalid = 1;
    check(!ps_discovery_barrier_wait() && fake_failure_count == 1, "bad clock was accepted");
    reset_case(); store64(ps_robot + 48, 1);
    check(!ps_discovery_barrier_wait() && fake_failure_count == 1, "nonzero drive was accepted");
    reset_case(); fake_camera_still = 0;
    check(!ps_discovery_barrier_wait() && fake_failure_count == 1, "moving camera was accepted");
    pl_print(1, "Virtual worker barrier probe passed.\n"); return 0;
}
