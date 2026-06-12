use core::f64::consts::PI;

use super::{
    kinematics,
    servo_safety::{
        self, ELBOW_TICK_MAX, ELBOW_TICK_MIN, SHOULDER_TICK_MAX, SHOULDER_TICK_MIN, ServoSafety,
        SpeedCommand, TICK_WRAP, TIP_TICK_MAX, TIP_TICK_MIN, YAW_TICK_MAX, YAW_TICK_MIN,
    },
};
use crate::stservo::{MAX_SERVO_ID, MIN_SERVO_ID, Mode};

pub use super::types::{
    ArmCommand, ArmMode, ControllerError, JOINT_COUNT, Joint, PuppyarmTelemetry,
};

const YAW_SIGN: f64 = 1.0;
const SHOULDER_SIGN: f64 = -1.0;
const SHOULDER_DRIVE_SIGN: i8 = 1;
const ELBOW_SIGN: f64 = -1.0;
const ELBOW_DRIVE_SIGN: i8 = 1;
const TIP_SIGN: f64 = 1.0;

const YAW_ZERO_TICK: i32 = YAW_TICK_MIN;
const SHOULDER_ZERO_TICK: i32 = 530;
const ELBOW_ZERO_TICK: i32 = 3565;
const TIP_ZERO_TICK: i32 = 1783;

const WHEEL_MODE_RECOVERY_RETRY_MS: u64 = 1000;
const WHEEL_MODE_NEVER_ATTEMPTED: u64 = u64::MAX;
const RAD_TO_DEG: f64 = 180.0 / core::f64::consts::PI;

fn current_targets(safety: &ServoSafety<JOINT_COUNT>) -> Option<[i32; JOINT_COUNT]> {
    let mut targets = [0; JOINT_COUNT];
    for (index, joint) in safety.joints.iter().enumerate() {
        targets[index] = joint.target_tick?;
    }
    Some(targets)
}

fn active_jog(safety: &ServoSafety<JOINT_COUNT>) -> Option<(usize, i8)> {
    for (index, joint) in safety.joints.iter().enumerate() {
        if joint.target_tick.is_none() && joint.speed != 0 {
            return Some((index, joint.speed.signum() as i8));
        }
    }
    None
}

