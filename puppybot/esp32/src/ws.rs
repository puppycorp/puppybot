#![allow(dead_code)]

use embassy_net::{
    Stack,
    tcp::{Error as TcpError, TcpSocket},
};
use embassy_time::{Duration, Timer};
use sha1::{Digest, Sha1};

use crate::protocol::{self, ProtocolEvent, ProtocolState, RobotConfig};
use crate::puppyarm::{
    controller::{ArmCommand, JOINT_COUNT},
    kinematics,
    servo_safety::SafetyFault,
    task::{IntentChannel, PuppyarmTelemetry, TelemetryChannel},
};
use crate::utility::{base64_encode, eq_ignore_ascii_case, find_bytes, trim_ascii};

const HTTP_PORT: u16 = 80;
const MAX_HTTP_REQUEST: usize = 2048;
const MAX_WS_FRAME_SIZE: usize = 2048;
const WEBSOCKET_GUID: &[u8] = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11";
const PUPPY_PROTOCOL_VERSION: u16 = 1;
const CMD_PING: u8 = 1;
const CMD_DRIVE_MOTOR: u8 = 2;
const CMD_STOP_MOTOR: u8 = 3;
const CMD_STOP_ALL_MOTORS: u8 = 4;
const CMD_APPLY_CONFIG: u8 = 6;
const CMD_SMARTBUS_SCAN: u8 = 7;
const CMD_SMARTBUS_SET_ID: u8 = 8;
const CMD_SET_MOTOR_POLL: u8 = 9;
const CMD_SET_BOT_ID: u8 = 10;
const CMD_ARM_MOVE: u8 = 11;
const CMD_ARM_SET_SPEED: u8 = 12;
const CMD_ARM_JOG: u8 = 13;
const CMD_ARM_STOP_JOINT: u8 = 14;
const CMD_ARM_STOP_ALL: u8 = 15;
const CMD_ARM_GOTO_TICKS: u8 = 16;
const CMD_ARM_GOTO_ANGLES: u8 = 17;
const CMD_ARM_GOTO_COORDS: u8 = 18;
const CMD_ARM_HOLD: u8 = 19;
const CMD_ARM_SET_JOINT_TICK: u8 = 20;
const CMD_ARM_SET_TICK_LIMITS: u8 = 21;
const CMD_ARM_SET_TICK_LIMITS_ENABLED: u8 = 22;
const CMD_ARM_MOVE_RELATIVE: u8 = 23;
const CMD_ARM_CLEAR_FAULTS: u8 = 24;
const CMD_CONFIG_GET: u8 = 25;
const CMD_CONFIG_SET: u8 = 26;
const CMD_DRIVE_STEER: u8 = 27;
const CMD_STOP_DRIVE: u8 = 28;
const CMD_ARM_JOINT: u8 = 29;
const CMD_ARM_POSE: u8 = 30;
const CMD_ARM_STOP: u8 = 31;
const CMD_SERVO_SET: u8 = 32;
const CMD_SUBSCRIBE: u8 = 33;
const MSG_TO_SRV_PONG: u8 = 1;
const MSG_TO_SRV_ARM_STATE: u8 = 7;
const MSG_TO_SRV_CONFIG_STATE: u8 = 8;
const CONFIG_VERSION: u8 = 1;
const SUBSCRIPTION_TOPIC_ARM_STATE: u8 = 1;
const WS_IDLE_POLL: Duration = Duration::from_millis(20);
const DEFAULT_SERVO_SPEED: u16 = 2400;

