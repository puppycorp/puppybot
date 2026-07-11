use std::{
    collections::{HashMap, HashSet},
    net::{IpAddr, SocketAddr},
    path::PathBuf,
    time::{Duration, Instant},
};

use puppybot_core::{
    config::{CoordinateCalibration, PuppybotConfigV1},
    drive::DriveCommand,
    protocol::{self, ProtocolEvent, ProtocolOutput},
    puppyarm::{
        kinematics::{self, IkError},
        servo_safety::TICK_WRAP,
        types::{ArmCommand, ControllerError, JOINT_COUNT, Joint, TcpFrame},
    },
    robot::Puppybot,
};
use tokio::time::{self, MissedTickBehavior};
use wgui::{
    ClientEvent, ClientMessage, Item, Wgui, button, hstack, modal, text, text_input, vstack,
};

use crate::{
    config,
    dc_motor_driver::DCMotorDriver,
    env::wgui_bind_addr,
    http, mdns,
    sim::{SimulatedPreview, SimulatedRuntimeBackend},
    stservo::{self, RuntimeStServo},
};

const RUNTIME_UI_CSS: &str = include_str!("../wui/runtime.css");
const DEFAULT_WS_BIND: &str = "0.0.0.0:8080";
const ROBOT_TICK_MS: u64 = 20;
const UI_RENDER_INTERVAL_MS: u64 = 100;
const HELD_DRIVE_REFRESH_MS: u64 = 200;
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

const EDIT_COORDINATE_X_ID: u32 = 500;
const EDIT_COORDINATE_Y_ID: u32 = 501;
const EDIT_COORDINATE_Z_ID: u32 = 502;
const SET_COORDINATES_CURRENT_ID: u32 = 503;
const MOVE_TO_COORDINATES_ID: u32 = 504;
const SET_COORDINATE_FRAME_BASE_ID: u32 = 505;
const SET_COORDINATE_FRAME_YAW_FLAT_ID: u32 = 506;
const FLIP_COORDINATE_FORWARD_AXIS_ID: u32 = 507;
const FLIP_COORDINATE_LEFT_AXIS_ID: u32 = 508;
const ROTATE_COORDINATE_BASE_FRAME_ID: u32 = 509;
const COORDINATE_FORWARD_ID: u32 = 510;
const COORDINATE_BACK_ID: u32 = 511;
const COORDINATE_LEFT_ID: u32 = 512;
const COORDINATE_RIGHT_ID: u32 = 513;
const COORDINATE_UP_ID: u32 = 514;
const COORDINATE_DOWN_ID: u32 = 515;

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

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
struct KeyboardDriveState {
    up: bool,
    down: bool,
    left: bool,
    right: bool,
}

pub(crate) struct ApiResponse {
    status: &'static str,
    body: Vec<u8>,
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
        Some(angle) => format!("{angle:.1} deg"),
        None => "-- deg".to_string(),
    }
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