fn default_joints() -> [Joint; JOINT_COUNT] {
    [
        Joint {
            servo_id: 2,
            tick_min: YAW_TICK_MIN,
            tick_max: YAW_TICK_MAX,
            raw_tick_min: YAW_TICK_MIN,
            raw_tick_max: YAW_TICK_MAX,
            sign: YAW_SIGN,
            drive_sign: 1,
            zero_offset_rad: zero_offset_from_reference(
                YAW_ZERO_TICK,
                YAW_TICK_MIN,
                YAW_TICK_MAX,
                YAW_SIGN,
                0.0,
            ),
            online: false,
            has_feedback: false,
            limit_reached: false,
            tick: None,
            target_tick: None,
            tick_delta: 0,
            limit_enabled: true,
            speed: 0,
            limit_min: YAW_TICK_MIN,
            limit_max: YAW_TICK_MAX,
            angle_deg: None,
            last_feedback_ms: 0,
            temp_c: None,
            last_sent_speed: None,
            last_speed_cmd_ms: 0,
            stall_since_ms: None,
            fault: None,
        },
        Joint {
            servo_id: 3,
            tick_min: SHOULDER_TICK_MIN,
            tick_max: SHOULDER_TICK_MAX,
            raw_tick_min: SHOULDER_TICK_MIN,
            raw_tick_max: SHOULDER_TICK_MAX,
            sign: SHOULDER_SIGN,
            drive_sign: SHOULDER_DRIVE_SIGN,
            zero_offset_rad: zero_offset_from_reference(
                SHOULDER_ZERO_TICK,
                SHOULDER_TICK_MIN,
                SHOULDER_TICK_MAX,
                SHOULDER_SIGN,
                PI / 2.0,
            ),
            online: false,
            has_feedback: false,
            limit_reached: false,
            tick: None,
            target_tick: None,
            tick_delta: 0,
            limit_enabled: true,
            speed: 0,
            limit_min: SHOULDER_TICK_MIN,
            limit_max: SHOULDER_TICK_MAX,
            angle_deg: None,
            last_feedback_ms: 0,
            temp_c: None,
            last_sent_speed: None,
            last_speed_cmd_ms: 0,
            stall_since_ms: None,
            fault: None,
        },
        Joint {
            servo_id: 4,
            tick_min: ELBOW_TICK_MIN,
            tick_max: ELBOW_TICK_MAX,
            raw_tick_min: ELBOW_TICK_MIN,
            raw_tick_max: ELBOW_TICK_MAX,
            sign: ELBOW_SIGN,
            drive_sign: ELBOW_DRIVE_SIGN,
            zero_offset_rad: zero_offset_from_reference(
                ELBOW_ZERO_TICK,
                ELBOW_TICK_MIN,
                ELBOW_TICK_MAX,
                ELBOW_SIGN,
                0.0,
            ),
            online: false,
            has_feedback: false,
            limit_reached: false,
            tick: None,
            target_tick: None,
            tick_delta: 0,
            limit_enabled: true,
            speed: 0,
            limit_min: ELBOW_TICK_MIN,
            limit_max: ELBOW_TICK_MAX,
            angle_deg: None,
            last_feedback_ms: 0,
            temp_c: None,
            last_sent_speed: None,
            last_speed_cmd_ms: 0,
            stall_since_ms: None,
            fault: None,
        },
        Joint {
            servo_id: 5,
            tick_min: TIP_TICK_MIN,
            tick_max: TIP_TICK_MAX,
            raw_tick_min: TIP_TICK_MIN,
            raw_tick_max: TIP_TICK_MAX,
            sign: TIP_SIGN,
            drive_sign: 1,
            zero_offset_rad: zero_offset_from_reference(
                TIP_ZERO_TICK,
                TIP_TICK_MIN,
                TIP_TICK_MAX,
                TIP_SIGN,
                0.0,
            ),
            online: false,
            has_feedback: false,
            limit_reached: false,
            tick: None,
            target_tick: None,
            tick_delta: 0,
            limit_enabled: true,
            speed: 0,
            limit_min: TIP_TICK_MIN,
            limit_max: TIP_TICK_MAX,
            angle_deg: None,
            last_feedback_ms: 0,
            temp_c: None,
            last_sent_speed: None,
            last_speed_cmd_ms: 0,
            stall_since_ms: None,
            fault: None,
        },
    ]
}

fn angle_to_tick(joint: &Joint, angle_rad: f64) -> i32 {
    let mid_tick = reference_mid_tick(joint);
    let physical_angle = joint.sign * angle_rad + joint.zero_offset_rad;
    libm::round(mid_tick + physical_angle * TICK_WRAP as f64 / (2.0 * PI)) as i32
}

fn tick_to_angle(joint: &Joint, tick: i32) -> f64 {
    let mid_tick = reference_mid_tick(joint);
    let aligned_tick = servo_safety::align_tick_to_reference(tick, mid_tick as i32);
    let physical_angle = (aligned_tick as f64 - mid_tick) * (2.0 * PI / TICK_WRAP as f64);
    (physical_angle - joint.zero_offset_rad) / joint.sign
}

fn zero_offset_from_reference(
    tick: i32,
    raw_tick_min: i32,
    raw_tick_max: i32,
    sign: f64,
    target_angle_rad: f64,
) -> f64 {
    let (lo, hi) = servo_safety::continuous_tick_interval(raw_tick_min, raw_tick_max);
    let mid_tick = 0.5 * (lo + hi) as f64;
    let aligned_tick = servo_safety::align_tick_to_reference(tick, mid_tick as i32);
    let physical_angle = (aligned_tick as f64 - mid_tick) * (2.0 * PI / TICK_WRAP as f64);
    physical_angle - sign * target_angle_rad
}

fn reference_mid_tick(joint: &Joint) -> f64 {
    let (lo, hi) = servo_safety::continuous_tick_interval(joint.raw_tick_min, joint.raw_tick_max);
    0.5 * (lo + hi) as f64
}

fn validate_joint(joint: usize) -> Result<usize, ControllerError> {
    if joint < JOINT_COUNT {
        Ok(joint)
    } else {
        Err(ControllerError::InvalidJoint)
    }
}

fn default_arm_state(now_ms: u64) -> (ServoSafety<JOINT_COUNT>, [Joint; JOINT_COUNT], ArmMode) {
    let joints = default_joints();
    let safety = ServoSafety::new([joints[0], joints[1], joints[2], joints[3]], now_ms);

    (safety, joints, ArmMode::Idle)
}

