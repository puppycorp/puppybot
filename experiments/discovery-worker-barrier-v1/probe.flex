global ps_discovery_job = 0;
global ps_discovery_started = 0;
global ps_discovery_frame_id = 0;
global ps_total = 0;
global ps_robot = 0;
global fake_now = 0;
global fake_finish_at = 0;
global fake_step = 0;
global fake_camera_still = 1;
global fake_failure_count = 0;
global fake_clock_invalid = 0;
fn pl_init() { return 1; }
fn pl_print(fd, text) { let n = 0; while load8(text + n) { n = n + 1; } return syscall(1, fd, text, n, 0, 0, 0); }
fn pb_robot_drive(robot) { return robot; }
fn ps_camera_still() { return fake_camera_still; }
fn pl_now() { if fake_clock_invalid { return -1; } return fake_now; }
fn h_pump(job, ms) {
    fake_now = fake_now + fake_step;
    if fake_now >= fake_finish_at { store64(job + 8, 0); store64(job + 40, -1); store64(job + 48, -1); }
    return 1;
}
fn ps_discovery_finish(reason, failed) { fake_failure_count = fake_failure_count + 1; return 0; }

