// Independent malformed-input, memory-bound and cooperative scheduling checks.
import "../core/system.flex";
import "../core/config.flex";

fn contracts_parser() {
    let guard = alloc(256); let packet = alloc(128); let data = alloc(64);
    let parser = guard + 64; let i = 0;
    while i < 256 { store8(guard + i, 165); i = i + 1; }
    i = 0; while i < 64 { store8(data + i, i); i = i + 1; }
    let length = 0;
    while length <= 64 {
        pb_servo_parser_init(parser);
        let n = pb_servo_packet(packet, 128, 17, 0, data, length);
        i = 0; while i < n {
            let result = pb_servo_byte(parser, load8(packet + i));
            if i == n - 1 { if result != 1 { return 10; } }
            else if result { return 11; }
            i = i + 1;
        }
        if pb_vget(parser, 1) != 17 || pb_vget(parser, 4) != length { return 12; }
        i = 0; while i < length { if load8(parser + 64 + i) != i { return 13; } i = i + 1; }
        length = length + 1;
    }
    i = 0; while i < 64 { if load8(guard + i) != 165 || load8(guard + 192 + i) != 165 { return 14; } i = i + 1; }
    pb_servo_parser_init(parser);
    let n = pb_servo_packet(packet, 128, 1, 0, data, 2);
    store8(packet + n - 1, load8(packet + n - 1) ^ 1);
    i = 0; let result = 0; while i < n { result = pb_servo_byte(parser, load8(packet + i)); i = i + 1; }
    if result != -4 { return 15; }
    pb_servo_parser_init(parser);
    pb_servo_byte(parser, 255); pb_servo_byte(parser, 255); pb_servo_byte(parser, 1);
    if pb_servo_byte(parser, 67) != -3 { return 16; }
    store8(packet, 123); if pb_servo_packet(packet, 5, 1, 0, data, 0) != -3 || load8(packet) != 123 { return 17; }
    return 0;
}
fn contracts_commands() {
    let robot = alloc(8192); let values = alloc(64); let response = alloc(256); let frame = alloc(32);
    pb_robot_init(robot, 0); pb_vset(values, 0, -32768);
    if pb_arm_command(robot, 1, values, 0) != 3 || pb_a(robot, PB_A_SPEED) != 200 { return 20; }
    let bad = 0x7ff0000000000000; pb_vset(values, 0, bad);
    if pb_arm_command(robot, 6, values, 0) != 3 || pb_j(pb_joint(robot, 0), PB_J_TARGET_VALID) { return 21; }
    pb_vset(values, 0, 1); pb_vset(values, 1, bad);
    if pb_arm_command(robot, 14, values, 0) != 3 { return 22; }
    let words = alloc(32); pb_zero(words, 32); pb_vset(words, 0, 300);
    pb_arm_command(robot, 1, words, 0);
    let command = 0; let offsets = alloc(64);
    // Every legacy speed-bearing command rejects i16::MIN before any event.
    pb_vset(offsets, 0, 12); pb_vset(offsets, 1, 13); pb_vset(offsets, 2, 16); pb_vset(offsets, 3, 17);
    pb_vset(offsets, 4, 18); pb_vset(offsets, 5, 19); pb_vset(offsets, 6, 20); pb_vset(offsets, 7, 29);
    while command < 8 {
        pb_zero(frame, 32); store8(frame, 1); let cmd = pb_vget(offsets, command); store8(frame + 1, cmd); pb_put16(frame + 2, 18);
        let at = 4; if cmd == 13 { at = 6; } if cmd == 20 { at = 5; } if cmd == 29 { at = 7; }
        pb_put16(frame + at, 32768);
        pb_robot_frame(robot, frame, 22, 0, response);
        if load64(robot + 4280) || pb_a(robot, PB_A_SPEED) != 300 { return 23; }
        command = command + 1;
    }
    let i = 0;
    while i < 4 {
        pb_zero(frame, 32); store8(frame, 1); store8(frame + 1, 17); pb_put16(frame + 2, 18); pb_put16(frame + 4, 500);
        pb_put32(frame + 6 + i * 4, 0x7fc01234);
        pb_robot_frame(robot, frame, 22, 0, response);
        if load64(robot + 4280) || pb_a(robot, PB_A_SPEED) != 300 { return 24; } i = i + 1;
    }
    return 0;
}
fn contracts_scheduler() {
    let robot = alloc(8192); let system = alloc(2048); let values = alloc(64);
    let reply = alloc(128); let params = alloc(2);
    pb_robot_init(robot, 0); pb_system_init(system, robot);
    if pb_system_begin(system, 0) != 8 || pb_system_begin(system, 0) != -16 { return 30; }
    if pb_system_take_tx(system) != 8 || pb_system_take_tx(system) { return 31; }
    pb_system_written(system, 10);
    pb_put16(params, 1234); let n = pb_servo_packet(reply, 128, 2, 0, params, 2);
    if pb_system_receive(system, reply, n, 20) != n || pb_vget(system, 6) != 1 { return 32; }
    if pb_system_take_tx(system) != 8 { return 33; }
    pb_system_written(system, 30);
    if pb_vget(system, 4) != 60 { return 34; }
    pb_system_poll(system, 59); if !pb_system_active(system) || pb_vget(system, 1) != 1 { return 35; }
    pb_system_poll(system, 60); if pb_j(pb_joint(robot, 0), PB_J_ONLINE) || pb_vget(system, 1) != 3 { return 36; }
    let loops = 0;
    while pb_system_active(system) && loops < 8 {
        if !pb_system_take_tx(system) { return 37; }
        pb_system_error(system); loops = loops + 1;
    }
    if pb_system_active(system) || loops != 4 || load64(robot + 4248) != 1 { return 38; }
    let i = 0; while i < 16 { if pb_system_queue(system, 1, values) { return 39; } i = i + 1; }
    if pb_system_queue(system, 1, values) != -11 { return 40; }
    return 0;
}
fn main() {
    let result = contracts_parser(); if result { return result; }
    result = contracts_commands(); if result { return result; }
    return contracts_scheduler();
}
