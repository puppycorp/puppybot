extern crate alloc;

use super::{
    controller::{ArmCommand, ArmController, ArmMode, ArmState, JOINT_COUNT},
    servo_safety::{self, SafetyFault},
};
#[cfg(feature = "runtime")]
use crate::protocol::{self, ProtocolJointTelemetry};
use crate::stservo::{
    MAX_SERVO_ID, MIN_SERVO_ID, Mode, StServo,
    mock::{FakeSerialBus, FakeServo, block_on_ready},
};
#[cfg(any(test, feature = "runtime"))]
use alloc::vec::Vec;

const ARM_WHEEL_ACC: u8 = 0;
const WHEEL_MODE_RECOVERY_RETRY_MS: u64 = 1000;
#[cfg(feature = "runtime")]
const RUNTIME_TICK_RATE_DIVISOR: i32 = 15;

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
            last_attempt_ms: [0; JOINT_COUNT],
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
        self.last_attempt_ms = [0; JOINT_COUNT];
    }

    fn is_ready(&self, index: usize, servo_id: u8) -> bool {
        index < JOINT_COUNT && self.servo_ids[index] == servo_id && self.ready[index]
    }

    fn can_retry(&self, index: usize, now: u64) -> bool {
        index < JOINT_COUNT
            && now.saturating_sub(self.last_attempt_ms[index]) >= WHEEL_MODE_RECOVERY_RETRY_MS
    }

    fn mark_attempt(&mut self, index: usize, now: u64) {
        if index < JOINT_COUNT {
            self.last_attempt_ms[index] = now;
        }
    }
}

