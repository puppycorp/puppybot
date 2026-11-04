extern crate alloc;

use alloc::vec;
use alloc::vec::Vec;

use crate::{
    drive::DriveCommand,
    puppyarm::{
        kinematics,
        servo_safety::SafetyFault,
        types::{ArmCommand, TcpFrame},
    },
};

pub const PUPPY_PROTOCOL_VERSION: u16 = 1;
pub const CMD_PING: u8 = 1;
pub const CMD_DRIVE_MOTOR: u8 = 2;
pub const CMD_STOP_MOTOR: u8 = 3;
pub const CMD_STOP_ALL_MOTORS: u8 = 4;
pub const CMD_SMARTBUS_SCAN: u8 = 7;
pub const CMD_SMARTBUS_SET_ID: u8 = 8;
pub const CMD_SET_MOTOR_POLL: u8 = 9;
pub const CMD_SET_BOT_ID: u8 = 10;
pub const CMD_ARM_MOVE: u8 = 11;
pub const CMD_ARM_SET_SPEED: u8 = 12;
pub const CMD_ARM_JOG: u8 = 13;
pub const CMD_ARM_STOP_JOINT: u8 = 14;
pub const CMD_ARM_STOP_ALL: u8 = 15;
pub const CMD_ARM_GOTO_TICKS: u8 = 16;
pub const CMD_ARM_GOTO_ANGLES: u8 = 17;
pub const CMD_ARM_GOTO_COORDS: u8 = 18;
pub const CMD_ARM_HOLD: u8 = 19;
pub const CMD_ARM_SET_JOINT_TICK: u8 = 20;
pub const CMD_ARM_SET_TICK_LIMITS: u8 = 21;
pub const CMD_ARM_SET_TICK_LIMITS_ENABLED: u8 = 22;
pub const CMD_ARM_MOVE_RELATIVE: u8 = 23;
pub const CMD_ARM_CLEAR_FAULTS: u8 = 24;
pub const CMD_CONFIG_GET: u8 = 25;
pub const CMD_CONFIG_SET: u8 = 26;
pub const CMD_DRIVE_STEER: u8 = 27;
pub const CMD_STOP_DRIVE: u8 = 28;
pub const CMD_ARM_JOINT: u8 = 29;
pub const CMD_ARM_POSE: u8 = 30;
pub const CMD_ARM_STOP: u8 = 31;
pub const CMD_SERVO_SET: u8 = 32;
pub const CMD_SUBSCRIBE: u8 = 33;
pub const CMD_ARM_START_TCP_JOG: u8 = 34;
pub const CMD_ARM_STOP_TCP_JOG: u8 = 35;

pub const MSG_TO_SRV_PONG: u8 = 1;
#[allow(dead_code)]
pub const MSG_TO_SRV_ARM_STATE: u8 = 7;
pub const MSG_TO_SRV_CONFIG_STATE: u8 = 8;
pub const CONFIG_VERSION: u8 = 1;
pub const SUBSCRIPTION_TOPIC_ARM_STATE: u8 = 1;

const DEFAULT_SERVO_SPEED: u16 = 2400;
const MOTOR_TYPE_DC: u8 = 0;
const ARM_STATE_TARGET_EXTENSION: u8 = 1;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct RobotConfig {
    pub steering_servo_id: u8,
    pub arm_servo_ids: [u8; 4],
}

impl RobotConfig {
    pub fn decode(payload: &[u8]) -> Option<Self> {
        if payload.len() < 6 || payload[0] != CONFIG_VERSION {
            return None;
        }
        if payload[2..6].contains(&0) {
            return None;
        }

        Some(Self {
            steering_servo_id: payload[1],
            arm_servo_ids: [payload[2], payload[3], payload[4], payload[5]],
        })
    }
}

