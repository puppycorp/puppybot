use core::f64::consts::PI;

use super::{
    kinematics,
    servo_safety::{
        self, ELBOW_TICK_MAX, ELBOW_TICK_MIN, SHOULDER_TICK_MAX, SHOULDER_TICK_MIN, SafetyFault,
        SpeedCommand, TICK_WRAP, TIP_TICK_MAX, TIP_TICK_MIN, YAW_TICK_MAX, YAW_TICK_MIN,
    },
};
use crate::stservo::{MAX_SERVO_ID, MIN_SERVO_ID, Mode};

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
const RAD_TO_DEG: f64 = 180.0 / core::f64::consts::PI;

fn current_targets(joints: &[Joint; JOINT_COUNT]) -> Option<[i32; JOINT_COUNT]> {
    let mut targets = [0; JOINT_COUNT];
    for (index, joint) in joints.iter().enumerate() {
        targets[index] = joint.target_tick?;
    }
    Some(targets)
}

fn active_jog(joints: &[Joint; JOINT_COUNT]) -> Option<(usize, i8)> {
    for (index, joint) in joints.iter().enumerate() {
        if joint.target_tick.is_none() && joint.speed != 0 {
            return Some((index, joint.speed.signum() as i8));
        }
    }
    None
}

fn default_joints() -> [Joint; JOINT_COUNT] {
    [
        Joint {
            servo_id: 1,
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
            servo_id: 2,
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
            servo_id: 3,
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
            servo_id: 4,
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

fn default_arm_state(now_ms: u64) -> ([Joint; JOINT_COUNT], ArmMode) {
    let mut joints = default_joints();
    servo_safety::init_joints(&mut joints, now_ms);

    (joints, ArmMode::Idle)
}

pub struct PuppyArm {
    joints: [Joint; JOINT_COUNT],
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
        let commands = self.speed_commands(now);
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
                let mut joint = self.joints[index];
                joint.has_feedback = joint.has_feedback && joint.tick.is_some();
                joint.limit_reached = servo_safety::is_outside_limits(&joint);
                joint.limit_min = joint.tick_min;
                joint.limit_max = joint.tick_max;
                joint.angle_deg = self
                    .joint_angle(index)
                    .ok()
                    .map(|angle_rad| (angle_rad * RAD_TO_DEG) as f32);
                joint
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
        self.last_ok_feedback_ms = now;
        Ok(())
    }

    fn record_feedback_failure(&mut self, joint: usize) -> Result<(), ControllerError> {
        let joint = validate_joint(joint)?;
        self.joints[joint].record_feedback_error();
        Ok(())
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

    fn joint_angle(&self, joint: usize) -> Result<f64, ControllerError> {
        let joint = validate_joint(joint)?;
        let tick = self.joints[joint]
            .tick
            .ok_or(ControllerError::MissingFeedback)?;
        Ok(tick_to_angle(&self.joints[joint], tick))
    }

    fn current_coords(&self) -> Result<(f64, f64, f64), ControllerError> {
        let angles = self.current_angles()?;
        Ok(kinematics::fk(angles[0], angles[1], angles[2], angles[3]))
    }

    fn goto_ticks(&mut self, ticks: [i32; JOINT_COUNT], now: u64) -> Result<(), ControllerError> {
        for (joint, tick) in self.joints.iter_mut().zip(ticks.iter()) {
            joint.clear_fault();
            joint.target_tick = Some(servo_safety::clip_tick_to_joint_limits(joint, *tick));
        }
        self.last_cmd_ms = now;
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

    fn move_tcp_relative(
        &mut self,
        frame: TcpFrame,
        dx_mm: f64,
        dy_mm: f64,
        dz_mm: f64,
        now: u64,
    ) -> Result<(), ControllerError> {
        let angles = self.current_angles()?;
        let tool_phi = angles[1] - angles[2] - angles[3];
        let (x, y, z_shoulder) = kinematics::fk(angles[0], angles[1], angles[2], angles[3]);
        let (dx, dy, dz) = match frame {
            TcpFrame::Base => (dx_mm, dy_mm, dz_mm),
            TcpFrame::Tool => Self::tool_delta_to_base_delta(angles, dx_mm, dy_mm, dz_mm),
        };
        let z_table = kinematics::shoulder_to_table_z(z_shoulder);
        self.goto_pose(
            x + dx,
            y + dy,
            kinematics::table_to_shoulder_z(z_table + dz),
            tool_phi,
            now,
        )
    }

    fn tool_delta_to_base_delta(
        angles: [f64; JOINT_COUNT],
        dx_mm: f64,
        dy_mm: f64,
        dz_mm: f64,
    ) -> (f64, f64, f64) {
        let [yaw, shoulder, elbow, wrist] = angles;
        let tool_phi = shoulder - elbow - wrist;
        let cos_yaw = libm::cos(yaw);
        let sin_yaw = libm::sin(yaw);
        let cos_phi = libm::cos(tool_phi);
        let sin_phi = libm::sin(tool_phi);

        let forward = (-cos_phi * cos_yaw, cos_phi * sin_yaw, sin_phi);
        let left = (sin_yaw, cos_yaw, 0.0);
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
        for (joint, tick) in self.joints.iter_mut().zip(ticks.iter()) {
            joint.clear_fault();
            joint.target_tick = Some(servo_safety::clip_tick_to_joint_limits(joint, *tick));
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
