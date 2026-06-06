use std::{
    net::TcpListener,
    sync::{Arc, Mutex},
    time::Instant,
};

use embassy_executor as _;
use puppybot_core::{
    protocol::{self, ProtocolEvent, ProtocolState},
    puppyarm::state_engine::PuppyArm,
};

mod mdns;
mod ws;

const DEFAULT_BIND: &str = "0.0.0.0:8080";

fn main() {
    init_logger();

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
    engine: PuppyArm,
    protocol: ProtocolState,
    started_at: Instant,
    last_tick_at: Instant,
    telemetry_seq: u32,
}

impl RuntimeRobot {
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

    pub(crate) fn tick(&mut self) {
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

    pub(crate) fn arm_state_frame(&self) -> Vec<u8> {
        self.engine.arm_state_frame()
    }
}
