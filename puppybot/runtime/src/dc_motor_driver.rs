use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

use puppybot_core::drive::{DriveActuator, DriveOutput};

const ROBOTDREAMS_SOCKET_ENV: &str = "PUPPYBOT_ROBOTDREAMS_SOCKET";
const DEFAULT_ROBOTDREAMS_SOCKET: &str = "/tmp/robotdreams-daemon.sock";
const DEFAULT_ROBOT_ID: &str = "puppybot";
const DEFAULT_DRIVE_BUS_ID: &str = "drive_bus";
const ROBOTDREAMS_IO_TIMEOUT: Duration = Duration::from_secs(2);
const ROBOTDREAMS_RETRY_AFTER_ERROR: Duration = Duration::from_millis(500);

#[derive(Debug)]
pub(crate) enum DCMotorDriverError {
    Io(String),
    Protocol(String),
}

impl std::fmt::Display for DCMotorDriverError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Io(message) => write!(f, "DC motor driver I/O failed: {message}"),
            Self::Protocol(message) => write!(f, "DC motor driver protocol failed: {message}"),
        }
    }
}

pub(crate) enum DCMotorDriver {
    Noop,
    RobotDreams(RobotDreamsDCMotorDriver),
}

pub(crate) struct RobotDreamsDCMotorDriver {
    socket_path: PathBuf,
    robot_id: String,
    bus_id: String,
    last_sent: Option<DriveOutput>,
    last_error_at: Option<Instant>,
}

impl DCMotorDriver {
    pub(crate) fn discover() -> Self {
        let explicit_socket = std::env::var_os(ROBOTDREAMS_SOCKET_ENV)
            .map(PathBuf::from)
            .filter(|path| !path.as_os_str().is_empty());
        if let Some(socket_path) = explicit_socket {
            log::info!(
                "RobotDreams drive bridge using {} from {ROBOTDREAMS_SOCKET_ENV}",
                socket_path.display()
            );
            return Self::RobotDreams(RobotDreamsDCMotorDriver::new(socket_path));
        }

        let default_socket = PathBuf::from(DEFAULT_ROBOTDREAMS_SOCKET);
        if default_socket.exists() {
            log::info!(
                "RobotDreams drive bridge using default socket {}",
                default_socket.display()
            );
            Self::RobotDreams(RobotDreamsDCMotorDriver::new(default_socket))
        } else {
            log::info!(
                "DC motor driver using noop backend; set {ROBOTDREAMS_SOCKET_ENV} to enable RobotDreams"
            );
            Self::Noop
        }
    }
}

impl RobotDreamsDCMotorDriver {
    fn new(socket_path: PathBuf) -> Self {
        Self {
            socket_path,
            robot_id: DEFAULT_ROBOT_ID.to_string(),
            bus_id: DEFAULT_DRIVE_BUS_ID.to_string(),
            last_sent: None,
            last_error_at: None,
        }
    }

    fn should_retry_after_error(&self) -> bool {
        self.last_error_at
            .map(|last_error_at| last_error_at.elapsed() >= ROBOTDREAMS_RETRY_AFTER_ERROR)
            .unwrap_or(true)
    }

    fn send_output(&mut self, output: DriveOutput) -> Result<(), DCMotorDriverError> {
        if !should_send_output(self.last_sent, output) {
            return Ok(());
        }
        if self.last_error_at.is_some() && !self.should_retry_after_error() {
            return Ok(());
        }

        match send_drive_command(&self.socket_path, &self.robot_id, &self.bus_id, output) {
            Ok(()) => {
                self.last_sent = Some(output);
                self.last_error_at = None;
                Ok(())
            }
            Err(err) => {
                self.last_error_at = Some(Instant::now());
                Err(err)
            }
        }
    }
}

fn should_send_output(last_sent: Option<DriveOutput>, output: DriveOutput) -> bool {
    if last_sent == Some(output) {
        return false;
    }
    output.active || last_sent.is_some()
}

impl DriveActuator for DCMotorDriver {
    type Error = DCMotorDriverError;

    fn apply_drive_output(&mut self, output: DriveOutput) -> Result<(), Self::Error> {
        match self {
            Self::Noop => Ok(()),
            Self::RobotDreams(actuator) => actuator.send_output(output),
        }
    }
}