pub struct PuppyArm {
    servo: StServo<FakeSerialBus>,
    controller: ArmController,
    wheel_modes: WheelModeState,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct PuppyarmJointSnapshot {
    pub servo_id: u8,
    pub tick: Option<i32>,
    pub target_tick: Option<i32>,
    pub speed: i16,
    pub limit_min: i32,
    pub limit_max: i32,
    pub limit_reached: bool,
    pub online: bool,
    pub has_feedback: bool,
    pub fault: Option<SafetyFault>,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct PuppyarmSnapshot {
    pub joints: [PuppyarmJointSnapshot; JOINT_COUNT],
    pub default_speed: i16,
    pub mode: ArmMode,
    pub last_error: Option<SafetyFault>,
}

fn valid_servo_ids(servo_ids: &[u8; JOINT_COUNT]) -> bool {
    servo_ids
        .iter()
        .all(|servo_id| (MIN_SERVO_ID..=MAX_SERVO_ID).contains(servo_id))
}

impl PuppyArm {
    pub fn new(now_ms: u64) -> Self {
        let mut controller = ArmController::new(now_ms);
        let mut bus = FakeSerialBus::new();

        for index in 0..JOINT_COUNT {
            let profile = controller.profiles[index];
            let tick = (profile.tick_min + profile.tick_max) / 2;
            let servo_tick = tick.clamp(0, servo_safety::TICK_WRAP) as u16;
            bus.set_servo(FakeServo::new(profile.servo_id, servo_tick));
            let _ = controller.record_feedback(index, tick, now_ms);
        }

        let mut engine = Self {
            servo: StServo::new(bus),
            wheel_modes: WheelModeState::new(&controller),
            controller,
        };
        engine.initialize_wheel_mode(now_ms);
        engine
    }

    pub fn state(&self) -> ArmState {
        self.controller.state()
    }

    pub fn snapshot(&self) -> PuppyarmSnapshot {
        PuppyarmSnapshot {
            joints: core::array::from_fn(|index| {
                let joint = self.controller.safety.joints[index];
                PuppyarmJointSnapshot {
                    servo_id: joint.servo_id,
                    tick: joint.tick,
                    target_tick: joint.target_tick,
                    speed: joint.speed,
                    limit_min: joint.tick_min,
                    limit_max: joint.tick_max,
                    limit_reached: servo_safety::is_outside_limits(&joint),
                    online: joint.is_online,
                    has_feedback: joint.has_feedback,
                    fault: joint.fault,
                }
            }),
            default_speed: self.controller.safety.default_speed,
            mode: self.controller.mode,
            last_error: self.controller.safety.last_error,
        }
    }

    #[cfg(test)]
    pub(crate) fn fake_servo(&self, servo_id: u8) -> Option<FakeServo> {
        self.servo.bus().servo(servo_id)
    }

    #[cfg(test)]
    pub(crate) fn bus_writes(&self) -> &[Vec<u8>] {
        &self.servo.bus().writes
    }

    pub fn handle_arm_cmd(&mut self, command: ArmCommand, now_ms: u64) {
        self.apply_arm_command(command, now_ms);
    }

    pub fn step(&mut self, now_ms: u64) {
        self.read_feedback(now_ms);
        self.apply_outputs(now_ms);
    }

    #[cfg(feature = "runtime")]
    pub fn advance_simulation(&mut self, elapsed_ms: u64, now_ms: u64) {
        let elapsed_ms = elapsed_ms as i32;
        if elapsed_ms > 0 {
            for index in 0..JOINT_COUNT {
                let servo_id = self.controller.profiles[index].servo_id;
                if let Some(servo) = self.servo.bus().servo(servo_id) {
                    let current = servo.position as i32;
                    let next = (current
                        + servo.wheel_speed as i32 * elapsed_ms / RUNTIME_TICK_RATE_DIVISOR)
                        .clamp(0, servo_safety::TICK_WRAP) as u16;
                    self.servo.bus_mut().set_position(servo_id, next);
                }
            }
        }

        self.step(now_ms);
    }

    #[cfg(feature = "runtime")]
    pub fn arm_state_frame(&self) -> Vec<u8> {
        let snapshot = self.snapshot();
        let joints: [ProtocolJointTelemetry<'_>; JOINT_COUNT] = core::array::from_fn(|index| {
            let joint = snapshot.joints[index];
            ProtocolJointTelemetry {
                servo_id: joint.servo_id,
                online: joint.online,
                has_feedback: joint.has_feedback && joint.tick.is_some(),
                limit_reached: joint.limit_reached,
                tick: joint.tick,
                target_tick: joint.target_tick,
                speed: joint.speed,
                limit_min: joint.limit_min,
                limit_max: joint.limit_max,
                angle_deg: self
                    .controller
                    .joint_angle(index)
                    .ok()
                    .map(|angle| (angle * 180.0 / core::f64::consts::PI) as f32),
                fault: joint.fault.map(protocol::fault_name),
            }
        });
        let coords = self.controller.current_coords().ok().map(|(x, y, z)| {
            (
                x as f32,
                y as f32,
                super::kinematics::shoulder_to_table_z(z) as f32,
            )
        });

        protocol::arm_state_frame(&joints, coords)
    }

    #[cfg(test)]
    pub(crate) fn set_read_failure(&mut self, servo_id: u8, enabled: bool) {
        self.servo.bus_mut().set_read_failure(servo_id, enabled);
    }

    #[cfg(test)]
    pub(crate) fn set_write_failure(&mut self, servo_id: u8, enabled: bool) {
        self.servo.bus_mut().set_write_failure(servo_id, enabled);
    }

    #[cfg(test)]
    pub(crate) fn set_position(&mut self, servo_id: u8, position: u16) {
        self.servo.bus_mut().set_position(servo_id, position);
    }

    fn apply_arm_command(&mut self, command: ArmCommand, now_ms: u64) {
        if let ArmCommand::SetServoIds(_) = command {
            let ArmCommand::SetServoIds(servo_ids) = command else {
                unreachable!();
            };
            if !valid_servo_ids(&servo_ids) {
                return;
            }
            if self
                .controller
                .handle_command(ArmCommand::SetServoIds(servo_ids), now_ms)
                .is_ok()
            {
                self.wheel_modes.sync_servo_ids(&self.controller);
                self.wheel_modes.mark_all_not_ready();
                self.initialize_wheel_mode(now_ms);
            }
            return;
        }

        let _ = self.controller.handle_command(command, now_ms);
    }

    fn initialize_wheel_mode(&mut self, now_ms: u64) {
        for index in 0..JOINT_COUNT {
            let servo_id = self.controller.profiles[index].servo_id;
            if self.ensure_wheel_mode(index, servo_id, now_ms, true) {
                if block_on_ready(self.servo.write_wheel_speed(servo_id, 0, ARM_WHEEL_ACC)).is_err()
                {
                    self.wheel_modes.mark_not_ready(index);
                }
            }
        }
    }

    fn ensure_wheel_mode(&mut self, index: usize, servo_id: u8, now_ms: u64, force: bool) -> bool {
        if self.wheel_modes.is_ready(index, servo_id) {
            return true;
        }

        if !force && !self.wheel_modes.can_retry(index, now_ms) {
            return false;
        }

        self.wheel_modes.mark_attempt(index, now_ms);
        if block_on_ready(self.servo.set_mode(servo_id, Mode::Wheel)).is_ok() {
            self.wheel_modes.mark_ready(index);
            true
        } else {
            self.wheel_modes.mark_not_ready(index);
            false
        }
    }

    fn read_feedback(&mut self, now_ms: u64) {
        for index in 0..JOINT_COUNT {
            let servo_id = self.controller.profiles[index].servo_id;
            let was_online = self.controller.safety.joints[index].is_online;
            match block_on_ready(self.servo.read_position(servo_id)) {
                Ok(tick) => {
                    let _ = self.controller.record_feedback(index, tick as i32, now_ms);
                    if !was_online {
                        self.wheel_modes.mark_not_ready(index);
                    }
                }
                Err(_) => {
                    let _ = self.controller.record_feedback_error(index);
                    self.wheel_modes.mark_not_ready(index);
                }
            }
        }
    }

    fn apply_outputs(&mut self, now_ms: u64) {
        let outputs = self.controller.update(now_ms);
        for (index, output) in outputs.iter().copied().enumerate() {
            if !output.should_send {
                continue;
            }

            let force_wheel_mode = output.speed == 0;
            if !self.ensure_wheel_mode(index, output.servo_id, now_ms, force_wheel_mode) {
                continue;
            }

            if block_on_ready(self.servo.write_wheel_speed(
                output.servo_id,
                output.speed,
                ARM_WHEEL_ACC,
            ))
            .is_err()
            {
                self.wheel_modes.mark_not_ready(index);
                continue;
            }

            let _ = self.controller.mark_speed_sent(index, output.speed, now_ms);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const INST_WRITE: u8 = 0x03;
    const SMS_STS_MODE: u8 = 33;
    const SMS_STS_ACC: u8 = 41;

    #[test]
    fn initializes_arm_servos_to_wheel_mode_before_any_motion() {
        let engine = PuppyArm::new(0);

        for servo_id in 2..=5 {
            let servo = engine.fake_servo(servo_id).unwrap();
            assert_eq!(servo.mode, Mode::Wheel);
            assert_eq!(servo.wheel_speed, 0);
        }

        for servo_id in 2..=5 {
            assert!(engine.bus_writes().iter().any(|write| is_write_to(
                write,
                servo_id,
                SMS_STS_MODE
            )));
        }
    }

    #[test]
    fn jog_sends_wheel_speed_through_fake_serial_bus() {
        let mut engine = PuppyArm::new(0);

        engine.handle_arm_cmd(ArmCommand::SetSpeed(300), 10);
        engine.handle_arm_cmd(
            ArmCommand::Spin {
                joint: 0,
                direction: 1,
            },
            10,
        );
        engine.step(20);

        assert_eq!(engine.state().joints[0].speed, 300);
        assert_eq!(engine.fake_servo(2).unwrap().wheel_speed, 300);
    }

    #[test]
    fn stop_joint_sends_zero_speed() {
        let mut engine = PuppyArm::new(0);

        engine.handle_arm_cmd(ArmCommand::SetSpeed(300), 10);
        engine.handle_arm_cmd(
            ArmCommand::Spin {
                joint: 0,
                direction: 1,
            },
            10,
        );
        engine.step(20);
        engine.handle_arm_cmd(ArmCommand::Stop { joint: 0 }, 30);
        engine.step(40);

        assert_eq!(engine.state().joints[0].speed, 0);
        assert_eq!(engine.fake_servo(2).unwrap().wheel_speed, 0);
    }

    #[test]
    fn read_failure_with_free_spin_stops_motion() {
        let mut engine = PuppyArm::new(0);

        spin_joint_zero(&mut engine, 300, 10);
        engine.step(20);
        assert_eq!(engine.fake_servo(2).unwrap().wheel_speed, 300);

        engine.set_read_failure(2, true);
        engine.step(40);

        let state = engine.state();
        assert_eq!(state.joints[0].speed, 0);
        assert!(!state.joints[0].is_online);
        assert_eq!(engine.fake_servo(2).unwrap().wheel_speed, 0);
    }

    #[test]
    fn read_failure_with_active_target_stops_motion() {
        let mut engine = PuppyArm::new(0);

        engine.handle_arm_cmd(ArmCommand::SetSpeed(300), 10);
        engine.handle_arm_cmd(
            ArmCommand::SetJointTick {
                joint: 0,
                tick: 500,
            },
            10,
        );
        engine.step(20);
        assert!(engine.fake_servo(2).unwrap().wheel_speed > 0);

        engine.set_read_failure(2, true);
        engine.step(40);

        let state = engine.state();
        assert_eq!(state.joints[0].speed, 0);
        assert!(state.joints[0].target_tick.is_some());
        assert_eq!(engine.fake_servo(2).unwrap().wheel_speed, 0);
    }

    #[test]
    fn recovered_servo_is_left_stopped() {
        let mut engine = PuppyArm::new(0);

        spin_joint_zero(&mut engine, 300, 10);
        engine.step(20);
        engine.set_read_failure(2, true);
        engine.step(40);
        engine.set_read_failure(2, false);
        engine.step(1060);

        assert_eq!(engine.state().joints[0].speed, 0);
        assert_eq!(engine.fake_servo(2).unwrap().wheel_speed, 0);
    }

    #[test]
    fn wheel_mode_recovery_waits_for_retry_timeout_after_write_failure() {
        let mut engine = PuppyArm::new(0);

        engine.set_write_failure(2, true);
        spin_joint_zero(&mut engine, 300, 10);
        engine.step(20);
        assert_eq!(engine.fake_servo(2).unwrap().wheel_speed, 0);

        engine.set_write_failure(2, false);
        let writes_before_retry = engine.bus_writes().len();
        engine.step(40);
        assert!(
            !engine.bus_writes()[writes_before_retry..]
                .iter()
                .any(|write| is_write_to(write, 2, SMS_STS_MODE)
                    || is_write_to(write, 2, SMS_STS_ACC))
        );

        engine.step(1010);
        assert_eq!(engine.fake_servo(2).unwrap().wheel_speed, 300);
        assert!(
            engine.bus_writes()[writes_before_retry..]
                .iter()
                .any(|write| is_write_to(write, 2, SMS_STS_MODE))
        );
    }

    #[test]
    fn changing_servo_ids_reinitializes_wheel_mode_before_speed() {
        let mut engine = PuppyArm::new(0);
        let before = engine.bus_writes().len();

        engine.handle_arm_cmd(ArmCommand::SetServoIds([3, 2, 4, 5]), 10);
        engine.handle_arm_cmd(ArmCommand::SetSpeed(250), 20);
        engine.handle_arm_cmd(
            ArmCommand::Spin {
                joint: 0,
                direction: 1,
            },
            20,
        );
        engine.step(30);

        let writes = &engine.bus_writes()[before..];
        let mode_index = writes
            .iter()
            .position(|write| is_write_to(write, 3, SMS_STS_MODE))
            .expect("missing wheel mode write for servo 3");
        let speed_index = writes
            .iter()
            .position(|write| is_write_to(write, 3, SMS_STS_ACC))
            .expect("missing wheel speed write for servo 3");
        assert!(mode_index < speed_index);
        assert_eq!(engine.fake_servo(3).unwrap().wheel_speed, 250);
    }

    #[test]
    fn direct_servo_set_targets_matching_arm_joint() {
        let mut engine = PuppyArm::new(0);

        engine.handle_arm_cmd(
            ArmCommand::SetServoAngle {
                servo_id: 3,
                angle_rad: core::f64::consts::FRAC_PI_2,
                speed: 2400,
            },
            10,
        );

        let state = engine.state();
        assert!(state.joints[1].target_tick.is_some());
        assert_eq!(state.default_speed, 2400);
        let servo = engine.fake_servo(3).unwrap();
        assert_eq!(servo.mode, Mode::Wheel);
    }

    #[test]
    fn direct_servo_set_ignores_non_arm_servo() {
        let mut engine = PuppyArm::new(0);
        let before = engine.state();

        engine.handle_arm_cmd(
            ArmCommand::SetServoAngle {
                servo_id: 42,
                angle_rad: core::f64::consts::PI / 3.0,
                speed: 2400,
            },
            10,
        );

        assert_eq!(engine.state(), before);
    }

    #[test]
    fn invalid_servo_id_config_does_not_mutate_state() {
        let mut engine = PuppyArm::new(0);

        engine.handle_arm_cmd(ArmCommand::SetServoIds([0, 3, 4, 5]), 10);

        assert_eq!(
            engine.state().joints.map(|joint| joint.servo_id),
            [2, 3, 4, 5]
        );
    }

    #[test]
    fn snapshot_exposes_joint_status_target_speed_limit_and_fault_fields() {
        let mut engine = PuppyArm::new(0);

        engine.controller.safety.default_speed = 321;
        engine.controller.safety.joints[0].tick = Some(2000);
        engine.controller.safety.joints[0].target_tick = Some(2100);
        engine.controller.safety.joints[0].speed = 123;
        engine.controller.safety.joints[0].tick_min = -500;
        engine.controller.safety.joints[0].tick_max = 500;
        engine.controller.safety.joints[0].is_online = false;
        engine.controller.safety.joints[0].has_feedback = false;
        engine.controller.safety.joints[0].fault = Some(servo_safety::SafetyFault::Stall);
        engine.controller.safety.last_error = Some(servo_safety::SafetyFault::FeedbackStale);

        let snapshot = engine.snapshot();

        assert_eq!(snapshot.default_speed, 321);
        assert_eq!(
            snapshot.last_error,
            Some(servo_safety::SafetyFault::FeedbackStale)
        );
        assert_eq!(snapshot.joints[0].servo_id, 2);
        assert_eq!(snapshot.joints[0].tick, Some(2000));
        assert_eq!(snapshot.joints[0].target_tick, Some(2100));
        assert_eq!(snapshot.joints[0].speed, 123);
        assert_eq!(snapshot.joints[0].limit_min, -500);
        assert_eq!(snapshot.joints[0].limit_max, 500);
        assert!(snapshot.joints[0].limit_reached);
        assert!(!snapshot.joints[0].online);
        assert!(!snapshot.joints[0].has_feedback);
        assert_eq!(
            snapshot.joints[0].fault,
            Some(servo_safety::SafetyFault::Stall)
        );
    }

    #[test]
    fn deadman_feedback_timeout_stops_free_spin() {
        let mut engine = PuppyArm::new(0);

        spin_joint_zero(&mut engine, 300, 10);
        engine.step(20);
        for servo_id in 2..=5 {
            engine.set_read_failure(servo_id, true);
        }
        engine.step(servo_safety::DEADMAN_FEEDBACK_TIMEOUT_MS + 30);

        assert_eq!(
            engine.controller.safety.last_error,
            Some(servo_safety::SafetyFault::DeadmanFeedbackStale)
        );
        assert_eq!(engine.state().joints[0].speed, 0);
        assert_eq!(engine.fake_servo(2).unwrap().wheel_speed, 0);
    }

    #[test]
    fn deadman_command_timeout_stops_free_spin() {
        let mut engine = PuppyArm::new(0);

        spin_joint_zero(&mut engine, 300, 10);
        engine.step(20);
        engine.set_position(2, 100);
        engine.step(servo_safety::DEADMAN_CMD_TIMEOUT_MS + 11);

        assert_eq!(
            engine.controller.safety.last_error,
            Some(servo_safety::SafetyFault::DeadmanCommandStale)
        );
        assert_eq!(engine.state().joints[0].speed, 0);
        assert_eq!(engine.fake_servo(2).unwrap().wheel_speed, 0);
    }

    #[test]
    fn deadman_command_timeout_does_not_cancel_target_tracking() {
        let mut engine = PuppyArm::new(0);

        engine.handle_arm_cmd(ArmCommand::SetSpeed(300), 10);
        engine.handle_arm_cmd(
            ArmCommand::SetJointTick {
                joint: 0,
                tick: 1000,
            },
            10,
        );
        engine.step(20);
        engine.set_position(2, 100);
        engine.step(360);
        engine.set_position(2, 200);
        engine.step(720);
        engine.set_position(2, 300);
        engine.step(servo_safety::DEADMAN_CMD_TIMEOUT_MS + 11);

        let state = engine.state();
        assert_eq!(engine.controller.safety.last_error, None);
        assert_eq!(state.joints[0].target_tick, Some(1000));
        assert!(state.joints[0].speed > 0);
    }

    #[test]
    fn over_temperature_fault_stops_motion() {
        let mut engine = PuppyArm::new(0);

        spin_joint_zero(&mut engine, 300, 10);
        engine.step(20);
        engine.controller.safety.joints[0].temp_c = Some(servo_safety::MAX_TEMP_C + 1);
        engine.step(40);

        assert_eq!(
            engine.controller.safety.joints[0].fault,
            Some(servo_safety::SafetyFault::OverTemperature)
        );
        assert_eq!(engine.state().joints[0].speed, 0);
        assert_eq!(engine.fake_servo(2).unwrap().wheel_speed, 0);
    }

    #[test]
    fn target_tracking_stall_fault_stops_motion() {
        let mut engine = PuppyArm::new(0);

        engine.handle_arm_cmd(ArmCommand::SetSpeed(300), 10);
        engine.handle_arm_cmd(
            ArmCommand::SetJointTick {
                joint: 0,
                tick: 1000,
            },
            10,
        );
        engine.step(20);
        engine.step(20 + servo_safety::STALL_TRIP_MS);

        assert_eq!(
            engine.controller.safety.joints[0].fault,
            Some(servo_safety::SafetyFault::Stall)
        );
        assert_eq!(engine.state().joints[0].speed, 0);
        assert_eq!(engine.fake_servo(2).unwrap().wheel_speed, 0);
    }

    #[test]
    fn clear_faults_command_clears_selected_and_all_faults() {
        let mut engine = PuppyArm::new(0);

        engine.controller.safety.joints[0].fault = Some(servo_safety::SafetyFault::Stall);
        engine.controller.safety.joints[1].fault = Some(servo_safety::SafetyFault::OverTemperature);
        engine.handle_arm_cmd(ArmCommand::ClearFaults { joint: Some(0) }, 10);
        assert_eq!(engine.controller.safety.joints[0].fault, None);
        assert_eq!(
            engine.controller.safety.joints[1].fault,
            Some(servo_safety::SafetyFault::OverTemperature)
        );

        engine.handle_arm_cmd(ArmCommand::ClearFaults { joint: None }, 20);
        assert_eq!(engine.controller.safety.joints[1].fault, None);
    }

    #[test]
    fn spin_clears_latched_fault_for_joint() {
        let mut engine = PuppyArm::new(0);

        engine.controller.safety.joints[0].fault = Some(servo_safety::SafetyFault::Stall);
        spin_joint_zero(&mut engine, 300, 10);

        assert_eq!(engine.controller.safety.joints[0].fault, None);
    }

    #[test]
    fn stop_is_state_safe_when_zero_speed_write_fails() {
        let mut engine = PuppyArm::new(0);

        spin_joint_zero(&mut engine, 300, 10);
        engine.step(20);
        assert_eq!(engine.fake_servo(2).unwrap().wheel_speed, 300);

        engine.set_write_failure(2, true);
        engine.handle_arm_cmd(ArmCommand::Stop { joint: 0 }, 30);
        engine.step(40);

        let state = engine.state();
        assert_eq!(state.joints[0].speed, 0);
        assert_eq!(state.joints[0].target_tick, None);
    }

    fn is_write_to(packet: &[u8], servo_id: u8, address: u8) -> bool {
        packet.len() >= 7
            && packet[0] == 0xff
            && packet[1] == 0xff
            && packet[2] == servo_id
            && packet[4] == INST_WRITE
            && packet[5] == address
    }

    fn spin_joint_zero(engine: &mut PuppyArm, speed: i16, now_ms: u64) {
        engine.handle_arm_cmd(ArmCommand::SetSpeed(speed), now_ms);
        engine.handle_arm_cmd(
            ArmCommand::Spin {
                joint: 0,
                direction: 1,
            },
            now_ms,
        );
    }
}
