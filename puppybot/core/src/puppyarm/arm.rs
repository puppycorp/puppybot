use super::{
    controller::{ArmCommand, ArmController, JOINT_COUNT},
    servo_safety::{self, SafetyFault, SpeedCommand},
};
use crate::stservo::{MAX_SERVO_ID, MIN_SERVO_ID, Mode};

const WHEEL_MODE_RECOVERY_RETRY_MS: u64 = 1000;
const WHEEL_MODE_NEVER_ATTEMPTED: u64 = u64::MAX;
const RAD_TO_DEG: f64 = 180.0 / core::f64::consts::PI;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
struct WheelModeState {
    servo_ids: [u8; JOINT_COUNT],
    ready: [bool; JOINT_COUNT],
    last_attempt_ms: [u64; JOINT_COUNT],
}

impl WheelModeState {
    fn new(controller: &ArmController) -> Self {
        Self {
            servo_ids: core::array::from_fn(|index| controller.profiles[index].servo_id),
            ready: [false; JOINT_COUNT],
            last_attempt_ms: [WHEEL_MODE_NEVER_ATTEMPTED; JOINT_COUNT],
        }
    }

    fn sync_servo_ids(&mut self, controller: &ArmController) {
        for index in 0..JOINT_COUNT {
            let servo_id = controller.profiles[index].servo_id;
            if self.servo_ids[index] != servo_id {
                self.servo_ids[index] = servo_id;
                self.ready[index] = false;
                self.last_attempt_ms[index] = 0;
            }
        }
    }

    fn mark_ready(&mut self, index: usize) {
        if index < JOINT_COUNT {
            self.ready[index] = true;
        }
    }

    fn mark_not_ready(&mut self, index: usize) {
        if index < JOINT_COUNT {
            self.ready[index] = false;
        }
    }

    fn mark_all_not_ready(&mut self) {
        self.ready = [false; JOINT_COUNT];
        self.last_attempt_ms = [WHEEL_MODE_NEVER_ATTEMPTED; JOINT_COUNT];
    }

    fn is_ready(&self, index: usize, servo_id: u8) -> bool {
        index < JOINT_COUNT && self.servo_ids[index] == servo_id && self.ready[index]
    }

    fn can_retry(&self, index: usize, now: u64) -> bool {
        index < JOINT_COUNT
            && (self.last_attempt_ms[index] == WHEEL_MODE_NEVER_ATTEMPTED
                || now.saturating_sub(self.last_attempt_ms[index]) >= WHEEL_MODE_RECOVERY_RETRY_MS)
    }

