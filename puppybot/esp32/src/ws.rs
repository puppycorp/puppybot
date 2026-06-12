#![allow(dead_code)]

use embassy_net::{
    Stack,
    tcp::{Error as TcpError, TcpSocket},
};
use embassy_time::{Duration, Instant, Timer};
use sha1::{Digest, Sha1};

use crate::app::{self, PuppybotApp};
use crate::protocol;
use crate::puppyarm::task::{IntentChannel, PuppyarmTelemetry, TelemetryChannel};
use crate::utility::{base64_encode, eq_ignore_ascii_case, find_bytes, trim_ascii};

const HTTP_PORT: u16 = 80;
const MAX_HTTP_REQUEST: usize = 2048;
const MAX_WS_FRAME_SIZE: usize = 2048;
const WEBSOCKET_GUID: &[u8] = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11";
const WS_IDLE_POLL: Duration = Duration::from_millis(20);

struct WsFrame<'a> {
    opcode: u8,
    payload: &'a [u8],
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

fn websocket_accept_key(key: &[u8], out: &mut [u8; 28]) -> Result<(), HttpError> {
    let mut hasher = Sha1::new();
    hasher.update(key);
    hasher.update(WEBSOCKET_GUID);
    let digest = hasher.finalize();
    base64_encode(&digest, out).map_err(|()| HttpError::FrameTooLarge)?;
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

async fn write_all(socket: &mut TcpSocket<'_>, mut buf: &[u8]) -> Result<(), TcpError> {
    while !buf.is_empty() {
        let written = socket.write(buf).await?;
        buf = &buf[written..];
    }
    socket.flush().await
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

async fn send_arm_state(
    socket: &mut TcpSocket<'_>,
    telemetry: &PuppyarmTelemetry,
) -> Result<(), HttpError> {
    let frame = app::arm_state_frame(telemetry);
    send_ws_frame(socket, 0x2, &frame).await
}

async fn handle_binary_ws_frame(
    socket: &mut TcpSocket<'_>,
    payload: &[u8],
    app: &mut PuppybotApp,
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

    let output = app.handle_frame(payload, telemetry_enabled, arm_intents);

    if let Some(response) = output.response {
        send_ws_frame(socket, 0x2, &response).await?;
    }

    Ok(())
}

async fn websocket_loop(
    socket: &mut TcpSocket<'_>,
    app: &mut PuppybotApp,
    arm_intents: &'static IntentChannel,
    arm_telemetry: &'static TelemetryChannel,
) -> Result<(), HttpError> {
    let mut payload = [0u8; MAX_WS_FRAME_SIZE];
    let mut telemetry_enabled = false;
    let mut latest_telemetry: Option<PuppyarmTelemetry> = None;
    let mut sent_telemetry_seq: Option<u32> = None;

    loop {
        app.tick();

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
                    app,
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

async fn handle_http_connection(
    socket: &mut TcpSocket<'_>,
    app: &mut PuppybotApp,
    arm_intents: &'static IntentChannel,
    arm_telemetry: &'static TelemetryChannel,
) -> Result<(), HttpError> {
    let mut request = [0u8; MAX_HTTP_REQUEST];
    let request_len = read_http_request(socket, &mut request).await?;
    let request = &request[..request_len];

    if is_websocket_request(request) {
        handle_websocket_upgrade(socket, request).await?;
        websocket_loop(socket, app, arm_intents, arm_telemetry).await
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

#[embassy_executor::task]
pub async fn http_websocket_server(
    stack: Stack<'static>,
    arm_intents: &'static IntentChannel,
    arm_telemetry: &'static TelemetryChannel,
) {
    let mut rx_buffer = [0u8; 4096];
    let mut tx_buffer = [0u8; 4096];
    let mut app = PuppybotApp::new(Instant::now().as_millis());

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
                    handle_http_connection(&mut socket, &mut app, arm_intents, arm_telemetry).await
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