pub struct PuppyArm {
    safety: ServoSafety<JOINT_COUNT>,
    joints: [Joint; JOINT_COUNT],
    mode: ArmMode,
    wheel_servo_ids: [u8; JOINT_COUNT],
    wheel_mode_ready: [bool; JOINT_COUNT],
    wheel_mode_last_attempt_ms: [u64; JOINT_COUNT],
    queued_initial_wheel_mode: bool,
}

fn valid_servo_ids(servo_ids: &[u8; JOINT_COUNT]) -> bool {
    servo_ids
        .iter()
        .all(|servo_id| (MIN_SERVO_ID..=MAX_SERVO_ID).contains(servo_id))
}

impl PuppyArm {
    pub fn new(now: u64) -> Self {
        let (safety, joints, mode) = default_arm_state(now);
        Self {
            safety,
            joints,
            mode,
            wheel_servo_ids: core::array::from_fn(|index| joints[index].servo_id),
            wheel_mode_ready: [false; JOINT_COUNT],
            wheel_mode_last_attempt_ms: [WHEEL_MODE_NEVER_ATTEMPTED; JOINT_COUNT],
            queued_initial_wheel_mode: false,
        }
    }

    fn sync_wheel_servo_ids(&mut self) {
        for index in 0..JOINT_COUNT {
            let servo_id = self.joints[index].servo_id;
            if self.wheel_servo_ids[index] != servo_id {
                self.wheel_servo_ids[index] = servo_id;
                self.wheel_mode_ready[index] = false;
                self.wheel_mode_last_attempt_ms[index] = 0;
            }
        }
    }

    fn mark_wheel_mode_ready(&mut self, index: usize) {
        if index < JOINT_COUNT {
            self.wheel_mode_ready[index] = true;
        }
    }

    fn mark_wheel_mode_not_ready(&mut self, index: usize) {
        if index < JOINT_COUNT {
            self.wheel_mode_ready[index] = false;
        }
    }

    fn mark_all_wheel_modes_not_ready(&mut self) {
        self.wheel_mode_ready = [false; JOINT_COUNT];
        self.wheel_mode_last_attempt_ms = [WHEEL_MODE_NEVER_ATTEMPTED; JOINT_COUNT];
    }

    fn wheel_mode_is_ready(&self, index: usize, servo_id: u8) -> bool {
        index < JOINT_COUNT
            && self.wheel_servo_ids[index] == servo_id
            && self.wheel_mode_ready[index]
    }

    fn can_retry_wheel_mode(&self, index: usize, now: u64) -> bool {
        index < JOINT_COUNT
            && (self.wheel_mode_last_attempt_ms[index] == WHEEL_MODE_NEVER_ATTEMPTED
                || now.saturating_sub(self.wheel_mode_last_attempt_ms[index])
                    >= WHEEL_MODE_RECOVERY_RETRY_MS)
    }

    fn mark_wheel_mode_attempt(&mut self, index: usize, now: u64) {
        if index < JOINT_COUNT {
            self.wheel_mode_last_attempt_ms[index] = now;
        }
    }

    pub fn record_feedback(&mut self, joint: usize, tick: u16, now: u64) {
        if joint >= JOINT_COUNT {
            return;
        }

        let was_online = self.safety.joints[joint].online;
        let _ = self.record_feedback_tick(joint, tick as i32, now);
        if !was_online {
            self.mark_wheel_mode_not_ready(joint);
        }
    }

    pub fn record_feedback_error(&mut self, joint: usize) {
        if joint >= JOINT_COUNT {
            return;
        }

        let _ = self.record_feedback_failure(joint);
        self.mark_wheel_mode_not_ready(joint);
    }

    pub fn take_initialize_wheel_mode(&mut self) -> bool {
        if self.queued_initial_wheel_mode {
            return false;
        }

        self.queued_initial_wheel_mode = true;
        true
    }

    pub fn update(&mut self, now: u64) -> [SpeedCommand; JOINT_COUNT] {
        let commands = self.safety.speed_commands(now);
        self.refresh_mode_from_motion();
        commands
    }

    pub fn wheel_mode_ready(&self, joint: usize, servo_id: u8) -> bool {
        self.wheel_mode_is_ready(joint, servo_id)
    }

