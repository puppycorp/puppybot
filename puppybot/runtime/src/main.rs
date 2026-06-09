use std::{
    net::TcpListener,
    sync::{Arc, Mutex},
    time::Instant,
};

use embassy_executor as _;
use puppybot_core::{
    protocol::{self, ProtocolEvent},
    robot::Puppybot,
};

mod mdns;
mod stservo;
mod ws;

const DEFAULT_BIND: &str = "0.0.0.0:8080";

fn main() {
    init_logger();
    stservo::log_serial_config_from_env();

    let bind = runtime_bind_addr();
    let listener = TcpListener::bind(&bind).expect("failed to bind runtime websocket server");
    let mdns = listener
        .local_addr()
        .ok()
        .and_then(|addr| mdns::start_advertisement(addr.port()));
    let robot = Arc::new(Mutex::new(RuntimeRobot::new()));

    log::info!("puppybot runtime listening on ws://{bind}/ws");
    log::info!("set PUPPYBOT_RUNTIME_ADDR=127.0.0.1:8080 to bind another address");

    let _mdns = mdns;
    for incoming in listener.incoming() {
        match incoming {
            Ok(stream) => {
                let robot = Arc::clone(&robot);
                std::thread::spawn(move || {
                    if let Err(err) = ws::handle_connection(stream, robot) {
                        log::warn!("runtime websocket connection ended: {err}");
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

fn runtime_bind_addr() -> String {
    match std::env::var("PUPPYBOT_RUNTIME_ADDR") {
        Ok(bind) => bind,
        Err(_) => match std::env::var("PUPPYBOT_HOST_ADDR") {
            Ok(bind) => {
                log::warn!("PUPPYBOT_HOST_ADDR is deprecated; use PUPPYBOT_RUNTIME_ADDR");
                bind
            }
            Err(_) => DEFAULT_BIND.to_string(),
        },
    }
}

pub(crate) struct RuntimeRobot {
    robot: Puppybot,
    started_at: Instant,
    last_tick_at: Instant,
    telemetry_seq: u32,
}

impl RuntimeRobot {
    fn new() -> Self {
        let started_at = Instant::now();
        Self {
            robot: Puppybot::new(0),
            started_at,
            last_tick_at: started_at,
            telemetry_seq: 0,
        }
    }

    fn now_ms(&self) -> u64 {
        self.started_at.elapsed().as_millis() as u64
    }

    pub(crate) fn tick(&mut self) {
        let now = Instant::now();
        let elapsed_ms = now.duration_since(self.last_tick_at).as_millis() as i32;
        if elapsed_ms == 0 {
            return;
        }
        self.last_tick_at = now;

        let now_ms = self.now_ms();
        self.robot.tick(elapsed_ms as u64, now_ms);
        self.telemetry_seq = self.telemetry_seq.wrapping_add(1);
    }

    pub(crate) fn telemetry_seq(&self) -> u32 {
        self.telemetry_seq
    }

    pub(crate) fn handle_binary_command(
        &mut self,
        payload: &[u8],
        telemetry_enabled: &mut bool,
    ) -> Option<Vec<u8>> {
        if payload.len() < 4 {
            log::warn!("ignoring short runtime WS frame len={}", payload.len());
            return None;
        }

        let version = payload[0];
        let cmd = payload[1];
        let payload_len = u16::from_le_bytes([payload[2], payload[3]]) as usize;
        log::info!(
            "runtime WS command {} version={} declared_len={} actual_len={}",
            protocol::command_name(cmd),
            version,
            payload_len,
            payload.len().saturating_sub(4)
        );

        self.robot.set_telemetry_enabled(*telemetry_enabled);
        let output = self.robot.handle_frame(payload, self.now_ms());
        *telemetry_enabled = self.robot.telemetry_enabled();

        if output
            .events
            .iter()
            .any(|event| matches!(event, ProtocolEvent::Drive(_)))
        {
            log::info!("runtime drive output: {:?}", self.robot.drive_output());
        }
        output.response
    }

    pub(crate) fn arm_state_frame(&self) -> Vec<u8> {
        self.robot.arm_state_frame()
    }
}
