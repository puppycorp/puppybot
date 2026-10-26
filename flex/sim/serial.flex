// External serial peripheral mode. The robot structure below is a calibrated
// view for geometry/telemetry only; this mode never ticks its controller.
import "../simulator/bus.flex";

global ps_external = 0;
global ps_serial_config = 0;
global ps_serial_temperature = 25;
global ps_serial_jam = -1;
global ps_serial_context = 0;
global ps_serial_path = 0;
global ps_serial_input = 0;
global ps_serial_output = 0;
global ps_serial_reply = 0;

fn ps_serial_stop() {
    if !ps_serial_context { return 0; }
    let i = 0; while i < 4 { pb_vset(ps_bus + pb_vget(ps_plant + 128 + i * 64, 3) * 48, 3, 0); i = i + 1; }
    pb_drive_stop(pb_robot_drive(ps_robot), ps_time); pb_vset(ps_serial_context, 14, 0); return 0;
}
fn ps_serial_quarantine(until) {
    if !ps_serial_context { return 0; }
    ps_serial_stop(); pb_vset(ps_serial_context, 15, until);
    pb_vset(ps_serial_context, 7, 0); pb_vset(ps_serial_context, 8, 0); pb_vset(ps_serial_context, 9, 0); pb_vset(ps_serial_context, 10, 0);
    syscall(16, load64(ps_serial_context), 0x540b, 2, 0, 0, 0); return 0;
}
fn ps_serial_open() {
    ps_serial_context = alloc(512); pb_zero(ps_serial_context, 512); store64(ps_serial_context, -1);
    pb_vset(ps_serial_context, 1, -1); pb_vset(ps_serial_context, 2, ps_plant); pb_vset(ps_serial_context, 3, ps_bus);
    pb_vset(ps_serial_context, 4, ps_serial_temperature); pb_vset(ps_serial_context, 12, pb_robot_drive(ps_robot));
    pb_vset(ps_serial_context, 13, -1); pb_vset(ps_serial_context, 17, -1);
    ps_serial_path = alloc(128); ps_serial_input = alloc(4096); ps_serial_output = alloc(16384); ps_serial_reply = alloc(128);
    if pv_pty(ps_serial_context, ps_serial_path) < 0 { pl_print(2, "Cannot create simulator virtual serial port.\n"); return 0; }
    return 1;
}
fn ps_serial_poll(wall) {
    if !ps_external { return 1; }
    if ps_paused { pb_vset(ps_serial_context, 15, -1); }
    else if pb_vget(ps_serial_context, 15) < 0 { pb_vset(ps_serial_context, 15, wall + 350); }
    if pv_bytes(ps_serial_context, ps_serial_input, ps_serial_output, ps_serial_reply, wall) < 0 { pl_print(2, "External simulator serial I/O failed.\n"); return 0; }
    if ps_paused || wall - pb_vget(ps_serial_context, 17) > 500 { ps_serial_stop(); }
    else if wall - pb_vget(ps_serial_context, 13) > 500 { pb_drive_stop(pb_robot_drive(ps_robot), ps_time); pb_vset(ps_serial_context, 14, 0); }
    return 1;
}
fn ps_serial_feedback() {
    let i = 0; let moving = 0;
    while i < 4 {
        let joint = pb_joint(ps_robot, i); let plant = ps_plant + 128 + i * 64;
        pb_arm_feedback(ps_robot, i, pb_vget(plant, 2), ps_time);
        let speed = pb_vget(ps_bus + pb_vget(plant, 3) * 48, 3); pb_js(joint, PB_J_SPEED, speed); if speed { moving = 1; }
        i = i + 1;
    }
    pb_as(ps_robot, PB_A_MODE, moving); return 0;
}
fn ps_serial_quote(b, text) {
    pl_char(b, 39); let i = 0;
    while load8(text + i) { let byte = load8(text + i); if byte == 39 { pl_text(b, "'\\''"); } else { pl_char(b, byte); } i = i + 1; }
    return pl_char(b, 39);
}
fn ps_serial_announce() {
    pl_builder(ps_builder, ps_json, 16384); pl_text(ps_builder, "Puppybot simulator listening on "); pl_text(ps_builder, ps_serial_path);
    pl_text(ps_builder, "\n3D environment, external controller. In another terminal:\n  flexscript run puppybot.flex --virtual-bus --servo-device ");
    ps_serial_quote(ps_builder, ps_serial_path); pl_text(ps_builder, " --config "); ps_serial_quote(ps_builder, ps_serial_config);
    pl_text(ps_builder, "\nOpen http://127.0.0.1:8081/ and enable outputs.\n"); return pl_print(1, ps_json);
}
fn ps_serial_observation(b) {
    pl_text(b, ",\"externalSerial\":"); if !ps_external { return pl_text(b, "null"); }
    pl_text(b, "{\"device\":"); pj_text(b, ps_serial_path); pl_text(b, ",\"config\":"); pj_text(b, ps_serial_config);
    pl_text(b, ",\"enabled\":"); pj_bool_text(b, pb_vget(ps_serial_context, 14)); pl_text(b, ",\"serialPackets\":"); pl_uint(b, pb_vget(ps_serial_context, 5));
    pl_text(b, ",\"temperatureC\":"); pl_int(b, ps_serial_temperature); return pl_text(b, "}");
}
fn ps_serial_close() {
    if ps_serial_context {
        ps_serial_stop(); syscall(3, pb_vget(ps_serial_context, 1), 0, 0, 0, 0, 0); syscall(3, load64(ps_serial_context), 0, 0, 0, 0, 0);
    } return 0;
}
