#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum DriveCommand {
    DriveSteer { throttle: i8, steering: i8 },
    SetMotorSpeed { motor_id: u8, speed: i8 },
    StopMotor { motor_id: u8 },
    Stop,
    SetSteeringServoId(u8),
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct DriveConfig {
    pub left_motor_id: u8,
    pub right_motor_id: u8,
    pub steering_servo_id: u8,
    pub steering_center_deg: u16,
    pub steering_range_deg: u16,
    pub command_timeout_ms: u64,
}

impl Default for DriveConfig {
    fn default() -> Self {
        Self {
            left_motor_id: 1,
            right_motor_id: 2,
            steering_servo_id: 1,
            steering_center_deg: 90,
            steering_range_deg: 45,
            command_timeout_ms: 500,
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct DriveOutput {
    pub left_motor_id: u8,
    pub right_motor_id: u8,
    pub steering_servo_id: u8,
    pub left_speed: i16,
    pub right_speed: i16,
    pub steering_angle_deg: u16,
    pub active: bool,
}

impl DriveOutput {
    fn neutral(config: DriveConfig) -> Self {
        Self {
            left_motor_id: config.left_motor_id,
            right_motor_id: config.right_motor_id,
            steering_servo_id: config.steering_servo_id,
            left_speed: 0,
            right_speed: 0,
            steering_angle_deg: config.steering_center_deg,
            active: false,
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct DriveController {
    config: DriveConfig,
    output: DriveOutput,
    last_command_ms: u64,
}

fn clamp_percent(value: i8) -> i16 {
    (value as i16).clamp(-100, 100)
}

impl DriveController {
    pub fn new(config: DriveConfig, now_ms: u64) -> Self {
        Self {
            config,
            output: DriveOutput::neutral(config),
            last_command_ms: now_ms,
        }
    }

    pub fn handle_command(&mut self, command: DriveCommand, now_ms: u64) {
        match command {
            DriveCommand::DriveSteer { throttle, steering } => {
                let throttle = clamp_percent(throttle);
                let steering = clamp_percent(steering);

                self.output = DriveOutput {
                    left_motor_id: self.config.left_motor_id,
                    right_motor_id: self.config.right_motor_id,
                    steering_servo_id: self.config.steering_servo_id,
                    left_speed: throttle,
                    right_speed: throttle,
                    steering_angle_deg: self.steering_angle_deg(steering),
                    active: throttle != 0 || steering != 0,
                };
                self.last_command_ms = now_ms;
            }
            DriveCommand::Stop => {
                self.stop(now_ms);
            }
            DriveCommand::SetMotorSpeed { motor_id, speed } => {
                self.set_motor_speed(motor_id, speed, now_ms);
            }
            DriveCommand::StopMotor { motor_id } => {
                self.set_motor_speed(motor_id, 0, now_ms);
            }
            DriveCommand::SetSteeringServoId(servo_id) => {
                self.config.steering_servo_id = servo_id;
                self.output.steering_servo_id = servo_id;
            }
        }
    }

    pub fn tick(&mut self, now_ms: u64) {
        if self.config.command_timeout_ms == 0 || !self.output.active {
            return;
        }

        if now_ms.saturating_sub(self.last_command_ms) >= self.config.command_timeout_ms {
            self.stop(now_ms);
        }
    }

    pub fn config(&self) -> DriveConfig {
        self.config
    }

    pub fn output(&self) -> DriveOutput {
        self.output
    }

    fn stop(&mut self, now_ms: u64) {
        self.output = DriveOutput::neutral(self.config);
        self.last_command_ms = now_ms;
    }

    fn set_motor_speed(&mut self, motor_id: u8, speed: i8, now_ms: u64) {
        let speed = clamp_percent(speed);
        if motor_id == self.config.left_motor_id {
            self.output.left_speed = speed;
        } else if motor_id == self.config.right_motor_id {
            self.output.right_speed = speed;
        } else {
            return;
        }

        self.output.active = self.output.left_speed != 0
            || self.output.right_speed != 0
            || self.output.steering_angle_deg != self.config.steering_center_deg;
        self.last_command_ms = now_ms;
    }

    fn steering_angle_deg(&self, steering: i16) -> u16 {
        let center = self.config.steering_center_deg as i16;
        let range = self.config.steering_range_deg as i16;
        (center + (steering * range / 100)).clamp(0, 180) as u16
    }
}

impl Default for DriveController {
    fn default() -> Self {
        Self::new(DriveConfig::default(), 0)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn drive_steer_sets_rear_motor_speeds_and_steering_angle() {
        let mut drive = DriveController::default();

        drive.handle_command(
            DriveCommand::DriveSteer {
                throttle: 60,
                steering: 50,
            },
            10,
        );

        assert_eq!(
            drive.output(),
            DriveOutput {
                left_motor_id: 1,
                right_motor_id: 2,
                steering_servo_id: 1,
                left_speed: 60,
                right_speed: 60,
                steering_angle_deg: 112,
                active: true,
            }
        );
    }

    #[test]
    fn stop_zeros_rear_motors_and_centers_steering() {
        let mut drive = DriveController::default();

        drive.handle_command(
            DriveCommand::DriveSteer {
                throttle: -40,
                steering: -100,
            },
            10,
        );
        drive.handle_command(DriveCommand::Stop, 20);

        assert_eq!(
            drive.output(),
            DriveOutput {
                left_motor_id: 1,
                right_motor_id: 2,
                steering_servo_id: 1,
                left_speed: 0,
                right_speed: 0,
                steering_angle_deg: 90,
                active: false,
            }
        );
    }

    #[test]
    fn set_motor_speed_updates_configured_rear_motor() {
        let mut drive = DriveController::default();

        drive.handle_command(
            DriveCommand::SetMotorSpeed {
                motor_id: 2,
                speed: -35,
            },
            10,
        );

        assert_eq!(drive.output().left_speed, 0);
        assert_eq!(drive.output().right_speed, -35);
        assert!(drive.output().active);
    }

    #[test]
    fn set_motor_speed_ignores_unknown_motor() {
        let mut drive = DriveController::default();

        drive.handle_command(
            DriveCommand::SetMotorSpeed {
                motor_id: 99,
                speed: 80,
            },
            10,
        );

        assert_eq!(drive.output(), DriveOutput::neutral(DriveConfig::default()));
    }

    #[test]
    fn stop_motor_only_stops_matching_rear_motor() {
        let mut drive = DriveController::default();

        drive.handle_command(
            DriveCommand::DriveSteer {
                throttle: 45,
                steering: 0,
            },
            10,
        );
        drive.handle_command(DriveCommand::StopMotor { motor_id: 1 }, 20);

        assert_eq!(drive.output().left_speed, 0);
        assert_eq!(drive.output().right_speed, 45);
        assert!(drive.output().active);
    }

    #[test]
    fn tick_stops_drive_after_timeout() {
        let mut drive = DriveController::default();

        drive.handle_command(
            DriveCommand::DriveSteer {
                throttle: 25,
                steering: 25,
            },
            10,
        );
        drive.tick(509);
        assert!(drive.output().active);

        drive.tick(510);
        assert!(!drive.output().active);
        assert_eq!(drive.output().left_speed, 0);
        assert_eq!(drive.output().steering_angle_deg, 90);
    }

    #[test]
    fn steering_angle_is_clamped_to_servo_range() {
        let mut drive = DriveController::new(
            DriveConfig {
                steering_center_deg: 170,
                steering_range_deg: 45,
                ..DriveConfig::default()
            },
            0,
        );

        drive.handle_command(
            DriveCommand::DriveSteer {
                throttle: 0,
                steering: 100,
            },
            10,
        );

        assert_eq!(drive.output().steering_angle_deg, 180);
    }

    #[test]
    fn config_updates_steering_servo_id() {
        let mut drive = DriveController::default();

        drive.handle_command(DriveCommand::SetSteeringServoId(9), 10);

        assert_eq!(drive.config().steering_servo_id, 9);
        assert_eq!(drive.output().steering_servo_id, 9);
    }
}