fn coordinate_jog_frame_label(frame: TcpFrame) -> &'static str {
    match frame {
        TcpFrame::Base => "Arm Base",
        frame => frame_label(frame),
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
    held_drive: Option<HeldDrive>,
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
    coordinate_frame: TcpFrame,
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
        let mut robot = Puppybot::new_with_config(&active_config, 0)
            .map_err(|err| format!("invalid runtime config: {err}"))?;
        robot.handle_event(
            ProtocolEvent::Arm(ArmCommand::SetSpeed(DEFAULT_ARM_SPEED)),
            0,
        );
        let backend = if options.simulated {
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
            RuntimeBackend::Simulated(SimulatedRuntimeBackend::new(&project_path, &active_config)?)
        } else {
            if options.robotdreams_project.is_some() {
                return Err("--robotdreams-project requires --sim".to_string());
            }
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
            held_drive: None,
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
            coordinate_frame: TcpFrame::YawFlat,
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
        self.backend.run_once(&mut self.robot, now_ms).await;
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
                })
            }
        };
        let state = serde_json::json!({
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
                "coordinateFrame": frame_label(self.coordinate_frame),
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
        ApiResponse { status, body }
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

        let response: Result<ApiResponse, ApiError> = match (method, path) {
            ("GET", "/api/config.json") => self
                .config_json()
                .map(|body| ApiResponse {
                    status: "200 OK",
                    body: body.into_bytes(),
                })
                .map_err(ApiError::internal),
            ("GET", "/api/state") => self
                .api_state_json()
                .map(|body| ApiResponse {
                    status: "200 OK",
                    body: body.into_bytes(),
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

    fn handle_api_command(&mut self, path: &str, body: &[u8]) -> Result<(), ApiError> {
        let json = Self::api_request_body(body)?;
        let segments = path
            .trim_start_matches('/')
            .split('/')
            .filter(|segment| !segment.is_empty())
            .collect::<Vec<_>>();

        match segments.as_slice() {
            ["api", "drive"] => self.api_drive(&json),
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
                self.arm("spin joint", ArmCommand::Spin { joint, direction })
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
                        ApiError::bad_request(format!("set joint reference rejected: {err:?}"))
                    })
            }
            ["api", "arm", "joints", joint, "angle-sign", "flip"] => {
                let joint = Self::api_joint(joint)?;
                self.flip_joint_angle_sign_for(joint);
                Ok(())
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
            ["api", "arm", "coordinate-frame"] => {
                let frame = Self::api_frame(&json, "frame")?;
                if !matches!(frame, TcpFrame::Base | TcpFrame::YawFlat) {
                    return Err(ApiError::bad_request(
                        "coordinate frame must be base or yawFlat",
                    ));
                }
                self.set_coordinate_frame(frame);
                Ok(())
            }
            ["api", "arm", "tcp-jog", "start"] => self.api_tcp_jog_start(&json),
            ["api", "arm", "coordinate-jog", "start"] => self.api_coordinate_jog_start(&json),
            ["api", "arm", "tcp-jog", "stop"] => self
                .arm("stop tcp jog", ArmCommand::StopTcpJog)
                .map_err(|err| ApiError::bad_request(format!("stop tcp jog rejected: {err:?}"))),
            ["api", "calibration", "save"] => {
                self.save_calibration();
                Ok(())
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
                "tcp jog direction must be forward, back, left, or right",
            ));
        }
        self.start_tcp_jog("http tcp jog", frame, direction)
            .map_err(|err| ApiError::bad_request(format!("tcp jog rejected: {err:?}")))
    }

    fn api_coordinate_jog_start(&mut self, json: &serde_json::Value) -> Result<(), ApiError> {
        let frame = Self::api_frame(json, "frame")?;
        if !matches!(frame, TcpFrame::Base | TcpFrame::YawFlat) {
            return Err(ApiError::bad_request(
                "coordinate jog frame must be base or yawFlat",
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
        self.start_tcp_jog("http coordinate jog", frame, direction)
            .map_err(|err| ApiError::bad_request(format!("coordinate jog rejected: {err:?}")))
    }

    fn coordinate_calibration(&self) -> CoordinateCalibration {
        self.active_config.coordinate
    }

    fn save_calibration(&mut self) {
        self.sync_arm_calibration_from_robot();
        match config::save_runtime_config(&self.config_path, &self.active_config) {
            Ok(()) => {
                self.calibration_dirty = false;
                self.last_command = format!("saved calibration to {}", self.config_path.display());
                log::info!("runtime App command: {}", self.last_command);
            }
            Err(err) => {
                self.last_command = format!("save calibration failed: {err}");
                log::warn!("runtime App save calibration failed: {err}");
            }
        }
        self.mark_ui_dirty();
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

        vstack(children)
            .fill(true)
            .min_height(0)
            .background_color("#12161c")
            .padding(18)
            .spacing(14)
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
            },
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

        hstack(vec![
            label_text(&format!(
                "{} (servo {})",
                ARM_JOINT_LABELS[index], joint.servo_id
            ))
            .min_width(132),
            body_text(&angle_detail(joint))
                .min_width(72)
                .text_align("right"),
            secondary_button("Calibrate")
                .height(30)
                .width(86)
                .inx(action_arg)
                .on_click(OPEN_JOINT_CALIBRATION_ID),
            secondary_button("Zero")
                .height(30)
                .width(64)
                .inx(action_arg)
                .on_press(SET_JOINT_ZERO_ID)
                .on_release(SET_JOINT_ZERO_ID)
                .on_repeat(SET_JOINT_ZERO_ID)
                .repeat_interval(250),
            dark_button("-")
                .height(30)
                .width(42)
                .inx(action_arg)
                .on_press(JOG_NEGATIVE_ID)
                .on_release(JOG_STOP_ID)
                .on_repeat(JOG_NEGATIVE_ID)
                .repeat_interval(250),
            secondary_button("Stop")
                .height(30)
                .inx(action_arg)
                .on_click(STOP_JOINT_ID),
            dark_button("+")
                .height(30)
                .width(42)
                .inx(action_arg)
                .on_press(JOG_POSITIVE_ID)
                .on_release(JOG_STOP_ID)
                .on_repeat(JOG_POSITIVE_ID)
                .repeat_interval(250),
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
        ])
        .spacing(8)
    }

    fn render_joint_target(&self) -> Item {
        subpanel(vec![
            title_text("Joint Target (deg)"),
            label_text(
                "Default (90 / 90 / 90 / 90) is a folded transport pose, not a neutral reach home",
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
                    .on_release(GOTO_ANGLES_ID)
                    .on_repeat(GOTO_DEFAULT_ANGLES_ID)
                    .repeat_interval(250),
                primary_button("Move Angles")
                    .height(34)
                    .width(116)
                    .on_press(GOTO_ANGLES_ID)
                    .on_release(GOTO_ANGLES_ID)
                    .on_repeat(GOTO_ANGLES_ID)
                    .repeat_interval(250),
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
                label_text("Jog Frame").min_width(72),
                frame_button(
                    "Arm Base",
                    self.coordinate_frame == TcpFrame::Base,
                    SET_COORDINATE_FRAME_BASE_ID,
                    92,
                ),
                frame_button(
                    "Yaw-flat",
                    self.coordinate_frame == TcpFrame::YawFlat,
                    SET_COORDINATE_FRAME_YAW_FLAT_ID,
                    96,
                ),
                title_text(coordinate_jog_frame_label(self.coordinate_frame)).min_width(76),
                label_text(frame_detail(self.coordinate_frame))
                    .grow(1)
                    .break_words(true),
            ])
            .spacing(8)
            .wrap(true),
            hstack(vec![
                label_text(&format!(
                    "forward sign {}, left sign {}, base rotation {:.0} deg",
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
        self.robot
            .handle_event(ProtocolEvent::Drive(DriveCommand::Stop), self.now_ms());
        self.telemetry_seq = self.telemetry_seq.wrapping_add(1);
        self.mark_ui_dirty();
    }

    fn apply_event(&mut self, label: &str, event: ProtocolEvent) -> Result<(), ControllerError> {
        if matches!(event, ProtocolEvent::Drive(DriveCommand::Stop)) {
            self.held_drive = None;
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
        let _ = self.arm("spin joint", ArmCommand::Spin { joint, direction });
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
        let (dx, dy) = rotate_xy_deg(dx, dy, self.coordinate_base_yaw_offset_deg());
        [dx, dy, dz_table]
    }

    fn start_tcp_jog(
        &mut self,
        label: &str,
        frame: TcpFrame,
        direction: [f64; 3],
    ) -> Result<(), ControllerError> {
        self.arm(label, ArmCommand::StartTcpJog { frame, direction })
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

    fn set_joint_reference_angle(
        &mut self,
        joint: usize,
        angle_deg: f64,
    ) -> Result<(), ControllerError> {
        let arm_joint = &self.robot.arm.joints[joint];
        if let Some(err) = joint_reference_tick_error(arm_joint) {
            self.calibration_editor_error = err;
            self.mark_ui_dirty();
            return Err(ControllerError::MissingFeedback);
        }
        let Some(tick) = arm_joint.tick else {
            self.calibration_editor_error = "current tick unavailable".to_string();
            self.mark_ui_dirty();
            return Err(ControllerError::MissingFeedback);
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
    }

    fn flip_joint_angle_sign(&mut self) {
        let Some(joint) = self.calibration_editor_joint else {
            return;
        };
        self.flip_joint_angle_sign_for(joint);
    }

    fn flip_joint_angle_sign_for(&mut self, joint: usize) {
        if joint >= JOINT_COUNT {
            self.calibration_editor_error = "invalid joint".to_string();
            self.mark_ui_dirty();
            return;
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
            }
            Err(err) => {
                self.calibration_editor_error =
                    format!("invalid calibration after sign flip: {err}");
                self.last_command = self.calibration_editor_error.clone();
            }
        }
        self.mark_ui_dirty();
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

    fn set_coordinate_frame(&mut self, frame: TcpFrame) {
        if !matches!(frame, TcpFrame::Base | TcpFrame::YawFlat) {
            return;
        }
        self.coordinate_frame = frame;
        self.last_command = format!("set coordinate frame {}", frame_label(frame).to_lowercase());
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
            SAVE_CALIBRATION_ID => self.save_calibration(),
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
            SET_COORDINATE_FRAME_BASE_ID => self.set_coordinate_frame(TcpFrame::Base),
            SET_COORDINATE_FRAME_YAW_FLAT_ID => self.set_coordinate_frame(TcpFrame::YawFlat),
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
            COORDINATE_FORWARD_ID => {
                let direction =
                    self.coordinate_jog_direction(self.coordinate_forward_sign(), 0.0, 0.0);
                let _ = self.start_tcp_jog("coordinate forward", self.coordinate_frame, direction);
            }
            COORDINATE_BACK_ID => {
                let direction =
                    self.coordinate_jog_direction(-self.coordinate_forward_sign(), 0.0, 0.0);
                let _ = self.start_tcp_jog("coordinate back", self.coordinate_frame, direction);
            }
            COORDINATE_LEFT_ID => {
                let direction =
                    self.coordinate_jog_direction(0.0, self.coordinate_left_sign(), 0.0);
                let _ = self.start_tcp_jog("coordinate left", self.coordinate_frame, direction);
            }
            COORDINATE_RIGHT_ID => {
                let direction =
                    self.coordinate_jog_direction(0.0, -self.coordinate_left_sign(), 0.0);
                let _ = self.start_tcp_jog("coordinate right", self.coordinate_frame, direction);
            }
            COORDINATE_UP_ID => {
                let _ = self.start_tcp_jog("coordinate up", self.coordinate_frame, [0.0, 0.0, 1.0]);
            }
            COORDINATE_DOWN_ID => {
                let _ =
                    self.start_tcp_jog("coordinate down", self.coordinate_frame, [0.0, 0.0, -1.0]);
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
                let _ = self.arm("stop tcp jog", ArmCommand::StopTcpJog);
            }
            _ => return false,
        }
        true
    }

    fn handle_repeat_id(&mut self, id: u32, inx: Option<u32>) -> bool {
        match id {
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
            COORDINATE_FORWARD_ID => {
                let direction =
                    self.coordinate_jog_direction(self.coordinate_forward_sign(), 0.0, 0.0);
                let _ = self.start_tcp_jog("coordinate forward", self.coordinate_frame, direction);
            }
            COORDINATE_BACK_ID => {
                let direction =
                    self.coordinate_jog_direction(-self.coordinate_forward_sign(), 0.0, 0.0);
                let _ = self.start_tcp_jog("coordinate back", self.coordinate_frame, direction);
            }
            COORDINATE_LEFT_ID => {
                let direction =
                    self.coordinate_jog_direction(0.0, self.coordinate_left_sign(), 0.0);
                let _ = self.start_tcp_jog("coordinate left", self.coordinate_frame, direction);
            }
            COORDINATE_RIGHT_ID => {
                let direction =
                    self.coordinate_jog_direction(0.0, -self.coordinate_left_sign(), 0.0);
                let _ = self.start_tcp_jog("coordinate right", self.coordinate_frame, direction);
            }
            COORDINATE_UP_ID => {
                let _ = self.start_tcp_jog("coordinate up", self.coordinate_frame, [0.0, 0.0, 1.0]);
            }
            COORDINATE_DOWN_ID => {
                let _ =
                    self.start_tcp_jog("coordinate down", self.coordinate_frame, [0.0, 0.0, -1.0]);
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
            ClientEvent::OnRepeat(event) => {
                if !self.handle_repeat_id(event.id, event.inx) {
                    log::debug!("unhandled wgui repeat id={} inx={:?}", event.id, event.inx);
                }
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
                        "application/json",
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
        CMD_CONFIG_GET, CMD_DRIVE_STEER, CMD_SUBSCRIBE, SUBSCRIPTION_TOPIC_ARM_STATE, command_frame,
    };

    #[tokio::test]
    async fn api_state_json_reports_runtime_state() {
        let mut app = App::with_options(AppOptions {
            config: None,
            servo_device: None,
            simulated: true,
            robotdreams_project: None,
            ui_bind: Some("127.0.0.1:0".parse().unwrap()),
            ws_bind: Some("127.0.0.1:0".parse().unwrap()),
        })
        .expect("simulated runtime app");

        for _ in 0..8 {
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
        assert_eq!(state["ui"]["coordinateFrame"], "Yaw-flat");
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

    fn response_json(response: ApiResponse) -> serde_json::Value {
        serde_json::from_slice(&response.body).expect("json response")
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
            br#"{"direction":"up","frame":"yawFlat"}"#,
        );
        assert_eq!(response.status, "200 OK");
        let body = response_json(response);
        assert_eq!(body["ok"], true);
        assert_eq!(body["state"]["ui"]["lastCommand"], "http coordinate jog");

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
