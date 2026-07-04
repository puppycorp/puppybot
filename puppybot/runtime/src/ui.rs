use std::{
    net::{IpAddr, SocketAddr},
    sync::{Arc, Mutex},
    thread,
};

use puppybot_core::{
    drive::DriveCommand,
    protocol::ProtocolEvent,
    puppyarm::{
        kinematics::{self, IkError},
        servo_safety::TICK_WRAP,
        types::{ArmCommand, ControllerError, JOINT_COUNT, Joint, TcpFrame},
    },
};
use wgui::{Wgui, WguiModel, wgui_controller};

use crate::RuntimeRobot;

const RUNTIME_UI_CSS: &str = include_str!("../wui/runtime.css");
const UI_ARM_SPEED: i16 = 220;
const UI_TCP_STEP_MM: f64 = 5.0;
const UI_COORD_STEP_MM: f64 = 5.0;
const UI_DRIVE_SPEED: i8 = 35;
const UI_STEER_SPEED: i8 = 55;
const UI_LIMIT_STEP_TICKS: i32 = 10;
const ARM_JOINT_LABELS: [&str; JOINT_COUNT] = ["Yaw", "Shoulder", "Elbow", "Wrist"];
const DEFAULT_GOTO_ANGLE_DEG: f64 = 90.0;

#[derive(Clone, Debug, WguiModel)]
pub(crate) struct RuntimeUiConfig {
    pub(crate) ws_bind: String,
    pub(crate) ws_url: String,
    pub(crate) ui_bind: String,
    pub(crate) ui_url: String,
    pub(crate) servo_status: String,
    pub(crate) servo_detail: String,
}

#[derive(Clone, Debug, WguiModel)]
pub(crate) struct RuntimeUiMetric {
    label: String,
    value: String,
    detail: String,
    accent: String,
    save_action: bool,
}

#[derive(Clone, Debug, WguiModel)]
pub(crate) struct RuntimeUiJogButton {
    label: String,
}

#[derive(Clone, Debug, WguiModel)]
pub(crate) struct RuntimeUiFrameButton {
    label: String,
    background: String,
    border: String,
    color: String,
}

#[derive(Clone, Debug, WguiModel)]
pub(crate) struct RuntimeUiLimit {
    label: String,
    detail: String,
    toggle_label: String,
    accent: String,
    background: String,
    border: String,
}

#[derive(Clone, Debug, WguiModel)]
pub(crate) struct RuntimeUiJoint {
    index: u32,
    action_arg: u32,
    label: String,
    angle: String,
    calibrate: RuntimeUiJogButton,
    negative: RuntimeUiJogButton,
    positive: RuntimeUiJogButton,
    limit: RuntimeUiLimit,
}

#[derive(Clone, Debug, WguiModel)]
pub(crate) struct RuntimeUiModel {
    status: Vec<RuntimeUiMetric>,
    joints: Vec<RuntimeUiJoint>,
    limit_modal_open: bool,
    limit_modal_title: String,
    limit_modal_detail: String,
    limit_modal_min: String,
    limit_modal_max: String,
    limit_modal_error: String,
    calibration_modal_open: bool,
    calibration_modal_title: String,
    calibration_modal_detail: String,
    calibration_modal_angle: String,
    calibration_modal_sign: String,
    calibration_modal_error: String,
    goto_angle_yaw: String,
    goto_angle_shoulder: String,
    goto_angle_elbow: String,
    goto_angle_wrist: String,
    goto_angle_error: String,
    coordinate_x: String,
    coordinate_y: String,
    coordinate_z: String,
    coordinate_detail: String,
    coordinate_calibration_detail: String,
    coordinate_frame_label: String,
    coordinate_frame_detail: String,
    coordinate_base_button: RuntimeUiFrameButton,
    coordinate_yaw_flat_button: RuntimeUiFrameButton,
    coordinate_error: String,
    tcp_frame_label: String,
    tcp_frame_detail: String,
    tcp_base_button: RuntimeUiFrameButton,
    tcp_tool_button: RuntimeUiFrameButton,
    last_command: String,
}

#[derive(Clone)]
pub(crate) struct RuntimeUiController {
    config: RuntimeUiConfig,
    robot: Arc<Mutex<RuntimeRobot>>,
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
    coordinate_x: String,
    coordinate_y: String,
    coordinate_z: String,
    coordinate_error: String,
    last_command: String,
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

fn metric(
    label: &str,
    value: &str,
    detail: &str,
    accent: &str,
    save_action: bool,
) -> RuntimeUiMetric {
    RuntimeUiMetric {
        label: label.to_string(),
        value: value.to_string(),
        detail: detail.to_string(),
        accent: accent.to_string(),
        save_action,
    }
}

fn jog_button(label: &str) -> RuntimeUiJogButton {
    RuntimeUiJogButton {
        label: label.to_string(),
    }
}

fn frame_button(label: &str, selected: bool) -> RuntimeUiFrameButton {
    if selected {
        RuntimeUiFrameButton {
            label: label.to_string(),
            background: "#1e5f9f".to_string(),
            border: "1px solid #4d8dff".to_string(),
            color: "#f4f7fb".to_string(),
        }
    } else {
        RuntimeUiFrameButton {
            label: label.to_string(),
            background: "#182838".to_string(),
            border: "1px solid #314154".to_string(),
            color: "#b6c2d2".to_string(),
        }
    }
}

fn frame_label(frame: TcpFrame) -> &'static str {
    match frame {
        TcpFrame::Base => "Base",
        TcpFrame::YawFlat => "Yaw-flat",
        TcpFrame::Tool => "Tool",
    }
}

fn frame_detail(frame: TcpFrame) -> &'static str {
    match frame {
        TcpFrame::Base => "moves along robot base axes",
        TcpFrame::YawFlat => "moves along current yaw in the horizontal plane",
        TcpFrame::Tool => "moves along current TCP/tool axes",
    }
}

fn limit_detail(joint: &Joint) -> String {
    match joint.tick {
        Some(tick) => format!("tick {tick} / {}..{}", joint.limit_min, joint.limit_max),
        None => format!("limits {}..{}", joint.limit_min, joint.limit_max),
    }
}

fn limit_status(joint: &Joint) -> RuntimeUiLimit {
    if !joint.limit_enabled {
        return RuntimeUiLimit {
            label: "Limits off".to_string(),
            detail: limit_detail(joint),
            toggle_label: "Enable".to_string(),
            accent: "#8ea0b7".to_string(),
            background: "#202936".to_string(),
            border: "1px solid #415066".to_string(),
        };
    }

    if !joint.has_feedback {
        return RuntimeUiLimit {
            label: "No feedback".to_string(),
            detail: "waiting for servo position".to_string(),
            toggle_label: "Disable".to_string(),
            accent: "#8ea0b7".to_string(),
            background: "#202936".to_string(),
            border: "1px solid #415066".to_string(),
        };
    }

    if joint.limit_reached {
        return RuntimeUiLimit {
            label: "LIMIT".to_string(),
            detail: limit_detail(joint),
            toggle_label: "Disable".to_string(),
            accent: "#ffb8b8".to_string(),
            background: "#7f2525".to_string(),
            border: "1px solid #d85b5b".to_string(),
        };
    }

    RuntimeUiLimit {
        label: "OK".to_string(),
        detail: limit_detail(joint),
        toggle_label: "Disable".to_string(),
        accent: "#bff0cf".to_string(),
        background: "#1d5034".to_string(),
        border: "1px solid #3fbf6f".to_string(),
    }
}

