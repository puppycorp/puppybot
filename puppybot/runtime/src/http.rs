use std::{collections::HashMap, net::SocketAddr};

use puppybot_core::utility::{base64_encode, eq_ignore_ascii_case, find_bytes, trim_ascii};
use sha1::{Digest, Sha1};
use tokio::{
    io::{AsyncRead, AsyncReadExt, AsyncWrite, AsyncWriteExt},
    net::{TcpListener as TokioTcpListener, TcpStream as TokioTcpStream},
    sync::mpsc,
};

const MAX_HTTP_REQUEST: usize = 12 * 1024;
const MAX_HTTP_BODY: usize = 8 * 1024;
const MAX_WS_FRAME_SIZE: usize = 2048;
const WEBSOCKET_GUID: &[u8] = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11";

struct OwnedWsFrame {
    opcode: u8,
    payload: Vec<u8>,
}

#[derive(Debug, PartialEq, Eq)]
pub(crate) enum HttpEvent {
    WebSocketConnected {
        client_id: u64,
    },
    WebSocketBinary {
        client_id: u64,
        payload: Vec<u8>,
    },
    WebSocketText {
        client_id: u64,
        payload: Vec<u8>,
    },
    HttpRequest {
        request_id: u64,
        method: Vec<u8>,
        target: Vec<u8>,
        body: Vec<u8>,
    },
    WebSocketClosed {
        client_id: u64,
    },
}

#[derive(Debug)]
pub(crate) enum HttpCommand {
    SendWebSocketBinary {
        client_id: u64,
        payload: Vec<u8>,
    },
    SendWebSocketText {
        client_id: u64,
        payload: Vec<u8>,
    },
    HttpResponse {
        request_id: u64,
        status: &'static str,
        content_type: &'static str,
        body: Vec<u8>,
    },
    #[allow(dead_code)]
    Close {
        client_id: u64,
    },
}

enum ConnectionCommand {
    SendBinary(Vec<u8>),
    SendText(Vec<u8>),
    HttpResponse {
        status: &'static str,
        content_type: &'static str,
        body: Vec<u8>,
    },
    Close,
}

pub(crate) struct HttpServer {
    local_addr: SocketAddr,
    events: mpsc::Receiver<HttpEvent>,
    commands: mpsc::Sender<HttpCommand>,
}

#[derive(Debug)]
pub(crate) enum Error {
    BadRequest,
    Closed,
    FrameTooLarge,
    RequestTooLarge,
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
            Self::Io(err) => write!(formatter, "{err}"),
        }
    }
}

impl std::error::Error for Error {}

impl HttpServer {
    pub(crate) fn local_addr(&self) -> SocketAddr {
        self.local_addr
    }

    pub(crate) async fn next(&mut self) -> Option<HttpEvent> {
        self.events.recv().await
    }

    pub(crate) async fn send_binary(&self, client_id: u64, payload: Vec<u8>) {
        let _ = self
            .commands
            .send(HttpCommand::SendWebSocketBinary { client_id, payload })
            .await;
    }

    pub(crate) async fn send_text(&self, client_id: u64, payload: Vec<u8>) {
        let _ = self
            .commands
            .send(HttpCommand::SendWebSocketText { client_id, payload })
            .await;
    }

    pub(crate) async fn send_http_response(
        &self,
        request_id: u64,
        status: &'static str,
        content_type: &'static str,
        body: Vec<u8>,
    ) {
        let _ = self
            .commands
            .send(HttpCommand::HttpResponse {
                request_id,
                status,
                content_type,
                body,
            })
            .await;
    }

    #[allow(dead_code)]
    pub(crate) async fn close(&self, client_id: u64) {
        let _ = self.commands.send(HttpCommand::Close { client_id }).await;
    }
}

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

fn request_line_parts(request: &[u8]) -> Option<(&[u8], &[u8])> {
    let line_end = find_bytes(request, b"\r\n")?;
    let request_line = &request[..line_end];
    let mut parts = request_line.split(|byte| *byte == b' ');
    match (parts.next(), parts.next(), parts.next()) {
        (Some(method), Some(target), Some(_)) => Some((method, target)),
        _ => None,
    }
}

