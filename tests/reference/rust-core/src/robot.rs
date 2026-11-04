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
        types::{ControllerError, JOINT_COUNT},
    },
    stservo::{Mode, SerialBus, StServo},
};

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
    let joints: [ProtocolJointTelemetry<'_>; JOINT_COUNT] =
        telemetry.joints.map(|joint| ProtocolJointTelemetry {
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
        });
    protocol::arm_state_frame(&joints, telemetry.coords_mm, telemetry.target_coords_mm)
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

    async fn read_servo_feedback<B>(&mut self, servo: &mut StServo<B>, now_ms: u64)
    where
        B: SerialBus,
        B::Error: core::fmt::Debug,
    {
        for offset in 0..JOINT_COUNT {
            let joint = (self.next_feedback_joint + offset) % JOINT_COUNT;
            let Some(servo_id) = self.arm.joint_servo_id(joint) else {
                continue;
            };
            self.next_feedback_joint = (joint + 1) % JOINT_COUNT;
            match servo.read_position(servo_id).await {
                Ok(tick) => {
                    self.arm.record_feedback(joint, tick, now_ms);
                }
                Err(err) => {
                    log::warn!("read position failed for servo {}: {:?}", servo_id, err);
                    self.arm.record_feedback_error(joint);
                }
            }
            break;
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
            if !initialize_wheel_mode && !output.should_send {
                continue;
            }

            let mut wheel_mode_ready = self.arm.wheel_mode_ready(joint, output.servo_id);
            if !wheel_mode_ready {
                let force_wheel_mode = initialize_wheel_mode || output.speed == 0;
                if !self.arm.begin_wheel_mode_attempt(
                    joint,
                    output.servo_id,
                    now_ms,
                    force_wheel_mode,
                ) {
                    continue;
                }

                let result = servo.set_mode(output.servo_id, Mode::Wheel).await;
                wheel_mode_ready = result.is_ok();
                if wheel_mode_ready {
                    log::info!("mode {:?} ready for servo {}", Mode::Wheel, output.servo_id);
                } else if let Err(err) = result {
                    log::warn!(
                        "set mode {:?} failed for servo {}: {:?}",
                        Mode::Wheel,
                        output.servo_id,
                        err
                    );
                }
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

            let result = servo
                .write_wheel_speed(output.servo_id, output.speed, ARM_WHEEL_ACC)
                .await;
            let success = result.is_ok();
            if let Err(err) = result {
                log::warn!(
                    "set wheel speed failed for servo {} speed {}: {:?}",
                    output.servo_id,
                    output.speed,
                    err
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
        puppyarm::types::ArmCommand,
        stservo::{
            StServo,
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
}
