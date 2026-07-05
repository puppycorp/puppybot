use std::{
    future::Future,
    net::{SocketAddr, TcpListener},
    path::PathBuf,
    sync::Arc as StdArc,
    sync::{Arc, Mutex},
    task::{Context, Poll, Wake, Waker},
    thread,
    time::{Duration, Instant},
};

use embassy_executor as _;
use puppybot_core::{
    config::{CoordinateCalibration, PuppybotConfigV1},
    drive::DriveActuator,
    protocol::{self, ProtocolEvent},
    puppyarm::types::{ArmCommand, ControllerError},
    robot::Puppybot,
};

mod config;
mod mdns;
mod robotdreams_drive;
mod stservo;
mod ui;
mod ws;

const DEFAULT_BIND: &str = "0.0.0.0:8080";
const DEFAULT_UI_BIND: &str = "127.0.0.1:8081";

#[derive(Debug, Default, PartialEq, Eq)]
struct RuntimeArgs {
    config: Option<String>,
    servo_device: Option<String>,
    ui_bind: Option<String>,
}

#[derive(Debug, PartialEq, Eq)]
enum RuntimeCli {
    Run(RuntimeArgs),
    Help,
}

pub(crate) struct RuntimeRobot {
    robot: Puppybot,
    servo: Option<stservo::RuntimeStServo>,
    drive_actuator: robotdreams_drive::RuntimeDriveActuator,
    config_path: PathBuf,
    active_config: PuppybotConfigV1,
    calibration_dirty: bool,
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
    fn new(
        servo: Option<stservo::RuntimeStServo>,
        config_path: PathBuf,
        config: PuppybotConfigV1,
    ) -> Self {
        let started_at = Instant::now();
        let robot = Puppybot::new_with_config(&config, 0).expect("validated runtime config");
        Self {
            robot,
            servo,
            drive_actuator: robotdreams_drive::RuntimeDriveActuator::discover(),
            config_path,
            active_config: config,
            calibration_dirty: false,
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
            block_on(self.robot.run_once_with_drive(
                servo,
                &mut self.drive_actuator,
                now_ms,
                || None,
            ));
        } else {
            self.robot.tick(elapsed_ms as u64, now_ms);
            if let Err(err) = self
                .drive_actuator
                .apply_drive_output(self.robot.drive_output())
            {
                log::warn!(
                    "set drive output {:?} failed: {}",
                    self.robot.drive_output(),
                    err
                );
            }
        }
        self.telemetry_seq = self.telemetry_seq.wrapping_add(1);
    }

    pub(crate) fn telemetry_seq(&self) -> u32 {
        self.telemetry_seq
    }

    pub(crate) fn handle_event(&mut self, event: ProtocolEvent) {
        if let Err(err) = self.try_handle_event(event) {
            log::warn!("runtime event rejected: {:?}", err);
        }
    }

