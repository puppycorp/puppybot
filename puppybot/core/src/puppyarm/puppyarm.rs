use core::f64::consts::PI;

use super::{
    kinematics,
    servo_safety::{
        self, ELBOW_TICK_MAX, ELBOW_TICK_MIN, SHOULDER_TICK_MAX, SHOULDER_TICK_MIN, SafetyFault,
        SpeedCommand, TICK_WRAP, TIP_TICK_MAX, TIP_TICK_MIN, YAW_TICK_MAX, YAW_TICK_MIN,
    },
};
use crate::{
    config::{ConfigError, JointCalibration, PuppyArmConfig},
    stservo::{MAX_SERVO_ID, MIN_SERVO_ID, Mode},
};

pub use super::types::{
    ArmCommand, ArmMode, ControllerError, JOINT_COUNT, Joint, PuppyarmTelemetry, TcpFrame,
};

const YAW_SIGN: f64 = 1.0;
const SHOULDER_SIGN: f64 = -1.0;
const SHOULDER_DRIVE_SIGN: i8 = 1;
const ELBOW_SIGN: f64 = -1.0;
const ELBOW_DRIVE_SIGN: i8 = 1;
const TIP_SIGN: f64 = 1.0;

const YAW_ZERO_TICK: i32 = 2048;
const SHOULDER_ZERO_TICK: i32 = 530;
const ELBOW_ZERO_TICK: i32 = 3565;
const TIP_ZERO_TICK: i32 = 1783;

const WHEEL_MODE_RECOVERY_RETRY_MS: u64 = 1000;
const WHEEL_MODE_NEVER_ATTEMPTED: u64 = u64::MAX;
const CARTESIAN_TOOL_PHI_SEARCH_STEPS: usize = 181;
const CARTESIAN_CURRENT_POSITION_TOLERANCE_MM: f64 = 1.0;
const SHOULDER_Z_TABLE_FLOOR_MM: f64 = -kinematics::Z_ORIGIN_MM;

fn current_targets(joints: &[Joint; JOINT_COUNT]) -> Option<[i32; JOINT_COUNT]> {
    let mut targets = [0; JOINT_COUNT];
    for (index, joint) in joints.iter().enumerate() {
        targets[index] = joint.target_tick?;
    }
    Some(targets)
}

fn target_angles(joints: &[Joint; JOINT_COUNT]) -> Option<[f64; JOINT_COUNT]> {
    let mut angles = [0.0; JOINT_COUNT];
    for (index, joint) in joints.iter().enumerate() {
        let angle = joint.target_angle_rad?;
        if !angle.is_finite() {
            return None;
        }
        angles[index] = angle;
    }
    Some(angles)
}

fn table_coords(coords: (f64, f64, f64)) -> (f32, f32, f32) {
    (
        coords.0 as f32,
        coords.1 as f32,
        super::kinematics::shoulder_to_table_z(coords.2) as f32,
    )
}

fn active_jog(joints: &[Joint; JOINT_COUNT]) -> Option<(usize, i8)> {
    for (index, joint) in joints.iter().enumerate() {
        if joint.target_tick.is_none() && joint.speed != 0 {
            return Some((index, joint.speed.signum() as i8));
        }
    }
    None
}

fn vector_length(vector: [f64; 3]) -> f64 {
    libm::sqrt(vector[0] * vector[0] + vector[1] * vector[1] + vector[2] * vector[2])
}