impl Default for RobotConfig {
    fn default() -> Self {
        Self {
            steering_servo_id: 1,
            arm_servo_ids: [1, 2, 3, 4],
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct ProtocolState {
    pub config: RobotConfig,
    pub telemetry_enabled: bool,
}

impl Default for ProtocolState {
    fn default() -> Self {
        Self {
            config: RobotConfig::default(),
            telemetry_enabled: false,
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum ProtocolEvent {
    Arm(ArmCommand),
    Drive(DriveCommand),
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ProtocolOutput {
    pub response: Option<Vec<u8>>,
    pub events: Vec<ProtocolEvent>,
}

#[derive(Clone, Copy, Debug, PartialEq)]
#[allow(dead_code)]
pub struct ProtocolJointTelemetry<'a> {
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
    pub target_angle_deg: Option<f32>,
    pub fault: Option<&'a [u8]>,
}

fn servo_speed_from_duration(duration_ms: u16) -> u16 {
    if duration_ms == 0 {
        return DEFAULT_SERVO_SPEED;
    }

    ((1_000_000u32 / duration_ms as u32).clamp(1, DEFAULT_SERVO_SPEED as u32)) as u16
}

fn arm_telemetry_requested(payload: &[u8], config: &RobotConfig) -> bool {
    let Some(count) = payload.first().copied() else {
        return false;
    };
    let count = (count as usize).min(payload.len().saturating_sub(1));
    payload[1..1 + count]
        .iter()
        .any(|servo_id| config.arm_servo_ids.contains(servo_id))
}

fn read_u16_le(bytes: &[u8]) -> u16 {
    u16::from_le_bytes([bytes[0], bytes[1]])
}

fn read_speed_i16(bytes: &[u8]) -> i16 {
    read_u16_le(bytes).min(i16::MAX as u16) as i16
}

fn read_i32_le(bytes: &[u8]) -> i32 {
    i32::from_le_bytes([bytes[0], bytes[1], bytes[2], bytes[3]])
}

fn read_f32_le(bytes: &[u8]) -> f32 {
    f32::from_bits(u32::from_le_bytes([bytes[0], bytes[1], bytes[2], bytes[3]]))
}

fn read_tcp_frame(value: u8) -> Option<TcpFrame> {
    match value {
        0 => Some(TcpFrame::Base),
        1 => Some(TcpFrame::Tool),
        2 => Some(TcpFrame::YawFlat),
        _ => None,
    }
}

fn deg_to_rad(degrees: f32) -> f64 {
    degrees as f64 * core::f64::consts::PI / 180.0
}

pub fn pong_frame() -> Vec<u8> {
    vec![
        (PUPPY_PROTOCOL_VERSION & 0xff) as u8,
        (PUPPY_PROTOCOL_VERSION >> 8) as u8,
        MSG_TO_SRV_PONG,
    ]
}

pub fn config_state_frame(config: &RobotConfig) -> Vec<u8> {
    let mut frame = Vec::with_capacity(9);
    frame.push((PUPPY_PROTOCOL_VERSION & 0xff) as u8);
    frame.push((PUPPY_PROTOCOL_VERSION >> 8) as u8);
    frame.push(MSG_TO_SRV_CONFIG_STATE);
    frame.push(CONFIG_VERSION);
    frame.push(config.steering_servo_id);
    frame.extend_from_slice(&config.arm_servo_ids);
    frame
}

pub fn handle_binary_command(frame: &[u8], state: &mut ProtocolState) -> ProtocolOutput {
    if frame.len() < 4 {
        return ProtocolOutput::default();
    }

    let cmd = frame[1];
    let declared_len = u16::from_le_bytes([frame[2], frame[3]]) as usize;
    let body = &frame[4..];
    if declared_len > body.len() {
        return ProtocolOutput::default();
    }

    let body = &body[..declared_len];
    let mut output = ProtocolOutput::default();

    match cmd {
        CMD_PING => output.response = Some(pong_frame()),
        CMD_DRIVE_MOTOR => {
            if body.len() >= 3 && body[1] == MOTOR_TYPE_DC {
                output
                    .events
                    .push(ProtocolEvent::Drive(DriveCommand::SetMotorSpeed {
                        motor_id: body[0],
                        speed: body[2] as i8,
                    }));
            }
        }
        CMD_STOP_MOTOR => {
            if let Some(motor_id) = body.first() {
                output
                    .events
                    .push(ProtocolEvent::Drive(DriveCommand::StopMotor {
                        motor_id: *motor_id,
                    }));
            }
        }
        CMD_SET_MOTOR_POLL => {
            state.telemetry_enabled = arm_telemetry_requested(body, &state.config);
        }
        CMD_CONFIG_GET => output.response = Some(config_state_frame(&state.config)),
        CMD_CONFIG_SET => {
            if let Some(config) = RobotConfig::decode(body) {
                state.config = config;
                output
                    .events
                    .push(ProtocolEvent::Arm(ArmCommand::SetServoIds(
                        config.arm_servo_ids,
                    )));
                output
                    .events
                    .push(ProtocolEvent::Drive(DriveCommand::SetSteeringServoId(
                        config.steering_servo_id,
                    )));
                output.response = Some(config_state_frame(&state.config));
            }
        }
        CMD_SUBSCRIBE => {
            if body.len() >= 2 && body[0] == SUBSCRIPTION_TOPIC_ARM_STATE {
                state.telemetry_enabled = body[1] != 0;
            }
        }
        CMD_ARM_SET_SPEED => {
            if body.len() >= 2 {
                output.events.push(ProtocolEvent::Arm(ArmCommand::SetSpeed(
                    read_u16_le(body) as i16
                )));
            }
        }
        CMD_ARM_JOG => {
            if body.len() >= 4 {
                let speed = u16::from_le_bytes([body[2], body[3]]);
                output
                    .events
                    .push(ProtocolEvent::Arm(ArmCommand::SetSpeed(speed as i16)));
                output.events.push(ProtocolEvent::Arm(ArmCommand::Spin {
                    joint: body[0] as usize,
                    direction: body[1] as i8,
                }));
            }
        }
        CMD_ARM_STOP_JOINT => {
            if let Some(joint) = body.first() {
                output.events.push(ProtocolEvent::Arm(ArmCommand::Stop {
                    joint: *joint as usize,
                }));
            }
        }
        CMD_ARM_STOP_ALL | CMD_ARM_STOP => {
            output.events.push(ProtocolEvent::Arm(ArmCommand::StopAll));
        }
        CMD_STOP_ALL_MOTORS => output.events.push(ProtocolEvent::Drive(DriveCommand::Stop)),
        CMD_ARM_GOTO_TICKS => {
            if body.len() >= 18 {
                output.events.push(ProtocolEvent::Arm(ArmCommand::SetSpeed(
                    u16::from_le_bytes([body[0], body[1]]) as i16,
                )));
                output
                    .events
                    .push(ProtocolEvent::Arm(ArmCommand::GotoTicks([
                        read_i32_le(&body[2..6]),
                        read_i32_le(&body[6..10]),
                        read_i32_le(&body[10..14]),
                        read_i32_le(&body[14..18]),
                    ])));
            }
        }
        CMD_ARM_GOTO_ANGLES => {
            if body.len() >= 18 {
                output.events.push(ProtocolEvent::Arm(ArmCommand::SetSpeed(
                    u16::from_le_bytes([body[0], body[1]]) as i16,
                )));
                output
                    .events
                    .push(ProtocolEvent::Arm(ArmCommand::GotoAngles([
                        deg_to_rad(read_f32_le(&body[2..6])),
                        deg_to_rad(read_f32_le(&body[6..10])),
                        deg_to_rad(read_f32_le(&body[10..14])),
                        deg_to_rad(read_f32_le(&body[14..18])),
                    ])));
            }
        }
        CMD_ARM_GOTO_COORDS => {
            if body.len() >= 18 {
                output.events.push(ProtocolEvent::Arm(ArmCommand::SetSpeed(
                    u16::from_le_bytes([body[0], body[1]]) as i16,
                )));
                output
                    .events
                    .push(ProtocolEvent::Arm(ArmCommand::GotoCoords {
                        x: read_f32_le(&body[2..6]) as f64,
                        y: read_f32_le(&body[6..10]) as f64,
                        z: kinematics::table_to_shoulder_z(read_f32_le(&body[10..14]) as f64),
                        tool_phi_rad: deg_to_rad(read_f32_le(&body[14..18])),
                    }));
            }
        }
        CMD_ARM_MOVE_RELATIVE => {
            if body.len() >= 15 {
                if let Some(frame) = read_tcp_frame(body[2]) {
                    let dx_mm = read_f32_le(&body[3..7]) as f64;
                    let dy_mm = read_f32_le(&body[7..11]) as f64;
                    let dz_mm = read_f32_le(&body[11..15]) as f64;
                    if dx_mm.is_finite() && dy_mm.is_finite() && dz_mm.is_finite() {
                        output.events.push(ProtocolEvent::Arm(ArmCommand::SetSpeed(
                            read_speed_i16(body),
                        )));
                        output.events.push(ProtocolEvent::Arm(ArmCommand::MoveTcp {
                            frame,
                            dx_mm,
                            dy_mm,
                            dz_mm,
                        }));
                    }
                }
            }
        }
        CMD_ARM_START_TCP_JOG => {
            if body.len() >= 17 {
                if let Some(frame) = read_tcp_frame(body[0]) {
                    let direction = [
                        read_f32_le(&body[1..5]) as f64,
                        read_f32_le(&body[5..9]) as f64,
                        read_f32_le(&body[9..13]) as f64,
                    ];
                    let speed_mm_s = read_f32_le(&body[13..17]) as f64;
                    if direction.iter().all(|component| component.is_finite())
                        && speed_mm_s.is_finite()
                        && speed_mm_s > 0.0
                    {
                        output
                            .events
                            .push(ProtocolEvent::Arm(ArmCommand::StartTcpJogAtSpeed {
                                frame,
                                direction,
                                speed_mm_s,
                            }));
                    }
                }
            }
        }
        CMD_ARM_STOP_TCP_JOG => {
            output
                .events
                .push(ProtocolEvent::Arm(ArmCommand::StopTcpJog));
        }
        CMD_ARM_HOLD => {
            if body.len() >= 2 {
                output.events.push(ProtocolEvent::Arm(ArmCommand::SetSpeed(
                    read_u16_le(body) as i16
                )));
                output.events.push(ProtocolEvent::Arm(ArmCommand::Hold));
            }
        }
        CMD_ARM_SET_JOINT_TICK => {
            if body.len() >= 7 {
                output.events.push(ProtocolEvent::Arm(ArmCommand::SetSpeed(
                    u16::from_le_bytes([body[1], body[2]]) as i16,
                )));
                output
                    .events
                    .push(ProtocolEvent::Arm(ArmCommand::SetJointTick {
                        joint: body[0] as usize,
                        tick: read_i32_le(&body[3..7]),
                    }));
            }
        }
        CMD_ARM_SET_TICK_LIMITS => {
            if body.len() >= 9 {
                output
                    .events
                    .push(ProtocolEvent::Arm(ArmCommand::SetTickLimits {
                        joint: body[0] as usize,
                        min: read_i32_le(&body[1..5]),
                        max: read_i32_le(&body[5..9]),
                    }));
            }
        }
        CMD_ARM_SET_TICK_LIMITS_ENABLED => {
            if body.len() >= 2 {
                output
                    .events
                    .push(ProtocolEvent::Arm(ArmCommand::SetTickLimitsEnabled {
                        joint: body[0] as usize,
                        enabled: body[1] != 0,
                    }));
            }
        }
        CMD_ARM_CLEAR_FAULTS => {
            let joint = body.first().copied().and_then(|value| {
                if value == 0xff {
                    None
                } else {
                    Some(value as usize)
                }
            });
            output
                .events
                .push(ProtocolEvent::Arm(ArmCommand::ClearFaults { joint }));
        }
        CMD_ARM_JOINT => {
            if body.len() >= 5 {
                output.events.push(ProtocolEvent::Arm(ArmCommand::SetSpeed(
                    u16::from_le_bytes([body[3], body[4]]) as i16,
                )));
                output
                    .events
                    .push(ProtocolEvent::Arm(ArmCommand::SetJointAngle {
                        joint: body[0] as usize,
                        angle_rad: deg_to_rad(i16::from_le_bytes([body[1], body[2]]) as f32),
                    }));
            }
        }
        CMD_ARM_POSE => {
            if body.len() >= 18 {
                output.events.push(ProtocolEvent::Arm(ArmCommand::SetSpeed(
                    u16::from_le_bytes([body[16], body[17]]) as i16,
                )));
                output
                    .events
                    .push(ProtocolEvent::Arm(ArmCommand::GotoCoords {
                        x: read_f32_le(&body[0..4]) as f64,
                        y: read_f32_le(&body[4..8]) as f64,
                        z: kinematics::table_to_shoulder_z(read_f32_le(&body[8..12]) as f64),
                        tool_phi_rad: deg_to_rad(read_f32_le(&body[12..16])),
                    }));
            }
        }
        CMD_DRIVE_STEER => {
            if body.len() >= 2 {
                output
                    .events
                    .push(ProtocolEvent::Drive(DriveCommand::DriveSteer {
                        throttle: body[0] as i8,
                        steering: body[1] as i8,
                    }));
            }
        }
        CMD_SERVO_SET => {
            if body.len() >= 5 && body[0] != 0 {
                let duration_ms = u16::from_le_bytes([body[3], body[4]]);
                output
                    .events
                    .push(ProtocolEvent::Arm(ArmCommand::SetServoAngle {
                        servo_id: body[0],
                        angle_rad: deg_to_rad(u16::from_le_bytes([body[1], body[2]]) as f32),
                        speed: servo_speed_from_duration(duration_ms) as i16,
                    }));
            }
        }
        CMD_STOP_DRIVE => output.events.push(ProtocolEvent::Drive(DriveCommand::Stop)),
        _ => {}
    }

    output
}

pub fn command_frame(cmd: u8, body: &[u8]) -> Vec<u8> {
    let mut frame = Vec::with_capacity(body.len() + 4);
    frame.push((PUPPY_PROTOCOL_VERSION & 0xff) as u8);
    frame.push(cmd);
    frame.extend_from_slice(&(body.len() as u16).to_le_bytes());
    frame.extend_from_slice(body);
    frame
}

#[allow(dead_code)]
pub fn arm_state_frame(
    joints: &[ProtocolJointTelemetry<'_>],
    coords_mm: Option<(f32, f32, f32)>,
    target_coords_mm: Option<(f32, f32, f32)>,
) -> Vec<u8> {
    let mut frame = Vec::with_capacity(256);
    frame.push((PUPPY_PROTOCOL_VERSION & 0xff) as u8);
    frame.push((PUPPY_PROTOCOL_VERSION >> 8) as u8);
    frame.push(MSG_TO_SRV_ARM_STATE);
    frame.push(joints.len() as u8);

    for joint in joints {
        let fault = joint.fault.unwrap_or(b"");
        let mut flags = 0u8;
        if joint.online {
            flags |= 0x01;
        }
        if joint.has_feedback {
            flags |= 0x02;
        }
        if joint.limit_reached {
            flags |= 0x04;
        }
        if joint.target_tick.is_some() {
            flags |= 0x08;
        }
        if !fault.is_empty() {
            flags |= 0x10;
        }

        frame.push(joint.servo_id);
        frame.push(flags);
        frame.extend_from_slice(&joint.tick.unwrap_or(0).to_le_bytes());
        frame.extend_from_slice(&joint.target_tick.unwrap_or(0).to_le_bytes());
        frame.extend_from_slice(&joint.speed.to_le_bytes());
        frame.extend_from_slice(&joint.limit_min.to_le_bytes());
        frame.extend_from_slice(&joint.limit_max.to_le_bytes());
        frame.extend_from_slice(&joint.angle_deg.unwrap_or(0.0).to_le_bytes());
        frame.push(fault.len() as u8);
        frame.extend_from_slice(fault);
    }

    match coords_mm {
        Some((x, y, z)) => {
            frame.push(0x01);
            frame.extend_from_slice(&x.to_le_bytes());
            frame.extend_from_slice(&y.to_le_bytes());
            frame.extend_from_slice(&z.to_le_bytes());
        }
        None => {
            frame.push(0x00);
            frame.extend_from_slice(&0.0f32.to_le_bytes());
            frame.extend_from_slice(&0.0f32.to_le_bytes());
            frame.extend_from_slice(&0.0f32.to_le_bytes());
        }
    }

    frame.push(ARM_STATE_TARGET_EXTENSION);
    for joint in joints {
        match joint.target_angle_deg {
            Some(target_angle_deg) => {
                frame.push(0x01);
                frame.extend_from_slice(&target_angle_deg.to_le_bytes());
            }
            None => {
                frame.push(0x00);
                frame.extend_from_slice(&0.0f32.to_le_bytes());
            }
        }
    }
    match target_coords_mm {
        Some((x, y, z)) => {
            frame.push(0x01);
            frame.extend_from_slice(&x.to_le_bytes());
            frame.extend_from_slice(&y.to_le_bytes());
            frame.extend_from_slice(&z.to_le_bytes());
        }
        None => {
            frame.push(0x00);
            frame.extend_from_slice(&0.0f32.to_le_bytes());
            frame.extend_from_slice(&0.0f32.to_le_bytes());
            frame.extend_from_slice(&0.0f32.to_le_bytes());
        }
    }

    frame
}

#[allow(dead_code)]
pub fn fault_name(fault: SafetyFault) -> &'static [u8] {
    match fault {
        SafetyFault::OverTemperature => b"over_temp",
        SafetyFault::FeedbackUnavailable => b"no_feedback",
        SafetyFault::FeedbackStale => b"stale_feedback",
        SafetyFault::Stall => b"stall",
        SafetyFault::DeadmanFeedbackStale => b"deadman_feedback",
        SafetyFault::DeadmanCommandStale => b"deadman_command",
    }
}

pub fn command_name(command: u8) -> &'static str {
    match command {
        CMD_PING => "PING",
        CMD_DRIVE_MOTOR => "DRIVE_MOTOR",
        CMD_STOP_MOTOR => "STOP_MOTOR",
        CMD_STOP_ALL_MOTORS => "STOP_ALL_MOTORS",
        CMD_SMARTBUS_SCAN => "SMARTBUS_SCAN",
        CMD_SMARTBUS_SET_ID => "SMARTBUS_SET_ID",
        CMD_SET_MOTOR_POLL => "SET_MOTOR_POLL",
        CMD_SET_BOT_ID => "SET_BOT_ID",
        CMD_ARM_MOVE => "ARM_MOVE",
        CMD_ARM_SET_SPEED => "ARM_SET_SPEED",
        CMD_ARM_JOG => "ARM_JOG",
        CMD_ARM_STOP_JOINT => "ARM_STOP_JOINT",
        CMD_ARM_STOP_ALL => "ARM_STOP_ALL",
        CMD_ARM_GOTO_TICKS => "ARM_GOTO_TICKS",
        CMD_ARM_GOTO_ANGLES => "ARM_GOTO_ANGLES",
        CMD_ARM_GOTO_COORDS => "ARM_GOTO_COORDS",
        CMD_ARM_HOLD => "ARM_HOLD",
        CMD_ARM_SET_JOINT_TICK => "ARM_SET_JOINT_TICK",
        CMD_ARM_SET_TICK_LIMITS => "ARM_SET_TICK_LIMITS",
        CMD_ARM_SET_TICK_LIMITS_ENABLED => "ARM_SET_TICK_LIMITS_ENABLED",
        CMD_ARM_MOVE_RELATIVE => "ARM_MOVE_RELATIVE",
        CMD_ARM_CLEAR_FAULTS => "ARM_CLEAR_FAULTS",
        CMD_CONFIG_GET => "CONFIG_GET",
        CMD_CONFIG_SET => "CONFIG_SET",
        CMD_DRIVE_STEER => "DRIVE_STEER",
        CMD_STOP_DRIVE => "STOP_DRIVE",
        CMD_ARM_JOINT => "ARM_JOINT",
        CMD_ARM_POSE => "ARM_POSE",
        CMD_ARM_START_TCP_JOG => "ARM_START_TCP_JOG",
        CMD_ARM_STOP_TCP_JOG => "ARM_STOP_TCP_JOG",
        CMD_ARM_STOP => "ARM_STOP",
        CMD_SERVO_SET => "SERVO_SET",
        CMD_SUBSCRIBE => "SUBSCRIBE",
        _ => "UNKNOWN",
    }
}

#[allow(dead_code)]
pub fn fault_name_str(fault: SafetyFault) -> &'static str {
    match fault {
        SafetyFault::OverTemperature => "over_temp",
        SafetyFault::FeedbackUnavailable => "no_feedback",
        SafetyFault::FeedbackStale => "stale_feedback",
        SafetyFault::Stall => "stall",
        SafetyFault::DeadmanFeedbackStale => "deadman_feedback",
        SafetyFault::DeadmanCommandStale => "deadman_command",
    }
}

#[cfg(all(test, feature = "runtime"))]
mod tests {
    use super::*;
    use crate::puppyarm::servo_safety::TICK_WRAP;

    #[test]
    fn ping_returns_pong() {
        let mut state = ProtocolState::default();
        let output = handle_binary_command(&command_frame(CMD_PING, &[]), &mut state);

        assert_eq!(output.response, Some(pong_frame()));
    }

    #[test]
    fn config_get_returns_current_config() {
        let mut state = ProtocolState {
            config: RobotConfig {
                steering_servo_id: 9,
                arm_servo_ids: [1, 2, 3, 4],
            },
            telemetry_enabled: false,
        };

        let output = handle_binary_command(&command_frame(CMD_CONFIG_GET, &[]), &mut state);

        assert_eq!(output.response, Some(config_state_frame(&state.config)));
    }

    #[test]
    fn config_set_updates_servo_ids_and_emits_config_events() {
        let mut state = ProtocolState::default();

        let output = handle_binary_command(
            &command_frame(CMD_CONFIG_SET, &[1, 9, 1, 2, 3, 4]),
            &mut state,
        );

        assert_eq!(state.config.steering_servo_id, 9);
        assert_eq!(state.config.arm_servo_ids, [1, 2, 3, 4]);
        assert_eq!(
            output.events,
            vec![
                ProtocolEvent::Arm(ArmCommand::SetServoIds([1, 2, 3, 4])),
                ProtocolEvent::Drive(DriveCommand::SetSteeringServoId(9)),
            ]
        );
        assert_eq!(output.response, Some(config_state_frame(&state.config)));
    }

    #[test]
    fn config_set_accepts_zero_steering_servo_id_to_disable_steering() {
        let mut state = ProtocolState::default();

        let output = handle_binary_command(
            &command_frame(CMD_CONFIG_SET, &[1, 0, 1, 2, 3, 4]),
            &mut state,
        );

        assert_eq!(state.config.steering_servo_id, 0);
        assert_eq!(state.config.arm_servo_ids, [1, 2, 3, 4]);
        assert_eq!(
            output.events,
            vec![
                ProtocolEvent::Arm(ArmCommand::SetServoIds([1, 2, 3, 4])),
                ProtocolEvent::Drive(DriveCommand::SetSteeringServoId(0)),
            ]
        );
        assert_eq!(output.response, Some(config_state_frame(&state.config)));
    }

    #[test]
    fn subscribe_toggles_telemetry() {
        let mut state = ProtocolState::default();

        handle_binary_command(
            &command_frame(CMD_SUBSCRIBE, &[SUBSCRIPTION_TOPIC_ARM_STATE, 1]),
            &mut state,
        );
        assert!(state.telemetry_enabled);

        handle_binary_command(
            &command_frame(CMD_SUBSCRIBE, &[SUBSCRIPTION_TOPIC_ARM_STATE, 0]),
            &mut state,
        );
        assert!(!state.telemetry_enabled);
    }

    #[test]
    fn set_motor_poll_toggles_telemetry_for_arm_servos() {
        let mut state = ProtocolState::default();

        handle_binary_command(&command_frame(CMD_SET_MOTOR_POLL, &[1, 99]), &mut state);
        assert!(!state.telemetry_enabled);

        handle_binary_command(&command_frame(CMD_SET_MOTOR_POLL, &[2, 99, 2]), &mut state);
        assert!(state.telemetry_enabled);
    }

    #[test]
    fn arm_jog_maps_to_speed_then_spin_intents() {
        let mut state = ProtocolState::default();
        let output =
            handle_binary_command(&command_frame(CMD_ARM_JOG, &[2, 255, 44, 1]), &mut state);

        assert_eq!(
            output.events,
            vec![
                ProtocolEvent::Arm(ArmCommand::SetSpeed(300)),
                ProtocolEvent::Arm(ArmCommand::Spin {
                    joint: 2,
                    direction: -1
                })
            ]
        );
    }

    #[test]
    fn arm_stop_joint_maps_to_stop_intent() {
        let mut state = ProtocolState::default();
        let output = handle_binary_command(&command_frame(CMD_ARM_STOP_JOINT, &[3]), &mut state);

        assert_eq!(
            output.events,
            vec![ProtocolEvent::Arm(ArmCommand::Stop { joint: 3 })]
        );
    }

    #[test]
    fn arm_stop_maps_to_stop_all_intent() {
        let mut state = ProtocolState::default();
        let output = handle_binary_command(&command_frame(CMD_ARM_STOP, &[]), &mut state);

        assert_eq!(output.events, vec![ProtocolEvent::Arm(ArmCommand::StopAll)]);
    }

    #[test]
    fn arm_joint_maps_to_joint_angle_intent() {
        let mut state = ProtocolState::default();
        let mut body = Vec::new();
        body.push(1);
        body.extend_from_slice(&90i16.to_le_bytes());
        body.extend_from_slice(&120u16.to_le_bytes());

        let output = handle_binary_command(&command_frame(CMD_ARM_JOINT, &body), &mut state);

        assert_eq!(output.events.len(), 2);
        assert_eq!(
            output.events[0],
            ProtocolEvent::Arm(ArmCommand::SetSpeed(120))
        );
        assert!(matches!(
            output.events[1],
            ProtocolEvent::Arm(ArmCommand::SetJointAngle { joint: 1, .. })
        ));
    }

    #[test]
    fn arm_goto_coords_maps_table_z_and_tool_pitch() {
        let mut state = ProtocolState::default();
        let mut body = Vec::new();
        body.extend_from_slice(&77u16.to_le_bytes());
        body.extend_from_slice(&1.0f32.to_le_bytes());
        body.extend_from_slice(&2.0f32.to_le_bytes());
        body.extend_from_slice(&42.0f32.to_le_bytes());
        body.extend_from_slice(&90.0f32.to_le_bytes());

        let output = handle_binary_command(&command_frame(CMD_ARM_GOTO_COORDS, &body), &mut state);

        assert_eq!(
            output.events[0],
            ProtocolEvent::Arm(ArmCommand::SetSpeed(77))
        );
        match output.events[1] {
            ProtocolEvent::Arm(ArmCommand::GotoCoords {
                z, tool_phi_rad, ..
            }) => {
                assert_eq!(z, 42.0 - kinematics::Z_ORIGIN_MM);
                assert_eq!(tool_phi_rad, core::f64::consts::FRAC_PI_2);
            }
            other => panic!("unexpected event {other:?}"),
        }
    }

    #[test]
    fn arm_pose_maps_table_z_to_shoulder_z() {
        let mut state = ProtocolState::default();
        let mut body = Vec::new();
        body.extend_from_slice(&1.0f32.to_le_bytes());
        body.extend_from_slice(&2.0f32.to_le_bytes());
        body.extend_from_slice(&42.0f32.to_le_bytes());
        body.extend_from_slice(&90.0f32.to_le_bytes());
        body.extend_from_slice(&77u16.to_le_bytes());

        let output = handle_binary_command(&command_frame(CMD_ARM_POSE, &body), &mut state);

        assert_eq!(
            output.events[0],
            ProtocolEvent::Arm(ArmCommand::SetSpeed(77))
        );
        match output.events[1] {
            ProtocolEvent::Arm(ArmCommand::GotoCoords { z, .. }) => {
                assert_eq!(z, 42.0 - kinematics::Z_ORIGIN_MM);
            }
            other => panic!("unexpected event {other:?}"),
        }
    }

    #[test]
    fn arm_move_relative_maps_to_speed_then_relative_intent() {
        let mut state = ProtocolState::default();
        let mut body = Vec::new();
        body.extend_from_slice(&300u16.to_le_bytes());
        body.push(2);
        body.extend_from_slice(&10.0f32.to_le_bytes());
        body.extend_from_slice(&20.0f32.to_le_bytes());
        body.extend_from_slice(&30.0f32.to_le_bytes());

        let output =
            handle_binary_command(&command_frame(CMD_ARM_MOVE_RELATIVE, &body), &mut state);

        assert_eq!(
            output.events,
            vec![
                ProtocolEvent::Arm(ArmCommand::SetSpeed(300)),
                ProtocolEvent::Arm(ArmCommand::MoveTcp {
                    frame: TcpFrame::YawFlat,
                    dx_mm: 10.0,
                    dy_mm: 20.0,
                    dz_mm: 30.0,
                })
            ]
        );
    }

    #[test]
    fn arm_move_relative_rejects_truncated_body() {
        let mut state = ProtocolState::default();
        let output = handle_binary_command(
            &command_frame(CMD_ARM_MOVE_RELATIVE, &[44, 1, 0, 0]),
            &mut state,
        );

        assert!(output.events.is_empty());
    }

    #[test]
    fn arm_move_relative_rejects_unknown_frame() {
        let mut state = ProtocolState::default();
        let mut body = Vec::new();
        body.extend_from_slice(&300u16.to_le_bytes());
        body.push(9);
        body.extend_from_slice(&10.0f32.to_le_bytes());
        body.extend_from_slice(&20.0f32.to_le_bytes());
        body.extend_from_slice(&30.0f32.to_le_bytes());

        let output =
            handle_binary_command(&command_frame(CMD_ARM_MOVE_RELATIVE, &body), &mut state);

        assert!(output.events.is_empty());
    }

    #[test]
    fn arm_move_relative_rejects_non_finite_delta() {
        let mut state = ProtocolState::default();
        let mut body = Vec::new();
        body.extend_from_slice(&300u16.to_le_bytes());
        body.push(0);
        body.extend_from_slice(&f32::NAN.to_le_bytes());
        body.extend_from_slice(&20.0f32.to_le_bytes());
        body.extend_from_slice(&30.0f32.to_le_bytes());

        let output =
            handle_binary_command(&command_frame(CMD_ARM_MOVE_RELATIVE, &body), &mut state);

        assert!(output.events.is_empty());
    }

    #[test]
    fn arm_move_relative_clamps_speed_to_i16_max() {
        let mut state = ProtocolState::default();
        let mut body = Vec::new();
        body.extend_from_slice(&40000u16.to_le_bytes());
        body.push(0);
        body.extend_from_slice(&0.0f32.to_le_bytes());
        body.extend_from_slice(&0.0f32.to_le_bytes());
        body.extend_from_slice(&1.0f32.to_le_bytes());

        let output =
            handle_binary_command(&command_frame(CMD_ARM_MOVE_RELATIVE, &body), &mut state);

        assert_eq!(
            output.events[0],
            ProtocolEvent::Arm(ArmCommand::SetSpeed(i16::MAX))
        );
    }

    #[test]
    fn arm_start_tcp_jog_maps_to_tcp_jog_intent() {
        let mut state = ProtocolState::default();
        let mut body = Vec::new();
        body.push(2);
        body.extend_from_slice(&1.0f32.to_le_bytes());
        body.extend_from_slice(&0.5f32.to_le_bytes());
        body.extend_from_slice(&0.0f32.to_le_bytes());
        body.extend_from_slice(&20.0f32.to_le_bytes());

        let output =
            handle_binary_command(&command_frame(CMD_ARM_START_TCP_JOG, &body), &mut state);

        assert_eq!(
            output.events,
            vec![ProtocolEvent::Arm(ArmCommand::StartTcpJogAtSpeed {
                frame: TcpFrame::YawFlat,
                direction: [1.0, 0.5, 0.0],
                speed_mm_s: 20.0,
            })]
        );
    }

    #[test]
    fn arm_start_tcp_jog_rejects_invalid_body() {
        let mut state = ProtocolState::default();

        let output = handle_binary_command(
            &command_frame(CMD_ARM_START_TCP_JOG, &[0, 0, 0]),
            &mut state,
        );
        assert!(output.events.is_empty());

        let mut unknown_frame = Vec::new();
        unknown_frame.push(99);
        unknown_frame.extend_from_slice(&1.0f32.to_le_bytes());
        unknown_frame.extend_from_slice(&0.0f32.to_le_bytes());
        unknown_frame.extend_from_slice(&0.0f32.to_le_bytes());
        unknown_frame.extend_from_slice(&20.0f32.to_le_bytes());
        let output = handle_binary_command(
            &command_frame(CMD_ARM_START_TCP_JOG, &unknown_frame),
            &mut state,
        );
        assert!(output.events.is_empty());

        let mut invalid_direction = Vec::new();
        invalid_direction.push(0);
        invalid_direction.extend_from_slice(&f32::NAN.to_le_bytes());
        invalid_direction.extend_from_slice(&0.0f32.to_le_bytes());
        invalid_direction.extend_from_slice(&0.0f32.to_le_bytes());
        invalid_direction.extend_from_slice(&20.0f32.to_le_bytes());
        let output = handle_binary_command(
            &command_frame(CMD_ARM_START_TCP_JOG, &invalid_direction),
            &mut state,
        );
        assert!(output.events.is_empty());

        for speed_mm_s in [0.0_f32, -20.0, f32::NAN, f32::INFINITY] {
            let mut invalid_legacy_speed = Vec::new();
            invalid_legacy_speed.push(0);
            invalid_legacy_speed.extend_from_slice(&1.0f32.to_le_bytes());
            invalid_legacy_speed.extend_from_slice(&0.0f32.to_le_bytes());
            invalid_legacy_speed.extend_from_slice(&0.0f32.to_le_bytes());
            invalid_legacy_speed.extend_from_slice(&speed_mm_s.to_le_bytes());
            let output = handle_binary_command(
                &command_frame(CMD_ARM_START_TCP_JOG, &invalid_legacy_speed),
                &mut state,
            );
            assert!(
                output.events.is_empty(),
                "legacy TCP jog speed {speed_mm_s:?} must be rejected"
            );
        }
    }

    #[test]
    fn arm_stop_tcp_jog_maps_to_stop_tcp_jog_intent() {
        let mut state = ProtocolState::default();
        let output = handle_binary_command(&command_frame(CMD_ARM_STOP_TCP_JOG, &[]), &mut state);

        assert_eq!(
            output.events,
            vec![ProtocolEvent::Arm(ArmCommand::StopTcpJog)]
        );
    }

    #[test]
    fn servo_set_rejects_zero_servo_id() {
        let mut state = ProtocolState::default();
        let output =
            handle_binary_command(&command_frame(CMD_SERVO_SET, &[0, 90, 0, 0, 0]), &mut state);

        assert!(output.events.is_empty());
    }

    #[test]
    fn drive_steer_maps_to_drive_intent() {
        let mut state = ProtocolState::default();
        let output = handle_binary_command(&command_frame(CMD_DRIVE_STEER, &[216, 50]), &mut state);

        assert_eq!(
            output.events,
            vec![ProtocolEvent::Drive(DriveCommand::DriveSteer {
                throttle: -40,
                steering: 50,
            })]
        );
    }

    #[test]
    fn drive_motor_maps_dc_payload_to_motor_speed_intent() {
        let mut state = ProtocolState::default();
        let output = handle_binary_command(
            &command_frame(CMD_DRIVE_MOTOR, &[2, MOTOR_TYPE_DC, 206, 0, 0, 0, 0]),
            &mut state,
        );

        assert_eq!(
            output.events,
            vec![ProtocolEvent::Drive(DriveCommand::SetMotorSpeed {
                motor_id: 2,
                speed: -50,
            })]
        );
    }

    #[test]
    fn drive_motor_ignores_non_dc_payload() {
        let mut state = ProtocolState::default();
        let output =
            handle_binary_command(&command_frame(CMD_DRIVE_MOTOR, &[2, 1, 50]), &mut state);

        assert!(output.events.is_empty());
    }

    #[test]
    fn stop_motor_maps_to_stop_motor_intent() {
        let mut state = ProtocolState::default();
        let output = handle_binary_command(&command_frame(CMD_STOP_MOTOR, &[2]), &mut state);

        assert_eq!(
            output.events,
            vec![ProtocolEvent::Drive(DriveCommand::StopMotor {
                motor_id: 2,
            })]
        );
    }

    #[test]
    fn stop_drive_maps_to_drive_stop_intent() {
        let mut state = ProtocolState::default();
        let output = handle_binary_command(&command_frame(CMD_STOP_DRIVE, &[]), &mut state);

        assert_eq!(
            output.events,
            vec![ProtocolEvent::Drive(DriveCommand::Stop)]
        );
    }

    #[test]
    fn telemetry_frame_round_trips_android_shape() {
        let joints = [ProtocolJointTelemetry {
            servo_id: 2,
            online: true,
            has_feedback: true,
            limit_reached: false,
            tick: Some(TICK_WRAP + 4),
            target_tick: Some(100),
            speed: -55,
            limit_min: -500,
            limit_max: 1300,
            angle_deg: Some(12.5),
            target_angle_deg: Some(45.0),
            fault: Some(b"stall"),
        }];

        let frame = arm_state_frame(&joints, Some((1.0, 2.0, 3.0)), Some((4.0, 5.0, 6.0)));

        assert_eq!(frame[0], 1);
        assert_eq!(frame[1], 0);
        assert_eq!(frame[2], MSG_TO_SRV_ARM_STATE);
        assert_eq!(frame[3], 1);
        assert_eq!(frame[4], 2);
        assert_eq!(frame[5], 0x01 | 0x02 | 0x08 | 0x10);
        assert_eq!(
            i32::from_le_bytes([frame[6], frame[7], frame[8], frame[9]]),
            TICK_WRAP + 4
        );
        assert_eq!(
            i32::from_le_bytes([frame[10], frame[11], frame[12], frame[13]]),
            100
        );
        assert_eq!(i16::from_le_bytes([frame[14], frame[15]]), -55);
        assert_eq!(frame[28], 5);
        assert_eq!(&frame[29..34], b"stall");
        assert_eq!(frame[34], 1);
        assert_eq!(
            f32::from_le_bytes([frame[35], frame[36], frame[37], frame[38]]),
            1.0
        );
        assert_eq!(frame[47], ARM_STATE_TARGET_EXTENSION);
        assert_eq!(frame[48], 1);
        assert_eq!(
            f32::from_le_bytes([frame[49], frame[50], frame[51], frame[52]]),
            45.0
        );
        assert_eq!(frame[53], 1);
        assert_eq!(
            f32::from_le_bytes([frame[54], frame[55], frame[56], frame[57]]),
            4.0
        );
    }
}
