import "arm.flex";
import "drive.flex";

// Robot allocation: shared arm at 0, drive at 4096, protocol IDs at 4200,
// telemetry flag at 4240, sequence at 4248, steering cache at 4256/4264,
// feedback cursor at 4272, decoded event count/response length at 4280/4288.
fn pb_robot_arm(robot) { return robot; }
fn pb_robot_drive(robot) { return robot + 4096; }
fn pb_robot_init(robot, now) {
    pb_zero(robot, 8192); pb_arm_init(robot, now); pb_drive_init(pb_robot_drive(robot), now);
    let i = 0; while i < 5 { store64(robot + 4200 + i * 8, pb_max(i, 1)); i = i + 1; }
    store64(robot + 4256, -1); return 0;
}
fn pb_protocol_event(robot, events, command, a, b, c, d, e) {
    let count = load64(robot + 4280); if count >= 2 { return -90; }
    let out = events + count * 64;
    pb_vset(out, 0, command); pb_vset(out, 1, a); pb_vset(out, 2, b);
    pb_vset(out, 3, c); pb_vset(out, 4, d); pb_vset(out, 5, e);
    store64(robot + 4280, count + 1); return 0;
}
fn pb_config_response(robot, out) {
    pb_put16(out, 1); store8(out + 2, 8); store8(out + 3, 1);
    let i = 0; while i < 5 { store8(out + 4 + i, load64(robot + 4200 + i * 8)); i = i + 1; }
    store64(robot + 4288, 9); return 9;
}
fn pb_protocol_speed(robot, events, value) { return pb_protocol_event(robot, events, 1, value, 0, 0, 0, 0); }
fn pb_protocol_frame(value) { if value == 1 { return 1; } if value == 2 { return 2; } if value == 0 { return 0; } return -1; }
fn pb_decode(robot, frame, size, events, out) {
    store64(robot + 4280, 0); store64(robot + 4288, 0);
    if size < 4 { return 0; }
    let cmd = load8(frame + 1); let n = pb_u16(frame + 2); let body = frame + 4;
    if n > size - 4 { return 0; }
    // i16::MIN has no positive i16 magnitude in the Rust controller. Treat its
    // speed spelling and nonfinite joint angles as malformed whole commands.
    let bad_speed = 0;
    if (cmd == 12 || cmd == 16 || cmd == 17 || cmd == 18 || cmd == 19) && n >= 2 { bad_speed = pb_u16(body) == 32768; }
    if cmd == 13 && n >= 4 { bad_speed = pb_u16(body + 2) == 32768; }
    if cmd == 20 && n >= 3 { bad_speed = pb_u16(body + 1) == 32768; }
    if cmd == 29 && n >= 5 { bad_speed = pb_u16(body + 3) == 32768; }
    if cmd == 30 && n >= 18 { bad_speed = pb_u16(body + 16) == 32768; }
    if bad_speed { return 0; }
    if cmd == 17 && n >= 18 {
        let i = 0; while i < 4 { if !f64_is_finite(pb_read_float(body + 2 + i * 4)) { return 0; } i = i + 1; }
    }
    if cmd == 1 { pb_put16(out, 1); store8(out + 2, 1); store64(robot + 4288, 3); return 3; }
    if cmd == 2 && n >= 3 && load8(body + 1) == 0 { pb_protocol_event(robot, events, 102, load8(body), pb_i8(load8(body + 2)), 0, 0, 0); }
    else if cmd == 3 && n >= 1 { pb_protocol_event(robot, events, 102, load8(body), 0, 0, 0, 0); }
    else if cmd == 4 || cmd == 28 { pb_protocol_event(robot, events, 103, 0, 0, 0, 0, 0); }
    else if cmd == 9 {
        let enabled = 0;
        if n >= 1 { let count = pb_min(load8(body), n - 1); let i = 0;
            while i < count { let j = 0; while j < 4 { if load8(body + i + 1) == load64(robot + 4208 + j * 8) { enabled = 1; } j = j + 1; } i = i + 1; }
        }
        store64(robot + 4240, enabled);
    }
    else if cmd == 25 { return pb_config_response(robot, out); }
    else if cmd == 26 && n >= 6 && load8(body) == 1 {
        let valid = 1; let i = 0; while i < 4 { if !load8(body + 2 + i) { valid = 0; } i = i + 1; }
        if valid {
            i = 0; while i < 5 { store64(robot + 4200 + i * 8, load8(body + 1 + i)); i = i + 1; }
            pb_protocol_event(robot, events, 20, load8(body + 2), load8(body + 3), load8(body + 4), load8(body + 5), 0);
            pb_protocol_event(robot, events, 104, load8(body + 1), 0, 0, 0, 0);
            return pb_config_response(robot, out);
        }
    }
    else if cmd == 33 && n >= 2 && load8(body) == 1 { store64(robot + 4240, load8(body + 1) != 0); }
    else if cmd == 12 && n >= 2 { pb_protocol_speed(robot, events, pb_i16(pb_u16(body))); }
    else if cmd == 13 && n >= 4 {
        pb_protocol_speed(robot, events, pb_i16(pb_u16(body + 2)));
        pb_protocol_event(robot, events, 2, load8(body), pb_i8(load8(body + 1)), 0, 0, 0);
    }
    else if cmd == 14 && n >= 1 { pb_protocol_event(robot, events, 3, load8(body), 0, 0, 0, 0); }
    else if cmd == 15 || cmd == 31 { pb_protocol_event(robot, events, 4, 0, 0, 0, 0, 0); }
    else if cmd == 16 && n >= 18 {
        pb_protocol_speed(robot, events, pb_i16(pb_u16(body)));
        pb_protocol_event(robot, events, 5, pb_i32(pb_u32(body + 2)), pb_i32(pb_u32(body + 6)), pb_i32(pb_u32(body + 10)), pb_i32(pb_u32(body + 14)), 0);
    }
    else if cmd == 17 && n >= 18 {
        pb_protocol_speed(robot, events, pb_i16(pb_u16(body)));
        pb_protocol_event(robot, events, 6, pb_radians(pb_read_float(body + 2)), pb_radians(pb_read_float(body + 6)), pb_radians(pb_read_float(body + 10)), pb_radians(pb_read_float(body + 14)), 0);
    }
    else if cmd == 18 && n >= 18 {
        pb_protocol_speed(robot, events, pb_i16(pb_u16(body)));
        pb_protocol_event(robot, events, 7, pb_read_float(body + 2), pb_read_float(body + 6), pb_read_float(body + 10), pb_radians(pb_read_float(body + 14)), 0);
    }
    else if cmd == 23 && n >= 15 {
        let which = pb_protocol_frame(load8(body + 2)); let x = pb_read_float(body + 3); let y = pb_read_float(body + 7); let z = pb_read_float(body + 11);
        if which >= 0 && f64_is_finite(x) && f64_is_finite(y) && f64_is_finite(z) {
            pb_protocol_speed(robot, events, pb_min(pb_u16(body), 32767)); pb_protocol_event(robot, events, 8, which, x, y, z, 0);
        }
    }
    else if cmd == 34 && n >= 17 {
        let which = pb_protocol_frame(load8(body)); let x = pb_read_float(body + 1); let y = pb_read_float(body + 5); let z = pb_read_float(body + 9); let speed = pb_read_float(body + 13);
        if which >= 0 && f64_is_finite(x) && f64_is_finite(y) && f64_is_finite(z) && f64_is_finite(speed) && f64_gt(speed, 0) { pb_protocol_event(robot, events, 10, which, x, y, z, speed); }
    }
    else if cmd == 35 { pb_protocol_event(robot, events, 11, 0, 0, 0, 0, 0); }
    else if cmd == 19 && n >= 2 { pb_protocol_speed(robot, events, pb_i16(pb_u16(body))); pb_protocol_event(robot, events, 12, 0, 0, 0, 0, 0); }
    else if cmd == 20 && n >= 7 {
        pb_protocol_speed(robot, events, pb_i16(pb_u16(body + 1))); pb_protocol_event(robot, events, 13, load8(body), pb_i32(pb_u32(body + 3)), 0, 0, 0);
    }
    else if cmd == 21 && n >= 9 { pb_protocol_event(robot, events, 17, load8(body), pb_i32(pb_u32(body + 1)), pb_i32(pb_u32(body + 5)), 0, 0); }
    else if cmd == 22 && n >= 2 { pb_protocol_event(robot, events, 18, load8(body), load8(body + 1) != 0, 0, 0, 0); }
    else if cmd == 24 { let index = -1; if n >= 1 && load8(body) != 255 { index = load8(body); } pb_protocol_event(robot, events, 19, index, 0, 0, 0, 0); }
    else if cmd == 29 && n >= 5 {
        pb_protocol_speed(robot, events, pb_i16(pb_u16(body + 3))); pb_protocol_event(robot, events, 14, load8(body), pb_radians(f64_from_i64(pb_i16(pb_u16(body + 1)))), 0, 0, 0);
    }
    else if cmd == 30 && n >= 18 {
        pb_protocol_speed(robot, events, pb_i16(pb_u16(body + 16))); pb_protocol_event(robot, events, 7, pb_read_float(body), pb_read_float(body + 4), pb_read_float(body + 8), pb_radians(pb_read_float(body + 12)), 0);
    }
    else if cmd == 27 && n >= 2 { pb_protocol_event(robot, events, 101, pb_i8(load8(body)), pb_i8(load8(body + 1)), 0, 0, 0); }
    else if cmd == 32 && n >= 5 && load8(body) {
        let duration = pb_u16(body + 3); let speed = 2400; if duration { speed = pb_clamp(1000000 / duration, 1, 2400); }
        pb_protocol_event(robot, events, 16, load8(body), pb_radians(f64_from_i64(pb_u16(body + 1))), speed, 0, 0);
    }
    return load64(robot + 4288);
}
fn pb_robot_event(robot, command, values, now) {
    let drive = pb_robot_drive(robot);
    if command == 101 { return pb_drive_steer(drive, pb_vget(values, 0), pb_vget(values, 1), now); }
    if command == 102 { return pb_drive_motor(drive, pb_vget(values, 0), pb_vget(values, 1), now); }
    if command == 103 { return pb_drive_stop(drive, now); }
    if command == 104 { pb_vset(drive, 2, pb_vget(values, 0)); return 0; }
    return pb_arm_command(robot, command, values, now);
}
fn pb_robot_frame(robot, frame, size, now, out) {
    let events = robot + 4608; let n = pb_decode(robot, frame, size, events, out); let i = 0;
    while i < load64(robot + 4280) { let event = events + i * 64; pb_robot_event(robot, load64(event), event + 8, now); i = i + 1; }
    return n;
}
fn pb_fault_name(fault) {
    if fault == 1 { return "over_temp"; } if fault == 2 { return "no_feedback"; }
    if fault == 3 { return "stale_feedback"; } if fault == 4 { return "stall"; }
    if fault == 5 { return "deadman_feedback"; } if fault == 6 { return "deadman_command"; } return "";
}
fn pb_text_size(text) { let n = 0; while load8(text + n) { n = n + 1; } return n; }
fn pb_telemetry_coords(out, robot, target) {
    let coords = robot + 4800; let valid = pb_arm_coords(robot, coords, target) == 0; store8(out, valid);
    let i = 0; while i < 3 { let word = 0; if valid { word = pb_f64_to_f32(pb_vget(coords, i)); } pb_put32(out + 1 + i * 4, word); i = i + 1; } return 13;
}
fn pb_arm_state_frame(robot, out, capacity) {
    if capacity < 256 { return -90; }
    pb_put16(out, 1); store8(out + 2, 7); store8(out + 3, 4); let at = 4; let i = 0;
    while i < 4 {
        let j = pb_joint(robot, i); let flags = pb_j(j, PB_J_ONLINE);
        if pb_j(j, PB_J_FEEDBACK) && pb_j(j, PB_J_TICK_VALID) { flags = flags | 2; }
        if pb_j(j, PB_J_TICK_VALID) && !pb_tick_within(j, pb_j(j, PB_J_TICK)) { flags = flags | 4; }
        if pb_j(j, PB_J_TARGET_VALID) { flags = flags | 8; } if pb_j(j, PB_J_FAULT) { flags = flags | 16; }
        store8(out + at, pb_j(j, PB_J_ID)); store8(out + at + 1, flags);
        let tick = 0; if pb_j(j, PB_J_TICK_VALID) { tick = pb_j(j, PB_J_TICK); }
        let target = 0; if pb_j(j, PB_J_TARGET_VALID) { target = pb_j(j, PB_J_TARGET); }
        pb_put32(out + at + 2, tick); pb_put32(out + at + 6, target); pb_put16(out + at + 10, pb_j(j, PB_J_SPEED));
        pb_put32(out + at + 12, pb_j(j, PB_J_MIN)); pb_put32(out + at + 16, pb_j(j, PB_J_MAX));
        let degrees = 0; if pb_j(j, PB_J_ANGLE_VALID) { degrees = pb_f64_to_f32(pb_degrees(pb_j(j, PB_J_ANGLE))); }
        pb_put32(out + at + 20, degrees); let fault = pb_fault_name(pb_j(j, PB_J_FAULT)); let size = pb_text_size(fault);
        store8(out + at + 24, size); pb_copy(out + at + 25, fault, size); at = at + 25 + size; i = i + 1;
    }
    at = at + pb_telemetry_coords(out + at, robot, 0); store8(out + at, 1); at = at + 1; i = 0;
    while i < 4 {
        let j = pb_joint(robot, i); let valid = pb_j(j, PB_J_TARGET_ANGLE_VALID); let degrees = 0;
        if valid { degrees = pb_f64_to_f32(pb_degrees(pb_j(j, PB_J_TARGET_ANGLE))); }
        store8(out + at, valid); pb_put32(out + at + 1, degrees); at = at + 5; i = i + 1;
    }
    at = at + pb_telemetry_coords(out + at, robot, 1); return at;
}
