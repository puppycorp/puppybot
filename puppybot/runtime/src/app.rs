use std::{
    collections::{HashMap, HashSet},
    net::{IpAddr, SocketAddr},
    path::PathBuf,
    sync::Arc,
    time::{Duration, Instant},
};

use puppybot_core::{
    config::{CoordinateCalibration, PuppybotConfigV1},
    drive::DriveCommand,
    protocol::{self, ProtocolEvent, ProtocolOutput},
    puppyarm::{
        kinematics::{self, IkError},
        servo_safety::TICK_WRAP,
        types::{ArmCommand, ArmMode, ControllerError, JOINT_COUNT, Joint, TcpFrame},
    },
    robot::Puppybot,
};
use tokio::time::{self, MissedTickBehavior};
use wgui::{
    ClientEvent, ClientMessage, Item, Wgui, button, hstack, modal, text, text_input, vstack,
};

use crate::{
    capture::{CaptureFailure, CaptureManager},
    config,
    dc_motor_driver::DCMotorDriver,
    env::wgui_bind_addr,
    http, mdns,
    sim::{CaptureCameraView, SimulatedPreview, SimulatedRuntimeBackend, TcpCameraJogDirection},
    stservo::{self, RuntimeStServo},
};

const RUNTIME_UI_CSS: &str = include_str!("../wui/runtime.css");
const DEFAULT_WS_BIND: &str = "0.0.0.0:8080";
const ROBOT_TICK_MS: u64 = 20;
const UI_RENDER_INTERVAL_MS: u64 = 100;
const HELD_DRIVE_REFRESH_MS: u64 = 200;
const HELD_JOINT_JOG_REFRESH_MS: u64 = 200;
const DEFAULT_ARM_SPEED: i16 = 220;
const UI_DRIVE_SPEED: i8 = 35;
const UI_STEER_SPEED: i8 = 55;
const UI_LIMIT_STEP_TICKS: i32 = 10;
const DEFAULT_GOTO_ANGLE_DEG: f64 = 90.0;
const ARM_JOINT_LABELS: [&str; JOINT_COUNT] = ["Yaw", "Shoulder", "Elbow", "Wrist"];

const SAVE_CALIBRATION_ID: u32 = 100;
const DRIVE_FORWARD_ID: u32 = 110;
const DRIVE_BACK_ID: u32 = 111;
const DRIVE_LEFT_ID: u32 = 112;
const DRIVE_RIGHT_ID: u32 = 113;
const DRIVE_STOP_ID: u32 = 114;

const OPEN_JOINT_CALIBRATION_ID: u32 = 200;
const CLOSE_JOINT_CALIBRATION_ID: u32 = 201;
const EDIT_JOINT_REFERENCE_ANGLE_ID: u32 = 202;
const APPLY_JOINT_CALIBRATION_ID: u32 = 203;
const FLIP_JOINT_ANGLE_SIGN_ID: u32 = 204;
const SET_JOINT_ZERO_ID: u32 = 205;
const JOG_NEGATIVE_ID: u32 = 206;
const JOG_POSITIVE_ID: u32 = 207;
const JOG_STOP_ID: u32 = 208;
const STOP_JOINT_ID: u32 = 209;

const EDIT_GOTO_ANGLE_YAW_ID: u32 = 300;
const EDIT_GOTO_ANGLE_SHOULDER_ID: u32 = 301;
const EDIT_GOTO_ANGLE_ELBOW_ID: u32 = 302;
const EDIT_GOTO_ANGLE_WRIST_ID: u32 = 303;
const SET_GOTO_ANGLES_CURRENT_ID: u32 = 304;
const GOTO_DEFAULT_ANGLES_ID: u32 = 305;
const GOTO_ANGLES_ID: u32 = 306;

const SET_TCP_FRAME_BASE_ID: u32 = 400;
const SET_TCP_FRAME_TOOL_ID: u32 = 401;
const EDIT_ARM_SPEED_ID: u32 = 402;
const MOVE_TCP_FORWARD_ID: u32 = 403;
const MOVE_TCP_BACK_ID: u32 = 404;
const MOVE_TCP_LEFT_ID: u32 = 405;
const MOVE_TCP_RIGHT_ID: u32 = 406;
const MOVE_TCP_STOP_ID: u32 = 407;
const SET_ARM_SPEED_ID: u32 = 408;
const MOVE_TCP_CAMERA_FORWARD_ID: u32 = 409;
const MOVE_TCP_CAMERA_BACK_ID: u32 = 410;
const MOVE_TCP_CAMERA_LEFT_ID: u32 = 411;
const MOVE_TCP_CAMERA_RIGHT_ID: u32 = 412;
const MOVE_TCP_CAMERA_UP_ID: u32 = 413;
const MOVE_TCP_CAMERA_DOWN_ID: u32 = 414;

const EDIT_COORDINATE_X_ID: u32 = 500;
const EDIT_COORDINATE_Y_ID: u32 = 501;
const EDIT_COORDINATE_Z_ID: u32 = 502;
const SET_COORDINATES_CURRENT_ID: u32 = 503;
const MOVE_TO_COORDINATES_ID: u32 = 504;
const FLIP_COORDINATE_FORWARD_AXIS_ID: u32 = 507;
const FLIP_COORDINATE_LEFT_AXIS_ID: u32 = 508;
const ROTATE_COORDINATE_BASE_FRAME_ID: u32 = 509;
const COORDINATE_FORWARD_ID: u32 = 510;
const COORDINATE_BACK_ID: u32 = 511;
const COORDINATE_LEFT_ID: u32 = 512;
const COORDINATE_RIGHT_ID: u32 = 513;
const COORDINATE_UP_ID: u32 = 514;
const COORDINATE_DOWN_ID: u32 = 515;
const PREVIEW_COORDINATES_ID: u32 = 516;
const CLOSE_COORDINATE_PREVIEW_ID: u32 = 517;

const ARM_HOLD_ID: u32 = 600;
const ARM_STOP_ALL_ID: u32 = 601;
const CLEAR_ARM_FAULTS_ID: u32 = 602;

const OPEN_LIMIT_EDITOR_ID: u32 = 700;
const CLOSE_LIMIT_EDITOR_ID: u32 = 701;
const EDIT_LIMIT_MIN_ID: u32 = 702;
const EDIT_LIMIT_MAX_ID: u32 = 703;
const LIMIT_MIN_DOWN_ID: u32 = 704;
const LIMIT_MIN_UP_ID: u32 = 705;
const LIMIT_MAX_DOWN_ID: u32 = 706;
const LIMIT_MAX_UP_ID: u32 = 707;
const SET_LIMIT_MIN_CURRENT_ID: u32 = 708;
const SET_LIMIT_MAX_CURRENT_ID: u32 = 709;
const TOGGLE_JOINT_LIMITS_ID: u32 = 710;
const APPLY_LIMIT_EDITOR_ID: u32 = 711;

fn event_arg(inx: Option<u32>) -> u32 {
    inx.unwrap_or(0)
}

fn ws_bind_addr() -> Result<SocketAddr, String> {
    let bind = match std::env::var("PUPPYBOT_RUNTIME_ADDR") {
        Ok(bind) => bind,
        Err(_) => match std::env::var("PUPPYBOT_HOST_ADDR") {
            Ok(bind) => {
                log::warn!("PUPPYBOT_HOST_ADDR is deprecated; use PUPPYBOT_RUNTIME_ADDR");
                bind
            }
            Err(_) => DEFAULT_WS_BIND.to_string(),
        },
    };

    bind.parse::<SocketAddr>()
        .map_err(|err| format!("invalid runtime websocket bind address '{bind}': {err}"))
}

#[derive(Debug, Default, Clone)]
pub(crate) struct AppOptions {
    pub(crate) config: Option<String>,
    pub(crate) servo_device: Option<String>,
    pub(crate) simulated: bool,
    pub(crate) robotdreams_project: Option<PathBuf>,
    pub(crate) ui_bind: Option<SocketAddr>,
    pub(crate) ws_bind: Option<SocketAddr>,
}

#[derive(Clone, Copy, Debug)]
struct HeldDrive {
    command: DriveCommand,
    last_refresh_ms: u64,
}

#[derive(Clone, Copy, Debug)]
struct HeldJointJog {
    joint: usize,
    direction: i8,
    last_refresh_ms: u64,
}

#[derive(Clone, Copy, Debug)]
struct HeldTcpJog {
    frame: TcpFrame,
    direction: [f64; 3],
    last_refresh_ms: u64,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
struct KeyboardDriveState {
    up: bool,
    down: bool,
    left: bool,
    right: bool,
}

pub(crate) struct ApiResponse {
    status: &'static str,
    content_type: &'static str,
    body: Arc<[u8]>,
}

struct ApiError {
    status: &'static str,
    message: String,
}

impl ApiError {
    fn bad_request(message: impl Into<String>) -> Self {
        Self {
            status: "400 Bad Request",
            message: message.into(),
        }
    }

    fn not_found(message: impl Into<String>) -> Self {
        Self {
            status: "404 Not Found",
            message: message.into(),
        }
    }

    fn method_not_allowed(message: impl Into<String>) -> Self {
        Self {
            status: "405 Method Not Allowed",
            message: message.into(),
        }
    }

    fn internal(message: impl Into<String>) -> Self {
        Self {
            status: "500 Internal Server Error",
            message: message.into(),
        }
    }

    fn conflict(message: impl Into<String>) -> Self {
        Self {
            status: "409 Conflict",
            message: message.into(),
        }
    }
}

fn api_capture_failure(error: CaptureFailure) -> ApiError {
    ApiError {
        status: error.status,
        message: error.message,
    }
}

impl KeyboardDriveState {
    fn set_key(&mut self, keycode: &str, pressed: bool) -> bool {
        match keycode {
            "ArrowUp" => self.up = pressed,
            "ArrowDown" => self.down = pressed,
            "ArrowLeft" => self.left = pressed,
            "ArrowRight" => self.right = pressed,
            _ => return false,
        }
        true
    }

    fn command(self) -> Option<DriveCommand> {
        let throttle = match (self.up, self.down) {
            (true, false) => UI_DRIVE_SPEED,
            (false, true) => -UI_DRIVE_SPEED,
            _ => 0,
        };
        let steering = match (self.left, self.right) {
            (true, false) => -UI_STEER_SPEED,
            (false, true) => UI_STEER_SPEED,
            _ => 0,
        };
        (throttle != 0 || steering != 0).then_some(DriveCommand::DriveSteer { throttle, steering })
    }
}

fn ui_host(addr: SocketAddr) -> String {
    let host = match addr.ip() {
        IpAddr::V4(ip) if ip.is_unspecified() => "127.0.0.1".to_string(),
        IpAddr::V6(ip) if ip.is_unspecified() => "::1".to_string(),
        _ => addr.ip().to_string(),
    };

    if host.contains(':') {
        format!("[{host}]")
    } else {
        host
    }
}

fn local_url(addr: SocketAddr, scheme: &str, path: &str) -> String {
    format!("{scheme}://{}:{}{path}", ui_host(addr), addr.port())
}

fn handle_binary_command_for_robot(
    robot: &mut Puppybot,
    payload: &[u8],
    now_ms: u64,
    telemetry_enabled: &mut bool,
) -> ProtocolOutput {
    if payload.len() < 4 {
        log::warn!("ignoring short runtime App WS frame len={}", payload.len());
        return ProtocolOutput::default();
    }

    let version = payload[0];
    let cmd = payload[1];
    let payload_len = u16::from_le_bytes([payload[2], payload[3]]) as usize;
    log::info!(
        "runtime App WS command {} version={} declared_len={} actual_len={}",
        protocol::command_name(cmd),
        version,
        payload_len,
        payload.len().saturating_sub(4)
    );

    robot.set_telemetry_enabled(*telemetry_enabled);
    let output = robot.handle_frame(payload, now_ms);
    *telemetry_enabled = robot.telemetry_enabled();
    output
}

struct UiMetric {
    label: String,
    value: String,
    detail: String,
    accent: &'static str,
    save_action: bool,
}

struct UiLimit {
    label: String,
    detail: String,
    toggle_label: &'static str,
    accent: &'static str,
    background: &'static str,
    border: &'static str,
}

fn title_text(value: &str) -> Item {
    text(value).color("#f4f7fb")
}

fn label_text(value: &str) -> Item {
    text(value).color("#91a0b3")
}

fn body_text(value: &str) -> Item {
    text(value).color("#d4dce8").break_words(true)
}

fn error_text(value: &str) -> Item {
    text(value).color("#ffb8b8").break_words(true)
}

fn panel(children: Vec<Item>) -> Item {
    vstack(children)
        .background_color("#18202b")
        .border("1px solid #2b394a")
        .padding(14)
        .spacing(10)
}

fn subpanel(children: Vec<Item>) -> Item {
    vstack(children)
        .background_color("#121923")
        .border("1px solid #263548")
        .padding(10)
        .spacing(8)
}

fn styled_button(title: &str, background: &str, border: &str, color: &str, height: u32) -> Item {
    button(title)
        .background_color(background)
        .border(border)
        .color(color)
        .height(height)
}

fn primary_button(title: &str) -> Item {
    styled_button(title, "#1e5f9f", "1px solid #4d8dff", "#f4f7fb", 34)
}

fn secondary_button(title: &str) -> Item {
    styled_button(title, "#29323f", "1px solid #415066", "#f4f7fb", 34)
}

fn dark_button(title: &str) -> Item {
    styled_button(title, "#182838", "1px solid #314154", "#f4f7fb", 34)
}

fn danger_button(title: &str) -> Item {
    styled_button(title, "#9f2f2f", "1px solid #d85b5b", "#fff4f4", 34)
}

fn input(id: u32, value: &str, placeholder: &str) -> Item {
    text_input().id(id).svalue(value).placeholder(placeholder)
}

fn field(label: &str, id: u32, value: &str, placeholder: &str, width: u32) -> Item {
    vstack(vec![label_text(label), input(id, value, placeholder)])
        .width(width)
        .spacing(4)
}

fn frame_button(label: &str, selected: bool, id: u32, width: u32) -> Item {
    let button = if selected {
        styled_button(label, "#1e5f9f", "1px solid #4d8dff", "#f4f7fb", 30)
    } else {
        styled_button(label, "#182838", "1px solid #314154", "#b6c2d2", 30)
    };
    button.width(width).on_click(id)
}

fn angle_detail(joint: &Joint) -> String {
    match joint.angle_deg() {
        Some(angle) => format!("angle {angle:.1} deg"),
        None => "angle -- deg".to_string(),
    }
}

fn opt_tick(value: Option<i32>) -> String {
    match value {
        Some(tick) => tick.to_string(),
        None => "—".to_string(),
    }
}

fn opt_deg(value: Option<f32>) -> String {
    match value {
        Some(deg) => format!("{deg:.1}"),
        None => "—".to_string(),
    }
}

fn close_preview_button() -> Item {
    hstack(vec![
        primary_button("Close").on_click(CLOSE_COORDINATE_PREVIEW_ID),
    ])
    .spacing(8)
}

fn preview_modal(body: Vec<Item>) -> Option<Item> {
    Some(
        modal(vec![
            vstack(body)
                .width(420)
                .max_width(420)
                .background_color("#18202b")
                .border("1px solid #415066")
                .padding(16)
                .spacing(12),
        ])
        .id(CLOSE_COORDINATE_PREVIEW_ID),
    )
}

fn limit_detail(joint: &Joint) -> String {
    match joint.tick {
        Some(tick) => format!("tick {tick} / {}..{}", joint.limit_min, joint.limit_max),
        None => format!("limits {}..{}", joint.limit_min, joint.limit_max),
    }
}

fn limit_status(joint: &Joint) -> UiLimit {
    if !joint.limit_enabled {
        return UiLimit {
            label: "Limits off".to_string(),
            detail: limit_detail(joint),
            toggle_label: "Enable",
            accent: "#8ea0b7",
            background: "#202936",
            border: "1px solid #415066",
        };
    }

    if !joint.has_feedback {
        return UiLimit {
            label: "No feedback".to_string(),
            detail: "waiting for servo position".to_string(),
            toggle_label: "Disable",
            accent: "#8ea0b7",
            background: "#202936",
            border: "1px solid #415066",
        };
    }

    if joint.limit_reached {
        return UiLimit {
            label: "LIMIT".to_string(),
            detail: limit_detail(joint),
            toggle_label: "Disable",
            accent: "#ffb8b8",
            background: "#7f2525",
            border: "1px solid #d85b5b",
        };
    }

    UiLimit {
        label: "OK".to_string(),
        detail: limit_detail(joint),
        toggle_label: "Disable",
        accent: "#bff0cf",
        background: "#1d5034",
        border: "1px solid #3fbf6f",
    }
}

fn joint_reference_tick_error(joint: &Joint) -> Option<String> {
    let tick = joint.tick?;
    if !(0..TICK_WRAP).contains(&tick) {
        Some(format!(
            "current tick {tick} is outside servo range 0..{}",
            TICK_WRAP - 1
        ))
    } else {
        None
    }
}

fn frame_label(frame: TcpFrame) -> &'static str {
    match frame {
        TcpFrame::Base => "Base",
        TcpFrame::YawFlat => "Yaw-flat",
        TcpFrame::Tool => "Tool",
    }
}

fn rigid_transform_json(
    transform: robotdreams_core::RigidTransform,
    from_frame: &str,
    to_frame: &str,
) -> serde_json::Value {
    serde_json::json!({
        "fromFrame": from_frame,
        "toFrame": to_frame,
        "translationM": transform.translation_m,
        "rotationMatrix": transform.rotation,
    })
}

fn frame_detail(frame: TcpFrame) -> &'static str {
    match frame {
        TcpFrame::Base => "moves along robot base axes",
        TcpFrame::YawFlat => "moves along current yaw in the horizontal plane",
        TcpFrame::Tool => "moves along current TCP/tool axes",
    }
}

fn angle_sign_label(sign: Option<i8>) -> String {
    match sign {
        Some(sign) if sign < 0 => "Angle sign: -1".to_string(),
        Some(_) => "Angle sign: +1".to_string(),
        None => "Angle sign: unavailable".to_string(),
    }
}

fn target_angle_inputs(joints: &[Joint; JOINT_COUNT]) -> Option<[String; JOINT_COUNT]> {
    let mut angles = [0.0; JOINT_COUNT];
    for (index, joint) in joints.iter().enumerate() {
        angles[index] = joint.target_angle_deg()?;
    }
    Some(std::array::from_fn(|index| format!("{:.1}", angles[index])))
}

fn format_coordinate_inputs(coords_mm: (f32, f32, f32)) -> (String, String, String) {
    (
        format!("{:.1}", coords_mm.0),
        format!("{:.1}", coords_mm.1),
        format!("{:.1}", coords_mm.2),
    )
}

fn rotate_xy_deg(x: f64, y: f64, degrees: f64) -> (f64, f64) {
    let radians = degrees.to_radians();
    let (sin, cos) = radians.sin_cos();
    (x * cos - y * sin, x * sin + y * cos)
}

fn coordinate_command(command: ArmCommand) -> bool {
    matches!(
        command,
        ArmCommand::GotoCoords { .. }
            | ArmCommand::MoveTcp { .. }
            | ArmCommand::StartTcpJog { .. }
            | ArmCommand::StartTcpJogAtSpeed { .. }
    )
}

fn goto_angles_command(command: ArmCommand) -> bool {
    matches!(command, ArmCommand::GotoAngles(_))
}

fn arm_command_error_text(command: ArmCommand, err: ControllerError) -> Option<String> {
    match (command, err) {
        (ArmCommand::GotoCoords { x, y, z, .. }, ControllerError::Ik(IkError::Unreachable)) => {
            Some(format!(
                "target unreachable: {x:.1}, {y:.1}, {:.1} mm",
                kinematics::shoulder_to_table_z(z)
            ))
        }
        (ArmCommand::MoveTcp { .. }, ControllerError::Ik(IkError::Unreachable)) => {
            Some("target unreachable from current position".to_string())
        }
        (ArmCommand::MoveTcp { .. }, ControllerError::MissingFeedback) => {
            Some("current position unavailable".to_string())
        }
        (ArmCommand::StartTcpJog { .. }, ControllerError::InvalidLimit) => {
            Some("invalid tcp jog command".to_string())
        }
        (ArmCommand::StartTcpJogAtSpeed { .. }, ControllerError::InvalidLimit) => {
            Some("invalid tcp jog command".to_string())
        }
        (ArmCommand::GotoAngles(_), ControllerError::MissingFeedback) => {
            Some("current joint feedback unavailable".to_string())
        }
        (_, ControllerError::Ik(IkError::Unreachable)) => Some("target unreachable".to_string()),
        _ => None,
    }
}

