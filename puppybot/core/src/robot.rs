extern crate alloc;

use alloc::vec::Vec;

use crate::{
    config::{ConfigError, PuppybotConfigV1},
    drive::{DriveActuator, DriveController, DriveOutput},
    protocol::{
        self, ProtocolEvent, ProtocolJointTelemetry, ProtocolOutput, ProtocolState, RobotConfig,
    },
    puppyarm::{
        puppyarm::{PuppyArm, PuppyarmTelemetry},
        servo_safety::{BLOCKING_SERVO_STATUS, is_outside_limits},
        types::{ACTUATOR_COUNT, ControllerError, GRIPPER_INDEX, JOINT_COUNT},
    },
    stservo::{Error as StServoError, Mode, SerialBus, StServo, wheel_speed_params},
};

#[cfg(test)]
use crate::config::DEFAULT_GRIPPER_SPEED;

pub use crate::system::PuppyBotSystem;

const ARM_WHEEL_ACC: u8 = 0;
const STEERING_SERVO_SPEED: u16 = 2400;
const STEERING_SERVO_ACC: u8 = 0;

pub struct Puppybot {
    pub arm: PuppyArm,
    drive: DriveController,
    protocol: ProtocolState,
    telemetry_seq: u32,
    last_steering_sent: Option<(u8, u16)>,
    next_feedback_joint: usize,
}

pub fn arm_state_frame(telemetry: &PuppyarmTelemetry) -> Vec<u8> {
    let actuator_count = if telemetry.has_gripper {
        ACTUATOR_COUNT
    } else {
        JOINT_COUNT
    };
    let joints = telemetry.joints[..actuator_count]
        .iter()
        .map(|joint| ProtocolJointTelemetry {
            servo_id: joint.servo_id,
            online: joint.online,
            has_feedback: joint.has_feedback,
            limit_reached: joint.limit_reached,
            tick: joint.tick,
            target_tick: joint.target_tick,
            speed: joint.speed,
            limit_min: joint.limit_min,
            limit_max: joint.limit_max,
            angle_deg: joint.angle_deg(),
            target_angle_deg: joint.target_angle_deg(),
            fault: joint.fault.map(protocol::fault_name),
        })
        .collect::<Vec<_>>();
    protocol::arm_state_frame(&joints, telemetry.coords_mm, telemetry.target_coords_mm)
}

fn arm_servo_write_applied<E>(result: &Result<(), StServoError<E>>) -> bool {
    match result {
        Ok(()) => true,
        Err(StServoError::Status(status)) => status & BLOCKING_SERVO_STATUS == 0,
        Err(_) => false,
    }
}

impl Puppybot {
    pub fn new(now_ms: u64) -> Self {
        Self {
            arm: PuppyArm::new(now_ms),
            drive: DriveController::new(Default::default(), now_ms),
            protocol: ProtocolState::default(),
            telemetry_seq: 0,
            last_steering_sent: None,
            next_feedback_joint: 0,
        }
    }

    pub fn new_with_config(config: &PuppybotConfigV1, now_ms: u64) -> Result<Self, ConfigError> {
        config.validate()?;
        Ok(Self {
            arm: PuppyArm::new_with_config(&config.arm, now_ms)?,
            drive: DriveController::new(config.drive, now_ms),
            protocol: ProtocolState {
                config: RobotConfig {
                    steering_servo_id: config.drive.steering_servo_id,
                    arm_servo_ids: config.arm.servo_ids(),
                },
                telemetry_enabled: false,
            },
            telemetry_seq: 0,
            last_steering_sent: None,
            next_feedback_joint: 0,
        })
    }

    pub fn handle_event(&mut self, event: ProtocolEvent, now_ms: u64) {
        if let Err(err) = self.try_handle_event(event, now_ms) {
            log::warn!("robot event rejected: {:?}", err);
        }
    }

    pub fn try_handle_event(
        &mut self,
        event: ProtocolEvent,
        now_ms: u64,
    ) -> Result<(), ControllerError> {
        match event {
            ProtocolEvent::Arm(command) => {
                self.arm.try_handle_arm_cmd(command, now_ms)?;
            }
            ProtocolEvent::Drive(command) => {
                self.drive.handle_command(command, now_ms);
            }
        }
        Ok(())
    }

