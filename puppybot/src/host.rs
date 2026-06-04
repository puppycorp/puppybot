use std::{
    io::{ErrorKind, Read, Write},
    net::{TcpListener, TcpStream},
    sync::{Arc, Mutex},
    time::{Duration, Instant},
};

use embassy_executor as _;
use sha1::{Digest, Sha1};

use crate::{
    protocol::{self, ProtocolEvent, ProtocolState},
    puppyarm::state_engine::PuppyArm,
    utility::{base64_encode, eq_ignore_ascii_case, find_bytes, trim_ascii},
};

const DEFAULT_BIND: &str = "0.0.0.0:8080";
const MAX_HTTP_REQUEST: usize = 2048;
const MAX_WS_FRAME_SIZE: usize = 2048;
const WEBSOCKET_GUID: &[u8] = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11";

pub(crate) fn run() {
    init_logger();

    let bind = std::env::var("PUPPYBOT_HOST_ADDR").unwrap_or_else(|_| DEFAULT_BIND.to_string());
    let listener = TcpListener::bind(&bind).expect("failed to bind host websocket server");
    let robot = Arc::new(Mutex::new(HostRobot::new()));

    log::info!("puppybot host simulator listening on ws://{bind}/ws");
    log::info!("set PUPPYBOT_HOST_ADDR=127.0.0.1:8080 to bind another address");

    for incoming in listener.incoming() {
        match incoming {
            Ok(stream) => {
                let robot = Arc::clone(&robot);
                std::thread::spawn(move || {
                    if let Err(err) = handle_connection(stream, robot) {
                        log::warn!("host websocket connection ended: {err}");
                    }
                });
            }
            Err(err) => log::warn!("accept failed: {err:?}"),
        }
    }
}

fn init_logger() {
    let _ = env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("info"))
        .format_timestamp_millis()
        .try_init();
}

fn handle_connection(mut stream: TcpStream, robot: Arc<Mutex<HostRobot>>) -> Result<(), HostError> {
    stream.set_read_timeout(Some(Duration::from_millis(100)))?;
    stream.set_nodelay(true)?;

    let mut request = [0u8; MAX_HTTP_REQUEST];
    let request_len = read_http_request(&mut stream, &mut request)?;
    let request = &request[..request_len];

    if is_websocket_request(request) {
        handle_websocket_upgrade(&mut stream, request)?;
        websocket_loop(&mut stream, robot)
    } else if request.starts_with(b"GET / ") || request.starts_with(b"GET / HTTP/") {
        stream.write_all(
            b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nConnection: close\r\nContent-Length: 43\r\n\r\npuppybot host websocket is on ws://host/ws\n",
        )?;
        Ok(())
    } else {
        stream.write_all(
            b"HTTP/1.1 404 Not Found\r\nConnection: close\r\nContent-Length: 10\r\n\r\nnot found\n",
        )?;
        Ok(())
    }
}

fn websocket_loop(stream: &mut TcpStream, robot: Arc<Mutex<HostRobot>>) -> Result<(), HostError> {
    let mut payload = [0u8; MAX_WS_FRAME_SIZE];
    let mut telemetry_enabled = false;
    let mut sent_telemetry_seq = None;

    loop {
        let telemetry = {
            let mut robot = robot.lock().unwrap();
            robot.tick();
            if telemetry_enabled && sent_telemetry_seq != Some(robot.telemetry_seq) {
                Some((robot.telemetry_seq, robot.arm_state_frame()))
            } else {
                None
            }
        };
        if let Some((seq, frame)) = telemetry {
            send_ws_frame(stream, 0x2, &frame)?;
            sent_telemetry_seq = Some(seq);
        }

        let frame = match read_ws_frame(stream, &mut payload) {
            Ok(frame) => frame,
            Err(HostError::WouldBlock) => continue,
            Err(err) => return Err(err),
        };

        match frame.opcode {
            0x1 => {
                if frame.payload == b"ping" {
                    send_ws_frame(stream, 0x1, b"pong")?;
                }
            }
            0x2 => {
                let response = {
                    let mut robot = robot.lock().unwrap();
                    robot.handle_binary_command(frame.payload, &mut telemetry_enabled)
                };
                if let Some(response) = response {
                    send_ws_frame(stream, 0x2, &response)?;
                }
            }
            0x8 => {
                send_ws_frame(stream, 0x8, &[])?;
                return Ok(());
            }
            0x9 => send_ws_frame(stream, 0xA, frame.payload)?,
            _ => {}
        }
    }
}

