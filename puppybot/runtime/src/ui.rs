use std::{
    net::{IpAddr, SocketAddr},
    sync::{Arc, Mutex},
    thread,
};

use puppybot_core::{
    drive::DriveCommand,
    protocol::ProtocolEvent,
    puppyarm::types::{ArmCommand, JOINT_COUNT, Joint, TcpFrame},
};
use wgui::{Wgui, WguiModel, wgui_controller};

use crate::RuntimeRobot;

const RUNTIME_UI_CSS: &str = include_str!("../wui/runtime.css");
const UI_ARM_SPEED: i16 = 220;
const UI_TCP_STEP_MM: f64 = 5.0;
const UI_DRIVE_SPEED: i8 = 35;
const UI_STEER_SPEED: i8 = 55;
const ARM_JOINT_LABELS: [&str; JOINT_COUNT] = ["Yaw", "Shoulder", "Elbow", "Wrist"];

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
    accent: String,
    background: String,
    border: String,
}

#[derive(Clone, Debug, WguiModel)]
pub(crate) struct RuntimeUiJoint {
    index: u32,
    action_arg: u32,
    label: String,
    negative: RuntimeUiJogButton,
    positive: RuntimeUiJogButton,
    limit: RuntimeUiLimit,
}

#[derive(Clone, Debug, WguiModel)]
pub(crate) struct RuntimeUiModel {
    title: String,
    subtitle: String,
    status: Vec<RuntimeUiMetric>,
    endpoints: Vec<RuntimeUiMetric>,
    joints: Vec<RuntimeUiJoint>,
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

fn metric(label: &str, value: &str, detail: &str, accent: &str) -> RuntimeUiMetric {
    RuntimeUiMetric {
        label: label.to_string(),
        value: value.to_string(),
        detail: detail.to_string(),
        accent: accent.to_string(),
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
            accent: "#8ea0b7".to_string(),
            background: "#202936".to_string(),
            border: "1px solid #415066".to_string(),
        };
    }

    if !joint.has_feedback {
        return RuntimeUiLimit {
            label: "No feedback".to_string(),
            detail: "waiting for servo position".to_string(),
            accent: "#8ea0b7".to_string(),
            background: "#202936".to_string(),
            border: "1px solid #415066".to_string(),
        };
    }

    if joint.limit_reached {
        return RuntimeUiLimit {
            label: "LIMIT".to_string(),
            detail: limit_detail(joint),
            accent: "#ffb8b8".to_string(),
            background: "#7f2525".to_string(),
            border: "1px solid #d85b5b".to_string(),
        };
    }

    RuntimeUiLimit {
        label: "OK".to_string(),
        detail: limit_detail(joint),
        accent: "#bff0cf".to_string(),
        background: "#1d5034".to_string(),
        border: "1px solid #3fbf6f".to_string(),
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
            negative: jog_button("-"),
            positive: jog_button("+"),
            limit: limit_status(&joints[index]),
        })
        .collect()
}

pub(crate) fn local_url(addr: SocketAddr, scheme: &str, path: &str) -> String {
    format!("{scheme}://{}:{}{path}", ui_host(addr), addr.port())
}

#[wgui_controller(template = "runtime")]
impl RuntimeUiController {
    pub(crate) fn new(config: RuntimeUiConfig, robot: Arc<Mutex<RuntimeRobot>>) -> Self {
        Self {
            config,
            robot,
            tcp_frame: TcpFrame::Base,
            last_command: "none".to_string(),
        }
    }

