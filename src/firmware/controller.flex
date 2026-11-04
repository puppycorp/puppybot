// The production embedded loop. Platform supplies pe_now_us and pe_uart_*.
// All allocations occur in pf_init; subsequent polls use bounded work/buffers.
import "../core/interlock.flex";
import "../core/config.flex";
import "serial.flex";
import "../../build/flex/esp32/config.flex";

global pf_robot = 0;
global pf_system = 0;
global pf_parser = 0;
global pf_scratch = 0;
global pf_wire = 0;
global pf_output = 0;
global pf_output_read = 0;
global pf_output_count = 0;
global pf_enabled = 0;
global pf_tx_size = 0;
global pf_tx_at = 0;
global pf_tx_start = 0;
global pf_next_cycle = 0;
global pf_cycle_start = 0;
global pf_cycle_active = 0;
global pf_cycles = 0;
global pf_cycle_us = 0;
global pf_max_cycle_us = 0;
global pf_overruns = 0;
global pf_bus_errors = 0;
global pf_serial_errors = 0;
global pf_dropped = 0;
global pf_next_telemetry = 0;
// Latched until a successful explicit enable:0 none,1 unavailable,2 stale,3 hot.
global pf_temperature_reason = 0;

fn pf_send(kind, bytes, size) {
    let n = pf_envelope(pf_wire, kind, bytes, size); if n < 0 { return n; }
    if n + pf_output_count > 2048 { pf_dropped = pf_dropped + 1; return -11; }
    let i = 0; while i < n { store8(pf_output + ((pf_output_read + pf_output_count + i) % 2048), load8(pf_wire + i)); i = i + 1; }
    pf_output_count = pf_output_count + n; return 0;
}
fn pf_status() {
    pb_zero(pf_scratch, 80); store8(pf_scratch, pf_enabled); store8(pf_scratch + 1, pf_temperature_reason);
    pb_put32(pf_scratch + 4, pf_cycles); pb_put32(pf_scratch + 8, pf_cycle_us); pb_put32(pf_scratch + 12, pf_max_cycle_us);
    pb_put32(pf_scratch + 16, pf_overruns); pb_put32(pf_scratch + 20, pf_bus_errors); pb_put32(pf_scratch + 24, pf_serial_errors);
    pb_put32(pf_scratch + 28, pf_dropped); pb_put32(pf_scratch + 32, 500); pb_put32(pf_scratch + 36, 1000000);
    let now = pe_now_us() / 1000;
    pb_put32(pf_scratch + 40, 20000); pb_put32(pf_scratch + 44, now);
    let i = 0; while i < 4 {
        let out = pf_scratch + 48 + i * 8; let joint = pb_joint(pf_robot, i); let time = pb_vget(pf_system, 12 + i);
        store8(out, pb_j(joint, PB_J_TEMP_VALID)); store8(out + 1, pb_j(joint, PB_J_TEMP));
        let age = 0xffffffff; if time >= 0 && now >= time { age = pb_min(now - time, 0xfffffffe); }
        pb_put32(out + 4, age); i = i + 1;
    } return pf_send(6, pf_scratch, 80);
}
fn pf_error(code) { pb_put32(pf_scratch, code); return pf_send(7, pf_scratch, 4); }
fn pf_stop(now) {
    pb_arm_stop(pf_robot, now); pb_as(pf_robot, PB_A_MODE, 0); pb_drive_stop(pb_robot_drive(pf_robot), now);
    if pf_enabled == 2 { return 0; }
    pb_system_cancel(pf_system); pe_uart_reset(2); pf_tx_size = 0; pf_cycle_active = 0; pf_next_cycle = now; return 0;
}
fn pf_temperature_fault(now) {
    return pb_temperature_fault(pf_system, now);
}
fn pf_temperature_poll(now) {
    if pf_enabled != 1 { return 0; }
    let reason = pf_temperature_fault(now);
    if reason { pf_temperature_reason = reason; pf_stop(now); pf_enabled = 2; }
    return 0;
}
fn pf_ready(now) {
    return pb_feedback_ready(pf_system, now);
}
fn pf_request(now) {
    let kind = load64(pf_parser + 24); let size = load64(pf_parser + 32); let data = pf_parser + 64;
    if kind == 5 && !size { return pf_status(); }
    if kind == 4 && size == 1 && load8(data) < 2 {
        if load8(data) {
            if !pf_ready(now) { let reason = pf_temperature_fault(now); if reason { pf_temperature_reason = reason; } return pf_error(-107); }
            pf_stop(now); pb_rearm_outputs(pf_robot); pf_temperature_reason = 0; pf_enabled = 1;
        }
        else { pf_stop(now); if pf_enabled { pf_enabled = 2; } }
        return pf_status();
    }
    if kind != 1 || size < 4 || load8(data) != 1 || pb_u16(data + 2) != size - 4 { return pf_error(-71); }
    let command = load8(data + 1);
    if command == 15 || command == 31 || command == 35 || command == 4 || command == 28 { pf_stop(now); return pf_status(); }
    if command != 1 && command != 25 && command != 9 && command != 33 && pf_enabled != 1 { return pf_error(-13); }
    // Wiring/calibration is fixed in the reviewed build profile. Generic v1
    // supports mutation; this first hardware target exposes motion and reads.
    if command == 21 || command == 22 || command == 24 || command == 26 { return pf_error(-95); }
    let n = pb_system_frame(pf_system, data, size, pf_scratch); if n < 0 { return pf_error(n); }
    if n { return pf_send(2, pf_scratch, n); }
    if !load64(pf_robot + 4280) && command != 9 && command != 33 { return pf_error(-22); }
    store8(pf_scratch, command); store8(pf_scratch + 1, pb_vget(pf_system, 9)); return pf_send(8, pf_scratch, 2);
}
fn pf_host_poll(now) {
    let i = 0; while i < 64 { let byte = pe_uart_read(0); if byte < 0 { if byte != -1 { pf_serial_errors = pf_serial_errors + 1; pf_serial_reset(pf_parser); pf_stop(now); if pf_enabled { pf_enabled = 2; } } i = 64; }
        else { let result = pf_serial_byte(pf_parser, byte, now); if result == 1 { pf_request(now); } else if result < 0 { pf_serial_errors = pf_serial_errors + 1; } i = i + 1; }
    }
    if pf_output_count { let n = pf_output_count; if n > 2048 - pf_output_read { n = 2048 - pf_output_read; }
        n = pe_uart_write(0, pf_output + pf_output_read, n); if n > 0 { pf_output_read = (pf_output_read + n) % 2048; pf_output_count = pf_output_count - n; }
    } return 0;
}
fn pf_bus_error() { pe_uart_reset(2); pf_bus_errors = pf_bus_errors + 1; pf_tx_size = 0; pb_system_error(pf_system); return 0; }
fn pf_bus_step(now) {
    if !pb_system_active(pf_system) && now >= pf_next_cycle {
        pf_next_cycle = now + 20; pf_cycle_start = pe_now_us(); pf_cycle_active = 1; pb_system_begin(pf_system, now);
    }
    if !pb_system_active(pf_system) { return 0; }
    if !pf_tx_size {
        let n = pb_system_take_tx(pf_system);
        if n {
            if !pf_enabled && pb_vget(pf_system, 1) != 1 { pb_system_error(pf_system); return 0; }
            // Drain only once when beginning a request; preserve received bytes
            // while TX shifts. A retransmission retains the controller deadline.
            let i = 0; while i < 128 { let old = pe_uart_read(2); if old == -1 { i = 128; } else if old < -1 { return pf_bus_error(); } else { i = i + 1; } }
            pf_tx_size = n; pf_tx_at = 0; pf_tx_start = now;
        }
    }
    if pf_tx_size {
        if now - pf_tx_start >= 10 { return pf_bus_error(); }
        let n = pe_uart_write(2, pb_system_packet(pf_system) + pf_tx_at, pf_tx_size - pf_tx_at);
        if n < 0 { return pf_bus_error(); } pf_tx_at = pf_tx_at + n;
        if pf_tx_at != pf_tx_size || !pe_uart_idle(2) { return 0; }
        pf_tx_size = 0; pb_system_written(pf_system, now);
    }
    let i = 0; while i < 128 && pb_system_active(pf_system) && !pb_vget(pf_system, 6) {
        let byte = pe_uart_read(2); if byte == -1 { i = 128; } else if byte < -1 { return pf_bus_error(); }
        else { store8(pf_scratch, byte); pb_system_receive(pf_system, pf_scratch, 1, now); i = i + 1; }
    }
    if pb_system_active(pf_system) && !pb_vget(pf_system, 6) && pb_vget(pf_system, 4) != -1 && now >= pb_vget(pf_system, 4) { pf_bus_errors = pf_bus_errors + 1; }
    pb_system_poll(pf_system, now);
    return 0;
}
fn pf_bus_poll(now) {
    pf_bus_step(now);
    if pf_cycle_active && !pb_system_active(pf_system) {
        pf_cycle_active = 0; pf_cycles = pf_cycles + 1; pf_cycle_us = pe_now_us() - pf_cycle_start;
        if pf_cycle_us > pf_max_cycle_us { pf_max_cycle_us = pf_cycle_us; } if pf_cycle_us > 20000 { pf_overruns = pf_overruns + 1; }
        if pf_enabled == 2 { pf_enabled = 0; }
    } return 0;
}
fn pf_init() {
    pf_robot = alloc(8192); pf_system = alloc(2048); let config = alloc(448); pf_parser = alloc(320);
    pf_scratch = alloc(256); pf_wire = alloc(264); pf_output = alloc(2048);
    if pf_robot < 0 || pf_system < 0 || config < 0 || pf_parser < 0 || pf_scratch < 0 || pf_wire < 0 || pf_output < 0 { return -12; }
    pb_command_timeout_ms = 500; pf_physical_config(config);
    let result = pb_robot_configure(pf_robot, config, pe_now_us() / 1000); if result { return result; }
    pb_system_init(pf_system, pf_robot); pb_system_temperature_enable(pf_system); return 0;
}
fn pf_poll() {
    let now = pe_now_us() / 1000; pf_host_poll(now); pf_temperature_poll(now); pf_bus_poll(now);
    // A completed/failed feedback reply can change the interlock this poll.
    // Cancel its pending outputs before another iteration can transmit them.
    pf_temperature_poll(pe_now_us() / 1000);
    if load64(pf_robot + 4240) && now >= pf_next_telemetry {
        pf_next_telemetry = now + 100; let n = pb_arm_state_frame(pf_robot, pf_scratch, 256); if n > 0 { pf_send(3, pf_scratch, n); }
    } return 0;
}