    pub fn begin_wheel_mode_attempt(
        &mut self,
        joint: usize,
        servo_id: u8,
        now: u64,
        force: bool,
    ) -> bool {
        if self.wheel_mode_is_ready(joint, servo_id) {
            return false;
        }

        if !force && !self.can_retry_wheel_mode(joint, now) {
            return false;
        }

        self.mark_wheel_mode_attempt(joint, now);
        true
    }

    pub fn can_write_wheel_speed(&self, joint: usize, servo_id: u8) -> bool {
        self.wheel_mode_is_ready(joint, servo_id)
    }

    pub fn record_set_mode_result(
        &mut self,
        joint: usize,
        servo_id: u8,
        mode: Mode,
        success: bool,
    ) {
        if mode != Mode::Wheel {
            return;
        }

        if success {
            self.mark_wheel_mode_ready(joint);
        } else {
            self.mark_wheel_mode_not_ready(joint);
        }

        if self.joints.get(joint).map(|joint| joint.servo_id) != Some(servo_id) {
            self.mark_wheel_mode_not_ready(joint);
        }
    }

    pub fn record_wheel_speed_result(
        &mut self,
        joint: usize,
        servo_id: u8,
        speed: i16,
        success: bool,
        now: u64,
    ) {
        if success {
            let _ = self.mark_speed_sent(joint, speed, now);
        } else {
            self.mark_wheel_mode_not_ready(joint);
        }

        if self.joints.get(joint).map(|joint| joint.servo_id) != Some(servo_id) {
            self.mark_wheel_mode_not_ready(joint);
        }
    }

    pub fn telemetry_snapshot(&self, seq: u32) -> PuppyarmTelemetry {
        let coords_mm = self.current_coords().ok().map(|(x, y, z)| {
            (
                x as f32,
                y as f32,
                super::kinematics::shoulder_to_table_z(z) as f32,
            )
        });

        PuppyarmTelemetry {
            seq,
            joints: core::array::from_fn(|index| {
                let joint = self.safety.joints[index];
                Joint {
                    servo_id: joint.servo_id,
                    tick_min: self.joints[index].tick_min,
                    tick_max: self.joints[index].tick_max,
                    raw_tick_min: self.joints[index].raw_tick_min,
                    raw_tick_max: self.joints[index].raw_tick_max,
                    sign: self.joints[index].sign,
                    drive_sign: self.joints[index].drive_sign,
                    zero_offset_rad: self.joints[index].zero_offset_rad,
                    online: joint.online,
                    has_feedback: joint.has_feedback && joint.tick.is_some(),
                    limit_reached: servo_safety::is_outside_limits(&joint),
                    tick: joint.tick,
                    target_tick: joint.target_tick,
                    tick_delta: joint.tick_delta,
                    limit_enabled: joint.limit_enabled,
                    speed: joint.speed,
                    limit_min: joint.tick_min,
                    limit_max: joint.tick_max,
                    angle_deg: self
                        .joint_angle(index)
                        .ok()
                        .map(|angle_rad| (angle_rad * RAD_TO_DEG) as f32),
                    last_feedback_ms: joint.last_feedback_ms,
                    temp_c: joint.temp_c,
                    last_sent_speed: joint.last_sent_speed,
                    last_speed_cmd_ms: joint.last_speed_cmd_ms,
                    stall_since_ms: joint.stall_since_ms,
                    fault: joint.fault,
                }
            }),
            coords_mm,
        }
    }

    pub fn handle_arm_cmd(&mut self, command: ArmCommand, now: u64) {
        if let ArmCommand::SetServoIds(_) = command {
            let ArmCommand::SetServoIds(servo_ids) = command else {
                unreachable!();
            };
            if !valid_servo_ids(&servo_ids) {
                log::warn!("arm intent rejected: SetServoIds");
                return;
            }
            if self
                .handle_command(ArmCommand::SetServoIds(servo_ids), now)
                .is_ok()
            {
                self.sync_wheel_servo_ids();
                self.mark_all_wheel_modes_not_ready();
                self.queued_initial_wheel_mode = false;
            } else {
                log::warn!("arm intent rejected: SetServoIds");
            }
            return;
        }

        if let Err(err) = self.handle_command(command, now) {
            log::warn!("arm intent rejected: {:?}", err);
        }
    }