#[embassy_executor::task]
pub async fn http_websocket_server(
    stack: Stack<'static>,
    arm_intents: &'static IntentChannel,
    arm_telemetry: &'static TelemetryChannel,
) {
    let mut rx_buffer = [0u8; 4096];
    let mut tx_buffer = [0u8; 4096];
    let mut config = RobotConfig::default();

    loop {
        let mut socket = TcpSocket::new(stack, &mut rx_buffer, &mut tx_buffer);
        socket.set_timeout(Some(Duration::from_secs(120)));
        socket.set_keep_alive(Some(Duration::from_secs(30)));
        socket.set_nagle_enabled(false);

        log::info!("HTTP/WebSocket server listening on port {HTTP_PORT}");
        match socket.accept(HTTP_PORT).await {
            Ok(()) => {
                log::info!("HTTP client connected: {:?}", socket.remote_endpoint());
                if let Err(err) =
                    handle_http_connection(&mut socket, &mut config, arm_intents, arm_telemetry)
                        .await
                {
                    log::warn!("HTTP/WebSocket connection ended: {:?}", err);
                }
            }
            Err(err) => {
                log::warn!("HTTP accept failed: {:?}", err);
                Timer::after(Duration::from_secs(1)).await;
            }
        }

        socket.close();
        let _ = socket.flush().await;
    }
}

async fn handle_http_connection(
    socket: &mut TcpSocket<'_>,
    config: &mut RobotConfig,
    arm_intents: &'static IntentChannel,
    arm_telemetry: &'static TelemetryChannel,
) -> Result<(), HttpError> {
    let mut request = [0u8; MAX_HTTP_REQUEST];
    let request_len = read_http_request(socket, &mut request).await?;
    let request = &request[..request_len];

    if is_websocket_request(request) {
        handle_websocket_upgrade(socket, request).await?;
        websocket_loop(socket, config, arm_intents, arm_telemetry).await
    } else if request.starts_with(b"GET / ") || request.starts_with(b"GET / HTTP/") {
        write_all(
            socket,
            b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nConnection: close\r\nContent-Length: 29\r\n\r\npuppybot websocket is on /ws\n",
        )
        .await?;
        Ok(())
    } else {
        write_all(
            socket,
            b"HTTP/1.1 404 Not Found\r\nConnection: close\r\nContent-Length: 10\r\n\r\nnot found\n",
        )
        .await?;
        Ok(())
    }
}

async fn read_http_request(
    socket: &mut TcpSocket<'_>,
    request: &mut [u8],
) -> Result<usize, HttpError> {
    let mut len = 0;

    loop {
        if len == request.len() {
            return Err(HttpError::RequestTooLarge);
        }

        let read = socket.read(&mut request[len..]).await?;
        if read == 0 {
            return Err(HttpError::Closed);
        }

        len += read;
        if find_bytes(&request[..len], b"\r\n\r\n").is_some() {
            return Ok(len);
        }
    }
}

async fn handle_websocket_upgrade(
    socket: &mut TcpSocket<'_>,
    request: &[u8],
) -> Result<(), HttpError> {
    let key = header_value(request, b"sec-websocket-key").ok_or(HttpError::BadRequest)?;
    let mut accept = [0u8; 28];
    websocket_accept_key(key, &mut accept)?;

    write_all(socket, b"HTTP/1.1 101 Switching Protocols\r\n").await?;
    write_all(socket, b"Upgrade: websocket\r\n").await?;
    write_all(socket, b"Connection: Upgrade\r\n").await?;
    write_all(socket, b"Sec-WebSocket-Accept: ").await?;
    write_all(socket, &accept).await?;
    write_all(socket, b"\r\n\r\n").await?;

    log::info!("WebSocket handshake completed");
    Ok(())
}