fn default_joints() -> [Joint; JOINT_COUNT] {
    [
        Joint {
            servo_id: 1,
            tick_min: YAW_TICK_MIN,
            tick_max: YAW_TICK_MAX,
            raw_tick_min: 0,
            raw_tick_max: TICK_WRAP - 1,
            sign: YAW_SIGN,
            drive_sign: 1,
            reference_tick: YAW_ZERO_TICK,
            reference_angle_rad: 0.0,
            zero_offset_rad: zero_offset_from_reference(
                YAW_ZERO_TICK,
                0,
                TICK_WRAP - 1,
                YAW_SIGN,
                0.0,
            ),
            online: false,
            has_feedback: false,
            limit_reached: false,
            tick: None,
            angle_rad: None,
            target_tick: None,
            target_angle_rad: None,
            tick_delta: 0,
            limit_enabled: true,
            speed: 0,
            limit_min: YAW_TICK_MIN,
            limit_max: YAW_TICK_MAX,
            last_feedback_ms: 0,
            temp_c: None,
            last_sent_speed: None,
            last_speed_cmd_ms: 0,
            stall_since_ms: None,
            fault: None,
        },
        Joint {
            servo_id: 2,
            tick_min: SHOULDER_TICK_MIN,
            tick_max: SHOULDER_TICK_MAX,
            raw_tick_min: 0,
            raw_tick_max: TICK_WRAP - 1,
            sign: SHOULDER_SIGN,
            drive_sign: SHOULDER_DRIVE_SIGN,
            reference_tick: SHOULDER_ZERO_TICK,
            reference_angle_rad: PI / 2.0,
            zero_offset_rad: zero_offset_from_reference(
                SHOULDER_ZERO_TICK,
                0,
                TICK_WRAP - 1,
                SHOULDER_SIGN,
                PI / 2.0,
            ),
            online: false,
            has_feedback: false,
            limit_reached: false,
            tick: None,
            angle_rad: None,
            target_tick: None,
            target_angle_rad: None,
            tick_delta: 0,
            limit_enabled: true,
            speed: 0,
            limit_min: SHOULDER_TICK_MIN,
            limit_max: SHOULDER_TICK_MAX,
            last_feedback_ms: 0,
            temp_c: None,
            last_sent_speed: None,
            last_speed_cmd_ms: 0,
            stall_since_ms: None,
            fault: None,
        },
        Joint {
            servo_id: 3,
            tick_min: ELBOW_TICK_MIN,
            tick_max: ELBOW_TICK_MAX,
            raw_tick_min: 0,
            raw_tick_max: TICK_WRAP - 1,
            sign: ELBOW_SIGN,
            drive_sign: ELBOW_DRIVE_SIGN,
            reference_tick: ELBOW_ZERO_TICK,
            reference_angle_rad: 0.0,
            zero_offset_rad: zero_offset_from_reference(
                ELBOW_ZERO_TICK,
                0,
                TICK_WRAP - 1,
                ELBOW_SIGN,
                0.0,
            ),
            online: false,
            has_feedback: false,
            limit_reached: false,
            tick: None,
            angle_rad: None,
            target_tick: None,
            target_angle_rad: None,
            tick_delta: 0,
            limit_enabled: true,
            speed: 0,
            limit_min: ELBOW_TICK_MIN,
            limit_max: ELBOW_TICK_MAX,
            last_feedback_ms: 0,
            temp_c: None,
            last_sent_speed: None,
            last_speed_cmd_ms: 0,
            stall_since_ms: None,
            fault: None,
        },
        Joint {
            servo_id: 4,
            tick_min: TIP_TICK_MIN,
            tick_max: TIP_TICK_MAX,
            raw_tick_min: 0,
            raw_tick_max: TICK_WRAP - 1,
            sign: TIP_SIGN,
            drive_sign: 1,
            reference_tick: TIP_ZERO_TICK,
            reference_angle_rad: 0.0,
            zero_offset_rad: zero_offset_from_reference(
                TIP_ZERO_TICK,
                0,
                TICK_WRAP - 1,
                TIP_SIGN,
                0.0,
            ),
            online: false,
            has_feedback: false,
            limit_reached: false,
            tick: None,
            angle_rad: None,
            target_tick: None,
            target_angle_rad: None,
            tick_delta: 0,
            limit_enabled: true,
            speed: 0,
            limit_min: TIP_TICK_MIN,
            limit_max: TIP_TICK_MAX,
            last_feedback_ms: 0,
            temp_c: None,
            last_sent_speed: None,
            last_speed_cmd_ms: 0,
            stall_since_ms: None,
            fault: None,
        },
    ]
}

fn joint_from_calibration(calibration: JointCalibration) -> Joint {
    let mut joint = Joint::new(
        calibration.servo_id,
        calibration.tick_min,
        calibration.tick_max,
    );
    joint.raw_tick_min = 0;
    joint.raw_tick_max = TICK_WRAP - 1;
    joint.sign = calibration.angle_sign as f64;
    joint.drive_sign = calibration.drive_sign;
    joint.reference_tick = calibration.reference_tick;
    joint.reference_angle_rad = calibration.reference_angle_rad;
    joint.zero_offset_rad = zero_offset_from_reference(
        calibration.reference_tick,
        joint.raw_tick_min,
        joint.raw_tick_max,
        joint.sign,
        calibration.reference_angle_rad,
    );
    joint.online = false;
    joint.limit_enabled = calibration.limit_enabled;
    joint.limit_min = calibration.tick_min;
    joint.limit_max = calibration.tick_max;
    joint
}

