use core::f64::consts::PI;

use super::{
    kinematics::{self, IkError},
    servo_safety::{
        self, ELBOW_TICK_MAX, ELBOW_TICK_MIN, JointSafety, SHOULDER_TICK_MAX, SHOULDER_TICK_MIN,
        ServoSafety, SpeedCommand, TICK_WRAP, TIP_TICK_MAX, TIP_TICK_MIN, YAW_TICK_MAX,
        YAW_TICK_MIN,
    },
};

pub const JOINT_COUNT: usize = 4;

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

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum ArmCommand {
    SetSpeed(i16),
    Spin {
        joint: usize,
        direction: i8,
    },
    Stop {
        joint: usize,
    },
    StopAll,
    GotoTicks([i32; JOINT_COUNT]),
    GotoAngles([f64; JOINT_COUNT]),
    GotoCoords {
        x: f64,
        y: f64,
        z: f64,
    },
    GotoPose {
        x: f64,
        y: f64,
        z: f64,
        tool_phi_rad: f64,
    },
    Hold,
    SetJointTick {
        joint: usize,
        tick: i32,
    },
    SetJointAngle {
        joint: usize,
        angle_rad: f64,
    },
    SetTickLimits {
        joint: usize,
        min: i32,
        max: i32,
    },
    SetTickLimitsEnabled {
        joint: usize,
        enabled: bool,
    },
    ClearFaults {
        joint: Option<usize>,
    },
    SetServoIds([u8; JOINT_COUNT]),
}

