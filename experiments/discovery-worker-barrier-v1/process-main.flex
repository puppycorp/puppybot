fn check(value, message) {
    if !value { h_print(2, message); h_print(2, "\n"); syscall(60, 1, 0, 0, 0, 0, 0); }
    return 1;
}
fn run_worker(delay) {
    let args = h_args("/bin/sleep", delay, 0, 0, 0, 0);
    ps_discovery_job = h_spawn(args, "", 0); ps_discovery_started = pl_now();
    check(ps_discovery_barrier_wait(), "real process barrier failed");
    check(load64(ps_discovery_job + 8) == 0 && ps_total == 1622 && ps_discovery_barrier_last_tick == 1622, "real process status or tick differs");
    return ps_discovery_barrier_last_wall_ms;
}
fn main(argc, argv) {
    h_environment(argc, argv); probe_clock = alloc(16); ps_robot = alloc(80);
    let fast = run_worker("0.05"); let slow = run_worker("0.25");
    check(fast >= 30 && slow >= 200, "worker wall durations not captured");
    h_print(1, "Real child process barrier probe passed.\n"); return 0;
}
