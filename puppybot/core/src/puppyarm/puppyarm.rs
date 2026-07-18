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
    ArmCommand, ArmMode, CartesianJointLimitError, ControllerError, JOINT_COUNT, Joint,
    JointLimitViolation, PuppyarmTelemetry, TcpFrame,
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

/// Keep a held Cartesian jog close enough to observed servo feedback that the
/// arm can follow its visual target.  The desired point remains exact and is
/// never reseeded from quantized feedback; only its forward lead is limited.
pub const MAX_TCP_JOG_TARGET_LEAD_MM: f64 = 8.0;

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

fn tcp_jog_lead_step_fraction(
    current_coords_mm: [f64; 3],
    target_coords_mm: [f64; 3],
    delta_mm: [f64; 3],
) -> f64 {
    let current_lead = [
        target_coords_mm[0] - current_coords_mm[0],
        target_coords_mm[1] - current_coords_mm[1],
        target_coords_mm[2] - current_coords_mm[2],
    ];
    if vector_length(current_lead) >= MAX_TCP_JOG_TARGET_LEAD_MM {
        return 0.0;
    }

    let candidate = [
        current_lead[0] + delta_mm[0],
        current_lead[1] + delta_mm[1],
        current_lead[2] + delta_mm[2],
    ];
    if vector_length(candidate) <= MAX_TCP_JOG_TARGET_LEAD_MM {
        return 1.0;
    }

    // The lead norm is continuous over this line segment.  Find the furthest
    // prefix that keeps the target inside the feedback-lead sphere.
    let mut lo = 0.0;
    let mut hi = 1.0;
    for _ in 0..20 {
        let fraction = (lo + hi) * 0.5;
        let candidate = [
            current_lead[0] + delta_mm[0] * fraction,
            current_lead[1] + delta_mm[1] * fraction,
            current_lead[2] + delta_mm[2] * fraction,
        ];
        if vector_length(candidate) <= MAX_TCP_JOG_TARGET_LEAD_MM {
            lo = fraction;
        } else {
            hi = fraction;
        }
    }
    lo
}

