use embassy_net::{
    Stack,
    tcp::{Error as TcpError, TcpSocket},
};
use embassy_time::{Duration, Timer};
use sha1::{Digest, Sha1};

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
const MSG_TO_SRV_PONG: u8 = 1;
const MSG_TO_SRV_CONFIG_STATE: u8 = 8;
const CONFIG_VERSION: u8 = 1;

#[embassy_executor::task]
pub async fn http_websocket_server(stack: Stack<'static>) {
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
                if let Err(err) = handle_http_connection(&mut socket, &mut config).await {
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
) -> Result<(), HttpError> {
    let mut request = [0u8; MAX_HTTP_REQUEST];
    let request_len = read_http_request(socket, &mut request).await?;
    let request = &request[..request_len];

    if is_websocket_request(request) {
        handle_websocket_upgrade(socket, request).await?;
        websocket_loop(socket, config).await
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
) -> Result<(), HttpError> {
    let mut payload = [0u8; MAX_WS_FRAME_SIZE];

    loop {
        let frame = read_ws_frame(socket, &mut payload).await?;

        match frame.opcode {
            0x1 => {
                log::info!("WS text frame len={}", frame.payload.len());
                if frame.payload == b"ping" {
                    send_ws_frame(socket, 0x1, b"pong").await?;
                }
            }
            0x2 => {
                handle_binary_ws_frame(socket, frame.payload, config).await?;
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
        command_name(cmd),
        version,
        payload_len,
        actual_len
    );

    if cmd == CMD_PING {
        let pong = [
            (PUPPY_PROTOCOL_VERSION & 0xff) as u8,
            (PUPPY_PROTOCOL_VERSION >> 8) as u8,
            MSG_TO_SRV_PONG,
        ];
        send_ws_frame(socket, 0x2, &pong).await?;
    } else if cmd == CMD_CONFIG_GET {
        send_config_state(socket, config).await?;
    } else if cmd == CMD_CONFIG_SET {
        match RobotConfig::decode(&payload[4..]) {
            Some(new_config) => {
                *config = new_config;
                log::info!(
                    "updated config steering_servo_id={} arm_servo_ids={:?}",
                    config.steering_servo_id,
                    config.arm_servo_ids
                );
                send_config_state(socket, config).await?;
            }
            None => {
                log::warn!("invalid CONFIG_SET payload len={}", payload[4..].len());
            }
        }
    } else {
        handle_robot_command(cmd, &payload[4..], config);
    }

    Ok(())
}

fn handle_robot_command(cmd: u8, payload: &[u8], config: &RobotConfig) {
    match cmd {
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
        }
        CMD_STOP_DRIVE => {
            log::info!("robot stop drive");
        }
        CMD_ARM_JOINT => {
            if payload.len() < 5 {
                log::warn!("invalid ARM_JOINT payload len={}", payload.len());
                return;
            }
            let joint = payload[0];
            let angle_deg = i16::from_le_bytes([payload[1], payload[2]]);
            let speed = u16::from_le_bytes([payload[3], payload[4]]);
            let servo_id = config
                .arm_servo_ids
                .get(joint as usize)
                .copied()
                .unwrap_or(0xff);
            log::info!(
                "robot arm joint={} servo_id={} angle_deg={} speed={}",
                joint,
                servo_id,
                angle_deg,
                speed
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
        }
        CMD_ARM_STOP => {
            log::info!("robot arm stop");
        }
        CMD_SERVO_SET => {
            if payload.len() < 5 {
                log::warn!("invalid SERVO_SET payload len={}", payload.len());
                return;
            }
            let servo_id = payload[0];
            let angle_deg = u16::from_le_bytes([payload[1], payload[2]]);
            let duration_ms = u16::from_le_bytes([payload[3], payload[4]]);
            log::info!(
                "servo set id={} angle_deg={} duration_ms={}",
                servo_id,
                angle_deg,
                duration_ms
            );
        }
        _ => {}
    }
}

fn read_f32_le(bytes: &[u8]) -> f32 {
    f32::from_bits(u32::from_le_bytes([bytes[0], bytes[1], bytes[2], bytes[3]]))
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

#[derive(Clone, Copy, Debug)]
struct RobotConfig {
    steering_servo_id: u8,
    arm_servo_ids: [u8; 4],
}

impl RobotConfig {
    fn decode(payload: &[u8]) -> Option<Self> {
        if payload.len() < 6 || payload[0] != CONFIG_VERSION {
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
            steering_servo_id: 0,
            arm_servo_ids: [1, 2, 3, 4],
        }
    }
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
