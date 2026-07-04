use super::types::Joint;

pub const TICK_WRAP: i32 = 4096;

pub const YAW_TICK_MIN: i32 = 0;
pub const YAW_TICK_MAX: i32 = 4095;
pub const SHOULDER_TICK_MIN: i32 = 100;
pub const SHOULDER_TICK_MAX: i32 = 1000;
pub const ELBOW_TICK_MIN: i32 = 2200;
pub const ELBOW_TICK_MAX: i32 = 3600;
pub const TIP_TICK_MIN: i32 = 500;
pub const TIP_TICK_MAX: i32 = 3000;

pub const TARGET_TICK_DEADBAND: i32 = 8;
pub const TARGET_TICK_APPROACH_WINDOW: i32 = 80;
pub const TARGET_TICK_MIN_APPROACH_SPEED: i16 = 20;
pub const DEADMAN_FEEDBACK_TIMEOUT_MS: u64 = 200;
pub const DEADMAN_CMD_TIMEOUT_MS: u64 = 1000;
pub const JOINT_FEEDBACK_TIMEOUT_MS: u64 = 250;
pub const MAX_TEMP_C: u8 = 80;
pub const STALL_SPEED_MIN: i16 = 80;
pub const STALL_TRIP_MS: u64 = 350;
pub const STALL_TRIP_FREE_SPIN_MS: u64 = 1250;
pub const SPEED_ACCEL_LIMIT_PER_S: i32 = 4000;
pub const SPEED_DECEL_LIMIT_PER_S: i32 = 6000;
pub const LIMIT_SLOWDOWN_WINDOW_TICKS: i32 = 120;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum SafetyFault {
    OverTemperature,
    FeedbackUnavailable,
    FeedbackStale,
    Stall,
    DeadmanFeedbackStale,
    DeadmanCommandStale,
}

fn distance_to_interval(value: i32, lo: i32, hi: i32) -> i32 {
    if value < lo {
        lo - value
    } else if value > hi {
        value - hi
    } else {
        0
    }
}

fn positive_mod(value: i32, modulus: i32) -> i32 {
    let value = value % modulus;
    if value < 0 { value + modulus } else { value }
}

pub fn continuous_tick_interval(min_tick: i32, max_tick: i32) -> (i32, i32) {
    if min_tick <= max_tick {
        (min_tick, max_tick)
    } else {
        (min_tick, max_tick + TICK_WRAP)
    }
}

pub fn align_tick_to_reference(tick: i32, reference: i32) -> i32 {
    let mut best = tick;
    let mut best_distance = (tick - reference).abs();
    let mut k = -2;
    while k <= 2 {
        let candidate = tick + k * TICK_WRAP;
        let distance = (candidate - reference).abs();
        if distance < best_distance {
            best = candidate;
            best_distance = distance;
        }
        k += 1;
    }
    best
}

pub fn align_tick_to_interval(tick: i32, lo: i32, hi: i32) -> i32 {
    let mut best = tick;
    let mut best_distance = distance_to_interval(tick, lo, hi);
    let mut best_offset_distance = 0;
    let mut k = -2;
    while k <= 2 {
        let candidate = tick + k * TICK_WRAP;
        let distance = distance_to_interval(candidate, lo, hi);
        let offset_distance = (candidate - tick).abs();
        if distance < best_distance
            || (distance == best_distance && offset_distance < best_offset_distance)
        {
            best = candidate;
            best_distance = distance;
            best_offset_distance = offset_distance;
        }
        k += 1;
    }
    best
}

pub fn clip_tick_to_joint_limits(joint: &Joint, tick: i32) -> i32 {
    if !joint.limit_enabled {
        return tick;
    }

    let (lo, hi) = continuous_tick_interval(joint.tick_min, joint.tick_max);
    align_tick_to_interval(tick, lo, hi).clamp(lo, hi)
}

pub fn tick_within_joint_limits(joint: &Joint, tick: i32) -> bool {
    if !joint.limit_enabled {
        return true;
    }

    let (lo, hi) = continuous_tick_interval(joint.tick_min, joint.tick_max);
    let tick = align_tick_to_interval(tick, lo, hi);
    lo <= tick && tick <= hi
}

