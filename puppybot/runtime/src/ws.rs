use std::{
    io::{ErrorKind, Read, Write},
    net::TcpStream,
    sync::{Arc, Mutex},
    time::Duration,
};

use puppybot_core::utility::{base64_encode, eq_ignore_ascii_case, find_bytes, trim_ascii};
use sha1::{Digest, Sha1};

use crate::RuntimeRobot;

const MAX_HTTP_REQUEST: usize = 2048;
const MAX_WS_FRAME_SIZE: usize = 2048;
const WEBSOCKET_GUID: &[u8] = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11";

struct WsFrame<'a> {
    opcode: u8,
    payload: &'a [u8],
}

#[derive(Debug)]
pub(crate) enum Error {
    BadRequest,
    Closed,
    FrameTooLarge,
    RequestTooLarge,
    WouldBlock,
    Io(std::io::Error),
}

impl From<std::io::Error> for Error {
    fn from(err: std::io::Error) -> Self {
        Self::Io(err)
    }
}

impl std::fmt::Display for Error {
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

impl std::error::Error for Error {}

fn websocket_accept_key(key: &[u8], out: &mut [u8; 28]) -> Result<(), Error> {
    let mut hasher = Sha1::new();
    hasher.update(key);
    hasher.update(WEBSOCKET_GUID);
    let digest = hasher.finalize();
    base64_encode(&digest, out).map_err(|()| Error::FrameTooLarge)?;
    Ok(())
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

fn is_websocket_request(request: &[u8]) -> bool {
    request.starts_with(b"GET /ws ")
        && header_value(request, b"upgrade")
            .map(|value| eq_ignore_ascii_case(value, b"websocket"))
            .unwrap_or(false)
        && header_value(request, b"sec-websocket-key").is_some()
}

fn request_target(request: &[u8]) -> Option<&[u8]> {
    let line_end = find_bytes(request, b"\r\n")?;
    let request_line = &request[..line_end];
    let mut parts = request_line.split(|byte| *byte == b' ');
    match (parts.next(), parts.next(), parts.next()) {
        (Some(b"GET"), Some(target), Some(_)) => Some(target),
        _ => None,
    }
}

fn read_exact(stream: &mut TcpStream, mut buf: &mut [u8]) -> Result<(), Error> {
    while !buf.is_empty() {
        match stream.read(buf) {
            Ok(0) => return Err(Error::Closed),
            Ok(read) => {
                let (_, rest) = buf.split_at_mut(read);
                buf = rest;
            }
            Err(err)
                if err.kind() == ErrorKind::WouldBlock || err.kind() == ErrorKind::TimedOut =>
            {
                return Err(Error::WouldBlock);
            }
            Err(err) => return Err(err.into()),
        }
    }
    Ok(())
}

fn send_ws_frame(stream: &mut TcpStream, opcode: u8, payload: &[u8]) -> Result<(), Error> {
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

fn read_ws_frame<'a>(stream: &mut TcpStream, payload: &'a mut [u8]) -> Result<WsFrame<'a>, Error> {
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
            return Err(Error::FrameTooLarge);
        }
        len = raw_len as usize;
    }

    if len > payload.len() {
        return Err(Error::FrameTooLarge);
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

fn handle_websocket_upgrade(stream: &mut TcpStream, request: &[u8]) -> Result<(), Error> {
    let key = header_value(request, b"sec-websocket-key").ok_or(Error::BadRequest)?;
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

fn read_http_request(stream: &mut TcpStream, request: &mut [u8]) -> Result<usize, Error> {
    let mut len = 0;

    loop {
        if len == request.len() {
            return Err(Error::RequestTooLarge);
        }

        match stream.read(&mut request[len..]) {
            Ok(0) => return Err(Error::Closed),
            Ok(read) => {
                len += read;
                if find_bytes(&request[..len], b"\r\n\r\n").is_some() {
                    return Ok(len);
                }
            }
            Err(err)
                if err.kind() == ErrorKind::WouldBlock || err.kind() == ErrorKind::TimedOut =>
            {
                return Err(Error::WouldBlock);
            }
            Err(err) => return Err(err.into()),
        }
    }
}

fn write_http_response(
    stream: &mut TcpStream,
    status: &str,
    content_type: &str,
    body: &[u8],
) -> Result<(), Error> {
    write!(
        stream,
        "HTTP/1.1 {status}\r\nContent-Type: {content_type}\r\nConnection: close\r\nContent-Length: {}\r\n\r\n",
        body.len()
    )?;
    stream.write_all(body)?;
    Ok(())
}

fn config_json_body(robot: &Arc<Mutex<RuntimeRobot>>) -> Result<String, String> {
    let mut robot = robot.lock().unwrap();
    robot.config_json()
}

fn websocket_loop(stream: &mut TcpStream, robot: Arc<Mutex<RuntimeRobot>>) -> Result<(), Error> {
    let mut payload = [0u8; MAX_WS_FRAME_SIZE];
    let mut telemetry_enabled = false;
    let mut sent_telemetry_seq = None;

    loop {
        let telemetry = {
            let mut robot = robot.lock().unwrap();
            robot.tick();
            if telemetry_enabled && sent_telemetry_seq != Some(robot.telemetry_seq()) {
                Some((robot.telemetry_seq(), robot.arm_state_frame()))
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
            Err(Error::WouldBlock) => continue,
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

pub(crate) fn handle_connection(
    mut stream: TcpStream,
    robot: Arc<Mutex<RuntimeRobot>>,
) -> Result<(), Error> {
    stream.set_read_timeout(Some(Duration::from_millis(100)))?;
    stream.set_nodelay(true)?;

    let mut request = [0u8; MAX_HTTP_REQUEST];
    let request_len = read_http_request(&mut stream, &mut request)?;
    let request = &request[..request_len];

    if is_websocket_request(request) {
        handle_websocket_upgrade(&mut stream, request)?;
        websocket_loop(&mut stream, robot)
    } else if request_target(request) == Some(b"/api/config.json") {
        let body = config_json_body(&robot);
        match body {
            Ok(body) => {
                write_http_response(&mut stream, "200 OK", "application/json", body.as_bytes())
            }
            Err(err) => {
                let body = format!("{{\"error\":{}}}\n", serde_json::json!(err));
                write_http_response(
                    &mut stream,
                    "500 Internal Server Error",
                    "application/json",
                    body.as_bytes(),
                )
            }
        }
    } else if request_target(request) == Some(b"/") {
        write_http_response(
            &mut stream,
            "200 OK",
            "text/plain",
            b"puppybot runtime websocket is available on /ws\nconfig is available on /api/config.json\n",
        )
    } else {
        write_http_response(&mut stream, "404 Not Found", "text/plain", b"not found\n")
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    use puppybot_core::config::PuppybotConfigV1;

    #[test]
    fn request_target_reads_get_path() {
        let request = b"GET /api/config.json HTTP/1.1\r\nHost: localhost\r\n\r\n";

        assert_eq!(
            request_target(request),
            Some(b"/api/config.json".as_slice())
        );
    }

    #[test]
    fn config_json_body_returns_active_config() {
        let robot = Arc::new(Mutex::new(RuntimeRobot::new(
            None,
            PathBuf::from("puppybot.json"),
            PuppybotConfigV1::default(),
        )));

        let body = config_json_body(&robot).unwrap();
        let value: serde_json::Value = serde_json::from_str(&body).unwrap();

        assert_eq!(value["path"], "puppybot.json");
        assert_eq!(value["dirty"], false);
        assert_eq!(value["config"]["serial"], "PB-DEV-0001");
    }
}
