use std::time::Duration;

use anyhow::{Context, Result, bail};
use futures_util::{SinkExt, StreamExt};
use puppybot_core::protocol::{
    CONFIG_VERSION, MSG_TO_SRV_ARM_STATE, MSG_TO_SRV_CONFIG_STATE, MSG_TO_SRV_PONG, RobotConfig,
    SUBSCRIPTION_TOPIC_ARM_STATE, command_frame,
};
use tokio_tungstenite::{connect_async, tungstenite::Message};

pub(crate) struct RuntimeClient {
    ws: tokio_tungstenite::WebSocketStream<
        tokio_tungstenite::MaybeTlsStream<tokio::net::TcpStream>,
    >,
}

#[derive(Debug)]
pub(crate) enum RuntimeFrame {
    Pong,
    Config(RobotConfig),
    ArmState(ArmState),
    Binary(Vec<u8>),
    Text(String),
}

#[derive(Debug)]
pub(crate) struct ArmState {
    pub(crate) joints: Vec<JointState>,
    pub(crate) coords_mm: Option<[f32; 3]>,
}

#[derive(Debug)]
pub(crate) struct JointState {
    pub(crate) servo_id: u8,
    pub(crate) online: bool,
    pub(crate) has_feedback: bool,
    pub(crate) limit_reached: bool,
    pub(crate) has_fault: bool,
    pub(crate) tick: i32,
    pub(crate) target_tick: Option<i32>,
    pub(crate) speed: i16,
    pub(crate) limit_min: i32,
    pub(crate) limit_max: i32,
    pub(crate) angle_deg: f32,
    pub(crate) fault: Option<String>,
}

fn read_i16_le(bytes: &[u8], offset: usize) -> Result<i16> {
    let bytes = bytes
        .get(offset..offset + 2)
        .with_context(|| format!("short frame reading i16 at {offset}"))?;
    Ok(i16::from_le_bytes([bytes[0], bytes[1]]))
}

fn read_i32_le(bytes: &[u8], offset: usize) -> Result<i32> {
    let bytes = bytes
        .get(offset..offset + 4)
        .with_context(|| format!("short frame reading i32 at {offset}"))?;
    Ok(i32::from_le_bytes([bytes[0], bytes[1], bytes[2], bytes[3]]))
}

fn read_f32_le(bytes: &[u8], offset: usize) -> Result<f32> {
    let bytes = bytes
        .get(offset..offset + 4)
        .with_context(|| format!("short frame reading f32 at {offset}"))?;
    Ok(f32::from_le_bytes([bytes[0], bytes[1], bytes[2], bytes[3]]))
}

fn decode_arm_state(payload: &[u8]) -> Result<ArmState> {
    if payload.len() < 4 || payload[2] != MSG_TO_SRV_ARM_STATE {
        bail!("not an arm state frame");
    }

    let joint_count = payload[3] as usize;
    let mut offset = 4;
    let mut joints = Vec::with_capacity(joint_count);

    for _ in 0..joint_count {
        let servo_id = *payload.get(offset).context("short arm state servo id")?;
        let flags = *payload.get(offset + 1).context("short arm state flags")?;
        offset += 2;

        let tick = read_i32_le(payload, offset)?;
        offset += 4;
        let raw_target_tick = read_i32_le(payload, offset)?;
        offset += 4;
        let speed = read_i16_le(payload, offset)?;
        offset += 2;
        let limit_min = read_i32_le(payload, offset)?;
        offset += 4;
        let limit_max = read_i32_le(payload, offset)?;
        offset += 4;
        let angle_deg = read_f32_le(payload, offset)?;
        offset += 4;

        let fault_len = *payload.get(offset).context("short arm state fault len")? as usize;
        offset += 1;
        let fault = if fault_len == 0 {
            None
        } else {
            let bytes = payload
                .get(offset..offset + fault_len)
                .context("short arm state fault string")?;
            Some(String::from_utf8_lossy(bytes).to_string())
        };
        offset += fault_len;

        let has_target = (flags & 0x08) != 0;
        joints.push(JointState {
            servo_id,
            online: (flags & 0x01) != 0,
            has_feedback: (flags & 0x02) != 0,
            limit_reached: (flags & 0x04) != 0,
            has_fault: (flags & 0x10) != 0,
            tick,
            target_tick: has_target.then_some(raw_target_tick),
            speed,
            limit_min,
            limit_max,
            angle_deg,
            fault,
        });
    }

    let coords_mm = match payload.get(offset).copied() {
        Some(0) => None,
        Some(_) => Some([
            read_f32_le(payload, offset + 1)?,
            read_f32_le(payload, offset + 5)?,
            read_f32_le(payload, offset + 9)?,
        ]),
        None => None,
    };

    Ok(ArmState { joints, coords_mm })
}

fn decode_binary(payload: Vec<u8>) -> Result<RuntimeFrame> {
    if payload.len() < 3 {
        return Ok(RuntimeFrame::Binary(payload));
    }

    match payload[2] {
        MSG_TO_SRV_PONG => Ok(RuntimeFrame::Pong),
        MSG_TO_SRV_CONFIG_STATE => {
            if payload.get(3).copied() != Some(CONFIG_VERSION) {
                bail!("unsupported config frame");
            }
            let config = RobotConfig::decode(&payload[3..]).context("invalid config frame")?;
            Ok(RuntimeFrame::Config(config))
        }
        MSG_TO_SRV_ARM_STATE => Ok(RuntimeFrame::ArmState(decode_arm_state(&payload)?)),
        _ => Ok(RuntimeFrame::Binary(payload)),
    }
}

impl RuntimeClient {
    pub(crate) async fn connect(url: &str) -> Result<Self> {
        let (ws, _) = connect_async(url)
            .await
            .with_context(|| format!("connect runtime websocket {url}"))?;
        Ok(Self { ws })
    }

    pub(crate) async fn send_command(&mut self, command: u8, body: &[u8]) -> Result<()> {
        self.ws
            .send(Message::Binary(command_frame(command, body)))
            .await
            .context("send runtime command")
    }

    pub(crate) async fn send_text(&mut self, text: &str) -> Result<()> {
        self.ws
            .send(Message::Text(text.to_string()))
            .await
            .context("send runtime text")
    }

    pub(crate) async fn read_frame(&mut self, timeout: Duration) -> Result<RuntimeFrame> {
        loop {
            let message = tokio::time::timeout(timeout, self.ws.next())
                .await
                .context("runtime websocket response timed out")?
                .context("runtime websocket closed")?
                .context("read runtime websocket message")?;

            match message {
                Message::Binary(payload) => return decode_binary(payload),
                Message::Text(payload) => return Ok(RuntimeFrame::Text(payload)),
                Message::Ping(payload) => {
                    self.ws.send(Message::Pong(payload)).await?;
                }
                Message::Pong(_) | Message::Frame(_) => {}
                Message::Close(_) => bail!("runtime websocket closed"),
            }
        }
    }

    pub(crate) async fn subscribe_arm_state(&mut self, enabled: bool) -> Result<()> {
        self.send_command(
            puppybot_core::protocol::CMD_SUBSCRIBE,
            &[SUBSCRIPTION_TOPIC_ARM_STATE, u8::from(enabled)],
        )
        .await
    }
}