pub type ArmIntent = ArmCommand;

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum ArmMode {
    Idle,
    Jogging { joint: usize, direction: i8 },
    TrackingTicks { targets: [i32; JOINT_COUNT] },
    Holding { targets: [i32; JOINT_COUNT] },
    Fault,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum ControllerError {
    InvalidJoint,
    InvalidLimit,
    MissingFeedback,
    Ik(IkError),
}

impl From<IkError> for ControllerError {
    fn from(err: IkError) -> Self {
        Self::Ik(err)
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct JointProfile {
    pub servo_id: u8,
    pub tick_min: i32,
    pub tick_max: i32,
    pub raw_tick_min: i32,
    pub raw_tick_max: i32,
    pub sign: f64,
    pub drive_sign: i8,
    pub zero_offset_rad: f64,
}

impl JointProfile {
    pub fn safety(&self) -> JointSafety {
        JointSafety::new(self.servo_id, self.tick_min, self.tick_max)
            .with_drive_sign(self.drive_sign)
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct JointState {
    pub servo_id: u8,
    pub tick: Option<i32>,
    pub target_tick: Option<i32>,
    pub speed: i16,
    pub limit_reached: bool,
    pub is_online: bool,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct ArmState {
    pub joints: [JointState; JOINT_COUNT],
    pub default_speed: i16,
    pub mode: ArmMode,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct ArmController {
    pub safety: ServoSafety<JOINT_COUNT>,
    pub profiles: [JointProfile; JOINT_COUNT],
    pub mode: ArmMode,
}

impl ArmController {
    pub fn new(now_ms: u64) -> Self {
        let profiles = default_joint_profiles();
        let safety = ServoSafety::new(
            [
                profiles[0].safety(),
                profiles[1].safety(),
                profiles[2].safety(),
                profiles[3].safety(),
            ],
            now_ms,
        );

        Self {
            safety,
            profiles,
            mode: ArmMode::Idle,
        }
    }

    pub fn handle_command(
        &mut self,
        command: ArmCommand,
        now_ms: u64,
    ) -> Result<(), ControllerError> {
        match command {
            ArmCommand::SetSpeed(speed) => {
                self.safety.set_default_speed(speed, now_ms);
                Ok(())
            }
            ArmCommand::Spin { joint, direction } => self
                .safety
                .spin(validate_joint(joint)?, direction, now_ms)
                .map(|()| {
                    self.mode = if direction == 0 {
                        ArmMode::Idle
                    } else {
                        ArmMode::Jogging {
                            joint,
                            direction: direction.signum(),
                        }
                    };
                })
                .map_err(|()| ControllerError::InvalidJoint),
            ArmCommand::Stop { joint } => self
                .safety
                .stop_joint(validate_joint(joint)?, now_ms)
                .map(|()| self.refresh_mode_from_motion())
                .map_err(|()| ControllerError::InvalidJoint),
            ArmCommand::StopAll => {
                self.safety.stop_all(now_ms);
                self.mode = ArmMode::Idle;
                Ok(())
            }
            ArmCommand::GotoTicks(ticks) => self.goto_ticks(ticks, now_ms),
            ArmCommand::GotoAngles(angles) => self.goto_angles(angles, now_ms),
            ArmCommand::GotoCoords { x, y, z } => self.goto_coords(x, y, z, now_ms),
            ArmCommand::GotoPose {
                x,
                y,
                z,
                tool_phi_rad,
            } => self.goto_pose(x, y, z, tool_phi_rad, now_ms),
            ArmCommand::Hold => self.hold(now_ms),
            ArmCommand::SetJointTick { joint, tick } => self.set_joint_tick(joint, tick, now_ms),
            ArmCommand::SetJointAngle { joint, angle_rad } => {
                self.set_joint_angle(joint, angle_rad, now_ms)
            }
            ArmCommand::SetTickLimits { joint, min, max } => self.set_tick_limits(joint, min, max),
            ArmCommand::SetTickLimitsEnabled { joint, enabled } => {
                let joint = validate_joint(joint)?;
                self.safety.joints[joint].limit_enabled = enabled;
                Ok(())
            }
            ArmCommand::ClearFaults { joint } => self
                .safety
                .clear_faults(joint.map(validate_joint).transpose()?)
                .map(|()| self.refresh_mode_from_motion())
                .map_err(|()| ControllerError::InvalidJoint),
            ArmCommand::SetServoIds(servo_ids) => {
                for (index, servo_id) in servo_ids.iter().copied().enumerate() {
                    self.profiles[index].servo_id = servo_id;
                    self.safety.joints[index].servo_id = servo_id;
                }
                Ok(())
            }
        }
    }

    pub fn record_feedback(
        &mut self,
        joint: usize,
        tick: i32,
        now_ms: u64,
    ) -> Result<(), ControllerError> {
        self.safety
            .record_feedback(validate_joint(joint)?, tick, now_ms)
            .map_err(|()| ControllerError::InvalidJoint)
    }

    pub fn record_feedback_error(&mut self, joint: usize) -> Result<(), ControllerError> {
        self.safety
            .record_feedback_error(validate_joint(joint)?)
            .map_err(|()| ControllerError::InvalidJoint)
    }

    pub fn speed_commands(&mut self, now_ms: u64) -> [SpeedCommand; JOINT_COUNT] {
        self.safety.speed_commands(now_ms)
    }

    pub fn update(&mut self, now_ms: u64) -> [SpeedCommand; JOINT_COUNT] {
        let commands = self.safety.speed_commands(now_ms);
        self.refresh_mode_from_motion();
        commands
    }

    pub fn mark_speed_sent(
        &mut self,
        joint: usize,
        speed: i16,
        now_ms: u64,
    ) -> Result<(), ControllerError> {
        self.safety
            .mark_speed_sent(validate_joint(joint)?, speed, now_ms)
            .map_err(|()| ControllerError::InvalidJoint)
    }

    pub fn state(&self) -> ArmState {
        ArmState {
            joints: core::array::from_fn(|index| {
                let joint = self.safety.joints[index];
                JointState {
                    servo_id: joint.servo_id,
                    tick: joint.tick,
                    target_tick: joint.target_tick,
                    speed: joint.speed,
                    limit_reached: servo_safety::is_outside_limits(&joint),
                    is_online: joint.is_online,
                }
            }),
            default_speed: self.safety.default_speed,
            mode: self.mode,
        }
    }

    pub fn current_angles(&self) -> Result<[f64; JOINT_COUNT], ControllerError> {
        let mut out = [0.0; JOINT_COUNT];
        for (index, angle) in out.iter_mut().enumerate() {
            *angle = self.joint_angle(index)?;
        }
        Ok(out)
    }

    pub fn joint_angle(&self, joint: usize) -> Result<f64, ControllerError> {
        let joint = validate_joint(joint)?;
        let tick = self.safety.joints[joint]
            .tick
            .ok_or(ControllerError::MissingFeedback)?;
        Ok(tick_to_angle(&self.profiles[joint], tick))
    }

    pub fn current_coords(&self) -> Result<(f64, f64, f64), ControllerError> {
        let angles = self.current_angles()?;
        Ok(kinematics::fk(angles[0], angles[1], angles[2], angles[3]))
    }

    fn goto_ticks(
        &mut self,
        ticks: [i32; JOINT_COUNT],
        now_ms: u64,
    ) -> Result<(), ControllerError> {
        self.safety
            .goto_ticks(&ticks, now_ms)
            .map(|()| self.mode = ArmMode::TrackingTicks { targets: ticks })
            .map_err(|()| ControllerError::InvalidJoint)
    }

    fn goto_angles(
        &mut self,
        angles: [f64; JOINT_COUNT],
        now_ms: u64,
    ) -> Result<(), ControllerError> {
        let ticks =
            core::array::from_fn(|index| angle_to_tick(&self.profiles[index], angles[index]));
        self.goto_ticks(ticks, now_ms)
    }

    fn goto_coords(&mut self, x: f64, y: f64, z: f64, now_ms: u64) -> Result<(), ControllerError> {
        let angles = kinematics::solve_coords_tool_down(x, y, z)?;
        self.goto_angles([angles.0, angles.1, angles.2, angles.3], now_ms)
    }

    fn goto_pose(
        &mut self,
        x: f64,
        y: f64,
        z: f64,
        tool_phi_rad: f64,
        now_ms: u64,
    ) -> Result<(), ControllerError> {
        let angles = kinematics::solve_coords_with_tool_pitch(x, y, z, tool_phi_rad)?;
        self.goto_angles([angles.0, angles.1, angles.2, angles.3], now_ms)
    }

    fn hold(&mut self, now_ms: u64) -> Result<(), ControllerError> {
        let mut ticks = [0; JOINT_COUNT];
        for (index, tick) in ticks.iter_mut().enumerate() {
            *tick = self.safety.joints[index]
                .tick
                .ok_or(ControllerError::MissingFeedback)?;
        }
        self.safety
            .goto_ticks(&ticks, now_ms)
            .map(|()| self.mode = ArmMode::Holding { targets: ticks })
            .map_err(|()| ControllerError::InvalidJoint)
    }

    fn set_joint_tick(
        &mut self,
        joint: usize,
        tick: i32,
        now_ms: u64,
    ) -> Result<(), ControllerError> {
        let joint = validate_joint(joint)?;
        let mut ticks = [0; JOINT_COUNT];
        for (index, target_tick) in ticks.iter_mut().enumerate() {
            *target_tick = self.safety.joints[index]
                .tick
                .ok_or(ControllerError::MissingFeedback)?;
        }
        ticks[joint] = tick;
        self.goto_ticks(ticks, now_ms)
    }

    fn set_joint_angle(
        &mut self,
        joint: usize,
        angle_rad: f64,
        now_ms: u64,
    ) -> Result<(), ControllerError> {
        let joint = validate_joint(joint)?;
        let mut ticks = [0; JOINT_COUNT];
        for (index, target_tick) in ticks.iter_mut().enumerate() {
            *target_tick = self.safety.joints[index]
                .tick
                .ok_or(ControllerError::MissingFeedback)?;
        }
        ticks[joint] = angle_to_tick(&self.profiles[joint], angle_rad);
        self.goto_ticks(ticks, now_ms)
    }

    fn set_tick_limits(&mut self, joint: usize, min: i32, max: i32) -> Result<(), ControllerError> {
        let joint = validate_joint(joint)?;
        if min == max {
            return Err(ControllerError::InvalidLimit);
        }

        self.profiles[joint].tick_min = min;
        self.profiles[joint].tick_max = max;
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

pub fn current_targets(safety: &ServoSafety<JOINT_COUNT>) -> Option<[i32; JOINT_COUNT]> {
    let mut targets = [0; JOINT_COUNT];
    for (index, joint) in safety.joints.iter().enumerate() {
        targets[index] = joint.target_tick?;
    }
    Some(targets)
}

pub fn active_jog(safety: &ServoSafety<JOINT_COUNT>) -> Option<(usize, i8)> {
    for (index, joint) in safety.joints.iter().enumerate() {
        if joint.target_tick.is_none() && joint.speed != 0 {
            return Some((index, joint.speed.signum() as i8));
        }
    }
    None
}

pub fn default_joint_profiles() -> [JointProfile; JOINT_COUNT] {
    [
        JointProfile {
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
        },
        JointProfile {
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
        },
        JointProfile {
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
        },
        JointProfile {
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
        },
    ]
}

pub fn angle_to_tick(profile: &JointProfile, angle_rad: f64) -> i32 {
    let mid_tick = reference_mid_tick(profile);
    let physical_angle = profile.sign * angle_rad + profile.zero_offset_rad;
    libm::round(mid_tick + physical_angle * TICK_WRAP as f64 / (2.0 * PI)) as i32
}

pub fn tick_to_angle(profile: &JointProfile, tick: i32) -> f64 {
    let mid_tick = reference_mid_tick(profile);
    let aligned_tick = servo_safety::align_tick_to_reference(tick, mid_tick as i32);
    let physical_angle = (aligned_tick as f64 - mid_tick) * (2.0 * PI / TICK_WRAP as f64);
    (physical_angle - profile.zero_offset_rad) / profile.sign
}

pub fn zero_offset_from_reference(
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

fn reference_mid_tick(profile: &JointProfile) -> f64 {
    let (lo, hi) =
        servo_safety::continuous_tick_interval(profile.raw_tick_min, profile.raw_tick_max);
    0.5 * (lo + hi) as f64
}

fn validate_joint(joint: usize) -> Result<usize, ControllerError> {
    if joint < JOINT_COUNT {
        Ok(joint)
    } else {
        Err(ControllerError::InvalidJoint)
    }
}

#[cfg(test)]
#[allow(dead_code)]
mod tests {
    #[allow(unused_imports)]
    use super::*;

    #[test]
    fn hold_requires_feedback() {
        let mut controller = ArmController::new(0);
        assert_eq!(
            controller.handle_command(ArmCommand::Hold, 0),
            Err(ControllerError::MissingFeedback)
        );
    }

    #[test]
    fn hold_targets_current_feedback_ticks() {
        let mut controller = ArmController::new(0);
        for index in 0..JOINT_COUNT {
            controller
                .record_feedback(index, 1000 + index as i32, 0)
                .unwrap();
        }

        controller.handle_command(ArmCommand::Hold, 10).unwrap();
        assert_eq!(controller.safety.joints[0].target_tick, Some(1000));
        assert_eq!(controller.safety.joints[3].target_tick, Some(1003));
    }

    #[test]
    fn set_joint_tick_keeps_other_feedback_ticks() {
        let mut controller = ArmController::new(0);
        for index in 0..JOINT_COUNT {
            controller
                .record_feedback(index, 1000 + index as i32, 0)
                .unwrap();
        }

        controller
            .handle_command(
                ArmCommand::SetJointTick {
                    joint: 2,
                    tick: 1500,
                },
                10,
            )
            .unwrap();

        assert_eq!(controller.safety.joints[0].target_tick, Some(1000));
        assert_eq!(controller.safety.joints[2].target_tick, Some(1500));
    }

    #[test]
    fn goto_angles_sets_target_ticks() {
        let mut controller = ArmController::new(0);
        controller
            .handle_command(ArmCommand::GotoAngles([0.0, PI / 2.0, 0.0, 0.0]), 10)
            .unwrap();

        assert_eq!(
            controller.safety.joints[0].target_tick,
            Some(servo_safety::clip_tick_to_joint_limits(
                &controller.safety.joints[0],
                YAW_ZERO_TICK
            ))
        );
        assert_eq!(
            controller.safety.joints[1].target_tick,
            Some(SHOULDER_ZERO_TICK)
        );
    }

    #[test]
    fn goto_coords_rejects_unreachable_target() {
        let mut controller = ArmController::new(0);
        let result = controller.handle_command(
            ArmCommand::GotoCoords {
                x: 1000.0,
                y: 0.0,
                z: 0.0,
            },
            10,
        );
        assert_eq!(result, Err(ControllerError::Ik(IkError::Unreachable)));
    }

    #[test]
    fn set_speed_updates_active_spin_on_next_step() {
        let mut controller = ArmController::new(0);
        controller.record_feedback(0, 0, 0).unwrap();
        controller
            .handle_command(
                ArmCommand::Spin {
                    joint: 0,
                    direction: 1,
                },
                0,
            )
            .unwrap();
        controller
            .handle_command(ArmCommand::SetSpeed(321), 10)
            .unwrap();

        let commands = controller.speed_commands(10);
        assert_eq!(commands[0].speed, 321);
    }
}