async fn websocket_loop(
    socket: &mut TcpSocket<'_>,
    config: &mut RobotConfig,
    arm_intents: &'static IntentChannel,
    arm_telemetry: &'static TelemetryChannel,
) -> Result<(), HttpError> {
    let mut payload = [0u8; MAX_WS_FRAME_SIZE];
    let mut telemetry_enabled = false;
    let mut latest_telemetry: Option<PuppyarmTelemetry> = None;
    let mut sent_telemetry_seq: Option<u32> = None;

    loop {
        while let Ok(snapshot) = arm_telemetry.try_receive() {
            latest_telemetry = Some(snapshot);
        }

        if telemetry_enabled
            && let Some(snapshot) = latest_telemetry
            && sent_telemetry_seq != Some(snapshot.seq)
        {
            send_arm_state(socket, &snapshot).await?;
            sent_telemetry_seq = Some(snapshot.seq);
        }

        if !socket.may_recv() {
            return Err(HttpError::Closed);
        }

        if !socket.can_recv() {
            Timer::after(WS_IDLE_POLL).await;
            continue;
        }

        let frame = read_ws_frame(socket, &mut payload).await?;

        match frame.opcode {
            0x1 => {
                log::info!("WS text frame len={}", frame.payload.len());
                if frame.payload == b"ping" {
                    send_ws_frame(socket, 0x1, b"pong").await?;
                }
            }
            0x2 => {
                handle_binary_ws_frame(
                    socket,
                    frame.payload,
                    config,
                    arm_intents,
                    &mut telemetry_enabled,
                )
                .await?;
            }
            0x8 => {
                log::info!("WS close frame received");
                send_ws_frame(socket, 0x8, &[]).await?;
                return Ok(());
            }
            0x9 => {
                send_ws_frame(socket, 0xA, frame.payload).await?;
            }
            0xA => {
                log::info!("WS pong frame received");
            }
            opcode => {
                log::warn!("unhandled WS opcode={opcode} len={}", frame.payload.len());
            }
        }
    }
}

async fn handle_binary_ws_frame(
    socket: &mut TcpSocket<'_>,
    payload: &[u8],
    config: &mut RobotConfig,
    arm_intents: &'static IntentChannel,
    telemetry_enabled: &mut bool,
) -> Result<(), HttpError> {
    if payload.len() < 4 {
        log::warn!("ignoring short binary WS frame len={}", payload.len());
        return Ok(());
    }

    let version = payload[0];
    let cmd = payload[1];
    let payload_len = u16::from_le_bytes([payload[2], payload[3]]) as usize;
    let actual_len = payload.len().saturating_sub(4);
    log::info!(
        "WS command {} version={} declared_len={} actual_len={}",
        protocol::command_name(cmd),
        version,
        payload_len,
        actual_len
    );

    let mut protocol_state = ProtocolState {
        config: *config,
        telemetry_enabled: *telemetry_enabled,
    };
    let output = protocol::handle_binary_command(payload, &mut protocol_state);
    *config = protocol_state.config;
    *telemetry_enabled = protocol_state.telemetry_enabled;

    for event in output.events {
        dispatch_protocol_event(arm_intents, event);
    }

    if let Some(response) = output.response {
        send_ws_frame(socket, 0x2, &response).await?;
    }

    Ok(())
}

fn dispatch_protocol_event(arm_intents: &'static IntentChannel, event: ProtocolEvent) {
    match event {
        ProtocolEvent::Arm(command) => send_arm_intent(arm_intents, command),
    }
}