    fn mark_attempt(&mut self, index: usize, now: u64) {
        if index < JOINT_COUNT {
            self.last_attempt_ms[index] = now;
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct PuppyarmTelemetry {
    pub seq: u32,
    pub joints: [PuppyarmJointTelemetry; JOINT_COUNT],
    pub coords_mm: Option<(f32, f32, f32)>,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct PuppyarmJointTelemetry {
    pub servo_id: u8,
    pub online: bool,
    pub has_feedback: bool,
    pub limit_reached: bool,
    pub tick: Option<i32>,
    pub target_tick: Option<i32>,
    pub speed: i16,
    pub limit_min: i32,
    pub limit_max: i32,
    pub angle_deg: Option<f32>,
    pub fault: Option<SafetyFault>,
}

pub struct PuppyArm {
    controller: ArmController,
    wheel_modes: WheelModeState,
    queued_initial_wheel_mode: bool,
}

fn valid_servo_ids(servo_ids: &[u8; JOINT_COUNT]) -> bool {
    servo_ids
        .iter()
        .all(|servo_id| (MIN_SERVO_ID..=MAX_SERVO_ID).contains(servo_id))
}

impl PuppyArm {
    pub fn new(now: u64) -> Self {
        let controller = ArmController::new(now);
        let wheel_modes = WheelModeState::new(&controller);
        Self {
            controller,
            wheel_modes,
            queued_initial_wheel_mode: false,
        }
    }

    pub fn record_feedback(&mut self, joint: usize, tick: u16, now: u64) {
        if joint >= JOINT_COUNT {
            return;
        }

        let was_online = self.controller.safety.joints[joint].is_online;
        let _ = self.controller.record_feedback(joint, tick as i32, now);
        if !was_online {
            self.wheel_modes.mark_not_ready(joint);
        }
    }

    pub fn record_feedback_error(&mut self, joint: usize) {
        if joint >= JOINT_COUNT {
            return;
        }

        let _ = self.controller.record_feedback_error(joint);
        self.wheel_modes.mark_not_ready(joint);
    }

    pub fn take_initialize_wheel_mode(&mut self) -> bool {
        if self.queued_initial_wheel_mode {
            return false;
        }

        self.queued_initial_wheel_mode = true;
        true
    }

    pub fn update(&mut self, now: u64) -> [SpeedCommand; JOINT_COUNT] {
        self.controller.update(now)
    }

    pub fn wheel_mode_ready(&self, joint: usize, servo_id: u8) -> bool {
        self.wheel_modes.is_ready(joint, servo_id)
    }

    pub fn begin_wheel_mode_attempt(
        &mut self,
        joint: usize,
        servo_id: u8,
        now: u64,
        force: bool,
    ) -> bool {
        if self.wheel_modes.is_ready(joint, servo_id) {
            return false;
        }

        if !force && !self.wheel_modes.can_retry(joint, now) {
            return false;
        }

        self.wheel_modes.mark_attempt(joint, now);
        true
    }

    pub fn can_write_wheel_speed(&self, joint: usize, servo_id: u8) -> bool {
        self.wheel_modes.is_ready(joint, servo_id)
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
            self.wheel_modes.mark_ready(joint);
        } else {
            self.wheel_modes.mark_not_ready(joint);
        }

        if self
            .controller
            .profiles
            .get(joint)
            .map(|profile| profile.servo_id)
            != Some(servo_id)
        {
            self.wheel_modes.mark_not_ready(joint);
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
            let _ = self.controller.mark_speed_sent(joint, speed, now);
        } else {
            self.wheel_modes.mark_not_ready(joint);
        }

        if self
            .controller
            .profiles
            .get(joint)
            .map(|profile| profile.servo_id)
            != Some(servo_id)
        {
            self.wheel_modes.mark_not_ready(joint);
        }
    }

    pub fn telemetry_snapshot(&self, seq: u32) -> PuppyarmTelemetry {
        let coords_mm = self.controller.current_coords().ok().map(|(x, y, z)| {
            (
                x as f32,
                y as f32,
                super::kinematics::shoulder_to_table_z(z) as f32,
            )
        });

        PuppyarmTelemetry {
            seq,
            joints: core::array::from_fn(|index| {
                let joint = self.controller.safety.joints[index];
                PuppyarmJointTelemetry {
                    servo_id: joint.servo_id,
                    online: joint.is_online,
                    has_feedback: joint.has_feedback && joint.tick.is_some(),
                    limit_reached: servo_safety::is_outside_limits(&joint),
                    tick: joint.tick,
                    target_tick: joint.target_tick,
                    speed: joint.speed,
                    limit_min: joint.tick_min,
                    limit_max: joint.tick_max,
                    angle_deg: self
                        .controller
                        .joint_angle(index)
                        .ok()
                        .map(|angle_rad| (angle_rad * RAD_TO_DEG) as f32),
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
                .controller
                .handle_command(ArmCommand::SetServoIds(servo_ids), now)
                .is_ok()
            {
                self.wheel_modes.sync_servo_ids(&self.controller);
                self.wheel_modes.mark_all_not_ready();
                self.queued_initial_wheel_mode = false;
            } else {
                log::warn!("arm intent rejected: SetServoIds");
            }
            return;
        }

        if let Err(err) = self.controller.handle_command(command, now) {
            log::warn!("arm intent rejected: {:?}", err);
        }
    }
}