fn request_target(request: &[u8]) -> Option<&[u8]> {
    request_line_parts(request).map(|(_, target)| target)
}

fn content_length(request: &[u8]) -> Result<usize, Error> {
    let Some(value) = header_value(request, b"content-length") else {
        return Ok(0);
    };
    let value = std::str::from_utf8(value).map_err(|_| Error::BadRequest)?;
    value.parse::<usize>().map_err(|_| Error::BadRequest)
}

async fn send_ws_frame_async<W>(writer: &mut W, opcode: u8, payload: &[u8]) -> Result<(), Error>
where
    W: AsyncWrite + Unpin,
{
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

    writer.write_all(&header[..header_len]).await?;
    writer.write_all(payload).await?;
    Ok(())
}

async fn read_ws_frame_async<R>(reader: &mut R) -> Result<OwnedWsFrame, Error>
where
    R: AsyncRead + Unpin,
{
    let mut header = [0u8; 2];
    reader.read_exact(&mut header).await?;

    let opcode = header[0] & 0x0f;
    let masked = (header[1] & 0x80) != 0;
    let mut len = (header[1] & 0x7f) as usize;

    if len == 126 {
        let mut extended = [0u8; 2];
        reader.read_exact(&mut extended).await?;
        len = u16::from_be_bytes(extended) as usize;
    } else if len == 127 {
        let mut extended = [0u8; 8];
        reader.read_exact(&mut extended).await?;
        let raw_len = u64::from_be_bytes(extended);
        if raw_len > usize::MAX as u64 {
            return Err(Error::FrameTooLarge);
        }
        len = raw_len as usize;
    }

    if len > MAX_WS_FRAME_SIZE {
        return Err(Error::FrameTooLarge);
    }

    let mut mask = [0u8; 4];
    if masked {
        reader.read_exact(&mut mask).await?;
    }

    let mut payload = vec![0u8; len];
    reader.read_exact(&mut payload).await?;
    if masked {
        for (idx, byte) in payload.iter_mut().enumerate() {
            *byte ^= mask[idx % 4];
        }
    }

    Ok(OwnedWsFrame { opcode, payload })
}

async fn read_http_request_async<R>(reader: &mut R, request: &mut [u8]) -> Result<usize, Error>
where
    R: AsyncRead + Unpin,
{
    let mut len = 0;
    let mut header_end = None;

    loop {
        if len == request.len() {
            return Err(Error::RequestTooLarge);
        }

        let read = reader.read(&mut request[len..]).await?;
        if read == 0 {
            return Err(Error::Closed);
        }
        len += read;
        if header_end.is_none() {
            header_end = find_bytes(&request[..len], b"\r\n\r\n").map(|index| index + 4);
        }
        if let Some(header_end) = header_end {
            let body_len = content_length(&request[..header_end])?;
            if body_len > MAX_HTTP_BODY {
                return Err(Error::RequestTooLarge);
            }
            let total_len = header_end
                .checked_add(body_len)
                .ok_or(Error::RequestTooLarge)?;
            if total_len > request.len() {
                return Err(Error::RequestTooLarge);
            }
            if len >= total_len {
                return Ok(total_len);
            }
        }
    }
}

async fn write_http_response_async<W>(
    writer: &mut W,
    status: &str,
    content_type: &str,
    body: &[u8],
) -> Result<(), Error>
where
    W: AsyncWrite + Unpin,
{
    let header = format!(
        "HTTP/1.1 {status}\r\nContent-Type: {content_type}\r\nConnection: close\r\nContent-Length: {}\r\n\r\n",
        body.len()
    );
    writer.write_all(header.as_bytes()).await?;
    writer.write_all(body).await?;
    Ok(())
}