#[cfg(unix)]
fn send_drive_command(
    socket_path: &Path,
    robot_id: &str,
    bus_id: &str,
    output: DriveOutput,
) -> Result<(), DCMotorDriverError> {
    use std::io::{BufRead, BufReader, Write};
    use std::os::unix::net::UnixStream;

    let mut stream =
        UnixStream::connect(socket_path).map_err(|err| DCMotorDriverError::Io(err.to_string()))?;
    stream
        .set_read_timeout(Some(ROBOTDREAMS_IO_TIMEOUT))
        .map_err(|err| DCMotorDriverError::Io(err.to_string()))?;
    stream
        .set_write_timeout(Some(ROBOTDREAMS_IO_TIMEOUT))
        .map_err(|err| DCMotorDriverError::Io(err.to_string()))?;

    let mut raw = serde_json::to_vec(&drive_command_request(robot_id, bus_id, output))
        .map_err(|err| DCMotorDriverError::Protocol(err.to_string()))?;
    raw.push(b'\n');
    stream
        .write_all(&raw)
        .map_err(|err| DCMotorDriverError::Io(err.to_string()))?;

    let mut reader = BufReader::new(stream);
    let mut response = String::new();
    reader
        .read_line(&mut response)
        .map_err(|err| DCMotorDriverError::Io(err.to_string()))?;
    let response: serde_json::Value = serde_json::from_str(&response)
        .map_err(|err| DCMotorDriverError::Protocol(err.to_string()))?;
    if response
        .get("ok")
        .and_then(|value| value.as_bool())
        .unwrap_or(false)
    {
        Ok(())
    } else {
        let message = response
            .get("message")
            .and_then(|value| value.as_str())
            .unwrap_or("RobotDreams daemon rejected drive command");
        Err(DCMotorDriverError::Protocol(message.to_string()))
    }
}

#[cfg(not(unix))]
fn send_drive_command(
    _socket_path: &Path,
    _robot_id: &str,
    _bus_id: &str,
    _output: DriveOutput,
) -> Result<(), DCMotorDriverError> {
    Err(DCMotorDriverError::Protocol(
        "RobotDreams drive bridge requires Unix sockets".to_string(),
    ))
}

fn drive_command_request(robot_id: &str, bus_id: &str, output: DriveOutput) -> serde_json::Value {
    serde_json::json!({
        "command": "projectCommand",
        "target": format!("robot:{robot_id}"),
        "action": "setDrive",
        "payload": {
            "busId": bus_id,
            "robotId": robot_id,
            "leftMotorId": output.left_motor_id,
            "rightMotorId": output.right_motor_id,
            "leftSpeed": output.left_speed,
            "rightSpeed": output.right_speed,
            "steeringAngleDeg": output.steering_angle_deg,
            "steeringCenterDeg": 90,
        }
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn output(left_speed: i16, right_speed: i16, active: bool) -> DriveOutput {
        DriveOutput {
            left_motor_id: 1,
            right_motor_id: 2,
            steering_servo_id: 5,
            left_speed,
            right_speed,
            steering_angle_deg: 90,
            active,
        }
    }

    #[test]
    fn initial_neutral_drive_output_is_not_sent() {
        assert!(!should_send_output(None, output(0, 0, false)));
    }

    #[test]
    fn active_drive_output_is_sent() {
        assert!(should_send_output(None, output(50, 50, true)));
    }

    #[test]
    fn neutral_drive_output_is_sent_after_active_output_to_stop_robotdreams() {
        assert!(should_send_output(
            Some(output(50, 50, true)),
            output(0, 0, false)
        ));
    }

    #[test]
    fn unchanged_drive_output_is_not_sent_again() {
        let active = output(50, 50, true);
        assert!(!should_send_output(Some(active), active));
    }

    #[test]
    fn drive_command_request_targets_robotdreams_project_drive() {
        let request = drive_command_request("puppybot", "drive_bus", output(50, 50, true));

        assert_eq!(
            request.pointer("/command").and_then(|value| value.as_str()),
            Some("projectCommand")
        );
        assert_eq!(
            request.pointer("/target").and_then(|value| value.as_str()),
            Some("robot:puppybot")
        );
        assert_eq!(
            request
                .pointer("/payload/busId")
                .and_then(|value| value.as_str()),
            Some("drive_bus")
        );
        assert_eq!(
            request
                .pointer("/payload/leftMotorId")
                .and_then(|value| value.as_u64()),
            Some(1)
        );
        assert_eq!(
            request
                .pointer("/payload/rightMotorId")
                .and_then(|value| value.as_u64()),
            Some(2)
        );
        assert_eq!(
            request
                .pointer("/payload/leftSpeed")
                .and_then(|value| value.as_i64()),
            Some(50)
        );
        assert_eq!(
            request
                .pointer("/payload/steeringAngleDeg")
                .and_then(|value| value.as_u64()),
            Some(90)
        );
    }
}