fn branch_continuity_score(
    current_angles: [f64; JOINT_COUNT],
    candidate_angles: [f64; JOINT_COUNT],
) -> f64 {
    let yaw_d = kinematics::angle_distance(current_angles[0], candidate_angles[0]);
    let shoulder_d = kinematics::angle_distance(current_angles[1], candidate_angles[1]);
    let elbow_d = kinematics::angle_distance(current_angles[2], candidate_angles[2]);
    let wrist_d = kinematics::angle_distance(current_angles[3], candidate_angles[3]);
    yaw_d + shoulder_d + 2.0 * elbow_d + 2.0 * wrist_d
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

fn validate_joint(joint: usize) -> Result<usize, ControllerError> {
    if joint < JOINT_COUNT {
        Ok(joint)
    } else {
        Err(ControllerError::InvalidJoint)
    }
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
            effective_target_coords_mm: self.effective_target_coords_mm(),
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
            ArmCommand::GotoCoords {
                x,
                y,
                z,
                tool_phi_rad,
            } => self.goto_coords(x, y, z, tool_phi_rad, now),
            ArmCommand::MoveTcp {
                frame,
                dx_mm,
                dy_mm,
                dz_mm,
            } => self.move_tcp_relative(frame, dx_mm, dy_mm, dz_mm, now),
            ArmCommand::StartTcpJog { frame, direction } => {
                self.start_tcp_jog(frame, direction, None, now)
            }
            ArmCommand::StartTcpJogAtSpeed {
                frame,
                direction,
                speed_mm_s,
            } => {
                if !speed_mm_s.is_finite() || speed_mm_s <= 0.0 {
                    return Err(ControllerError::InvalidLimit);
                }
                self.start_tcp_jog(frame, direction, Some(speed_mm_s), now)
            }
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
        speed_override_mm_s: Option<f64>,
        now: u64,
    ) -> Result<(), ControllerError> {
        if !direction.iter().all(|component| component.is_finite()) {
            return Err(ControllerError::InvalidLimit);
        }
        let length = vector_length(direction);
        if length <= f64::EPSILON {
            return Err(ControllerError::InvalidLimit);
        }
        let target_angles = self.target_or_current_angles()?;
        let (target_angles, target_coords_mm, tool_pitch_rad, holding_boundary) = match self.mode {
            ArmMode::TcpJogging {
                target_angles,
                target_coords_mm,
                tool_pitch_rad,
                direction,
                ..
            } => (
                target_angles,
                target_coords_mm,
                tool_pitch_rad,
                direction == [0.0; 3],
            ),
            _ => {
                let tool_pitch_rad =
                    kinematics::tool_pitch(target_angles[1], target_angles[2], target_angles[3]);
                let (x, y, z) = kinematics::fk(
                    target_angles[0],
                    target_angles[1],
                    target_angles[2],
                    target_angles[3],
                );
                (target_angles, [x, y, z], tool_pitch_rad, false)
            }
        };
        let direction = [
            direction[0] / length,
            direction[1] / length,
            direction[2] / length,
        ];
        let (frame, mut direction) = match frame {
            TcpFrame::YawFlat => {
                let (dx, dy, dz) = Self::yaw_flat_delta_to_base_delta(
                    target_angles,
                    direction[0],
                    direction[1],
                    direction[2],
                );
                (TcpFrame::Base, [dx, dy, dz])
            }
            frame => (frame, direction),
        };
        if holding_boundary {
            direction = [0.0; 3];
        }
        self.mode = ArmMode::TcpJogging {
            frame,
            direction,
            speed_override_mm_s,
            last_step_ms: now,
            target_angles,
            target_coords_mm,
            tool_pitch_rad,
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
            .map(|tick| self.joints[joint].tick_to_angle(tick));
        let target_angle_rad = self.joints[joint]
            .target_tick
            .map(|tick| self.joints[joint].tick_to_angle(tick));

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

    fn explicit_target_or_current_angles(&self) -> Option<[f64; JOINT_COUNT]> {
        if let Some(angles) = target_angles(&self.joints) {
            return Some(angles);
        }

        if !self.joints.iter().any(|joint| joint.target_tick.is_some()) {
            return None;
        }

        let mut angles = self.current_angles().ok()?;
        for (index, joint) in self.joints.iter().enumerate() {
            if joint.target_tick.is_some() {
                angles[index] = joint.target_angle_rad?;
            }
        }
        Some(angles)
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
        if let ArmMode::TcpJogging {
            target_coords_mm, ..
        } = self.mode
        {
            return Some(table_coords((
                target_coords_mm[0],
                target_coords_mm[1],
                target_coords_mm[2],
            )));
        }
        self.explicit_target_or_current_angles()
            .map(|angles| table_coords(kinematics::fk(angles[0], angles[1], angles[2], angles[3])))
    }

    pub fn effective_target_coords_mm(&self) -> Option<(f32, f32, f32)> {
        if let ArmMode::TcpJogging {
            target_coords_mm, ..
        } = self.mode
        {
            return Some(table_coords((
                target_coords_mm[0],
                target_coords_mm[1],
                target_coords_mm[2],
            )));
        }
        self.explicit_target_or_current_angles()
            .or_else(|| self.current_angles().ok())
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

    fn goto_coords(
        &mut self,
        x: f64,
        y: f64,
        z: f64,
        tool_phi_rad: f64,
        now: u64,
    ) -> Result<(), ControllerError> {
        let angles =
            self.nearest_branch_candidate(x, y, z, tool_phi_rad, self.current_angles().ok())?;
        self.goto_checked_angles(angles, now)
    }

    fn goto_coords_nearest_branch(
        &mut self,
        x: f64,
        y: f64,
        z: f64,
        tool_phi_rad: f64,
        current_angles: [f64; JOINT_COUNT],
        now: u64,
    ) -> Result<(), ControllerError> {
        let angles = self.solve_coords_nearest_branch(x, y, z, tool_phi_rad, current_angles)?;
        self.goto_checked_angles(angles, now)
    }

    fn angles_to_ticks(&self, angles: [f64; JOINT_COUNT]) -> [i32; JOINT_COUNT] {
        core::array::from_fn(|index| self.joints[index].angle_to_tick(angles[index]))
    }

    fn cartesian_angles_to_ticks(&self, angles: [f64; JOINT_COUNT]) -> [i32; JOINT_COUNT] {
        self.angles_to_ticks(angles)
            .map(servo_safety::canonical_servo_tick)
    }

    fn ticks_within_joint_limits(&self, ticks: &[i32; JOINT_COUNT]) -> bool {
        self.joints
            .iter()
            .zip(ticks.iter())
            .all(|(joint, tick)| servo_safety::tick_within_joint_limits(joint, *tick))
    }

    fn cartesian_joint_limit_error(
        &self,
        candidate_ticks: [i32; JOINT_COUNT],
    ) -> Option<CartesianJointLimitError> {
        let violations = core::array::from_fn(|joint| {
            let config = &self.joints[joint];
            (!servo_safety::tick_within_joint_limits(config, candidate_ticks[joint])).then_some(
                JointLimitViolation {
                    joint,
                    requested_tick: candidate_ticks[joint],
                    tick_min: config.tick_min,
                    tick_max: config.tick_max,
                },
            )
        });
        violations
            .iter()
            .any(Option::is_some)
            .then_some(CartesianJointLimitError {
                candidate_ticks,
                violations,
            })
    }

    fn goto_checked_angles(
        &mut self,
        angles: [f64; JOINT_COUNT],
        now: u64,
    ) -> Result<(), ControllerError> {
        let ticks = self.cartesian_angles_to_ticks(angles);
        if let Some(error) = self.cartesian_joint_limit_error(ticks) {
            return Err(ControllerError::CartesianJointLimits(error));
        }
        self.goto_ticks(ticks, now)
    }

    fn solve_coords_nearest_branch(
        &self,
        x: f64,
        y: f64,
        z: f64,
        tool_phi_rad: f64,
        current_angles: [f64; JOINT_COUNT],
    ) -> Result<[f64; JOINT_COUNT], ControllerError> {
        self.nearest_branch_candidate(x, y, z, tool_phi_rad, Some(current_angles))
    }

    fn nearest_branch_candidate(
        &self,
        x: f64,
        y: f64,
        z: f64,
        tool_phi_rad: f64,
        current_angles: Option<[f64; JOINT_COUNT]>,
    ) -> Result<[f64; JOINT_COUNT], ControllerError> {
        let mut best_valid: Option<([f64; JOINT_COUNT], f64)> = None;
        let mut best_limited: Option<([i32; JOINT_COUNT], f64)> = None;
        for result in kinematics::ik_with_tool_pitch_branches(x, y, z, tool_phi_rad) {
            if !result.reachable {
                continue;
            }
            let angles = [result.yaw, result.shoulder, result.elbow, result.wrist];
            let score = match current_angles {
                Some(current) => branch_continuity_score(current, angles),
                None => 0.0,
            };
            let ticks = self.cartesian_angles_to_ticks(angles);
            if self.ticks_within_joint_limits(&ticks) {
                if best_valid.is_none_or(|(_, best_score)| score < best_score) {
                    best_valid = Some((angles, score));
                }
            } else if best_limited.is_none_or(|(_, best_score)| score < best_score) {
                best_limited = Some((ticks, score));
            }
        }
        if let Some((angles, _)) = best_valid {
            return Ok(angles);
        }
        if let Some((ticks, _)) = best_limited {
            return Err(ControllerError::CartesianJointLimits(
                self.cartesian_joint_limit_error(ticks)
                    .expect("limited IK candidate has a joint-limit violation"),
            ));
        }
        Err(ControllerError::Ik(kinematics::IkError::Unreachable))
    }

    pub fn preview_target_angles(
        &self,
        x: f64,
        y: f64,
        z: f64,
        tool_phi_rad: f64,
    ) -> Option<[f64; JOINT_COUNT]> {
        self.preview_target_angles_result(x, y, z, tool_phi_rad)
            .ok()
    }

    pub fn preview_target_angles_result(
        &self,
        x: f64,
        y: f64,
        z: f64,
        tool_phi_rad: f64,
    ) -> Result<[f64; JOINT_COUNT], ControllerError> {
        self.nearest_branch_candidate(x, y, z, tool_phi_rad, self.current_angles().ok())
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
                self.goto_coords_nearest_branch(x + dx, y + dy, target_z, tool_phi, angles, now)?
            }
            TcpFrame::Tool => {
                self.goto_coords_nearest_branch(x + dx, y + dy, target_z, tool_phi, angles, now)?
            }
        };
        if matches!(frame, TcpFrame::Base | TcpFrame::YawFlat)
            && dx_mm.abs() <= f64::EPSILON
            && dy_mm.abs() <= f64::EPSILON
        {
            self.set_joint_target_tick(0, self.joints[0].angle_to_tick(angles[0]));
        }
        target_angles(&self.joints).ok_or(ControllerError::MissingFeedback)
    }

    fn advance_tcp_jog(&mut self, now: u64) {
        let ArmMode::TcpJogging {
            frame,
            direction,
            speed_override_mm_s,
            last_step_ms,
            target_angles: jog_target_angles,
            target_coords_mm,
            tool_pitch_rad,
        } = self.mode
        else {
            return;
        };

        let elapsed_ms = now.saturating_sub(last_step_ms);
        if elapsed_ms == 0 {
            return;
        }
        let speed_mm_s = speed_override_mm_s.unwrap_or(f64::from(self.default_speed.abs()));
        let step_mm = speed_mm_s * elapsed_ms as f64 / 1000.0;
        if direction == [0.0; 3] {
            self.mode = ArmMode::TcpJogging {
                frame,
                direction,
                speed_override_mm_s,
                last_step_ms: now,
                target_angles: jog_target_angles,
                target_coords_mm,
                tool_pitch_rad,
            };
            return;
        }
        let (dx, dy, dz) = match frame {
            TcpFrame::Base | TcpFrame::YawFlat => (
                direction[0] * step_mm,
                direction[1] * step_mm,
                direction[2] * step_mm,
            ),
            TcpFrame::Tool => Self::tool_delta_to_base_delta(
                jog_target_angles,
                direction[0] * step_mm,
                direction[1] * step_mm,
                direction[2] * step_mm,
            ),
        };
        let current_coords_mm = match self.current_coords() {
            Ok((x, y, z)) => [x, y, z],
            Err(_) => {
                self.mode = ArmMode::TcpJogging {
                    frame,
                    direction,
                    speed_override_mm_s,
                    last_step_ms: now,
                    target_angles: jog_target_angles,
                    target_coords_mm,
                    tool_pitch_rad,
                };
                return;
            }
        };
        let step_fraction =
            tcp_jog_lead_step_fraction(current_coords_mm, target_coords_mm, [dx, dy, dz]);
        if step_fraction <= f64::EPSILON {
            self.mode = ArmMode::TcpJogging {
                frame,
                direction,
                speed_override_mm_s,
                last_step_ms: now,
                target_angles: jog_target_angles,
                target_coords_mm,
                tool_pitch_rad,
            };
            return;
        }
        let (dx, dy, dz) = (dx * step_fraction, dy * step_fraction, dz * step_fraction);
        let next_coords_mm = [
            target_coords_mm[0] + dx,
            target_coords_mm[1] + dy,
            target_coords_mm[2] + dz,
        ];
        let result = self
            .solve_coords_nearest_branch(
                next_coords_mm[0],
                next_coords_mm[1],
                next_coords_mm[2],
                tool_pitch_rad,
                jog_target_angles,
            )
            .and_then(|angles| {
                self.goto_checked_angles(angles, now)?;
                Ok(angles)
            });
        match result {
            Ok(jog_target_angles) => {
                self.mode = ArmMode::TcpJogging {
                    frame,
                    direction,
                    speed_override_mm_s,
                    last_step_ms: now,
                    target_angles: jog_target_angles,
                    target_coords_mm: next_coords_mm,
                    tool_pitch_rad,
                };
            }
            Err(ControllerError::Ik(kinematics::IkError::Unreachable))
            | Err(ControllerError::CartesianJointLimits(_)) => {
                // Do not discard a whole high-speed step at the workspace or
                // configured joint-limit boundary. Find the furthest reachable
                // fraction while keeping the original Cartesian start and
                // direction, then hold that boundary target until release.
                let mut reachable_fraction = 0.0;
                let mut unreachable_fraction = 1.0;
                let mut boundary_coords_mm = target_coords_mm;
                let mut boundary_angles = jog_target_angles;
                for _ in 0..14 {
                    let fraction = (reachable_fraction + unreachable_fraction) * 0.5;
                    let candidate_coords_mm = [
                        target_coords_mm[0] + dx * fraction,
                        target_coords_mm[1] + dy * fraction,
                        target_coords_mm[2] + dz * fraction,
                    ];
                    let candidate = self
                        .solve_coords_nearest_branch(
                            candidate_coords_mm[0],
                            candidate_coords_mm[1],
                            candidate_coords_mm[2],
                            tool_pitch_rad,
                            jog_target_angles,
                        )
                        .and_then(|angles| {
                            self.goto_checked_angles(angles, now)?;
                            Ok(angles)
                        });
                    match candidate {
                        Ok(angles) => {
                            reachable_fraction = fraction;
                            boundary_coords_mm = candidate_coords_mm;
                            boundary_angles = angles;
                        }
                        Err(ControllerError::Ik(kinematics::IkError::Unreachable))
                        | Err(ControllerError::CartesianJointLimits(_)) => {
                            unreachable_fraction = fraction;
                        }
                        Err(_) => break,
                    }
                }
                if reachable_fraction > 0.0 {
                    // While the control remains held, keep one exact Cartesian
                    // endpoint and its joint targets stable. Release still sends
                    // StopTcpJog, which clears every target and speed.
                    self.mode = ArmMode::TcpJogging {
                        frame,
                        direction: [0.0; 3],
                        speed_override_mm_s,
                        last_step_ms: now,
                        target_angles: boundary_angles,
                        target_coords_mm: boundary_coords_mm,
                        tool_pitch_rad,
                    };
                } else {
                    self.mode = ArmMode::Idle;
                    self.refresh_mode_from_motion();
                }
            }
            Err(_) => {
                self.mode = ArmMode::Idle;
                self.refresh_mode_from_motion();
            }
        }
    }

    fn yaw_flat_delta_to_base_delta(
        angles: [f64; JOINT_COUNT],
        dx_mm: f64,
        dy_mm: f64,
        dz_mm: f64,
    ) -> (f64, f64, f64) {
        let yaw = kinematics::geometric_yaw(angles[0]);
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
        let yaw = kinematics::geometric_yaw(yaw);
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
        ticks[joint] = self.joints[joint].angle_to_tick(angle_rad);
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