    pub fn handle_frame(&mut self, frame: &[u8], now_ms: u64) -> ProtocolOutput {
        let output = protocol::handle_binary_command(frame, &mut self.protocol);
        for event in output.events.iter().copied() {
            self.handle_event(event, now_ms);
        }
        output
    }

    pub fn tick(&mut self, elapsed_ms: u64, now_ms: u64) {
        let _ = elapsed_ms;
        self.drive.tick(now_ms);
    }

    pub fn protocol_state(&self) -> ProtocolState {
        self.protocol
    }

    pub fn set_telemetry_enabled(&mut self, enabled: bool) {
        self.protocol.telemetry_enabled = enabled;
    }

    pub fn telemetry_enabled(&self) -> bool {
        self.protocol.telemetry_enabled
    }

    pub fn drive_output(&self) -> DriveOutput {
        self.drive.output()
    }

    pub fn arm_telemetry(&self) -> PuppyarmTelemetry {
        self.arm.telemetry_snapshot(self.telemetry_seq)
    }

    pub fn arm_state_frame(&self) -> Vec<u8> {
        arm_state_frame(&self.arm_telemetry())
    }

    fn record_servo_feedback_error<E>(
        &mut self,
        joint: usize,
        servo_id: u8,
        now_ms: u64,
        err: &StServoError<E>,
    ) where
        E: core::fmt::Debug,
    {
        let status = err.status();
        if joint == GRIPPER_INDEX {
            let gripper = self.arm.joints[GRIPPER_INDEX];
            log::warn!(
                "gripper feedback failed servo {} sample_ms {} error {:?} previous_tick {:?} commanded_speed {} last_sent {:?} status 0x{:02x} fault {:?}",
                servo_id,
                now_ms,
                err,
                gripper.tick,
                gripper.speed,
                gripper.last_sent_speed,
                gripper.servo_status,
                gripper.fault
            );
        } else {
            log::warn!("read position failed for servo {}: {:?}", servo_id, err);
        }
        self.arm.record_feedback_error(joint);
        if let Some(status) = status {
            self.arm.record_servo_status(joint, status);
        }
    }

    async fn read_servo_feedback<B>(&mut self, servo: &mut StServo<B>, now_ms: u64)
    where
        B: SerialBus,
        B::Error: core::fmt::Debug,
    {
        let actuator_count = self.arm.actuator_count();
        for offset in 0..actuator_count {
            let joint = (self.next_feedback_joint + offset) % actuator_count;
            let Some(servo_id) = self.arm.joint_servo_id(joint) else {
                continue;
            };
            self.next_feedback_joint = (joint + 1) % actuator_count;
            if joint == GRIPPER_INDEX {
                match servo.read_feedback_with_status(servo_id).await {
                    Ok(response) => {
                        let feedback = response.value;
                        self.arm.record_feedback(joint, feedback.position, now_ms);
                        self.arm.record_servo_status(joint, response.status);
                        self.arm
                            .record_temperature(joint, Some(feedback.temperature_c));
                        let gripper = self.arm.joints[GRIPPER_INDEX];
                        log::debug!(
                            "gripper feedback servo {} sample_ms {} tick {} delta {:+} present_speed {:+} load_raw {:+} voltage {:.1}V voltage_raw {} temperature {}C moving {} current_raw {:+} status 0x{:02x} commanded_speed {} last_sent {:?} limits {}..{} outside {} fault {:?}",
                            servo_id,
                            now_ms,
                            feedback.position,
                            gripper.tick_delta,
                            feedback.speed,
                            feedback.load,
                            f32::from(feedback.voltage_raw) * 0.1,
                            feedback.voltage_raw,
                            feedback.temperature_c,
                            feedback.moving,
                            feedback.current,
                            response.status,
                            gripper.speed,
                            gripper.last_sent_speed,
                            gripper.tick_min,
                            gripper.tick_max,
                            is_outside_limits(&gripper),
                            gripper.fault
                        );
                    }
                    Err(err) => {
                        self.record_servo_feedback_error(joint, servo_id, now_ms, &err);
                    }
                }
            } else {
                match servo.read_position_with_status(servo_id).await {
                    Ok(response) => {
                        self.arm.record_feedback(joint, response.value, now_ms);
                        self.arm.record_servo_status(joint, response.status);
                    }
                    Err(err) => {
                        self.record_servo_feedback_error(joint, servo_id, now_ms, &err);
                    }
                }
            }
            break;
        }
    }