struct HostRobot {
    engine: PuppyArm,
    protocol: ProtocolState,
    started_at: Instant,
    last_tick_at: Instant,
    telemetry_seq: u32,
}

impl HostRobot {
    fn new() -> Self {
        let started_at = Instant::now();
        Self {
            engine: PuppyArm::new(0),
            protocol: ProtocolState::default(),
            started_at,
            last_tick_at: started_at,
            telemetry_seq: 0,
        }
    }

    fn now_ms(&self) -> u64 {
        self.started_at.elapsed().as_millis() as u64
    }

    fn tick(&mut self) {
        let now = Instant::now();
        let elapsed_ms = now.duration_since(self.last_tick_at).as_millis() as i32;
        if elapsed_ms == 0 {
            return;
        }
        self.last_tick_at = now;

        let now_ms = self.now_ms();
        self.engine.advance_simulation(elapsed_ms as u64, now_ms);
        self.telemetry_seq = self.telemetry_seq.wrapping_add(1);
    }

    fn handle_binary_command(
        &mut self,
        payload: &[u8],
        telemetry_enabled: &mut bool,
    ) -> Option<Vec<u8>> {
        if payload.len() < 4 {
            log::warn!("ignoring short host WS frame len={}", payload.len());
            return None;
        }

        let version = payload[0];
        let cmd = payload[1];
        let payload_len = u16::from_le_bytes([payload[2], payload[3]]) as usize;
        log::info!(
            "host WS command {} version={} declared_len={} actual_len={}",
            protocol::command_name(cmd),
            version,
            payload_len,
            payload.len().saturating_sub(4)
        );

        self.protocol.telemetry_enabled = *telemetry_enabled;
        let output = protocol::handle_binary_command(payload, &mut self.protocol);
        *telemetry_enabled = self.protocol.telemetry_enabled;

        for event in output.events {
            self.dispatch_protocol_event(event);
        }

        output.response
    }

    fn dispatch_protocol_event(&mut self, event: ProtocolEvent) {
        let now_ms = self.now_ms();
        let ProtocolEvent::Arm(command) = event;
        self.engine.handle_arm_cmd(command, now_ms);
        self.engine.step(now_ms);
    }

    fn arm_state_frame(&self) -> Vec<u8> {
        self.engine.arm_state_frame()
    }
}

struct WsFrame<'a> {
    opcode: u8,
    payload: &'a [u8],
}

fn read_http_request(stream: &mut TcpStream, request: &mut [u8]) -> Result<usize, HostError> {
    let mut len = 0;

    loop {
        if len == request.len() {
            return Err(HostError::RequestTooLarge);
        }

        match stream.read(&mut request[len..]) {
            Ok(0) => return Err(HostError::Closed),
            Ok(read) => {
                len += read;
                if find_bytes(&request[..len], b"\r\n\r\n").is_some() {
                    return Ok(len);
                }
            }
            Err(err)
                if err.kind() == ErrorKind::WouldBlock || err.kind() == ErrorKind::TimedOut =>
            {
                return Err(HostError::WouldBlock);
            }
            Err(err) => return Err(err.into()),
        }
    }
}

