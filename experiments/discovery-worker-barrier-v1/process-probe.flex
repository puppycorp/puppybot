global ps_discovery_job = 0;
global ps_discovery_started = 0;
global ps_discovery_frame_id = 1621;
global ps_total = 1622;
global ps_robot = 0;
global probe_clock = 0;
fn pl_now() {
    if syscall(228, 1, probe_clock, 0, 0, 0, 0) < 0 { return -1; }
    return load64(probe_clock) * 1000 + load64(probe_clock + 8) / 1000000;
}
fn pb_robot_drive(robot) { return robot; }
fn ps_camera_still() { return 1; }
fn ps_discovery_finish(reason, failed) { h_print(2, reason); return 0; }