    fn record_arm_servo_result<E>(&mut self, joint: usize, result: &Result<(), StServoError<E>>) {
        let status = match result {
            Ok(()) => Some(0),
            Err(err) => err.status(),
        };
        if let Some(status) = status {
            self.arm.record_servo_status(joint, status);
        }
    }

    async fn apply_steering_output<B>(&mut self, servo: &mut StServo<B>)
    where
        B: SerialBus,
        B::Error: core::fmt::Debug,
    {
        let output = self.drive.output();
        if !output.active || output.steering_servo_id == 0 {
            return;
        }
        let steering = (output.steering_servo_id, output.steering_angle_deg);
        if self.last_steering_sent == Some(steering) {
            return;
        }

        match servo
            .write_angle(
                output.steering_servo_id,
                output.steering_angle_deg,
                STEERING_SERVO_SPEED,
                STEERING_SERVO_ACC,
            )
            .await
        {
            Ok(()) => self.last_steering_sent = Some(steering),
            Err(err) => log::warn!(
                "set steering servo {} angle {} failed: {:?}",
                output.steering_servo_id,
                output.steering_angle_deg,
                err
            ),
        }
    }

    fn apply_drive_actuator_output<D>(&self, drive_actuator: &mut D)
    where
        D: DriveActuator,
        D::Error: core::fmt::Debug,
    {
        let output = self.drive.output();
        if let Err(err) = drive_actuator.apply_drive_output(output) {
            log::warn!("set drive output {:?} failed: {:?}", output, err);
        }
    }

    async fn apply_arm_outputs<B>(&mut self, servo: &mut StServo<B>, now_ms: u64)
    where
        B: SerialBus,
        B::Error: core::fmt::Debug,
    {
        let initialize_wheel_mode = self.arm.take_initialize_wheel_mode();
        let outputs = self.arm.update(now_ms);
        for joint in 0..outputs.len() {
            let output = outputs[joint];
            if output.servo_id == 0 {
                continue;
            }
            if !initialize_wheel_mode && !output.should_send {
                continue;
            }
            let mut wheel_mode_ready = self.arm.wheel_mode_ready(joint, output.servo_id);
            if !wheel_mode_ready {
                if self.arm.servo_status_blocks_motion(joint) {
                    continue;
                }
                if !self.arm.begin_wheel_mode_attempt(
                    joint,
                    output.servo_id,
                    now_ms,
                    initialize_wheel_mode,
                ) {
                    continue;
                }

                let result = servo.set_mode(output.servo_id, Mode::Wheel).await;
                wheel_mode_ready = arm_servo_write_applied(&result);
                if wheel_mode_ready {
                    if let Err(err) = &result {
                        log::warn!(
                            "mode {:?} ready for servo {} with warning: {:?}",
                            Mode::Wheel,
                            output.servo_id,
                            err
                        );
                    } else {
                        log::info!("mode {:?} ready for servo {}", Mode::Wheel, output.servo_id);
                    }
                } else if let Err(err) = &result {
                    log::warn!(
                        "set mode {:?} failed for servo {}: {:?}",
                        Mode::Wheel,
                        output.servo_id,
                        err
                    );
                }
                self.record_arm_servo_result(joint, &result);
                self.arm.record_set_mode_result(
                    joint,
                    output.servo_id,
                    Mode::Wheel,
                    wheel_mode_ready,
                );
            }

            if !wheel_mode_ready || !self.arm.can_write_wheel_speed(joint, output.servo_id) {
                continue;
            }

            if joint == GRIPPER_INDEX {
                let gripper = self.arm.joints[GRIPPER_INDEX];
                let params = wheel_speed_params(output.speed, ARM_WHEEL_ACC);
                log::info!(
                    "gripper wheel write servo {} sample_ms {} speed {} params {:02x?} tick {:?} delta {:+} status 0x{:02x} limits {}..{} fault {:?}",
                    output.servo_id,
                    now_ms,
                    output.speed,
                    params,
                    gripper.tick,
                    gripper.tick_delta,
                    gripper.servo_status,
                    gripper.tick_min,
                    gripper.tick_max,
                    gripper.fault
                );
            }
            let result = servo
                .write_wheel_speed(output.servo_id, output.speed, ARM_WHEEL_ACC)
                .await;
            let success = arm_servo_write_applied(&result);
            if !success && let Err(err) = &result {
                log::warn!(
                    "set wheel speed failed for servo {} speed {}: {:?}",
                    output.servo_id,
                    output.speed,
                    err
                );
            }
            self.record_arm_servo_result(joint, &result);
            if joint == GRIPPER_INDEX {
                log::info!(
                    "gripper wheel result servo {} sample_ms {} speed {} applied {} response_status {:?}",
                    output.servo_id,
                    now_ms,
                    output.speed,
                    success,
                    result.as_ref().err().and_then(StServoError::status)
                );
            }
            self.arm.record_wheel_speed_result(
                joint,
                output.servo_id,
                output.speed,
                success,
                now_ms,
            );
        }
    }