async fn handle_websocket_upgrade_async<W>(writer: &mut W, request: &[u8]) -> Result<(), Error>
where
    W: AsyncWrite + Unpin,
{
    let key = header_value(request, b"sec-websocket-key").ok_or(Error::BadRequest)?;
    let mut accept = [0u8; 28];
    websocket_accept_key(key, &mut accept)?;

    writer
        .write_all(b"HTTP/1.1 101 Switching Protocols\r\n")
        .await?;
    writer.write_all(b"Upgrade: websocket\r\n").await?;
    writer.write_all(b"Connection: Upgrade\r\n").await?;
    writer.write_all(b"Sec-WebSocket-Accept: ").await?;
    writer.write_all(&accept).await?;
    writer.write_all(b"\r\n\r\n").await?;
    Ok(())
}

async fn app_connection_loop(
    mut stream: TokioTcpStream,
    client_id: u64,
    events: mpsc::Sender<HttpEvent>,
    mut commands: mpsc::Receiver<ConnectionCommand>,
) -> Result<(), Error> {
    let mut request = [0u8; MAX_HTTP_REQUEST];
    let request_len = read_http_request_async(&mut stream, &mut request).await?;
    let request = &request[..request_len];

    if !is_websocket_request(request) {
        let parts = request_line_parts(request);
        let target = parts.map(|(_, target)| target);
        if target == Some(b"/") {
            write_http_response_async(
                &mut stream,
                "200 OK",
                "text/plain",
                b"puppybot runtime websocket is available on /ws\nconfig is available on /api/config.json\nstate is available on /api/state\ncommands are available under /api/\n",
            )
            .await?;
        } else if target.is_some_and(|target| target.starts_with(b"/api/")) {
            let (method, target) = parts.expect("target matched above");
            let header_end = find_bytes(request, b"\r\n\r\n")
                .map(|index| index + 4)
                .ok_or(Error::BadRequest)?;
            let body = request[header_end..].to_vec();
            let _ = events
                .send(HttpEvent::HttpRequest {
                    request_id: client_id,
                    method: method.to_vec(),
                    target: target.to_vec(),
                    body,
                })
                .await;
            match commands.recv().await {
                Some(ConnectionCommand::HttpResponse {
                    status,
                    content_type,
                    body,
                }) => {
                    write_http_response_async(&mut stream, status, content_type, &body).await?;
                }
                _ => {
                    write_http_response_async(
                        &mut stream,
                        "500 Internal Server Error",
                        "application/json",
                        b"{\"error\":\"runtime response channel closed\"}\n",
                    )
                    .await?;
                }
            }
        } else {
            write_http_response_async(&mut stream, "404 Not Found", "text/plain", b"not found\n")
                .await?;
        }
        return Ok(());
    }

    handle_websocket_upgrade_async(&mut stream, request).await?;
    let _ = events
        .send(HttpEvent::WebSocketConnected { client_id })
        .await;
    let (mut reader, mut writer) = stream.into_split();

    loop {
        tokio::select! {
            frame = read_ws_frame_async(&mut reader) => {
                match frame? {
                    OwnedWsFrame { opcode: 0x1, payload } => {
                        let _ = events.send(HttpEvent::WebSocketText { client_id, payload }).await;
                    }
                    OwnedWsFrame { opcode: 0x2, payload } => {
                        let _ = events.send(HttpEvent::WebSocketBinary { client_id, payload }).await;
                    }
                    OwnedWsFrame { opcode: 0x8, .. } => {
                        let _ = send_ws_frame_async(&mut writer, 0x8, &[]).await;
                        return Ok(());
                    }
                    OwnedWsFrame { opcode: 0x9, payload } => {
                        send_ws_frame_async(&mut writer, 0xA, &payload).await?;
                    }
                    _ => {}
                }
            }
            command = commands.recv() => {
                match command {
                    Some(ConnectionCommand::SendBinary(payload)) => {
                        send_ws_frame_async(&mut writer, 0x2, &payload).await?;
                    }
                    Some(ConnectionCommand::SendText(payload)) => {
                        send_ws_frame_async(&mut writer, 0x1, &payload).await?;
                    }
                    Some(ConnectionCommand::HttpResponse { .. }) => {}
                    Some(ConnectionCommand::Close) => {
                        let _ = send_ws_frame_async(&mut writer, 0x8, &[]).await;
                        return Ok(());
                    }
                    None => return Ok(()),
                }
            }
        }
    }
}