    pub(crate) fn state(&self) -> RuntimeUiModel {
        let telemetry = {
            let robot = self.robot.lock().unwrap();
            robot.arm_telemetry()
        };

        RuntimeUiModel {
            title: "Puppybot Runtime".to_string(),
            subtitle: "Local runtime status and connection details".to_string(),
            status: vec![
                metric(
                    "Runtime",
                    "running",
                    "process is accepting robot websocket clients",
                    "#3fbf6f",
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
                ),
            ],
            endpoints: vec![
                metric(
                    "Runtime WebSocket",
                    &self.config.ws_url,
                    &self.config.ws_bind,
                    "#4d8dff",
                ),
                metric(
                    "Runtime UI",
                    &self.config.ui_url,
                    &self.config.ui_bind,
                    "#4d8dff",
                ),
            ],
            joints: joint_controls(&telemetry.joints),
            tcp_frame_label: self.tcp_frame_label().to_string(),
            tcp_frame_detail: self.tcp_frame_detail().to_string(),
            tcp_base_button: frame_button("Base", self.tcp_frame == TcpFrame::Base),
            tcp_tool_button: frame_button("Tool", self.tcp_frame == TcpFrame::Tool),
            last_command: self.last_command.clone(),
        }
    }

    pub(crate) fn title(&self) -> String {
        self.state().title
    }

    fn apply_event(&mut self, label: &str, event: ProtocolEvent) {
        {
            let mut robot = self.robot.lock().unwrap();
            robot.handle_event(event);
        }
        self.last_command = label.to_string();
        log::info!("runtime UI command: {label}");
    }

    fn drive(&mut self, label: &str, throttle: i8, steering: i8) {
        self.apply_event(
            label,
            ProtocolEvent::Drive(DriveCommand::DriveSteer { throttle, steering }),
        );
    }

    fn arm(&mut self, label: &str, command: ArmCommand) {
        self.apply_event(label, ProtocolEvent::Arm(command));
    }

    fn tcp_frame_label(&self) -> &'static str {
        match self.tcp_frame {
            TcpFrame::Base => "Base",
            TcpFrame::Tool => "Tool",
        }
    }

    fn tcp_frame_detail(&self) -> &'static str {
        match self.tcp_frame {
            TcpFrame::Base => "moves along robot base axes",
            TcpFrame::Tool => "moves along current TCP/tool axes",
        }
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
        self.arm(label, ArmCommand::SetSpeed(UI_ARM_SPEED));
        self.arm(
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
        self.arm(label, ArmCommand::SetSpeed(UI_ARM_SPEED));
        self.arm(label, ArmCommand::Spin { joint, direction });
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
        self.apply_event("stop drive", ProtocolEvent::Drive(DriveCommand::Stop));
    }

    pub(crate) fn stop_joint(&mut self, joint_arg: u32) {
        let Some(joint) = Self::joint_arg_to_index(joint_arg) else {
            return;
        };

        self.arm("stop joint", ArmCommand::Stop { joint });
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

    pub(crate) fn set_tcp_frame_base(&mut self) {
        self.set_tcp_frame(TcpFrame::Base);
    }

    pub(crate) fn set_tcp_frame_tool(&mut self) {
        self.set_tcp_frame(TcpFrame::Tool);
    }

    pub(crate) fn move_tcp_forward_start(&mut self) {
        self.move_tcp("move tcp forward", -UI_TCP_STEP_MM, 0.0, 0.0);
    }

    pub(crate) fn move_tcp_forward_refresh(&mut self) {
        self.move_tcp("move tcp forward", -UI_TCP_STEP_MM, 0.0, 0.0);
    }

    pub(crate) fn move_tcp_back_start(&mut self) {
        self.move_tcp("move tcp back", UI_TCP_STEP_MM, 0.0, 0.0);
    }

    pub(crate) fn move_tcp_back_refresh(&mut self) {
        self.move_tcp("move tcp back", UI_TCP_STEP_MM, 0.0, 0.0);
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
        self.arm("stop tcp jog", ArmCommand::StopAll);
    }

    pub(crate) fn arm_hold(&mut self) {
        self.arm("arm hold", ArmCommand::SetSpeed(UI_ARM_SPEED));
        self.arm("arm hold", ArmCommand::Hold);
    }

    pub(crate) fn arm_stop_all(&mut self) {
        self.arm("arm stop all", ArmCommand::StopAll);
    }

    pub(crate) fn clear_arm_faults(&mut self) {
        self.arm("clear arm faults", ArmCommand::ClearFaults { joint: None });
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
