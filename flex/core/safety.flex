import "layout.flex";

// Platforms may choose a shorter command lease before starting the controller.
global pb_command_timeout_ms = 1000;

// Fault IDs: 1 over_temp, 2 no_feedback, 3 stale_feedback, 4 stall,
// 5 deadman_feedback, 6 deadman_command. Zero means no fault.
fn pb_mod(n, m) { let r = n % m; if r < 0 { r = r + m; } return r; }
fn pb_canonical(tick) { return pb_mod(tick, 4096); }
fn pb_limit_hi(j) { let hi = pb_j(j, PB_J_MAX); if pb_j(j, PB_J_MIN) > hi { hi = hi + 4096; } return hi; }
fn pb_distance_interval(tick, lo, hi) { if tick < lo { return lo - tick; } if tick > hi { return tick - hi; } return 0; }
fn pb_align_reference(tick, reference) {
    let best = tick; let distance = pb_abs(tick - reference); let k = -2;
    while k <= 2 {
        let candidate = tick + k * 4096; let d = pb_abs(candidate - reference);
        if d < distance { best = candidate; distance = d; } k = k + 1;
    }
    return best;
}
fn pb_align_interval(tick, lo, hi) {
    let best = tick; let distance = pb_distance_interval(tick, lo, hi); let offset = 0; let k = -2;
    while k <= 2 {
        let candidate = tick + k * 4096;
        let d = pb_distance_interval(candidate, lo, hi); let o = pb_abs(candidate - tick);
        if d < distance || (d == distance && o < offset) { best = candidate; distance = d; offset = o; }
        k = k + 1;
    }
    return best;
}
fn pb_plain_interval(j) {
    let lo = pb_j(j, PB_J_MIN); let hi = pb_j(j, PB_J_MAX);
    return lo >= 0 && lo <= hi && hi < 4096 && !(lo == 0 && hi == 4095);
}
fn pb_clip_tick(j, tick) {
    if !pb_j(j, PB_J_LIMIT_ENABLED) { return tick; }
    let lo = pb_j(j, PB_J_MIN); let hi = pb_j(j, PB_J_MAX);
    if pb_plain_interval(j) { return pb_clamp(tick, lo, hi); }
    hi = pb_limit_hi(j); return pb_clamp(pb_align_interval(tick, lo, hi), lo, hi);
}
fn pb_tick_within(j, tick) {
    if !pb_j(j, PB_J_LIMIT_ENABLED) { return 1; }
    let lo = pb_j(j, PB_J_MIN); let hi = pb_j(j, PB_J_MAX);
    if pb_plain_interval(j) { return lo <= tick && tick <= hi; }
    hi = pb_limit_hi(j); tick = pb_align_interval(tick, lo, hi); return lo <= tick && tick <= hi;
}
fn pb_target_error(target, current) {
    let naive = target - current; if pb_abs(naive) <= 8 { return naive; }
    let wrapped = pb_mod(target - current + 2048, 4096) - 2048;
    if pb_abs(wrapped) <= 8 || pb_abs(wrapped) + 8 < pb_abs(naive) { return wrapped; } return naive;
}
fn pb_limited_error(j, target, current) {
    let lo = pb_j(j, PB_J_MIN); let hi = pb_j(j, PB_J_MAX);
    if pb_plain_interval(j) { return pb_clamp(target, lo, hi) - pb_clamp(current, lo, hi); }
    hi = pb_limit_hi(j); return pb_align_interval(target, lo, hi) - pb_align_interval(current, lo, hi);
}
fn pb_limit_blocks(j, speed) {
    if !pb_j(j, PB_J_LIMIT_ENABLED) || !speed || !pb_j(j, PB_J_TICK_VALID) { return 0; }
    let lo = pb_j(j, PB_J_MIN); let hi = pb_limit_hi(j);
    let tick = pb_align_interval(pb_j(j, PB_J_TICK), lo, hi);
    if tick < lo { return speed < 0; } if tick > hi { return speed > 0; }
    return (speed > 0 && tick >= hi) || (speed < 0 && tick <= lo);
}
fn pb_clear_target(j) { pb_js(j, PB_J_TARGET_VALID, 0); pb_js(j, PB_J_TARGET_ANGLE_VALID, 0); return 0; }
fn pb_joint_stop(j) { pb_clear_target(j); pb_js(j, PB_J_SPEED, 0); return 0; }
fn pb_clear_fault(j) { pb_js(j, PB_J_FAULT, 0); pb_js(j, PB_J_STALL_VALID, 0); return 0; }
fn pb_requested_speed(j, speed) {
    if pb_j(j, PB_J_TARGET_VALID) {
        if !pb_j(j, PB_J_TICK_VALID) { return 0; }
        let error = pb_target_error(pb_j(j, PB_J_TARGET), pb_j(j, PB_J_TICK));
        if pb_j(j, PB_J_LIMIT_ENABLED) { error = pb_limited_error(j, pb_j(j, PB_J_TARGET), pb_j(j, PB_J_TICK)); }
        if pb_abs(error) <= 8 { pb_clear_target(j); return 0; }
        let magnitude = pb_abs(speed);
        if magnitude > 0 && pb_abs(error) < 80 { magnitude = pb_max(pb_min(magnitude, 20), magnitude * pb_abs(error) / 80); }
        return pb_sign(error) * magnitude * pb_j(j, PB_J_DRIVE_SIGN);
    }
    return pb_sign(pb_j(j, PB_J_SPEED)) * pb_abs(speed);
}
fn pb_safety_fault(j, requested, now) {
    if pb_j(j, PB_J_TEMP_VALID) && pb_j(j, PB_J_TEMP) > 80 { pb_js(j, PB_J_STALL_VALID, 0); return 1; }
    if !pb_j(j, PB_J_LIMIT_ENABLED) { pb_js(j, PB_J_STALL_VALID, 0); return 0; }
    if !pb_j(j, PB_J_TICK_VALID) { pb_js(j, PB_J_STALL_VALID, 0); return 2; }
    if pb_elapsed(now, pb_j(j, PB_J_LAST_FEEDBACK)) > 250 { pb_js(j, PB_J_STALL_VALID, 0); return 3; }
    if pb_abs(requested) >= 80 && !pb_j(j, PB_J_DELTA) {
        if pb_j(j, PB_J_STALL_VALID) {
            let trip = 1250; if pb_j(j, PB_J_TARGET_VALID) { trip = 350; }
            if pb_elapsed(now, pb_j(j, PB_J_STALL_SINCE)) >= trip { return 4; }
        } else { pb_js(j, PB_J_STALL_VALID, 1); pb_js(j, PB_J_STALL_SINCE, now); }
    } else { pb_js(j, PB_J_STALL_VALID, 0); }
    return 0;
}
fn pb_govern_speed(j, requested, now) {
    if !requested { pb_js(j, PB_J_STALL_VALID, 0); return 0; }
    let fault = pb_safety_fault(j, requested, now);
    if fault { pb_js(j, PB_J_FAULT, fault); return 0; }
    if pb_j(j, PB_J_FAULT) { return 0; }
    if !pb_j(j, PB_J_TICK_VALID) || !pb_j(j, PB_J_LIMIT_ENABLED) { return requested; }
    if !pb_limit_blocks(j, requested) { return requested; }
    if pb_j(j, PB_J_TARGET_VALID) && !pb_limit_blocks(j, -requested) { return -requested; }
    return 0;
}
fn pb_slowdown(j, requested) {
    if !requested || !pb_j(j, PB_J_LIMIT_ENABLED) || !pb_j(j, PB_J_TICK_VALID) { return requested; }
    let lo = pb_j(j, PB_J_MIN); let hi = pb_limit_hi(j); let tick = pb_align_interval(pb_j(j, PB_J_TICK), lo, hi);
    let distance = tick - lo; if requested > 0 { distance = hi - tick; }
    if distance <= 0 { return 0; } if distance >= 120 { return requested; }
    let magnitude = pb_abs(requested); return pb_sign(requested) * pb_clamp(magnitude * distance / 120, 1, magnitude);
}
fn pb_slew(j, desired, now) {
    if !pb_j(j, PB_J_SENT_VALID) { return desired; }
    let previous = pb_j(j, PB_J_SENT_SPEED);
    if desired == previous || desired == 0 { return desired; }
    let dt = pb_max(pb_elapsed(now, pb_j(j, PB_J_LAST_SPEED_CMD)), 50);
    let rate = 6000; if pb_abs(desired) > pb_abs(previous) { rate = 4000; }
    let delta = rate * dt / 1000; return previous + pb_clamp(desired - previous, -delta, delta);
}
fn pb_safe_speed(j, speed, now) {
    let requested = pb_requested_speed(j, speed); let safe = pb_govern_speed(j, requested, now);
    let maximum = pb_abs(speed);
    if !maximum { safe = 0; } else if pb_abs(safe) > maximum { safe = pb_sign(safe) * maximum; }
    if pb_j(j, PB_J_TARGET_VALID) { safe = pb_slowdown(j, safe); safe = pb_slew(j, safe, now); }
    pb_js(j, PB_J_SPEED, safe); return safe;
}
fn pb_deadman(arm, now) {
    if pb_elapsed(now, pb_a(arm, PB_A_LAST_OK)) > 200 { return 5; }
    let active = 0; let i = 0;
    while i < 4 {
        let j = pb_joint(arm, i);
        if !pb_j(j, PB_J_TARGET_VALID) && (pb_j(j, PB_J_SPEED) || (pb_j(j, PB_J_SENT_VALID) && pb_j(j, PB_J_SENT_SPEED))) { active = 1; }
        i = i + 1;
    }
    if active && pb_elapsed(now, pb_a(arm, PB_A_LAST_CMD)) > pb_command_timeout_ms { return 6; }
    return 0;
}