struct WsClientState {
    telemetry_enabled: bool,
    last_telemetry_seq: u32,
}

pub struct App {
    wgui: Wgui,
    ws_bind_addr: SocketAddr,
    ws_clients: HashMap<u64, WsClientState>,
    robot: Puppybot,
    backend: RuntimeBackend,
    capture_manager: CaptureManager,
    held_drive: Option<HeldDrive>,
    held_joint_jog: Option<HeldJointJog>,
    held_tcp_jog: Option<HeldTcpJog>,
    config_path: PathBuf,
    active_config: PuppybotConfigV1,
    calibration_dirty: bool,
    started_at: Instant,
    last_tick_at: Instant,
    client_ids: HashSet<usize>,
    ui_dirty: bool,
    last_render_at: Instant,
    telemetry_seq: u32,
    tcp_frame: TcpFrame,
    limit_editor_joint: Option<usize>,
    limit_editor_min: String,
    limit_editor_max: String,
    limit_editor_error: String,
    calibration_editor_joint: Option<usize>,
    calibration_editor_angle: String,
    calibration_editor_error: String,
    goto_angle_yaw: String,
    goto_angle_shoulder: String,
    goto_angle_elbow: String,
    goto_angle_wrist: String,
    goto_angle_error: String,
    arm_speed: String,
    arm_speed_error: String,
    coordinate_x: String,
    coordinate_y: String,
    coordinate_z: String,
    coordinate_error: String,
    coordinate_preview_open: bool,
    keyboard_drive: KeyboardDriveState,
    last_command: String,
}

enum RuntimeBackend {
    Hardware {
        servo: RuntimeStServo,
        dc_motor_driver: DCMotorDriver,
    },
    Simulated(SimulatedRuntimeBackend),
}

impl RuntimeBackend {
    fn is_simulated(&self) -> bool {
        matches!(self, Self::Simulated(_))
    }

    async fn run_once(&mut self, robot: &mut Puppybot, now_ms: u64) {
        match self {
            Self::Hardware {
                servo,
                dc_motor_driver,
            } => {
                robot
                    .run_once_with_drive(servo, dc_motor_driver, now_ms, || None)
                    .await;
            }
            Self::Simulated(backend) => backend.run_once(robot, now_ms).await,
        }
    }

    fn status_value(&self) -> &'static str {
        match self {
            Self::Hardware { .. } => "hardware",
            Self::Simulated(_) => "simulation",
        }
    }

    fn status_detail(&self) -> &'static str {
        match self {
            Self::Hardware { .. } => "required STServo bus is open",
            Self::Simulated(_) => "RobotDreams virtual STServo bus is in-process",
        }
    }
}

impl App {
    #[allow(dead_code)]
    pub fn new() -> Result<App, String> {
        Self::with_options(AppOptions::default())
    }

    pub(crate) fn with_options(options: AppOptions) -> Result<App, String> {
        let started_at = Instant::now();

        let config_path = config::runtime_config_path(options.config.as_deref());
        let runtime_config = config::load_runtime_config(&config_path)?;
        if runtime_config.is_some() {
            log::info!("loaded runtime config from {}", config_path.display());
        } else {
            log::info!(
                "runtime config {} not found; using built-in defaults",
                config_path.display()
            );
        }
        let active_config = runtime_config.unwrap_or_default();
        let simulation_project_path = if options.simulated {
            if options.servo_device.is_some() {
                return Err("--sim cannot be combined with --servo-device".to_string());
            }
            let project_path = options
                .robotdreams_project
                .unwrap_or_else(SimulatedRuntimeBackend::default_project_path);
            log::info!(
                "runtime using RobotDreams simulation project {}",
                project_path.display()
            );
            Some(project_path)
        } else {
            if options.robotdreams_project.is_some() {
                return Err("--robotdreams-project requires --sim".to_string());
            }
            None
        };
        let mut robot = Puppybot::new_with_config(&active_config, 0)
            .map_err(|err| format!("invalid runtime config: {err}"))?;
        robot.handle_event(
            ProtocolEvent::Arm(ArmCommand::SetSpeed(DEFAULT_ARM_SPEED)),
            0,
        );
        let backend = if let Some(project_path) = simulation_project_path {
            RuntimeBackend::Simulated(SimulatedRuntimeBackend::new(project_path, &active_config)?)
        } else {
            let servo = stservo::open_serial(options.servo_device.as_deref()).ok_or_else(|| {
                "STServo bus is required; pass --servo-device or set PUPPYBOT_STSERVO_PORT"
                    .to_string()
            })?;
            RuntimeBackend::Hardware {
                servo,
                dc_motor_driver: DCMotorDriver::discover(),
            }
        };
        let goto_angles = Self::initial_goto_angle_inputs_for_robot(&robot);
        let (coordinate_x, coordinate_y, coordinate_z) =
            Self::initial_coordinate_inputs_for_robot(&robot);
        let ui_bind = match options.ui_bind {
            Some(bind) => bind,
            None => wgui_bind_addr()?,
        };
        let ws_bind_addr = match options.ws_bind {
            Some(bind) => bind,
            None => ws_bind_addr()?,
        };
        let wgui = Wgui::new(ui_bind);
        wgui.set_css(RUNTIME_UI_CSS);

        Ok(App {
            wgui,
            ws_bind_addr,
            ws_clients: HashMap::new(),
            robot,
            backend,
            capture_manager: CaptureManager::new(),
            held_drive: None,
            held_joint_jog: None,
            held_tcp_jog: None,
            config_path,
            active_config,
            calibration_dirty: false,
            started_at,
            last_tick_at: started_at,
            client_ids: HashSet::new(),
            ui_dirty: false,
            last_render_at: started_at,
            telemetry_seq: 0,
            tcp_frame: TcpFrame::Base,
            limit_editor_joint: None,
            limit_editor_min: String::new(),
            limit_editor_max: String::new(),
            limit_editor_error: String::new(),
            calibration_editor_joint: None,
            calibration_editor_angle: String::new(),
            calibration_editor_error: String::new(),
            goto_angle_yaw: goto_angles[0].clone(),
            goto_angle_shoulder: goto_angles[1].clone(),
            goto_angle_elbow: goto_angles[2].clone(),
            goto_angle_wrist: goto_angles[3].clone(),
            goto_angle_error: String::new(),
            arm_speed: DEFAULT_ARM_SPEED.to_string(),
            arm_speed_error: String::new(),
            coordinate_x,
            coordinate_y,
            coordinate_z,
            coordinate_error: String::new(),
            coordinate_preview_open: false,
            keyboard_drive: KeyboardDriveState::default(),
            last_command: "none".to_string(),
        })
    }

    pub(crate) fn simulated_preview(&self) -> Option<SimulatedPreview> {
        match &self.backend {
            RuntimeBackend::Hardware { .. } => None,
            RuntimeBackend::Simulated(backend) => Some(backend.preview()),
        }
    }

    fn initial_goto_angle_inputs_for_robot(robot: &Puppybot) -> [String; JOINT_COUNT] {
        let joints = robot.arm.joints;
        std::array::from_fn(|index| {
            joints[index]
                .angle_deg()
                .map(|angle| format!("{angle:.1}"))
                .unwrap_or_else(|| "0.0".to_string())
        })
    }

    fn initial_coordinate_inputs_for_robot(robot: &Puppybot) -> (String, String, String) {
        robot
            .arm
            .coords_mm()
            .map(format_coordinate_inputs)
            .unwrap_or_else(|| ("200.0".to_string(), "0.0".to_string(), "80.0".to_string()))
    }

    fn now_ms(&self) -> u64 {
        self.started_at.elapsed().as_millis() as u64
    }

    async fn tick_robot(&mut self) {
        let now = Instant::now();
        let elapsed_ms = now.duration_since(self.last_tick_at).as_millis() as u64;

        if elapsed_ms == 0 {
            return;
        }

        self.last_tick_at = now;
        let now_ms = self.now_ms();
        self.refresh_held_drive(now_ms);
        self.refresh_held_joint_jog(now_ms);
        self.refresh_held_tcp_jog(now_ms);
        self.backend.run_once(&mut self.robot, now_ms).await;
        if let Some(view) = self.capture_manager.active_recording_view()
            && let Some(preview) = self.simulated_preview()
            && let Ok(state) = preview.capture_state_for_view(view)
        {
            self.capture_manager.sample_recording(state);
        }
        self.telemetry_seq = self.telemetry_seq.wrapping_add(1);
    }

    fn refresh_held_drive(&mut self, now_ms: u64) {
        let Some(held) = self.held_drive else {
            return;
        };
        if now_ms.saturating_sub(held.last_refresh_ms) < HELD_DRIVE_REFRESH_MS {
            return;
        }
        if let Err(err) = self
            .robot
            .try_handle_event(ProtocolEvent::Drive(held.command), now_ms)
        {
            log::warn!("held drive refresh rejected: {:?}", err);
            self.held_drive = None;
            return;
        }
        self.held_drive = Some(HeldDrive {
            command: held.command,
            last_refresh_ms: now_ms,
        });
    }

    fn refresh_held_joint_jog(&mut self, now_ms: u64) {
        let Some(held) = self.held_joint_jog else {
            return;
        };
        if now_ms.saturating_sub(held.last_refresh_ms) < HELD_JOINT_JOG_REFRESH_MS {
            return;
        }
        let command = ArmCommand::Spin {
            joint: held.joint,
            direction: held.direction,
        };
        if let Err(err) = self
            .robot
            .try_handle_event(ProtocolEvent::Arm(command), now_ms)
        {
            log::warn!("held joint jog refresh rejected: {:?}", err);
            self.held_joint_jog = None;
            return;
        }
        self.held_joint_jog = Some(HeldJointJog {
            joint: held.joint,
            direction: held.direction,
            last_refresh_ms: now_ms,
        });
        self.telemetry_seq = self.telemetry_seq.wrapping_add(1);
    }

    fn refresh_held_tcp_jog(&mut self, now_ms: u64) {
        let Some(held) = self.held_tcp_jog else {
            return;
        };
        if now_ms.saturating_sub(held.last_refresh_ms) < HELD_JOINT_JOG_REFRESH_MS {
            return;
        }
        let command = ArmCommand::StartTcpJog {
            frame: held.frame,
            direction: held.direction,
        };
        if let Err(err) = self
            .robot
            .try_handle_event(ProtocolEvent::Arm(command), now_ms)
        {
            log::warn!("held TCP jog refresh rejected: {:?}", err);
            self.held_tcp_jog = None;
            return;
        }
        self.held_tcp_jog = Some(HeldTcpJog {
            last_refresh_ms: now_ms,
            ..held
        });
        self.telemetry_seq = self.telemetry_seq.wrapping_add(1);
    }