fn handle_robot_command(
    cmd: u8,
    payload: &[u8],
    config: &RobotConfig,
    arm_intents: &'static IntentChannel,
    telemetry_enabled: &mut bool,
) {
    match cmd {
        CMD_SET_MOTOR_POLL => {
            *telemetry_enabled = arm_telemetry_requested(payload, config);
            log::info!(
                "arm telemetry enabled={} via motor poll",
                *telemetry_enabled
            );
        }
        CMD_SUBSCRIBE => {
            if payload.len() < 2 {
                log::warn!("invalid SUBSCRIBE payload len={}", payload.len());
                return;
            }

            let topic = payload[0];
            let enabled = payload[1] != 0;
            match topic {
                SUBSCRIPTION_TOPIC_ARM_STATE => {
                    *telemetry_enabled = enabled;
                    log::info!("arm telemetry subscription enabled={enabled}");
                }
                _ => {
                    log::warn!("unknown subscription topic={topic}");
                }
            }
        }
        CMD_DRIVE_STEER => {
            if payload.len() < 2 {
                log::warn!("invalid DRIVE_STEER payload len={}", payload.len());
                return;
            }
            let throttle = payload[0] as i8;
            let steering = payload[1] as i8;
            log::info!(
                "robot drive throttle={} steering={} steering_servo_id={}",
                throttle,
                steering,
                config.steering_servo_id
            );
            if config.steering_servo_id == 0 {
                log::warn!("ignoring DRIVE_STEER because steering servo id is not configured");
                return;
            }
            log::warn!("ignoring DRIVE_STEER because steering is not handled by puppyarm");
        }
        CMD_STOP_DRIVE => {
            log::info!("robot stop drive");
        }
        CMD_ARM_SET_SPEED => {
            if payload.len() < 2 {
                log::warn!("invalid ARM_SET_SPEED payload len={}", payload.len());
                return;
            }
            let speed = u16::from_le_bytes([payload[0], payload[1]]);
            send_arm_intent(arm_intents, ArmCommand::SetSpeed(speed as i16));
        }
        CMD_ARM_JOG => {
            if payload.len() < 4 {
                log::warn!("invalid ARM_JOG payload len={}", payload.len());
                return;
            }
            let joint = payload[0] as usize;
            let direction = payload[1] as i8;
            let speed = u16::from_le_bytes([payload[2], payload[3]]);
            send_arm_intent(arm_intents, ArmCommand::SetSpeed(speed as i16));
            send_arm_intent(arm_intents, ArmCommand::Spin { joint, direction });
        }
        CMD_ARM_STOP_JOINT => {
            if payload.is_empty() {
                log::warn!("invalid ARM_STOP_JOINT payload len={}", payload.len());
                return;
            }
            send_arm_intent(
                arm_intents,
                ArmCommand::Stop {
                    joint: payload[0] as usize,
                },
            );
        }
        CMD_ARM_STOP_ALL => {
            send_arm_intent(arm_intents, ArmCommand::StopAll);
        }
        CMD_ARM_GOTO_TICKS => {
            if payload.len() < 18 {
                log::warn!("invalid ARM_GOTO_TICKS payload len={}", payload.len());
                return;
            }
            let speed = u16::from_le_bytes([payload[0], payload[1]]);
            let ticks = [
                read_i32_le(&payload[2..6]),
                read_i32_le(&payload[6..10]),
                read_i32_le(&payload[10..14]),
                read_i32_le(&payload[14..18]),
            ];
            send_arm_intent(arm_intents, ArmCommand::SetSpeed(speed as i16));
            send_arm_intent(arm_intents, ArmCommand::GotoTicks(ticks));
        }
        CMD_ARM_GOTO_ANGLES => {
            if payload.len() < 18 {
                log::warn!("invalid ARM_GOTO_ANGLES payload len={}", payload.len());
                return;
            }
            let speed = u16::from_le_bytes([payload[0], payload[1]]);
            let angles = [
                deg_to_rad(read_f32_le(&payload[2..6])),
                deg_to_rad(read_f32_le(&payload[6..10])),
                deg_to_rad(read_f32_le(&payload[10..14])),
                deg_to_rad(read_f32_le(&payload[14..18])),
            ];
            send_arm_intent(arm_intents, ArmCommand::SetSpeed(speed as i16));
            send_arm_intent(arm_intents, ArmCommand::GotoAngles(angles));
        }
        CMD_ARM_GOTO_COORDS => {
            if payload.len() < 14 {
                log::warn!("invalid ARM_GOTO_COORDS payload len={}", payload.len());
                return;
            }
            let speed = u16::from_le_bytes([payload[0], payload[1]]);
            let x = read_f32_le(&payload[2..6]) as f64;
            let y = read_f32_le(&payload[6..10]) as f64;
            let z = read_f32_le(&payload[10..14]) as f64;
            send_arm_intent(arm_intents, ArmCommand::SetSpeed(speed as i16));
            send_arm_intent(
                arm_intents,
                ArmCommand::GotoCoords {
                    x,
                    y,
                    z: kinematics::table_to_shoulder_z(z),
                },
            );
        }
        CMD_ARM_HOLD => {
            if payload.len() < 2 {
                log::warn!("invalid ARM_HOLD payload len={}", payload.len());
                return;
            }
            let speed = u16::from_le_bytes([payload[0], payload[1]]);
            send_arm_intent(arm_intents, ArmCommand::SetSpeed(speed as i16));
            send_arm_intent(arm_intents, ArmCommand::Hold);
        }
        CMD_ARM_SET_JOINT_TICK => {
            if payload.len() < 7 {
                log::warn!("invalid ARM_SET_JOINT_TICK payload len={}", payload.len());
                return;
            }
            let joint = payload[0] as usize;
            let speed = u16::from_le_bytes([payload[1], payload[2]]);
            let tick = read_i32_le(&payload[3..7]);
            send_arm_intent(arm_intents, ArmCommand::SetSpeed(speed as i16));
            send_arm_intent(arm_intents, ArmCommand::SetJointTick { joint, tick });
        }
        CMD_ARM_SET_TICK_LIMITS => {
            if payload.len() < 9 {
                log::warn!("invalid ARM_SET_TICK_LIMITS payload len={}", payload.len());
                return;
            }
            send_arm_intent(
                arm_intents,
                ArmCommand::SetTickLimits {
                    joint: payload[0] as usize,
                    min: read_i32_le(&payload[1..5]),
                    max: read_i32_le(&payload[5..9]),
                },
            );
        }
        CMD_ARM_SET_TICK_LIMITS_ENABLED => {
            if payload.len() < 2 {
                log::warn!(
                    "invalid ARM_SET_TICK_LIMITS_ENABLED payload len={}",
                    payload.len()
                );
                return;
            }
            send_arm_intent(
                arm_intents,
                ArmCommand::SetTickLimitsEnabled {
                    joint: payload[0] as usize,
                    enabled: payload[1] != 0,
                },
            );
        }
        CMD_ARM_MOVE_RELATIVE => {
            if payload.len() < 10 {
                log::warn!("invalid ARM_MOVE_RELATIVE payload len={}", payload.len());
                return;
            }
            log::warn!("ARM_MOVE_RELATIVE is not wired to the Rust state engine yet");
        }
        CMD_ARM_CLEAR_FAULTS => {
            let joint = payload.first().copied().and_then(|value| {
                if value == 0xff {
                    None
                } else {
                    Some(value as usize)
                }
            });
            send_arm_intent(arm_intents, ArmCommand::ClearFaults { joint });
        }
        CMD_ARM_JOINT => {
            if payload.len() < 5 {
                log::warn!("invalid ARM_JOINT payload len={}", payload.len());
                return;
            }
            let joint = payload[0];
            let angle_deg = i16::from_le_bytes([payload[1], payload[2]]);
            let speed = u16::from_le_bytes([payload[3], payload[4]]);
            log::info!(
                "robot arm joint={} angle_deg={} speed={}",
                joint,
                angle_deg,
                speed
            );
            send_arm_intent(arm_intents, ArmCommand::SetSpeed(speed as i16));
            send_arm_intent(
                arm_intents,
                ArmCommand::SetJointAngle {
                    joint: joint as usize,
                    angle_rad: deg_to_rad(angle_deg as f32),
                },
            );
        }
        CMD_ARM_POSE => {
            if payload.len() < 18 {
                log::warn!("invalid ARM_POSE payload len={}", payload.len());
                return;
            }
            let x = read_f32_le(&payload[0..4]);
            let y = read_f32_le(&payload[4..8]);
            let z = read_f32_le(&payload[8..12]);
            let wrist_deg = read_f32_le(&payload[12..16]);
            let speed = u16::from_le_bytes([payload[16], payload[17]]);
            log::info!(
                "robot arm pose x={} y={} z={} wrist_deg={} speed={}",
                x,
                y,
                z,
                wrist_deg,
                speed
            );
            send_arm_intent(arm_intents, ArmCommand::SetSpeed(speed as i16));
            send_arm_intent(
                arm_intents,
                ArmCommand::GotoPose {
                    x: x as f64,
                    y: y as f64,
                    z: kinematics::table_to_shoulder_z(z as f64),
                    tool_phi_rad: deg_to_rad(wrist_deg) as f64,
                },
            );
        }
        CMD_ARM_STOP => {
            log::info!("robot arm stop");
            send_arm_intent(arm_intents, ArmCommand::StopAll);
        }
        CMD_SERVO_SET => {
            if payload.len() < 5 {
                log::warn!("invalid SERVO_SET payload len={}", payload.len());
                return;
            }
            let servo_id = payload[0];
            let angle_deg = u16::from_le_bytes([payload[1], payload[2]]);
            let duration_ms = u16::from_le_bytes([payload[3], payload[4]]);
            if servo_id == 0 {
                log::warn!("ignoring SERVO_SET for unconfigured servo id 0");
                return;
            }
            log::info!(
                "servo set id={} angle_deg={} duration_ms={}",
                servo_id,
                angle_deg,
                duration_ms
            );
            send_arm_intent(
                arm_intents,
                ArmCommand::SetServoAngle {
                    servo_id,
                    angle_rad: deg_to_rad(angle_deg as f32),
                    speed: servo_speed_from_duration(duration_ms) as i16,
                },
            );
        }
        _ => {}
    }
}

