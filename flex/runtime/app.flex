// One controller instance is shared by HTTP and protocol v1 WebSocket clients.
import "../host/config.flex";
import "../core/interlock.flex";

// App words: robot, system, config, fake bus, serial, config path, start time,
// dirty, fake mode, held drive, throttle, steer, drive refresh, held joint,
// joint index, direction, joint refresh, held TCP, frame, dx/dy/dz, TCP refresh,
// selected arm speed, selected TCP frame. Scratch begins at byte 768.
// Physical admission:37 guarded,38 monitor/enabled/stopping,39 thermal reason.
fn pr_guard_motion(command) {
    return command == 2 || (command >= 5 && command <= 10) || (command >= 12 && command <= 14) || command == 16 || command == 101 || command == 102;
}
fn pr_guard_setting(command) { return command == 15 || command == 17 || command == 18 || command == 20 || command == 104; }
fn pr_joint_name(index, lower) {
    if index == 0 { if lower { return "yaw"; } return "Yaw"; }
    if index == 1 { if lower { return "shoulder"; } return "Shoulder"; }
    if index == 2 { if lower { return "elbow"; } return "Elbow"; }
    if lower { return "wrist"; } return "Wrist";
}
fn pr_init(app, robot, system, config, path, fake, start) {
    pb_zero(app, 2048); pb_vset(app, 0, robot); pb_vset(app, 1, system); pb_vset(app, 2, config);
    pb_vset(app, 5, path); pb_vset(app, 6, start); pb_vset(app, 8, fake); pb_vset(app, 23, 220);
    pb_copy(app + 512, "ready", 6); let values = app + 768; store64(values, 220); pb_arm_command(robot, 1, values, 0); return 0;
}
fn pr_dirty(app) { if pc_sync(load64(app), pb_vget(app, 2)) { pb_vset(app, 7, 1); } return 0; }
fn pr_last(app, text) { let n = pb_min(pl_size(text), 255); pb_copy(app + 512, text, n); store8(app + 512 + n, 0); return 0; }
fn pr_apply(app, command, values, now) {
    let robot = load64(app);
    if pb_vget(app, 37) {
        if pr_guard_setting(command) { return 8; }
        if pr_guard_motion(command) && (pb_vget(app, 38) != 1 || !pb_feedback_ready(pb_vget(app, 1), now)) { return 7; }
        if command == 4 || command == 11 || command == 103 { return pr_guard_abort(app, now); }
    }
    if command == 6 { let i = 0; while i < 4 { if !pc_angle_valid(pb_vget(values, i)) { return 3; } i = i + 1; } }
    if command == 7 && !pc_angle_valid(pb_vget(values, 3)) { return 3; }
    if (command == 14 || command == 16) && !pc_angle_valid(pb_vget(values, 1)) { return 3; }
    if command == 15 && !pc_angle_valid(pb_vget(values, 2)) { return 3; }
    if !pb_vget(app, 8) && load64(pb_vget(app, 4)) < 0 {
        if command == 2 || (command >= 5 && command <= 10) || command == 12 || command == 16 || command == 101 || command == 102 { return 4; }
    }
    if command == 103 { pb_vset(app, 9, 0); }
    if command == 3 && pb_vget(app, 13) && pb_vget(app, 14) == load64(values) { pb_vset(app, 13, 0); }
    if command == 4 || command == 11 || command == 12 || (command >= 5 && command <= 10) { pb_vset(app, 13, 0); pb_vset(app, 17, 0); }
    let error = pb_robot_event(robot, command, values, now);
    if !error { pr_dirty(app); store64(robot + 4248, (load64(robot + 4248) + 1) & 0xffffffff); }
    return error;
}
fn pr_wire(app, bytes, size, response, now) {
    if pb_vget(app, 37) && size >= 2 {
        let command = load8(bytes + 1);
        if command == 21 || command == 22 || command == 24 || command == 26 { return 0; }
    }
    let robot = load64(app); let events = robot + 4608; let n = pb_decode(robot, bytes, size, events, response);
    let count = load64(robot + 4280); let i = 0;
    while i < count { let event = events + i * 64; pr_apply(app, load64(event), event + 8, now); i = i + 1; }
    if count { pr_last(app, "websocket command"); } return n;
}
fn pr_refresh(app, now) {
    // Physical callers renew jogs with new requests; retained UI state must not
    // keep an abandoned command alive beyond the500ms command lease.
    if pb_vget(app, 37) { return 0; }
    let robot = load64(app); let values = app + 768;
    if pb_vget(app, 9) && pb_elapsed(now, pb_vget(app, 12)) >= 200 {
        pb_drive_steer(pb_robot_drive(robot), pb_vget(app, 10), pb_vget(app, 11), now); pb_vset(app, 12, now);
    }
    if pb_vget(app, 13) && pb_elapsed(now, pb_vget(app, 16)) >= 200 {
        store64(values, pb_vget(app, 14)); store64(values + 8, pb_vget(app, 15));
        if pb_arm_command(robot, 2, values, now) { pb_vset(app, 13, 0); } else { pb_vset(app, 16, now); }
    }
    if pb_vget(app, 17) && pb_elapsed(now, pb_vget(app, 22)) >= 200 {
        store64(values, pb_vget(app, 18)); pb_copy(values + 8, app + 19 * 8, 24);
        if pb_arm_command(robot, 9, values, now) { pb_vset(app, 17, 0); } else { pb_vset(app, 22, now); }
    }
    return 0;
}
fn pr_stop(app, now) {
    pb_vset(app, 9, 0); pb_vset(app, 13, 0); pb_vset(app, 17, 0);
    let robot = load64(app); pb_arm_stop(robot, now); pb_as(robot, PB_A_MODE, 0); pb_drive_stop(pb_robot_drive(robot), now); return 0;
}
fn pr_guard_abort(app, now) {
    if pb_vget(app, 38) == 2 { return pr_stop(app, now); }
    pr_stop(app, now); pb_system_cancel(pb_vget(app, 1));
    let serial = pb_vget(app, 4); let fd = load64(serial);
    if fd >= 0 { syscall(16, fd, 0x540b, 2, 0, 0, 0); }
    pb_zero(serial + 8, 32); pb_vset(serial, 6, pb_vget(app, 38) != 0); return 0;
}
fn pr_guard_stop(app, now) { pr_guard_abort(app, now); pb_vset(app, 38, 2); pb_vset(pb_vget(app, 4), 6, 1); return 0; }
fn pr_guard_init(app) {
    pb_vset(app, 37, 1); pb_vset(app, 38, 0); pb_vset(app, 39, 0);
    pb_command_timeout_ms = 500; pb_system_temperature_enable(pb_vget(app, 1)); pb_vset(pb_vget(app, 4), 6, 0); return 0;
}
fn pr_guard_poll(app, now) {
    if !pb_vget(app, 37) { return 0; }
    let system = pb_vget(app, 1); let serial = pb_vget(app, 4);
    if pb_vget(app, 38) == 1 {
        let reason = pb_temperature_fault(system, now);
        if reason { pb_vset(app, 39, reason); pr_guard_stop(app, now); pr_last(app, "temperature interlock; outputs disabling"); }
    }
    pb_vset(serial, 6, pb_vget(app, 38) != 0); return 0;
}
fn pr_guard_cycle(app) {
    if pb_vget(app, 37) && pb_vget(app, 38) == 2 && !pb_system_active(pb_vget(app, 1)) {
        pb_vset(app, 38, 0); pb_vset(pb_vget(app, 4), 6, 0);
    } return 0;
}
fn pr_control_state(app, builder, now) {
    let state = pb_vget(app, 38); let system = pb_vget(app, 1); let robot = load64(app);
    pl_text(builder, ",\"control\":{\"state\":");
    if !pb_vget(app, 37) || state == 1 { pj_text(builder, "enabled"); }
    else if state == 2 { pj_text(builder, "stopping"); } else { pj_text(builder, "monitor"); }
    pl_text(builder, ",\"guarded\":"); pj_bool_text(builder, pb_vget(app, 37));
    pl_text(builder, ",\"commandTimeoutMs\":"); pl_uint(builder, pb_command_timeout_ms);
    if pb_vget(app, 37) {
        pl_text(builder, ",\"temperatureInterlock\":"); pj_text(builder, pb_temperature_reason(pb_vget(app, 39)));
        pl_text(builder, ",\"temperatures\":["); let i = 0;
        while i < 4 {
            if i { pl_char(builder, 44); } let joint = pb_joint(robot, i); let time = pb_vget(system, 12 + i);
            pl_text(builder, "{\"temperatureC\":"); if pb_j(joint, PB_J_TEMP_VALID) { pl_int(builder, pb_j(joint, PB_J_TEMP)); } else { pl_text(builder, "null"); }
            pl_text(builder, ",\"ageMs\":"); if time >= 0 && now >= time { pl_uint(builder, now - time); } else { pl_text(builder, "null"); }
            pl_text(builder, ",\"fresh\":"); pj_bool_text(builder, pb_j(joint, PB_J_TEMP_VALID) && time >= 0 && now >= time && now - time <= 250);
            pl_char(builder, 125); i = i + 1;
        } pl_char(builder, 93);
    } return pl_char(builder, 125);
}
fn pr_coords(builder, robot, type) {
    let out = robot + 5000; let error = 0;
    if type == 2 { error = pb_arm_effective_coords(robot, out); } else { error = pb_arm_coords(robot, out, type); }
    if error { return pl_text(builder, "null"); }
    pl_char(builder, 91); let i = 0;
    while i < 3 { if i { pl_char(builder, 44); } pl_float(builder, pb_f32_to_f64(pb_f64_to_f32(pb_vget(out, i)))); i = i + 1; }
    return pl_char(builder, 93);
}
fn pr_joint_json(builder, robot, index, autonomy) {
    let j = pb_joint(robot, index); pl_text(builder, "{\"index\":"); pl_int(builder, index);
    pl_text(builder, ",\"name\":"); pj_text(builder, pr_joint_name(index, 1));
    if !autonomy { pl_text(builder, ",\"servoId\":"); pl_int(builder, pb_j(j, PB_J_ID)); }
    pl_text(builder, ",\"tick\":"); if pb_j(j, PB_J_TICK_VALID) { pl_int(builder, pb_j(j, PB_J_TICK)); } else { pl_text(builder, "null"); }
    pl_text(builder, ",\"targetTick\":"); if pb_j(j, PB_J_TARGET_VALID) { pl_int(builder, pb_j(j, PB_J_TARGET)); } else { pl_text(builder, "null"); }
    pl_text(builder, ",\"angleDeg\":"); if pb_j(j, PB_J_ANGLE_VALID) { pl_float(builder, pb_f32_to_f64(pb_f64_to_f32(pb_degrees(pb_j(j, PB_J_ANGLE))))); } else { pl_text(builder, "null"); }
    pl_text(builder, ",\"targetAngleDeg\":"); if pb_j(j, PB_J_TARGET_ANGLE_VALID) { pl_float(builder, pb_f32_to_f64(pb_f64_to_f32(pb_degrees(pb_j(j, PB_J_TARGET_ANGLE))))); } else { pl_text(builder, "null"); }
    pl_text(builder, ",\"online\":"); pj_bool_text(builder, pb_j(j, PB_J_ONLINE));
    pl_text(builder, ",\"hasFeedback\":"); pj_bool_text(builder, pb_j(j, PB_J_FEEDBACK) && pb_j(j, PB_J_TICK_VALID));
    pl_text(builder, ",\"limitReached\":"); pj_bool_text(builder, pb_j(j, PB_J_TICK_VALID) && !pb_tick_within(j, pb_j(j, PB_J_TICK)));
    if !autonomy {
        pl_text(builder, ",\"speed\":"); pl_int(builder, pb_j(j, PB_J_SPEED));
        pl_text(builder, ",\"minTick\":"); pl_int(builder, pb_j(j, PB_J_MIN)); pl_text(builder, ",\"maxTick\":"); pl_int(builder, pb_j(j, PB_J_MAX));
        pl_text(builder, ",\"fault\":"); if pb_j(j, PB_J_FAULT) { pj_text(builder, pb_fault_name(pb_j(j, PB_J_FAULT))); } else { pl_text(builder, "null"); }
    }
    return pl_char(builder, 125);
}
fn pr_mode_name(mode) {
    if mode == 0 { return "Idle"; } if mode == 1 { return "Jogging"; } if mode == 2 { return "TrackingTicks"; }
    if mode == 3 { return "TcpJogging"; } if mode == 4 { return "Holding"; } return "Fault";
}
fn pr_state(app, builder, now, autonomy) {
    let robot = load64(app); let drive = pb_robot_drive(robot);
    pl_text(builder, "{\"schema\":");
    if autonomy { pj_text(builder, "puppybot.runtime.autonomy-observation.v1"); }
    else { pj_text(builder, "puppybot.runtime.state.v1"); pl_text(builder, ",\"mode\":"); if pb_vget(app, 36) { pj_text(builder, "simulated"); } else if pb_vget(app, 8) { pj_text(builder, "fake"); } else { pj_text(builder, "hardware"); } }
    pl_text(builder, ",\"timeMs\":"); pl_uint(builder, now); pl_text(builder, ",\"arm\":{");
    if !autonomy { pl_text(builder, "\"mode\":"); pj_text(builder, pr_mode_name(pb_a(robot, PB_A_MODE))); pl_char(builder, 44); }
    pl_text(builder, "\"frame\":\"armBase\",\"unit\":\"mm\",\"currentTcpMm\":"); pr_coords(builder, robot, 0);
    pl_text(builder, ",\"targetTcpMm\":"); pr_coords(builder, robot, 1);
    if !autonomy { pl_text(builder, ",\"effectiveTargetTcpMm\":"); pr_coords(builder, robot, 2); }
    pl_text(builder, ",\"joints\":["); let i = 0;
    while i < 4 { if i { pl_char(builder, 44); } pr_joint_json(builder, robot, i, autonomy); i = i + 1; }
    pl_text(builder, "]},\"drive\":{");
    if !autonomy {
        pl_text(builder, "\"leftMotorId\":"); pl_int(builder, pb_vget(drive, 0)); pl_text(builder, ",\"rightMotorId\":"); pl_int(builder, pb_vget(drive, 1));
        pl_text(builder, ",\"steeringServoId\":"); pl_int(builder, pb_vget(drive, 2)); pl_char(builder, 44);
    }
    pl_text(builder, "\"leftSpeed\":"); pl_int(builder, pb_vget(drive, 6)); pl_text(builder, ",\"rightSpeed\":"); pl_int(builder, pb_vget(drive, 7));
    pl_text(builder, ",\"steeringAngleDeg\":"); pl_int(builder, pb_vget(drive, 8)); pl_text(builder, ",\"active\":"); pj_bool_text(builder, pb_vget(drive, 9));
    pl_text(builder, "},\"sim\":{\"enabled\":false"); if !autonomy { pl_text(builder, ",\"markers\":[],\"frames\":null"); }
    pl_char(builder, 125);
    if !autonomy {
        pl_text(builder, ",\"ui\":{\"coordinateFrame\":\"Robot Base\",\"absoluteCoordinateFrame\":\"Arm Base\",\"tcpFrame\":");
        if pb_vget(app, 24) == 1 { pj_text(builder, "Tool"); } else { pj_text(builder, "Base"); }
        pl_text(builder, ",\"armSpeed\":"); pl_int(builder, pb_vget(app, 23)); pl_text(builder, ",\"lastCommand\":"); pj_text(builder, app + 512); pl_char(builder, 125);
    }
    pr_control_state(app, builder, now); return pl_char(builder, 125);
}
fn pr_problem(app, builder, status, message, code) {
    pl_text(builder, "{\"ok\":false,\"error\":");
    if code == 6 {
        let temp = app + 1024; let b = app + 960; pl_builder(b, temp, 512);
        pl_text(b, "blocked by "); let robot = load64(app); let i = 0; let found = 0;
        while i < 4 && !found {
            let j = pb_joint(robot, i); let tick = load64(robot + 272 + i * 8);
            if !pb_tick_within(j, tick) {
                pl_text(b, pr_joint_name(i, 0)); let lo = pb_j(j, PB_J_MIN); let hi = pb_j(j, PB_J_MAX);
                if lo < hi && tick < lo { pl_text(b, " lower limit ("); pl_int(b, tick); pl_text(b, " < "); pl_int(b, lo); }
                else if lo < hi && tick > hi { pl_text(b, " upper limit ("); pl_int(b, tick); pl_text(b, " > "); pl_int(b, hi); }
                else { pl_text(b, " tick limit ("); pl_int(b, tick); pl_text(b, " outside configured range"); }
                pl_char(b, 41); found = 1;
            }
            i = i + 1;
        }
        pj_text(builder, temp);
    } else { pj_text(builder, message); }
    if code { pl_text(builder, ",\"controllerError\":"); pl_int(builder, code); }
    pl_char(builder, 125); return status;
}
fn pr_controller_error(code) {
    if code == 1 { return "invalid joint"; } if code == 2 { return "invalid servo IDs"; }
    if code == 3 { return "invalid command value"; } if code == 4 { return "joint feedback is unavailable"; }
    if code == 5 { return "target is geometrically unreachable"; }
    if code == 7 { return "outputs require explicit enable and fresh position/temperature feedback"; }
    if code == 8 { return "hardware calibration and limit changes require a reviewed configuration and restart"; } return "controller command rejected";
}
fn pr_direction(name, out) {
    pb_zero(out, 24);
    if pl_equal(name, "forward") { store64(out, PB_ONE); return 1; }
    if pl_equal(name, "back") || pl_equal(name, "backward") { store64(out, pb_neg(PB_ONE)); return 1; }
    if pl_equal(name, "left") { store64(out + 8, PB_ONE); return 1; }
    if pl_equal(name, "right") { store64(out + 8, pb_neg(PB_ONE)); return 1; }
    if pl_equal(name, "up") { store64(out + 16, PB_ONE); return 1; }
    if pl_equal(name, "down") { store64(out + 16, pb_neg(PB_ONE)); return 1; }
    return 0;
}
fn pr_frame(name) {
    if pl_equal(name, "base") || pl_equal(name, "Base") || pl_equal(name, "armBase") || pl_equal(name, "Arm Base") { return 0; }
    if pl_equal(name, "tool") || pl_equal(name, "Tool") { return 1; }
    if pl_equal(name, "yawFlat") || pl_equal(name, "yaw-flat") || pl_equal(name, "Yaw-flat") || pl_equal(name, "YawFlat") { return 2; }
    return -1;
}
fn pr_joint_command(app, path, root, now) {
    let slash = ph_find(path + 16, pl_size(path + 16), "/", 1);
    if slash < 1 { return -404; } let index = pl_integer(path + 16, slash);
    if pl_bad_number || index < 0 || index > 3 { pj_fail("joint must be between 0 and 3"); return -400; }
    let tail = path + 17 + slash; let values = app + 768; let robot = load64(app); let j = pb_joint(robot, index);
    pb_zero(values, 64); store64(values, index);
    if pl_equal(tail, "spin") {
        let direction = pj_integer(root, "direction", -1, 1); if !direction || pj_error { pj_fail("direction must be -1 or 1"); return -400; }
        pr_apply(app, 4, values, now); store64(values + 8, direction);
        let error = pr_apply(app, 2, values, now);
        if !error { pb_vset(app, 13, 1); pb_vset(app, 14, index); pb_vset(app, 15, direction); pb_vset(app, 16, now); } return error;
    }
    if pl_equal(tail, "stop") { return pr_apply(app, 3, values, now); }
    if pl_equal(tail, "zero") { return pr_apply(app, 14, values, now); }
    if pl_equal(tail, "reference") {
        let angle = pc_radians(pj_real(root, "angleDeg")); if pj_error { return -400; }
        if !pb_j(j, PB_J_TICK_VALID) { return 4; }
        store64(values + 8, pb_j(j, PB_J_TICK)); store64(values + 16, angle); return pr_apply(app, 15, values, now);
    }
    if pl_equal(tail, "limits") {
        store64(values + 8, pj_integer(root, "minTick", -2147483648, 2147483647)); store64(values + 16, pj_integer(root, "maxTick", -2147483648, 2147483647));
        if pj_error { return -400; } return pr_apply(app, 17, values, now);
    }
    if pl_equal(tail, "limits/enabled") { store64(values + 8, pj_boolean(root, "enabled")); if pj_error { return -400; } return pr_apply(app, 18, values, now); }
    if pl_equal(tail, "angle-sign/flip") {
        if pb_vget(app, 37) { return 8; }
        pr_dirty(app); let config = pb_vget(app, 2); let calibration = pb_config_joint(config, index);
        pb_vset(calibration, 5, -pb_vget(calibration, 5));
        let error = pb_robot_configure(robot, config, now); if error { return 3; }
        pb_system_init(pb_vget(app, 1), robot); pb_vset(app, 7, 1); pb_vset(app, 9, 0); pb_vset(app, 13, 0); pb_vset(app, 17, 0);
        store64(values, pb_vget(app, 23)); pb_arm_command(robot, 1, values, now); return 0;
    }
    return -404;
}
fn pr_command(app, path, root, now) {
    let values = app + 768; pb_zero(values, 64); let robot = load64(app); let config = pb_vget(app, 2);
    if pl_equal(path, "/api/control/enable") {
        if !pb_vget(app, 37) { return 0; }
        if !pb_feedback_ready(pb_vget(app, 1), now) {
            let reason = pb_temperature_fault(pb_vget(app, 1), now); if reason { pb_vset(app, 39, reason); } return 7;
        }
        pr_guard_stop(app, now); pb_rearm_outputs(robot); pb_vset(app, 38, 1); pb_vset(app, 39, 0); return 0;
    }
    if pl_equal(path, "/api/control/disable") { if pb_vget(app, 37) { return pr_guard_stop(app, now); } return pr_stop(app, now); }
    if pb_vget(app, 37) && pl_starts(path, "/api/arm/coordinate-calibration/") { return 8; }
    if pl_starts(path, "/api/arm/joints/") { return pr_joint_command(app, path, root, now); }
    if pl_equal(path, "/api/drive") {
        let throttle = 0; let steering = 0;
        if pj_get(root, "throttle") && pj_get(root, "steering") { throttle = pj_integer(root, "throttle", -128, 127); steering = pj_integer(root, "steering", -128, 127); }
        else {
            let action = pj_string_field(root, "action"); if pj_error { return -400; }
            if pl_equal(action, "forward") { throttle = 35; }
            else if pl_equal(action, "back") || pl_equal(action, "backward") { throttle = -35; }
            else if pl_equal(action, "left") { steering = -55; }
            else if pl_equal(action, "right") { steering = 55; }
            else if !pl_equal(action, "stop") { pj_fail("invalid drive action"); return -400; }
        }
        if pj_error { return -400; }
        store64(values, throttle); store64(values + 8, steering); let error = pr_apply(app, 101, values, now);
        pb_vset(app, 9, throttle != 0 || steering != 0); pb_vset(app, 10, throttle); pb_vset(app, 11, steering); pb_vset(app, 12, now); return error;
    }
    if pl_equal(path, "/api/drive/stop") { return pr_apply(app, 103, values, now); }
    if pl_equal(path, "/api/arm/speed") {
        let speed = pj_integer(root, "speed", 0, 32767); if pj_error { return -400; }
        store64(values, speed); let error = pr_apply(app, 1, values, now); if !error { pb_vset(app, 23, speed); } return error;
    }
    if pl_equal(path, "/api/arm/stop") { return pr_apply(app, 4, values, now); }
    if pl_equal(path, "/api/arm/hold") { return pr_apply(app, 12, values, now); }
    if pl_equal(path, "/api/arm/clear-faults") { store64(values, -1); return pr_apply(app, 19, values, now); }
    if pl_equal(path, "/api/arm/goto-angles") {
        store64(values, pc_radians(pj_real(root, "yawDeg"))); store64(values + 8, pc_radians(pj_real(root, "shoulderDeg")));
        store64(values + 16, pc_radians(pj_real(root, "elbowDeg"))); store64(values + 24, pc_radians(pj_real(root, "wristDeg")));
        if pj_error { return -400; } return pr_apply(app, 6, values, now);
    }
    if pl_equal(path, "/api/arm/goto-default") || pl_equal(path, "/api/arm/goto-default-angles") || pl_equal(path, "/api/arm/poses/drive-scan") {
        let i = 0; while i < 4 { pb_vset(values, i, PB_HALF_PI); i = i + 1; }
        if pl_equal(path, "/api/arm/poses/drive-scan") {
            pb_vset(values, 1, pc_radians(0x4028000000000000)); pb_vset(values, 2, pc_radians(0x404a000000000000)); pb_vset(values, 3, pc_radians(0x404ec00000000000));
            let ticks = app + 832; pb_angles_ticks(robot, ticks, values, 1);
            if !pb_ticks_within(robot, ticks) { pb_copy(robot + 272, ticks, 32); return 6; }
        }
        return pr_apply(app, 6, values, now);
    }
    if pl_equal(path, "/api/arm/goto-current") || pl_equal(path, "/api/arm/coordinates/current") { return 0; }
    if pl_equal(path, "/api/arm/coordinates/move") {
        store64(values, pj_real(root, "xMm")); store64(values + 8, pj_real(root, "yMm")); store64(values + 16, pj_real(root, "zMm")); store64(values + 24, pc_radians(pj_real(root, "toolPhiDeg")));
        if pj_error { return -400; } return pr_apply(app, 7, values, now);
    }
    if pl_equal(path, "/api/arm/tcp-frame") {
        let name = pj_string_field(root, "frame"); if pj_error { return -400; } let frame = pr_frame(name);
        if frame != 0 && frame != 1 { pj_fail("tcp frame must be base or tool"); return -400; } pb_vset(app, 24, frame); return 0;
    }
    if pl_equal(path, "/api/arm/coordinate-frame") { pj_fail("Coordinate Move is always robot-base relative"); return -400; }
    if pl_equal(path, "/api/arm/tcp-jog/stop") { return pr_apply(app, 11, values, now); }
    if pl_equal(path, "/api/arm/tcp-jog/start") || pl_equal(path, "/api/arm/coordinate-jog/start") {
        let name = pj_string_field(root, "frame"); if pj_error { return -400; } let frame = pr_frame(name);
        let direction = pj_string_field(root, "direction"); if pj_error { return -400; }
        let vector = app + 832; if !pr_direction(direction, vector) { pj_fail("invalid jog direction"); return -400; }
        if pl_equal(path, "/api/arm/coordinate-jog/start") {
            if frame != 0 { pj_fail("coordinate jog frame must be base/armBase"); return -400; }
            let angle = pc_radians(pb_vget(config + 128, 3)); let cy = f64_cos(angle); let sy = f64_sin(angle);
            let x = f64_mul(pb_vget(vector, 0), f64_from_i64(pb_vget(config + 128, 0)));
            let y = f64_mul(pb_vget(vector, 1), f64_from_i64(pb_vget(config + 128, 1)));
            pb_vset(vector, 0, f64_sub(f64_mul(x, cy), f64_mul(y, sy))); pb_vset(vector, 1, f64_add(f64_mul(x, sy), f64_mul(y, cy)));
            pb_vset(vector, 2, f64_mul(pb_vget(vector, 2), f64_from_i64(pb_vget(config + 128, 2))));
        } else {
            if frame != 0 && frame != 1 { pj_fail("tcp jog frame must be base or tool"); return -400; }
            let x = f64_mul(pb_vget(vector, 2), f64_from_i64(pb_vget(config + 128, 6)));
            let y = f64_mul(pb_vget(vector, 1), f64_from_i64(pb_vget(config + 128, 5)));
            let z = f64_mul(pb_vget(vector, 0), f64_from_i64(pb_vget(config + 128, 4)));
            pb_vset(vector, 0, x); pb_vset(vector, 1, y); pb_vset(vector, 2, z);
        }
        if pb_vget(app, 13) { store64(values, pb_vget(app, 14)); pr_apply(app, 3, values, now); }
        store64(values, frame); pb_copy(values + 8, vector, 24); let error = pr_apply(app, 9, values, now);
        if !error { pb_vset(app, 17, 1); pb_vset(app, 18, pb_a(robot, PB_A_FRAME)); pb_copy(app + 19 * 8, robot + PB_A_DX * 8, 24); pb_vset(app, 22, now); } return error;
    }
    if pl_equal(path, "/api/calibration/save") {
        pr_dirty(app); if pb_config_validate(config) { pj_fail("active calibration is invalid"); return -400; }
        let b = app + 960; let output = pb_vget(app, 30); pl_builder(b, output, 65536); pc_emit(b, config); pl_char(b, 10);
        if load64(b + 24) || pl_atomic_file(pb_vget(app, 5), output, load64(b + 8)) { pj_fail("cannot save calibration atomically"); return -400; }
        pb_vset(app, 7, 0); return 0;
    }
    if pl_starts(path, "/api/arm/coordinate-calibration/") {
        let field = path + 32; let index = -1;
        if pl_equal(field, "flip-forward") { index = 0; } if pl_equal(field, "flip-left") { index = 1; } if pl_equal(field, "flip-up") { index = 2; }
        if index >= 0 { pb_vset(config + 128, index, -pb_vget(config + 128, index)); pb_vset(app, 7, 1); return 0; }
        if pl_equal(field, "rotate-base") {
            let angle = pc_wrap_degrees(f64_add(pb_vget(config + 128, 3), 0x4056800000000000));
            pb_vset(config + 128, 3, angle); pb_vset(app, 7, 1); return 0;
        }
    }
    if pl_starts(path, "/api/sim/") || pl_equal(path, "/api/arm/tcp-camera-jog/start") { pj_fail("this operation requires the RobotDreams simulation backend"); return -409; }
    return -404;
}
fn pr_request(app, method, path, body, size, builder, now) {
    if pl_equal(method, "GET") {
        if pl_equal(path, "/api/state") { pr_state(app, builder, now, 0); return 200; }
        if pl_equal(path, "/api/autonomy/state") { pr_state(app, builder, now, 1); return 200; }
        if pl_equal(path, "/api/config.json") {
            pr_dirty(app); let config = pb_vget(app, 2); if pb_config_validate(config) { return pr_problem(app, builder, 500, "active calibration is invalid", 0); }
            pl_text(builder, "{\"path\":"); pj_text(builder, pb_vget(app, 5)); pl_text(builder, ",\"dirty\":"); pj_bool_text(builder, pb_vget(app, 7)); pl_text(builder, ",\"config\":"); pc_emit(builder, config); pl_char(builder, 125); return 200;
        }
        if pl_equal(path, "/") || pl_equal(path, "/health") { pl_text(builder, "{\"ok\":true,\"name\":\"Puppybot\"}"); return 200; }
        if pl_starts(path, "/api/sim/") || pl_starts(path, "/api/autonomy/observations/") || pl_starts(path, "/api/autonomy/cameras/") { return pr_problem(app, builder, 409, "simulation cameras and captures are unavailable in this backend", 0); }
        return pr_problem(app, builder, 404, "unknown api endpoint", 0);
    }
    if !pl_equal(method, "POST") { return pr_problem(app, builder, 405, "api commands require POST", 0); }
    if pb_vget(app, 36) && pl_equal(path, "/api/calibration/save") { return pr_problem(app, builder, 409, "Gym retains the initial calibration with the run", 0); }
    let root = 0; if !size { root = pj_parse("{}", 2); } else { root = pj_parse(body, size); }
    if !root || pj_kind(root) != 4 { return pr_problem(app, builder, 400, "request body must be a JSON object", 0); }
    let command_path = path;
    if pl_starts(path, "/api/autonomy/") {
        let out = app + 1792; pb_copy(out, "/api/", 5); let n = pl_size(path + 14); if n > 240 { return pr_problem(app, builder, 404, "unknown api endpoint", 0); }
        pb_copy(out + 5, path + 14, n + 1); command_path = out;
    }
    if !pb_vget(app, 8) && load64(pb_vget(app, 4)) < 0 && !pl_equal(command_path, "/api/control/disable") && !pl_equal(command_path, "/api/arm/stop") && !pl_equal(command_path, "/api/drive/stop") && !pl_equal(command_path, "/api/arm/tcp-jog/stop") && !pl_equal(command_path, "/api/calibration/save") {
        return pr_problem(app, builder, 409, "STServo bus is disconnected", 0);
    }
    let error = pr_command(app, command_path, root, now);
    if error < 0 { let message = pj_message; if error == -404 { message = "unknown api command"; } if !message { message = "command rejected"; } return pr_problem(app, builder, -error, message, 0); }
    if error { let status = 400; if error == 7 || error == 8 { status = 409; } return pr_problem(app, builder, status, pr_controller_error(error), error); }
    pr_last(app, path); pl_text(builder, "{\"ok\":true,\"state\":"); pr_state(app, builder, now, 0); pl_char(builder, 125); return 200;
}