pub fn target_tick_error(target_tick: i32, current_tick: i32) -> i32 {
    let naive_error = target_tick - current_tick;
    if naive_error.abs() <= TARGET_TICK_DEADBAND {
        return naive_error;
    }

    let half_wrap = TICK_WRAP / 2;
    let wrapped_error = positive_mod(target_tick - current_tick + half_wrap, TICK_WRAP) - half_wrap;
    if wrapped_error.abs() <= TARGET_TICK_DEADBAND
        || wrapped_error.abs() + TARGET_TICK_DEADBAND < naive_error.abs()
    {
        return wrapped_error;
    }

    naive_error
}

pub fn target_tick_error_limited(joint: &Joint, target_tick: i32, current_tick: i32) -> i32 {
    let (lo, hi) = continuous_tick_interval(joint.tick_min, joint.tick_max);
    let current = align_tick_to_interval(current_tick, lo, hi);
    let target = align_tick_to_interval(target_tick, lo, hi);
    target - current
}

pub fn is_outside_limits(joint: &Joint) -> bool {
    let Some(tick) = joint.tick else {
        return false;
    };
    !tick_within_joint_limits(joint, tick)
}

pub fn limit_blocks_for_speed(joint: &Joint, speed: i16) -> bool {
    if !joint.limit_enabled || speed == 0 {
        return false;
    }

    let Some(tick) = joint.tick else {
        return false;
    };

    let direction = speed.signum() as i32;
    let (lo, hi) = continuous_tick_interval(joint.tick_min, joint.tick_max);
    let tick = align_tick_to_interval(tick, lo, hi);

    if tick < lo {
        return direction < 0;
    }
    if tick > hi {
        return direction > 0;
    }
    (direction > 0 && tick >= hi) || (direction < 0 && tick <= lo)
}

fn compute_target_tracking_speed(joint: &mut Joint, default_speed: i16) -> i16 {
    let Some(current_tick) = joint.tick else {
        return 0;
    };
    let Some(target_tick) = joint.target_tick else {
        return 0;
    };

    let tick_error = if joint.limit_enabled {
        target_tick_error_limited(joint, target_tick, current_tick)
    } else {
        target_tick_error(target_tick, current_tick)
    };

    if tick_error.abs() <= TARGET_TICK_DEADBAND {
        joint.target_tick = None;
        return 0;
    }

    let mut speed_mag = default_speed.abs();
    if speed_mag > 0 && tick_error.abs() < TARGET_TICK_APPROACH_WINDOW {
        let scaled = ((speed_mag as i32 * tick_error.abs()) / TARGET_TICK_APPROACH_WINDOW) as i16;
        speed_mag = speed_mag.min(TARGET_TICK_MIN_APPROACH_SPEED).max(scaled);
    }

    let direction = if tick_error > 0 { 1 } else { -1 };
    direction * speed_mag * joint.drive_sign as i16
}

fn compute_requested_speed(joint: &mut Joint, default_speed: i16) -> i16 {
    if joint.target_tick.is_some() {
        return compute_target_tracking_speed(joint, default_speed);
    }
    if joint.speed != 0 {
        return joint.speed.signum() * default_speed.abs();
    }
    0
}

fn safety_fault_reason(
    joint: &mut Joint,
    requested_speed: i16,
    now_ms: u64,
) -> Option<SafetyFault> {
    if let Some(temp_c) = joint.temp_c
        && temp_c > MAX_TEMP_C
    {
        joint.stall_since_ms = None;
        return Some(SafetyFault::OverTemperature);
    }

    if !joint.limit_enabled {
        joint.stall_since_ms = None;
        return None;
    }

    if joint.tick.is_none() {
        joint.stall_since_ms = None;
        return Some(SafetyFault::FeedbackUnavailable);
    }

    if now_ms.saturating_sub(joint.last_feedback_ms) > JOINT_FEEDBACK_TIMEOUT_MS {
        joint.stall_since_ms = None;
        return Some(SafetyFault::FeedbackStale);
    }

    if requested_speed.abs() >= STALL_SPEED_MIN && joint.tick_delta == 0 {
        if let Some(stall_since_ms) = joint.stall_since_ms {
            let trip_ms = if joint.target_tick.is_some() {
                STALL_TRIP_MS
            } else {
                STALL_TRIP_FREE_SPIN_MS
            };
            if now_ms.saturating_sub(stall_since_ms) >= trip_ms {
                return Some(SafetyFault::Stall);
            }
        } else {
            joint.stall_since_ms = Some(now_ms);
        }
    } else {
        joint.stall_since_ms = None;
    }

    None
}

