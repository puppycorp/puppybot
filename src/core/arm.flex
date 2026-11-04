import "safety.flex";
import "kinematics.flex";

// Controller errors: 1 joint, 2 servo IDs, 3 limit, 4 missing feedback,
// 5 unreachable, 6 Cartesian joint limits. Zero means success.
fn pb_tick_angle(j, tick) {
    let mid = f64_mul(f64_add(f64_from_i64(pb_j(j, PB_J_RAW_MIN)), f64_from_i64(pb_j(j, PB_J_RAW_MAX))), 0x3fe0000000000000);
    let aligned = pb_align_reference(tick, f64_to_i64_trunc(mid));
    let physical = f64_mul(f64_sub(f64_from_i64(aligned), mid), f64_div(PB_TAU, 0x40b0000000000000));
    return f64_div(f64_sub(physical, pb_j(j, PB_J_ZERO_OFFSET)), pb_j(j, PB_J_SIGN));
}
fn pb_angle_tick(j, angle) {
    let mid = f64_mul(f64_add(f64_from_i64(pb_j(j, PB_J_RAW_MIN)), f64_from_i64(pb_j(j, PB_J_RAW_MAX))), 0x3fe0000000000000);
    let physical = f64_add(f64_mul(pb_j(j, PB_J_SIGN), angle), pb_j(j, PB_J_ZERO_OFFSET));
    return pb_clamp(f64_to_i64_round(f64_add(mid, f64_div(f64_mul(physical, 0x40b0000000000000), PB_TAU))), -2147483648, 2147483647);
}
fn pb_reference_offset(j, tick, angle) {
    let mid = f64_mul(f64_add(f64_from_i64(pb_j(j, PB_J_RAW_MIN)), f64_from_i64(pb_j(j, PB_J_RAW_MAX))), 0x3fe0000000000000);
    let aligned = pb_align_reference(tick, f64_to_i64_trunc(mid));
    let physical = f64_mul(f64_sub(f64_from_i64(aligned), mid), f64_div(PB_TAU, 0x40b0000000000000));
    return f64_sub(physical, f64_mul(pb_j(j, PB_J_SIGN), angle));
}
fn pb_joint_calibrate(j, id, lo, hi, reference, angle, sign, drive_sign) {
    pb_zero(j, 256);
    pb_js(j, PB_J_ID, id); pb_js(j, PB_J_MIN, lo); pb_js(j, PB_J_MAX, hi);
    pb_js(j, PB_J_RAW_MIN, 0); pb_js(j, PB_J_RAW_MAX, 4095);
    pb_js(j, PB_J_SIGN, f64_from_i64(sign)); pb_js(j, PB_J_DRIVE_SIGN, drive_sign);
    pb_js(j, PB_J_REFERENCE_TICK, reference); pb_js(j, PB_J_REFERENCE_ANGLE, angle);
    pb_js(j, PB_J_ZERO_OFFSET, pb_reference_offset(j, reference, angle));
    pb_js(j, PB_J_LIMIT_ENABLED, 1); return 0;
}
fn pb_arm_init(arm, now) {
    pb_zero(arm, 4096);
    pb_as(arm, PB_A_SPEED, 200); pb_as(arm, PB_A_LAST_CMD, now); pb_as(arm, PB_A_LAST_OK, now);
    pb_joint_calibrate(pb_joint(arm, 0), 1, 0, 4095, 2048, 0, 1, 1);
    pb_joint_calibrate(pb_joint(arm, 1), 2, 100, 1000, 530, PB_HALF_PI, -1, 1);
    pb_joint_calibrate(pb_joint(arm, 2), 3, 2200, 3600, 3565, 0, -1, 1);
    pb_joint_calibrate(pb_joint(arm, 3), 4, 500, 3000, 1783, 0, 1, 1);
    let i = 0;
    while i < 4 {
        pb_js(pb_joint(arm, i), PB_J_LAST_FEEDBACK, now); pb_js(pb_joint(arm, i), PB_J_LAST_SPEED_CMD, now);
        store64(pb_wheel_id(arm, i), i + 1); store64(pb_wheel_attempt(arm, i), -1); i = i + 1;
    }
    return 0;
}
fn pb_refresh_angles(j) {
    pb_js(j, PB_J_ANGLE_VALID, 0); pb_js(j, PB_J_TARGET_ANGLE_VALID, 0);
    if pb_j(j, PB_J_TICK_VALID) {
        let angle = pb_tick_angle(j, pb_j(j, PB_J_TICK));
        pb_js(j, PB_J_ANGLE, angle); pb_js(j, PB_J_ANGLE_VALID, f64_is_finite(angle));
    }
    if pb_j(j, PB_J_TARGET_VALID) {
        let angle = pb_tick_angle(j, pb_j(j, PB_J_TARGET));
        pb_js(j, PB_J_TARGET_ANGLE, angle); pb_js(j, PB_J_TARGET_ANGLE_VALID, f64_is_finite(angle));
    }
    return 0;
}
fn pb_arm_feedback(arm, index, tick, now) {
    if index < 0 || index >= 4 { return 1; }
    let j = pb_joint(arm, index); let delta = 0;
    if pb_j(j, PB_J_TICK_VALID) { delta = tick - pb_j(j, PB_J_TICK); }
    if !pb_j(j, PB_J_ONLINE) { store64(pb_wheel_ready(arm, index), 0); }
    pb_js(j, PB_J_TICK, tick); pb_js(j, PB_J_TICK_VALID, 1); pb_js(j, PB_J_DELTA, delta);
    pb_js(j, PB_J_FEEDBACK, 1); pb_js(j, PB_J_ONLINE, 1); pb_js(j, PB_J_LAST_FEEDBACK, now);
    pb_refresh_angles(j); pb_as(arm, PB_A_LAST_OK, now); return 0;
}
fn pb_arm_feedback_error(arm, index) {
    if index < 0 || index >= 4 { return 1; }
    let j = pb_joint(arm, index);
    pb_js(j, PB_J_ONLINE, 0); pb_js(j, PB_J_TICK_VALID, 0); pb_js(j, PB_J_ANGLE_VALID, 0); pb_js(j, PB_J_DELTA, 0);
    store64(pb_wheel_ready(arm, index), 0); return 0;
}
fn pb_arm_temperature(arm, index, valid, value) {
    if index < 0 || index >= 4 { return 1; }
    let j = pb_joint(arm, index); pb_js(j, PB_J_TEMP_VALID, valid); pb_js(j, PB_J_TEMP, value); return 0;
}
fn pb_set_target(j, tick) { pb_js(j, PB_J_TARGET, pb_clip_tick(j, tick)); pb_js(j, PB_J_TARGET_VALID, 1); return pb_refresh_angles(j); }
fn pb_all_targets(arm) {
    let i = 0; while i < 4 { if !pb_j(pb_joint(arm, i), PB_J_TARGET_VALID) { return 0; } i = i + 1; } return 1;
}
fn pb_current_angles(arm, out) {
    let i = 0;
    while i < 4 { let j = pb_joint(arm, i); if !pb_j(j, PB_J_ANGLE_VALID) { return 4; } pb_vset(out, i, pb_j(j, PB_J_ANGLE)); i = i + 1; }
    return 0;
}
fn pb_target_angles(arm, out) {
    let i = 0;
    while i < 4 {
        let j = pb_joint(arm, i);
        if !pb_j(j, PB_J_TARGET_ANGLE_VALID) || !f64_is_finite(pb_j(j, PB_J_TARGET_ANGLE)) { return 4; }
        pb_vset(out, i, pb_j(j, PB_J_TARGET_ANGLE)); i = i + 1;
    }
    return 0;
}
fn pb_target_or_current(arm, out) { if !pb_target_angles(arm, out) { return 0; } return pb_current_angles(arm, out); }
fn pb_explicit_angles(arm, out) {
    if !pb_target_angles(arm, out) { return 0; }
    let any = 0; let i = 0;
    while i < 4 { if pb_j(pb_joint(arm, i), PB_J_TARGET_VALID) { any = 1; } i = i + 1; }
    if !any || pb_current_angles(arm, out) { return 4; }
    i = 0;
    while i < 4 {
        let j = pb_joint(arm, i);
        if pb_j(j, PB_J_TARGET_VALID) { if !pb_j(j, PB_J_TARGET_ANGLE_VALID) { return 4; } pb_vset(out, i, pb_j(j, PB_J_TARGET_ANGLE)); }
        i = i + 1;
    }
    return 0;
}
fn pb_arm_coords(arm, out, target) {
    if target && pb_a(arm, PB_A_MODE) == 3 { pb_copy(out, arm + PB_A_X * 8, 24); return 0; }
    let angles = arm + 1900;
    let error = 0; if target { error = pb_explicit_angles(arm, angles); } else { error = pb_current_angles(arm, angles); }
    if error { return error; } return pb_fk_vector(out, angles);
}
fn pb_refresh_mode(arm) {
    if pb_a(arm, PB_A_ERROR) { pb_as(arm, PB_A_MODE, 5); return 0; }
    if pb_a(arm, PB_A_MODE) == 3 { return 0; }
    if pb_all_targets(arm) {
        let i = 0; while i < 4 { store64(arm + 304 + i * 8, pb_j(pb_joint(arm, i), PB_J_TARGET)); i = i + 1; }
        pb_as(arm, PB_A_MODE, 2); return 0;
    }
    let i = 0;
    while i < 4 {
        let j = pb_joint(arm, i);
        if !pb_j(j, PB_J_TARGET_VALID) && pb_j(j, PB_J_SPEED) { store64(arm + 336, i); store64(arm + 344, pb_sign(pb_j(j, PB_J_SPEED))); pb_as(arm, PB_A_MODE, 1); return 0; } i = i + 1;
    }
    pb_as(arm, PB_A_MODE, 0); return 0;
}
fn pb_arm_stop(arm, now) { let i = 0; while i < 4 { pb_joint_stop(pb_joint(arm, i)); i = i + 1; } pb_as(arm, PB_A_LAST_CMD, now); return 0; }
fn pb_goto_ticks(arm, ticks, now) {
    pb_copy(arm + 304, ticks, 32);
    let i = 0; while i < 4 { let j = pb_joint(arm, i); pb_clear_fault(j); pb_set_target(j, pb_vget(ticks, i)); i = i + 1; }
    pb_as(arm, PB_A_LAST_CMD, now); pb_as(arm, PB_A_MODE, 2); return 0;
}
fn pb_angles_ticks(arm, out, angles, canonical) {
    let i = 0; while i < 4 { let tick = pb_angle_tick(pb_joint(arm, i), pb_vget(angles, i)); if canonical { tick = pb_canonical(tick); } pb_vset(out, i, tick); i = i + 1; } return 0;
}
fn pb_ticks_within(arm, ticks) {
    let i = 0; while i < 4 { if !pb_tick_within(pb_joint(arm, i), pb_vget(ticks, i)) { return 0; } i = i + 1; } return 1;
}
fn pb_goto_angles(arm, angles, now, checked) {
    let i = 0; while i < 4 { if !f64_is_finite(pb_vget(angles, i)) { return 3; } i = i + 1; }
    let ticks = arm + 2200; pb_angles_ticks(arm, ticks, angles, checked);
    if checked && !pb_ticks_within(arm, ticks) { pb_copy(arm + 272, ticks, 32); return 6; }
    return pb_goto_ticks(arm, ticks, now);
}
fn pb_nearest_branch(arm, out, x, y, z, pitch, current) {
    let candidate = arm + 2048; let ticks = arm + 2088; let best = arm + 2120; let limited = arm + 2152;
    let valid_found = 0; let limited_found = 0; let valid_score = 0; let limited_score = 0;
    let i = 0;
    while i < 4 {
        let radial = PB_ONE; let elbow = PB_ONE;
        if i >= 2 { radial = pb_neg(PB_ONE); } if i % 2 { elbow = pb_neg(PB_ONE); }
        if pb_ik_branch(candidate, x, y, z, pitch, radial, elbow) {
            let score = 0; if current { score = pb_continuity(current, candidate); }
            pb_angles_ticks(arm, ticks, candidate, 1);
            if pb_ticks_within(arm, ticks) {
                if !valid_found || f64_lt(score, valid_score) { valid_found = 1; valid_score = score; pb_copy(best, candidate, 32); }
            } else {
                if !limited_found || f64_lt(score, limited_score) { limited_found = 1; limited_score = score; pb_copy(limited, ticks, 32); }
            }
        }
        i = i + 1;
    }
    if valid_found { pb_copy(out, best, 32); return 0; }
    if limited_found { pb_copy(arm + 272, limited, 32); return 6; } return 5;
}
fn pb_goto_coords(arm, x, y, z, pitch, now) {
    let current = arm + 1536; if pb_current_angles(arm, current) { current = 0; }
    let angles = arm + 1568; let error = pb_nearest_branch(arm, angles, x, y, z, pitch, current);
    if error { return error; } return pb_goto_angles(arm, angles, now, 1);
}
fn pb_move_tcp(arm, frame, dx, dy, dz, now) {
    let current = arm + 1536; let error = pb_target_or_current(arm, current); if error { return error; }
    let coords = arm + 1600; let delta = arm + 1624; let angles = arm + 1568;
    let pitch = pb_tool_pitch(pb_vget(current, 1), pb_vget(current, 2), pb_vget(current, 3));
    pb_fk_vector(coords, current); pb_delta_base(delta, current, frame, dx, dy, dz);
    error = pb_nearest_branch(arm, angles, f64_add(pb_vget(coords, 0), pb_vget(delta, 0)), f64_add(pb_vget(coords, 1), pb_vget(delta, 1)), f64_add(pb_vget(coords, 2), pb_vget(delta, 2)), pitch, current);
    if error { return error; }
    error = pb_goto_angles(arm, angles, now, 1); if error { return error; }
    if (frame == 0 || frame == 2) && f64_le(f64_magnitude(dx), PB_EPSILON) && f64_le(f64_magnitude(dy), PB_EPSILON) { pb_set_target(pb_joint(arm, 0), pb_angle_tick(pb_joint(arm, 0), pb_vget(current, 0))); }
    return pb_target_angles(arm, angles);
}
fn pb_start_jog(arm, frame, direction, override_valid, speed, now) {
    let i = 0; while i < 3 { if !f64_is_finite(pb_vget(direction, i)) { return 3; } i = i + 1; }
    let length = pb_length3(direction); if f64_le(length, PB_EPSILON) { return 3; }
    let current = arm + 1536; let error = pb_target_or_current(arm, current); if error { return error; }
    let held = 0;
    if pb_a(arm, PB_A_MODE) == 3 {
        pb_copy(current, arm + PB_A_YAW * 8, 32);
        held = f64_eq(pb_a(arm, PB_A_DX), 0) && f64_eq(pb_a(arm, PB_A_DY), 0) && f64_eq(pb_a(arm, PB_A_DZ), 0);
    } else {
        pb_copy(arm + PB_A_YAW * 8, current, 32); pb_fk_vector(arm + PB_A_X * 8, current);
        pb_as(arm, PB_A_PITCH, pb_tool_pitch(pb_vget(current, 1), pb_vget(current, 2), pb_vget(current, 3)));
    }
    let normalized = arm + 1600; i = 0;
    while i < 3 { pb_vset(normalized, i, f64_div(pb_vget(direction, i), length)); i = i + 1; }
    let delta = arm + 1624;
    if frame == 2 { pb_delta_base(delta, current, 2, pb_vget(normalized, 0), pb_vget(normalized, 1), pb_vget(normalized, 2)); pb_copy(normalized, delta, 24); frame = 0; }
    if held { pb_zero(normalized, 24); }
    pb_copy(arm + PB_A_DX * 8, normalized, 24); pb_as(arm, PB_A_FRAME, frame);
    pb_as(arm, PB_A_OVERRIDE_VALID, override_valid); pb_as(arm, PB_A_OVERRIDE_SPEED, speed);
    pb_as(arm, PB_A_LAST_STEP, now); pb_as(arm, PB_A_LAST_CMD, now); pb_as(arm, PB_A_MODE, 3); return 0;
}
fn pb_lead_fraction(current, target, delta) {
    let x = f64_sub(pb_vget(target, 0), pb_vget(current, 0));
    let y = f64_sub(pb_vget(target, 1), pb_vget(current, 1));
    let z = f64_sub(pb_vget(target, 2), pb_vget(current, 2));
    if f64_ge(f64_sqrt(f64_add(f64_add(f64_mul(x, x), f64_mul(y, y)), f64_mul(z, z))), 0x4020000000000000) { return 0; }
    let cx = f64_add(x, pb_vget(delta, 0)); let cy = f64_add(y, pb_vget(delta, 1)); let cz = f64_add(z, pb_vget(delta, 2));
    if f64_le(f64_sqrt(f64_add(f64_add(f64_mul(cx, cx), f64_mul(cy, cy)), f64_mul(cz, cz))), 0x4020000000000000) { return PB_ONE; }
    let lo = 0; let hi = PB_ONE; let i = 0;
    while i < 20 {
        let f = f64_mul(f64_add(lo, hi), 0x3fe0000000000000); cx = f64_add(x, f64_mul(pb_vget(delta, 0), f)); cy = f64_add(y, f64_mul(pb_vget(delta, 1), f)); cz = f64_add(z, f64_mul(pb_vget(delta, 2), f));
        if f64_le(f64_sqrt(f64_add(f64_add(f64_mul(cx, cx), f64_mul(cy, cy)), f64_mul(cz, cz))), 0x4020000000000000) { lo = f; } else { hi = f; } i = i + 1;
    }
    return lo;
}
fn pb_advance_jog(arm, now) {
    if pb_a(arm, PB_A_MODE) != 3 { return 0; }
    let elapsed = pb_elapsed(now, pb_a(arm, PB_A_LAST_STEP)); if !elapsed { return 0; }
    pb_as(arm, PB_A_LAST_STEP, now);
    if f64_eq(pb_a(arm, PB_A_DX), 0) && f64_eq(pb_a(arm, PB_A_DY), 0) && f64_eq(pb_a(arm, PB_A_DZ), 0) { return 0; }
    let speed = f64_from_i64(pb_abs(pb_a(arm, PB_A_SPEED))); if pb_a(arm, PB_A_OVERRIDE_VALID) { speed = pb_a(arm, PB_A_OVERRIDE_SPEED); }
    let step = f64_div(f64_mul(speed, f64_from_i64(elapsed)), 0x408f400000000000);
    let delta = arm + 2304; let current = arm + 2328; let coords = arm + 2360; let next = arm + 2384;
    let solved = arm + 2416; let boundary = arm + 2448; let boundary_angles = arm + 2472;
    let frame = pb_a(arm, PB_A_FRAME);
    if frame == 1 { pb_delta_base(delta, arm + PB_A_YAW * 8, 1, f64_mul(pb_a(arm, PB_A_DX), step), f64_mul(pb_a(arm, PB_A_DY), step), f64_mul(pb_a(arm, PB_A_DZ), step)); }
    else { pb_vset(delta, 0, f64_mul(pb_a(arm, PB_A_DX), step)); pb_vset(delta, 1, f64_mul(pb_a(arm, PB_A_DY), step)); pb_vset(delta, 2, f64_mul(pb_a(arm, PB_A_DZ), step)); }
    if pb_current_angles(arm, current) { return 0; } pb_fk_vector(coords, current);
    let fraction = pb_lead_fraction(coords, arm + PB_A_X * 8, delta); if f64_le(fraction, PB_EPSILON) { return 0; }
    let i = 0; while i < 3 { pb_vset(delta, i, f64_mul(pb_vget(delta, i), fraction)); pb_vset(next, i, f64_add(pb_a(arm, PB_A_X + i), pb_vget(delta, i))); i = i + 1; }
    let error = pb_nearest_branch(arm, solved, pb_vget(next, 0), pb_vget(next, 1), pb_vget(next, 2), pb_a(arm, PB_A_PITCH), arm + PB_A_YAW * 8);
    if !error { error = pb_goto_angles(arm, solved, now, 1); }
    if !error { pb_copy(arm + PB_A_YAW * 8, solved, 32); pb_copy(arm + PB_A_X * 8, next, 24); pb_as(arm, PB_A_MODE, 3); return 0; }
    if error != 5 && error != 6 { pb_as(arm, PB_A_MODE, 0); pb_refresh_mode(arm); return 0; }
    let lo = 0; let hi = PB_ONE;
    pb_copy(boundary, arm + PB_A_X * 8, 24); pb_copy(boundary_angles, arm + PB_A_YAW * 8, 32);
    i = 0;
    while i < 14 {
        fraction = f64_mul(f64_add(lo, hi), 0x3fe0000000000000); let k = 0;
        while k < 3 { pb_vset(next, k, f64_add(pb_a(arm, PB_A_X + k), f64_mul(pb_vget(delta, k), fraction))); k = k + 1; }
        error = pb_nearest_branch(arm, solved, pb_vget(next, 0), pb_vget(next, 1), pb_vget(next, 2), pb_a(arm, PB_A_PITCH), arm + PB_A_YAW * 8);
        if !error { error = pb_goto_angles(arm, solved, now, 1); }
        if !error { lo = fraction; pb_copy(boundary, next, 24); pb_copy(boundary_angles, solved, 32); }
        else if error == 5 || error == 6 { hi = fraction; } else { i = 14; }
        i = i + 1;
    }
    if f64_gt(lo, 0) { pb_copy(arm + PB_A_YAW * 8, boundary_angles, 32); pb_copy(arm + PB_A_X * 8, boundary, 24); pb_zero(arm + PB_A_DX * 8, 24); pb_as(arm, PB_A_MODE, 3); }
    else { pb_as(arm, PB_A_MODE, 0); pb_refresh_mode(arm); }
    return 0;
}
fn pb_arm_update(arm, now, commands) {
    pb_advance_jog(arm, now);
    let retain = pb_a(arm, PB_A_MODE) == 3 && pb_all_targets(arm); let saved = arm + 1800; let i = 0;
    if retain { while i < 4 { pb_vset(saved, i, pb_j(pb_joint(arm, i), PB_J_TARGET)); i = i + 1; } }
    let reason = pb_deadman(arm, now);
    if reason { pb_as(arm, PB_A_ERROR, reason); i = 0; while i < 4 { pb_joint_stop(pb_joint(arm, i)); i = i + 1; } }
    i = 0;
    while i < 4 {
        let j = pb_joint(arm, i); let speed = pb_safe_speed(j, pb_a(arm, PB_A_SPEED), now);
        pb_vset(commands + i * 24, 0, pb_j(j, PB_J_ID)); pb_vset(commands + i * 24, 1, speed);
        pb_vset(commands + i * 24, 2, !pb_j(j, PB_J_SENT_VALID) || pb_j(j, PB_J_SENT_SPEED) != speed); i = i + 1;
    }
    if !pb_a(arm, PB_A_ERROR) && retain { i = 0; while i < 4 { pb_set_target(pb_joint(arm, i), pb_vget(saved, i)); i = i + 1; } }
    pb_refresh_mode(arm); return 0;
}
fn pb_arm_mode_result(arm, index, id, wheel, success) {
    if index < 0 || index >= 4 || !wheel { return 0; }
    store64(pb_wheel_ready(arm, index), success && pb_j(pb_joint(arm, index), PB_J_ID) == id); return 0;
}
fn pb_arm_speed_result(arm, index, id, speed, success, now) {
    if index < 0 || index >= 4 { return 1; }
    let j = pb_joint(arm, index);
    if success { pb_js(j, PB_J_SENT_VALID, 1); pb_js(j, PB_J_SENT_SPEED, speed); pb_js(j, PB_J_LAST_SPEED_CMD, now); }
    else { store64(pb_wheel_ready(arm, index), 0); }
    if pb_j(j, PB_J_ID) != id { store64(pb_wheel_ready(arm, index), 0); } return 0;
}
fn pb_begin_wheel(arm, index, id, now, force) {
    if index < 0 || index >= 4 { return 0; }
    if load64(pb_wheel_id(arm, index)) == id && load64(pb_wheel_ready(arm, index)) { return 0; }
    let before = load64(pb_wheel_attempt(arm, index));
    if !force && before != -1 && pb_elapsed(now, before) < 1000 { return 0; }
    store64(pb_wheel_attempt(arm, index), now); return 1;
}
fn pb_arm_command(arm, command, values, now) {
    let a = pb_vget(values, 0); let b = pb_vget(values, 1); let c = pb_vget(values, 2); let d = pb_vget(values, 3);
    if command == 1 { if a == -32768 { return 3; } pb_as(arm, PB_A_SPEED, pb_abs(a)); pb_as(arm, PB_A_LAST_CMD, now); return 0; }
    if command == 4 || command == 11 { pb_arm_stop(arm, now); pb_as(arm, PB_A_MODE, 0); return 0; }
    if command == 5 { return pb_goto_ticks(arm, values, now); }
    if command == 6 { return pb_goto_angles(arm, values, now, 0); }
    if command == 7 { return pb_goto_coords(arm, a, b, c, d, now); }
    if command == 8 { return pb_move_tcp(arm, a, b, c, d, now); }
    if command == 9 || command == 10 {
        if command == 10 && (!f64_is_finite(pb_vget(values, 4)) || f64_le(pb_vget(values, 4), 0)) { return 3; }
        return pb_start_jog(arm, a, values + 8, command == 10, pb_vget(values, 4), now);
    }
    if command == 12 || command == 13 || command == 14 || command == 16 {
        if (command == 14 || command == 16) && !f64_is_finite(b) { return 3; }
        if command == 16 && c == -32768 { return 3; }
        let index = a;
        if command == 16 {
            index = -1; let i = 0; while i < 4 { if index < 0 && pb_j(pb_joint(arm, i), PB_J_ID) == a { index = i; } i = i + 1; }
            if index < 0 { return 1; } pb_as(arm, PB_A_SPEED, pb_abs(c)); pb_as(arm, PB_A_LAST_CMD, now);
        }
        if command != 12 && (index < 0 || index >= 4) { return 1; }
        let ticks = arm + 1536; let i = 0;
        while i < 4 { let j = pb_joint(arm, i); if !pb_j(j, PB_J_TICK_VALID) { return 4; } pb_vset(ticks, i, pb_j(j, PB_J_TICK)); i = i + 1; }
        if command == 13 { pb_vset(ticks, index, b); }
        if command == 14 || command == 16 { pb_vset(ticks, index, pb_angle_tick(pb_joint(arm, index), b)); }
        let error = pb_goto_ticks(arm, ticks, now); if command == 12 { pb_as(arm, PB_A_MODE, 4); } return error;
    }
    if command == 19 {
        if a >= 4 || a < -1 { return 1; }
        let i = 0; while i < 4 { if a == -1 || a == i { pb_clear_fault(pb_joint(arm, i)); } i = i + 1; }
        if a == -1 { pb_as(arm, PB_A_ERROR, 0); } pb_refresh_mode(arm); return 0;
    }
    if command == 20 {
        let i = 0; while i < 4 { if pb_vget(values, i) < 1 || pb_vget(values, i) > 253 { return 2; } i = i + 1; }
        i = 0; while i < 4 {
            pb_js(pb_joint(arm, i), PB_J_ID, pb_vget(values, i)); store64(pb_wheel_id(arm, i), pb_vget(values, i));
            store64(pb_wheel_ready(arm, i), 0); store64(pb_wheel_attempt(arm, i), -1); i = i + 1;
        }
        pb_as(arm, PB_A_INITIALIZED, 0); return 0;
    }
    if a < 0 || a >= 4 { return 1; } let j = pb_joint(arm, a);
    if command == 2 { store64(arm + 336, a); store64(arm + 344, pb_sign(b)); pb_clear_fault(j); pb_clear_target(j); pb_js(j, PB_J_SPEED, pb_sign(b)*pb_abs(pb_a(arm, PB_A_SPEED))); pb_as(arm, PB_A_LAST_CMD, now); pb_as(arm, PB_A_MODE, b != 0); return 0; }
    if command == 3 { pb_joint_stop(j); pb_as(arm, PB_A_LAST_CMD, now); pb_refresh_mode(arm); return 0; }
    if command == 15 {
        if !f64_is_finite(c) || b < 0 || b >= 4096 { return 3; }
        pb_arm_stop(arm, now); pb_as(arm, PB_A_MODE, 0); pb_js(j, PB_J_REFERENCE_TICK, b); pb_js(j, PB_J_REFERENCE_ANGLE, c);
        pb_js(j, PB_J_ZERO_OFFSET, pb_reference_offset(j, b, c)); pb_refresh_angles(j); return 0;
    }
    if command == 17 { if b == c { return 3; } pb_js(j, PB_J_MIN, b); pb_js(j, PB_J_MAX, c); return 0; }
    if command == 18 { pb_js(j, PB_J_LIMIT_ENABLED, b != 0); return 0; }
    return 3;
}

