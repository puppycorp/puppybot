// Cooperative serial controller. The caller owns 2048 bytes and supplies time,
// serial writes/reads and their errors. No sleeping or unbounded I/O loop.
import "protocol.flex";
import "stservo.flex";

// Header words: robot, stage, joint, cycle time, deadline, TX size, TX pending,
// initial mode setup, active cycle, queued count, queue read cursor.
// Stages: 0 idle, 1 feedback, 2 steering, 3 wheel mode, 4 wheel speed.
fn pb_system_init(system, robot) {
    pb_zero(system, 2048); store64(system, robot); return 0;
}
fn pb_system_active(system) { return pb_vget(system, 8); }
fn pb_system_packet(system) { return system + 128; }
fn pb_system_queue(system, command, values) {
    let count = pb_vget(system, 9); let read = pb_vget(system, 10);
    if count >= 16 { return -11; }
    let event = system + 768 + ((read + count) % 16) * 64;
    pb_zero(event, 64); store64(event, command); pb_copy(event + 8, values, 40);
    pb_vset(system, 9, count + 1); return 0;
}
fn pb_system_frame(system, frame, size, response) {
    let robot = load64(system); let events = robot + 4608;
    let n = pb_decode(robot, frame, size, events, response);
    let count = load64(robot + 4280);
    if pb_vget(system, 9) + count > 16 { return -11; }
    let i = 0;
    while i < count { let event = events + i * 64; pb_system_queue(system, load64(event), event + 8); i = i + 1; }
    return n;
}
fn pb_system_request(system, stage, size) {
    if size < 0 { return size; }
    pb_vset(system, 1, stage); pb_vset(system, 5, size); pb_vset(system, 6, 1);
    // The platform starts the response deadline after its bounded write completes.
    pb_vset(system, 4, -1); pb_servo_parser_init(system + 384); return size;
}
fn pb_system_take_tx(system) {
    if !pb_vget(system, 6) { return 0; }
    pb_vset(system, 6, 0); return pb_vget(system, 5);
}
fn pb_system_written(system, now) {
    if !pb_system_active(system) || pb_vget(system, 6) { return -22; }
    if pb_vget(system, 4) == -1 { pb_vset(system, 4, now + 50); }
    return 0;
}
fn pb_system_next_output(system) {
    let robot = load64(system); let now = pb_vget(system, 3); let i = pb_vget(system, 2);
    while i < 4 {
        let command = system + 640 + i * 24; let id = pb_vget(command, 0); let speed = pb_vget(command, 1);
        if pb_vget(system, 7) || pb_vget(command, 2) {
            pb_vset(system, 2, i);
            if load64(pb_wheel_id(robot, i)) == id && load64(pb_wheel_ready(robot, i)) {
                return pb_system_request(system, 4, pb_servo_wheel(system + 128, 256, id, speed, 0, system + 512));
            }
            if pb_begin_wheel(robot, i, id, now, pb_vget(system, 7) || speed == 0) {
                return pb_system_request(system, 3, pb_servo_write8(system + 128, 256, id, 33, 1, system + 512));
            }
        }
        i = i + 1;
    }
    pb_vset(system, 1, 0); pb_vset(system, 8, 0);
    store64(robot + 4248, (load64(robot + 4248) + 1) & 0xffffffff); return 0;
}
fn pb_system_outputs(system) {
    let robot = load64(system);
    pb_vset(system, 7, !pb_a(robot, PB_A_INITIALIZED)); pb_as(robot, PB_A_INITIALIZED, 1);
    pb_arm_update(robot, pb_vget(system, 3), system + 640); pb_vset(system, 2, 0);
    return pb_system_next_output(system);
}
fn pb_system_after_feedback(system) {
    let robot = load64(system); let now = pb_vget(system, 3);
    while pb_vget(system, 9) {
        let read = pb_vget(system, 10); let event = system + 768 + read * 64;
        pb_robot_event(robot, load64(event), event + 8, now);
        pb_vset(system, 10, (read + 1) % 16); pb_vset(system, 9, pb_vget(system, 9) - 1);
    }
    let drive = pb_robot_drive(robot); pb_drive_tick(drive, now);
    let id = pb_vget(drive, 2); let angle = pb_vget(drive, 8);
    if pb_vget(drive, 9) && id && (load64(robot + 4256) != id || load64(robot + 4264) != angle) {
        return pb_system_request(system, 2, pb_servo_position(system + 128, 256, id, pb_servo_angle(angle), 2400, 0, system + 512));
    }
    return pb_system_outputs(system);
}
fn pb_system_complete(system, success, tick) {
    let robot = load64(system); let stage = pb_vget(system, 1); let i = pb_vget(system, 2); let now = pb_vget(system, 3);
    if stage == 1 {
        if success { pb_arm_feedback(robot, i, tick, now); } else { pb_arm_feedback_error(robot, i); }
        return pb_system_after_feedback(system);
    }
    if stage == 2 {
        if success { let drive = pb_robot_drive(robot); store64(robot + 4256, pb_vget(drive, 2)); store64(robot + 4264, pb_vget(drive, 8)); }
        return pb_system_outputs(system);
    }
    let command = system + 640 + i * 24; let id = pb_vget(command, 0); let speed = pb_vget(command, 1);
    if stage == 3 {
        pb_arm_mode_result(robot, i, id, 1, success);
        if success { return pb_system_request(system, 4, pb_servo_wheel(system + 128, 256, id, speed, 0, system + 512)); }
    }
    if stage == 4 { pb_arm_speed_result(robot, i, id, speed, success, now); }
    pb_vset(system, 2, i + 1); return pb_system_next_output(system);
}
fn pb_system_begin(system, now) {
    if pb_system_active(system) { return -16; }
    let robot = load64(system); let i = load64(robot + 4272);
    store64(robot + 4272, (i + 1) % 4);
    pb_vset(system, 8, 1); pb_vset(system, 2, i); pb_vset(system, 3, now);
    let id = pb_j(pb_joint(robot, i), PB_J_ID);
    return pb_system_request(system, 1, pb_servo_read(system + 128, 256, id, 56, 2, system + 512));
}
fn pb_system_error(system) {
    if !pb_system_active(system) { return 0; }
    pb_vset(system, 6, 0); return pb_system_complete(system, 0, 0);
}
fn pb_system_poll(system, now) {
    if !pb_system_active(system) || pb_vget(system, 6) { return 0; }
    let deadline = pb_vget(system, 4);
    if deadline != -1 && now >= deadline { return pb_system_error(system); } return 0;
}
fn pb_system_receive(system, bytes, size, now) {
    if !pb_system_active(system) || pb_vget(system, 6) { return 0; }
    if pb_vget(system, 4) != -1 && now >= pb_vget(system, 4) { pb_system_error(system); return 0; }
    let i = 0;
    while i < size {
        let parsed = pb_servo_byte(system + 384, load8(bytes + i)); i = i + 1;
        if parsed < 0 { pb_system_error(system); return i; }
        if parsed == 1 {
            let expected = load8(system + 130);
            if pb_vget(system + 384, 1) != expected {
                // Match StServo::tx_rx_expected: drain and retransmit on another ID.
                pb_servo_parser_init(system + 384); pb_vset(system, 6, 1); return i;
            }
            let success = pb_vget(system + 384, 2) == 0; let tick = 0;
            if pb_vget(system, 1) == 1 {
                if pb_vget(system + 384, 4) < 2 { success = 0; }
                else { tick = pb_u16(system + 448); }
            }
            pb_system_complete(system, success, tick); return i;
        }
    }
    return i;
}