    pub async fn run_once<B, F>(
        &mut self,
        servo: &mut StServo<B>,
        now_ms: u64,
        mut receive_event: F,
    ) where
        B: SerialBus,
        B::Error: core::fmt::Debug,
        F: FnMut() -> Option<ProtocolEvent>,
    {
        self.read_servo_feedback(servo, now_ms).await;
        while let Some(event) = receive_event() {
            self.handle_event(event, now_ms);
        }

        self.drive.tick(now_ms);
        self.apply_steering_output(servo).await;
        self.apply_arm_outputs(servo, now_ms).await;
        self.telemetry_seq = self.telemetry_seq.wrapping_add(1);
    }

    pub async fn run_once_with_drive<B, D, F>(
        &mut self,
        servo: &mut StServo<B>,
        drive_actuator: &mut D,
        now_ms: u64,
        mut receive_event: F,
    ) where
        B: SerialBus,
        B::Error: core::fmt::Debug,
        D: DriveActuator,
        D::Error: core::fmt::Debug,
        F: FnMut() -> Option<ProtocolEvent>,
    {
        self.read_servo_feedback(servo, now_ms).await;
        while let Some(event) = receive_event() {
            self.handle_event(event, now_ms);
        }

        self.drive.tick(now_ms);
        self.apply_steering_output(servo).await;
        self.apply_drive_actuator_output(drive_actuator);
        self.apply_arm_outputs(servo, now_ms).await;
        self.telemetry_seq = self.telemetry_seq.wrapping_add(1);
    }

    pub async fn try_run_once_with_drive<B, D, F>(
        &mut self,
        servo: &mut StServo<B>,
        drive_actuator: &mut D,
        now_ms: u64,
        mut receive_event: F,
    ) -> Result<(), ControllerError>
    where
        B: SerialBus,
        B::Error: core::fmt::Debug,
        D: DriveActuator,
        D::Error: core::fmt::Debug,
        F: FnMut() -> Option<ProtocolEvent>,
    {
        self.read_servo_feedback(servo, now_ms).await;
        while let Some(event) = receive_event() {
            self.try_handle_event(event, now_ms)?;
        }

        self.drive.tick(now_ms);
        self.apply_steering_output(servo).await;
        self.apply_drive_actuator_output(drive_actuator);
        self.apply_arm_outputs(servo, now_ms).await;
        self.telemetry_seq = self.telemetry_seq.wrapping_add(1);
        Ok(())
    }
}