// Export the complete tagged mode value into at least 128 caller-owned bytes.
// The returned length is in words; the first word is the mode tag.
fn pb_arm_mode_words(arm, out) {
    let mode = pb_a(arm, PB_A_MODE); store64(out, mode);
    if mode == 1 { store64(out + 8, load64(arm + 336)); store64(out + 16, load64(arm + 344)); return 3; }
    if mode == 2 || mode == 4 { pb_copy(out + 8, arm + 304, 32); return 5; }
    if mode == 3 {
        store64(out + 8, pb_a(arm, PB_A_FRAME)); pb_copy(out + 16, arm + PB_A_DX * 8, 24);
        store64(out + 40, pb_a(arm, PB_A_OVERRIDE_VALID)); let speed = 0;
        if pb_a(arm, PB_A_OVERRIDE_VALID) { speed = pb_a(arm, PB_A_OVERRIDE_SPEED); }
        store64(out + 48, speed); store64(out + 56, pb_a(arm, PB_A_LAST_STEP));
        pb_copy(out + 64, arm + PB_A_YAW * 8, 32); pb_copy(out + 96, arm + PB_A_X * 8, 24);
        store64(out + 120, pb_a(arm, PB_A_PITCH)); return 16;
    }
    return 1;
}

fn pb_arm_effective_coords(arm, out) {
    if !pb_arm_coords(arm, out, 1) { return 0; } return pb_arm_coords(arm, out, 0);
}