fn clamp_angle(angle_deg: i16) -> u16 {
    angle_deg.clamp(0, 240) as u16
}

fn servo_speed_from_duration(duration_ms: u16) -> u16 {
    if duration_ms == 0 {
        return DEFAULT_SERVO_SPEED;
    }

    ((1_000_000u32 / duration_ms as u32).clamp(1, DEFAULT_SERVO_SPEED as u32)) as u16
}

fn arm_telemetry_requested(payload: &[u8], config: &RobotConfig) -> bool {
    if payload.is_empty() {
        log::warn!("invalid SET_MOTOR_POLL payload len=0");
        return false;
    }

    let count = (payload[0] as usize).min(payload.len().saturating_sub(1));
    payload[1..1 + count]
        .iter()
        .any(|servo_id| config.arm_servo_ids.contains(servo_id))
}

fn send_arm_intent(arm_intents: &'static IntentChannel, command: ArmCommand) {
    if arm_intents.try_send(command).is_err() {
        log::warn!("arm intent queue full; dropping intent");
    }
}

fn read_i32_le(bytes: &[u8]) -> i32 {
    i32::from_le_bytes([bytes[0], bytes[1], bytes[2], bytes[3]])
}

fn read_f32_le(bytes: &[u8]) -> f32 {
    f32::from_bits(u32::from_le_bytes([bytes[0], bytes[1], bytes[2], bytes[3]]))
}