    fn sync_arm_calibration_from_robot(&mut self) {
        let mut changed = false;
        for (index, joint) in self.robot.arm.joints.iter().enumerate() {
            let config_joint = &mut self.active_config.arm.joints[index];
            if config_joint.servo_id != joint.servo_id {
                config_joint.servo_id = joint.servo_id;
                changed = true;
            }
            if config_joint.tick_min != joint.tick_min {
                config_joint.tick_min = joint.tick_min;
                changed = true;
            }
            if config_joint.tick_max != joint.tick_max {
                config_joint.tick_max = joint.tick_max;
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

    pub(crate) fn config_json(&mut self) -> Result<String, String> {
        self.sync_arm_calibration_from_robot();
        config::runtime_config_state_json(
            &self.config_path.display().to_string(),
            self.calibration_dirty,
            &self.active_config,
        )
    }

    pub(crate) fn api_state_json(&self) -> Result<String, String> {
        let now_ms = self.now_ms();
        let arm = self.robot.arm_telemetry();
        let drive = self.robot.drive_output();
        let tuple_json = |value: Option<(f32, f32, f32)>| {
            value
                .map(|(x, y, z)| serde_json::json!([x, y, z]))
                .unwrap_or(serde_json::Value::Null)
        };
        let joints = arm
            .joints
            .iter()
            .enumerate()
            .map(|(index, joint)| {
                serde_json::json!({
                    "index": index,
                    "name": ARM_JOINT_LABELS[index].to_ascii_lowercase(),
                    "servoId": joint.servo_id,
                    "tick": joint.tick,
                    "targetTick": joint.target_tick,
                    "angleDeg": joint.angle_deg(),
                    "targetAngleDeg": joint.target_angle_deg(),
                    "online": joint.online,
                    "hasFeedback": joint.has_feedback,
                    "limitReached": joint.limit_reached,
                })
            })
            .collect::<Vec<_>>();
        let sim = match &self.backend {
            RuntimeBackend::Hardware { .. } => {
                serde_json::json!({
                    "enabled": false,
                    "markers": [],
                    "frames": null,
                })
            }
            RuntimeBackend::Simulated(backend) => {
                let markers = backend
                    .debug_markers(&self.robot)
                    .into_iter()
                    .map(|marker| {
                        serde_json::json!({
                            "robotId": marker.robot_id,
                            "floorZ": marker.floor_z,
                            "currentTcp": marker.current_tcp,
                            "targetTcp": marker.target_tcp,
                            "frame": "world",
                            "unit": "m",
                        })
                    })
                    .collect::<Vec<_>>();
                let frames = backend.frame_transforms().map(|frames| {
                    serde_json::json!({
                        "worldFromBase": rigid_transform_json(
                            frames.world_from_base,
                            "base",
                            "world",
                        ),
                        "baseFromArmBase": rigid_transform_json(
                            frames.base_from_arm_base,
                            "armBase",
                            "base",
                        ),
                    })
                });
                serde_json::json!({
                    "enabled": true,
                    "markers": markers,
                    "frames": frames,
                    "manipulation": backend
                        .manipulation_state()
                        .ok()
                        .and_then(|state| serde_json::to_value(state).ok()),
                    "captureState": backend
                        .preview()
                        .capture_state()
                        .ok()
                        .and_then(|state| serde_json::to_value(state.as_ref()).ok()),
                })
            }
        };
        let state = serde_json::json!({
            "schema": "puppybot.runtime.state.v1",
            "mode": self.backend.status_value(),
            "timeMs": now_ms,
            "arm": {
                "mode": format!("{:?}", self.robot.arm.mode()),
                "frame": "armBase",
                "unit": "mm",
                "currentTcpMm": tuple_json(arm.coords_mm),
                "targetTcpMm": tuple_json(arm.target_coords_mm),
                "effectiveTargetTcpMm": tuple_json(arm.effective_target_coords_mm),
                "joints": joints,
            },
            "drive": {
                "leftMotorId": drive.left_motor_id,
                "rightMotorId": drive.right_motor_id,
                "steeringServoId": drive.steering_servo_id,
                "leftSpeed": drive.left_speed,
                "rightSpeed": drive.right_speed,
                "steeringAngleDeg": drive.steering_angle_deg,
                "active": drive.active,
            },
            "sim": sim,
            "ui": {
                "coordinateFrame": "Robot Base",
                "absoluteCoordinateFrame": "Arm Base",
                "tcpFrame": frame_label(self.tcp_frame),
                "armSpeed": self.arm_speed.parse::<i16>().ok(),
                "lastCommand": self.last_command.as_str(),
            },
        });
        serde_json::to_string_pretty(&state).map_err(|err| err.to_string())
    }

    fn api_json(status: &'static str, value: serde_json::Value) -> ApiResponse {
        let body = serde_json::to_vec_pretty(&value)
            .unwrap_or_else(|_| b"{\"ok\":false,\"error\":\"json encoding failed\"}\n".to_vec());
        ApiResponse {
            status,
            content_type: "application/json; charset=utf-8",
            body: body.into(),
        }
    }

    fn api_error(error: ApiError) -> ApiResponse {
        Self::api_json(
            error.status,
            serde_json::json!({
                "ok": false,
                "error": error.message,
            }),
        )
    }

    fn api_success(&self) -> Result<ApiResponse, ApiError> {
        let state = self
            .api_state_json()
            .map_err(ApiError::internal)
            .and_then(|json| {
                serde_json::from_str::<serde_json::Value>(&json).map_err(|err| {
                    ApiError::internal(format!("state json could not be decoded: {err}"))
                })
            })?;
        Ok(Self::api_json(
            "200 OK",
            serde_json::json!({
                "ok": true,
                "state": state,
            }),
        ))
    }

    fn api_request_body(body: &[u8]) -> Result<serde_json::Value, ApiError> {
        if body.is_empty() {
            return Ok(serde_json::json!({}));
        }
        serde_json::from_slice(body)
            .map_err(|err| ApiError::bad_request(format!("invalid json: {err}")))
    }

    fn json_str<'a>(value: &'a serde_json::Value, field: &str) -> Result<&'a str, ApiError> {
        value
            .get(field)
            .and_then(|value| value.as_str())
            .ok_or_else(|| ApiError::bad_request(format!("{field} must be a string")))
    }

    fn json_f64(value: &serde_json::Value, field: &str) -> Result<f64, ApiError> {
        let number = value
            .get(field)
            .and_then(|value| value.as_f64())
            .ok_or_else(|| ApiError::bad_request(format!("{field} must be a number")))?;
        if number.is_finite() {
            Ok(number)
        } else {
            Err(ApiError::bad_request(format!("{field} must be finite")))
        }
    }

    fn json_i64(value: &serde_json::Value, field: &str) -> Result<i64, ApiError> {
        value
            .get(field)
            .and_then(|value| value.as_i64())
            .ok_or_else(|| ApiError::bad_request(format!("{field} must be an integer")))
    }

    fn json_bool(value: &serde_json::Value, field: &str) -> Result<bool, ApiError> {
        value
            .get(field)
            .and_then(|value| value.as_bool())
            .ok_or_else(|| ApiError::bad_request(format!("{field} must be a boolean")))
    }

    fn api_joint(segment: &str) -> Result<usize, ApiError> {
        let joint = segment
            .parse::<usize>()
            .map_err(|_| ApiError::bad_request("joint must be an integer"))?;
        if joint < JOINT_COUNT {
            Ok(joint)
        } else {
            Err(ApiError::bad_request(format!(
                "joint must be between 0 and {}",
                JOINT_COUNT - 1
            )))
        }
    }

    fn api_frame(value: &serde_json::Value, field: &str) -> Result<TcpFrame, ApiError> {
        match Self::json_str(value, field)? {
            "base" | "Base" | "armBase" | "Arm Base" => Ok(TcpFrame::Base),
            "tool" | "Tool" => Ok(TcpFrame::Tool),
            "yawFlat" | "yaw-flat" | "Yaw-flat" | "YawFlat" => Ok(TcpFrame::YawFlat),
            _ => Err(ApiError::bad_request(format!(
                "{field} must be base/armBase, tool, or yawFlat"
            ))),
        }
    }

    fn api_direction(direction: &str) -> Result<[f64; 3], ApiError> {
        match direction {
            "forward" => Ok([1.0, 0.0, 0.0]),
            "back" | "backward" => Ok([-1.0, 0.0, 0.0]),
            "left" => Ok([0.0, 1.0, 0.0]),
            "right" => Ok([0.0, -1.0, 0.0]),
            "up" => Ok([0.0, 0.0, 1.0]),
            "down" => Ok([0.0, 0.0, -1.0]),
            _ => Err(ApiError::bad_request(
                "direction must be forward, back, left, right, up, or down",
            )),
        }
    }

    pub(crate) fn handle_api_request(
        &mut self,
        method: &[u8],
        target: &[u8],
        body: &[u8],
    ) -> ApiResponse {
        let method = match std::str::from_utf8(method) {
            Ok(method) => method,
            Err(_) => return Self::api_error(ApiError::bad_request("method must be ascii")),
        };
        let target = match std::str::from_utf8(target) {
            Ok(target) => target,
            Err(_) => return Self::api_error(ApiError::bad_request("target must be utf-8")),
        };
        let path = target
            .split_once('?')
            .map(|(path, _)| path)
            .unwrap_or(target);

        if method == "POST" && path.starts_with("/api/sim/captures/") {
            let response = self.handle_capture_post(path, body);
            return match response {
                Ok(response) => response,
                Err(error) => Self::api_error(error),
            };
        }
        if method == "GET" && path.starts_with("/api/sim/captures/") {
            let response = self.handle_capture_get(path);
            return match response {
                Ok(response) => response,
                Err(error) => Self::api_error(error),
            };
        }

        let response: Result<ApiResponse, ApiError> = match (method, path) {
            ("GET", "/api/config.json") => self
                .config_json()
                .map(|body| ApiResponse {
                    status: "200 OK",
                    content_type: "application/json; charset=utf-8",
                    body: body.into_bytes().into(),
                })
                .map_err(ApiError::internal),
            ("GET", "/api/state") => self
                .api_state_json()
                .map(|body| ApiResponse {
                    status: "200 OK",
                    content_type: "application/json; charset=utf-8",
                    body: body.into_bytes().into(),
                })
                .map_err(ApiError::internal),
            ("GET", _) => Err(ApiError::not_found("unknown api endpoint")),
            ("POST", _) => self
                .handle_api_command(path, body)
                .and_then(|()| self.api_success()),
            _ => Err(ApiError::method_not_allowed("api commands require POST")),
        };

        match response {
            Ok(response) => response,
            Err(error) => Self::api_error(error),
        }
    }

    fn handle_capture_post(&self, path: &str, body: &[u8]) -> Result<ApiResponse, ApiError> {
        if !self.ws_bind_addr.ip().is_loopback() {
            return Err(ApiError::conflict(
                "capture creation is disabled on a non-loopback runtime bind",
            ));
        }
        let request = Self::api_request_body(body)?;
        let preview = self
            .simulated_preview()
            .ok_or_else(|| ApiError::conflict("capture requires simulation mode"))?;
        let project_path = preview.project_path().to_path_buf();
        let job = match path {
            "/api/sim/captures/screenshot" => {
                if request.as_object().is_some_and(|object| !object.is_empty()) {
                    return Err(ApiError::bad_request(
                        "screenshot request currently accepts only an empty JSON object",
                    ));
                }
                let state = preview.capture_state().map_err(ApiError::internal)?;
                self.capture_manager
                    .enqueue_screenshot(project_path, state)
                    .map_err(api_capture_failure)?
            }
            "/api/sim/captures/record" => {
                let frames = request
                    .get("frames")
                    .and_then(|value| value.as_u64())
                    .ok_or_else(|| ApiError::bad_request("frames must be a positive integer"))?;
                let frames = u32::try_from(frames)
                    .map_err(|_| ApiError::bad_request("frames exceeds supported range"))?;
                let view = match request.get("camera") {
                    None => CaptureCameraView::External,
                    Some(value) if value.as_str() == Some("external") => {
                        CaptureCameraView::External
                    }
                    Some(value) if value.as_str() == Some("tcp") => CaptureCameraView::Tcp,
                    Some(_) => {
                        return Err(ApiError::bad_request(
                            "camera must be either external or tcp",
                        ));
                    }
                };
                if request.as_object().is_some_and(|object| {
                    object.keys().any(|key| key != "frames" && key != "camera")
                }) {
                    return Err(ApiError::bad_request(
                        "record request accepts only the frames and camera fields",
                    ));
                }
                preview
                    .capture_state_for_view(view)
                    .map_err(ApiError::conflict)?;
                self.capture_manager
                    .begin_recording(project_path, frames, view)
                    .map_err(api_capture_failure)?
            }
            _ => return Err(ApiError::not_found("unknown capture endpoint")),
        };
        Ok(Self::api_json(
            "202 Accepted",
            serde_json::json!({"ok": true, "job": job}),
        ))
    }

    fn handle_capture_get(&self, path: &str) -> Result<ApiResponse, ApiError> {
        let suffix = path
            .strip_prefix("/api/sim/captures/")
            .ok_or_else(|| ApiError::not_found("unknown capture endpoint"))?;
        let segments = suffix.split('/').collect::<Vec<_>>();
        match segments.as_slice() {
            [id] => {
                let status = self
                    .capture_manager
                    .status(id)
                    .map_err(api_capture_failure)?;
                Ok(Self::api_json(
                    "200 OK",
                    serde_json::json!({"ok": true, "job": status}),
                ))
            }
            [id, "state"] => {
                let body = self
                    .capture_manager
                    .state(id)
                    .map_err(api_capture_failure)?;
                Ok(ApiResponse {
                    status: "200 OK",
                    content_type: "application/json; charset=utf-8",
                    body,
                })
            }
            [id, "artifact"] => {
                let (content_type, body) = self
                    .capture_manager
                    .artifact(id)
                    .map_err(api_capture_failure)?;
                Ok(ApiResponse {
                    status: "200 OK",
                    content_type,
                    body,
                })
            }
            _ => Err(ApiError::not_found("unknown capture endpoint")),
        }
    }

    fn handle_api_command(&mut self, path: &str, body: &[u8]) -> Result<(), ApiError> {
        let json = Self::api_request_body(body)?;
        let segments = path
            .trim_start_matches('/')
            .split('/')
            .filter(|segment| !segment.is_empty())
            .collect::<Vec<_>>();

        match segments.as_slice() {
            ["api", "drive"] => self.api_drive(&json),
            ["api", "sim", "interact"] => self.api_sim_interact(),
            ["api", "drive", "stop"] => {
                self.stop_drive();
                Ok(())
            }
            ["api", "arm", "speed"] => self.api_arm_speed(&json),
            ["api", "arm", "hold"] => self
                .arm("arm hold", ArmCommand::Hold)
                .map_err(|err| ApiError::bad_request(format!("arm hold rejected: {err:?}"))),
            ["api", "arm", "stop"] => self
                .arm("arm stop all", ArmCommand::StopAll)
                .map_err(|err| ApiError::bad_request(format!("arm stop rejected: {err:?}"))),
            ["api", "arm", "clear-faults"] => self
                .arm("clear arm faults", ArmCommand::ClearFaults { joint: None })
                .map_err(|err| ApiError::bad_request(format!("clear faults rejected: {err:?}"))),
            ["api", "arm", "joints", joint, "spin"] => {
                let joint = Self::api_joint(joint)?;
                let direction = Self::json_i64(&json, "direction")?;
                let direction = match direction {
                    -1 => -1,
                    1 => 1,
                    _ => return Err(ApiError::bad_request("direction must be -1 or 1")),
                };
                self.start_joint_jog("spin joint", joint, direction)
                    .map_err(|err| ApiError::bad_request(format!("spin joint rejected: {err:?}")))
            }
            ["api", "arm", "joints", joint, "stop"] => {
                let joint = Self::api_joint(joint)?;
                self.arm("stop joint", ArmCommand::Stop { joint })
                    .map_err(|err| ApiError::bad_request(format!("stop joint rejected: {err:?}")))
            }
            ["api", "arm", "joints", joint, "zero"] => {
                let joint = Self::api_joint(joint)?;
                self.arm(
                    "move joint to zero",
                    ArmCommand::SetJointAngle {
                        joint,
                        angle_rad: 0.0,
                    },
                )
                .map_err(|err| ApiError::bad_request(format!("zero joint rejected: {err:?}")))
            }
            ["api", "arm", "joints", joint, "reference"] => {
                let joint = Self::api_joint(joint)?;
                let angle_deg = Self::json_f64(&json, "angleDeg")?;
                self.set_joint_reference_angle(joint, angle_deg)
                    .map_err(|err| {
                        ApiError::bad_request(format!("set joint reference rejected: {err}"))
                    })
            }
            ["api", "arm", "joints", joint, "angle-sign", "flip"] => {
                let joint = Self::api_joint(joint)?;
                self.flip_joint_angle_sign_for(joint)
                    .map_err(ApiError::bad_request)
            }
            ["api", "arm", "joints", joint, "limits"] => {
                let joint = Self::api_joint(joint)?;
                let min = i32::try_from(Self::json_i64(&json, "minTick")?)
                    .map_err(|_| ApiError::bad_request("minTick is out of range"))?;
                let max = i32::try_from(Self::json_i64(&json, "maxTick")?)
                    .map_err(|_| ApiError::bad_request("maxTick is out of range"))?;
                if min == max {
                    return Err(ApiError::bad_request("minTick and maxTick must differ"));
                }
                self.arm(
                    "set joint limits",
                    ArmCommand::SetTickLimits { joint, min, max },
                )
                .map_err(|err| ApiError::bad_request(format!("set limits rejected: {err:?}")))
            }
            ["api", "arm", "joints", joint, "limits", "enabled"] => {
                let joint = Self::api_joint(joint)?;
                let enabled = Self::json_bool(&json, "enabled")?;
                self.arm(
                    if enabled {
                        "enable joint limits"
                    } else {
                        "disable joint limits"
                    },
                    ArmCommand::SetTickLimitsEnabled { joint, enabled },
                )
                .map_err(|err| {
                    ApiError::bad_request(format!("set limits enabled rejected: {err:?}"))
                })
            }
            ["api", "arm", "goto-angles"] => self.api_goto_angles(&json),
            ["api", "arm", "goto-default"] | ["api", "arm", "goto-default-angles"] => {
                self.move_to_default_goto_angles();
                Ok(())
            }
            ["api", "arm", "goto-current"] => {
                self.set_goto_angles_current();
                Ok(())
            }
            ["api", "arm", "coordinates", "current"] => {
                self.set_coordinates_current();
                Ok(())
            }
            ["api", "arm", "coordinates", "move"] => self.api_move_coordinates(&json),
            ["api", "arm", "tcp-frame"] => {
                let frame = Self::api_frame(&json, "frame")?;
                if !matches!(frame, TcpFrame::Base | TcpFrame::Tool) {
                    return Err(ApiError::bad_request("tcp frame must be base or tool"));
                }
                self.set_tcp_frame(frame);
                Ok(())
            }
            ["api", "arm", "coordinate-frame"] => Err(ApiError::bad_request(
                "Coordinate Move is always robot-base relative; no jog frame can be selected",
            )),
            ["api", "arm", "tcp-jog", "start"] => self.api_tcp_jog_start(&json),
            ["api", "arm", "tcp-camera-jog", "start"] => self.api_tcp_camera_jog_start(&json),
            ["api", "arm", "coordinate-jog", "start"] => self.api_coordinate_jog_start(&json),
            ["api", "arm", "tcp-jog", "stop"] => self
                .arm("stop tcp jog", ArmCommand::StopTcpJog)
                .map_err(|err| ApiError::bad_request(format!("stop tcp jog rejected: {err:?}"))),
            ["api", "calibration", "save"] => {
                self.save_calibration().map_err(ApiError::bad_request)
            }
            ["api", "arm", "coordinate-calibration", "flip-forward"] => {
                self.flip_coordinate_forward_axis();
                Ok(())
            }
            ["api", "arm", "coordinate-calibration", "flip-left"] => {
                self.flip_coordinate_left_axis();
                Ok(())
            }
            ["api", "arm", "coordinate-calibration", "rotate-base"] => {
                self.rotate_coordinate_base_frame();
                Ok(())
            }
            _ => Err(ApiError::not_found("unknown api command")),
        }
    }

    fn api_drive(&mut self, json: &serde_json::Value) -> Result<(), ApiError> {
        match Self::json_str(json, "action")? {
            "forward" => self.drive("drive forward", UI_DRIVE_SPEED, 0),
            "back" | "backward" => self.drive("drive back", -UI_DRIVE_SPEED, 0),
            "left" => self.drive("drive left", 0, -UI_STEER_SPEED),
            "right" => self.drive("drive right", 0, UI_STEER_SPEED),
            "stop" => self.stop_drive(),
            _ => {
                return Err(ApiError::bad_request(
                    "action must be forward, back, left, right, or stop",
                ));
            }
        }
        Ok(())
    }

    fn api_sim_interact(&mut self) -> Result<(), ApiError> {
        let action = match &mut self.backend {
            RuntimeBackend::Hardware { .. } => {
                return Err(ApiError::conflict(
                    "Interact is simulation-only and is unavailable in hardware mode",
                ));
            }
            RuntimeBackend::Simulated(backend) => {
                backend.tool_action().map_err(ApiError::conflict)?
            }
        };
        self.last_command = format!("Interact: {}", action.result);
        self.mark_ui_dirty();
        Ok(())
    }

    fn api_arm_speed(&mut self, json: &serde_json::Value) -> Result<(), ApiError> {
        let speed = Self::json_i64(json, "speed")?;
        if speed < 0 || speed > i64::from(i16::MAX) {
            return Err(ApiError::bad_request(
                "speed must be a non-negative i16 integer",
            ));
        }
        self.arm_speed = speed.to_string();
        self.apply_arm_speed();
        Ok(())
    }

    fn api_goto_angles(&mut self, json: &serde_json::Value) -> Result<(), ApiError> {
        let yaw = Self::json_f64(json, "yawDeg")?;
        let shoulder = Self::json_f64(json, "shoulderDeg")?;
        let elbow = Self::json_f64(json, "elbowDeg")?;
        let wrist = Self::json_f64(json, "wristDeg")?;
        self.goto_angle_yaw = format!("{yaw:.1}");
        self.goto_angle_shoulder = format!("{shoulder:.1}");
        self.goto_angle_elbow = format!("{elbow:.1}");
        self.goto_angle_wrist = format!("{wrist:.1}");
        self.arm(
            "move to target angles",
            ArmCommand::GotoAngles([
                yaw.to_radians(),
                shoulder.to_radians(),
                elbow.to_radians(),
                wrist.to_radians(),
            ]),
        )
        .map_err(|err| ApiError::bad_request(format!("goto angles rejected: {err:?}")))?;
        self.sync_coordinates_from_target();
        Ok(())
    }

    fn api_move_coordinates(&mut self, json: &serde_json::Value) -> Result<(), ApiError> {
        let x = Self::json_f64(json, "xMm")?;
        let y = Self::json_f64(json, "yMm")?;
        let z_table = Self::json_f64(json, "zMm")?;
        let tool_phi_rad = Self::json_f64(json, "toolPhiDeg")?.to_radians();
        self.coordinate_x = format!("{x:.1}");
        self.coordinate_y = format!("{y:.1}");
        self.coordinate_z = format!("{z_table:.1}");
        self.coordinate_error.clear();
        self.arm(
            "move to coordinates",
            ArmCommand::GotoCoords {
                x,
                y,
                z: kinematics::table_to_shoulder_z(z_table),
                tool_phi_rad,
            },
        )
        .map_err(|err| ApiError::bad_request(format!("move to coordinates rejected: {err:?}")))?;
        self.sync_goto_angles_from_targets();
        Ok(())
    }

    fn api_tcp_jog_start(&mut self, json: &serde_json::Value) -> Result<(), ApiError> {
        let frame = Self::api_frame(json, "frame")?;
        if !matches!(frame, TcpFrame::Base | TcpFrame::Tool) {
            return Err(ApiError::bad_request("tcp jog frame must be base or tool"));
        }
        let direction = Self::api_direction(Self::json_str(json, "direction")?)?;
        if direction[2] != 0.0 {
            return Err(ApiError::bad_request(
                "TCP Jog has no vertical control; use Coordinate Move for robot Z or TCP Camera POV in simulation",
            ));
        }
        self.start_tcp_jog("http tcp jog", frame, direction)
            .map_err(|err| ApiError::bad_request(format!("tcp jog rejected: {err:?}")))
    }

    fn api_tcp_camera_jog_start(&mut self, json: &serde_json::Value) -> Result<(), ApiError> {
        let direction = match Self::json_str(json, "direction")? {
            "forward" => TcpCameraJogDirection::Forward,
            "back" | "backward" => TcpCameraJogDirection::Back,
            "left" => TcpCameraJogDirection::Left,
            "right" => TcpCameraJogDirection::Right,
            "up" => TcpCameraJogDirection::Up,
            "down" => TcpCameraJogDirection::Down,
            _ => {
                return Err(ApiError::bad_request(
                    "direction must be forward, back, left, right, up, or down",
                ));
            }
        };
        self.start_tcp_camera_jog("http TCP camera POV jog", direction)
            .map_err(ApiError::conflict)
    }

    fn api_coordinate_jog_start(&mut self, json: &serde_json::Value) -> Result<(), ApiError> {
        let frame = Self::api_frame(json, "frame")?;
        if frame != TcpFrame::Base {
            return Err(ApiError::bad_request(
                "coordinate jog frame must be base/armBase; directions are robot-base relative",
            ));
        }
        let direction = match Self::json_str(json, "direction")? {
            "forward" => self.coordinate_jog_direction(self.coordinate_forward_sign(), 0.0, 0.0),
            "back" | "backward" => {
                self.coordinate_jog_direction(-self.coordinate_forward_sign(), 0.0, 0.0)
            }
            "left" => self.coordinate_jog_direction(0.0, self.coordinate_left_sign(), 0.0),
            "right" => self.coordinate_jog_direction(0.0, -self.coordinate_left_sign(), 0.0),
            "up" => [0.0, 0.0, 1.0],
            "down" => [0.0, 0.0, -1.0],
            _ => {
                return Err(ApiError::bad_request(
                    "direction must be forward, back, left, right, up, or down",
                ));
            }
        };
        self.start_tcp_jog("http coordinate jog", TcpFrame::Base, direction)
            .map_err(|err| ApiError::bad_request(format!("coordinate jog rejected: {err:?}")))
    }

    fn coordinate_calibration(&self) -> CoordinateCalibration {
        self.active_config.coordinate
    }

    fn save_calibration(&mut self) -> Result<(), String> {
        if self.backend.is_simulated() {
            let err = "simulation model mapping is session-only and cannot be saved".to_string();
            self.last_command = err.clone();
            self.mark_ui_dirty();
            return Err(err);
        }
        self.sync_arm_calibration_from_robot();
        let result = match config::save_runtime_config(&self.config_path, &self.active_config) {
            Ok(()) => {
                self.calibration_dirty = false;
                self.last_command = format!("saved calibration to {}", self.config_path.display());
                log::info!("runtime App command: {}", self.last_command);
                Ok(())
            }
            Err(err) => {
                self.last_command = format!("save calibration failed: {err}");
                log::warn!("runtime App save calibration failed: {err}");
                Err(err)
            }
        };
        self.mark_ui_dirty();
        result
    }

    fn render_item(&self) -> Item {
        let mut children = vec![
            self.render_status_cards(),
            hstack(vec![self.render_drive_control(), self.render_arm_panel()])
                .spacing(12)
                .wrap(true),
        ];
        if let Some(modal) = self.render_limit_modal() {
            children.push(modal);
        }
        if let Some(modal) = self.render_calibration_modal() {
            children.push(modal);
        }
        if let Some(modal) = self.render_coordinate_preview_modal() {
            children.push(modal);
        }

        vstack(children)
            .fill(true)
            .min_height(0)
            .background_color("#12161c")
            .padding(18)
            .spacing(14)
    }

    fn calibration_status_metric(&self) -> UiMetric {
        if self.backend.is_simulated() {
            UiMetric {
                label: "Calibration".to_string(),
                value: "session mapped".to_string(),
                detail: "Physical controller calibration; RobotDreams mapping is session-only"
                    .to_string(),
                accent: "#3fbf6f",
                save_action: false,
            }
        } else {
            UiMetric {
                label: "Config".to_string(),
                value: if self.calibration_dirty {
                    "unsaved".to_string()
                } else {
                    "saved".to_string()
                },
                detail: self.config_path.display().to_string(),
                accent: if self.calibration_dirty {
                    "#d89b2f"
                } else {
                    "#3fbf6f"
                },
                save_action: self.calibration_dirty,
            }
        }
    }

    fn render_status_cards(&self) -> Item {
        let arm = self.robot.arm_telemetry();
        let drive = self.robot.drive_output();
        let feedback_count = arm.joints.iter().filter(|joint| joint.has_feedback).count();
        let fault_count = arm
            .joints
            .iter()
            .filter(|joint| joint.fault.is_some())
            .count();
        let active_joint_count = arm.joints.iter().filter(|joint| joint.speed != 0).count();
        let uptime = self.now_ms() / 1000;
        let ws_url = local_url(self.ws_bind_addr, "ws", "/ws");
        let ui_clients = self.client_ids.len();

        let status = vec![
            UiMetric {
                label: "Runtime".to_string(),
                value: "running".to_string(),
                detail: format!("{ws_url}; uptime {uptime}s; {ui_clients} UI clients"),
                accent: "#3fbf6f",
                save_action: false,
            },
            UiMetric {
                label: "Servo bus".to_string(),
                value: self.backend.status_value().to_string(),
                detail: self.backend.status_detail().to_string(),
                accent: "#3fbf6f",
                save_action: false,
            },
            UiMetric {
                label: "Drive".to_string(),
                value: if drive.active { "Active" } else { "Idle" }.to_string(),
                detail: format!(
                    "left {} / right {} / steering {} deg",
                    drive.left_speed, drive.right_speed, drive.steering_angle_deg
                ),
                accent: if drive.active { "#ffd166" } else { "#8ea0b7" },
                save_action: false,
            },
            self.calibration_status_metric(),
            UiMetric {
                label: "Arm".to_string(),
                value: if fault_count == 0 {
                    format!("{feedback_count}/{JOINT_COUNT} feedback")
                } else {
                    format!("{fault_count} fault(s)")
                },
                detail: format!("{active_joint_count} joints moving"),
                accent: if fault_count == 0 {
                    "#3fbf6f"
                } else {
                    "#d85b5b"
                },
                save_action: false,
            },
        ];

        hstack(status.into_iter().map(|item| {
            let mut children = vec![
                hstack(vec![
                    vstack(Vec::<Item>::new())
                        .width(8)
                        .height(40)
                        .background_color(item.accent),
                    vstack(vec![
                        label_text(&item.label),
                        title_text(&item.value).break_words(true),
                    ])
                    .grow(1)
                    .spacing(2),
                ])
                .spacing(8),
                body_text(&item.detail),
            ];
            if item.save_action {
                children.push(
                    primary_button("Save Calibration")
                        .height(32)
                        .on_click(SAVE_CALIBRATION_ID),
                );
            }
            vstack(children)
                .width(300)
                .min_width(250)
                .background_color("#18202b")
                .border("1px solid #2b394a")
                .padding(12)
                .spacing(6)
        }))
        .spacing(12)
        .wrap(true)
    }

    fn render_drive_control(&self) -> Item {
        panel(vec![
            title_text("Drive Control"),
            hstack(vec![
                primary_button("Forward")
                    .height(34)
                    .on_press(DRIVE_FORWARD_ID)
                    .on_release(DRIVE_STOP_ID),
            ])
            .spacing(8),
            hstack(vec![
                dark_button("Left")
                    .height(34)
                    .on_press(DRIVE_LEFT_ID)
                    .on_release(DRIVE_STOP_ID),
                danger_button("Stop").height(34).on_click(DRIVE_STOP_ID),
                dark_button("Right")
                    .height(34)
                    .on_press(DRIVE_RIGHT_ID)
                    .on_release(DRIVE_STOP_ID),
            ])
            .spacing(8),
            hstack(vec![
                dark_button("Back")
                    .height(34)
                    .on_press(DRIVE_BACK_ID)
                    .on_release(DRIVE_STOP_ID),
            ])
            .spacing(8),
        ])
        .width(360)
        .min_width(300)
    }

    fn render_joint_row(&self, index: usize, joint: &Joint) -> Item {
        let action_arg = index as u32 + 1;
        let limit = limit_status(joint);
        let mut children = vec![
            label_text(&format!(
                "{} (servo {})",
                ARM_JOINT_LABELS[index], joint.servo_id
            ))
            .min_width(132),
            body_text(&angle_detail(joint))
                .min_width(72)
                .text_align("right"),
        ];
        if !self.backend.is_simulated() {
            children.push(
                secondary_button("Calibrate")
                    .height(30)
                    .width(86)
                    .inx(action_arg)
                    .on_click(OPEN_JOINT_CALIBRATION_ID),
            );
        }
        children.extend([
            secondary_button("Zero")
                .height(30)
                .width(64)
                .inx(action_arg)
                .on_press(SET_JOINT_ZERO_ID)
                .on_release(SET_JOINT_ZERO_ID),
            dark_button("-")
                .height(30)
                .width(42)
                .inx(action_arg)
                .on_press(JOG_NEGATIVE_ID)
                .on_release(JOG_STOP_ID),
            secondary_button("Stop")
                .height(30)
                .inx(action_arg)
                .on_click(STOP_JOINT_ID),
            dark_button("+")
                .height(30)
                .width(42)
                .inx(action_arg)
                .on_press(JOG_POSITIVE_ID)
                .on_release(JOG_STOP_ID),
            vstack(vec![
                text(&limit.label).color(limit.accent).text_align("center"),
                body_text(&limit.detail).text_align("center"),
            ])
            .min_width(112)
            .background_color(limit.background)
            .border(limit.border)
            .padding(6)
            .spacing(2),
            secondary_button("Limits")
                .height(30)
                .width(80)
                .inx(action_arg)
                .on_click(OPEN_LIMIT_EDITOR_ID),
            secondary_button(limit.toggle_label)
                .height(30)
                .width(80)
                .inx(action_arg)
                .on_click(TOGGLE_JOINT_LIMITS_ID),
        ]);
        hstack(children).spacing(8)
    }

    fn render_joint_target(&self) -> Item {
        subpanel(vec![
            title_text("Joint Target (deg)"),
            label_text(
                "Default (90 / 90 / 90 / 90) is the upright-shoulder, horizontal-reach, tool-down reference pose",
            ),
            hstack(vec![
                field(
                    "Yaw",
                    EDIT_GOTO_ANGLE_YAW_ID,
                    &self.goto_angle_yaw,
                    "yaw",
                    86,
                ),
                field(
                    "Shoulder",
                    EDIT_GOTO_ANGLE_SHOULDER_ID,
                    &self.goto_angle_shoulder,
                    "shoulder",
                    86,
                ),
                field(
                    "Elbow",
                    EDIT_GOTO_ANGLE_ELBOW_ID,
                    &self.goto_angle_elbow,
                    "elbow",
                    86,
                ),
                field(
                    "Wrist",
                    EDIT_GOTO_ANGLE_WRIST_ID,
                    &self.goto_angle_wrist,
                    "wrist",
                    86,
                ),
                secondary_button("Current")
                    .height(34)
                    .width(88)
                    .on_click(SET_GOTO_ANGLES_CURRENT_ID),
                secondary_button("Default")
                    .height(34)
                    .width(88)
                    .on_press(GOTO_DEFAULT_ANGLES_ID)
                    .on_release(GOTO_ANGLES_ID),
                primary_button("Move Angles")
                    .height(34)
                    .width(116)
                    .on_press(GOTO_ANGLES_ID)
                    .on_release(GOTO_ANGLES_ID),
            ])
            .spacing(12),
            error_text(&self.goto_angle_error),
        ])
    }

    fn render_arm_speed(&self) -> Item {
        subpanel(vec![
            title_text("Arm Speed"),
            hstack(vec![
                field("Speed", EDIT_ARM_SPEED_ID, &self.arm_speed, "speed", 112),
                primary_button("Set Speed")
                    .height(34)
                    .width(104)
                    .on_click(SET_ARM_SPEED_ID),
            ])
            .spacing(8),
            error_text(&self.arm_speed_error),
        ])
    }

    fn render_tcp_jog(&self) -> Item {
        subpanel(vec![
            title_text("TCP Jog"),
            hstack(vec![
                label_text("Frame").min_width(56),
                frame_button(
                    "Base",
                    self.tcp_frame == TcpFrame::Base,
                    SET_TCP_FRAME_BASE_ID,
                    74,
                ),
                frame_button(
                    "Tool",
                    self.tcp_frame == TcpFrame::Tool,
                    SET_TCP_FRAME_TOOL_ID,
                    74,
                ),
                title_text(frame_label(self.tcp_frame)).min_width(48),
                label_text(frame_detail(self.tcp_frame))
                    .grow(1)
                    .break_words(true),
            ])
            .spacing(8),
            hstack(vec![
                primary_button("Forward")
                    .height(32)
                    .on_press(MOVE_TCP_FORWARD_ID)
                    .on_release(MOVE_TCP_STOP_ID),
            ])
            .spacing(8),
            hstack(vec![
                dark_button("Left")
                    .height(32)
                    .on_press(MOVE_TCP_LEFT_ID)
                    .on_release(MOVE_TCP_STOP_ID),
                dark_button("Back")
                    .height(32)
                    .on_press(MOVE_TCP_BACK_ID)
                    .on_release(MOVE_TCP_STOP_ID),
                dark_button("Right")
                    .height(32)
                    .on_press(MOVE_TCP_RIGHT_ID)
                    .on_release(MOVE_TCP_STOP_ID),
            ])
            .spacing(8),
        ])
    }

    fn render_tcp_camera_jog(&self) -> Item {
        if !self.backend.is_simulated() {
            return subpanel(vec![
                title_text("TCP Camera POV"),
                label_text("Available only in --sim: requires the live RobotDreams wrist camera."),
            ]);
        }
        subpanel(vec![
            title_text("TCP Camera POV"),
            label_text(
                "Live wrist-camera screen axes. Each press samples and latches one direction in arm-base coordinates.",
            )
            .break_words(true),
            hstack(vec![
                primary_button("Forward (into view)")
                    .height(32)
                    .on_press(MOVE_TCP_CAMERA_FORWARD_ID)
                    .on_release(MOVE_TCP_STOP_ID),
                dark_button("Back (away)")
                    .height(32)
                    .on_press(MOVE_TCP_CAMERA_BACK_ID)
                    .on_release(MOVE_TCP_STOP_ID),
            ])
            .spacing(8)
            .wrap(true),
            hstack(vec![
                dark_button("Screen Left")
                    .height(32)
                    .on_press(MOVE_TCP_CAMERA_LEFT_ID)
                    .on_release(MOVE_TCP_STOP_ID),
                dark_button("Screen Right")
                    .height(32)
                    .on_press(MOVE_TCP_CAMERA_RIGHT_ID)
                    .on_release(MOVE_TCP_STOP_ID),
                dark_button("Screen Up")
                    .height(32)
                    .on_press(MOVE_TCP_CAMERA_UP_ID)
                    .on_release(MOVE_TCP_STOP_ID),
                dark_button("Screen Down")
                    .height(32)
                    .on_press(MOVE_TCP_CAMERA_DOWN_ID)
                    .on_release(MOVE_TCP_STOP_ID),
            ])
            .spacing(8)
            .wrap(true),
        ])
    }

    fn render_coordinate_move(&self) -> Item {
        let coordinate_calibration = self.coordinate_calibration();
        let coordinate_detail = self
            .robot
            .arm
            .coords_mm()
            .map(|(x, y, z)| format!("current {x:.1}, {y:.1}, {z:.1} mm"))
            .unwrap_or_else(|| "current position unavailable".to_string());

        subpanel(vec![
            title_text("Arm Base (mm)"),
            label_text(&coordinate_detail).break_words(true),
            hstack(vec![
                title_text("Robot-relative jog").min_width(128),
                label_text(
                    "Forward/back/left/right follow PuppyBot's body, not the camera or arm yaw.",
                )
                .grow(1)
                .break_words(true),
            ])
            .spacing(8)
            .wrap(true),
            hstack(vec![
                label_text(&format!(
                    "robot to arm-base calibration: forward sign {}, left sign {}, yaw {:.1} deg",
                    coordinate_calibration.forward_sign,
                    coordinate_calibration.left_sign,
                    coordinate_calibration.base_yaw_offset_deg
                ))
                .grow(1)
                .break_words(true),
                secondary_button("Flip F/B")
                    .height(30)
                    .width(88)
                    .on_click(FLIP_COORDINATE_FORWARD_AXIS_ID),
                secondary_button("Flip L/R")
                    .height(30)
                    .width(88)
                    .on_click(FLIP_COORDINATE_LEFT_AXIS_ID),
                secondary_button("Rotate 90")
                    .height(30)
                    .width(104)
                    .on_click(ROTATE_COORDINATE_BASE_FRAME_ID),
            ])
            .spacing(8)
            .wrap(true),
            hstack(vec![
                field("X", EDIT_COORDINATE_X_ID, &self.coordinate_x, "x", 96),
                field("Y", EDIT_COORDINATE_Y_ID, &self.coordinate_y, "y", 96),
                field("Z", EDIT_COORDINATE_Z_ID, &self.coordinate_z, "z", 96),
                secondary_button("Current")
                    .height(34)
                    .width(88)
                    .on_click(SET_COORDINATES_CURRENT_ID),
                secondary_button("Preview")
                    .height(34)
                    .width(88)
                    .on_click(PREVIEW_COORDINATES_ID),
                primary_button("Move")
                    .height(34)
                    .width(88)
                    .on_click(MOVE_TO_COORDINATES_ID),
            ])
            .spacing(8)
            .wrap(true),
            hstack(vec![
                dark_button("Forward")
                    .height(32)
                    .width(82)
                    .on_press(COORDINATE_FORWARD_ID)
                    .on_release(MOVE_TCP_STOP_ID),
                dark_button("Back")
                    .height(32)
                    .width(82)
                    .on_press(COORDINATE_BACK_ID)
                    .on_release(MOVE_TCP_STOP_ID),
                dark_button("Left")
                    .height(32)
                    .width(82)
                    .on_press(COORDINATE_LEFT_ID)
                    .on_release(MOVE_TCP_STOP_ID),
                dark_button("Right")
                    .height(32)
                    .width(82)
                    .on_press(COORDINATE_RIGHT_ID)
                    .on_release(MOVE_TCP_STOP_ID),
                dark_button("Up")
                    .height(32)
                    .width(82)
                    .on_press(COORDINATE_UP_ID)
                    .on_release(MOVE_TCP_STOP_ID),
                dark_button("Down")
                    .height(32)
                    .width(82)
                    .on_press(COORDINATE_DOWN_ID)
                    .on_release(MOVE_TCP_STOP_ID),
            ])
            .spacing(8)
            .wrap(true),
            error_text(&self.coordinate_error),
        ])
    }

    fn render_limit_modal(&self) -> Option<Item> {
        self.limit_editor_joint.map(|joint| {
            let (title, detail) = if joint < JOINT_COUNT {
                let telemetry_joint = &self.robot.arm.joints[joint];
                (
                    format!("{} Limits", ARM_JOINT_LABELS[joint]),
                    match telemetry_joint.tick {
                        Some(tick) => {
                            format!("servo {} current tick {tick}", telemetry_joint.servo_id)
                        }
                        None => format!("servo {} waiting for feedback", telemetry_joint.servo_id),
                    },
                )
            } else {
                ("Joint Limits".to_string(), "no joint selected".to_string())
            };

            modal(vec![
                vstack(vec![
                    title_text(&title).text_align("center"),
                    label_text(&detail).text_align("center").break_words(true),
                    subpanel(vec![
                        label_text("Minimum tick"),
                        hstack(vec![
                            dark_button("-")
                                .height(32)
                                .width(36)
                                .on_click(LIMIT_MIN_DOWN_ID),
                            input(EDIT_LIMIT_MIN_ID, &self.limit_editor_min, "min"),
                            dark_button("+")
                                .height(32)
                                .width(36)
                                .on_click(LIMIT_MIN_UP_ID),
                            secondary_button("Now")
                                .height(32)
                                .width(56)
                                .on_click(SET_LIMIT_MIN_CURRENT_ID),
                        ])
                        .spacing(8),
                        label_text("Maximum tick"),
                        hstack(vec![
                            dark_button("-")
                                .height(32)
                                .width(36)
                                .on_click(LIMIT_MAX_DOWN_ID),
                            input(EDIT_LIMIT_MAX_ID, &self.limit_editor_max, "max"),
                            dark_button("+")
                                .height(32)
                                .width(36)
                                .on_click(LIMIT_MAX_UP_ID),
                            secondary_button("Now")
                                .height(32)
                                .width(56)
                                .on_click(SET_LIMIT_MAX_CURRENT_ID),
                        ])
                        .spacing(8),
                    ]),
                    error_text(&self.limit_editor_error).text_align("center"),
                    hstack(vec![
                        secondary_button("Cancel").on_click(CLOSE_LIMIT_EDITOR_ID),
                        primary_button("Set").on_click(APPLY_LIMIT_EDITOR_ID),
                    ])
                    .spacing(8),
                ])
                .width(420)
                .max_width(420)
                .background_color("#18202b")
                .border("1px solid #415066")
                .padding(16)
                .spacing(12),
            ])
            .id(CLOSE_LIMIT_EDITOR_ID)
        })
    }

    fn render_calibration_modal(&self) -> Option<Item> {
        if self.backend.is_simulated() {
            return None;
        }
        self.calibration_editor_joint.map(|joint| {
            let (title, detail) = if joint < JOINT_COUNT {
                let telemetry_joint = &self.robot.arm.joints[joint];
                (
                    format!("{} Calibration", ARM_JOINT_LABELS[joint]),
                    match telemetry_joint.tick {
                        Some(tick) => format!(
                            "servo {} current tick {tick}; set what angle this pose represents",
                            telemetry_joint.servo_id
                        ),
                        None => format!("servo {} waiting for feedback", telemetry_joint.servo_id),
                    },
                )
            } else {
                (
                    "Joint Calibration".to_string(),
                    "no joint selected".to_string(),
                )
            };
            let sign = self
                .calibration_editor_joint
                .and_then(|joint| self.active_config.arm.joints.get(joint))
                .map(|joint| joint.angle_sign);

            modal(vec![
                vstack(vec![
                    title_text(&title).text_align("center"),
                    label_text(&detail).text_align("center").break_words(true),
                    subpanel(vec![
                        label_text("Reference angle (deg)"),
                        input(
                            EDIT_JOINT_REFERENCE_ANGLE_ID,
                            &self.calibration_editor_angle,
                            "angle",
                        ),
                    ]),
                    hstack(vec![
                        label_text(&angle_sign_label(sign)).break_words(true),
                        secondary_button("Flip")
                            .height(34)
                            .width(72)
                            .on_click(FLIP_JOINT_ANGLE_SIGN_ID),
                    ])
                    .spacing(8),
                    error_text(&self.calibration_editor_error).text_align("center"),
                    hstack(vec![
                        secondary_button("Cancel").on_click(CLOSE_JOINT_CALIBRATION_ID),
                        primary_button("Apply").on_click(APPLY_JOINT_CALIBRATION_ID),
                    ])
                    .spacing(8),
                ])
                .width(420)
                .max_width(420)
                .background_color("#18202b")
                .border("1px solid #415066")
                .padding(16)
                .spacing(12),
            ])
            .id(CLOSE_JOINT_CALIBRATION_ID)
        })
    }

    fn render_coordinate_preview_modal(&self) -> Option<Item> {
        if !self.coordinate_preview_open {
            return None;
        }

        let current = self
            .robot
            .arm
            .coords_mm()
            .map(|(x, y, z)| format!("current TCP {x:.1}, {y:.1}, {z:.1} mm"))
            .unwrap_or_else(|| "current TCP position unavailable".to_string());

        let parsed = Self::parse_coordinate(&self.coordinate_x, "x")
            .and_then(|x| Self::parse_coordinate(&self.coordinate_y, "y").map(|y| (x, y)))
            .and_then(|(x, y)| Self::parse_coordinate(&self.coordinate_z, "z").map(|z| (x, y, z)));

        let mut body = vec![
            title_text("Coordinate Preview").text_align("center"),
            label_text(&current).text_align("center").break_words(true),
        ];

        let Some((x, y, z_table)) = parsed.ok() else {
            body.push(
                label_text("coordinates invalid")
                    .text_align("center")
                    .break_words(true),
            );
            body.push(close_preview_button());
            return preview_modal(body);
        };

        let z = kinematics::table_to_shoulder_z(z_table);
        let tool_phi_rad = kinematics::ARM_TOOL_PHI_RAD;
        let target_angles = self.robot.arm.preview_target_angles(x, y, z, tool_phi_rad);

        body.push(
            label_text(&format!(
                "target TCP (from coordinates) {x:.1}, {y:.1}, {z_table:.1} mm"
            ))
            .text_align("center")
            .break_words(true),
        );

        if target_angles.is_none() {
            body.push(
                label_text("target unreachable")
                    .text_align("center")
                    .break_words(true),
            );
        }

        let joints: Vec<Item> = (0..JOINT_COUNT)
            .map(|joint| {
                let j = &self.robot.arm.joints[joint];
                let target_angle_rad = target_angles.map(|angles| angles[joint]);
                let target_tick = target_angle_rad.map(|rad| j.angle_to_tick(rad));
                let target_deg =
                    target_angle_rad.map(|rad| kinematics::wrap_pi(rad).to_degrees() as f32);
                subpanel(vec![
                    title_text(ARM_JOINT_LABELS[joint]),
                    label_text(&format!(
                        "servo {}  speed {}  online {}  feedback {}  limit {}",
                        j.servo_id, j.speed, j.online, j.has_feedback, j.limit_reached
                    ))
                    .break_words(true),
                    label_text(&format!(
                        "tick {}  target tick {}",
                        opt_tick(j.tick),
                        opt_tick(target_tick)
                    ))
                    .break_words(true),
                    label_text(&format!(
                        "angle {} deg  target {} deg",
                        opt_deg(j.angle_deg()),
                        opt_deg(target_deg)
                    ))
                    .break_words(true),
                ])
            })
            .collect();

        body.extend(joints);
        body.push(close_preview_button());

        preview_modal(body)
    }

    fn render_arm_panel(&self) -> Item {
        let arm = self.robot.arm_telemetry();
        let mut children = vec![title_text("Arm Jog")];
        children.push(self.render_arm_speed());
        children.extend(
            arm.joints
                .iter()
                .enumerate()
                .map(|(index, joint)| self.render_joint_row(index, joint)),
        );
        children.push(self.render_joint_target());
        children.push(self.render_tcp_jog());
        children.push(self.render_tcp_camera_jog());
        children.push(self.render_coordinate_move());
        children.push(
            hstack(vec![
                primary_button("Hold").on_click(ARM_HOLD_ID),
                danger_button("Stop Arm").on_click(ARM_STOP_ALL_ID),
                secondary_button("Clear Faults").on_click(CLEAR_ARM_FAULTS_ID),
            ])
            .spacing(8),
        );
        children.push(label_text("Last command"));
        children.push(title_text(&self.last_command).break_words(true));
        panel(children).grow(1).min_width(430)
    }

    fn mark_ui_dirty(&mut self) {
        self.ui_dirty = true;
    }

    fn stop_robot(&mut self) {
        self.held_drive = None;
        self.held_joint_jog = None;
        self.held_tcp_jog = None;
        self.robot
            .handle_event(ProtocolEvent::Drive(DriveCommand::Stop), self.now_ms());
        self.robot
            .handle_event(ProtocolEvent::Arm(ArmCommand::StopAll), self.now_ms());
        self.telemetry_seq = self.telemetry_seq.wrapping_add(1);
        self.mark_ui_dirty();
    }

    fn apply_event(&mut self, label: &str, event: ProtocolEvent) -> Result<(), ControllerError> {
        if matches!(event, ProtocolEvent::Drive(DriveCommand::Stop)) {
            self.held_drive = None;
        }
        match event {
            ProtocolEvent::Arm(ArmCommand::Stop { joint }) => {
                if self.held_joint_jog.is_some_and(|held| held.joint == joint) {
                    self.held_joint_jog = None;
                }
            }
            ProtocolEvent::Arm(
                ArmCommand::StopAll
                | ArmCommand::StopTcpJog
                | ArmCommand::Hold
                | ArmCommand::GotoTicks(_)
                | ArmCommand::GotoAngles(_)
                | ArmCommand::GotoCoords { .. }
                | ArmCommand::MoveTcp { .. }
                | ArmCommand::StartTcpJog { .. }
                | ArmCommand::StartTcpJogAtSpeed { .. },
            ) => {
                self.held_joint_jog = None;
                self.held_tcp_jog = None;
            }
            _ => {}
        }
        let reference_calibration = match event {
            ProtocolEvent::Arm(ArmCommand::SetJointReference {
                joint,
                tick,
                angle_rad,
            }) => Some((joint, tick, angle_rad)),
            _ => None,
        };
        let result = self.robot.try_handle_event(event, self.now_ms());
        match result {
            Ok(()) => {
                self.sync_arm_calibration_from_robot();
                if let Some((joint, tick, angle_rad)) = reference_calibration {
                    self.sync_joint_reference_calibration(joint, tick, angle_rad)?;
                }
                self.last_command = label.to_string();
                log::info!("runtime App command: {label}");
                self.mark_ui_dirty();
                self.telemetry_seq = self.telemetry_seq.wrapping_add(1);
                Ok(())
            }
            Err(err) => {
                self.last_command = format!("{label} rejected: {err:?}");
                log::warn!("runtime App command rejected: {label}: {err:?}");
                self.mark_ui_dirty();
                Err(err)
            }
        }
    }

    fn arm(&mut self, label: &str, command: ArmCommand) -> Result<(), ControllerError> {
        let result = self.apply_event(label, ProtocolEvent::Arm(command));
        match result {
            Ok(()) => {
                if coordinate_command(command) {
                    self.coordinate_error.clear();
                }
                if goto_angles_command(command) {
                    self.goto_angle_error.clear();
                }
                Ok(())
            }
            Err(err) => {
                if let Some(text) = arm_command_error_text(command, err) {
                    if goto_angles_command(command) {
                        self.goto_angle_error = text;
                    } else {
                        self.coordinate_error = text;
                    }
                }
                Err(err)
            }
        }
    }

    pub(crate) fn telemetry_seq(&self) -> u32 {
        self.telemetry_seq
    }

    pub(crate) fn arm_state_frame(&self) -> Vec<u8> {
        self.robot.arm_state_frame()
    }

    pub(crate) fn handle_binary_command(
        &mut self,
        payload: &[u8],
        telemetry_enabled: &mut bool,
    ) -> Option<Vec<u8>> {
        if self.backend.is_simulated() && payload.get(1).copied() == Some(protocol::CMD_CONFIG_SET)
        {
            self.last_command =
                "simulation model mapping is session-only; config changes are unavailable"
                    .to_string();
            log::warn!("runtime App rejected simulation config change");
            self.mark_ui_dirty();
            return None;
        }
        let now_ms = self.now_ms();
        let output =
            handle_binary_command_for_robot(&mut self.robot, payload, now_ms, telemetry_enabled);
        self.sync_arm_calibration_from_robot();

        if output.events.is_empty() {
            return output.response;
        }

        self.last_command = output
            .events
            .last()
            .map(|event| match event {
                ProtocolEvent::Arm(_) => "websocket arm command",
                ProtocolEvent::Drive(_) => "websocket drive command",
            })
            .unwrap_or("websocket command")
            .to_string();

        if output
            .events
            .iter()
            .any(|event| matches!(event, ProtocolEvent::Drive(_)))
        {
            log::info!("runtime App drive output: {:?}", self.robot.drive_output());
        }

        self.telemetry_seq = self.telemetry_seq.wrapping_add(1);
        self.mark_ui_dirty();
        output.response
    }

    fn drive(&mut self, label: &str, throttle: i8, steering: i8) {
        let command = DriveCommand::DriveSteer { throttle, steering };
        match self.start_drive_hold(command) {
            Ok(()) => {
                self.last_command = label.to_string();
                log::info!("runtime App command: {label}");
            }
            Err(err) => {
                self.last_command = format!("{label} rejected: {err:?}");
                log::warn!("runtime App command rejected: {label}: {err:?}");
            }
        }
        self.mark_ui_dirty();
    }

    fn start_drive_hold(&mut self, command: DriveCommand) -> Result<(), ControllerError> {
        let now_ms = self.now_ms();
        self.robot
            .try_handle_event(ProtocolEvent::Drive(command), now_ms)?;
        self.held_drive = Some(HeldDrive {
            command,
            last_refresh_ms: now_ms,
        });
        self.telemetry_seq = self.telemetry_seq.wrapping_add(1);
        Ok(())
    }

    fn stop_drive_hold(&mut self) -> Result<(), ControllerError> {
        self.held_drive = None;
        self.apply_event("stop drive", ProtocolEvent::Drive(DriveCommand::Stop))
    }

    fn set_keyboard_drive_key(&mut self, keycode: &str, pressed: bool) -> bool {
        if !self.keyboard_drive.set_key(keycode, pressed) {
            return false;
        }
        self.apply_keyboard_drive();
        true
    }

    fn apply_keyboard_drive(&mut self) {
        if let Some(command) = self.keyboard_drive.command() {
            match self.start_drive_hold(command) {
                Ok(()) => {
                    self.last_command = format!("keyboard drive {command:?}");
                    log::info!("runtime App command: keyboard drive {command:?}");
                }
                Err(err) => {
                    self.last_command = format!("keyboard drive rejected: {err:?}");
                    log::warn!("runtime App command rejected: keyboard drive: {err:?}");
                }
            }
        } else {
            match self.stop_drive_hold() {
                Ok(()) => {
                    self.last_command = "keyboard stop drive".to_string();
                    log::info!("runtime App command: keyboard stop drive");
                }
                Err(err) => {
                    self.last_command = format!("keyboard stop drive rejected: {err:?}");
                    log::warn!("runtime App command rejected: keyboard stop drive: {err:?}");
                }
            }
        }
        self.mark_ui_dirty();
    }

    fn clear_keyboard_drive(&mut self) {
        if self.keyboard_drive == KeyboardDriveState::default() {
            return;
        }
        self.keyboard_drive = KeyboardDriveState::default();
        self.stop_drive();
    }

    fn joint_arg_to_index(joint_arg: u32) -> Option<usize> {
        let index = usize::try_from(joint_arg.checked_sub(1)?).ok()?;
        (index < JOINT_COUNT).then_some(index)
    }

    fn stop_drive(&mut self) {
        match self.stop_drive_hold() {
            Ok(()) => {
                self.last_command = "stop drive".to_string();
                log::info!("runtime App command: stop drive");
            }
            Err(err) => {
                self.last_command = format!("stop drive rejected: {err:?}");
                log::warn!("runtime App command rejected: stop drive: {err:?}");
            }
        }
        self.mark_ui_dirty();
    }

    fn stop_joint(&mut self, joint_arg: u32) {
        let Some(joint) = Self::joint_arg_to_index(joint_arg) else {
            return;
        };
        let _ = self.arm("stop joint", ArmCommand::Stop { joint });
    }

    fn spin_joint(&mut self, joint_arg: u32, direction: i8) {
        let Some(joint) = Self::joint_arg_to_index(joint_arg) else {
            return;
        };
        let _ = self.start_joint_jog("spin joint", joint, direction);
    }

    fn set_joint_zero(&mut self, joint_arg: u32) {
        let Some(joint) = Self::joint_arg_to_index(joint_arg) else {
            return;
        };
        let _ = self.arm(
            "move joint to zero",
            ArmCommand::SetJointAngle {
                joint,
                angle_rad: 0.0,
            },
        );
    }

    fn parse_limit_editor(&mut self) -> Option<(usize, i32, i32)> {
        let Some(joint) = self.limit_editor_joint else {
            return None;
        };
        let min = match self.limit_editor_min.trim().parse::<i32>() {
            Ok(value) => value,
            Err(_) => {
                self.limit_editor_error = "min must be an integer".to_string();
                return None;
            }
        };
        let max = match self.limit_editor_max.trim().parse::<i32>() {
            Ok(value) => value,
            Err(_) => {
                self.limit_editor_error = "max must be an integer".to_string();
                return None;
            }
        };
        if min == max {
            self.limit_editor_error = "min and max must differ".to_string();
            return None;
        }
        Some((joint, min, max))
    }

    fn parse_calibration_editor(&mut self) -> Option<(usize, f64)> {
        let Some(joint) = self.calibration_editor_joint else {
            return None;
        };
        let angle_deg = match self.calibration_editor_angle.trim().parse::<f64>() {
            Ok(value) if value.is_finite() => value,
            _ => {
                self.calibration_editor_error = "angle must be a finite number".to_string();
                return None;
            }
        };
        Some((joint, angle_deg))
    }

    fn parse_goto_angle(value: &str, label: &str) -> Result<f64, String> {
        let parsed = value
            .trim()
            .parse::<f64>()
            .map_err(|_| format!("{label} angle must be a number"))?;
        if parsed.is_finite() {
            Ok(parsed)
        } else {
            Err(format!("{label} angle must be finite"))
        }
    }

    fn parse_goto_angles(&mut self) -> Option<[f64; JOINT_COUNT]> {
        let yaw = match Self::parse_goto_angle(&self.goto_angle_yaw, "yaw") {
            Ok(value) => value,
            Err(err) => {
                self.goto_angle_error = err;
                return None;
            }
        };
        let shoulder = match Self::parse_goto_angle(&self.goto_angle_shoulder, "shoulder") {
            Ok(value) => value,
            Err(err) => {
                self.goto_angle_error = err;
                return None;
            }
        };
        let elbow = match Self::parse_goto_angle(&self.goto_angle_elbow, "elbow") {
            Ok(value) => value,
            Err(err) => {
                self.goto_angle_error = err;
                return None;
            }
        };
        let wrist = match Self::parse_goto_angle(&self.goto_angle_wrist, "wrist") {
            Ok(value) => value,
            Err(err) => {
                self.goto_angle_error = err;
                return None;
            }
        };
        self.goto_angle_error.clear();
        Some([
            yaw.to_radians(),
            shoulder.to_radians(),
            elbow.to_radians(),
            wrist.to_radians(),
        ])
    }

    fn parse_coordinate(value: &str, label: &str) -> Result<f64, String> {
        let parsed = value
            .trim()
            .parse::<f64>()
            .map_err(|_| format!("{label} must be a number"))?;
        if parsed.is_finite() {
            Ok(parsed)
        } else {
            Err(format!("{label} must be finite"))
        }
    }

    fn parse_coordinates(&mut self) -> Option<(f64, f64, f64)> {
        let x = match Self::parse_coordinate(&self.coordinate_x, "x") {
            Ok(value) => value,
            Err(err) => {
                self.coordinate_error = err;
                return None;
            }
        };
        let y = match Self::parse_coordinate(&self.coordinate_y, "y") {
            Ok(value) => value,
            Err(err) => {
                self.coordinate_error = err;
                return None;
            }
        };
        let z = match Self::parse_coordinate(&self.coordinate_z, "z") {
            Ok(value) => value,
            Err(err) => {
                self.coordinate_error = err;
                return None;
            }
        };
        self.coordinate_error.clear();
        Some((x, y, z))
    }

    fn parse_arm_speed(&mut self) -> Option<i16> {
        let trimmed = self.arm_speed.trim();
        let speed = match trimmed.parse::<i16>() {
            Ok(value) if value >= 0 => value,
            _ => {
                self.arm_speed_error = "speed must be a non-negative whole number".to_string();
                return None;
            }
        };
        self.arm_speed_error.clear();
        Some(speed)
    }

    fn apply_arm_speed(&mut self) {
        let Some(speed) = self.parse_arm_speed() else {
            self.mark_ui_dirty();
            return;
        };
        let _ = self.arm("set arm speed", ArmCommand::SetSpeed(speed));
    }

    fn nudge_limit_editor(&mut self, min_delta: i32, max_delta: i32) {
        let Some((_, min, max)) = self.parse_limit_editor() else {
            return;
        };
        self.limit_editor_min = (min + min_delta).to_string();
        self.limit_editor_max = (max + max_delta).to_string();
        self.limit_editor_error.clear();
    }

    fn coordinate_forward_sign(&self) -> f64 {
        f64::from(self.coordinate_calibration().forward_sign)
    }

    fn coordinate_left_sign(&self) -> f64 {
        f64::from(self.coordinate_calibration().left_sign)
    }

    fn coordinate_base_yaw_offset_deg(&self) -> f64 {
        self.coordinate_calibration().base_yaw_offset_deg
    }

    fn coordinate_jog_direction(&self, dx: f64, dy: f64, dz_table: f64) -> [f64; 3] {
        // Coordinate Move uses PuppyBot body axes (+X forward, +Y left, +Z up).
        // The controller consumes arm-base vectors, so the calibrated robot-to-arm
        // mount transform is applied exactly once before issuing an immutable Base jog.
        let (dx, dy) = rotate_xy_deg(dx, dy, self.coordinate_base_yaw_offset_deg());
        [dx, dy, dz_table]
    }

    fn start_tcp_jog(
        &mut self,
        label: &str,
        frame: TcpFrame,
        direction: [f64; 3],
    ) -> Result<(), ControllerError> {
        // A free-spin command must never survive a transition into TCP control.
        // Stop it explicitly before changing the arm mode; `StartTcpJog` itself
        // only changes the controller mode and does not constitute a per-joint
        // free-spin stop command.
        if let Some(held) = self.held_joint_jog.take() {
            let _ = self.arm(
                "stop joint jog before tcp jog",
                ArmCommand::Stop { joint: held.joint },
            );
        }
        self.arm(label, ArmCommand::StartTcpJog { frame, direction })?;
        let (refresh_frame, refresh_direction) = match self.robot.arm.mode() {
            ArmMode::TcpJogging {
                frame, direction, ..
            } => (frame, direction),
            _ => (frame, direction),
        };
        self.held_tcp_jog = Some(HeldTcpJog {
            frame: refresh_frame,
            direction: refresh_direction,
            last_refresh_ms: self.now_ms(),
        });
        Ok(())
    }

    fn start_tcp_camera_jog(
        &mut self,
        label: &str,
        camera_direction: TcpCameraJogDirection,
    ) -> Result<(), String> {
        let direction = match &self.backend {
            RuntimeBackend::Simulated(backend) => backend
                .wrist_camera_jog_direction(camera_direction)
                .map_err(|error| format!("TCP camera POV jog unavailable: {error}"))?,
            RuntimeBackend::Hardware { .. } => {
                return Err(
                    "TCP camera POV jog requires --sim and the RobotDreams wrist camera"
                        .to_string(),
                );
            }
        };
        // The camera vector is sampled above, then intentionally issued as an
        // immutable Base jog.  Held refreshes re-send that same vector rather
        // than sampling the moving wrist camera again.
        self.start_tcp_jog(label, TcpFrame::Base, direction)
            .map_err(|error| format!("TCP camera POV jog rejected: {error:?}"))
    }

    fn start_joint_jog(
        &mut self,
        label: &str,
        joint: usize,
        direction: i8,
    ) -> Result<(), ControllerError> {
        let direction = direction.signum();
        let now_ms = self.now_ms();
        self.robot.try_handle_event(
            ProtocolEvent::Arm(ArmCommand::Spin { joint, direction }),
            now_ms,
        )?;
        self.held_joint_jog = Some(HeldJointJog {
            joint,
            direction,
            last_refresh_ms: now_ms,
        });
        self.last_command = label.to_string();
        log::info!("runtime App command: {label}");
        self.mark_ui_dirty();
        self.telemetry_seq = self.telemetry_seq.wrapping_add(1);
        Ok(())
    }

    fn move_to_goto_angles(&mut self, label: &str) {
        let Some(angles_rad) = self.parse_goto_angles() else {
            self.mark_ui_dirty();
            return;
        };
        if self.arm(label, ArmCommand::GotoAngles(angles_rad)).is_ok() {
            self.sync_coordinates_from_target();
        }
    }

    fn move_to_default_goto_angles(&mut self) {
        self.goto_angle_yaw = format!("{DEFAULT_GOTO_ANGLE_DEG:.1}");
        self.goto_angle_shoulder = format!("{DEFAULT_GOTO_ANGLE_DEG:.1}");
        self.goto_angle_elbow = format!("{DEFAULT_GOTO_ANGLE_DEG:.1}");
        self.goto_angle_wrist = format!("{DEFAULT_GOTO_ANGLE_DEG:.1}");
        self.goto_angle_error.clear();
        self.move_to_goto_angles("move to default target angles");
    }

    fn sync_goto_angles_from_targets(&mut self) {
        let joints = self.robot.arm.joints;
        if let Some(angles) = target_angle_inputs(&joints) {
            self.goto_angle_yaw = angles[0].clone();
            self.goto_angle_shoulder = angles[1].clone();
            self.goto_angle_elbow = angles[2].clone();
            self.goto_angle_wrist = angles[3].clone();
            self.goto_angle_error.clear();
        }
    }

    fn sync_coordinates_from_target(&mut self) {
        if let Some(coords_mm) = self.robot.arm.target_coords_mm() {
            let (x, y, z) = format_coordinate_inputs(coords_mm);
            self.coordinate_x = x;
            self.coordinate_y = y;
            self.coordinate_z = z;
            self.coordinate_error.clear();
        }
    }

    fn move_to_coordinate_target(
        &mut self,
        label: &str,
        x: f64,
        y: f64,
        z_table: f64,
        tool_phi_rad: f64,
    ) {
        self.coordinate_x = format!("{x:.1}");
        self.coordinate_y = format!("{y:.1}");
        self.coordinate_z = format!("{z_table:.1}");
        self.coordinate_error.clear();
        if self
            .arm(
                label,
                ArmCommand::GotoCoords {
                    x,
                    y,
                    z: kinematics::table_to_shoulder_z(z_table),
                    tool_phi_rad,
                },
            )
            .is_ok()
        {
            self.sync_goto_angles_from_targets();
        }
    }

    fn open_joint_calibration(&mut self, joint_arg: u32) {
        if self.backend.is_simulated() {
            self.last_command =
                "simulation model mapping is session-only and cannot be edited".to_string();
            self.calibration_editor_joint = None;
            self.mark_ui_dirty();
            return;
        }
        let Some(joint_index) = Self::joint_arg_to_index(joint_arg) else {
            return;
        };
        let joint = &self.robot.arm.joints[joint_index];
        self.calibration_editor_joint = Some(joint_index);
        self.calibration_editor_angle = joint
            .angle_deg()
            .map(|angle| format!("{angle:.1}"))
            .unwrap_or_else(|| "0.0".to_string());
        self.calibration_editor_error.clear();
        self.mark_ui_dirty();
    }

    fn close_joint_calibration(&mut self) {
        self.calibration_editor_joint = None;
        self.calibration_editor_error.clear();
        self.mark_ui_dirty();
    }

    fn apply_joint_calibration(&mut self) {
        if self.backend.is_simulated() {
            self.last_command =
                "simulation model mapping is session-only and cannot be edited".to_string();
            self.calibration_editor_joint = None;
            self.mark_ui_dirty();
            return;
        }
        let Some((joint, angle_deg)) = self.parse_calibration_editor() else {
            self.mark_ui_dirty();
            return;
        };
        if self.set_joint_reference_angle(joint, angle_deg).is_ok() {
            self.calibration_editor_joint = None;
            self.calibration_editor_error.clear();
        }
        self.mark_ui_dirty();
    }

    fn set_joint_reference_angle(&mut self, joint: usize, angle_deg: f64) -> Result<(), String> {
        if self.backend.is_simulated() {
            let err = "simulation model mapping is session-only and cannot be edited".to_string();
            self.calibration_editor_error = err.clone();
            self.last_command = err.clone();
            self.mark_ui_dirty();
            return Err(err);
        }
        if joint >= JOINT_COUNT {
            return Err("invalid joint".to_string());
        }
        let arm_joint = &self.robot.arm.joints[joint];
        if let Some(err) = joint_reference_tick_error(arm_joint) {
            self.calibration_editor_error = err;
            self.mark_ui_dirty();
            return Err("joint reference requires current feedback".to_string());
        }
        let Some(tick) = arm_joint.tick else {
            self.calibration_editor_error = "current tick unavailable".to_string();
            self.mark_ui_dirty();
            return Err("joint reference requires current feedback".to_string());
        };

        self.arm(
            &format!(
                "calibrate {} reference angle",
                ARM_JOINT_LABELS[joint].to_lowercase()
            ),
            ArmCommand::SetJointReference {
                joint,
                tick,
                angle_rad: angle_deg.to_radians(),
            },
        )
        .map_err(|err| format!("{err:?}"))
    }

    fn flip_joint_angle_sign(&mut self) {
        let Some(joint) = self.calibration_editor_joint else {
            return;
        };
        let _ = self.flip_joint_angle_sign_for(joint);
    }

    fn flip_joint_angle_sign_for(&mut self, joint: usize) -> Result<(), String> {
        if self.backend.is_simulated() {
            let err =
                "simulation model mapping is session-only and its angle sign cannot be flipped"
                    .to_string();
            self.calibration_editor_error = err.clone();
            self.last_command = err.clone();
            self.mark_ui_dirty();
            return Err(err);
        }
        if joint >= JOINT_COUNT {
            self.calibration_editor_error = "invalid joint".to_string();
            self.mark_ui_dirty();
            return Err("invalid joint".to_string());
        }

        self.sync_arm_calibration_from_robot();
        let new_sign = {
            let config_joint = &mut self.active_config.arm.joints[joint];
            config_joint.angle_sign = -config_joint.angle_sign;
            config_joint.angle_sign
        };
        match Puppybot::new_with_config(&self.active_config, self.now_ms()) {
            Ok(robot) => {
                self.robot = robot;
                self.calibration_dirty = true;
                self.calibration_editor_error.clear();
                self.last_command = format!(
                    "flipped {} angle sign to {new_sign}",
                    ARM_JOINT_LABELS[joint].to_lowercase()
                );
                log::info!("runtime App command: {}", self.last_command);
                self.mark_ui_dirty();
                Ok(())
            }
            Err(err) => {
                self.calibration_editor_error =
                    format!("invalid calibration after sign flip: {err}");
                self.last_command = self.calibration_editor_error.clone();
                self.mark_ui_dirty();
                Err(self.calibration_editor_error.clone())
            }
        }
    }

    fn set_goto_angles_current(&mut self) {
        let joints = self.robot.arm.joints;
        let mut angles = [0.0; JOINT_COUNT];
        for (index, joint) in joints.iter().enumerate() {
            let Some(angle) = joint.angle_deg() else {
                self.goto_angle_error = format!(
                    "current {} angle unavailable",
                    ARM_JOINT_LABELS[index].to_lowercase()
                );
                self.mark_ui_dirty();
                return;
            };
            angles[index] = angle;
        }
        self.goto_angle_yaw = format!("{:.1}", angles[0]);
        self.goto_angle_shoulder = format!("{:.1}", angles[1]);
        self.goto_angle_elbow = format!("{:.1}", angles[2]);
        self.goto_angle_wrist = format!("{:.1}", angles[3]);
        self.goto_angle_error.clear();
        self.mark_ui_dirty();
    }

    fn set_tcp_frame(&mut self, frame: TcpFrame) {
        self.tcp_frame = frame;
        self.last_command = format!("set tcp jog frame {}", frame_label(frame).to_lowercase());
        log::info!("runtime App command: {}", self.last_command);
        self.mark_ui_dirty();
    }

    fn set_coordinates_current(&mut self) {
        if let Some((x, y, z)) = self.robot.arm.coords_mm() {
            self.coordinate_x = format!("{x:.1}");
            self.coordinate_y = format!("{y:.1}");
            self.coordinate_z = format!("{z:.1}");
            self.coordinate_error.clear();
            let _ = self.arm("set coordinate target to current", ArmCommand::Hold);
            self.sync_goto_angles_from_targets();
        } else {
            self.coordinate_error = "current position unavailable".to_string();
        }
        self.mark_ui_dirty();
    }

    fn move_to_coordinates(&mut self) {
        let Some((x, y, z_table)) = self.parse_coordinates() else {
            self.mark_ui_dirty();
            return;
        };
        self.move_to_coordinate_target(
            "move to coordinates",
            x,
            y,
            z_table,
            kinematics::ARM_TOOL_PHI_RAD,
        );
    }

    fn flip_coordinate_forward_axis(&mut self) {
        self.active_config.coordinate.forward_sign = -self.active_config.coordinate.forward_sign;
        self.calibration_dirty = true;
        self.last_command = format!(
            "flipped coordinate forward sign to {}",
            self.active_config.coordinate.forward_sign
        );
        log::info!("runtime App command: {}", self.last_command);
        self.mark_ui_dirty();
    }

    fn flip_coordinate_left_axis(&mut self) {
        self.active_config.coordinate.left_sign = -self.active_config.coordinate.left_sign;
        self.calibration_dirty = true;
        self.last_command = format!(
            "flipped coordinate left sign to {}",
            self.active_config.coordinate.left_sign
        );
        log::info!("runtime App command: {}", self.last_command);
        self.mark_ui_dirty();
    }

    fn rotate_coordinate_base_frame(&mut self) {
        let offset = (self.active_config.coordinate.base_yaw_offset_deg + 90.0).rem_euclid(360.0);
        self.active_config.coordinate.base_yaw_offset_deg =
            if offset == 360.0 { 0.0 } else { offset };
        self.calibration_dirty = true;
        self.last_command = format!(
            "rotated coordinate base frame to {:.0} deg",
            self.active_config.coordinate.base_yaw_offset_deg
        );
        log::info!("runtime App command: {}", self.last_command);
        self.mark_ui_dirty();
    }

    fn open_limit_editor(&mut self, joint_arg: u32) {
        let Some(joint_index) = Self::joint_arg_to_index(joint_arg) else {
            return;
        };
        let joint = &self.robot.arm.joints[joint_index];
        self.limit_editor_joint = Some(joint_index);
        self.limit_editor_min = joint.limit_min.to_string();
        self.limit_editor_max = joint.limit_max.to_string();
        self.limit_editor_error.clear();
        self.mark_ui_dirty();
    }

    fn close_limit_editor(&mut self) {
        self.limit_editor_joint = None;
        self.limit_editor_error.clear();
        self.mark_ui_dirty();
    }

    fn set_limit_min_current(&mut self) {
        let Some(joint) = self.limit_editor_joint else {
            return;
        };
        if let Some(tick) = self.robot.arm.joints[joint].tick {
            self.limit_editor_min = tick.to_string();
            self.limit_editor_error.clear();
        } else {
            self.limit_editor_error = "no feedback tick for selected joint".to_string();
        }
        self.mark_ui_dirty();
    }

    fn set_limit_max_current(&mut self) {
        let Some(joint) = self.limit_editor_joint else {
            return;
        };
        if let Some(tick) = self.robot.arm.joints[joint].tick {
            self.limit_editor_max = tick.to_string();
            self.limit_editor_error.clear();
        } else {
            self.limit_editor_error = "no feedback tick for selected joint".to_string();
        }
        self.mark_ui_dirty();
    }

    fn toggle_joint_limits(&mut self, joint_arg: u32) {
        let Some(joint) = Self::joint_arg_to_index(joint_arg) else {
            return;
        };
        let enabled = !self.robot.arm.joints[joint].limit_enabled;
        let _ = self.arm(
            if enabled {
                "enable joint limits"
            } else {
                "disable joint limits"
            },
            ArmCommand::SetTickLimitsEnabled { joint, enabled },
        );
    }

    fn apply_limit_editor(&mut self) {
        let Some((joint, min, max)) = self.parse_limit_editor() else {
            self.mark_ui_dirty();
            return;
        };
        let _ = self.arm(
            "set joint limits",
            ArmCommand::SetTickLimits { joint, min, max },
        );
        self.limit_editor_joint = None;
        self.limit_editor_error.clear();
        self.mark_ui_dirty();
    }

    fn handle_click_id(&mut self, id: u32, inx: Option<u32>) -> bool {
        match id {
            SAVE_CALIBRATION_ID => {
                let _ = self.save_calibration();
            }
            DRIVE_STOP_ID => self.stop_drive(),
            OPEN_JOINT_CALIBRATION_ID => self.open_joint_calibration(event_arg(inx)),
            CLOSE_JOINT_CALIBRATION_ID => self.close_joint_calibration(),
            APPLY_JOINT_CALIBRATION_ID => self.apply_joint_calibration(),
            FLIP_JOINT_ANGLE_SIGN_ID => self.flip_joint_angle_sign(),
            STOP_JOINT_ID => self.stop_joint(event_arg(inx)),
            SET_GOTO_ANGLES_CURRENT_ID => self.set_goto_angles_current(),
            SET_ARM_SPEED_ID => self.apply_arm_speed(),
            SET_TCP_FRAME_BASE_ID => self.set_tcp_frame(TcpFrame::Base),
            SET_TCP_FRAME_TOOL_ID => self.set_tcp_frame(TcpFrame::Tool),
            SET_COORDINATES_CURRENT_ID => self.set_coordinates_current(),
            MOVE_TO_COORDINATES_ID => self.move_to_coordinates(),
            PREVIEW_COORDINATES_ID => {
                self.coordinate_preview_open = true;
            }
            CLOSE_COORDINATE_PREVIEW_ID => {
                self.coordinate_preview_open = false;
            }
            FLIP_COORDINATE_FORWARD_AXIS_ID => self.flip_coordinate_forward_axis(),
            FLIP_COORDINATE_LEFT_AXIS_ID => self.flip_coordinate_left_axis(),
            ROTATE_COORDINATE_BASE_FRAME_ID => self.rotate_coordinate_base_frame(),
            ARM_HOLD_ID => {
                let _ = self.arm("arm hold", ArmCommand::Hold);
            }
            ARM_STOP_ALL_ID => {
                let _ = self.arm("arm stop all", ArmCommand::StopAll);
            }
            CLEAR_ARM_FAULTS_ID => {
                let _ = self.arm("clear arm faults", ArmCommand::ClearFaults { joint: None });
            }
            OPEN_LIMIT_EDITOR_ID => self.open_limit_editor(event_arg(inx)),
            CLOSE_LIMIT_EDITOR_ID => self.close_limit_editor(),
            LIMIT_MIN_DOWN_ID => self.nudge_limit_editor(-UI_LIMIT_STEP_TICKS, 0),
            LIMIT_MIN_UP_ID => self.nudge_limit_editor(UI_LIMIT_STEP_TICKS, 0),
            LIMIT_MAX_DOWN_ID => self.nudge_limit_editor(0, -UI_LIMIT_STEP_TICKS),
            LIMIT_MAX_UP_ID => self.nudge_limit_editor(0, UI_LIMIT_STEP_TICKS),
            SET_LIMIT_MIN_CURRENT_ID => self.set_limit_min_current(),
            SET_LIMIT_MAX_CURRENT_ID => self.set_limit_max_current(),
            TOGGLE_JOINT_LIMITS_ID => self.toggle_joint_limits(event_arg(inx)),
            APPLY_LIMIT_EDITOR_ID => self.apply_limit_editor(),
            _ => return false,
        }
        true
    }

    fn handle_press_id(&mut self, id: u32, inx: Option<u32>) -> bool {
        match id {
            DRIVE_FORWARD_ID => self.drive("drive forward", UI_DRIVE_SPEED, 0),
            DRIVE_BACK_ID => self.drive("drive back", -UI_DRIVE_SPEED, 0),
            DRIVE_LEFT_ID => self.drive("drive left", 0, -UI_STEER_SPEED),
            DRIVE_RIGHT_ID => self.drive("drive right", 0, UI_STEER_SPEED),
            SET_JOINT_ZERO_ID => self.set_joint_zero(event_arg(inx)),
            JOG_NEGATIVE_ID => self.spin_joint(event_arg(inx), -1),
            JOG_POSITIVE_ID => self.spin_joint(event_arg(inx), 1),
            GOTO_DEFAULT_ANGLES_ID => self.move_to_default_goto_angles(),
            GOTO_ANGLES_ID => self.move_to_goto_angles("move to target angles"),
            MOVE_TCP_FORWARD_ID => {
                let _ = self.start_tcp_jog("move tcp forward", self.tcp_frame, [1.0, 0.0, 0.0]);
            }
            MOVE_TCP_BACK_ID => {
                let _ = self.start_tcp_jog("move tcp back", self.tcp_frame, [-1.0, 0.0, 0.0]);
            }
            MOVE_TCP_LEFT_ID => {
                let _ = self.start_tcp_jog("move tcp left", self.tcp_frame, [0.0, 1.0, 0.0]);
            }
            MOVE_TCP_RIGHT_ID => {
                let _ = self.start_tcp_jog("move tcp right", self.tcp_frame, [0.0, -1.0, 0.0]);
            }
            MOVE_TCP_CAMERA_FORWARD_ID => {
                let _ = self.start_tcp_camera_jog(
                    "move TCP camera POV forward (into view)",
                    TcpCameraJogDirection::Forward,
                );
            }
            MOVE_TCP_CAMERA_BACK_ID => {
                let _ = self.start_tcp_camera_jog(
                    "move TCP camera POV back (away)",
                    TcpCameraJogDirection::Back,
                );
            }
            MOVE_TCP_CAMERA_LEFT_ID => {
                let _ = self.start_tcp_camera_jog(
                    "move TCP camera POV screen left",
                    TcpCameraJogDirection::Left,
                );
            }
            MOVE_TCP_CAMERA_RIGHT_ID => {
                let _ = self.start_tcp_camera_jog(
                    "move TCP camera POV screen right",
                    TcpCameraJogDirection::Right,
                );
            }
            MOVE_TCP_CAMERA_UP_ID => {
                let _ = self.start_tcp_camera_jog(
                    "move TCP camera POV screen up",
                    TcpCameraJogDirection::Up,
                );
            }
            MOVE_TCP_CAMERA_DOWN_ID => {
                let _ = self.start_tcp_camera_jog(
                    "move TCP camera POV screen down",
                    TcpCameraJogDirection::Down,
                );
            }
            COORDINATE_FORWARD_ID => {
                let direction =
                    self.coordinate_jog_direction(self.coordinate_forward_sign(), 0.0, 0.0);
                let _ = self.start_tcp_jog("coordinate forward", TcpFrame::Base, direction);
            }
            COORDINATE_BACK_ID => {
                let direction =
                    self.coordinate_jog_direction(-self.coordinate_forward_sign(), 0.0, 0.0);
                let _ = self.start_tcp_jog("coordinate back", TcpFrame::Base, direction);
            }
            COORDINATE_LEFT_ID => {
                let direction =
                    self.coordinate_jog_direction(0.0, self.coordinate_left_sign(), 0.0);
                let _ = self.start_tcp_jog("coordinate left", TcpFrame::Base, direction);
            }
            COORDINATE_RIGHT_ID => {
                let direction =
                    self.coordinate_jog_direction(0.0, -self.coordinate_left_sign(), 0.0);
                let _ = self.start_tcp_jog("coordinate right", TcpFrame::Base, direction);
            }
            COORDINATE_UP_ID => {
                let _ = self.start_tcp_jog("coordinate up", TcpFrame::Base, [0.0, 0.0, 1.0]);
            }
            COORDINATE_DOWN_ID => {
                let _ = self.start_tcp_jog("coordinate down", TcpFrame::Base, [0.0, 0.0, -1.0]);
            }
            _ => return false,
        }
        true
    }

    fn handle_release_id(&mut self, id: u32, inx: Option<u32>) -> bool {
        match id {
            DRIVE_STOP_ID => self.stop_drive(),
            SET_JOINT_ZERO_ID | JOG_STOP_ID => self.stop_joint(event_arg(inx)),
            GOTO_ANGLES_ID => {
                let _ = self.arm("stop target angles", ArmCommand::StopAll);
            }
            MOVE_TCP_STOP_ID => {
                self.held_tcp_jog = None;
                let _ = self.arm("stop tcp jog", ArmCommand::StopTcpJog);
            }
            _ => return false,
        }
        true
    }

    fn handle_text_id(&mut self, id: u32, value: String) -> bool {
        match id {
            EDIT_JOINT_REFERENCE_ANGLE_ID => {
                self.calibration_editor_angle = value;
                self.calibration_editor_error.clear();
                self.mark_ui_dirty();
            }
            EDIT_GOTO_ANGLE_YAW_ID => {
                self.goto_angle_yaw = value;
                self.goto_angle_error.clear();
                self.mark_ui_dirty();
            }
            EDIT_GOTO_ANGLE_SHOULDER_ID => {
                self.goto_angle_shoulder = value;
                self.goto_angle_error.clear();
                self.mark_ui_dirty();
            }
            EDIT_GOTO_ANGLE_ELBOW_ID => {
                self.goto_angle_elbow = value;
                self.goto_angle_error.clear();
                self.mark_ui_dirty();
            }
            EDIT_GOTO_ANGLE_WRIST_ID => {
                self.goto_angle_wrist = value;
                self.goto_angle_error.clear();
                self.mark_ui_dirty();
            }
            EDIT_ARM_SPEED_ID => {
                self.arm_speed = value;
                self.arm_speed_error.clear();
                self.mark_ui_dirty();
            }
            EDIT_COORDINATE_X_ID => {
                self.coordinate_x = value;
                self.coordinate_error.clear();
                self.mark_ui_dirty();
            }
            EDIT_COORDINATE_Y_ID => {
                self.coordinate_y = value;
                self.coordinate_error.clear();
                self.mark_ui_dirty();
            }
            EDIT_COORDINATE_Z_ID => {
                self.coordinate_z = value;
                self.coordinate_error.clear();
                self.mark_ui_dirty();
            }
            EDIT_LIMIT_MIN_ID => {
                self.limit_editor_min = value;
                self.limit_editor_error.clear();
                self.mark_ui_dirty();
            }
            EDIT_LIMIT_MAX_ID => {
                self.limit_editor_max = value;
                self.limit_editor_error.clear();
                self.mark_ui_dirty();
            }
            _ => return false,
        }
        true
    }

    async fn render_client(&mut self, client_id: usize) {
        self.wgui.set_title(client_id, "PuppyBot").await;
        self.wgui.render(client_id, self.render_item()).await;
    }

    async fn render(&mut self) {
        if self.client_ids.is_empty() {
            self.ui_dirty = false;
            return;
        }

        let title = "PuppyBot";
        let item = self.render_item();
        let client_ids = self.client_ids.iter().copied().collect::<Vec<_>>();

        for client_id in client_ids {
            self.wgui.set_title(client_id, title).await;
            self.wgui.render(client_id, item.clone()).await;
        }

        self.last_render_at = Instant::now();
        self.ui_dirty = false;
    }

    async fn render_maybe(&mut self) {
        if !self.ui_dirty {
            return;
        }

        if self.last_render_at.elapsed().as_millis() < UI_RENDER_INTERVAL_MS as u128 {
            return;
        }

        self.render().await;
    }

    async fn handle_wgui_message(&mut self, message: ClientMessage) {
        let client_id = message.client_id;

        match message.event {
            ClientEvent::Connected { .. } => {
                self.client_ids.insert(client_id);
                self.render_client(client_id).await;
            }
            ClientEvent::Disconnected { .. } => {
                self.client_ids.remove(&client_id);
                // A UI connection may have been holding a free-spin button.
                // There is no reliable release event after a disconnect, so a
                // disconnect always stops any active held joint jog.
                if let Some(held) = self.held_joint_jog {
                    let _ = self.arm(
                        "stop joint jog on ui disconnect",
                        ArmCommand::Stop { joint: held.joint },
                    );
                }
                if self.held_tcp_jog.is_some() {
                    let _ = self.arm("stop TCP jog on ui disconnect", ArmCommand::StopTcpJog);
                }
                self.clear_keyboard_drive();
                if self.client_ids.is_empty() {
                    self.stop_robot();
                } else {
                    self.mark_ui_dirty();
                }
            }
            ClientEvent::Refresh | ClientEvent::PathChanged(_) => {
                self.render_client(client_id).await;
            }
            ClientEvent::Input(_) => {}
            ClientEvent::OnClick(event) => {
                if !self.handle_click_id(event.id, event.inx) {
                    log::debug!("unhandled wgui click id={} inx={:?}", event.id, event.inx);
                }
            }
            ClientEvent::OnPress(event) => {
                if !self.handle_press_id(event.id, event.inx) {
                    log::debug!("unhandled wgui press id={} inx={:?}", event.id, event.inx);
                }
            }
            ClientEvent::OnRelease(event) => {
                if !self.handle_release_id(event.id, event.inx) {
                    log::debug!("unhandled wgui release id={} inx={:?}", event.id, event.inx);
                }
            }
            // PuppyBot hold controls are press-to-start and release-to-stop.
            // Ignore repeats from stale browser clients so they can never
            // renew a command or clear controller safety state.
            ClientEvent::OnRepeat(event) => {
                log::debug!("ignored wgui repeat id={} inx={:?}", event.id, event.inx);
            }
            ClientEvent::OnKeyDown(event) => {
                if !self.set_keyboard_drive_key(&event.keycode, true) {
                    log::debug!("wgui key down key={} id={:?}", event.keycode, event.id);
                }
            }
            ClientEvent::OnKeyUp(event) => {
                if !self.set_keyboard_drive_key(&event.keycode, false) {
                    log::debug!("wgui key up key={} id={:?}", event.keycode, event.id);
                }
            }
            ClientEvent::OnTextChanged(event) => {
                if !self.handle_text_id(event.id, event.value) {
                    log::debug!(
                        "unhandled wgui text changed id={} inx={:?}",
                        event.id,
                        event.inx
                    );
                }
            }
            ClientEvent::OnSliderChange(event) => {
                log::debug!(
                    "wgui slider changed id={} inx={:?} value={}",
                    event.id,
                    event.inx,
                    event.value
                );
                self.mark_ui_dirty();
            }
            ClientEvent::OnSelect(event) => {
                log::debug!(
                    "wgui select id={} inx={:?} value={:?}",
                    event.id,
                    event.inx,
                    event.value
                );
                self.mark_ui_dirty();
            }
            _ => {}
        }
    }

    async fn handle_ws_event(&mut self, server: &http::HttpServer, event: http::HttpEvent) {
        match event {
            http::HttpEvent::WebSocketConnected { client_id } => {
                self.ws_clients.insert(
                    client_id,
                    WsClientState {
                        telemetry_enabled: false,
                        last_telemetry_seq: self.telemetry_seq(),
                    },
                );
            }
            http::HttpEvent::WebSocketBinary { client_id, payload } => {
                let mut telemetry_enabled = self
                    .ws_clients
                    .get(&client_id)
                    .map(|client| client.telemetry_enabled)
                    .unwrap_or(false);

                let response = self.handle_binary_command(&payload, &mut telemetry_enabled);

                if let Some(client) = self.ws_clients.get_mut(&client_id) {
                    client.telemetry_enabled = telemetry_enabled;
                }

                if let Some(response) = response {
                    server.send_binary(client_id, response).await;
                }
            }
            http::HttpEvent::WebSocketText { client_id, payload } if payload == b"ping" => {
                server.send_text(client_id, b"pong".to_vec()).await;
            }
            http::HttpEvent::HttpRequest {
                request_id,
                method,
                target,
                body,
            } => {
                let response = self.handle_api_request(&method, &target, &body);
                server
                    .send_http_response(
                        request_id,
                        response.status,
                        response.content_type,
                        response.body,
                    )
                    .await;
            }
            http::HttpEvent::WebSocketClosed { client_id } => {
                self.ws_clients.remove(&client_id);
            }
            _ => {}
        }
    }

    async fn send_ws_telemetry(&mut self, server: &http::HttpServer) {
        let telemetry_seq = self.telemetry_seq();
        let client_ids = self
            .ws_clients
            .iter_mut()
            .filter_map(|(client_id, client)| {
                if !client.telemetry_enabled || client.last_telemetry_seq == telemetry_seq {
                    return None;
                }
                client.last_telemetry_seq = telemetry_seq;
                Some(*client_id)
            })
            .collect::<Vec<_>>();

        if client_ids.is_empty() {
            return;
        }

        let frame = self.arm_state_frame();
        for client_id in client_ids {
            server.send_binary(client_id, frame.clone()).await;
        }
    }

    pub async fn run(&mut self) -> Result<(), String> {
        let mut ws = http::start_app_server(self.ws_bind_addr).map_err(|err| err.to_string())?;
        let ws_addr = ws.local_addr();
        let _mdns = mdns::start_advertisement(ws_addr.port());
        log::info!(
            "puppybot runtime websocket listening on {}",
            local_url(ws_addr, "ws", "/ws")
        );
        log::info!("puppybot runtime WGUI listening on configured UI bind");
        log::info!("set PUPPYBOT_RUNTIME_ADDR=127.0.0.1:8080 to bind another address");

        let mut robot_tick = time::interval(Duration::from_millis(ROBOT_TICK_MS));
        robot_tick.set_missed_tick_behavior(MissedTickBehavior::Skip);

        loop {
            tokio::select! {
                message = self.wgui.next() => {
                    let Some(message) = message else {
                        break;
                    };

                    self.handle_wgui_message(message).await;
                }
                event = ws.next() => {
                    let Some(event) = event else {
                        break;
                    };

                    self.handle_ws_event(&ws, event).await;
                }
                _ = robot_tick.tick() => {
                    self.tick_robot().await;
                    self.mark_ui_dirty();
                }
            }
            self.send_ws_telemetry(&ws).await;
            self.render_maybe().await;
        }

        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use puppybot_core::protocol::{
        CMD_CONFIG_GET, CMD_CONFIG_SET, CMD_DRIVE_STEER, CMD_SUBSCRIBE,
        SUBSCRIPTION_TOPIC_ARM_STATE, command_frame,
    };

    #[tokio::test]
    async fn api_state_json_reports_runtime_state() {
        let config_path = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("puppybot.json");
        let mut app = App::with_options(AppOptions {
            config: Some(config_path.display().to_string()),
            servo_device: None,
            simulated: true,
            robotdreams_project: None,
            ui_bind: Some("127.0.0.1:0".parse().unwrap()),
            ws_bind: Some("127.0.0.1:0".parse().unwrap()),
        })
        .expect("simulated runtime app");

        for _ in 0..8 {
            app.last_tick_at = Instant::now() - Duration::from_millis(ROBOT_TICK_MS);
            app.tick_robot().await;
        }
        let state: serde_json::Value =
            serde_json::from_str(&app.api_state_json().expect("api state json"))
                .expect("valid state json");

        assert_eq!(state["mode"], "simulation");
        assert!(state["timeMs"].is_number());
        assert_eq!(
            state["arm"]["joints"].as_array().expect("joints").len(),
            JOINT_COUNT
        );
        for (index, joint) in state["arm"]["joints"]
            .as_array()
            .expect("joints")
            .iter()
            .enumerate()
        {
            assert_eq!(joint["name"], ARM_JOINT_LABELS[index].to_ascii_lowercase());
            assert_eq!(
                joint["tick"],
                app.active_config.arm.joints[index].reference_tick
            );
            assert!((joint["angleDeg"].as_f64().expect("controller angle") - 90.0).abs() < 1.0e-9);
            assert!(joint.get("referenceTick").is_none());
            assert!(joint.get("urdfAngleDeg").is_none());
        }
        assert!(state["arm"].get("currentTcpMm").is_some());
        assert!(state["arm"].get("targetTcpMm").is_some());
        assert_eq!(state["arm"]["frame"], "armBase");
        assert_eq!(state["arm"]["unit"], "mm");
        assert_eq!(state["arm"]["targetTcpMm"], serde_json::Value::Null);
        assert_eq!(
            state["arm"]["effectiveTargetTcpMm"],
            state["arm"]["currentTcpMm"]
        );
        assert!(state["drive"].get("leftSpeed").is_some());
        assert_eq!(state["sim"]["enabled"], true);
        assert_eq!(state["sim"]["manipulation"]["simulationOnly"], true);
        assert_eq!(state["sim"]["manipulation"]["action"], "Interact");
        assert_eq!(state["sim"]["manipulation"]["ball"]["objectId"], "ball");
        assert_eq!(
            state["sim"]["manipulation"]["binTrigger"]["source"],
            "RobotDreams physics trigger"
        );
        assert!(state["sim"]["captureState"]["frames"][0]["manipulation"].is_object());
        assert!(state["sim"]["markers"].is_array());
        let marker = &state["sim"]["markers"].as_array().expect("sim markers")[0];
        assert_eq!(marker["targetTcp"], serde_json::Value::Null);
        assert_eq!(marker["frame"], "world");
        assert_eq!(marker["unit"], "m");
        assert_eq!(state["sim"]["frames"]["worldFromBase"]["fromFrame"], "base");
        assert_eq!(state["sim"]["frames"]["worldFromBase"]["toFrame"], "world");
        assert_eq!(
            state["sim"]["frames"]["baseFromArmBase"]["fromFrame"],
            "armBase"
        );
        assert_eq!(state["sim"]["frames"]["baseFromArmBase"]["toFrame"], "base");
        assert!(state["sim"]["frames"]["worldFromBase"]["translationM"].is_array());
        assert!(state["sim"]["frames"]["baseFromArmBase"]["rotationMatrix"].is_array());
        assert_eq!(state["ui"]["coordinateFrame"], "Robot Base");
        assert_eq!(state["ui"]["absoluteCoordinateFrame"], "Arm Base");
    }

    fn test_app() -> App {
        App::with_options(AppOptions {
            config: None,
            servo_device: None,
            simulated: true,
            robotdreams_project: None,
            ui_bind: Some("127.0.0.1:0".parse().unwrap()),
            ws_bind: Some("127.0.0.1:0".parse().unwrap()),
        })
        .expect("simulated runtime app")
    }

    fn assert_close(actual: f64, expected: f64) {
        assert!(
            (actual - expected).abs() < 1.0e-9,
            "expected {expected}, got {actual}"
        );
    }

    fn project_body_vector_to_screen(
        vector: [f64; 2],
        screen_right: [f64; 2],
        screen_up: [f64; 2],
    ) -> [f64; 2] {
        [
            vector[0] * screen_right[0] + vector[1] * screen_right[1],
            vector[0] * screen_up[0] + vector[1] * screen_up[1],
        ]
    }

    #[tokio::test]
    async fn coordinate_jog_calibration_maps_body_axes_through_arm_base_mount() {
        let runtime_config = config::load_runtime_config(
            &std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("puppybot.json"),
        )
        .expect("load PuppyBot runtime config")
        .expect("PuppyBot runtime config exists");
        let model: serde_json::Value =
            serde_json::from_str(include_str!("../../../models/puppybot/robotdreams.json"))
                .expect("parse PuppyBot RobotDreams model profile");
        assert_eq!(model["frameMapping"]["core"]["forwardAxis"], "x");
        assert_eq!(model["frameMapping"]["core"]["leftAxis"], "y");
        assert_eq!(model["frameMapping"]["core"]["upAxis"], "z");
        let arm_base_yaw_rad = model["frames"]["armBase"]["rotation"][2]
            .as_f64()
            .expect("armBase yaw");

        let mut app = test_app();
        app.active_config.coordinate = runtime_config.coordinate;
        let forward_arm = app.coordinate_jog_direction(1.0, 0.0, 0.0);
        let left_arm = app.coordinate_jog_direction(0.0, 1.0, 0.0);
        let (forward_body_x, forward_body_y) = rotate_xy_deg(
            forward_arm[0],
            forward_arm[1],
            arm_base_yaw_rad.to_degrees(),
        );
        let (left_body_x, left_body_y) =
            rotate_xy_deg(left_arm[0], left_arm[1], arm_base_yaw_rad.to_degrees());

        // RobotDreams declares body +X forward and +Y left.  The controller
        // arm-base vectors must transform back to precisely that basis.
        assert_close(forward_body_x, 1.0);
        assert_close(forward_body_y, 0.0);
        assert_close(left_body_x, 0.0);
        assert_close(left_body_y, 1.0);

        // The same fixed body vectors have the intended screen projection in
        // the supplied top and side/oblique views.  Camera motion cannot alter
        // the body vectors that Coordinate Move sends to the controller.
        let top_forward = project_body_vector_to_screen(
            [forward_body_x, forward_body_y],
            [0.0, -1.0],
            [1.0, 0.0],
        );
        let top_left =
            project_body_vector_to_screen([left_body_x, left_body_y], [0.0, -1.0], [1.0, 0.0]);
        assert_close(top_forward[0], 0.0);
        assert_close(top_forward[1], 1.0);
        assert_close(top_left[0], -1.0);
        assert_close(top_left[1], 0.0);

        let oblique_forward =
            project_body_vector_to_screen([forward_body_x, forward_body_y], [1.0, 0.0], [0.0, 1.0]);
        let oblique_left =
            project_body_vector_to_screen([left_body_x, left_body_y], [1.0, 0.0], [0.0, 1.0]);
        assert_close(oblique_forward[0], 1.0);
        assert_close(oblique_forward[1], 0.0);
        assert_close(oblique_left[0], 0.0);
        assert_close(oblique_left[1], 1.0);
    }

    fn assert_hold_event_contract(value: &serde_json::Value, press_count: &mut usize) {
        match value {
            serde_json::Value::Object(object) => {
                if object
                    .get("press")
                    .and_then(serde_json::Value::as_u64)
                    .is_some()
                {
                    *press_count += 1;
                    assert!(
                        object
                            .get("release")
                            .and_then(serde_json::Value::as_u64)
                            .is_some(),
                        "every press-to-start control must define a release-to-stop event: {object:?}"
                    );
                }
                assert!(
                    object
                        .get("repeat")
                        .and_then(serde_json::Value::as_u64)
                        .is_none(),
                    "PuppyBot must not render repeat-command handlers: {object:?}"
                );
                for child in object.values() {
                    assert_hold_event_contract(child, press_count);
                }
            }
            serde_json::Value::Array(array) => {
                for child in array {
                    assert_hold_event_contract(child, press_count);
                }
            }
            _ => {}
        }
    }

    #[tokio::test]
    async fn rendered_hold_controls_pair_press_with_release_and_never_repeat() {
        let app = test_app();
        let rendered = serde_json::to_value(app.render_item()).expect("serialize PuppyBot UI");
        let mut press_count = 0;

        assert_hold_event_contract(&rendered, &mut press_count);

        assert_eq!(press_count, 28, "unexpected PuppyBot hold-control count");
    }

    #[tokio::test]
    async fn goto_press_issues_once_stale_repeats_preserve_stall_and_release_stops() {
        let mut app = test_app();
        let sequence_before = app.telemetry_seq();

        assert!(app.handle_press_id(GOTO_ANGLES_ID, None));
        assert_eq!(app.telemetry_seq(), sequence_before.wrapping_add(1));
        let targets_after_press = app.robot.arm.joints.map(|joint| joint.target_tick);
        assert!(targets_after_press.iter().all(Option::is_some));

        app.robot.arm.joints[0].fault =
            Some(puppybot_core::puppyarm::servo_safety::SafetyFault::Stall);
        app.robot.arm.joints[0].stall_since_ms = Some(1234);
        for (id, inx) in [
            (GOTO_ANGLES_ID, None),
            (GOTO_DEFAULT_ANGLES_ID, None),
            (SET_JOINT_ZERO_ID, Some(1)),
        ] {
            app.handle_wgui_message(ClientMessage {
                client_id: 7,
                event: ClientEvent::OnRepeat(wgui::OnRepeat { id, inx }),
            })
            .await;
            assert_eq!(app.telemetry_seq(), sequence_before.wrapping_add(1));
            assert_eq!(
                app.robot.arm.joints.map(|joint| joint.target_tick),
                targets_after_press
            );
            assert_eq!(
                app.robot.arm.joints[0].fault,
                Some(puppybot_core::puppyarm::servo_safety::SafetyFault::Stall)
            );
            assert_eq!(app.robot.arm.joints[0].stall_since_ms, Some(1234));
        }

        assert!(app.handle_release_id(GOTO_ANGLES_ID, None));
        assert_eq!(app.telemetry_seq(), sequence_before.wrapping_add(2));
        assert!(
            app.robot
                .arm
                .joints
                .iter()
                .all(|joint| joint.target_tick.is_none() && joint.speed == 0)
        );
    }

    #[tokio::test]
    async fn default_and_zero_hold_controls_stop_on_release() {
        let mut default_app = test_app();
        assert!(default_app.handle_press_id(GOTO_DEFAULT_ANGLES_ID, None));
        assert!(
            default_app
                .robot
                .arm
                .joints
                .iter()
                .all(|joint| joint.target_tick.is_some())
        );
        assert!(default_app.handle_release_id(GOTO_ANGLES_ID, None));
        assert!(
            default_app
                .robot
                .arm
                .joints
                .iter()
                .all(|joint| joint.target_tick.is_none() && joint.speed == 0)
        );

        let mut zero_app = test_app();
        for joint in 0..JOINT_COUNT {
            let tick = u16::try_from(zero_app.robot.arm.joints[joint].reference_tick)
                .expect("reference tick is valid");
            zero_app.robot.arm.record_feedback(joint, tick, 0);
        }
        assert!(zero_app.handle_press_id(SET_JOINT_ZERO_ID, Some(1)));
        assert!(zero_app.robot.arm.joints[0].target_tick.is_some());
        assert!(zero_app.handle_release_id(SET_JOINT_ZERO_ID, Some(1)));
        assert_eq!(zero_app.robot.arm.joints[0].target_tick, None);
        assert_eq!(zero_app.robot.arm.joints[0].speed, 0);
    }

    #[tokio::test]
    async fn simulation_calibration_is_session_only_and_cannot_be_mutated_or_saved() {
        let mut physical = PuppybotConfigV1::default();
        for (index, joint) in physical.arm.joints.iter_mut().enumerate() {
            joint.servo_id = (index + 1) as u8;
            joint.reference_tick = (100 + index * 700) as i32;
            joint.reference_angle_rad = -2.0 + index as f64 * 0.6;
            joint.angle_sign = if index % 2 == 0 { -1 } else { 1 };
        }
        let config_path = std::env::temp_dir().join(format!(
            "puppybot-sim-calibration-{}-{}.json",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("system time")
                .as_nanos()
        ));
        let physical_json = config::runtime_config_json(&physical).expect("physical config JSON");
        std::fs::write(&config_path, &physical_json).expect("write physical config fixture");
        let persisted = config::load_runtime_config(&config_path)
            .expect("load round-tripped physical config")
            .expect("physical config exists");

        let mut app = App::with_options(AppOptions {
            config: Some(config_path.display().to_string()),
            servo_device: None,
            simulated: true,
            robotdreams_project: None,
            ui_bind: Some("127.0.0.1:0".parse().unwrap()),
            ws_bind: Some("127.0.0.1:0".parse().unwrap()),
        })
        .expect("simulated runtime app");
        let active = app.active_config.arm.joints;
        assert_eq!(active, persisted.arm.joints);

        let metric = app.calibration_status_metric();
        assert_eq!(metric.label, "Calibration");
        assert_eq!(metric.value, "session mapped");
        assert_eq!(
            metric.detail,
            "Physical controller calibration; RobotDreams mapping is session-only"
        );
        assert!(!metric.save_action);

        app.open_joint_calibration(1);
        assert!(app.calibration_editor_joint.is_none());
        assert!(app.render_calibration_modal().is_none());

        let reference = app.handle_api_request(
            b"POST",
            b"/api/arm/joints/1/reference",
            br#"{"angleDeg":12.0}"#,
        );
        assert_eq!(reference.status, "400 Bad Request");
        let flip = app.handle_api_request(b"POST", b"/api/arm/joints/1/angle-sign/flip", b"");
        assert_eq!(flip.status, "400 Bad Request");
        let save = app.handle_api_request(b"POST", b"/api/calibration/save", b"");
        assert_eq!(save.status, "400 Bad Request");

        let mut telemetry_enabled = false;
        assert!(
            app.handle_binary_command(
                &command_frame(CMD_CONFIG_SET, &[1, 9, 11, 12, 13, 14]),
                &mut telemetry_enabled,
            )
            .is_none()
        );
        assert_eq!(app.active_config.arm.joints, active);
        assert_eq!(
            std::fs::read_to_string(&config_path).expect("physical config remains readable"),
            physical_json
        );

        std::fs::remove_file(config_path).expect("remove physical config fixture");
    }

    fn response_json(response: ApiResponse) -> serde_json::Value {
        serde_json::from_slice(&response.body).expect("json response")
    }

    #[tokio::test]
    async fn capture_api_accepts_bounded_jobs_only_on_loopback() {
        let mut app = test_app();
        let response = app.handle_api_request(b"POST", b"/api/sim/captures/screenshot", br#"{}"#);
        assert_eq!(response.status, "202 Accepted");
        assert_eq!(response.content_type, "application/json; charset=utf-8");
        let body = response_json(response);
        let status_url = body["job"]["status"].as_str().expect("status url");
        let response = app.handle_api_request(b"GET", status_url.as_bytes(), b"");
        assert_eq!(response.status, "200 OK");

        let response =
            app.handle_api_request(b"POST", b"/api/sim/captures/record", br#"{"frames":0}"#);
        assert_eq!(response.status, "400 Bad Request");
        let response =
            app.handle_api_request(b"POST", b"/api/sim/captures/record", br#"{"frames":501}"#);
        assert_eq!(response.status, "400 Bad Request");
        let response = app.handle_api_request(
            b"POST",
            b"/api/sim/captures/record",
            br#"{"frames":2,"camera":"unknown"}"#,
        );
        assert_eq!(response.status, "400 Bad Request");
        let response = app.handle_api_request(
            b"POST",
            b"/api/sim/captures/record",
            br#"{"frames":2,"camera":"tcp"}"#,
        );
        assert_eq!(response.status, "202 Accepted");
        let body = response_json(response);
        let status_url = body["job"]["status"].as_str().expect("record status url");
        let response = app.handle_api_request(b"GET", status_url.as_bytes(), b"");
        assert_eq!(response_json(response)["job"]["camera"], "wrist_camera");
        let response =
            app.handle_api_request(b"POST", b"/api/sim/captures/record", br#"{"frames":2}"#);
        assert_eq!(response.status, "429 Too Many Requests");

        let mut remote = App::with_options(AppOptions {
            config: None,
            servo_device: None,
            simulated: true,
            robotdreams_project: None,
            ui_bind: Some("127.0.0.1:0".parse().unwrap()),
            ws_bind: Some("0.0.0.0:8080".parse().unwrap()),
        })
        .expect("remote-bound simulated app");
        let response =
            remote.handle_api_request(b"POST", b"/api/sim/captures/screenshot", br#"{}"#);
        assert_eq!(response.status, "409 Conflict");
    }

    #[tokio::test]
    async fn simulation_interact_rejects_pickup_far_from_observed_tcp() {
        let mut app = test_app();
        let response = app.handle_api_request(b"POST", b"/api/sim/interact", br#"{}"#);
        assert_eq!(response.status, "409 Conflict");
        let body = response_json(response);
        assert!(
            body["error"]
                .as_str()
                .expect("Interact error")
                .contains("observed TCP")
        );
        let state: serde_json::Value =
            serde_json::from_str(&app.api_state_json().expect("api state json"))
                .expect("valid state json");
        assert_eq!(state["sim"]["manipulation"]["ball"]["attached"], false);
        assert_eq!(
            state["sim"]["manipulation"]["lastAction"],
            serde_json::Value::Null
        );
    }

    #[tokio::test]
    async fn api_command_drive_forward_and_stop_updates_state() {
        let mut app = test_app();

        let response = app.handle_api_request(b"POST", b"/api/drive", br#"{"action":"forward"}"#);
        assert_eq!(response.status, "200 OK");
        let body = response_json(response);
        assert_eq!(body["ok"], true);
        assert_eq!(body["state"]["drive"]["active"], true);
        assert_eq!(body["state"]["drive"]["leftSpeed"], UI_DRIVE_SPEED);
        assert_eq!(body["state"]["drive"]["rightSpeed"], UI_DRIVE_SPEED);

        let response = app.handle_api_request(b"POST", b"/api/drive/stop", b"");
        assert_eq!(response.status, "200 OK");
        let body = response_json(response);
        assert_eq!(body["state"]["drive"]["active"], false);
    }

    #[tokio::test]
    async fn api_command_arm_speed_updates_state() {
        let mut app = test_app();

        let response = app.handle_api_request(b"POST", b"/api/arm/speed", br#"{"speed":123}"#);

        assert_eq!(response.status, "200 OK");
        let body = response_json(response);
        assert_eq!(body["ok"], true);
        assert_eq!(body["state"]["ui"]["armSpeed"], 123);
        assert_eq!(body["state"]["ui"]["lastCommand"], "set arm speed");
    }

    #[tokio::test]
    async fn api_command_coordinate_jog_start_and_stop_updates_arm_state() {
        let mut app = test_app();
        for _ in 0..8 {
            app.tick_robot().await;
        }

        let response = app.handle_api_request(
            b"POST",
            b"/api/arm/coordinate-jog/start",
            br#"{"direction":"up","frame":"base"}"#,
        );
        assert_eq!(response.status, "200 OK");
        let body = response_json(response);
        assert_eq!(body["ok"], true);
        assert_eq!(body["state"]["ui"]["lastCommand"], "http coordinate jog");

        let response = app.handle_api_request(
            b"POST",
            b"/api/arm/coordinate-jog/start",
            br#"{"direction":"forward","frame":"yawFlat"}"#,
        );
        assert_eq!(response.status, "400 Bad Request");

        let response = app.handle_api_request(b"POST", b"/api/arm/tcp-jog/stop", b"");
        assert_eq!(response.status, "200 OK");
        let body = response_json(response);
        assert_eq!(body["state"]["ui"]["lastCommand"], "stop tcp jog");
    }

    #[tokio::test]
    async fn api_command_joint_limits_and_errors_are_reported() {
        let mut app = test_app();

        let response = app.handle_api_request(
            b"POST",
            b"/api/arm/joints/1/limits",
            br#"{"minTick":1000,"maxTick":3000}"#,
        );
        assert_eq!(response.status, "200 OK");
        let body = response_json(response);
        assert_eq!(body["ok"], true);
        assert_eq!(body["state"]["ui"]["lastCommand"], "set joint limits");

        let response = app.handle_api_request(b"POST", b"/api/arm/speed", br#"{"speed":-1}"#);
        assert_eq!(response.status, "400 Bad Request");
        let body = response_json(response);
        assert_eq!(body["ok"], false);

        let response = app.handle_api_request(b"POST", b"/api/arm/nope", b"");
        assert_eq!(response.status, "404 Not Found");

        let response = app.handle_api_request(b"PUT", b"/api/arm/stop", b"");
        assert_eq!(response.status, "405 Method Not Allowed");
    }

    #[tokio::test]
    async fn held_joint_jog_is_refreshed_server_side_and_stops_on_release() {
        let mut app = test_app();

        assert!(app.handle_press_id(JOG_POSITIVE_ID, Some(1)));
        let held = app.held_joint_jog.expect("joint jog hold created on press");
        assert_eq!(held.joint, 0);
        assert_eq!(held.direction, 1);

        let refresh_at = held.last_refresh_ms + HELD_JOINT_JOG_REFRESH_MS;
        app.refresh_held_joint_jog(refresh_at);
        let refreshed = app
            .held_joint_jog
            .expect("joint jog still held after refresh");
        assert_eq!(refreshed.last_refresh_ms, refresh_at);
        assert_eq!(refreshed.joint, 0);
        assert_eq!(refreshed.direction, 1);

        assert!(app.handle_release_id(JOG_STOP_ID, Some(1)));
        assert!(app.held_joint_jog.is_none());
        assert_eq!(app.robot.arm.joints[0].speed, 0);
    }

    #[tokio::test]
    async fn held_coordinate_jog_is_refreshed_server_side_and_stops_on_release() {
        let mut app = test_app();
        for joint in 0..JOINT_COUNT {
            let tick =
                u16::try_from(app.robot.arm.joints[joint].reference_tick).expect("reference tick");
            app.robot.arm.record_feedback(joint, tick, 0);
        }

        assert!(app.handle_press_id(COORDINATE_DOWN_ID, None));
        let held = app.held_tcp_jog.expect("TCP jog hold created on press");
        assert_eq!(held.frame, TcpFrame::Base);
        assert_eq!(held.direction, [0.0, 0.0, -1.0]);

        let refresh_at = held.last_refresh_ms + HELD_JOINT_JOG_REFRESH_MS;
        app.refresh_held_tcp_jog(refresh_at);
        assert_eq!(
            app.held_tcp_jog
                .expect("TCP jog still held after refresh")
                .last_refresh_ms,
            refresh_at
        );

        assert!(app.handle_release_id(MOVE_TCP_STOP_ID, None));
        assert!(app.held_tcp_jog.is_none());
        assert!(
            app.robot
                .arm
                .joints
                .iter()
                .all(|joint| joint.target_tick.is_none() && joint.speed == 0)
        );
    }

    #[tokio::test]
    async fn tcp_camera_pov_buttons_and_api_latch_sampled_wrist_camera_axes() {
        let mut app = test_app();
        for joint in 0..JOINT_COUNT {
            let tick =
                u16::try_from(app.robot.arm.joints[joint].reference_tick).expect("reference tick");
            app.robot.arm.record_feedback(joint, tick, 0);
        }

        let expected_up = match &app.backend {
            RuntimeBackend::Simulated(backend) => backend
                .wrist_camera_jog_direction(TcpCameraJogDirection::Up)
                .expect("sample wrist-camera up"),
            RuntimeBackend::Hardware { .. } => unreachable!("test app is simulated"),
        };
        assert!(app.handle_press_id(MOVE_TCP_CAMERA_UP_ID, None));
        let held = app.held_tcp_jog.expect("camera up creates TCP jog hold");
        assert_eq!(held.frame, TcpFrame::Base);
        assert_eq!(held.direction, expected_up);
        let refresh_at = held.last_refresh_ms + HELD_JOINT_JOG_REFRESH_MS;
        app.refresh_held_tcp_jog(refresh_at);
        assert!(matches!(
            app.robot.arm.mode(),
            ArmMode::TcpJogging {
                frame: TcpFrame::Base,
                direction,
                ..
            } if direction == expected_up
        ));
        assert_eq!(
            app.held_tcp_jog
                .expect("camera direction remains held")
                .direction,
            expected_up,
            "refresh must reuse the sampled base vector rather than re-sampling the moving camera"
        );

        assert!(app.handle_release_id(MOVE_TCP_STOP_ID, None));
        let response = app.handle_api_request(
            b"POST",
            b"/api/arm/tcp-camera-jog/start",
            br#"{"direction":"left"}"#,
        );
        assert_eq!(response.status, "200 OK");
        let expected_left = match &app.backend {
            RuntimeBackend::Simulated(backend) => backend
                .wrist_camera_jog_direction(TcpCameraJogDirection::Left)
                .expect("sample wrist-camera left"),
            RuntimeBackend::Hardware { .. } => unreachable!("test app is simulated"),
        };
        assert!(
            app.held_tcp_jog.is_some_and(
                |held| held.frame == TcpFrame::Base && held.direction == expected_left
            )
        );

        let response = app.handle_api_request(
            b"POST",
            b"/api/arm/tcp-jog/start",
            br#"{"frame":"base","direction":"up"}"#,
        );
        assert_eq!(response.status, "400 Bad Request");
    }

    #[tokio::test]
    async fn held_coordinate_forward_refreshes_immutable_robot_base_direction() {
        let mut app = test_app();
        for joint in 0..JOINT_COUNT {
            let tick =
                u16::try_from(app.robot.arm.joints[joint].reference_tick).expect("reference tick");
            app.robot.arm.record_feedback(joint, tick, 0);
        }
        app.active_config.coordinate.base_yaw_offset_deg = -7.15244988058;

        assert!(app.handle_press_id(COORDINATE_FORWARD_ID, None));
        let held = app.held_tcp_jog.expect("TCP jog hold created on press");
        assert_eq!(held.frame, TcpFrame::Base);
        assert_ne!(held.direction[0], 0.0);
        assert_ne!(held.direction[1], 0.0);

        let refresh_at = held.last_refresh_ms + HELD_JOINT_JOG_REFRESH_MS;
        app.refresh_held_tcp_jog(refresh_at);
        let refreshed = app
            .held_tcp_jog
            .expect("TCP jog remains held after refresh");
        assert_eq!(refreshed.frame, TcpFrame::Base);
        assert_eq!(refreshed.direction, held.direction);
        assert!(matches!(
            app.robot.arm.mode(),
            ArmMode::TcpJogging {
                frame: TcpFrame::Base,
                direction,
                ..
            } if direction == held.direction
        ));
    }

    #[tokio::test]
    async fn api_joint_spin_is_server_held_and_stop_releases_it() {
        let mut app = test_app();

        let response =
            app.handle_api_request(b"POST", b"/api/arm/joints/1/spin", br#"{"direction":1}"#);
        assert_eq!(response.status, "200 OK");
        assert!(
            app.held_joint_jog
                .is_some_and(|held| held.joint == 1 && held.direction == 1)
        );

        let response = app.handle_api_request(b"POST", b"/api/arm/joints/1/stop", b"");
        assert_eq!(response.status, "200 OK");
        assert!(app.held_joint_jog.is_none());
        assert_eq!(app.robot.arm.joints[1].speed, 0);
    }

    #[tokio::test]
    async fn joint_jog_without_server_refresh_expires_at_core_deadman() {
        let mut app = test_app();

        app.start_joint_jog("test joint jog", 0, 1)
            .expect("start joint jog");
        let started_at = app
            .held_joint_jog
            .expect("joint jog hold created")
            .last_refresh_ms;
        // Simulate a server loop failure: firmware feedback is still healthy, but
        // the app no longer renews the free-spin command.
        app.held_joint_jog = None;
        let expired_at =
            started_at + puppybot_core::puppyarm::servo_safety::DEADMAN_CMD_TIMEOUT_MS + 1;
        for joint in 0..JOINT_COUNT {
            let tick = u16::try_from(app.robot.arm.joints[joint].reference_tick)
                .expect("simulated reference tick is within servo range");
            app.robot.arm.record_feedback(joint, tick, expired_at);
        }

        let commands = app.robot.arm.update(expired_at);

        assert!(commands.iter().all(|command| command.speed == 0));
        assert!(matches!(
            app.robot.arm.mode(),
            puppybot_core::puppyarm::types::ArmMode::Fault
        ));
    }

    #[tokio::test]
    async fn ui_disconnect_stops_a_held_joint_jog_even_with_another_client_connected() {
        let mut app = test_app();
        app.client_ids.insert(7);
        app.client_ids.insert(8);
        app.start_joint_jog("test joint jog", 0, 1)
            .expect("start joint jog");

        app.handle_wgui_message(ClientMessage {
            client_id: 7,
            event: ClientEvent::Disconnected { id: 7 },
        })
        .await;

        assert!(app.held_joint_jog.is_none());
        assert_eq!(app.robot.arm.joints[0].speed, 0);
    }

    #[test]
    fn binary_command_parser_ignores_short_payload() {
        let mut robot = Puppybot::new(0);
        let mut telemetry_enabled = false;

        let output =
            handle_binary_command_for_robot(&mut robot, &[1, 2, 3], 10, &mut telemetry_enabled);

        assert_eq!(output, ProtocolOutput::default());
        assert!(!telemetry_enabled);
    }

    #[test]
    fn binary_command_parser_returns_config_response() {
        let mut robot = Puppybot::new(0);
        let mut telemetry_enabled = false;

        let output = handle_binary_command_for_robot(
            &mut robot,
            &command_frame(CMD_CONFIG_GET, &[]),
            10,
            &mut telemetry_enabled,
        );

        assert!(
            output
                .response
                .as_ref()
                .is_some_and(|response| !response.is_empty())
        );
        assert!(output.events.is_empty());
    }

    #[test]
    fn binary_command_parser_updates_telemetry_subscription_state() {
        let mut robot = Puppybot::new(0);
        let mut telemetry_enabled = false;

        let output = handle_binary_command_for_robot(
            &mut robot,
            &command_frame(CMD_SUBSCRIBE, &[SUBSCRIPTION_TOPIC_ARM_STATE, 1]),
            10,
            &mut telemetry_enabled,
        );

        assert!(output.events.is_empty());
        assert!(telemetry_enabled);
    }

    #[test]
    fn binary_command_parser_updates_drive_output() {
        let mut robot = Puppybot::new(0);
        let mut telemetry_enabled = false;

        let output = handle_binary_command_for_robot(
            &mut robot,
            &command_frame(CMD_DRIVE_STEER, &[50, 0]),
            10,
            &mut telemetry_enabled,
        );

        assert!(
            output
                .events
                .iter()
                .any(|event| matches!(event, ProtocolEvent::Drive(_)))
        );
        assert_eq!(robot.drive_output().left_speed, 50);
        assert_eq!(robot.drive_output().right_speed, 50);
    }
}