    pub(crate) fn try_handle_event(&mut self, event: ProtocolEvent) -> Result<(), ControllerError> {
        let reference_calibration = match event {
            ProtocolEvent::Arm(ArmCommand::SetJointReference {
                joint,
                tick,
                angle_rad,
            }) => Some((joint, tick, angle_rad)),
            _ => None,
        };
        let now_ms = self.now_ms();
        self.robot.try_handle_event(event, now_ms)?;
        self.sync_arm_calibration_from_robot();
        if let Some((joint, tick, angle_rad)) = reference_calibration {
            self.sync_joint_reference_calibration(joint, tick, angle_rad)?;
        }
        self.telemetry_seq = self.telemetry_seq.wrapping_add(1);
        Ok(())
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
        self.sync_arm_calibration_from_robot();
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

    pub(crate) fn arm_telemetry(&self) -> puppybot_core::puppyarm::puppyarm::PuppyarmTelemetry {
        self.robot.arm_telemetry()
    }

    pub(crate) fn calibration_state(&self) -> (bool, String) {
        (
            self.calibration_dirty,
            self.config_path.display().to_string(),
        )
    }

    pub(crate) fn coordinate_calibration(&self) -> CoordinateCalibration {
        self.active_config.coordinate
    }

    pub(crate) fn flip_coordinate_forward_sign(&mut self) -> i8 {
        self.active_config.coordinate.forward_sign = -self.active_config.coordinate.forward_sign;
        self.calibration_dirty = true;
        self.active_config.coordinate.forward_sign
    }

    pub(crate) fn flip_coordinate_left_sign(&mut self) -> i8 {
        self.active_config.coordinate.left_sign = -self.active_config.coordinate.left_sign;
        self.calibration_dirty = true;
        self.active_config.coordinate.left_sign
    }

    pub(crate) fn rotate_coordinate_base_yaw_offset_deg(&mut self) -> f64 {
        let offset = (self.active_config.coordinate.base_yaw_offset_deg + 90.0).rem_euclid(360.0);
        self.active_config.coordinate.base_yaw_offset_deg =
            if offset == 360.0 { 0.0 } else { offset };
        self.calibration_dirty = true;
        self.active_config.coordinate.base_yaw_offset_deg
    }

    pub(crate) fn save_calibration(&mut self) -> Result<String, String> {
        self.sync_arm_calibration_from_robot();
        config::save_runtime_config(&self.config_path, &self.active_config)?;
        self.calibration_dirty = false;
        Ok(self.config_path.display().to_string())
    }

    pub(crate) fn config_json(&mut self) -> Result<String, String> {
        self.sync_arm_calibration_from_robot();
        config::runtime_config_state_json(
            &self.config_path.display().to_string(),
            self.calibration_dirty,
            &self.active_config,
        )
    }

    fn sync_arm_calibration_from_robot(&mut self) {
        let telemetry = self.robot.arm_telemetry();
        let mut changed = false;
        for (index, joint) in telemetry.joints.iter().enumerate() {
            let config_joint = &mut self.active_config.arm.joints[index];
            if config_joint.servo_id != joint.servo_id {
                config_joint.servo_id = joint.servo_id;
                changed = true;
            }
            if config_joint.tick_min != joint.limit_min {
                config_joint.tick_min = joint.limit_min;
                changed = true;
            }
            if config_joint.tick_max != joint.limit_max {
                config_joint.tick_max = joint.limit_max;
                changed = true;
            }
            if config_joint.limit_enabled != joint.limit_enabled {
                config_joint.limit_enabled = joint.limit_enabled;
                changed = true;
            }
            if config_joint.reference_tick != joint.reference_tick {
                config_joint.reference_tick = joint.reference_tick;
                changed = true;
            }
            if config_joint.reference_angle_rad != joint.reference_angle_rad {
                config_joint.reference_angle_rad = joint.reference_angle_rad;
                changed = true;
            }
        }
        if changed {
            self.calibration_dirty = true;
        }
    }

    pub(crate) fn joint_angle_sign(&self, joint: usize) -> Option<i8> {
        self.active_config
            .arm
            .joints
            .get(joint)
            .map(|joint| joint.angle_sign)
    }

    pub(crate) fn flip_joint_angle_sign(&mut self, joint: usize) -> Result<i8, String> {
        if joint >= self.active_config.arm.joints.len() {
            return Err("invalid joint".to_string());
        }

        self.sync_arm_calibration_from_robot();
        let new_sign = {
            let config_joint = &mut self.active_config.arm.joints[joint];
            config_joint.angle_sign = -config_joint.angle_sign;
            config_joint.angle_sign
        };
        let now_ms = self.now_ms();
        self.robot = Puppybot::new_with_config(&self.active_config, now_ms)
            .map_err(|err| format!("invalid calibration after sign flip: {err}"))?;
        self.calibration_dirty = true;
        Ok(new_sign)
    }

    fn sync_joint_reference_calibration(
        &mut self,
        joint: usize,
        tick: i32,
        angle_rad: f64,
    ) -> Result<(), ControllerError> {
        if joint >= self.active_config.arm.joints.len() {
            return Err(ControllerError::InvalidJoint);
        }

        let config_joint = &mut self.active_config.arm.joints[joint];
        if config_joint.reference_tick != tick || config_joint.reference_angle_rad != angle_rad {
            config_joint.reference_tick = tick;
            config_joint.reference_angle_rad = angle_rad;
            self.calibration_dirty = true;
        }
        Ok(())
    }
}

fn start_robot_tick_loop(robot: Arc<Mutex<RuntimeRobot>>) -> thread::JoinHandle<()> {
    thread::spawn(move || {
        loop {
            {
                let mut robot = robot.lock().unwrap();
                robot.tick();
            }
            thread::sleep(Duration::from_millis(20));
        }
    })
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

fn runtime_ui_bind_addr(value: Option<&str>) -> Result<SocketAddr, String> {
    let bind = match value {
        Some(value) => value.to_string(),
        None => std::env::var("PUPPYBOT_RUNTIME_UI_ADDR")
            .unwrap_or_else(|_| DEFAULT_UI_BIND.to_string()),
    };
    bind.parse::<SocketAddr>()
        .map_err(|err| format!("invalid runtime UI bind address '{bind}': {err}"))
}

fn runtime_usage() -> &'static str {
    "Usage: puppybot-runtime [OPTIONS]\n\nOptions:\n  --config <PATH>        Load runtime config JSON, default ./puppybot.json\n  --servo-device <PATH>  Use an STServo serial device, overriding PUPPYBOT_STSERVO_PORT\n  --ui-bind <ADDR>       Bind the WGUI dashboard, default 127.0.0.1:8081\n  -h, --help             Show this help text"
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
            "--config" => {
                let Some(path) = args.next() else {
                    return Err("--config requires a path".to_string());
                };
                let path = path.trim();
                if path.is_empty() {
                    return Err("--config requires a non-empty path".to_string());
                }
                parsed.config = Some(path.to_string());
            }
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
            "--ui-bind" => {
                let Some(bind) = args.next() else {
                    return Err("--ui-bind requires host:port".to_string());
                };
                let bind = bind.trim();
                if bind.is_empty() {
                    return Err("--ui-bind requires a non-empty host:port".to_string());
                }
                parsed.ui_bind = Some(bind.to_string());
            }
            _ => {
                if let Some(path) = arg.strip_prefix("--config=") {
                    let path = path.trim();
                    if path.is_empty() {
                        return Err("--config requires a non-empty path".to_string());
                    }
                    parsed.config = Some(path.to_string());
                } else if let Some(device) = arg.strip_prefix("--servo-device=") {
                    let device = device.trim();
                    if device.is_empty() {
                        return Err("--servo-device requires a non-empty path".to_string());
                    }
                    parsed.servo_device = Some(device.to_string());
                } else if let Some(bind) = arg.strip_prefix("--ui-bind=") {
                    let bind = bind.trim();
                    if bind.is_empty() {
                        return Err("--ui-bind requires a non-empty host:port".to_string());
                    }
                    parsed.ui_bind = Some(bind.to_string());
                } else {
                    return Err(format!("unknown option: {arg}"));
                }
            }
        }
    }

    Ok(RuntimeCli::Run(parsed))
}