fn deg_to_rad(degrees: f32) -> f64 {
    degrees as f64 * core::f64::consts::PI / 180.0
}

async fn send_config_state(
    socket: &mut TcpSocket<'_>,
    config: &RobotConfig,
) -> Result<(), HttpError> {
    let mut frame = [0u8; 9];
    frame[0] = (PUPPY_PROTOCOL_VERSION & 0xff) as u8;
    frame[1] = (PUPPY_PROTOCOL_VERSION >> 8) as u8;
    frame[2] = MSG_TO_SRV_CONFIG_STATE;
    frame[3] = CONFIG_VERSION;
    frame[4] = config.steering_servo_id;
    frame[5..9].copy_from_slice(&config.arm_servo_ids);
    send_ws_frame(socket, 0x2, &frame).await
}

async fn send_arm_state(
    socket: &mut TcpSocket<'_>,
    telemetry: &PuppyarmTelemetry,
) -> Result<(), HttpError> {
    let mut frame = [0u8; 256];
    let mut offset = 0;

    push_u8(
        &mut frame,
        &mut offset,
        (PUPPY_PROTOCOL_VERSION & 0xff) as u8,
    );
    push_u8(&mut frame, &mut offset, (PUPPY_PROTOCOL_VERSION >> 8) as u8);
    push_u8(&mut frame, &mut offset, MSG_TO_SRV_ARM_STATE);
    push_u8(&mut frame, &mut offset, JOINT_COUNT as u8);

    for joint in telemetry.joints {
        let fault = joint.fault.map(fault_name).unwrap_or(b"");
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

        push_u8(&mut frame, &mut offset, joint.servo_id);
        push_u8(&mut frame, &mut offset, flags);
        push_i32(&mut frame, &mut offset, joint.tick.unwrap_or(0));
        push_i32(&mut frame, &mut offset, joint.target_tick.unwrap_or(0));
        push_i16(&mut frame, &mut offset, joint.speed);
        push_i32(&mut frame, &mut offset, joint.limit_min);
        push_i32(&mut frame, &mut offset, joint.limit_max);
        push_f32(&mut frame, &mut offset, joint.angle_deg.unwrap_or(0.0));
        push_u8(&mut frame, &mut offset, fault.len() as u8);
        push_bytes(&mut frame, &mut offset, fault);
    }

    match telemetry.coords_mm {
        Some((x, y, z)) => {
            push_u8(&mut frame, &mut offset, 0x01);
            push_f32(&mut frame, &mut offset, x);
            push_f32(&mut frame, &mut offset, y);
            push_f32(&mut frame, &mut offset, z);
        }
        None => {
            push_u8(&mut frame, &mut offset, 0x00);
            push_f32(&mut frame, &mut offset, 0.0);
            push_f32(&mut frame, &mut offset, 0.0);
            push_f32(&mut frame, &mut offset, 0.0);
        }
    }

    send_ws_frame(socket, 0x2, &frame[..offset]).await
}