fn angle_detail(joint: &Joint) -> String {
    match joint.angle_deg {
        Some(angle) => format!("{angle:.1} deg"),
        None => "-- deg".to_string(),
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

fn joint_controls(joints: &[Joint; JOINT_COUNT]) -> Vec<RuntimeUiJoint> {
    (0..JOINT_COUNT)
        .map(|index| RuntimeUiJoint {
            index: index as u32,
            action_arg: index as u32 + 1,
            label: format!(
                "{} (servo {})",
                ARM_JOINT_LABELS[index], joints[index].servo_id
            ),
            angle: angle_detail(&joints[index]),
            calibrate: jog_button("Calibrate"),
            negative: jog_button("-"),
            positive: jog_button("+"),
            limit: limit_status(&joints[index]),
        })
        .collect()
}

fn initial_coordinate_inputs(robot: &Arc<Mutex<RuntimeRobot>>) -> (String, String, String) {
    let coords = {
        let robot = robot.lock().unwrap();
        robot.arm_telemetry().coords_mm
    };
    match coords {
        Some((x, y, z)) => (format!("{x:.1}"), format!("{y:.1}"), format!("{z:.1}")),
        None => ("200.0".to_string(), "0.0".to_string(), "80.0".to_string()),
    }
}

fn initial_goto_angle_inputs(robot: &Arc<Mutex<RuntimeRobot>>) -> [String; JOINT_COUNT] {
    let telemetry = {
        let robot = robot.lock().unwrap();
        robot.arm_telemetry()
    };
    std::array::from_fn(|index| {
        telemetry.joints[index]
            .angle_deg
            .map(|angle| format!("{angle:.1}"))
            .unwrap_or_else(|| "0.0".to_string())
    })
}

fn target_angle_inputs(joints: &[Joint; JOINT_COUNT]) -> Option<[String; JOINT_COUNT]> {
    let mut angles = [0.0; JOINT_COUNT];
    for (index, joint) in joints.iter().enumerate() {
        angles[index] = joint.target_angle_deg?;
    }
    Some(std::array::from_fn(|index| format!("{:.1}", angles[index])))
}

fn coordinate_inputs(coords_mm: (f32, f32, f32)) -> (String, String, String) {
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
            | ArmCommand::GotoPose { .. }
            | ArmCommand::MoveTcpRelative { .. }
    )
}

fn angle_sign_label(sign: Option<i8>) -> String {
    match sign {
        Some(sign) if sign < 0 => "Angle sign: -1".to_string(),
        Some(_) => "Angle sign: +1".to_string(),
        None => "Angle sign: unavailable".to_string(),
    }
}

fn goto_angles_command(command: ArmCommand) -> bool {
    matches!(command, ArmCommand::GotoAngles(_))
}

fn tcp_forward_delta_mm() -> (f64, f64, f64) {
    (UI_TCP_STEP_MM, 0.0, 0.0)
}

fn tcp_back_delta_mm() -> (f64, f64, f64) {
    (-UI_TCP_STEP_MM, 0.0, 0.0)
}

fn arm_command_error_text(command: ArmCommand, err: ControllerError) -> Option<String> {
    match (command, err) {
        (ArmCommand::GotoCoords { x, y, z }, ControllerError::Ik(IkError::Unreachable)) => {
            Some(format!(
                "target unreachable: {x:.1}, {y:.1}, {:.1} mm",
                kinematics::shoulder_to_table_z(z)
            ))
        }
        (ArmCommand::GotoPose { x, y, z, .. }, ControllerError::Ik(IkError::Unreachable)) => {
            Some(format!(
                "target unreachable: {x:.1}, {y:.1}, {:.1} mm",
                kinematics::shoulder_to_table_z(z)
            ))
        }
        (ArmCommand::MoveTcpRelative { .. }, ControllerError::Ik(IkError::Unreachable)) => {
            Some("target unreachable from current position".to_string())
        }
        (ArmCommand::MoveTcpRelative { .. }, ControllerError::MissingFeedback) => {
            Some("current position unavailable".to_string())
        }
        (ArmCommand::GotoAngles(_), ControllerError::MissingFeedback) => {
            Some("current joint feedback unavailable".to_string())
        }
        (_, ControllerError::Ik(IkError::Unreachable)) => Some("target unreachable".to_string()),
        _ => None,
    }
}

pub(crate) fn local_url(addr: SocketAddr, scheme: &str, path: &str) -> String {
    format!("{scheme}://{}:{}{path}", ui_host(addr), addr.port())
}

#[wgui_controller(template = "runtime")]
impl RuntimeUiController {
    pub(crate) fn new(config: RuntimeUiConfig, robot: Arc<Mutex<RuntimeRobot>>) -> Self {
        let (coordinate_x, coordinate_y, coordinate_z) = initial_coordinate_inputs(&robot);
        let goto_angles = initial_goto_angle_inputs(&robot);
        Self {
            config,
            robot,
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
            coordinate_x,
            coordinate_y,
            coordinate_z,
            coordinate_error: String::new(),
            last_command: "none".to_string(),
        }
    }

    pub(crate) fn state(&self) -> RuntimeUiModel {
        let (telemetry, calibration_dirty, config_path, calibration_modal_sign) = {
            let robot = self.robot.lock().unwrap();
            let (calibration_dirty, config_path) = robot.calibration_state();
            let sign = self
                .calibration_editor_joint
                .and_then(|joint| robot.joint_angle_sign(joint));
            (
                robot.arm_telemetry(),
                calibration_dirty,
                config_path,
                angle_sign_label(sign),
            )
        };
        let (limit_modal_title, limit_modal_detail) = match self.limit_editor_joint {
            Some(joint) if joint < JOINT_COUNT => {
                let telemetry_joint = &telemetry.joints[joint];
                (
                    format!("{} Limits", ARM_JOINT_LABELS[joint]),
                    match telemetry_joint.tick {
                        Some(tick) => {
                            format!("servo {} current tick {tick}", telemetry_joint.servo_id)
                        }
                        None => format!("servo {} waiting for feedback", telemetry_joint.servo_id),
                    },
                )
            }
            _ => ("Joint Limits".to_string(), "no joint selected".to_string()),
        };
        let (calibration_modal_title, calibration_modal_detail) = match self
            .calibration_editor_joint
        {
            Some(joint) if joint < JOINT_COUNT => {
                let telemetry_joint = &telemetry.joints[joint];
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
            }
            _ => (
                "Joint Calibration".to_string(),
                "no joint selected".to_string(),
            ),
        };
        let coordinate_detail = match telemetry.coords_mm {
            Some((x, y, z)) => format!("current {x:.1}, {y:.1}, {z:.1} mm"),
            None => "current position unavailable".to_string(),
        };
        let coordinate_calibration = {
            let robot = self.robot.lock().unwrap();
            robot.coordinate_calibration()
        };
        let coordinate_calibration_detail = format!(
            "forward sign {}, left sign {}, base rotation {:.0} deg",
            coordinate_calibration.forward_sign,
            coordinate_calibration.left_sign,
            coordinate_calibration.base_yaw_offset_deg
        );

        RuntimeUiModel {
            status: vec![
                metric(
                    "Runtime",
                    "running",
                    "process is accepting robot websocket clients",
                    "#3fbf6f",
                    false,
                ),
                metric(
                    "Servo bus",
                    &self.config.servo_status,
                    &self.config.servo_detail,
                    if self.config.servo_status == "hardware" {
                        "#3fbf6f"
                    } else {
                        "#d89b2f"
                    },
                    false,
                ),
                metric(
                    "Config",
                    if calibration_dirty {
                        "unsaved"
                    } else {
                        "saved"
                    },
                    &config_path,
                    if calibration_dirty {
                        "#d89b2f"
                    } else {
                        "#3fbf6f"
                    },
                    true,
                ),
                metric("UI", "online", "web control connected", "#3fbf6f", false),
            ],
            joints: joint_controls(&telemetry.joints),
            limit_modal_open: self.limit_editor_joint.is_some(),
            limit_modal_title,
            limit_modal_detail,
            limit_modal_min: self.limit_editor_min.clone(),
            limit_modal_max: self.limit_editor_max.clone(),
            limit_modal_error: self.limit_editor_error.clone(),
            calibration_modal_open: self.calibration_editor_joint.is_some(),
            calibration_modal_title,
            calibration_modal_detail,
            calibration_modal_angle: self.calibration_editor_angle.clone(),
            calibration_modal_sign,
            calibration_modal_error: self.calibration_editor_error.clone(),
            goto_angle_yaw: self.goto_angle_yaw.clone(),
            goto_angle_shoulder: self.goto_angle_shoulder.clone(),
            goto_angle_elbow: self.goto_angle_elbow.clone(),
            goto_angle_wrist: self.goto_angle_wrist.clone(),
            goto_angle_error: self.goto_angle_error.clone(),
            coordinate_x: self.coordinate_x.clone(),
            coordinate_y: self.coordinate_y.clone(),
            coordinate_z: self.coordinate_z.clone(),
            coordinate_detail,
            coordinate_calibration_detail,
            coordinate_frame_label: self.coordinate_frame_label().to_string(),
            coordinate_frame_detail: self.coordinate_frame_detail().to_string(),
            coordinate_base_button: frame_button("Base", self.coordinate_frame == TcpFrame::Base),
            coordinate_yaw_flat_button: frame_button(
                "Yaw-flat",
                self.coordinate_frame == TcpFrame::YawFlat,
            ),
            coordinate_error: self.coordinate_error.clone(),
            tcp_frame_label: self.tcp_frame_label().to_string(),
            tcp_frame_detail: self.tcp_frame_detail().to_string(),
            tcp_base_button: frame_button("Base", self.tcp_frame == TcpFrame::Base),
            tcp_tool_button: frame_button("Tool", self.tcp_frame == TcpFrame::Tool),
            last_command: self.last_command.clone(),
        }
    }

    pub(crate) fn title(&self) -> String {
        "PuppyBot Runtime".to_string()
    }

    fn apply_event(&mut self, label: &str, event: ProtocolEvent) -> Result<(), ControllerError> {
        let result = {
            let mut robot = self.robot.lock().unwrap();
            robot.try_handle_event(event)
        };
        match result {
            Ok(()) => {
                self.last_command = label.to_string();
                log::info!("runtime UI command: {label}");
                Ok(())
            }
            Err(err) => {
                self.last_command = format!("{label} rejected: {err:?}");
                log::warn!("runtime UI command rejected: {label}: {err:?}");
                Err(err)
            }
        }
    }

    fn drive(&mut self, label: &str, throttle: i8, steering: i8) {
        let _ = self.apply_event(
            label,
            ProtocolEvent::Drive(DriveCommand::DriveSteer { throttle, steering }),
        );
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

    fn tcp_frame_label(&self) -> &'static str {
        frame_label(self.tcp_frame)
    }

    fn coordinate_frame_label(&self) -> &'static str {
        frame_label(self.coordinate_frame)
    }

    fn tcp_frame_detail(&self) -> &'static str {
        frame_detail(self.tcp_frame)
    }

    fn coordinate_frame_detail(&self) -> &'static str {
        frame_detail(self.coordinate_frame)
    }

    fn set_coordinate_frame(&mut self, frame: TcpFrame) {
        if !matches!(frame, TcpFrame::Base | TcpFrame::YawFlat) {
            return;
        }
        self.coordinate_frame = frame;
        self.last_command = format!(
            "set coordinate frame {}",
            self.coordinate_frame_label().to_lowercase()
        );
        log::info!(
            "runtime UI command: set coordinate frame {}",
            self.coordinate_frame_label().to_lowercase()
        );
    }

    fn set_tcp_frame(&mut self, frame: TcpFrame) {
        self.tcp_frame = frame;
        self.last_command = format!(
            "set tcp jog frame {}",
            self.tcp_frame_label().to_lowercase()
        );
        log::info!(
            "runtime UI command: set tcp jog frame {}",
            self.tcp_frame_label().to_lowercase()
        );
    }

    fn move_tcp(&mut self, label: &str, dx_mm: f64, dy_mm: f64, dz_mm: f64) {
        let _ = self.arm(label, ArmCommand::SetSpeed(UI_ARM_SPEED));
        let _ = self.arm(
            label,
            ArmCommand::MoveTcpRelative {
                frame: self.tcp_frame,
                dx_mm,
                dy_mm,
                dz_mm,
            },
        );
    }

    fn joint_arg_to_index(joint_arg: u32) -> Option<usize> {
        let joint = joint_arg.checked_sub(1)? as usize;
        if joint < JOINT_COUNT {
            Some(joint)
        } else {
            None
        }
    }

    fn spin_joint(&mut self, joint_arg: u32, direction: i32) {
        let Some(joint) = Self::joint_arg_to_index(joint_arg) else {
            return;
        };
        if direction == 0 {
            return;
        }

        let direction = if direction > 0 { 1 } else { -1 };
        let label = if direction > 0 {
            "hold jog joint positive"
        } else {
            "hold jog joint negative"
        };
        let _ = self.arm(label, ArmCommand::SetSpeed(UI_ARM_SPEED));
        let _ = self.arm(label, ArmCommand::Spin { joint, direction });
    }

    fn refresh_spin_joint(&mut self, joint_arg: u32, direction: i32) {
        let Some(joint) = Self::joint_arg_to_index(joint_arg) else {
            return;
        };
        if direction == 0 {
            return;
        }

        let direction = if direction > 0 { 1 } else { -1 };
        let mut robot = self.robot.lock().unwrap();
        robot.handle_event(ProtocolEvent::Arm(ArmCommand::Spin { joint, direction }));
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

    fn nudge_limit_editor(&mut self, min_delta: i32, max_delta: i32) {
        let Some((_, min, max)) = self.parse_limit_editor() else {
            return;
        };
        self.limit_editor_min = (min + min_delta).to_string();
        self.limit_editor_max = (max + max_delta).to_string();
        self.limit_editor_error.clear();
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

    fn move_to_coordinate_target(&mut self, label: &str, x: f64, y: f64, z_table: f64) {
        self.coordinate_x = format!("{x:.1}");
        self.coordinate_y = format!("{y:.1}");
        self.coordinate_z = format!("{z_table:.1}");
        self.coordinate_error.clear();
        let _ = self.arm(label, ArmCommand::SetSpeed(UI_ARM_SPEED));
        let result = self.arm(
            label,
            ArmCommand::GotoCoords {
                x,
                y,
                z: kinematics::table_to_shoulder_z(z_table),
            },
        );
        if result.is_ok() {
            self.sync_goto_angles_from_targets();
        }
    }

    fn nudge_coordinates_relative(&mut self, label: &str, dx: f64, dy: f64, dz_table: f64) {
        let (dx, dy) = rotate_xy_deg(dx, dy, self.coordinate_base_yaw_offset_deg());
        let _ = self.arm(label, ArmCommand::SetSpeed(UI_ARM_SPEED));
        let result = self.arm(
            label,
            ArmCommand::MoveTcpRelative {
                frame: self.coordinate_frame,
                dx_mm: dx,
                dy_mm: dy,
                dz_mm: dz_table,
            },
        );
        if result.is_ok() {
            self.sync_coordinates_from_target();
            self.sync_goto_angles_from_targets();
        }
    }

    fn coordinate_forward_sign(&self) -> f64 {
        let robot = self.robot.lock().unwrap();
        f64::from(robot.coordinate_calibration().forward_sign)
    }

    fn coordinate_left_sign(&self) -> f64 {
        let robot = self.robot.lock().unwrap();
        f64::from(robot.coordinate_calibration().left_sign)
    }

    fn coordinate_base_yaw_offset_deg(&self) -> f64 {
        let robot = self.robot.lock().unwrap();
        robot.coordinate_calibration().base_yaw_offset_deg
    }

    fn move_to_goto_angles(&mut self, label: &str) {
        let Some(angles_rad) = self.parse_goto_angles() else {
            return;
        };
        let _ = self.arm(label, ArmCommand::SetSpeed(UI_ARM_SPEED));
        let result = self.arm(label, ArmCommand::GotoAngles(angles_rad));
        if result.is_ok() {
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
        let telemetry = {
            let robot = self.robot.lock().unwrap();
            robot.arm_telemetry()
        };
        if let Some(angles) = target_angle_inputs(&telemetry.joints) {
            self.goto_angle_yaw = angles[0].clone();
            self.goto_angle_shoulder = angles[1].clone();
            self.goto_angle_elbow = angles[2].clone();
            self.goto_angle_wrist = angles[3].clone();
            self.goto_angle_error.clear();
        }
    }

    fn sync_coordinates_from_target(&mut self) {
        let telemetry = {
            let robot = self.robot.lock().unwrap();
            robot.arm_telemetry()
        };
        if let Some(coords_mm) = telemetry.target_coords_mm {
            let (x, y, z) = coordinate_inputs(coords_mm);
            self.coordinate_x = x;
            self.coordinate_y = y;
            self.coordinate_z = z;
            self.coordinate_error.clear();
        }
    }

    pub(crate) fn drive_forward(&mut self) {
        self.drive("drive forward", UI_DRIVE_SPEED, 0);
    }

    pub(crate) fn drive_back(&mut self) {
        self.drive("drive back", -UI_DRIVE_SPEED, 0);
    }

    pub(crate) fn drive_left(&mut self) {
        self.drive("drive left", 0, -UI_STEER_SPEED);
    }

    pub(crate) fn drive_right(&mut self) {
        self.drive("drive right", 0, UI_STEER_SPEED);
    }

    pub(crate) fn stop_drive(&mut self) {
        let _ = self.apply_event("stop drive", ProtocolEvent::Drive(DriveCommand::Stop));
    }

    pub(crate) fn stop_joint(&mut self, joint_arg: u32) {
        let Some(joint) = Self::joint_arg_to_index(joint_arg) else {
            return;
        };

        let _ = self.arm("stop joint", ArmCommand::Stop { joint });
    }

    pub(crate) fn jog_stop(&mut self, joint_arg: u32) {
        self.stop_joint(joint_arg);
    }

    pub(crate) fn jog_negative_start(&mut self, joint_arg: u32) {
        self.spin_joint(joint_arg, -1);
    }

    pub(crate) fn jog_positive_start(&mut self, joint_arg: u32) {
        self.spin_joint(joint_arg, 1);
    }

    pub(crate) fn jog_negative_refresh(&mut self, joint_arg: u32) {
        self.refresh_spin_joint(joint_arg, -1);
    }

    pub(crate) fn jog_positive_refresh(&mut self, joint_arg: u32) {
        self.refresh_spin_joint(joint_arg, 1);
    }

    pub(crate) fn open_joint_calibration(&mut self, joint_arg: u32) {
        let Some(joint_index) = Self::joint_arg_to_index(joint_arg) else {
            return;
        };
        let telemetry = {
            let robot = self.robot.lock().unwrap();
            robot.arm_telemetry()
        };
        let joint = &telemetry.joints[joint_index];
        self.calibration_editor_joint = Some(joint_index);
        self.calibration_editor_angle = joint
            .angle_deg
            .map(|angle| format!("{angle:.1}"))
            .unwrap_or_else(|| "0.0".to_string());
        self.calibration_editor_error.clear();
    }

    pub(crate) fn close_joint_calibration(&mut self) {
        self.calibration_editor_joint = None;
        self.calibration_editor_error.clear();
    }

    pub(crate) fn edit_joint_reference_angle(&mut self, value: String) {
        self.calibration_editor_angle = value;
        self.calibration_editor_error.clear();
    }

    pub(crate) fn apply_joint_calibration(&mut self) {
        let Some((joint, angle_deg)) = self.parse_calibration_editor() else {
            return;
        };
        let tick = {
            let robot = self.robot.lock().unwrap();
            let telemetry = robot.arm_telemetry();
            if let Some(err) = joint_reference_tick_error(&telemetry.joints[joint]) {
                self.calibration_editor_error = err;
                return;
            }
            telemetry.joints[joint].tick
        };
        let Some(tick) = tick else {
            self.calibration_editor_error = "current tick unavailable".to_string();
            return;
        };

        let result = self.arm(
            &format!(
                "calibrate {} reference angle",
                ARM_JOINT_LABELS[joint].to_lowercase()
            ),
            ArmCommand::SetJointReference {
                joint,
                tick,
                angle_rad: angle_deg.to_radians(),
            },
        );
        if result.is_ok() {
            self.calibration_editor_joint = None;
            self.calibration_editor_error.clear();
        }
    }

    pub(crate) fn flip_joint_angle_sign(&mut self) {
        let Some(joint) = self.calibration_editor_joint else {
            return;
        };
        if joint >= JOINT_COUNT {
            self.calibration_editor_error = "invalid joint".to_string();
            return;
        }

        let label = ARM_JOINT_LABELS[joint].to_lowercase();
        let result = {
            let mut robot = self.robot.lock().unwrap();
            robot.flip_joint_angle_sign(joint)
        };
        match result {
            Ok(sign) => {
                self.calibration_editor_error.clear();
                self.last_command = format!("flipped {label} angle sign to {sign}");
                log::info!("runtime UI command: flipped {label} angle sign to {sign}");
            }
            Err(err) => {
                self.calibration_editor_error = err.clone();
                self.last_command = format!("flip {label} angle sign failed: {err}");
                log::warn!("runtime UI flip {label} angle sign failed: {err}");
            }
        }
    }

    pub(crate) fn set_joint_zero_start(&mut self, joint_arg: u32) {
        let Some(joint) = Self::joint_arg_to_index(joint_arg) else {
            return;
        };

        let label = format!("move {} to zero", ARM_JOINT_LABELS[joint].to_lowercase());
        let _ = self.arm(&label, ArmCommand::SetSpeed(UI_ARM_SPEED));
        let _ = self.arm(
            &label,
            ArmCommand::SetJointAngle {
                joint,
                angle_rad: 0.0,
            },
        );
    }

    pub(crate) fn set_joint_zero_refresh(&mut self, joint_arg: u32) {
        self.set_joint_zero_start(joint_arg);
    }

    pub(crate) fn set_joint_zero_stop(&mut self, joint_arg: u32) {
        self.stop_joint(joint_arg);
    }

    pub(crate) fn set_joint_zero(&mut self, joint_arg: u32) {
        self.set_joint_zero_start(joint_arg);
    }

    pub(crate) fn edit_goto_angle_yaw(&mut self, value: String) {
        self.goto_angle_yaw = value;
        self.goto_angle_error.clear();
    }

    pub(crate) fn edit_goto_angle_shoulder(&mut self, value: String) {
        self.goto_angle_shoulder = value;
        self.goto_angle_error.clear();
    }

    pub(crate) fn edit_goto_angle_elbow(&mut self, value: String) {
        self.goto_angle_elbow = value;
        self.goto_angle_error.clear();
    }

    pub(crate) fn edit_goto_angle_wrist(&mut self, value: String) {
        self.goto_angle_wrist = value;
        self.goto_angle_error.clear();
    }

    pub(crate) fn set_goto_angles_current(&mut self) {
        let telemetry = {
            let robot = self.robot.lock().unwrap();
            robot.arm_telemetry()
        };
        let mut angles = [0.0; JOINT_COUNT];
        for (index, joint) in telemetry.joints.iter().enumerate() {
            let Some(angle) = joint.angle_deg else {
                self.goto_angle_error = format!(
                    "current {} angle unavailable",
                    ARM_JOINT_LABELS[index].to_lowercase()
                );
                return;
            };
            angles[index] = angle;
        }
        self.goto_angle_yaw = format!("{:.1}", angles[0]);
        self.goto_angle_shoulder = format!("{:.1}", angles[1]);
        self.goto_angle_elbow = format!("{:.1}", angles[2]);
        self.goto_angle_wrist = format!("{:.1}", angles[3]);
        self.goto_angle_error.clear();
    }

    pub(crate) fn goto_angles_start(&mut self) {
        self.move_to_goto_angles("move to target angles");
    }

    pub(crate) fn goto_angles_refresh(&mut self) {
        self.move_to_goto_angles("move to target angles");
    }

    pub(crate) fn goto_default_angles_start(&mut self) {
        self.move_to_default_goto_angles();
    }

    pub(crate) fn goto_default_angles_refresh(&mut self) {
        self.move_to_default_goto_angles();
    }

    pub(crate) fn goto_angles_stop(&mut self) {
        let _ = self.arm("stop target angles", ArmCommand::StopAll);
    }

    pub(crate) fn set_tcp_frame_base(&mut self) {
        self.set_tcp_frame(TcpFrame::Base);
    }

    pub(crate) fn set_tcp_frame_tool(&mut self) {
        self.set_tcp_frame(TcpFrame::Tool);
    }

    pub(crate) fn move_tcp_forward_start(&mut self) {
        let (dx, dy, dz) = tcp_forward_delta_mm();
        self.move_tcp("move tcp forward", dx, dy, dz);
    }

    pub(crate) fn move_tcp_forward_refresh(&mut self) {
        let (dx, dy, dz) = tcp_forward_delta_mm();
        self.move_tcp("move tcp forward", dx, dy, dz);
    }

    pub(crate) fn move_tcp_back_start(&mut self) {
        let (dx, dy, dz) = tcp_back_delta_mm();
        self.move_tcp("move tcp back", dx, dy, dz);
    }

    pub(crate) fn move_tcp_back_refresh(&mut self) {
        let (dx, dy, dz) = tcp_back_delta_mm();
        self.move_tcp("move tcp back", dx, dy, dz);
    }

    pub(crate) fn move_tcp_left_start(&mut self) {
        self.move_tcp("move tcp left", 0.0, UI_TCP_STEP_MM, 0.0);
    }

    pub(crate) fn move_tcp_left_refresh(&mut self) {
        self.move_tcp("move tcp left", 0.0, UI_TCP_STEP_MM, 0.0);
    }

    pub(crate) fn move_tcp_right_start(&mut self) {
        self.move_tcp("move tcp right", 0.0, -UI_TCP_STEP_MM, 0.0);
    }

    pub(crate) fn move_tcp_right_refresh(&mut self) {
        self.move_tcp("move tcp right", 0.0, -UI_TCP_STEP_MM, 0.0);
    }

    pub(crate) fn move_tcp_stop(&mut self) {
        let _ = self.arm("stop tcp jog", ArmCommand::StopAll);
    }

    pub(crate) fn edit_coordinate_x(&mut self, value: String) {
        self.coordinate_x = value;
        self.coordinate_error.clear();
    }

    pub(crate) fn edit_coordinate_y(&mut self, value: String) {
        self.coordinate_y = value;
        self.coordinate_error.clear();
    }

    pub(crate) fn edit_coordinate_z(&mut self, value: String) {
        self.coordinate_z = value;
        self.coordinate_error.clear();
    }

    pub(crate) fn set_coordinates_current(&mut self) {
        let coords = {
            let robot = self.robot.lock().unwrap();
            robot.arm_telemetry().coords_mm
        };
        if let Some((x, y, z)) = coords {
            self.coordinate_x = format!("{x:.1}");
            self.coordinate_y = format!("{y:.1}");
            self.coordinate_z = format!("{z:.1}");
            self.coordinate_error.clear();
        } else {
            self.coordinate_error = "current position unavailable".to_string();
        }
    }

    pub(crate) fn move_to_coordinates(&mut self) {
        let Some((x, y, z_table)) = self.parse_coordinates() else {
            return;
        };
        self.move_to_coordinate_target("move to coordinates", x, y, z_table);
    }

    pub(crate) fn set_coordinate_frame_base(&mut self) {
        self.set_coordinate_frame(TcpFrame::Base);
    }

    pub(crate) fn set_coordinate_frame_yaw_flat(&mut self) {
        self.set_coordinate_frame(TcpFrame::YawFlat);
    }

    pub(crate) fn coordinate_forward(&mut self) {
        self.nudge_coordinates_relative(
            "coordinate forward",
            UI_COORD_STEP_MM * self.coordinate_forward_sign(),
            0.0,
            0.0,
        );
    }

    pub(crate) fn coordinate_forward_start(&mut self) {
        self.coordinate_forward();
    }

    pub(crate) fn coordinate_forward_refresh(&mut self) {
        self.coordinate_forward();
    }

    pub(crate) fn coordinate_back(&mut self) {
        self.nudge_coordinates_relative(
            "coordinate back",
            -UI_COORD_STEP_MM * self.coordinate_forward_sign(),
            0.0,
            0.0,
        );
    }

    pub(crate) fn coordinate_back_start(&mut self) {
        self.coordinate_back();
    }

    pub(crate) fn coordinate_back_refresh(&mut self) {
        self.coordinate_back();
    }

    pub(crate) fn coordinate_left(&mut self) {
        self.nudge_coordinates_relative(
            "coordinate left",
            0.0,
            UI_COORD_STEP_MM * self.coordinate_left_sign(),
            0.0,
        );
    }

    pub(crate) fn coordinate_left_start(&mut self) {
        self.coordinate_left();
    }

    pub(crate) fn coordinate_left_refresh(&mut self) {
        self.coordinate_left();
    }

    pub(crate) fn coordinate_right(&mut self) {
        self.nudge_coordinates_relative(
            "coordinate right",
            0.0,
            -UI_COORD_STEP_MM * self.coordinate_left_sign(),
            0.0,
        );
    }

    pub(crate) fn coordinate_right_start(&mut self) {
        self.coordinate_right();
    }

    pub(crate) fn coordinate_right_refresh(&mut self) {
        self.coordinate_right();
    }

    pub(crate) fn coordinate_up(&mut self) {
        self.nudge_coordinates_relative("coordinate up", 0.0, 0.0, UI_COORD_STEP_MM);
    }

    pub(crate) fn coordinate_up_start(&mut self) {
        self.coordinate_up();
    }

    pub(crate) fn coordinate_up_refresh(&mut self) {
        self.coordinate_up();
    }

    pub(crate) fn coordinate_down(&mut self) {
        self.nudge_coordinates_relative("coordinate down", 0.0, 0.0, -UI_COORD_STEP_MM);
    }

    pub(crate) fn coordinate_down_start(&mut self) {
        self.coordinate_down();
    }

    pub(crate) fn coordinate_down_refresh(&mut self) {
        self.coordinate_down();
    }

    pub(crate) fn flip_coordinate_forward_axis(&mut self) {
        let sign = {
            let mut robot = self.robot.lock().unwrap();
            robot.flip_coordinate_forward_sign()
        };
        self.last_command = format!("flipped coordinate forward sign to {sign}");
        log::info!("runtime UI command: flipped coordinate forward sign to {sign}");
    }

    pub(crate) fn flip_coordinate_left_axis(&mut self) {
        let sign = {
            let mut robot = self.robot.lock().unwrap();
            robot.flip_coordinate_left_sign()
        };
        self.last_command = format!("flipped coordinate left sign to {sign}");
        log::info!("runtime UI command: flipped coordinate left sign to {sign}");
    }

    pub(crate) fn rotate_coordinate_base_frame(&mut self) {
        let offset = {
            let mut robot = self.robot.lock().unwrap();
            robot.rotate_coordinate_base_yaw_offset_deg()
        };
        self.last_command = format!("rotated coordinate base frame to {offset:.0} deg");
        log::info!("runtime UI command: rotated coordinate base frame to {offset:.0} deg");
    }

    pub(crate) fn arm_hold(&mut self) {
        let _ = self.arm("arm hold", ArmCommand::SetSpeed(UI_ARM_SPEED));
        let _ = self.arm("arm hold", ArmCommand::Hold);
    }

    pub(crate) fn arm_stop_all(&mut self) {
        let _ = self.arm("arm stop all", ArmCommand::StopAll);
    }

    pub(crate) fn clear_arm_faults(&mut self) {
        let _ = self.arm("clear arm faults", ArmCommand::ClearFaults { joint: None });
    }

    pub(crate) fn open_limit_editor(&mut self, joint_arg: u32) {
        let Some(joint_index) = Self::joint_arg_to_index(joint_arg) else {
            return;
        };
        let telemetry = {
            let robot = self.robot.lock().unwrap();
            robot.arm_telemetry()
        };
        let joint = &telemetry.joints[joint_index];
        self.limit_editor_joint = Some(joint_index);
        self.limit_editor_min = joint.limit_min.to_string();
        self.limit_editor_max = joint.limit_max.to_string();
        self.limit_editor_error.clear();
    }

    pub(crate) fn close_limit_editor(&mut self) {
        self.limit_editor_joint = None;
        self.limit_editor_error.clear();
    }

    pub(crate) fn edit_limit_min(&mut self, value: String) {
        self.limit_editor_min = value;
        self.limit_editor_error.clear();
    }

    pub(crate) fn edit_limit_max(&mut self, value: String) {
        self.limit_editor_max = value;
        self.limit_editor_error.clear();
    }

    pub(crate) fn limit_min_down(&mut self, joint_arg: u32) {
        let _ = joint_arg;
        self.nudge_limit_editor(-UI_LIMIT_STEP_TICKS, 0);
    }

    pub(crate) fn limit_min_up(&mut self, joint_arg: u32) {
        let _ = joint_arg;
        self.nudge_limit_editor(UI_LIMIT_STEP_TICKS, 0);
    }

    pub(crate) fn limit_max_down(&mut self, joint_arg: u32) {
        let _ = joint_arg;
        self.nudge_limit_editor(0, -UI_LIMIT_STEP_TICKS);
    }

    pub(crate) fn limit_max_up(&mut self, joint_arg: u32) {
        let _ = joint_arg;
        self.nudge_limit_editor(0, UI_LIMIT_STEP_TICKS);
    }

    pub(crate) fn set_limit_min_current(&mut self, joint_arg: u32) {
        let _ = joint_arg;
        let Some(joint) = self.limit_editor_joint else {
            return;
        };
        let telemetry = {
            let robot = self.robot.lock().unwrap();
            robot.arm_telemetry()
        };
        if let Some(tick) = telemetry.joints[joint].tick {
            self.limit_editor_min = tick.to_string();
            self.limit_editor_error.clear();
        } else {
            self.limit_editor_error = "no feedback tick for selected joint".to_string();
        }
    }

    pub(crate) fn set_limit_max_current(&mut self, joint_arg: u32) {
        let _ = joint_arg;
        let Some(joint) = self.limit_editor_joint else {
            return;
        };
        let telemetry = {
            let robot = self.robot.lock().unwrap();
            robot.arm_telemetry()
        };
        if let Some(tick) = telemetry.joints[joint].tick {
            self.limit_editor_max = tick.to_string();
            self.limit_editor_error.clear();
        } else {
            self.limit_editor_error = "no feedback tick for selected joint".to_string();
        }
    }

    pub(crate) fn toggle_joint_limits(&mut self, joint_arg: u32) {
        let Some(joint) = Self::joint_arg_to_index(joint_arg) else {
            return;
        };
        let enabled = {
            let robot = self.robot.lock().unwrap();
            let telemetry = robot.arm_telemetry();
            !telemetry.joints[joint].limit_enabled
        };
        let _ = self.arm(
            if enabled {
                "enable joint limits"
            } else {
                "disable joint limits"
            },
            ArmCommand::SetTickLimitsEnabled { joint, enabled },
        );
    }

    pub(crate) fn apply_limit_editor(&mut self) {
        let Some((joint, min, max)) = self.parse_limit_editor() else {
            return;
        };
        let _ = self.arm(
            "set joint limits",
            ArmCommand::SetTickLimits { joint, min, max },
        );
        self.limit_editor_joint = None;
        self.limit_editor_error.clear();
    }

    pub(crate) fn save_calibration(&mut self) {
        let result = {
            let mut robot = self.robot.lock().unwrap();
            robot.save_calibration()
        };
        match result {
            Ok(path) => {
                self.last_command = format!("saved calibration to {path}");
                log::info!("runtime UI command: save calibration to {path}");
            }
            Err(err) => {
                self.last_command = format!("save calibration failed: {err}");
                log::warn!("runtime UI save calibration failed: {err}");
            }
        }
    }
}

pub(crate) fn start_runtime_ui(
    bind: SocketAddr,
    config: RuntimeUiConfig,
    robot: Arc<Mutex<RuntimeRobot>>,
) -> thread::JoinHandle<()> {
    thread::spawn(move || {
        let runtime = tokio::runtime::Builder::new_multi_thread()
            .enable_all()
            .build()
            .expect("failed to start runtime UI tokio runtime");

        runtime.block_on(async move {
            let page_config = config.clone();
            let page_robot = robot.clone();
            let mut wgui = Wgui::new(bind);
            wgui.set_css(RUNTIME_UI_CSS);
            wgui.add_page_with("/", move || {
                let config = page_config.clone();
                let robot = page_robot.clone();
                async move { RuntimeUiController::new(config, robot) }
            });
            wgui.run().await;
        });
    })
}

#[cfg(test)]
mod tests {
    use std::path::PathBuf;

    use super::*;

    fn test_ui_config() -> RuntimeUiConfig {
        RuntimeUiConfig {
            ws_bind: "127.0.0.1:0".to_string(),
            ws_url: "ws://127.0.0.1:0/ws".to_string(),
            ui_bind: "127.0.0.1:0".to_string(),
            ui_url: "http://127.0.0.1:0".to_string(),
            servo_status: "simulated".to_string(),
            servo_detail: "test".to_string(),
        }
    }

    fn test_controller() -> RuntimeUiController {
        let robot = Arc::new(Mutex::new(RuntimeRobot::new(
            None,
            PathBuf::from("/tmp/puppybot-runtime-ui-test.json"),
            Default::default(),
        )));
        RuntimeUiController::new(test_ui_config(), robot)
    }

    fn goto_angle_inputs(controller: &RuntimeUiController) -> [String; JOINT_COUNT] {
        [
            controller.goto_angle_yaw.clone(),
            controller.goto_angle_shoulder.clone(),
            controller.goto_angle_elbow.clone(),
            controller.goto_angle_wrist.clone(),
        ]
    }

    fn current_coordinate_inputs(controller: &RuntimeUiController) -> (String, String, String) {
        (
            controller.coordinate_x.clone(),
            controller.coordinate_y.clone(),
            controller.coordinate_z.clone(),
        )
    }

    #[test]
    fn unreachable_coordinate_error_mentions_target() {
        let err = arm_command_error_text(
            ArmCommand::GotoCoords {
                x: 1000.0,
                y: 20.0,
                z: kinematics::table_to_shoulder_z(80.0),
            },
            ControllerError::Ik(IkError::Unreachable),
        );

        assert_eq!(
            err.as_deref(),
            Some("target unreachable: 1000.0, 20.0, 80.0 mm")
        );
    }

    #[test]
    fn tcp_forward_and_back_use_positive_and_negative_x_deltas() {
        assert_eq!(tcp_forward_delta_mm(), (UI_TCP_STEP_MM, 0.0, 0.0));
        assert_eq!(tcp_back_delta_mm(), (-UI_TCP_STEP_MM, 0.0, 0.0));
    }

    #[test]
    fn coordinate_rotation_rotates_xy_by_degrees() {
        let (x, y) = rotate_xy_deg(10.0, 0.0, 90.0);

        assert!(x.abs() < 1.0e-9);
        assert!((y - 10.0).abs() < 1.0e-9);
    }

    #[test]
    fn coordinate_frame_switch_is_independent_from_tcp_jog_frame() {
        let mut controller = test_controller();

        assert_eq!(controller.coordinate_frame, TcpFrame::YawFlat);
        assert_eq!(controller.tcp_frame, TcpFrame::Base);
        assert_eq!(controller.state().coordinate_frame_label, "Yaw-flat");

        controller.set_coordinate_frame_base();

        assert_eq!(controller.coordinate_frame, TcpFrame::Base);
        assert_eq!(controller.tcp_frame, TcpFrame::Base);
        assert_eq!(controller.last_command, "set coordinate frame base");
        let state = controller.state();
        assert_eq!(state.coordinate_frame_label, "Base");
        assert_eq!(state.coordinate_base_button.background, "#1e5f9f");
        assert_eq!(state.coordinate_yaw_flat_button.background, "#182838");

        controller.set_coordinate_frame_yaw_flat();

        assert_eq!(controller.coordinate_frame, TcpFrame::YawFlat);
        assert_eq!(controller.tcp_frame, TcpFrame::Base);
        assert_eq!(controller.last_command, "set coordinate frame yaw-flat");
    }

    #[test]
    fn rotate_coordinate_base_frame_updates_calibration_detail() {
        let mut controller = test_controller();

        assert!(
            controller
                .state()
                .coordinate_calibration_detail
                .contains("base rotation 0 deg")
        );

        controller.rotate_coordinate_base_frame();

        assert_eq!(
            controller.last_command,
            "rotated coordinate base frame to 90 deg"
        );
        assert!(
            controller
                .state()
                .coordinate_calibration_detail
                .contains("base rotation 90 deg")
        );
        assert!(controller.robot.lock().unwrap().calibration_state().0);

        controller.rotate_coordinate_base_frame();
        assert!(
            controller
                .state()
                .coordinate_calibration_detail
                .contains("base rotation 180 deg")
        );

        controller.rotate_coordinate_base_frame();
        assert!(
            controller
                .state()
                .coordinate_calibration_detail
                .contains("base rotation 270 deg")
        );

        controller.rotate_coordinate_base_frame();
        assert!(
            controller
                .state()
                .coordinate_calibration_detail
                .contains("base rotation 0 deg")
        );
    }

    #[test]
    fn coordinate_forward_reports_missing_feedback_without_using_inputs() {
        let mut controller = test_controller();
        controller.edit_coordinate_x("100.0".to_string());
        controller.edit_coordinate_y("0.0".to_string());
        controller.edit_coordinate_z("80.0".to_string());

        controller.coordinate_forward();

        assert_eq!(controller.coordinate_error, "current position unavailable");
        assert_eq!(
            controller.last_command,
            "coordinate forward rejected: MissingFeedback"
        );
        assert_eq!(
            current_coordinate_inputs(&controller),
            ("100.0".to_string(), "0.0".to_string(), "80.0".to_string())
        );
    }

    #[test]
    fn coordinate_back_reports_missing_feedback_without_using_inputs() {
        let mut controller = test_controller();
        controller.edit_coordinate_x("100.0".to_string());
        controller.edit_coordinate_y("0.0".to_string());
        controller.edit_coordinate_z("80.0".to_string());

        controller.coordinate_back();

        assert_eq!(controller.coordinate_error, "current position unavailable");
        assert_eq!(
            controller.last_command,
            "coordinate back rejected: MissingFeedback"
        );
        assert_eq!(
            current_coordinate_inputs(&controller),
            ("100.0".to_string(), "0.0".to_string(), "80.0".to_string())
        );
    }

    #[test]
    fn coordinate_left_reports_missing_feedback_without_using_inputs() {
        let mut controller = test_controller();
        controller.edit_coordinate_x("100.0".to_string());
        controller.edit_coordinate_y("0.0".to_string());
        controller.edit_coordinate_z("80.0".to_string());

        controller.coordinate_left();

        assert_eq!(controller.coordinate_error, "current position unavailable");
        assert_eq!(
            controller.last_command,
            "coordinate left rejected: MissingFeedback"
        );
        assert_eq!(
            current_coordinate_inputs(&controller),
            ("100.0".to_string(), "0.0".to_string(), "80.0".to_string())
        );
    }

    #[test]
    fn coordinate_up_reports_missing_feedback_without_using_inputs() {
        let mut controller = test_controller();
        controller.edit_coordinate_x("100.0".to_string());
        controller.edit_coordinate_y("0.0".to_string());
        controller.edit_coordinate_z("80.0".to_string());

        controller.coordinate_up();

        assert_eq!(controller.coordinate_error, "current position unavailable");
        assert_eq!(
            controller.last_command,
            "coordinate up rejected: MissingFeedback"
        );
        assert_eq!(
            current_coordinate_inputs(&controller),
            ("100.0".to_string(), "0.0".to_string(), "80.0".to_string())
        );
    }

    #[test]
    fn coordinate_move_updates_goto_angle_inputs_from_target_telemetry() {
        let mut controller = test_controller();
        controller.edit_goto_angle_yaw("91.0".to_string());
        controller.edit_goto_angle_shoulder("92.0".to_string());
        controller.edit_goto_angle_elbow("93.0".to_string());
        controller.edit_goto_angle_wrist("94.0".to_string());
        controller.edit_coordinate_x("-200.0".to_string());
        controller.edit_coordinate_y("0.0".to_string());
        controller.edit_coordinate_z("75.0".to_string());

        controller.move_to_coordinates();

        let telemetry = controller.robot.lock().unwrap().arm_telemetry();
        assert_eq!(
            goto_angle_inputs(&controller),
            target_angle_inputs(&telemetry.joints).unwrap()
        );
        assert_ne!(
            goto_angle_inputs(&controller),
            [
                "91.0".to_string(),
                "92.0".to_string(),
                "93.0".to_string(),
                "94.0".to_string(),
            ]
        );
        assert_eq!(controller.coordinate_error, "");
        assert!(!controller.robot.lock().unwrap().calibration_state().0);
    }

    #[test]
    fn rejected_coordinate_move_leaves_goto_angle_inputs_unchanged() {
        let mut controller = test_controller();
        controller.edit_goto_angle_yaw("11.0".to_string());
        controller.edit_goto_angle_shoulder("12.0".to_string());
        controller.edit_goto_angle_elbow("13.0".to_string());
        controller.edit_goto_angle_wrist("14.0".to_string());
        controller.edit_coordinate_x("1000.0".to_string());
        controller.edit_coordinate_y("20.0".to_string());
        controller.edit_coordinate_z("80.0".to_string());

        controller.move_to_coordinates();

        assert_eq!(
            goto_angle_inputs(&controller),
            [
                "11.0".to_string(),
                "12.0".to_string(),
                "13.0".to_string(),
                "14.0".to_string(),
            ]
        );
        assert_eq!(
            controller.coordinate_error,
            "target unreachable: 1000.0, 20.0, 80.0 mm"
        );
        assert!(!controller.robot.lock().unwrap().calibration_state().0);
    }

    #[test]
    fn parse_goto_angles_accepts_finite_degrees() {
        let mut controller = test_controller();
        controller.edit_goto_angle_yaw("10".to_string());
        controller.edit_goto_angle_shoulder("-20.5".to_string());
        controller.edit_goto_angle_elbow("30".to_string());
        controller.edit_goto_angle_wrist("0".to_string());

        let angles = controller.parse_goto_angles().unwrap();

        assert_eq!(
            angles,
            [
                10.0_f64.to_radians(),
                (-20.5_f64).to_radians(),
                30.0_f64.to_radians(),
                0.0,
            ]
        );
        assert_eq!(controller.goto_angle_error, "");
    }

    #[test]
    fn goto_angles_start_rejects_invalid_input_without_motion() {
        let mut controller = test_controller();
        controller.edit_goto_angle_yaw("0".to_string());
        controller.edit_goto_angle_shoulder("not-a-number".to_string());
        controller.edit_goto_angle_elbow("0".to_string());
        controller.edit_goto_angle_wrist("0".to_string());

        controller.goto_angles_start();

        assert_eq!(
            controller.goto_angle_error,
            "shoulder angle must be a number"
        );
        assert_eq!(controller.last_command, "none");
        assert!(!controller.robot.lock().unwrap().calibration_state().0);
    }

    #[test]
    fn goto_angles_start_uses_motion_command_path_without_dirtying_calibration() {
        let mut controller = test_controller();
        controller.edit_goto_angle_yaw("10".to_string());
        controller.edit_goto_angle_shoulder("20".to_string());
        controller.edit_goto_angle_elbow("-30".to_string());
        controller.edit_goto_angle_wrist("40".to_string());

        controller.goto_angles_start();

        assert_eq!(controller.last_command, "move to target angles");
        assert_eq!(controller.goto_angle_error, "");
        assert!(!controller.robot.lock().unwrap().calibration_state().0);
    }

    #[test]
    fn goto_angles_start_updates_coordinate_inputs_from_target_coords() {
        let mut controller = test_controller();
        controller.edit_coordinate_x("1.0".to_string());
        controller.edit_coordinate_y("2.0".to_string());
        controller.edit_coordinate_z("3.0".to_string());
        controller.edit_goto_angle_yaw("10".to_string());
        controller.edit_goto_angle_shoulder("70".to_string());
        controller.edit_goto_angle_elbow("25".to_string());
        controller.edit_goto_angle_wrist("-15".to_string());

        controller.goto_angles_start();

        let telemetry = controller.robot.lock().unwrap().arm_telemetry();
        assert_eq!(
            current_coordinate_inputs(&controller),
            coordinate_inputs(telemetry.target_coords_mm.unwrap())
        );
        assert_ne!(
            current_coordinate_inputs(&controller),
            ("1.0".to_string(), "2.0".to_string(), "3.0".to_string())
        );
        assert_eq!(controller.goto_angle_error, "");
        assert_eq!(controller.coordinate_error, "");
        assert!(!controller.robot.lock().unwrap().calibration_state().0);
    }

    #[test]
    fn goto_angles_refresh_uses_motion_command_path() {
        let mut controller = test_controller();
        controller.edit_goto_angle_yaw("1".to_string());
        controller.edit_goto_angle_shoulder("2".to_string());
        controller.edit_goto_angle_elbow("3".to_string());
        controller.edit_goto_angle_wrist("4".to_string());

        controller.goto_angles_refresh();

        assert_eq!(controller.last_command, "move to target angles");
    }

    #[test]
    fn goto_angles_refresh_updates_coordinate_inputs_from_target_coords() {
        let mut controller = test_controller();
        controller.edit_coordinate_x("10.0".to_string());
        controller.edit_coordinate_y("20.0".to_string());
        controller.edit_coordinate_z("30.0".to_string());
        controller.edit_goto_angle_yaw("-5".to_string());
        controller.edit_goto_angle_shoulder("80".to_string());
        controller.edit_goto_angle_elbow("15".to_string());
        controller.edit_goto_angle_wrist("5".to_string());

        controller.goto_angles_refresh();

        let telemetry = controller.robot.lock().unwrap().arm_telemetry();
        assert_eq!(
            current_coordinate_inputs(&controller),
            coordinate_inputs(telemetry.target_coords_mm.unwrap())
        );
        assert!(!controller.robot.lock().unwrap().calibration_state().0);
    }

    #[test]
    fn goto_default_angles_start_moves_to_ninety_degree_targets() {
        let mut controller = test_controller();
        controller.edit_coordinate_x("10.0".to_string());
        controller.edit_coordinate_y("20.0".to_string());
        controller.edit_coordinate_z("30.0".to_string());
        controller.edit_goto_angle_yaw("1".to_string());
        controller.edit_goto_angle_shoulder("2".to_string());
        controller.edit_goto_angle_elbow("3".to_string());
        controller.edit_goto_angle_wrist("4".to_string());

        controller.goto_default_angles_start();

        assert_eq!(
            goto_angle_inputs(&controller),
            [
                "90.0".to_string(),
                "90.0".to_string(),
                "90.0".to_string(),
                "90.0".to_string(),
            ]
        );
        assert_eq!(controller.last_command, "move to default target angles");
        let telemetry = controller.robot.lock().unwrap().arm_telemetry();
        assert_eq!(
            current_coordinate_inputs(&controller),
            coordinate_inputs(telemetry.target_coords_mm.unwrap())
        );
        assert_eq!(controller.goto_angle_error, "");
        assert_eq!(controller.coordinate_error, "");
        assert!(!controller.robot.lock().unwrap().calibration_state().0);
    }

    #[test]
    fn goto_default_angles_refresh_repeats_default_motion() {
        let mut controller = test_controller();

        controller.goto_default_angles_refresh();

        assert_eq!(controller.last_command, "move to default target angles");
        assert_eq!(
            goto_angle_inputs(&controller),
            [
                "90.0".to_string(),
                "90.0".to_string(),
                "90.0".to_string(),
                "90.0".to_string(),
            ]
        );
    }

    #[test]
    fn invalid_goto_angles_leave_coordinate_inputs_unchanged() {
        let mut controller = test_controller();
        controller.edit_coordinate_x("10.0".to_string());
        controller.edit_coordinate_y("20.0".to_string());
        controller.edit_coordinate_z("30.0".to_string());
        controller.edit_goto_angle_yaw("0".to_string());
        controller.edit_goto_angle_shoulder("not-a-number".to_string());
        controller.edit_goto_angle_elbow("0".to_string());
        controller.edit_goto_angle_wrist("0".to_string());

        controller.goto_angles_start();

        assert_eq!(
            current_coordinate_inputs(&controller),
            ("10.0".to_string(), "20.0".to_string(), "30.0".to_string())
        );
        assert_eq!(
            controller.goto_angle_error,
            "shoulder angle must be a number"
        );
        assert_eq!(controller.last_command, "none");
        assert!(!controller.robot.lock().unwrap().calibration_state().0);
    }

    #[test]
    fn goto_angles_stop_stops_all_without_dirtying_calibration() {
        let mut controller = test_controller();

        controller.goto_angles_stop();

        assert_eq!(controller.last_command, "stop target angles");
        assert!(!controller.robot.lock().unwrap().calibration_state().0);
    }

    #[test]
    fn apply_joint_calibration_without_feedback_reports_unavailable_tick() {
        let mut controller = test_controller();

        controller.open_joint_calibration(1);
        controller.edit_joint_reference_angle("0".to_string());
        controller.apply_joint_calibration();

        assert_eq!(
            controller.calibration_editor_error,
            "current tick unavailable"
        );
    }

    #[test]
    fn flip_joint_angle_sign_marks_calibration_dirty_and_keeps_modal_open() {
        let mut controller = test_controller();

        controller.open_joint_calibration(4);
        controller.flip_joint_angle_sign();

        assert_eq!(controller.last_command, "flipped wrist angle sign to -1");
        assert_eq!(controller.calibration_editor_error, "");
        assert_eq!(controller.calibration_editor_joint, Some(3));
        assert_eq!(
            controller.robot.lock().unwrap().joint_angle_sign(3),
            Some(-1)
        );
        assert!(controller.robot.lock().unwrap().calibration_state().0);
    }

    #[test]
    fn calibration_state_reports_current_joint_angle_sign() {
        let mut controller = test_controller();

        controller.open_joint_calibration(4);
        assert_eq!(controller.state().calibration_modal_sign, "Angle sign: +1");

        controller.flip_joint_angle_sign();

        assert_eq!(controller.state().calibration_modal_sign, "Angle sign: -1");
    }

    #[test]
    fn set_joint_zero_start_without_feedback_uses_motion_command_path() {
        let mut controller = test_controller();

        controller.set_joint_zero_start(1);

        assert_eq!(
            controller.last_command,
            "move yaw to zero rejected: MissingFeedback"
        );
        assert!(!controller.robot.lock().unwrap().calibration_state().0);
    }

    #[test]
    fn set_joint_zero_stop_stops_selected_joint_without_dirtying_calibration() {
        let mut controller = test_controller();

        controller.set_joint_zero_stop(2);

        assert_eq!(controller.last_command, "stop joint");
        assert!(!controller.robot.lock().unwrap().calibration_state().0);
    }

    #[test]
    fn set_joint_zero_ignores_invalid_args_without_changing_last_command() {
        let mut controller = test_controller();

        controller.set_joint_zero_start(0);
        controller.set_joint_zero_stop(0);
        controller.set_joint_zero_refresh(0);

        assert_eq!(controller.last_command, "none");
    }

    #[test]
    fn joint_reference_tick_error_allows_ticks_outside_movement_range() {
        let mut joint = Joint::new(2, 100, 1000);
        joint.tick = Some(2048);

        assert_eq!(joint_reference_tick_error(&joint), None);
    }

    #[test]
    fn joint_reference_tick_error_mentions_servo_range() {
        let mut joint = Joint::new(2, 100, 1000);
        joint.tick = Some(4096);

        assert_eq!(
            joint_reference_tick_error(&joint),
            Some("current tick 4096 is outside servo range 0..4095".to_string())
        );
    }
}
