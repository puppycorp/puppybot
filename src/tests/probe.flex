// Binary word protocol for the independent Rust differential runner.
import "../core/protocol.flex";
import "../platform/fake.flex";
import "../core/config.flex";

global probe_system = 0;
global probe_bus = 0;
global probe_config = 0;

fn probe_read(out, size) {
    let at = 0;
    while at < size {
        let n = syscall(0, 0, out + at, size - at, 0, 0, 0);
        if n == -4 { n = 0; }
        else if n <= 0 { return at == 0; }
        at = at + n;
    }
    return 2;
}
fn probe_write(out, size) {
    let at = 0;
    while at < size {
        let n = syscall(1, 1, out + at, size - at, 0, 0, 0);
        if n == -4 { n = 0; } else if n <= 0 { return 1; }
        at = at + n;
    }
    return 0;
}
fn probe_snapshot(robot, out) {
    pb_vset(out, 0, pb_a(robot, PB_A_MODE)); let drive = pb_robot_drive(robot);
    pb_vset(out, 1, pb_vget(drive, 0)); pb_vset(out, 2, pb_vget(drive, 1)); pb_vset(out, 3, pb_vget(drive, 2));
    pb_vset(out, 4, pb_vget(drive, 6)); pb_vset(out, 5, pb_vget(drive, 7)); pb_vset(out, 6, pb_vget(drive, 8)); pb_vset(out, 7, pb_vget(drive, 9));
    pb_vset(out, 8, load64(robot + 4240)); let i = 0;
    while i < 5 { pb_vset(out, 9 + i, load64(robot + 4200 + i * 8)); i = i + 1; }
    let index = 14; i = 0;
    while i < 4 {
        let j = pb_joint(robot, i); let k = 0;
        while k < 32 {
            let value = pb_j(j, k);
            if (k == 13 && !pb_j(j, 12)) || (k == 15 && !pb_j(j, 14)) || (k == 17 && !pb_j(j, 16)) || (k == 19 && !pb_j(j, 18)) || (k == 25 && !pb_j(j, 24)) || (k == 27 && !pb_j(j, 26)) || (k == 30 && !pb_j(j, 29)) { value = 0; }
            pb_vset(out, index, value); index = index + 1; k = k + 1;
        }
        i = i + 1;
    }
    let bytes = robot + 6000; let n = pb_arm_state_frame(robot, bytes, 512);
    pb_vset(out, index, n); index = index + 1; i = 0;
    while i < n { pb_vset(out, index, load8(bytes + i)); index = index + 1; i = i + 1; }
    return index;
}
fn probe_execute(robot, op, args, count, out) {
    let a = pb_vget(args, 0); let b = pb_vget(args, 1); let c = pb_vget(args, 2); let d = pb_vget(args, 3); let e = pb_vget(args, 4);
    if op == 0 { pb_robot_init(robot, a); pb_system_init(probe_system, robot); pb_fake_init(probe_bus); return 0; }
    if op == 1 { pb_vset(out, 0, pb_arm_command(robot, b, args + 16, a)); return 1; }
    if op == 2 { pb_arm_feedback(robot, b, c & 65535, a); return 0; }
    if op == 3 { pb_arm_update(robot, a, out); return 12; }
    if op == 4 { pb_arm_feedback_error(robot, a); return 0; }
    if op == 5 { pb_arm_temperature(robot, a, b, c); return 0; }
    if op == 6 { pb_arm_speed_result(robot, b, c, d, e, a); return 0; }
    if op == 7 { pb_arm_mode_result(robot, a, b, c, d); return 0; }
    if op == 8 {
        let bytes = robot + 5500; let response = robot + 6000; let i = 1;
        while i < count { store8(bytes + i - 1, pb_vget(args, i)); i = i + 1; }
        let n = pb_robot_frame(robot, bytes, count - 1, a, response); pb_vset(out, 0, n); i = 0;
        while i < n { pb_vset(out, i + 1, load8(response + i)); i = i + 1; }
        let events = load64(robot + 4280); pb_vset(out, n + 1, events); let at = n + 2; i = 0;
        while i < events { pb_copy(out + at * 8, robot + 4608 + i * 64, 48); at = at + 6; i = i + 1; } return at;
    }
    if op == 9 { return probe_snapshot(robot, out); }
    if op == 10 { pb_drive_tick(pb_robot_drive(robot), a); return 0; }
    if op == 11 {
        let config = probe_config; pb_config_default(config); pb_copy(config + 192, args + 8, 256);
        let error = pb_robot_configure(robot, config, a);
        // Robot init clears the allocation; keep config outside it during apply.
        pb_vset(out, 0, error != 0); return 1;
    }
    if op == 12 { pb_vset(out, 0, pb_begin_wheel(robot, b, c, a, d)); return 1; }
    if op == 13 { pb_vset(out, 0, a < 4 && a >= 0 && load64(pb_wheel_id(robot, a)) == b && load64(pb_wheel_ready(robot, a))); return 1; }
    if op == 14 { pb_vset(out, 0, !pb_a(robot, PB_A_INITIALIZED)); pb_as(robot, PB_A_INITIALIZED, 1); return 1; }
    if op == 15 {
        let bytes = robot + 5500; let params = robot + 5800; let i = 2;
        while i < count { store8(params + i - 2, pb_vget(args, i)); i = i + 1; }
        let n = pb_servo_packet(bytes, 256, a, b, params, count - 2); i = 0;
        while i < n { pb_vset(out, i, load8(bytes + i)); i = i + 1; } return n;
    }
    if op == 16 {
        let i = 0;
        while i < 4 {
            let radial = PB_ONE; let elbow = PB_ONE; if i >= 2 { radial = pb_neg(PB_ONE); } if i % 2 { elbow = pb_neg(PB_ONE); }
            pb_ik_branch(out + i * 40, a, b, c, d, radial, elbow); i = i + 1;
        }
        return 20;
    }
    if op == 17 { pb_fk(out, a, b, c, d); return 3; }
    if op == 18 { pb_vset(out, 0, pb_f32_to_f64(a)); return 1; }
    if op == 19 { pb_vset(out, 0, pb_f64_to_f32(a)); return 1; }
    if op == 20 { pb_fake_servo(probe_bus, a, b); return 0; }
    if op == 21 { pb_vset(probe_bus + a * 48, b, c); return 0; }
    if op == 22 {
        let trace = robot + 5500; let n = pb_fake_cycle(probe_system, probe_bus, a, trace, 1000);
        if n < 0 { return -1; } let i = 0; while i < n { pb_vset(out, i, load8(trace + i)); i = i + 1; } return n;
    }
    if op == 23 { pb_vset(out, 0, pb_system_queue(probe_system, a, args + 8)); return 1; }
    if op == 24 { pb_copy(probe_config, args, 448); pb_vset(out, 0, pb_config_validate(probe_config)); return 1; }
    if op == 25 { return pb_arm_mode_words(robot, out); }
    if op == 26 { pb_arm_chain_points(out, a, b, c, d); return 15; }
    if op == 27 { pb_tooltip_to_wrist(out, a, b, c, d); return 3; }
    return -1;
}
fn main() {
    let robot = alloc(8192); let args = alloc(4096); let out = alloc(8192); let header = alloc(16);
    pb_robot_init(robot, 0); probe_system = alloc(2048); probe_bus = alloc(16384); probe_config = alloc(448); pb_system_init(probe_system, robot); pb_fake_init(probe_bus);
    while 1 {
        let ready = probe_read(header, 16); if ready == 1 { return 0; } if ready != 2 { return 1; }
        let count = load64(header + 8); if count < 0 || count > 512 { return 2; }
        pb_zero(args, 4096); if count && probe_read(args, count * 8) != 2 { return 3; }
        let n = probe_execute(robot, load64(header), args, count, out + 8); if n < 0 || n > 1023 { return 4; }
        store64(out, n); if probe_write(out, (n + 1) * 8) { return 5; }
    }
    return 0;
}