fn handle_websocket_upgrade(stream: &mut TcpStream, request: &[u8]) -> Result<(), HostError> {
    let key = header_value(request, b"sec-websocket-key").ok_or(HostError::BadRequest)?;
    let mut accept = [0u8; 28];
    websocket_accept_key(key, &mut accept)?;

    stream.write_all(b"HTTP/1.1 101 Switching Protocols\r\n")?;
    stream.write_all(b"Upgrade: websocket\r\n")?;
    stream.write_all(b"Connection: Upgrade\r\n")?;
    stream.write_all(b"Sec-WebSocket-Accept: ")?;
    stream.write_all(&accept)?;
    stream.write_all(b"\r\n\r\n")?;
    Ok(())
}

fn read_ws_frame<'a>(
    stream: &mut TcpStream,
    payload: &'a mut [u8],
) -> Result<WsFrame<'a>, HostError> {
    let mut header = [0u8; 2];
    read_exact(stream, &mut header)?;

    let opcode = header[0] & 0x0f;
    let masked = (header[1] & 0x80) != 0;
    let mut len = (header[1] & 0x7f) as usize;

    if len == 126 {
        let mut extended = [0u8; 2];
        read_exact(stream, &mut extended)?;
        len = u16::from_be_bytes(extended) as usize;
    } else if len == 127 {
        let mut extended = [0u8; 8];
        read_exact(stream, &mut extended)?;
        let raw_len = u64::from_be_bytes(extended);
        if raw_len > usize::MAX as u64 {
            return Err(HostError::FrameTooLarge);
        }
        len = raw_len as usize;
    }

    if len > payload.len() {
        return Err(HostError::FrameTooLarge);
    }

    let mut mask = [0u8; 4];
    if masked {
        read_exact(stream, &mut mask)?;
    }

    read_exact(stream, &mut payload[..len])?;
    if masked {
        for (idx, byte) in payload[..len].iter_mut().enumerate() {
            *byte ^= mask[idx % 4];
        }
    }

    Ok(WsFrame {
        opcode,
        payload: &payload[..len],
    })
}

fn send_ws_frame(stream: &mut TcpStream, opcode: u8, payload: &[u8]) -> Result<(), HostError> {
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

    stream.write_all(&header[..header_len])?;
    stream.write_all(payload)?;
    Ok(())
}

fn read_exact(stream: &mut TcpStream, mut buf: &mut [u8]) -> Result<(), HostError> {
    while !buf.is_empty() {
        match stream.read(buf) {
            Ok(0) => return Err(HostError::Closed),
            Ok(read) => {
                let (_, rest) = buf.split_at_mut(read);
                buf = rest;
            }
            Err(err)
                if err.kind() == ErrorKind::WouldBlock || err.kind() == ErrorKind::TimedOut =>
            {
                return Err(HostError::WouldBlock);
            }
            Err(err) => return Err(err.into()),
        }
    }
    Ok(())
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

fn websocket_accept_key(key: &[u8], out: &mut [u8; 28]) -> Result<(), HostError> {
    let mut hasher = Sha1::new();
    hasher.update(key);
    hasher.update(WEBSOCKET_GUID);
    let digest = hasher.finalize();
    base64_encode(&digest, out).map_err(|()| HostError::FrameTooLarge)?;
    Ok(())
}

#[derive(Debug)]
enum HostError {
    BadRequest,
    Closed,
    FrameTooLarge,
    RequestTooLarge,
    WouldBlock,
    Io(std::io::Error),
}

impl From<std::io::Error> for HostError {
    fn from(err: std::io::Error) -> Self {
        Self::Io(err)
    }
}

impl std::fmt::Display for HostError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::BadRequest => formatter.write_str("bad request"),
            Self::Closed => formatter.write_str("connection closed"),
            Self::FrameTooLarge => formatter.write_str("websocket frame too large"),
            Self::RequestTooLarge => formatter.write_str("http request too large"),
            Self::WouldBlock => formatter.write_str("operation would block"),
            Self::Io(err) => write!(formatter, "{err}"),
        }
    }
}

impl std::error::Error for HostError {}
