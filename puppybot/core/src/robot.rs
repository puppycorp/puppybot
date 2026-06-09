extern crate alloc;

use alloc::vec::Vec;

use crate::{
    drive::{DriveController, DriveOutput},
    protocol::{self, ProtocolEvent, ProtocolJointTelemetry, ProtocolOutput, ProtocolState},
    puppyarm::{
        arm::{PuppyArm, PuppyarmTelemetry},
        controller::JOINT_COUNT,
    },
    stservo::{Mode, SerialBus, StServo},
};

const ARM_WHEEL_ACC: u8 = 0;
const STEERING_SERVO_ID: u8 = 1;
const FIRST_ARM_SERVO_ID: u8 = 2;
const LAST_ARM_SERVO_ID: u8 = 5;
const STEERING_SERVO_SPEED: u16 = 2400;
const STEERING_SERVO_ACC: u8 = 0;

pub struct Puppybot {
    arm: PuppyArm,
    drive: DriveController,
    protocol: ProtocolState,
    telemetry_seq: u32,
    last_steering_sent: Option<(u8, u16)>,
}

impl Puppybot {
    pub fn new(now_ms: u64) -> Self {
        Self {
            arm: PuppyArm::new(now_ms),
            drive: DriveController::new(Default::default(), now_ms),
            protocol: ProtocolState::default(),
            telemetry_seq: 0,
            last_steering_sent: None,
        }
    }

    pub fn handle_frame(&mut self, frame: &[u8], now_ms: u64) -> ProtocolOutput {
        let output = protocol::handle_binary_command(frame, &mut self.protocol);
        for event in output.events.iter().copied() {
            self.handle_event(event, now_ms);
        }
        output
    }

    pub fn handle_event(&mut self, event: ProtocolEvent, now_ms: u64) {
        match event {
            ProtocolEvent::Arm(command) => {
                self.arm.handle_arm_cmd(command, now_ms);
            }
            ProtocolEvent::Drive(command) => {
                self.drive.handle_command(command, now_ms);
            }
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
        for servo_id in STEERING_SERVO_ID..=LAST_ARM_SERVO_ID {
            match servo.read_position(servo_id).await {
                Ok(tick) => {
                    if servo_id >= FIRST_ARM_SERVO_ID {
                        self.arm.record_feedback(
                            (servo_id - FIRST_ARM_SERVO_ID) as usize,
                            tick,
                            now_ms,
                        );
                    }
                }
                Err(err) => {
                    log::warn!("read position failed for servo {}: {:?}", servo_id, err);
                    if servo_id >= FIRST_ARM_SERVO_ID {
                        self.arm
                            .record_feedback_error((servo_id - FIRST_ARM_SERVO_ID) as usize);
                    }
                }
            }
        }
    }

    async fn apply_steering_output<B>(&mut self, servo: &mut StServo<B>)
    where
        B: SerialBus,
        B::Error: core::fmt::Debug,
    {
        let output = self.drive.output();
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
            angle_deg: joint.angle_deg,
            fault: joint.fault.map(protocol::fault_name),
        });
    protocol::arm_state_frame(&joints, telemetry.coords_mm)
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
        drive::DriveCommand,
        protocol::{CMD_CONFIG_GET, CMD_DRIVE_STEER, CMD_STOP_DRIVE, ProtocolEvent, command_frame},
        puppyarm::controller::ArmCommand,
        stservo::{
            StServo, angle_to_position,
            mock::{FakeSerialBus, FakeServo, block_on_ready},
        },
    };

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
    fn run_once_handles_robot_events_on_shared_servo_bus() {
        let mut robot = Puppybot::new(0);
        let mut bus = FakeSerialBus::new();
        for servo_id in 1..=5 {
            bus.set_servo(FakeServo::new(servo_id, 0));
        }
        let mut servo = StServo::new(bus);
        let mut events = [
            ProtocolEvent::Drive(DriveCommand::DriveSteer {
                throttle: 0,
                steering: 100,
            }),
            ProtocolEvent::Arm(ArmCommand::SetSpeed(300)),
            ProtocolEvent::Arm(ArmCommand::Spin {
                joint: 0,
                direction: 1,
            }),
        ]
        .into_iter();

        block_on_ready(robot.run_once(&mut servo, 20, || events.next()));

        assert_eq!(
            servo.bus().servo(1).unwrap().position,
            angle_to_position(135)
        );
        assert_eq!(servo.bus().servo(2).unwrap().wheel_speed, 300);
        assert_eq!(robot.arm_telemetry().joints[0].tick, Some(0));
    }
}