impl Default for Puppybot {
    fn default() -> Self {
        Self::new(0)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{
        config::{
            JointCalibration, PUPPYBOT_CONFIG_VERSION, PuppyArmConfig, PuppybotConfigV1, SERIAL_LEN,
        },
        drive::DriveCommand,
        protocol::{CMD_CONFIG_GET, CMD_DRIVE_STEER, CMD_STOP_DRIVE, ProtocolEvent, command_frame},
        puppyarm::types::{ACTUATOR_COUNT, ArmCommand, GRIPPER_INDEX},
        stservo::{
            STATUS_INPUT_VOLTAGE, STATUS_OVERLOAD, StServo,
            mock::{FakeSerialBus, FakeServo, block_on_ready},
        },
    };

    fn serial(value: &str) -> [u8; SERIAL_LEN] {
        let mut serial = [0; SERIAL_LEN];
        serial[..value.len()].copy_from_slice(value.as_bytes());
        serial
    }

    fn joint(servo_id: u8) -> JointCalibration {
        JointCalibration {
            servo_id,
            tick_min: 0,
            tick_max: 4095,
            reference_tick: 2048,
            reference_angle_rad: 0.0,
            angle_sign: 1,
            drive_sign: 1,
            limit_enabled: true,
        }
    }

    fn config_with_arm_servo_ids(ids: [u8; JOINT_COUNT]) -> PuppybotConfigV1 {
        PuppybotConfigV1 {
            version: PUPPYBOT_CONFIG_VERSION,
            serial: serial("PB-DEV-0001"),
            drive: Default::default(),
            arm: PuppyArmConfig {
                joints: [joint(ids[0]), joint(ids[1]), joint(ids[2]), joint(ids[3])],
                gripper: None,
                gripper_speed: DEFAULT_GRIPPER_SPEED,
            },
            coordinate: Default::default(),
        }
    }

    fn run_feedback_cycle<B>(robot: &mut Puppybot, servo: &mut StServo<B>)
    where
        B: SerialBus,
        B::Error: core::fmt::Debug,
    {
        for tick in 0..JOINT_COUNT {
            block_on_ready(robot.run_once(servo, (tick as u64 + 1) * 20, || None));
        }
    }

    #[test]
    fn handle_frame_updates_drive_output() {
        let mut robot = Puppybot::new(0);

        robot.handle_frame(&command_frame(CMD_DRIVE_STEER, &[50, 100]), 10);

        let output = robot.drive_output();
        assert_eq!(output.left_speed, 50);
        assert_eq!(output.right_speed, 50);
        assert_eq!(output.steering_angle_deg, 135);
        assert!(output.active);
    }

    #[test]
    fn handle_frame_returns_protocol_response() {
        let mut robot = Puppybot::new(0);

        let output = robot.handle_frame(&command_frame(CMD_CONFIG_GET, &[]), 10);

        assert!(output.response.is_some());
    }

    #[test]
    fn handle_event_applies_drive_command() {
        let mut robot = Puppybot::new(0);

        robot.handle_event(
            ProtocolEvent::Drive(DriveCommand::SetMotorSpeed {
                motor_id: 1,
                speed: -25,
            }),
            10,
        );

        assert_eq!(robot.drive_output().left_speed, -25);
        assert_eq!(robot.drive_output().right_speed, 0);
    }

    #[test]
    fn handle_event_applies_arm_command() {
        let mut robot = Puppybot::new(0);

        robot.handle_event(ProtocolEvent::Arm(ArmCommand::SetSpeed(123)), 10);

        assert!(!robot.arm_state_frame().is_empty());
    }

    #[test]
    fn tick_stops_stale_drive_output() {
        let mut robot = Puppybot::new(0);

        robot.handle_frame(&command_frame(CMD_DRIVE_STEER, &[50, 0]), 10);
        robot.tick(499, 509);
        assert!(robot.drive_output().active);

        robot.tick(1, 510);
        assert!(!robot.drive_output().active);
    }

    #[test]
    fn stop_drive_frame_stops_drive_output() {
        let mut robot = Puppybot::new(0);

        robot.handle_frame(&command_frame(CMD_DRIVE_STEER, &[50, 0]), 10);
        robot.handle_frame(&command_frame(CMD_STOP_DRIVE, &[]), 20);

        assert!(!robot.drive_output().active);
    }

    #[test]
    fn system_new_wraps_bus_and_run_once_reads_feedback() {
        let config = config_with_arm_servo_ids([11, 12, 13, 14]);
        let robot = Puppybot::new_with_config(&config, 0).unwrap();
        let mut bus = FakeSerialBus::new();
        for (servo_id, position) in [(11, 101), (12, 202), (13, 303), (14, 404)] {
            bus.set_servo(FakeServo::new(servo_id, position));
        }
        let mut system = PuppyBotSystem::new(robot, bus);

        for _ in 0..JOINT_COUNT {
            block_on_ready(system.run_once(|| None));
        }

        let telemetry = system.robot().arm_telemetry();
        assert_eq!(telemetry.joints[0].servo_id, 11);
        assert_eq!(telemetry.joints[0].tick, Some(101));
        assert_eq!(telemetry.joints[1].tick, Some(202));
        assert_eq!(telemetry.joints[2].tick, Some(303));
        assert_eq!(telemetry.joints[3].tick, Some(404));
    }

    #[test]
    fn system_with_servo_preserves_wrapped_bus_access() {
        let robot = Puppybot::new(0);
        let servo = StServo::new(FakeSerialBus::new().with_servo(1, 1234));
        let mut system = PuppyBotSystem::with_servo(robot, servo);

        assert_eq!(system.servo().bus().servo(1).unwrap().position, 1234);

        system.servo_mut().bus_mut().set_position(1, 2048);

        assert_eq!(system.servo().bus().servo(1).unwrap().position, 2048);
    }

    #[test]
    fn system_run_once_advances_time_deterministically() {
        let mut bus = FakeSerialBus::new();
        for servo_id in 1..=4 {
            bus.set_servo(FakeServo::new(servo_id, 0));
        }
        bus.set_servo(FakeServo::new(7, 0));
        let mut system = PuppyBotSystem::new(Puppybot::new(0), bus);

        assert_eq!(system.now_ms(), 0);

        block_on_ready(system.run_once(|| None));

        assert_eq!(system.now_ms(), crate::system::PUPPYBOT_SYSTEM_TICK_MS);
    }

    #[test]
    fn run_once_handles_robot_events_on_shared_servo_bus() {
        let mut robot = Puppybot::new(0);
        let mut bus = FakeSerialBus::new();
        for servo_id in 1..=4 {
            bus.set_servo(FakeServo::new(servo_id, 0));
        }
        bus.set_servo(FakeServo::new(7, 0));
        let mut servo = StServo::new(bus);
        let mut events = [
            ProtocolEvent::Arm(ArmCommand::SetSpeed(300)),
            ProtocolEvent::Arm(ArmCommand::Spin {
                joint: 0,
                direction: 1,
            }),
        ]
        .into_iter();

        block_on_ready(robot.run_once(&mut servo, 20, || events.next()));

        assert_eq!(servo.bus().servo(1).unwrap().wheel_speed, 300);
        assert_eq!(robot.arm_telemetry().joints[0].tick, Some(0));
    }

    #[test]
    fn run_once_drive_forward_with_no_steering_servo_does_not_write_arm_yaw() {
        let mut config = config_with_arm_servo_ids([1, 2, 3, 4]);
        config.drive.steering_servo_id = 0;
        let mut robot = Puppybot::new_with_config(&config, 0).unwrap();
        let mut bus = FakeSerialBus::new();
        for (servo_id, position) in [(1, 1234), (2, 2000), (3, 2000), (4, 2000)] {
            bus.set_servo(FakeServo::new(servo_id, position));
        }
        let mut servo = StServo::new(bus);
        let mut event = Some(ProtocolEvent::Drive(DriveCommand::DriveSteer {
            throttle: 35,
            steering: 0,
        }));

        block_on_ready(robot.run_once(&mut servo, 20, || event.take()));

        assert_eq!(robot.drive_output().steering_servo_id, 0);
        assert_eq!(robot.drive_output().left_speed, 35);
        assert_eq!(servo.bus().servo(1).unwrap().position, 1234);
    }

    #[test]
    fn run_once_drive_forward_with_separate_steering_servo_does_not_write_arm_yaw() {
        let mut config = config_with_arm_servo_ids([1, 2, 3, 4]);
        config.drive.steering_servo_id = 5;
        let mut robot = Puppybot::new_with_config(&config, 0).unwrap();
        let mut bus = FakeSerialBus::new();
        for (servo_id, position) in [(1, 1234), (2, 2000), (3, 2000), (4, 2000), (5, 1500)] {
            bus.set_servo(FakeServo::new(servo_id, position));
        }
        let mut servo = StServo::new(bus);
        let mut event = Some(ProtocolEvent::Drive(DriveCommand::DriveSteer {
            throttle: 35,
            steering: 0,
        }));

        block_on_ready(robot.run_once(&mut servo, 20, || event.take()));

        assert_eq!(robot.drive_output().steering_servo_id, 5);
        assert_eq!(robot.drive_output().left_speed, 35);
        assert_eq!(servo.bus().servo(1).unwrap().position, 1234);
        assert_ne!(servo.bus().servo(5).unwrap().position, 1500);
    }

    #[test]
    fn run_once_polls_feedback_one_joint_at_a_time() {
        let config = config_with_arm_servo_ids([11, 12, 13, 14]);
        let mut robot = Puppybot::new_with_config(&config, 0).unwrap();
        let mut bus = FakeSerialBus::new();
        for (servo_id, position) in [(11, 101), (12, 202), (13, 303), (14, 404)] {
            bus.set_servo(FakeServo::new(servo_id, position));
        }
        let mut servo = StServo::new(bus);

        block_on_ready(robot.run_once(&mut servo, 20, || None));

        let telemetry = robot.arm_telemetry();
        assert_eq!(telemetry.joints[0].servo_id, 11);
        assert_eq!(telemetry.joints[0].tick, Some(101));
        assert_eq!(telemetry.joints[1].tick, None);
        assert_eq!(telemetry.joints[2].tick, None);
        assert_eq!(telemetry.joints[3].tick, None);
    }

    #[test]
    fn run_once_reads_feedback_from_configured_arm_servo_ids_after_cycle() {
        let config = config_with_arm_servo_ids([11, 12, 13, 14]);
        let mut robot = Puppybot::new_with_config(&config, 0).unwrap();
        let mut bus = FakeSerialBus::new();
        for (servo_id, position) in [(11, 101), (12, 202), (13, 303), (14, 404)] {
            bus.set_servo(FakeServo::new(servo_id, position));
        }
        let mut servo = StServo::new(bus);

        run_feedback_cycle(&mut robot, &mut servo);

        let telemetry = robot.arm_telemetry();
        assert_eq!(telemetry.joints[0].servo_id, 11);
        assert_eq!(telemetry.joints[0].tick, Some(101));
        assert_eq!(telemetry.joints[1].tick, Some(202));
        assert_eq!(telemetry.joints[2].tick, Some(303));
        assert_eq!(telemetry.joints[3].tick, Some(404));
    }

    #[test]
    fn run_once_preserves_feedback_while_exposing_servo_status_errors() {
        let config = config_with_arm_servo_ids([11, 12, 13, 14]);
        let mut robot = Puppybot::new_with_config(&config, 0).unwrap();
        let mut bus = FakeSerialBus::new();
        for (servo_id, position) in [(11, 101), (12, 202), (13, 303), (14, 404)] {
            bus.set_servo(FakeServo::new(servo_id, position));
        }
        bus.set_status_error(11, STATUS_INPUT_VOLTAGE | STATUS_OVERLOAD);
        let mut servo = StServo::new(bus);

        block_on_ready(robot.run_once(&mut servo, 20, || None));

        let joint = robot.arm_telemetry().joints[0];
        assert_eq!(joint.servo_status, STATUS_INPUT_VOLTAGE | STATUS_OVERLOAD);
        assert_eq!(joint.tick, Some(101));
        assert!(joint.online);

        servo.bus_mut().set_status_error(11, 0);
        run_feedback_cycle(&mut robot, &mut servo);

        let joint = robot.arm_telemetry().joints[0];
        assert_eq!(joint.servo_status, 0);
        assert_eq!(joint.tick, Some(101));
        assert!(joint.online);
    }

    #[test]
    fn input_voltage_warning_allows_gripper_wheel_mode_and_jog() {
        let mut config = config_with_arm_servo_ids([11, 12, 13, 14]);
        config.arm.gripper = Some(joint(7));
        let mut robot = Puppybot::new_with_config(&config, 0).unwrap();
        let mut bus = FakeSerialBus::new();
        for (servo_id, position) in [(11, 101), (12, 202), (13, 303), (14, 404), (7, 2100)] {
            bus.set_servo(FakeServo::new(servo_id, position));
        }
        bus.set_status_error(7, STATUS_INPUT_VOLTAGE);
        let mut servo = StServo::new(bus);

        for now_ms in (20..1100).step_by(20) {
            block_on_ready(robot.run_once(&mut servo, now_ms, || None));
        }

        let mode_attempts = servo
            .bus()
            .writes
            .iter()
            .filter(|packet| {
                packet.get(2) == Some(&7)
                    && packet.get(4) == Some(&0x03)
                    && packet.get(5) == Some(&33)
            })
            .count();
        assert_eq!(mode_attempts, 1);

        let mut event = Some(ProtocolEvent::Arm(ArmCommand::Spin {
            joint: GRIPPER_INDEX,
            direction: 1,
        }));
        block_on_ready(robot.run_once(&mut servo, 1100, || event.take()));

        let telemetry = robot.arm_telemetry().joints[GRIPPER_INDEX];
        assert_eq!(telemetry.servo_status, STATUS_INPUT_VOLTAGE);
        assert_eq!(telemetry.speed, 50);
        assert_eq!(telemetry.fault, None);
        assert!(robot.arm.wheel_mode_ready(GRIPPER_INDEX, 7));
        assert_eq!(
            servo
                .bus()
                .servo(7)
                .expect("configured gripper servo")
                .wheel_speed,
            50
        );
    }

    #[test]
    fn run_once_drives_configured_gripper_servo_in_wheel_mode() {
        let mut config = config_with_arm_servo_ids([11, 12, 13, 14]);
        config.arm.gripper = Some(joint(7));
        let mut robot = Puppybot::new_with_config(&config, 0).unwrap();
        let mut bus = FakeSerialBus::new();
        for (servo_id, position) in [(11, 101), (12, 202), (13, 303), (14, 404), (7, 2100)] {
            bus.set_servo(FakeServo::new(servo_id, position));
        }
        let mut servo = StServo::new(bus);
        for tick in 0..ACTUATOR_COUNT {
            block_on_ready(robot.run_once(&mut servo, (tick as u64 + 1) * 20, || None));
        }
        let mut event = Some(ProtocolEvent::Arm(ArmCommand::Spin {
            joint: GRIPPER_INDEX,
            direction: 1,
        }));

        block_on_ready(robot.run_once(&mut servo, 140, || event.take()));

        assert_eq!(robot.arm_telemetry().joints[GRIPPER_INDEX].speed, 50);
        assert!(robot.arm.wheel_mode_ready(GRIPPER_INDEX, 7));
        let gripper = servo.bus().servo(7).expect("configured gripper servo");
        assert_eq!(gripper.mode, Mode::Wheel);
        assert_eq!(gripper.wheel_speed, 50);
        assert_eq!(robot.arm_telemetry().joints[GRIPPER_INDEX].tick, Some(2100));
        assert!(servo.bus().writes.iter().any(|packet| {
            packet.get(2) == Some(&7)
                && packet.get(4) == Some(&0x03)
                && packet.get(5..13) == Some(&[41, 0, 0, 0, 0, 0, 50, 0])
        }));
    }
}
