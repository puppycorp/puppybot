use std::{
    future::Future,
    net::TcpListener,
    sync::Arc as StdArc,
    sync::{Arc, Mutex},
    task::{Context, Poll, Wake, Waker},
    thread,
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

#[derive(Debug, Default, PartialEq, Eq)]
struct RuntimeArgs {
    servo_device: Option<String>,
}

#[derive(Debug, PartialEq, Eq)]
enum RuntimeCli {
    Run(RuntimeArgs),
    Help,
}

pub(crate) struct RuntimeRobot {
    robot: Puppybot,
    servo: Option<stservo::RuntimeStServo>,
    started_at: Instant,
    last_tick_at: Instant,
    telemetry_seq: u32,
}

struct ThreadWaker(thread::Thread);

impl Wake for ThreadWaker {
    fn wake(self: StdArc<Self>) {
        self.0.unpark();
    }

    fn wake_by_ref(self: &StdArc<Self>) {
        self.0.unpark();
    }
}

fn block_on<F>(future: F) -> F::Output
where
    F: Future,
{
    let current_thread = thread::current();
    let waker = Waker::from(StdArc::new(ThreadWaker(current_thread)));
    let mut context = Context::from_waker(&waker);
    let mut future = std::pin::pin!(future);

    loop {
        match future.as_mut().poll(&mut context) {
            Poll::Ready(output) => return output,
            Poll::Pending => thread::park(),
        }
    }
}

impl RuntimeRobot {
    fn new(servo: Option<stservo::RuntimeStServo>) -> Self {
        let started_at = Instant::now();
        Self {
            robot: Puppybot::new(0),
            servo,
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
        if let Some(servo) = self.servo.as_mut() {
            block_on(self.robot.run_once(servo, now_ms, || None));
        } else {
            self.robot.tick(elapsed_ms as u64, now_ms);
        }
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

fn runtime_usage() -> &'static str {
    "Usage: puppybot-runtime [OPTIONS]\n\nOptions:\n  --servo-device <PATH>  Use an STServo serial device, overriding PUPPYBOT_STSERVO_PORT\n  -h, --help             Show this help text"
}

fn parse_runtime_args<I, S>(args: I) -> Result<RuntimeCli, String>
where
    I: IntoIterator<Item = S>,
    S: Into<String>,
{
    let mut parsed = RuntimeArgs::default();
    let mut args = args.into_iter().map(Into::into);

    while let Some(arg) = args.next() {
        match arg.as_str() {
            "-h" | "--help" => return Ok(RuntimeCli::Help),
            "--servo-device" => {
                let Some(device) = args.next() else {
                    return Err("--servo-device requires a path".to_string());
                };
                let device = device.trim();
                if device.is_empty() {
                    return Err("--servo-device requires a non-empty path".to_string());
                }
                parsed.servo_device = Some(device.to_string());
            }
            _ => {
                if let Some(device) = arg.strip_prefix("--servo-device=") {
                    let device = device.trim();
                    if device.is_empty() {
                        return Err("--servo-device requires a non-empty path".to_string());
                    }
                    parsed.servo_device = Some(device.to_string());
                } else {
                    return Err(format!("unknown option: {arg}"));
                }
            }
        }
    }

    Ok(RuntimeCli::Run(parsed))
}

fn init_logger() {
    let _ = env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("info"))
        .format_timestamp_millis()
        .try_init();
}

fn main() {
    init_logger();
    let args = match parse_runtime_args(std::env::args().skip(1)) {
        Ok(RuntimeCli::Run(args)) => args,
        Ok(RuntimeCli::Help) => {
            println!("{}", runtime_usage());
            return;
        }
        Err(err) => {
            eprintln!("{err}\n\n{}", runtime_usage());
            std::process::exit(2);
        }
    };
    let servo = stservo::open_serial(args.servo_device.as_deref());

    let bind = runtime_bind_addr();
    let listener = TcpListener::bind(&bind).expect("failed to bind runtime websocket server");
    let mdns = listener
        .local_addr()
        .ok()
        .and_then(|addr| mdns::start_advertisement(addr.port()));
    let robot = Arc::new(Mutex::new(RuntimeRobot::new(servo)));

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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn runtime_args_accept_servo_device_value() {
        assert_eq!(
            parse_runtime_args(["--servo-device", "/dev/ttyUSB0"]),
            Ok(RuntimeCli::Run(RuntimeArgs {
                servo_device: Some("/dev/ttyUSB0".to_string())
            }))
        );
    }

    #[test]
    fn runtime_args_accept_servo_device_equals_value() {
        assert_eq!(
            parse_runtime_args(["--servo-device=/dev/ttyUSB0"]),
            Ok(RuntimeCli::Run(RuntimeArgs {
                servo_device: Some("/dev/ttyUSB0".to_string())
            }))
        );
    }

    #[test]
    fn runtime_args_reject_missing_servo_device_value() {
        assert_eq!(
            parse_runtime_args(["--servo-device"]),
            Err("--servo-device requires a path".to_string())
        );
    }

    #[test]
    fn runtime_args_return_help() {
        assert_eq!(parse_runtime_args(["--help"]), Ok(RuntimeCli::Help));
    }
}