fn fault_name(fault: SafetyFault) -> &'static [u8] {
    match fault {
        SafetyFault::OverTemperature => b"over_temp",
        SafetyFault::FeedbackUnavailable => b"no_feedback",
        SafetyFault::FeedbackStale => b"stale_feedback",
        SafetyFault::Stall => b"stall",
        SafetyFault::DeadmanFeedbackStale => b"deadman_feedback",
        SafetyFault::DeadmanCommandStale => b"deadman_command",
    }
}

fn push_u8(frame: &mut [u8], offset: &mut usize, value: u8) {
    frame[*offset] = value;
    *offset += 1;
}

fn push_i16(frame: &mut [u8], offset: &mut usize, value: i16) {
    push_bytes(frame, offset, &value.to_le_bytes());
}

fn push_i32(frame: &mut [u8], offset: &mut usize, value: i32) {
    push_bytes(frame, offset, &value.to_le_bytes());
}

fn push_f32(frame: &mut [u8], offset: &mut usize, value: f32) {
    push_bytes(frame, offset, &value.to_le_bytes());
}

fn push_bytes(frame: &mut [u8], offset: &mut usize, value: &[u8]) {
    let end = *offset + value.len();
    frame[*offset..end].copy_from_slice(value);
    *offset = end;
}

struct WsFrame<'a> {
    opcode: u8,
    payload: &'a [u8],
}

async fn read_ws_frame<'a>(
    socket: &mut TcpSocket<'_>,
    payload: &'a mut [u8],
) -> Result<WsFrame<'a>, HttpError> {
    let mut header = [0u8; 2];
    read_exact(socket, &mut header).await?;

    let opcode = header[0] & 0x0f;
    let masked = (header[1] & 0x80) != 0;
    let mut len = (header[1] & 0x7f) as usize;

    if len == 126 {
        let mut extended = [0u8; 2];
        read_exact(socket, &mut extended).await?;
        len = u16::from_be_bytes(extended) as usize;
    } else if len == 127 {
        let mut extended = [0u8; 8];
        read_exact(socket, &mut extended).await?;
        let raw_len = u64::from_be_bytes(extended);
        if raw_len > usize::MAX as u64 {
            return Err(HttpError::FrameTooLarge);
        }
        len = raw_len as usize;
    }

    if len > payload.len() {
        return Err(HttpError::FrameTooLarge);
    }

    let mut mask = [0u8; 4];
    if masked {
        read_exact(socket, &mut mask).await?;
    }

    read_exact(socket, &mut payload[..len]).await?;

    if masked {
        for (idx, byte) in payload[..len].iter_mut().enumerate() {
            *byte ^= mask[idx % 4];
        }
    } else {
        log::warn!("received unmasked client WS frame");
    }

    Ok(WsFrame {
        opcode,
        payload: &payload[..len],
    })
}

