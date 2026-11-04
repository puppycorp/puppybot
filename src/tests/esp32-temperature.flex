// Exercise the actual combined-feedback parser and embedded temperature policy.
import "../firmware/controller.flex";
global pt_now = 100000;
global pt_reply = 0;
global pt_data = 0;
global pt_checksum_bad = 0;
fn pe_now_us() { return pt_now; }
fn pe_uart_reset(bus) { return 0; }
fn pe_uart_read(bus) { return -1; }
fn pe_uart_write(bus, data, size) { return size; }
fn pe_uart_idle(bus) { return 1; }
fn pt_read(system, size, status, temperature, time) {
    pb_system_cancel(system); let robot = load64(system); let index = load64(robot + 4272);
    pb_system_begin(system, time - 20);
    if pb_system_take_tx(system) != 8 || load8(pb_system_packet(system) + 5) != 56 || load8(pb_system_packet(system) + 6) != 8 { return -1; }
    pb_system_written(system, time - 10); pb_zero(pt_data, 64); pb_put16(pt_data, 2048); store8(pt_data + 7, temperature);
    let n = pb_servo_packet(pt_reply, 128, pb_j(pb_joint(robot, index), PB_J_ID), status, pt_data, size);
    if pt_checksum_bad { store8(pt_reply + n - 1, load8(pt_reply + n - 1) ^ 1); }
    let i = 0; while i < n { if pb_system_receive(system, pt_reply + i, 1, time) != 1 { return -2; } i = i + 1; }
    return index;
}
fn pt_parser() {
    let robot = alloc(8192); let system = alloc(2048); pb_robot_init(robot, 0); pb_system_init(system, robot);
    pb_system_temperature_enable(system); pt_reply = alloc(128); pt_data = alloc(64);
    let index = pt_read(system, 8, 0, 81, 20); if index < 0 { return 1; }
    let joint = pb_joint(robot, index);
    if !pb_j(joint, PB_J_TEMP_VALID) || pb_j(joint, PB_J_TEMP) != 81 || pb_j(joint, PB_J_TICK) != 2048 || pb_vget(system, 12 + index) != 20 { return 2; }
    // The recorded temperature reaches the existing Rust-equivalent governor.
    if pb_govern_speed(joint, 100, 20) || pb_j(joint, PB_J_FAULT) != 1 { return 3; }
    pb_system_cancel(system); if !pb_vget(system, 11) || pb_vget(system, 12 + index) != 20 { return 4; }
    let size = 0;
    while size <= 64 {
        index = load64(robot + 4272); joint = pb_joint(robot, index); pb_arm_temperature(robot, index, 1, 91);
        pb_vset(system, 12 + index, 10);
        if pt_read(system, size, 0, 32, 40) != index { return 5; }
        if size == 8 { if !pb_j(joint, PB_J_TEMP_VALID) || pb_j(joint, PB_J_TEMP) != 32 || pb_vget(system, 12 + index) != 40 { return 6; } }
        else { if pb_j(joint, PB_J_TEMP_VALID) || pb_vget(system, 12 + index) != -1 || pb_j(joint, PB_J_TEMP) != 91 { return 7; } }
        size = size + 1;
    }
    index = pt_read(system, 8, 4, 25, 60); if index < 0 || pb_j(pb_joint(robot, index), PB_J_TEMP_VALID) { return 8; }
    pt_checksum_bad = 1; index = pt_read(system, 8, 0, 25, 80); pt_checksum_bad = 0;
    if index < 0 || pb_j(pb_joint(robot, index), PB_J_TEMP_VALID) { return 9; }
    pb_system_cancel(system); index = load64(robot + 4272); pb_arm_temperature(robot, index, 1, 25); pb_vset(system, 12 + index, 90);
    pb_system_begin(system, 100); pb_system_take_tx(system); pb_system_written(system, 100); pb_system_poll(system, 150);
    if pb_j(pb_joint(robot, index), PB_J_TEMP_VALID) || pb_vget(system, 12 + index) != -1 { return 10; }
    return 0;
}
fn pt_policy() {
    if pf_init() || pf_temperature_fault(100) != 1 || pf_ready(100) { return 11; }
    let i = 0; while i < 4 {
        pb_arm_feedback(pf_robot, i, pb_j(pb_joint(pf_robot, i), PB_J_REFERENCE_TICK), 100);
        pb_arm_temperature(pf_robot, i, 1, 80); pb_vset(pf_system, 12 + i, 100); i = i + 1;
    }
    if !pf_ready(100) || pf_temperature_fault(350) || pf_temperature_fault(351) != 2 || pf_temperature_fault(99) != 2 { return 12; }
    // Explicit enable preserves combined reads and all sensor receipt times.
    store64(pf_parser + 24, 4); store64(pf_parser + 32, 1); store8(pf_parser + 64, 1);
    pf_request(100); if pf_enabled != 1 || !pb_vget(pf_system, 11) || pb_vget(pf_system, 12) != 100 { return 13; }
    let values = alloc(64); pb_vset(values, 0, 0); pb_vset(values, 1, 1); pb_arm_command(pf_robot, 2, values, 100);
    pb_system_queue(pf_system, 2, values); pb_arm_temperature(pf_robot, 2, 1, 81); pf_temperature_poll(100);
    if pf_enabled != 2 || pf_temperature_reason != 3 || pb_vget(pf_system, 9) || pb_a(pf_robot, PB_A_MODE) { return 14; }
    i = 0; while i < 4 { if pb_j(pb_joint(pf_robot, i), PB_J_SPEED) { return 15; } i = i + 1; }
    // Cooling never re-enables output. A fresh explicit enable is required.
    pb_arm_temperature(pf_robot, 2, 1, 25); pf_temperature_poll(100); if pf_enabled != 2 { return 16; }
    pf_request(100); if pf_enabled != 1 || pf_temperature_reason { return 17; }
    pf_temperature_poll(351); if pf_enabled != 2 || pf_temperature_reason != 2 { return 18; }
    pf_enabled = 0; pf_request(351); if pf_enabled { return 19; }
    // A failed read is unavailable, never a fabricated zero-degree sample.
    pf_request(100); pb_arm_temperature(pf_robot, 0, 0, 91); pf_temperature_poll(100);
    if pf_enabled != 2 || pf_temperature_reason != 1 || pb_j(pb_joint(pf_robot, 0), PB_J_TEMP) != 91 { return 20; }
    pf_status(); return 0;
}
fn main() { let result = pt_parser(); if result { return result; } return pt_policy(); }