fn runtime_ui_config(
    ws_bind: String,
    ws_url: String,
    ui_bind: SocketAddr,
    servo_hardware: bool,
    servo_device: Option<&str>,
) -> ui::RuntimeUiConfig {
    let servo_status = if servo_hardware {
        "hardware"
    } else {
        "simulated"
    };
    let servo_detail = match (servo_hardware, servo_device) {
        (true, Some(device)) => format!("using STServo device {device}"),
        (true, None) => {
            "opened from PUPPYBOT_STSERVO_PORT, remembered port, or auto-detect".to_string()
        }
        (false, Some(device)) => format!("could not open {device}; using simulated state"),
        (false, None) => {
            "no STServo device open; pass --servo-device or set PUPPYBOT_STSERVO_PORT".to_string()
        }
    };

    ui::RuntimeUiConfig {
        ws_bind,
        ws_url,
        ui_bind: ui_bind.to_string(),
        ui_url: ui::local_url(ui_bind, "http", "/"),
        servo_status: servo_status.to_string(),
        servo_detail,
    }
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
    let ui_bind = match runtime_ui_bind_addr(args.ui_bind.as_deref()) {
        Ok(bind) => bind,
        Err(err) => {
            eprintln!("{err}\n\n{}", runtime_usage());
            std::process::exit(2);
        }
    };
    let servo = stservo::open_serial(args.servo_device.as_deref());
    let servo_hardware = servo.is_some();
    let config_path = config::runtime_config_path(args.config.as_deref());
    let runtime_config = match config::load_runtime_config(&config_path) {
        Ok(config) => config,
        Err(err) => {
            eprintln!("{err}");
            std::process::exit(2);
        }
    };
    if runtime_config.is_some() {
        log::info!("loaded runtime config from {}", config_path.display());
    } else {
        log::info!(
            "runtime config {} not found; using built-in defaults",
            config_path.display()
        );
    }

    let bind = runtime_bind_addr();
    let listener = TcpListener::bind(&bind).expect("failed to bind runtime websocket server");
    let ws_url = listener
        .local_addr()
        .map(|addr| ui::local_url(addr, "ws", "/ws"))
        .unwrap_or_else(|_| format!("ws://{bind}/ws"));
    let logged_ws_url = ws_url.clone();
    let ui_config = runtime_ui_config(
        bind.clone(),
        ws_url,
        ui_bind,
        servo_hardware,
        args.servo_device.as_deref(),
    );
    let ui_url = ui_config.ui_url.clone();
    let mdns = listener
        .local_addr()
        .ok()
        .and_then(|addr| mdns::start_advertisement(addr.port()));
    let robot_config = runtime_config.unwrap_or_default();
    let robot = Arc::new(Mutex::new(RuntimeRobot::new(
        servo,
        config_path,
        robot_config,
    )));
    let _robot_tick = start_robot_tick_loop(Arc::clone(&robot));
    let _ui = ui::start_runtime_ui(ui_bind, ui_config, Arc::clone(&robot));

    log::info!("puppybot runtime listening on {logged_ws_url}");
    log::info!("puppybot runtime UI listening on {ui_url}");
    log::info!("set PUPPYBOT_RUNTIME_ADDR=127.0.0.1:8080 to bind another address");

    let _mdns = mdns;
    for incoming in listener.incoming() {
        match incoming {
            Ok(stream) => {
                let robot = Arc::clone(&robot);
                std::thread::spawn(move || {
                    if let Err(err) = ws::handle_connection(stream, robot) {
                        if matches!(err, ws::Error::Closed) {
                            log::info!("runtime websocket connection closed");
                        } else {
                            log::warn!("runtime websocket connection ended: {err}");
                        }
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
    use puppybot_core::puppyarm::types::ArmCommand;

    #[test]
    fn runtime_args_accept_servo_device_value() {
        assert_eq!(
            parse_runtime_args(["--servo-device", "/dev/ttyUSB0"]),
            Ok(RuntimeCli::Run(RuntimeArgs {
                config: None,
                servo_device: Some("/dev/ttyUSB0".to_string()),
                ui_bind: None
            }))
        );
    }

    #[test]
    fn runtime_args_accept_servo_device_equals_value() {
        assert_eq!(
            parse_runtime_args(["--servo-device=/dev/ttyUSB0"]),
            Ok(RuntimeCli::Run(RuntimeArgs {
                config: None,
                servo_device: Some("/dev/ttyUSB0".to_string()),
                ui_bind: None
            }))
        );
    }

    #[test]
    fn runtime_args_accept_ui_bind_value() {
        assert_eq!(
            parse_runtime_args(["--ui-bind", "127.0.0.1:9000"]),
            Ok(RuntimeCli::Run(RuntimeArgs {
                config: None,
                servo_device: None,
                ui_bind: Some("127.0.0.1:9000".to_string())
            }))
        );
    }

    #[test]
    fn runtime_args_accept_ui_bind_equals_value() {
        assert_eq!(
            parse_runtime_args(["--ui-bind=127.0.0.1:9000"]),
            Ok(RuntimeCli::Run(RuntimeArgs {
                config: None,
                servo_device: None,
                ui_bind: Some("127.0.0.1:9000".to_string())
            }))
        );
    }

    #[test]
    fn runtime_args_accept_config_value() {
        assert_eq!(
            parse_runtime_args(["--config", "puppybot.json"]),
            Ok(RuntimeCli::Run(RuntimeArgs {
                config: Some("puppybot.json".to_string()),
                servo_device: None,
                ui_bind: None
            }))
        );
    }

    #[test]
    fn runtime_args_accept_config_equals_value() {
        assert_eq!(
            parse_runtime_args(["--config=puppybot.json"]),
            Ok(RuntimeCli::Run(RuntimeArgs {
                config: Some("puppybot.json".to_string()),
                servo_device: None,
                ui_bind: None
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
    fn runtime_args_reject_missing_config_value() {
        assert_eq!(
            parse_runtime_args(["--config"]),
            Err("--config requires a path".to_string())
        );
    }

    #[test]
    fn runtime_args_return_help() {
        assert_eq!(parse_runtime_args(["--help"]), Ok(RuntimeCli::Help));
    }

    #[test]
    fn runtime_ui_bind_addr_rejects_invalid_value() {
        assert_eq!(
            runtime_ui_bind_addr(Some("wat")).unwrap_err(),
            "invalid runtime UI bind address 'wat': invalid socket address syntax"
        );
    }

    #[test]
    fn runtime_robot_saves_adjusted_joint_limits() {
        let path = std::env::temp_dir().join(format!(
            "runtime-robot-save-calibration-{}.json",
            std::process::id()
        ));
        let _ = std::fs::remove_file(&path);

        let mut robot = RuntimeRobot::new(None, path.clone(), PuppybotConfigV1::default());
        robot.handle_event(ProtocolEvent::Arm(ArmCommand::SetTickLimits {
            joint: 0,
            min: 10,
            max: 120,
        }));

        assert!(robot.calibration_state().0);

        robot.save_calibration().unwrap();

        let saved = config::load_runtime_config(&path).unwrap().unwrap();
        assert_eq!(saved.arm.joints[0].tick_min, 10);
        assert_eq!(saved.arm.joints[0].tick_max, 120);
        assert!(!robot.calibration_state().0);

        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn runtime_robot_saves_joint_reference_calibration() {
        let path = std::env::temp_dir().join(format!(
            "runtime-robot-save-joint-reference-{}.json",
            std::process::id()
        ));
        let _ = std::fs::remove_file(&path);

        let reference_angle_rad = 12.5_f64.to_radians();
        let mut robot = RuntimeRobot::new(None, path.clone(), PuppybotConfigV1::default());
        let result = robot.try_handle_event(ProtocolEvent::Arm(ArmCommand::SetJointReference {
            joint: 1,
            tick: 700,
            angle_rad: reference_angle_rad,
        }));

        assert_eq!(result, Ok(()));
        assert!(robot.calibration_state().0);

        robot.save_calibration().unwrap();

        let saved = config::load_runtime_config(&path).unwrap().unwrap();
        assert_eq!(saved.arm.joints[1].reference_tick, 700);
        assert_eq!(saved.arm.joints[1].reference_angle_rad, reference_angle_rad);
        assert!(!robot.calibration_state().0);

        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn runtime_robot_saves_flipped_joint_angle_sign() {
        let path = std::env::temp_dir().join(format!(
            "runtime-robot-save-joint-angle-sign-{}.json",
            std::process::id()
        ));
        let _ = std::fs::remove_file(&path);

        let mut robot = RuntimeRobot::new(None, path.clone(), PuppybotConfigV1::default());

        assert_eq!(robot.joint_angle_sign(3), Some(1));

        let sign = robot.flip_joint_angle_sign(3).unwrap();

        assert_eq!(sign, -1);
        assert_eq!(robot.joint_angle_sign(3), Some(-1));
        assert!(robot.calibration_state().0);

        robot.save_calibration().unwrap();

        let saved = config::load_runtime_config(&path).unwrap().unwrap();
        assert_eq!(saved.arm.joints[3].angle_sign, -1);
        assert!(!robot.calibration_state().0);

        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn runtime_robot_saves_flipped_coordinate_forward_sign() {
        let path = std::env::temp_dir().join(format!(
            "runtime-robot-save-coordinate-sign-{}.json",
            std::process::id()
        ));
        let _ = std::fs::remove_file(&path);

        let mut robot = RuntimeRobot::new(None, path.clone(), PuppybotConfigV1::default());

        assert_eq!(robot.coordinate_calibration().forward_sign, 1);

        let sign = robot.flip_coordinate_forward_sign();

        assert_eq!(sign, -1);
        assert_eq!(robot.coordinate_calibration().forward_sign, -1);
        assert!(robot.calibration_state().0);

        robot.save_calibration().unwrap();

        let saved = config::load_runtime_config(&path).unwrap().unwrap();
        assert_eq!(saved.coordinate.forward_sign, -1);
        assert!(!robot.calibration_state().0);

        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn runtime_robot_saves_rotated_coordinate_base_yaw_offset() {
        let path = std::env::temp_dir().join(format!(
            "runtime-robot-save-coordinate-rotation-{}.json",
            std::process::id()
        ));
        let _ = std::fs::remove_file(&path);

        let mut robot = RuntimeRobot::new(None, path.clone(), PuppybotConfigV1::default());

        assert_eq!(robot.coordinate_calibration().base_yaw_offset_deg, 0.0);

        let offset = robot.rotate_coordinate_base_yaw_offset_deg();

        assert_eq!(offset, 90.0);
        assert_eq!(robot.coordinate_calibration().base_yaw_offset_deg, 90.0);
        assert!(robot.calibration_state().0);

        robot.save_calibration().unwrap();

        let saved = config::load_runtime_config(&path).unwrap().unwrap();
        assert_eq!(saved.coordinate.base_yaw_offset_deg, 90.0);
        assert!(!robot.calibration_state().0);

        let _ = std::fs::remove_file(&path);
    }
}
