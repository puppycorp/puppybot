// JSON boundary for the shared configuration. Parsing writes a separate
// candidate; the active robot/configuration changes only after validation.
import "json.flex";
import "../core/config.flex";

fn pc_radians(degrees) { return f64_mul(degrees, 0x3f91df46a2529d39); }
fn pc_degrees(radians) { return f64_mul(radians, 0x404ca5dc1a63c1f8); }
// Host inputs stay within 100 turns so the reference controller's repeated
// angle wrapping has a bounded cost, including calibrated feedback angles.
fn pc_angle_valid(radians) { return f64_is_finite(radians) && f64_le(f64_magnitude(radians), 0x4083a28c59d5433b); }
fn pc_wrap_degrees(angle) {
    let negative = f64_sign(angle); let value = f64_magnitude(angle); let period = 0x4076800000000000; let scale = period;
    while f64_le(scale, f64_mul(value, 0x3fe0000000000000)) { scale = f64_mul(scale, 0x4000000000000000); }
    while f64_ge(scale, period) {
        if f64_ge(value, scale) { value = f64_sub(value, scale); } scale = f64_mul(scale, 0x3fe0000000000000);
    }
    if negative && !f64_eq(value, 0) { value = f64_sub(period, value); }
    if f64_ge(value, period) { return 0; } return value;
}
fn pc_optional_int(object, name, fallback, lo, hi) {
    if !pj_get(object, name) { return fallback; } return pj_integer(object, name, lo, hi);
}
fn pc_optional_real(object, name, fallback) {
    if !pj_get(object, name) { return fallback; } return pj_real(object, name);
}
fn pc_compatible_tick(object, name, old_name) {
    let node = pj_get(object, name); let old = pj_get(object, old_name); let value = 0;
    if node { value = pj_integer(object, name, -2147483648, 2147483647); }
    if old {
        let legacy = pj_integer(object, old_name, -2147483648, 2147483647);
        if node && value != legacy { pj_fail("tick limit conflicts with its legacy spelling"); return 0; } value = legacy;
    }
    if !node && !old { pj_field = name; pj_fail("missing tick limit field"); } return value;
}
fn pc_unsigned(object, name) {
    let node = pj_get(object, name); pj_field = name;
    if pj_kind(node) == 7 { return pj_value(node); }
    if pj_kind(node) != 1 || pj_value(node) < 0 { pj_fail("nonnegative integer expected"); return 0; } return pj_value(node);
}
fn pc_parse(config, root) {
    if pj_kind(root) != 4 { pj_fail("configuration must be a JSON object"); return 1; }
    pb_config_default(config); store64(config, pj_integer(root, "version", 0, 65535));
    let serial = pj_need(root, "serial", 2); let size = pj_count(serial);
    if size > 32 { pj_fail("serial exceeds 32 bytes"); return 1; }
    pb_zero(config + 8, 32); if serial { pb_copy(config + 8, pj_value(serial), size); }
    let drive = pj_need(root, "drive", 4); let out = config + 40;
    pb_vset(out, 0, pj_integer(drive, "left_motor_id", 0, 255));
    pb_vset(out, 1, pj_integer(drive, "right_motor_id", 0, 255));
    pb_vset(out, 2, pj_integer(drive, "steering_servo_id", 0, 255));
    pb_vset(out, 3, pj_integer(drive, "steering_center_deg", 0, 65535));
    pb_vset(out, 4, pj_integer(drive, "steering_range_deg", 0, 65535));
    pb_vset(out, 5, pc_unsigned(drive, "command_timeout_ms"));
    let arm = pj_need(root, "arm", 4); let joints = pj_need(arm, "joints", 3);
    if pj_count(joints) != 4 { pj_fail("arm.joints must contain four entries"); return 1; }
    let i = 0;
    while i < 4 {
        let node = pj_index(joints, i); if pj_kind(node) != 4 { pj_fail("joint calibration must be an object"); return 1; }
        let j = pb_config_joint(config, i);
        pb_vset(j, 0, pj_integer(node, "servo_id", 0, 255));
        pb_vset(j, 1, pc_compatible_tick(node, "tick_min", "soft_tick_min"));
        pb_vset(j, 2, pc_compatible_tick(node, "tick_max", "soft_tick_max"));
        pb_vset(j, 3, pj_integer(node, "reference_tick", -2147483648, 2147483647));
        pb_vset(j, 4, pc_radians(pj_real(node, "reference_angle_deg")));
        if !pc_angle_valid(pb_vget(j, 4)) { pj_fail("reference angle must be within 100 turns"); return 1; }
        pb_vset(j, 5, pj_integer(node, "angle_sign", -128, 127));
        pb_vset(j, 6, pj_integer(node, "drive_sign", -128, 127));
        pb_vset(j, 7, pj_boolean(node, "limit_enabled")); i = i + 1;
    }
    let coordinate = pj_get(root, "coordinate"); out = config + 128;
    if coordinate {
        if pj_kind(coordinate) != 4 { pj_fail("coordinate must be an object"); return 1; }
        pb_vset(out, 0, pj_integer(coordinate, "forward_sign", -128, 127));
        pb_vset(out, 1, pj_integer(coordinate, "left_sign", -128, 127));
        pb_vset(out, 2, pc_optional_int(coordinate, "up_sign", 1, -128, 127));
        pb_vset(out, 3, pc_optional_real(coordinate, "base_yaw_offset_deg", 0));
        pb_vset(out, 4, pc_optional_int(coordinate, "tcp_forward_sign", 1, -128, 127));
        pb_vset(out, 5, pc_optional_int(coordinate, "tcp_left_sign", 1, -128, 127));
        pb_vset(out, 6, pc_optional_int(coordinate, "tcp_up_sign", 1, -128, 127));
    }
    if pj_error { return 1; }
    let error = pb_config_validate(config);
    if error { pj_fail("configuration validation failed"); return error; } return 0;
}
fn pc_load(config, path, input) {
    let n = pl_read_file(path, input, 65536);
    if n == -2 { pb_config_default(config); return 0; }
    if n < 0 { pj_fail("cannot read configuration file"); return n; }
    let root = pj_parse(input, n); if !root { return -22; }
    if pc_parse(config, root) { return -22; } return 1;
}
fn pc_emit(builder, config) {
    pl_text(builder, "{\"version\":"); pl_uint(builder, load64(config)); pl_text(builder, ",\"serial\":");
    let n = 0; while n < 32 && load8(config + 8 + n) { n = n + 1; } pj_quote(builder, config + 8, n);
    let drive = config + 40;
    pl_text(builder, ",\"drive\":{\"left_motor_id\":"); pl_uint(builder, pb_vget(drive, 0));
    pl_text(builder, ",\"right_motor_id\":"); pl_uint(builder, pb_vget(drive, 1));
    pl_text(builder, ",\"steering_servo_id\":"); pl_uint(builder, pb_vget(drive, 2));
    pl_text(builder, ",\"steering_center_deg\":"); pl_uint(builder, pb_vget(drive, 3));
    pl_text(builder, ",\"steering_range_deg\":"); pl_uint(builder, pb_vget(drive, 4));
    pl_text(builder, ",\"command_timeout_ms\":"); pl_uint(builder, pb_vget(drive, 5));
    pl_text(builder, "},\"arm\":{\"joints\":["); let i = 0;
    while i < 4 {
        if i { pl_char(builder, 44); } let j = pb_config_joint(config, i);
        pl_text(builder, "{\"servo_id\":"); pl_uint(builder, pb_vget(j, 0));
        pl_text(builder, ",\"tick_min\":"); pl_int(builder, pb_vget(j, 1));
        pl_text(builder, ",\"tick_max\":"); pl_int(builder, pb_vget(j, 2));
        pl_text(builder, ",\"reference_tick\":"); pl_int(builder, pb_vget(j, 3));
        pl_text(builder, ",\"reference_angle_deg\":"); pl_float(builder, pc_degrees(pb_vget(j, 4)));
        pl_text(builder, ",\"angle_sign\":"); pl_int(builder, pb_vget(j, 5));
        pl_text(builder, ",\"drive_sign\":"); pl_int(builder, pb_vget(j, 6));
        pl_text(builder, ",\"limit_enabled\":"); pj_bool_text(builder, pb_vget(j, 7)); pl_char(builder, 125); i = i + 1;
    }
    let coordinate = config + 128;
    pl_text(builder, "]},\"coordinate\":{\"forward_sign\":"); pl_int(builder, pb_vget(coordinate, 0));
    pl_text(builder, ",\"left_sign\":"); pl_int(builder, pb_vget(coordinate, 1));
    pl_text(builder, ",\"up_sign\":"); pl_int(builder, pb_vget(coordinate, 2));
    pl_text(builder, ",\"base_yaw_offset_deg\":"); pl_float(builder, pb_vget(coordinate, 3));
    pl_text(builder, ",\"tcp_forward_sign\":"); pl_int(builder, pb_vget(coordinate, 4));
    pl_text(builder, ",\"tcp_left_sign\":"); pl_int(builder, pb_vget(coordinate, 5));
    pl_text(builder, ",\"tcp_up_sign\":"); pl_int(builder, pb_vget(coordinate, 6));
    return pl_text(builder, "}}");
}
fn pc_sync(robot, config) {
    let changed = 0; let i = 0;
    while i < 4 {
        let j = pb_joint(robot, i); let c = pb_config_joint(config, i); let k = 0;
        while k < 8 {
            let value = 0;
            if k == 0 { value = pb_j(j, PB_J_ID); }
            if k == 1 { value = pb_j(j, PB_J_MIN); }
            if k == 2 { value = pb_j(j, PB_J_MAX); }
            if k == 3 { value = pb_j(j, PB_J_REFERENCE_TICK); }
            if k == 4 { value = pb_j(j, PB_J_REFERENCE_ANGLE); }
            if k == 5 { value = f64_to_i64_trunc(pb_j(j, PB_J_SIGN)); }
            if k == 6 { value = pb_j(j, PB_J_DRIVE_SIGN); }
            if k == 7 { value = pb_j(j, PB_J_LIMIT_ENABLED); }
            if pb_vget(c, k) != value { changed = 1; pb_vset(c, k, value); } k = k + 1;
        }
        i = i + 1;
    }
    let id = pb_vget(pb_robot_drive(robot), 2);
    if pb_vget(config + 40, 2) != id { changed = 1; pb_vset(config + 40, 2, id); } return changed;
}