pub(crate) fn start_app_server(bind_addr: SocketAddr) -> Result<HttpServer, Error> {
    let listener = std::net::TcpListener::bind(bind_addr)?;
    listener.set_nonblocking(true)?;
    let listener = TokioTcpListener::from_std(listener)?;
    let local_addr = listener.local_addr()?;
    let (event_tx, event_rx) = mpsc::channel(64);
    let (command_tx, mut command_rx) = mpsc::channel(64);
    let (closed_tx, mut closed_rx) = mpsc::channel(64);

    tokio::spawn(async move {
        let mut clients: HashMap<u64, mpsc::Sender<ConnectionCommand>> = HashMap::new();
        let mut next_client_id = 1u64;

        loop {
            tokio::select! {
                accepted = listener.accept() => {
                    let (stream, _) = match accepted {
                        Ok(accepted) => accepted,
                        Err(err) => {
                            log::warn!("runtime App websocket accept failed: {err}");
                            continue;
                        }
                    };
                    let client_id = next_client_id;
                    next_client_id = next_client_id.wrapping_add(1).max(1);
                    let (client_tx, client_rx) = mpsc::channel(16);
                    clients.insert(client_id, client_tx);
                    let events = event_tx.clone();
                    let closed = closed_tx.clone();
                    tokio::spawn(async move {
                        let result = app_connection_loop(stream, client_id, events.clone(), client_rx).await;
                        if let Err(err) = result
                            && !matches!(err, Error::Closed)
                        {
                            log::warn!("runtime App websocket client {client_id} ended: {err}");
                        }
                        let _ = events.send(HttpEvent::WebSocketClosed { client_id }).await;
                        let _ = closed.send(client_id).await;
                    });
                }
                command = command_rx.recv() => {
                    let Some(command) = command else {
                        break;
                    };
                    match command {
                        HttpCommand::SendWebSocketBinary { client_id, payload } => {
                            if let Some(client) = clients.get(&client_id)
                                && client.send(ConnectionCommand::SendBinary(payload)).await.is_err()
                            {
                                clients.remove(&client_id);
                            }
                        }
                        HttpCommand::SendWebSocketText { client_id, payload } => {
                            if let Some(client) = clients.get(&client_id)
                                && client.send(ConnectionCommand::SendText(payload)).await.is_err()
                            {
                                clients.remove(&client_id);
                            }
                        }
                        HttpCommand::HttpResponse { request_id, status, content_type, body } => {
                            if let Some(client) = clients.get(&request_id)
                                && client.send(ConnectionCommand::HttpResponse { status, content_type, body }).await.is_err()
                            {
                                clients.remove(&request_id);
                            }
                        }
                        HttpCommand::Close { client_id } => {
                            if let Some(client) = clients.remove(&client_id) {
                                let _ = client.send(ConnectionCommand::Close).await;
                            }
                        }
                    }
                }
                closed = closed_rx.recv() => {
                    let Some(client_id) = closed else {
                        break;
                    };
                    clients.remove(&client_id);
                }
            }
        }
    });

    Ok(HttpServer {
        local_addr,
        events: event_rx,
        commands: command_tx,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::ErrorKind as IoErrorKind;
    use std::time::Duration;

    use tokio::time::timeout;

    fn start_test_app_server() -> Option<HttpServer> {
        match start_app_server("127.0.0.1:0".parse().unwrap()) {
            Ok(server) => Some(server),
            Err(Error::Io(err)) if err.kind() == IoErrorKind::PermissionDenied => None,
            Err(err) => panic!("failed to start test websocket server: {err}"),
        }
    }

    async fn connect_app_ws(server: &HttpServer) -> TokioTcpStream {
        let mut stream = TokioTcpStream::connect(server.local_addr()).await.unwrap();
        stream
            .write_all(
                b"GET /ws HTTP/1.1\r\n\
                Host: localhost\r\n\
                Upgrade: websocket\r\n\
                Connection: Upgrade\r\n\
                Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n\
                Sec-WebSocket-Version: 13\r\n\
                \r\n",
            )
            .await
            .unwrap();

        let mut response = [0u8; 512];
        let read = stream.read(&mut response).await.unwrap();
        assert!(
            std::str::from_utf8(&response[..read])
                .unwrap()
                .starts_with("HTTP/1.1 101 Switching Protocols")
        );
        stream
    }

    async fn next_app_event(server: &mut HttpServer) -> HttpEvent {
        timeout(Duration::from_secs(1), server.next())
            .await
            .unwrap()
            .unwrap()
    }

    async fn send_client_frame(stream: &mut TokioTcpStream, opcode: u8, payload: &[u8]) {
        assert!(payload.len() < 126);
        let mask = [1u8, 2, 3, 4];
        let mut frame = Vec::with_capacity(6 + payload.len());
        frame.push(0x80 | opcode);
        frame.push(0x80 | payload.len() as u8);
        frame.extend_from_slice(&mask);
        for (idx, byte) in payload.iter().enumerate() {
            frame.push(*byte ^ mask[idx % mask.len()]);
        }
        stream.write_all(&frame).await.unwrap();
    }

    #[tokio::test]
    async fn app_server_routes_config_http_response() {
        let Some(mut server) = start_test_app_server() else {
            return;
        };
        let mut client = TokioTcpStream::connect(server.local_addr()).await.unwrap();
        client
            .write_all(b"GET /api/config.json HTTP/1.1\r\nHost: localhost\r\n\r\n")
            .await
            .unwrap();

        let request_id = match next_app_event(&mut server).await {
            HttpEvent::HttpRequest {
                request_id,
                method,
                target,
                body,
            } => {
                assert_eq!(method, b"GET");
                assert_eq!(target, b"/api/config.json");
                assert!(body.is_empty());
                request_id
            }
            event => panic!("unexpected event: {event:?}"),
        };
        server
            .send_http_response(
                request_id,
                "200 OK",
                "application/json",
                b"{\"ok\":true}\n".to_vec(),
            )
            .await;

        let mut response = [0u8; 512];
        let read = timeout(Duration::from_secs(1), client.read(&mut response))
            .await
            .unwrap()
            .unwrap();
        let response = std::str::from_utf8(&response[..read]).unwrap();
        assert!(response.starts_with("HTTP/1.1 200 OK"));
        assert!(response.contains("{\"ok\":true}"));
    }

    #[tokio::test]
    async fn app_server_routes_state_http_response() {
        let Some(mut server) = start_test_app_server() else {
            return;
        };
        let mut client = TokioTcpStream::connect(server.local_addr()).await.unwrap();
        client
            .write_all(b"GET /api/state HTTP/1.1\r\nHost: localhost\r\n\r\n")
            .await
            .unwrap();

        let request_id = match next_app_event(&mut server).await {
            HttpEvent::HttpRequest {
                request_id,
                method,
                target,
                body,
            } => {
                assert_eq!(method, b"GET");
                assert_eq!(target, b"/api/state");
                assert!(body.is_empty());
                request_id
            }
            event => panic!("unexpected event: {event:?}"),
        };
        server
            .send_http_response(
                request_id,
                "200 OK",
                "application/json",
                b"{\"state\":true}\n".to_vec(),
            )
            .await;

        let mut response = [0u8; 512];
        let read = timeout(Duration::from_secs(1), client.read(&mut response))
            .await
            .unwrap()
            .unwrap();
        let response = std::str::from_utf8(&response[..read]).unwrap();
        assert!(response.starts_with("HTTP/1.1 200 OK"));
        assert!(response.contains("Content-Type: application/json"));
        assert!(response.contains("{\"state\":true}"));
    }

    #[test]
    fn request_target_reads_get_path() {
        let config_request = b"GET /api/config.json HTTP/1.1\r\nHost: localhost\r\n\r\n";
        let state_request = b"GET /api/state HTTP/1.1\r\nHost: localhost\r\n\r\n";

        assert_eq!(
            request_target(config_request),
            Some(b"/api/config.json".as_slice())
        );
        assert_eq!(
            request_target(state_request),
            Some(b"/api/state".as_slice())
        );
    }

    #[tokio::test]
    async fn app_server_routes_post_api_body() {
        let Some(mut server) = start_test_app_server() else {
            return;
        };
        let mut client = TokioTcpStream::connect(server.local_addr()).await.unwrap();
        client
            .write_all(
                b"POST /api/drive HTTP/1.1\r\nHost: localhost\r\nContent-Length: 20\r\n\r\n{\"action\":\"forward\"}",
            )
            .await
            .unwrap();

        let request_id = match next_app_event(&mut server).await {
            HttpEvent::HttpRequest {
                request_id,
                method,
                target,
                body,
            } => {
                assert_eq!(method, b"POST");
                assert_eq!(target, b"/api/drive");
                assert_eq!(body, br#"{"action":"forward"}"#);
                request_id
            }
            event => panic!("unexpected event: {event:?}"),
        };
        server
            .send_http_response(
                request_id,
                "200 OK",
                "application/json",
                b"{\"ok\":true}\n".to_vec(),
            )
            .await;

        let mut response = [0u8; 512];
        let read = timeout(Duration::from_secs(1), client.read(&mut response))
            .await
            .unwrap()
            .unwrap();
        let response = std::str::from_utf8(&response[..read]).unwrap();
        assert!(response.starts_with("HTTP/1.1 200 OK"));
        assert!(response.contains("{\"ok\":true}"));
    }

    #[tokio::test]
    async fn app_server_delivers_binary_and_routes_binary_response() {
        let Some(mut server) = start_test_app_server() else {
            return;
        };
        let mut client = connect_app_ws(&server).await;

        let client_id = match next_app_event(&mut server).await {
            HttpEvent::WebSocketConnected { client_id } => client_id,
            event => panic!("unexpected event: {event:?}"),
        };

        send_client_frame(&mut client, 0x2, b"abc").await;
        assert_eq!(
            next_app_event(&mut server).await,
            HttpEvent::WebSocketBinary {
                client_id,
                payload: b"abc".to_vec()
            }
        );

        server.send_binary(client_id, b"response".to_vec()).await;
        let frame = read_ws_frame_async(&mut client).await.unwrap();
        assert_eq!(frame.opcode, 0x2);
        assert_eq!(frame.payload, b"response");
    }

    #[tokio::test]
    async fn app_server_delivers_text_and_routes_text_response() {
        let Some(mut server) = start_test_app_server() else {
            return;
        };
        let mut client = connect_app_ws(&server).await;

        let client_id = match next_app_event(&mut server).await {
            HttpEvent::WebSocketConnected { client_id } => client_id,
            event => panic!("unexpected event: {event:?}"),
        };

        send_client_frame(&mut client, 0x1, b"ping").await;
        assert_eq!(
            next_app_event(&mut server).await,
            HttpEvent::WebSocketText {
                client_id,
                payload: b"ping".to_vec()
            }
        );

        server.send_text(client_id, b"pong".to_vec()).await;
        let frame = read_ws_frame_async(&mut client).await.unwrap();
        assert_eq!(frame.opcode, 0x1);
        assert_eq!(frame.payload, b"pong");
    }

    #[tokio::test]
    async fn app_server_ignores_send_to_missing_client() {
        let Some(server) = start_test_app_server() else {
            return;
        };

        server.send_binary(999, b"missing".to_vec()).await;
        server.send_text(999, b"missing".to_vec()).await;
        server.close(999).await;
    }
}