fn apply_safety_governor(joint: &mut Joint, requested_speed: i16, now_ms: u64) -> i16 {
    if requested_speed == 0 {
        joint.stall_since_ms = None;
        return 0;
    }

    if let Some(reason) = safety_fault_reason(joint, requested_speed, now_ms) {
        joint.fault = Some(reason);
        return 0;
    }

    if joint.fault.is_some() {
        return 0;
    }

    if joint.tick.is_none() || !joint.limit_enabled {
        return requested_speed;
    }

    if !limit_blocks_for_speed(joint, requested_speed) {
        return requested_speed;
    }

    if joint.target_tick.is_some() {
        let recovery_speed = -requested_speed;
        if !limit_blocks_for_speed(joint, recovery_speed) {
            return recovery_speed;
        }
    }

    0
}

fn apply_limit_slowdown(joint: &Joint, requested_speed: i16) -> i16 {
    if requested_speed == 0 || !joint.limit_enabled {
        return requested_speed;
    }

    let Some(tick) = joint.tick else {
        return requested_speed;
    };

    let direction = requested_speed.signum() as i32;
    let (lo, hi) = continuous_tick_interval(joint.tick_min, joint.tick_max);
    let tick = align_tick_to_interval(tick, lo, hi);
    let distance = if direction > 0 { hi - tick } else { tick - lo };

    if distance <= 0 {
        return 0;
    }
    if distance >= LIMIT_SLOWDOWN_WINDOW_TICKS {
        return requested_speed;
    }

    let base = requested_speed.abs() as i32;
    let scaled = (base * distance / LIMIT_SLOWDOWN_WINDOW_TICKS).clamp(1, base) as i16;
    requested_speed.signum() * scaled
}

fn slew_limit_speed(joint: &Joint, desired_speed: i16, now_ms: u64) -> i16 {
    let Some(previous) = joint.last_sent_speed else {
        return desired_speed;
    };

    if desired_speed == previous || desired_speed == 0 {
        return desired_speed;
    }

    let dt_ms = now_ms.saturating_sub(joint.last_speed_cmd_ms).max(50);
    let rate = if desired_speed.abs() > previous.abs() {
        SPEED_ACCEL_LIMIT_PER_S
    } else {
        SPEED_DECEL_LIMIT_PER_S
    };
    let max_delta = (rate as u64 * dt_ms / 1000) as i32;
    let delta = (desired_speed - previous) as i32;
    let limited_delta = delta.clamp(-max_delta, max_delta) as i16;
    previous + limited_delta
}

pub fn compute_safe_speed(joint: &mut Joint, default_speed: i16, now_ms: u64) -> i16 {
    let requested = compute_requested_speed(joint, default_speed);
    let mut safe_speed = apply_safety_governor(joint, requested, now_ms);

    let max_speed = default_speed.abs();
    if max_speed == 0 {
        safe_speed = 0;
    } else if safe_speed.abs() > max_speed {
        safe_speed = safe_speed.signum() * max_speed;
    }

    if joint.target_tick.is_some() {
        safe_speed = apply_limit_slowdown(joint, safe_speed);
        safe_speed = slew_limit_speed(joint, safe_speed, now_ms);
    }

    joint.speed = safe_speed;
    safe_speed
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct SpeedCommand {
    pub servo_id: u8,
    pub speed: i16,
    pub should_send: bool,
}

pub fn init_joints(joints: &mut [Joint], now_ms: u64) {
    for joint in joints {
        joint.last_feedback_ms = now_ms;
        joint.last_speed_cmd_ms = now_ms;
    }
}

fn has_active_free_spin(joints: &[Joint]) -> bool {
    joints.iter().any(|joint| {
        joint.target_tick.is_none() && (joint.speed != 0 || joint.last_sent_speed.unwrap_or(0) != 0)
    })
}

pub fn deadman_reason(
    joints: &[Joint],
    last_cmd_ms: u64,
    last_ok_feedback_ms: u64,
    now_ms: u64,
) -> Option<SafetyFault> {
    if now_ms.saturating_sub(last_ok_feedback_ms) > DEADMAN_FEEDBACK_TIMEOUT_MS {
        return Some(SafetyFault::DeadmanFeedbackStale);
    }

    if has_active_free_spin(joints) && now_ms.saturating_sub(last_cmd_ms) > DEADMAN_CMD_TIMEOUT_MS {
        return Some(SafetyFault::DeadmanCommandStale);
    }

    None
}

pub fn force_stop(joints: &mut [Joint], last_error: &mut Option<SafetyFault>, reason: SafetyFault) {
    *last_error = Some(reason);
    for joint in joints {
        joint.target_tick = None;
        joint.speed = 0;
    }
}