fn configured_joints(config: &PuppyArmConfig) -> [Joint; JOINT_COUNT] {
    core::array::from_fn(|index| joint_from_calibration(config.joints[index]))
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

fn default_arm_state(now_ms: u64) -> ([Joint; JOINT_COUNT], ArmMode) {
    let mut joints = default_joints();
    servo_safety::init_joints(&mut joints, now_ms);

    (joints, ArmMode::Idle)
}

fn configured_arm_state(
    config: &PuppyArmConfig,
    now_ms: u64,
) -> Result<([Joint; JOINT_COUNT], ArmMode), ConfigError> {
    config.validate()?;
    let mut joints = configured_joints(config);
    servo_safety::init_joints(&mut joints, now_ms);

    Ok((joints, ArmMode::Idle))
}

pub struct PuppyArm {
    pub joints: [Joint; JOINT_COUNT],
    default_speed: i16,
    last_cmd_ms: u64,
    last_ok_feedback_ms: u64,
    last_error: Option<SafetyFault>,
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
        let (joints, mode) = default_arm_state(now);
        Self {
            joints,
            default_speed: 200,
            last_cmd_ms: now,
            last_ok_feedback_ms: now,
            last_error: None,
            mode,
            wheel_servo_ids: core::array::from_fn(|index| joints[index].servo_id),
            wheel_mode_ready: [false; JOINT_COUNT],
            wheel_mode_last_attempt_ms: [WHEEL_MODE_NEVER_ATTEMPTED; JOINT_COUNT],
            queued_initial_wheel_mode: false,
        }
    }

    pub fn new_with_config(config: &PuppyArmConfig, now: u64) -> Result<Self, ConfigError> {
        let (joints, mode) = configured_arm_state(config, now)?;
        Ok(Self {
            joints,
            default_speed: 200,
            last_cmd_ms: now,
            last_ok_feedback_ms: now,
            last_error: None,
            mode,
            wheel_servo_ids: core::array::from_fn(|index| joints[index].servo_id),
            wheel_mode_ready: [false; JOINT_COUNT],
            wheel_mode_last_attempt_ms: [WHEEL_MODE_NEVER_ATTEMPTED; JOINT_COUNT],
            queued_initial_wheel_mode: false,
        })
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

        let was_online = self.joints[joint].online;
        let _ = self.record_feedback_tick(joint, tick as i32, now);
        if !was_online {
            self.mark_wheel_mode_not_ready(joint);
        }
    }

    pub fn joint_servo_id(&self, joint: usize) -> Option<u8> {
        self.joints.get(joint).map(|joint| joint.servo_id)
    }

    pub fn record_feedback_error(&mut self, joint: usize) {
        if joint >= JOINT_COUNT {
            return;
        }

        let _ = self.record_feedback_failure(joint);
        self.mark_wheel_mode_not_ready(joint);
    }

    pub fn record_temperature(&mut self, joint: usize, temp_c: Option<u8>) {
        if joint >= JOINT_COUNT {
            return;
        }

        self.joints[joint].set_temperature(temp_c);
    }

    pub fn take_initialize_wheel_mode(&mut self) -> bool {
        if self.queued_initial_wheel_mode {
            return false;
        }

        self.queued_initial_wheel_mode = true;
        true
    }

    pub fn update(&mut self, now: u64) -> [SpeedCommand; JOINT_COUNT] {
        self.advance_tcp_jog(now);
        let tcp_jog_targets = if matches!(self.mode, ArmMode::TcpJogging { .. }) {
            current_targets(&self.joints)
        } else {
            None
        };
        let commands = self.speed_commands(now);
        if self.last_error.is_none() {
            if let Some(targets) = tcp_jog_targets {
                for (joint, target) in targets.into_iter().enumerate() {
                    self.set_joint_target_tick(joint, target);
                }
            }
        }
        self.refresh_mode_from_motion();
        commands
    }

    pub fn mode(&self) -> ArmMode {
        self.mode
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
        PuppyarmTelemetry {
            seq,
            joints: core::array::from_fn(|index| {
                let mut joint = self.joints[index];
                joint.has_feedback = joint.has_feedback && joint.tick.is_some();
                joint.limit_reached = servo_safety::is_outside_limits(&joint);
                joint.limit_min = joint.tick_min;
                joint.limit_max = joint.tick_max;
                joint
            }),
            coords_mm: self.coords_mm(),
            target_coords_mm: self.target_coords_mm(),
        }
    }

    pub fn handle_arm_cmd(&mut self, command: ArmCommand, now: u64) {
        if let Err(err) = self.try_handle_arm_cmd(command, now) {
            log::warn!("arm intent rejected: {:?}", err);
        }
    }

    pub fn try_handle_arm_cmd(
        &mut self,
        command: ArmCommand,
        now: u64,
    ) -> Result<(), ControllerError> {
        if let ArmCommand::SetServoIds(_) = command {
            let ArmCommand::SetServoIds(servo_ids) = command else {
                unreachable!();
            };
            if !valid_servo_ids(&servo_ids) {
                return Err(ControllerError::InvalidServoIds);
            }
            if self
                .handle_command(ArmCommand::SetServoIds(servo_ids), now)
                .is_ok()
            {
                self.sync_wheel_servo_ids();
                self.mark_all_wheel_modes_not_ready();
                self.queued_initial_wheel_mode = false;
                Ok(())
            } else {
                Err(ControllerError::InvalidServoIds)
            }
        } else {
            self.handle_command(command, now)
        }
    }

    fn handle_command(&mut self, command: ArmCommand, now: u64) -> Result<(), ControllerError> {
        match command {
            ArmCommand::SetSpeed(speed) => {
                self.set_default_speed(speed, now);
                Ok(())
            }
            ArmCommand::Spin { joint, direction } => {
                self.spin(joint, direction, now)?;
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
                self.stop_joint(joint, now)?;
                self.refresh_mode_from_motion();
                Ok(())
            }
            ArmCommand::StopAll => {
                self.stop_all(now);
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
            ArmCommand::MoveTcpRelative {
                frame,
                dx_mm,
                dy_mm,
                dz_mm,
            } => self.move_tcp_relative(frame, dx_mm, dy_mm, dz_mm, now),
            ArmCommand::StartTcpJog {
                frame,
                direction,
                speed_mm_s,
            } => self.start_tcp_jog(frame, direction, speed_mm_s, now),
            ArmCommand::StopTcpJog => {
                self.stop_all(now);
                self.mode = ArmMode::Idle;
                Ok(())
            }
            ArmCommand::Hold => self.hold(now),
            ArmCommand::SetJointTick { joint, tick } => self.set_joint_tick(joint, tick, now),
            ArmCommand::SetJointAngle { joint, angle_rad } => {
                self.set_joint_angle(joint, angle_rad, now)
            }
            ArmCommand::SetJointReference {
                joint,
                tick,
                angle_rad,
            } => self.set_joint_reference(joint, tick, angle_rad, now),
            ArmCommand::SetServoAngle {
                servo_id,
                angle_rad,
                speed,
            } => self.set_servo_angle(servo_id, angle_rad, speed, now),
            ArmCommand::SetTickLimits { joint, min, max } => self.set_tick_limits(joint, min, max),
            ArmCommand::SetTickLimitsEnabled { joint, enabled } => {
                let joint = validate_joint(joint)?;
                self.joints[joint].limit_enabled = enabled;
                Ok(())
            }
            ArmCommand::ClearFaults { joint } => {
                self.clear_faults(joint.map(validate_joint).transpose()?);
                self.refresh_mode_from_motion();
                Ok(())
            }
            ArmCommand::SetServoIds(servo_ids) => {
                for (index, servo_id) in servo_ids.iter().copied().enumerate() {
                    self.joints[index].servo_id = servo_id;
                }
                Ok(())
            }
        }
    }

    fn set_default_speed(&mut self, speed: i16, now: u64) {
        self.default_speed = speed.abs();
        self.last_cmd_ms = now;
    }

    fn start_tcp_jog(
        &mut self,
        frame: TcpFrame,
        direction: [f64; 3],
        speed_mm_s: f64,
        now: u64,
    ) -> Result<(), ControllerError> {
        if !speed_mm_s.is_finite() || speed_mm_s <= 0.0 {
            return Err(ControllerError::InvalidLimit);
        }
        if !direction.iter().all(|component| component.is_finite()) {
            return Err(ControllerError::InvalidLimit);
        }
        let length = vector_length(direction);
        if length <= f64::EPSILON {
            return Err(ControllerError::InvalidLimit);
        }
        let target_angles = self.target_or_current_angles()?;
        self.mode = ArmMode::TcpJogging {
            frame,
            direction: [
                direction[0] / length,
                direction[1] / length,
                direction[2] / length,
            ],
            speed_mm_s,
            last_step_ms: now,
            target_angles,
        };
        self.last_cmd_ms = now;
        Ok(())
    }

    fn spin(&mut self, joint: usize, direction: i8, now: u64) -> Result<(), ControllerError> {
        let joint = validate_joint(joint)?;
        self.joints[joint].spin(direction, self.default_speed);
        self.last_cmd_ms = now;
        Ok(())
    }

    fn stop_joint(&mut self, joint: usize, now: u64) -> Result<(), ControllerError> {
        let joint = validate_joint(joint)?;
        self.joints[joint].stop();
        self.last_cmd_ms = now;
        Ok(())
    }

    fn stop_all(&mut self, now: u64) {
        for joint in &mut self.joints {
            joint.stop();
        }
        self.last_cmd_ms = now;
    }

    fn clear_faults(&mut self, joint: Option<usize>) {
        if let Some(index) = joint {
            self.joints[index].clear_fault();
        } else {
            for joint in &mut self.joints {
                joint.clear_fault();
            }
            self.last_error = None;
        }
    }

    fn record_feedback_tick(
        &mut self,
        joint: usize,
        tick: i32,
        now: u64,
    ) -> Result<(), ControllerError> {
        let joint = validate_joint(joint)?;
        self.joints[joint].record_feedback(tick, now);
        self.refresh_joint_angle_cache(joint);
        self.last_ok_feedback_ms = now;
        Ok(())
    }

    fn record_feedback_failure(&mut self, joint: usize) -> Result<(), ControllerError> {
        let joint = validate_joint(joint)?;
        self.joints[joint].record_feedback_error();
        Ok(())
    }

    fn refresh_joint_angle_cache(&mut self, joint: usize) {
        if joint >= JOINT_COUNT {
            return;
        }

        let angle_rad = self.joints[joint]
            .tick
            .map(|tick| tick_to_angle(&self.joints[joint], tick));
        let target_angle_rad = self.joints[joint]
            .target_tick
            .map(|tick| tick_to_angle(&self.joints[joint], tick));

        self.joints[joint].angle_rad = angle_rad.filter(|angle| angle.is_finite());
        self.joints[joint].target_angle_rad = target_angle_rad.filter(|angle| angle.is_finite());
    }

    fn set_joint_target_tick(&mut self, joint: usize, tick: i32) {
        if joint >= JOINT_COUNT {
            return;
        }

        let clipped_tick = servo_safety::clip_tick_to_joint_limits(&self.joints[joint], tick);
        self.joints[joint].target_tick = Some(clipped_tick);
        self.refresh_joint_angle_cache(joint);
    }

    fn mark_speed_sent(
        &mut self,
        joint: usize,
        speed: i16,
        now: u64,
    ) -> Result<(), ControllerError> {
        let joint = validate_joint(joint)?;
        self.joints[joint].last_sent_speed = Some(speed);
        self.joints[joint].last_speed_cmd_ms = now;
        Ok(())
    }

    fn speed_commands(&mut self, now: u64) -> [SpeedCommand; JOINT_COUNT] {
        if let Some(reason) = servo_safety::deadman_reason(
            &self.joints,
            self.last_cmd_ms,
            self.last_ok_feedback_ms,
            now,
        ) {
            servo_safety::force_stop(&mut self.joints, &mut self.last_error, reason);
        }

        core::array::from_fn(|index| {
            let desired =
                servo_safety::compute_safe_speed(&mut self.joints[index], self.default_speed, now);
            let should_send = self.joints[index].last_sent_speed != Some(desired);
            SpeedCommand {
                servo_id: self.joints[index].servo_id,
                speed: desired,
                should_send,
            }
        })
    }

    fn current_angles(&self) -> Result<[f64; JOINT_COUNT], ControllerError> {
        let mut out = [0.0; JOINT_COUNT];
        for (index, angle) in out.iter_mut().enumerate() {
            *angle = self.joint_angle(index)?;
        }
        Ok(out)
    }

    fn target_or_current_angles(&self) -> Result<[f64; JOINT_COUNT], ControllerError> {
        target_angles(&self.joints).map_or_else(|| self.current_angles(), Ok)
    }

    fn joint_angle(&self, joint: usize) -> Result<f64, ControllerError> {
        let joint = validate_joint(joint)?;
        self.joints[joint]
            .angle_rad
            .ok_or(ControllerError::MissingFeedback)
    }

    fn current_coords(&self) -> Result<(f64, f64, f64), ControllerError> {
        let angles = self.current_angles()?;
        Ok(kinematics::fk(angles[0], angles[1], angles[2], angles[3]))
    }

    pub fn coords_mm(&self) -> Option<(f32, f32, f32)> {
        self.current_coords().ok().map(table_coords)
    }

    pub fn target_coords_mm(&self) -> Option<(f32, f32, f32)> {
        target_angles(&self.joints)
            .map(|angles| table_coords(kinematics::fk(angles[0], angles[1], angles[2], angles[3])))
    }

    fn goto_ticks(&mut self, ticks: [i32; JOINT_COUNT], now: u64) -> Result<(), ControllerError> {
        for (index, tick) in ticks.iter().enumerate() {
            self.joints[index].clear_fault();
            self.set_joint_target_tick(index, *tick);
        }
        self.last_cmd_ms = now;
        self.mode = ArmMode::TrackingTicks { targets: ticks };
        Ok(())
    }

    fn goto_angles(&mut self, angles: [f64; JOINT_COUNT], now: u64) -> Result<(), ControllerError> {
        let ticks = self.angles_to_ticks(angles);
        self.goto_ticks(ticks, now)
    }

    fn goto_coords(&mut self, x: f64, y: f64, z: f64, now: u64) -> Result<(), ControllerError> {
        if z < SHOULDER_Z_TABLE_FLOOR_MM {
            return Err(ControllerError::Ik(kinematics::IkError::Unreachable));
        }
        if let Ok((current_x, current_y, current_z)) = self.current_coords() {
            let distance_mm = libm::sqrt(
                (x - current_x) * (x - current_x)
                    + (y - current_y) * (y - current_y)
                    + (z - current_z) * (z - current_z),
            );
            if distance_mm <= CARTESIAN_CURRENT_POSITION_TOLERANCE_MM {
                return self.goto_checked_angles(self.current_angles()?, now);
            }
        }

        let angles = self.solve_coords_with_wrist_search(x, y, z)?;
        self.goto_checked_angles(angles, now)
    }

    fn goto_pose(
        &mut self,
        x: f64,
        y: f64,
        z: f64,
        tool_phi_rad: f64,
        now: u64,
    ) -> Result<(), ControllerError> {
        if z < SHOULDER_Z_TABLE_FLOOR_MM {
            return Err(ControllerError::Ik(kinematics::IkError::Unreachable));
        }
        let angles = kinematics::solve_coords_with_tool_pitch(x, y, z, tool_phi_rad)?;
        self.goto_checked_angles([angles.0, angles.1, angles.2, angles.3], now)
    }

    fn angles_to_ticks(&self, angles: [f64; JOINT_COUNT]) -> [i32; JOINT_COUNT] {
        core::array::from_fn(|index| angle_to_tick(&self.joints[index], angles[index]))
    }

    fn ticks_within_joint_limits(&self, ticks: &[i32; JOINT_COUNT]) -> bool {
        self.joints
            .iter()
            .zip(ticks.iter())
            .all(|(joint, tick)| servo_safety::tick_within_joint_limits(joint, *tick))
    }

    fn angles_within_joint_limits(&self, angles: [f64; JOINT_COUNT]) -> bool {
        self.ticks_within_joint_limits(&self.angles_to_ticks(angles))
    }

    fn goto_checked_angles(
        &mut self,
        angles: [f64; JOINT_COUNT],
        now: u64,
    ) -> Result<(), ControllerError> {
        let ticks = self.angles_to_ticks(angles);
        if !self.ticks_within_joint_limits(&ticks) {
            return Err(ControllerError::Ik(kinematics::IkError::Unreachable));
        }
        self.goto_ticks(ticks, now)
    }

    fn solve_coords_with_wrist_search(
        &self,
        x: f64,
        y: f64,
        z: f64,
    ) -> Result<[f64; JOINT_COUNT], ControllerError> {
        let result = kinematics::ik(x, y, z);
        if !result.reachable {
            return Err(ControllerError::Ik(kinematics::IkError::Unreachable));
        }

        let base = [result.yaw, result.shoulder, result.elbow];
        let tool_down = Self::coords_candidate_angles(base, kinematics::ARM_TOOL_PHI_RAD);
        if self.angles_within_joint_limits(tool_down) {
            return Ok(tool_down);
        }

        let step = 2.0 * PI / CARTESIAN_TOOL_PHI_SEARCH_STEPS as f64;
        for offset in 1..=CARTESIAN_TOOL_PHI_SEARCH_STEPS / 2 + 1 {
            let offset = offset as f64 * step;
            for direction in [-1.0, 1.0] {
                let tool_phi_rad =
                    kinematics::wrap_pi(kinematics::ARM_TOOL_PHI_RAD + direction * offset);
                let result = kinematics::ik_with_tool_pitch(x, y, z, tool_phi_rad);
                if !result.reachable {
                    continue;
                }
                let angles = [result.yaw, result.shoulder, result.elbow, result.wrist];
                if self.angles_within_joint_limits(angles) {
                    return Ok(angles);
                }
            }
        }

        Err(ControllerError::Ik(kinematics::IkError::Unreachable))
    }

    fn coords_candidate_angles(base: [f64; 3], tool_phi_rad: f64) -> [f64; JOINT_COUNT] {
        [
            base[0],
            base[1],
            base[2],
            kinematics::solve_tip_angle_down(base[1], base[2], tool_phi_rad),
        ]
    }

    fn move_tcp_relative(
        &mut self,
        frame: TcpFrame,
        dx_mm: f64,
        dy_mm: f64,
        dz_mm: f64,
        now: u64,
    ) -> Result<(), ControllerError> {
        let angles = self.target_or_current_angles()?;
        self.move_tcp_relative_from_angles(angles, frame, dx_mm, dy_mm, dz_mm, now)
            .map(|_| ())
    }

    fn move_tcp_relative_from_angles(
        &mut self,
        angles: [f64; JOINT_COUNT],
        frame: TcpFrame,
        dx_mm: f64,
        dy_mm: f64,
        dz_mm: f64,
        now: u64,
    ) -> Result<[f64; JOINT_COUNT], ControllerError> {
        let tool_phi = kinematics::tool_pitch(angles[1], angles[2], angles[3]);
        let (x, y, z_shoulder) = kinematics::fk(angles[0], angles[1], angles[2], angles[3]);
        let (dx, dy, dz) = match frame {
            TcpFrame::Base => (dx_mm, dy_mm, dz_mm),
            TcpFrame::YawFlat => Self::yaw_flat_delta_to_base_delta(angles, dx_mm, dy_mm, dz_mm),
            TcpFrame::Tool => Self::tool_delta_to_base_delta(angles, dx_mm, dy_mm, dz_mm),
        };
        let z_table = kinematics::shoulder_to_table_z(z_shoulder);
        let target_z = kinematics::table_to_shoulder_z(z_table + dz);
        match frame {
            TcpFrame::Base | TcpFrame::YawFlat => {
                self.goto_pose(x + dx, y + dy, target_z, tool_phi, now)?
            }
            TcpFrame::Tool => self.goto_pose(x + dx, y + dy, target_z, tool_phi, now)?,
        };
        if matches!(frame, TcpFrame::Base | TcpFrame::YawFlat)
            && dx_mm.abs() <= f64::EPSILON
            && dy_mm.abs() <= f64::EPSILON
        {
            self.set_joint_target_tick(0, angle_to_tick(&self.joints[0], angles[0]));
        }
        target_angles(&self.joints).ok_or(ControllerError::MissingFeedback)
    }

    fn jog_tcp_relative_from_angles(
        &mut self,
        angles: [f64; JOINT_COUNT],
        frame: TcpFrame,
        dx_mm: f64,
        dy_mm: f64,
        dz_mm: f64,
        now: u64,
    ) -> Result<[f64; JOINT_COUNT], ControllerError> {
        match self.move_tcp_relative_from_angles(angles, frame, dx_mm, dy_mm, dz_mm, now) {
            Ok(angles) => Ok(angles),
            Err(_err) if matches!(frame, TcpFrame::Base | TcpFrame::YawFlat) => {
                let (x, y, z_shoulder) = kinematics::fk(angles[0], angles[1], angles[2], angles[3]);
                let (dx, dy, dz) = match frame {
                    TcpFrame::Base => (dx_mm, dy_mm, dz_mm),
                    TcpFrame::YawFlat => {
                        Self::yaw_flat_delta_to_base_delta(angles, dx_mm, dy_mm, dz_mm)
                    }
                    TcpFrame::Tool => unreachable!("tool frame excluded above"),
                };
                let z_table = kinematics::shoulder_to_table_z(z_shoulder);
                let target_z = kinematics::table_to_shoulder_z(z_table + dz);
                let solved = self.solve_coords_with_wrist_search(x + dx, y + dy, target_z)?;
                self.goto_checked_angles(solved, now)?;
                if dx_mm.abs() <= f64::EPSILON && dy_mm.abs() <= f64::EPSILON {
                    self.set_joint_target_tick(0, angle_to_tick(&self.joints[0], angles[0]));
                }
                target_angles(&self.joints).ok_or(ControllerError::MissingFeedback)
            }
            Err(err) => Err(err),
        }
    }

    fn advance_tcp_jog(&mut self, now: u64) {
        let ArmMode::TcpJogging {
            frame,
            direction,
            speed_mm_s,
            last_step_ms,
            target_angles,
        } = self.mode
        else {
            return;
        };

        let elapsed_ms = now.saturating_sub(last_step_ms);
        if elapsed_ms == 0 {
            return;
        }
        let step_mm = speed_mm_s * elapsed_ms as f64 / 1000.0;
        let result = self.jog_tcp_relative_from_angles(
            target_angles,
            frame,
            direction[0] * step_mm,
            direction[1] * step_mm,
            direction[2] * step_mm,
            now,
        );
        if result.is_ok() {
            self.mode = ArmMode::TcpJogging {
                frame,
                direction,
                speed_mm_s,
                last_step_ms: now,
                target_angles: result.expect("checked ok above"),
            };
        } else {
            self.mode = ArmMode::Idle;
            self.refresh_mode_from_motion();
        }
    }

    fn yaw_flat_delta_to_base_delta(
        angles: [f64; JOINT_COUNT],
        dx_mm: f64,
        dy_mm: f64,
        dz_mm: f64,
    ) -> (f64, f64, f64) {
        let yaw = angles[0];
        let cos_yaw = libm::cos(yaw);
        let sin_yaw = libm::sin(yaw);
        (
            dx_mm * cos_yaw - dy_mm * sin_yaw,
            dx_mm * sin_yaw + dy_mm * cos_yaw,
            dz_mm,
        )
    }

    fn tool_delta_to_base_delta(
        angles: [f64; JOINT_COUNT],
        dx_mm: f64,
        dy_mm: f64,
        dz_mm: f64,
    ) -> (f64, f64, f64) {
        let [yaw, shoulder, elbow, wrist] = angles;
        let tool_phi = kinematics::tool_pitch(shoulder, elbow, wrist);
        let cos_yaw = libm::cos(yaw);
        let sin_yaw = libm::sin(yaw);
        let cos_phi = libm::cos(tool_phi);
        let sin_phi = libm::sin(tool_phi);

        let forward = (cos_phi * cos_yaw, cos_phi * sin_yaw, sin_phi);
        let left = (-sin_yaw, cos_yaw, 0.0);
        let up = (
            forward.1 * left.2 - forward.2 * left.1,
            forward.2 * left.0 - forward.0 * left.2,
            forward.0 * left.1 - forward.1 * left.0,
        );

        (
            dx_mm * forward.0 + dy_mm * left.0 + dz_mm * up.0,
            dx_mm * forward.1 + dy_mm * left.1 + dz_mm * up.1,
            dx_mm * forward.2 + dy_mm * left.2 + dz_mm * up.2,
        )
    }

    fn hold(&mut self, now: u64) -> Result<(), ControllerError> {
        let mut ticks = [0; JOINT_COUNT];
        for (index, tick) in ticks.iter_mut().enumerate() {
            *tick = self.joints[index]
                .tick
                .ok_or(ControllerError::MissingFeedback)?;
        }
        for (index, tick) in ticks.iter().enumerate() {
            self.joints[index].clear_fault();
            self.set_joint_target_tick(index, *tick);
        }
        self.last_cmd_ms = now;
        self.mode = ArmMode::Holding { targets: ticks };
        Ok(())
    }

    fn set_joint_tick(&mut self, joint: usize, tick: i32, now: u64) -> Result<(), ControllerError> {
        let joint = validate_joint(joint)?;
        let mut ticks = [0; JOINT_COUNT];
        for (index, target_tick) in ticks.iter_mut().enumerate() {
            *target_tick = self.joints[index]
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
            *target_tick = self.joints[index]
                .tick
                .ok_or(ControllerError::MissingFeedback)?;
        }
        ticks[joint] = angle_to_tick(&self.joints[joint], angle_rad);
        self.goto_ticks(ticks, now)
    }

    fn set_joint_reference(
        &mut self,
        joint: usize,
        tick: i32,
        angle_rad: f64,
        now: u64,
    ) -> Result<(), ControllerError> {
        let joint = validate_joint(joint)?;
        if !angle_rad.is_finite() {
            return Err(ControllerError::InvalidLimit);
        }

        let raw_tick_min = self.joints[joint].raw_tick_min;
        let raw_tick_max = self.joints[joint].raw_tick_max;
        let sign = self.joints[joint].sign;
        if !(0..TICK_WRAP).contains(&tick) {
            return Err(ControllerError::InvalidLimit);
        }

        self.stop_all(now);
        self.mode = ArmMode::Idle;
        self.joints[joint].reference_tick = tick;
        self.joints[joint].reference_angle_rad = angle_rad;
        self.joints[joint].zero_offset_rad =
            zero_offset_from_reference(tick, raw_tick_min, raw_tick_max, sign, angle_rad);
        self.refresh_joint_angle_cache(joint);
        Ok(())
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
        self.set_default_speed(speed, now);
        self.set_joint_angle(joint, angle_rad, now)
    }

    fn set_tick_limits(&mut self, joint: usize, min: i32, max: i32) -> Result<(), ControllerError> {
        let joint = validate_joint(joint)?;
        if min == max {
            return Err(ControllerError::InvalidLimit);
        }

        self.joints[joint].tick_min = min;
        self.joints[joint].tick_max = max;
        Ok(())
    }

    fn refresh_mode_from_motion(&mut self) {
        if self.last_error.is_some() {
            self.mode = ArmMode::Fault;
            return;
        }

        if matches!(self.mode, ArmMode::TcpJogging { .. }) {
            return;
        }

        if let Some(targets) = current_targets(&self.joints) {
            self.mode = ArmMode::TrackingTicks { targets };
            return;
        }

        if let Some((joint, direction)) = active_jog(&self.joints) {
            self.mode = ArmMode::Jogging { joint, direction };
            return;
        }

        self.mode = ArmMode::Idle;
    }
}
