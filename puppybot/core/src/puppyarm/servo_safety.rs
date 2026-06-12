pub const TICK_WRAP: i32 = 4096;

pub const YAW_TICK_MIN: i32 = -1400;
pub const YAW_TICK_MAX: i32 = 1400;
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

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct JointSafety {
    pub servo_id: u8,
    pub tick_min: i32,
    pub tick_max: i32,
    pub drive_sign: i8,
    pub speed: i16,
    pub target_tick: Option<i32>,
    pub tick: Option<i32>,
    pub tick_delta: i32,
    pub limit_enabled: bool,
    pub has_feedback: bool,
    pub is_online: bool,
    pub last_feedback_ms: u64,
    pub temp_c: Option<u8>,
    pub last_sent_speed: Option<i16>,
    pub last_speed_cmd_ms: u64,
    pub stall_since_ms: Option<u64>,
    pub fault: Option<SafetyFault>,
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

pub fn clip_tick_to_joint_limits(joint: &JointSafety, tick: i32) -> i32 {
    if !joint.limit_enabled {
        return tick;
    }

    let (lo, hi) = continuous_tick_interval(joint.tick_min, joint.tick_max);
    align_tick_to_interval(tick, lo, hi).clamp(lo, hi)
}

pub fn tick_within_joint_limits(joint: &JointSafety, tick: i32) -> bool {
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
    if wrapped_error.abs() <= TARGET_TICK_DEADBAND {
        return wrapped_error;
    }

    naive_error
}

pub fn target_tick_error_limited(joint: &JointSafety, target_tick: i32, current_tick: i32) -> i32 {
    let (lo, hi) = continuous_tick_interval(joint.tick_min, joint.tick_max);
    let current = align_tick_to_interval(current_tick, lo, hi);
    let target = align_tick_to_interval(target_tick, lo, hi);
    target - current
}

pub fn is_outside_limits(joint: &JointSafety) -> bool {
    let Some(tick) = joint.tick else {
        return false;
    };
    !tick_within_joint_limits(joint, tick)
}

pub fn limit_blocks_for_speed(joint: &JointSafety, speed: i16) -> bool {
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

fn compute_target_tracking_speed(joint: &mut JointSafety, default_speed: i16) -> i16 {
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

fn compute_requested_speed(joint: &mut JointSafety, default_speed: i16) -> i16 {
    if joint.target_tick.is_some() {
        return compute_target_tracking_speed(joint, default_speed);
    }
    if joint.speed != 0 {
        return joint.speed.signum() * default_speed.abs();
    }
    0
}

fn safety_fault_reason(
    joint: &mut JointSafety,
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

fn apply_safety_governor(joint: &mut JointSafety, requested_speed: i16, now_ms: u64) -> i16 {
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

fn apply_limit_slowdown(joint: &JointSafety, requested_speed: i16) -> i16 {
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

fn slew_limit_speed(joint: &JointSafety, desired_speed: i16, now_ms: u64) -> i16 {
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
fn compute_safe_speed(joint: &mut JointSafety, default_speed: i16, now_ms: u64) -> i16 {
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

impl JointSafety {
    pub const fn new(servo_id: u8, tick_min: i32, tick_max: i32) -> Self {
        Self {
            servo_id,
            tick_min,
            tick_max,
            drive_sign: 1,
            speed: 0,
            target_tick: None,
            tick: None,
            tick_delta: 0,
            limit_enabled: true,
            has_feedback: false,
            is_online: true,
            last_feedback_ms: 0,
            temp_c: None,
            last_sent_speed: None,
            last_speed_cmd_ms: 0,
            stall_since_ms: None,
            fault: None,
        }
    }

    pub const fn with_drive_sign(mut self, drive_sign: i8) -> Self {
        self.drive_sign = drive_sign;
        self
    }

    pub fn record_feedback(&mut self, tick: i32, now_ms: u64) {
        let previous = self.tick;
        self.tick = Some(tick);
        self.tick_delta = previous.map(|value| tick - value).unwrap_or(0);
        self.has_feedback = true;
        self.is_online = true;
        self.last_feedback_ms = now_ms;
    }

    pub fn record_feedback_error(&mut self) {
        self.is_online = false;
        self.tick = None;
        self.tick_delta = 0;
    }

    pub fn set_temperature(&mut self, temp_c: Option<u8>) {
        self.temp_c = temp_c;
    }

    pub fn clear_fault(&mut self) {
        self.fault = None;
        self.stall_since_ms = None;
    }

    pub fn stop(&mut self) {
        self.target_tick = None;
        self.speed = 0;
    }

    pub fn spin(&mut self, direction: i8, default_speed: i16) {
        self.clear_fault();
        self.target_tick = None;
        self.speed = direction.signum() as i16 * default_speed.abs();
    }

    pub fn goto_tick(&mut self, tick: i32) {
        self.clear_fault();
        self.target_tick = Some(clip_tick_to_joint_limits(self, tick));
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct SpeedCommand {
    pub servo_id: u8,
    pub speed: i16,
    pub should_send: bool,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct ServoSafety<const N: usize> {
    pub joints: [JointSafety; N],
    pub default_speed: i16,
    pub last_cmd_ms: u64,
    pub last_ok_feedback_ms: u64,
    pub last_error: Option<SafetyFault>,
}

impl<const N: usize> ServoSafety<N> {
    pub fn new(mut joints: [JointSafety; N], now_ms: u64) -> Self {
        for joint in &mut joints {
            joint.last_feedback_ms = now_ms;
            joint.last_speed_cmd_ms = now_ms;
        }

        Self {
            joints,
            default_speed: 200,
            last_cmd_ms: now_ms,
            last_ok_feedback_ms: now_ms,
            last_error: None,
        }
    }

    pub fn set_default_speed(&mut self, speed: i16, now_ms: u64) {
        self.default_speed = speed.abs();
        self.last_cmd_ms = now_ms;
    }

    pub fn spin(&mut self, joint_index: usize, direction: i8, now_ms: u64) -> Result<(), ()> {
        let default_speed = self.default_speed;
        let joint = self.joints.get_mut(joint_index).ok_or(())?;
        joint.spin(direction, default_speed);
        self.last_cmd_ms = now_ms;
        Ok(())
    }

    pub fn stop_joint(&mut self, joint_index: usize, now_ms: u64) -> Result<(), ()> {
        let joint = self.joints.get_mut(joint_index).ok_or(())?;
        joint.stop();
        self.last_cmd_ms = now_ms;
        Ok(())
    }

    pub fn stop_all(&mut self, now_ms: u64) {
        for joint in &mut self.joints {
            joint.stop();
        }
        self.last_cmd_ms = now_ms;
    }

    pub fn goto_ticks(&mut self, ticks: &[i32], now_ms: u64) -> Result<(), ()> {
        if ticks.len() != self.joints.len() {
            return Err(());
        }

        for (joint, tick) in self.joints.iter_mut().zip(ticks.iter()) {
            joint.goto_tick(*tick);
        }
        self.last_cmd_ms = now_ms;
        Ok(())
    }

    pub fn clear_faults(&mut self, joint_index: Option<usize>) -> Result<(), ()> {
        if let Some(index) = joint_index {
            self.joints.get_mut(index).ok_or(())?.clear_fault();
        } else {
            for joint in &mut self.joints {
                joint.clear_fault();
            }
            self.last_error = None;
        }
        Ok(())
    }

    pub fn record_feedback(
        &mut self,
        joint_index: usize,
        tick: i32,
        now_ms: u64,
    ) -> Result<(), ()> {
        let joint = self.joints.get_mut(joint_index).ok_or(())?;
        joint.record_feedback(tick, now_ms);
        self.last_ok_feedback_ms = now_ms;
        Ok(())
    }

    pub fn record_feedback_error(&mut self, joint_index: usize) -> Result<(), ()> {
        self.joints
            .get_mut(joint_index)
            .ok_or(())?
            .record_feedback_error();
        Ok(())
    }

    pub fn speed_commands(&mut self, now_ms: u64) -> [SpeedCommand; N] {
        if let Some(reason) = self.deadman_reason(now_ms) {
            self.force_stop(reason);
        }

        core::array::from_fn(|index| {
            let desired = compute_safe_speed(&mut self.joints[index], self.default_speed, now_ms);
            let should_send = self.joints[index].last_sent_speed != Some(desired);
            SpeedCommand {
                servo_id: self.joints[index].servo_id,
                speed: desired,
                should_send,
            }
        })
    }

    pub fn mark_speed_sent(
        &mut self,
        joint_index: usize,
        speed: i16,
        now_ms: u64,
    ) -> Result<(), ()> {
        let joint = self.joints.get_mut(joint_index).ok_or(())?;
        joint.last_sent_speed = Some(speed);
        joint.last_speed_cmd_ms = now_ms;
        Ok(())
    }

    fn deadman_reason(&self, now_ms: u64) -> Option<SafetyFault> {
        if now_ms.saturating_sub(self.last_ok_feedback_ms) > DEADMAN_FEEDBACK_TIMEOUT_MS {
            return Some(SafetyFault::DeadmanFeedbackStale);
        }

        if self.has_active_free_spin()
            && now_ms.saturating_sub(self.last_cmd_ms) > DEADMAN_CMD_TIMEOUT_MS
        {
            return Some(SafetyFault::DeadmanCommandStale);
        }

        None
    }

    fn has_active_free_spin(&self) -> bool {
        self.joints.iter().any(|joint| {
            joint.target_tick.is_none()
                && (joint.speed != 0 || joint.last_sent_speed.unwrap_or(0) != 0)
        })
    }

    fn force_stop(&mut self, reason: SafetyFault) {
        self.last_error = Some(reason);
        for joint in &mut self.joints {
            joint.target_tick = None;
            joint.speed = 0;
        }
    }
}

pub fn default_arm_safety(now_ms: u64) -> ServoSafety<4> {
    ServoSafety::new(
        [
            JointSafety::new(1, YAW_TICK_MIN, YAW_TICK_MAX),
            JointSafety::new(2, SHOULDER_TICK_MIN, SHOULDER_TICK_MAX),
            JointSafety::new(3, ELBOW_TICK_MIN, ELBOW_TICK_MAX),
            JointSafety::new(4, TIP_TICK_MIN, TIP_TICK_MAX),
        ],
        now_ms,
    )
}

#[cfg(test)]
mod tests {
    #[allow(unused_imports)]
    use super::*;

    #[test]
    fn target_error_prefers_small_wrap_near_deadband() {
        assert_eq!(target_tick_error(2, 4094), 4);
    }

    #[test]
    fn target_error_keeps_large_naive_error_when_wrap_is_not_near_target() {
        assert_eq!(target_tick_error(100, 3900), -3800);
    }

    #[test]
    fn limit_blocks_only_when_moving_farther_out() {
        let mut joint = JointSafety::new(1, 100, 200);
        joint.tick = Some(200);
        assert!(limit_blocks_for_speed(&joint, 50));
        assert!(!limit_blocks_for_speed(&joint, -50));
    }

    #[test]
    fn joint_limit_exceeded_blocks_farther_out_motion() {
        let mut joint = JointSafety::new(1, 100, 200);
        joint.tick = Some(250);

        assert!(is_outside_limits(&joint));
        assert!(limit_blocks_for_speed(&joint, 80));
    }

    #[test]
    fn joint_limit_exceeded_allows_return_toward_valid_range() {
        let mut joint = JointSafety::new(1, 100, 200);
        joint.tick = Some(250);

        assert!(is_outside_limits(&joint));
        assert!(!limit_blocks_for_speed(&joint, -80));
    }

    #[test]
    fn wrapped_tick_limits_behave_near_zero() {
        let mut joint = JointSafety::new(1, 4000, 100);
        joint.tick = Some(100);

        assert!(!is_outside_limits(&joint));
        assert!(limit_blocks_for_speed(&joint, 80));
        assert!(!limit_blocks_for_speed(&joint, -80));
    }

    #[test]
    fn negative_min_limit_treats_high_modulo_tick_as_inside() {
        let mut joint = JointSafety::new(1, -500, 1300);
        joint.tick = Some(3976);

        assert!(!is_outside_limits(&joint));
        assert!(!limit_blocks_for_speed(&joint, 120));
        assert!(!limit_blocks_for_speed(&joint, -120));
    }

    #[test]
    fn extended_max_limit_allows_motion_back_toward_interval() {
        let mut joint = JointSafety::new(1, 3300, 4100);
        joint.tick = Some(88);

        assert!(is_outside_limits(&joint));
        assert!(limit_blocks_for_speed(&joint, 120));
        assert!(!limit_blocks_for_speed(&joint, -120));
    }

    #[test]
    fn unrelated_joint_limit_does_not_block_yaw_jog() {
        let mut safety = default_arm_safety(0);
        safety.record_feedback(0, 0, 0).unwrap();
        safety.record_feedback(3, TIP_TICK_MAX + 4, 0).unwrap();
        safety.spin(0, 1, 0).unwrap();

        let commands = safety.speed_commands(10);

        assert!(is_outside_limits(&safety.joints[3]));
        assert_eq!(commands[0].speed, safety.default_speed);
    }

    #[test]
    fn disabled_limits_allow_target_motion() {
        let mut safety = ServoSafety::new([JointSafety::new(1, 4000, 100)], 0);
        safety.default_speed = 80;
        safety.joints[0].limit_enabled = false;
        safety.record_feedback(0, 2000, 0).unwrap();
        safety.goto_ticks(&[4050], 0).unwrap();

        let commands = safety.speed_commands(10);

        assert_eq!(commands[0].speed, 80);
    }

    #[test]
    fn goto_ticks_uses_default_speed() {
        let mut safety = ServoSafety::new([JointSafety::new(1, -1000, 1000)], 0);
        safety.default_speed = 80;
        safety.record_feedback(0, 0, 0).unwrap();
        safety.goto_ticks(&[100], 0).unwrap();

        let commands = safety.speed_commands(10);

        assert_eq!(commands[0].speed, 80);
    }

    #[test]
    fn goto_ticks_stops_at_target() {
        let mut safety = ServoSafety::new([JointSafety::new(1, -1000, 1000)], 0);
        safety.default_speed = 80;
        safety.record_feedback(0, 100, 0).unwrap();
        safety.goto_ticks(&[100], 0).unwrap();

        let commands = safety.speed_commands(10);

        assert_eq!(commands[0].speed, 0);
        assert_eq!(safety.joints[0].target_tick, None);
    }

    #[test]
    fn goto_ticks_stops_within_deadband() {
        let mut safety = ServoSafety::new([JointSafety::new(1, -1000, 1000)], 0);
        safety.default_speed = 80;
        safety.record_feedback(0, 96, 0).unwrap();
        safety.goto_ticks(&[100], 0).unwrap();

        let commands = safety.speed_commands(10);

        assert_eq!(commands[0].speed, 0);
        assert_eq!(safety.joints[0].target_tick, None);
    }

    #[test]
    fn goto_ticks_reduces_speed_when_close() {
        let mut safety = ServoSafety::new([JointSafety::new(1, -1000, 1000)], 0);
        safety.default_speed = 80;
        safety.record_feedback(0, 40, 0).unwrap();
        safety.goto_ticks(&[100], 0).unwrap();

        let commands = safety.speed_commands(10);

        assert_eq!(commands[0].speed, 60);
    }

    #[test]
    fn stop_cancels_active_target() {
        let mut safety = ServoSafety::new([JointSafety::new(1, -1000, 1000)], 0);
        safety.record_feedback(0, 0, 0).unwrap();
        safety.goto_ticks(&[100], 0).unwrap();

        safety.stop_joint(0, 10).unwrap();

        assert_eq!(safety.joints[0].target_tick, None);
        assert_eq!(safety.joints[0].speed, 0);
    }

    #[test]
    fn zero_default_speed_stops_spinning_joint() {
        let mut safety = ServoSafety::new([JointSafety::new(1, -1000, 1000)], 0);
        safety.default_speed = 200;
        safety.record_feedback(0, 0, 0).unwrap();
        safety.spin(0, 1, 0).unwrap();
        safety.set_default_speed(0, 10);

        let commands = safety.speed_commands(10);

        assert_eq!(commands[0].speed, 0);
    }

    #[test]
    fn zero_default_speed_stops_active_goto_motion() {
        let mut safety = ServoSafety::new([JointSafety::new(1, -1000, 1000)], 0);
        safety.default_speed = 200;
        safety.record_feedback(0, 0, 0).unwrap();
        safety.goto_ticks(&[500], 0).unwrap();
        safety.set_default_speed(0, 10);

        let commands = safety.speed_commands(10);

        assert_eq!(commands[0].speed, 0);
        assert_eq!(safety.joints[0].target_tick, Some(500));
    }

    #[test]
    fn target_tracking_speed_scales_with_positive_tick_error() {
        let mut safety = ServoSafety::new([JointSafety::new(1, -1000, 1000)], 0);
        safety.default_speed = 200;
        safety.record_feedback(0, 40, 0).unwrap();
        safety.goto_ticks(&[80], 0).unwrap();

        let commands = safety.speed_commands(10);

        assert_eq!(commands[0].speed, 100);
    }

    #[test]
    fn target_tracking_speed_scales_with_negative_tick_error() {
        let mut safety = ServoSafety::new([JointSafety::new(1, -1000, 1000)], 0);
        safety.default_speed = 200;
        safety.record_feedback(0, 80, 0).unwrap();
        safety.goto_ticks(&[40], 0).unwrap();

        let commands = safety.speed_commands(10);

        assert_eq!(commands[0].speed, -100);
    }

    #[test]
    fn slew_limit_bounds_acceleration() {
        let mut safety = ServoSafety::new([JointSafety::new(1, -2000, 2000)], 0);
        safety.default_speed = 400;
        safety.record_feedback(0, 0, 0).unwrap();
        safety.goto_ticks(&[1000], 0).unwrap();
        safety.mark_speed_sent(0, 0, 0).unwrap();

        let commands = safety.speed_commands(10);

        assert_eq!(commands[0].speed, 200);
    }

    #[test]
    fn slew_limit_bounds_deceleration() {
        let mut safety = ServoSafety::new([JointSafety::new(1, -2000, 2000)], 0);
        safety.default_speed = 400;
        safety.record_feedback(0, 0, 0).unwrap();
        safety.goto_ticks(&[20], 0).unwrap();
        safety.mark_speed_sent(0, 400, 0).unwrap();

        let commands = safety.speed_commands(10);

        assert_eq!(commands[0].speed, 100);
    }

    #[test]
    fn stale_feedback_forces_zero_speed() {
        let mut safety = default_arm_safety(0);
        safety.record_feedback(0, 0, 0).unwrap();
        safety.spin(0, 1, 0).unwrap();
        safety
            .record_feedback(1, 200, JOINT_FEEDBACK_TIMEOUT_MS + 1)
            .unwrap();
        let commands = safety.speed_commands(JOINT_FEEDBACK_TIMEOUT_MS + 1);
        assert_eq!(commands[0].speed, 0);
        assert_eq!(safety.joints[0].fault, Some(SafetyFault::FeedbackStale));
    }

    #[test]
    fn deadman_stops_free_spin() {
        let mut safety = default_arm_safety(0);
        safety.record_feedback(0, 100, 0).unwrap();
        safety.spin(0, 1, 0).unwrap();
        safety.mark_speed_sent(0, 200, 0).unwrap();
        safety
            .record_feedback(0, 100, DEADMAN_CMD_TIMEOUT_MS + 1)
            .unwrap();
        let commands = safety.speed_commands(DEADMAN_CMD_TIMEOUT_MS + 1);
        assert_eq!(commands[0].speed, 0);
        assert_eq!(safety.last_error, Some(SafetyFault::DeadmanCommandStale));
    }

    #[test]
    fn target_approach_slows_down_near_limit() {
        let mut safety = default_arm_safety(0);
        safety.record_feedback(0, YAW_TICK_MAX - 20, 0).unwrap();
        safety
            .goto_ticks(&[YAW_TICK_MAX, 200, 2300, 600], 0)
            .unwrap();
        let commands = safety.speed_commands(10);
        assert!(commands[0].speed > 0);
        assert!(commands[0].speed < safety.default_speed);
    }
}