    fn handle_command(&mut self, command: ArmCommand, now: u64) -> Result<(), ControllerError> {
        match command {
            ArmCommand::SetSpeed(speed) => {
                self.safety.set_default_speed(speed, now);
                Ok(())
            }
            ArmCommand::Spin { joint, direction } => {
                self.safety
                    .spin(validate_joint(joint)?, direction, now)
                    .map_err(|()| ControllerError::InvalidJoint)?;
                self.mode = if direction == 0 {
                    ArmMode::Idle
                } else {
                    ArmMode::Jogging {
                        joint,
                        direction: direction.signum(),
                    }
                };
                Ok(())
            }
            ArmCommand::Stop { joint } => {
                self.safety
                    .stop_joint(validate_joint(joint)?, now)
                    .map_err(|()| ControllerError::InvalidJoint)?;
                self.refresh_mode_from_motion();
                Ok(())
            }
            ArmCommand::StopAll => {
                self.safety.stop_all(now);
                self.mode = ArmMode::Idle;
                Ok(())
            }
            ArmCommand::GotoTicks(ticks) => self.goto_ticks(ticks, now),
            ArmCommand::GotoAngles(angles) => self.goto_angles(angles, now),
            ArmCommand::GotoCoords { x, y, z } => self.goto_coords(x, y, z, now),
            ArmCommand::GotoPose {
                x,
                y,
                z,
                tool_phi_rad,
            } => self.goto_pose(x, y, z, tool_phi_rad, now),
            ArmCommand::Hold => self.hold(now),
            ArmCommand::SetJointTick { joint, tick } => self.set_joint_tick(joint, tick, now),
            ArmCommand::SetJointAngle { joint, angle_rad } => {
                self.set_joint_angle(joint, angle_rad, now)
            }
            ArmCommand::SetServoAngle {
                servo_id,
                angle_rad,
                speed,
            } => self.set_servo_angle(servo_id, angle_rad, speed, now),
            ArmCommand::SetTickLimits { joint, min, max } => self.set_tick_limits(joint, min, max),
            ArmCommand::SetTickLimitsEnabled { joint, enabled } => {
                let joint = validate_joint(joint)?;
                self.safety.joints[joint].limit_enabled = enabled;
                Ok(())
            }
            ArmCommand::ClearFaults { joint } => {
                self.safety
                    .clear_faults(joint.map(validate_joint).transpose()?)
                    .map_err(|()| ControllerError::InvalidJoint)?;
                self.refresh_mode_from_motion();
                Ok(())
            }
            ArmCommand::SetServoIds(servo_ids) => {
                for (index, servo_id) in servo_ids.iter().copied().enumerate() {
                    self.joints[index].servo_id = servo_id;
                    self.safety.joints[index].servo_id = servo_id;
                }
                Ok(())
            }
        }
    }

    fn record_feedback_tick(
        &mut self,
        joint: usize,
        tick: i32,
        now: u64,
    ) -> Result<(), ControllerError> {
        self.safety
            .record_feedback(validate_joint(joint)?, tick, now)
            .map_err(|()| ControllerError::InvalidJoint)
    }

    fn record_feedback_failure(&mut self, joint: usize) -> Result<(), ControllerError> {
        self.safety
            .record_feedback_error(validate_joint(joint)?)
            .map_err(|()| ControllerError::InvalidJoint)
    }

    fn mark_speed_sent(
        &mut self,
        joint: usize,
        speed: i16,
        now: u64,
    ) -> Result<(), ControllerError> {
        self.safety
            .mark_speed_sent(validate_joint(joint)?, speed, now)
            .map_err(|()| ControllerError::InvalidJoint)
    }

    fn current_angles(&self) -> Result<[f64; JOINT_COUNT], ControllerError> {
        let mut out = [0.0; JOINT_COUNT];
        for (index, angle) in out.iter_mut().enumerate() {
            *angle = self.joint_angle(index)?;
        }
        Ok(out)
    }

    fn joint_angle(&self, joint: usize) -> Result<f64, ControllerError> {
        let joint = validate_joint(joint)?;
        let tick = self.safety.joints[joint]
            .tick
            .ok_or(ControllerError::MissingFeedback)?;
        Ok(tick_to_angle(&self.joints[joint], tick))
    }

    fn current_coords(&self) -> Result<(f64, f64, f64), ControllerError> {
        let angles = self.current_angles()?;
        Ok(kinematics::fk(angles[0], angles[1], angles[2], angles[3]))
    }