async fn send_ws_frame(
    socket: &mut TcpSocket<'_>,
    opcode: u8,
    payload: &[u8],
) -> Result<(), HttpError> {
    let mut header = [0u8; 10];
    header[0] = 0x80 | (opcode & 0x0f);

    let header_len = if payload.len() < 126 {
        header[1] = payload.len() as u8;
        2
    } else if payload.len() <= u16::MAX as usize {
        header[1] = 126;
        header[2..4].copy_from_slice(&(payload.len() as u16).to_be_bytes());
        4
    } else {
        header[1] = 127;
        header[2..10].copy_from_slice(&(payload.len() as u64).to_be_bytes());
        10
    };

    write_all(socket, &header[..header_len]).await?;
    write_all(socket, payload).await?;
    Ok(())
}

async fn read_exact(socket: &mut TcpSocket<'_>, mut buf: &mut [u8]) -> Result<(), HttpError> {
    while !buf.is_empty() {
        let read = socket.read(buf).await?;
        if read == 0 {
            return Err(HttpError::Closed);
        }
        let (_, rest) = buf.split_at_mut(read);
        buf = rest;
    }
    Ok(())
}

async fn write_all(socket: &mut TcpSocket<'_>, mut buf: &[u8]) -> Result<(), TcpError> {
    while !buf.is_empty() {
        let written = socket.write(buf).await?;
        buf = &buf[written..];
    }
    socket.flush().await
}

fn is_websocket_request(request: &[u8]) -> bool {
    request.starts_with(b"GET /ws ")
        && header_value(request, b"upgrade")
            .map(|value| eq_ignore_ascii_case(value, b"websocket"))
            .unwrap_or(false)
        && header_value(request, b"sec-websocket-key").is_some()
}

fn header_value<'a>(request: &'a [u8], name: &[u8]) -> Option<&'a [u8]> {
    let header_end = find_bytes(request, b"\r\n\r\n")?;

    for line in request[..header_end].split(|byte| *byte == b'\n') {
        let line = trim_ascii(line.strip_suffix(b"\r").unwrap_or(line));
        if let Some(colon) = line.iter().position(|byte| *byte == b':')
            && eq_ignore_ascii_case(trim_ascii(&line[..colon]), name)
        {
            return Some(trim_ascii(&line[colon + 1..]));
        }
    }

    None
}

fn websocket_accept_key(key: &[u8], out: &mut [u8; 28]) -> Result<(), HttpError> {
    let mut hasher = Sha1::new();
    hasher.update(key);
    hasher.update(WEBSOCKET_GUID);
    let digest = hasher.finalize();
    base64_encode(&digest, out).map_err(|()| HttpError::FrameTooLarge)?;
    Ok(())
}

fn command_name(command: u8) -> &'static str {
    match command {
        CMD_PING => "PING",
        CMD_DRIVE_MOTOR => "DRIVE_MOTOR",
        CMD_STOP_MOTOR => "STOP_MOTOR",
        CMD_STOP_ALL_MOTORS => "STOP_ALL_MOTORS",
        CMD_APPLY_CONFIG => "APPLY_CONFIG",
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
        CMD_ARM_STOP => "ARM_STOP",
        CMD_SERVO_SET => "SERVO_SET",
        CMD_SUBSCRIBE => "SUBSCRIBE",
        _ => "UNKNOWN",
    }
}

#[derive(Debug)]
enum HttpError {
    BadRequest,
    Closed,
    FrameTooLarge,
    RequestTooLarge,
    Tcp(TcpError),
}

impl From<TcpError> for HttpError {
    fn from(err: TcpError) -> Self {
        Self::Tcp(err)
    }
}