    fn goto_ticks(&mut self, ticks: [i32; JOINT_COUNT], now: u64) -> Result<(), ControllerError> {
        self.safety
            .goto_ticks(&ticks, now)
            .map_err(|()| ControllerError::InvalidJoint)?;
        self.mode = ArmMode::TrackingTicks { targets: ticks };
        Ok(())
    }

    fn goto_angles(&mut self, angles: [f64; JOINT_COUNT], now: u64) -> Result<(), ControllerError> {
        let ticks = core::array::from_fn(|index| angle_to_tick(&self.joints[index], angles[index]));
        self.goto_ticks(ticks, now)
    }

    fn goto_coords(&mut self, x: f64, y: f64, z: f64, now: u64) -> Result<(), ControllerError> {
        let angles = kinematics::solve_coords_tool_down(x, y, z)?;
        self.goto_angles([angles.0, angles.1, angles.2, angles.3], now)
    }

    fn goto_pose(
        &mut self,
        x: f64,
        y: f64,
        z: f64,
        tool_phi_rad: f64,
        now: u64,
    ) -> Result<(), ControllerError> {
        let angles = kinematics::solve_coords_with_tool_pitch(x, y, z, tool_phi_rad)?;
        self.goto_angles([angles.0, angles.1, angles.2, angles.3], now)
    }

    fn hold(&mut self, now: u64) -> Result<(), ControllerError> {
        let mut ticks = [0; JOINT_COUNT];
        for (index, tick) in ticks.iter_mut().enumerate() {
            *tick = self.safety.joints[index]
                .tick
                .ok_or(ControllerError::MissingFeedback)?;
        }
        self.safety
            .goto_ticks(&ticks, now)
            .map_err(|()| ControllerError::InvalidJoint)?;
        self.mode = ArmMode::Holding { targets: ticks };
        Ok(())
    }

    fn set_joint_tick(&mut self, joint: usize, tick: i32, now: u64) -> Result<(), ControllerError> {
        let joint = validate_joint(joint)?;
        let mut ticks = [0; JOINT_COUNT];
        for (index, target_tick) in ticks.iter_mut().enumerate() {
            *target_tick = self.safety.joints[index]
                .tick
                .ok_or(ControllerError::MissingFeedback)?;
        }
        ticks[joint] = tick;
        self.goto_ticks(ticks, now)
    }

    fn set_joint_angle(
        &mut self,
        joint: usize,
        angle_rad: f64,
        now: u64,
    ) -> Result<(), ControllerError> {
        let joint = validate_joint(joint)?;
        let mut ticks = [0; JOINT_COUNT];
        for (index, target_tick) in ticks.iter_mut().enumerate() {
            *target_tick = self.safety.joints[index]
                .tick
                .ok_or(ControllerError::MissingFeedback)?;
        }
        ticks[joint] = angle_to_tick(&self.joints[joint], angle_rad);
        self.goto_ticks(ticks, now)
    }

    fn set_servo_angle(
        &mut self,
        servo_id: u8,
        angle_rad: f64,
        speed: i16,
        now: u64,
    ) -> Result<(), ControllerError> {
        let joint = self
            .joints
            .iter()
            .position(|joint| joint.servo_id == servo_id)
            .ok_or(ControllerError::InvalidJoint)?;
        self.safety.set_default_speed(speed, now);
        self.set_joint_angle(joint, angle_rad, now)
    }

    fn set_tick_limits(&mut self, joint: usize, min: i32, max: i32) -> Result<(), ControllerError> {
        let joint = validate_joint(joint)?;
        if min == max {
            return Err(ControllerError::InvalidLimit);
        }

        self.joints[joint].tick_min = min;
        self.joints[joint].tick_max = max;
        self.safety.joints[joint].tick_min = min;
        self.safety.joints[joint].tick_max = max;
        Ok(())
    }

    fn refresh_mode_from_motion(&mut self) {
        if self.safety.last_error.is_some() {
            self.mode = ArmMode::Fault;
            return;
        }

        if let Some(targets) = current_targets(&self.safety) {
            self.mode = ArmMode::TrackingTicks { targets };
            return;
        }

        if let Some((joint, direction)) = active_jog(&self.safety) {
            self.mode = ArmMode::Jogging { joint, direction };
            return;
        }

        self.mode = ArmMode::Idle;
    }
}
