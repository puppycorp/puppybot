use std::sync::atomic::{AtomicBool, Ordering};
use std::{
    collections::{BTreeMap, BTreeSet, HashMap, VecDeque},
    fs,
    path::{Path, PathBuf},
    sync::{Arc, Mutex},
    time::{Duration as StdDuration, Instant},
};

use embassy_time::Duration;
use pge_app::{
    Node as PgeAppNode, OrbitController, State as PgeAppState, Vec2, Vec3, WindowOverlayLines,
    WindowRenderConfig, WindowRenderTarget, run_windows_with_overlay,
};
use pge_core::{ArenaId as PgeCoreArenaId, Node as PgeCoreNode, Transform as PgeCoreTransform};
use pge_renderer::Renderer;
use pge_video::{
    Mp4EncodeRequest, RawRgbaMp4EncodeRequest, default_frame_path, default_raw_rgba_frame_path,
    encode_png_sequence_to_mp4, encode_raw_rgba_sequence_to_mp4,
};
use pge_wgpu_renderer::WgpuRenderer;
use puppybot_core::{
    config::{JointCalibration, PuppybotConfigV1},
    drive::{DriveActuator, DriveOutput},
    protocol::ProtocolEvent,
    puppyarm::{
        kinematics,
        servo_safety::TICK_WRAP,
        types::{ArmCommand, JOINT_COUNT, PuppyarmTelemetry},
    },
    robot::Puppybot,
    stservo::{SerialBus, StServo},
};
use robotdreams_core::{
    CoordinateDebugMarkerPositions, RigidTransform, RobotDreams, RobotDreamsPgeFrameOptions,
    RobotDreamsPgeTextLabel, RobotState, VirtualServoJointMapping, coordinate_debug_legend_labels,
    robotdreams_pge_frame,
};
use serde::{Deserialize, Serialize};
use sha1::{Digest, Sha1};

const SERVO_FULL_ROTATION_TICKS: f64 = TICK_WRAP as f64;
const SIMULATION_STEP_SECONDS: f32 = 0.02;
const SERVO_MAIN_BUS_ID: &str = "main_bus";
const DRIVE_BUS_ID: &str = "drive_bus";
const ROBOT_ID: &str = "puppybot";
const BALL_OBJECT_ID: &str = "ball";
const BIN_TRIGGER_ID: &str = "ball_in_bin";
const BALL_PICKUP_TOLERANCE_M: f32 = 0.035;
const WRIST_CAMERA_ID: &str = "wrist_camera";
const TCP_CAMERA_WINDOW_TITLE: &str = "PuppyBot TCP Camera";
const TCP_ALIGNMENT_TOLERANCE_MM: f64 = 2.0;
const SCREENSHOT_ARM_SPEED: i16 = 220;
pub(crate) const RECORDING_FPS: u32 = 50;
const RECORDING_SETTLE_FRAMES: u32 = 120;
const MODEL_JOINT_NAMES: [&str; 4] = ["yaw", "shoulder", "elbow", "wrist"];
const CONTROLLER_ARM_POINT_NAMES: [&str; 5] = ["yaw", "shoulder", "elbow", "wrist", "tcp"];
const CONTROLLER_ARM_SEGMENT_NAMES: [&str; 4] =
    ["yaw_shoulder", "shoulder_elbow", "elbow_wrist", "wrist_tcp"];
const CONTROLLER_ARM_POINT_RADIUS_M: f32 = 0.012;
const PUPPYBOT_CURRENT_TCP_MARKER_RADIUS_M: f32 = 0.009;
const CONTROLLER_ARM_LEGEND: &str = "CYAN CENTER = MODEL CURRENT TCP; MAGENTA CHAIN = CTRL FK (OBSERVED JOINTS; CONCENTRIC TCP POINT VISIBLE AS MAGENTA RING WHEN ALIGNED)";
pub(crate) const CAPTURE_STATE_SCHEMA: &str = "puppybot.sim.capture-state.v1";
pub(crate) const CAPTURE_TRACE_SCHEMA: &str = "puppybot.sim.capture-trace.v1";
const CAPTURE_FOV_DEG: f32 = 55.0;
const MAX_CAPTURE_WIDTH: u32 = 1920;
const MAX_CAPTURE_HEIGHT: u32 = 1080;
const MAX_CAPTURE_PIXELS: u64 = 1920 * 1080;
const MAX_CAPTURE_TRACE_FRAMES: usize = 500;
const MAX_CAPTURE_TRACE_FPS: u32 = 50;
const SIMULATION_UPS_SAMPLE_INTERVAL: StdDuration = StdDuration::from_secs(1);
const SIMULATION_UPS_STALE_INTERVAL: StdDuration = StdDuration::from_secs(2);

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct SimManipulationState {
    pub(crate) simulation_only: bool,
    pub(crate) action: String,
    pub(crate) pickup_tolerance_m: f32,
    pub(crate) ball: SimBallState,
    pub(crate) bin_trigger: SimBinTriggerState,
    pub(crate) last_action: Option<SimToolActionResult>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct SimBallState {
    pub(crate) object_id: String,
    pub(crate) center_world_m: [f32; 3],
    pub(crate) linear_velocity_mps: [f32; 3],
    pub(crate) motion: String,
    pub(crate) attached: bool,
    pub(crate) attached_to: Option<String>,
    pub(crate) tcp_distance_m: Option<f32>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct SimBinTriggerState {
    pub(crate) id: String,
    pub(crate) object_id: String,
    pub(crate) ball_detected: bool,
    pub(crate) entered: bool,
    pub(crate) entry_count: u64,
    pub(crate) entered_at_sec: Option<f64>,
    pub(crate) settled: bool,
    pub(crate) triggered: bool,
    pub(crate) triggered_at_sec: Option<f64>,
    pub(crate) settled_time_sec: f32,
    pub(crate) source: String,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct SimToolActionResult {
    pub(crate) sequence: u64,
    pub(crate) action: String,
    pub(crate) result: String,
    pub(crate) attached: bool,
    pub(crate) observed_tcp_world_m: [f32; 3],
    pub(crate) ball_center_world_m: [f32; 3],
    pub(crate) tcp_distance_m: f32,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct CaptureStateV1 {
    pub(crate) schema: String,
    pub(crate) exact_visual_replay: bool,
    pub(crate) exact_saved_transforms: bool,
    pub(crate) pose_equivalent_render: bool,
    pub(crate) exact_dynamic_continuation: bool,
    pub(crate) project: CaptureProject,
    pub(crate) camera: CaptureCamera,
    pub(crate) frames: Vec<CaptureFrame>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct CaptureProject {
    pub(crate) file_name: String,
    pub(crate) content_sha1: String,
    pub(crate) hash_scope: String,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct CaptureCamera {
    pub(crate) target_m: [f32; 3],
    pub(crate) eye_m: [f32; 3],
    pub(crate) rotation_matrix: [[f32; 3]; 3],
    pub(crate) radius_m: f32,
    pub(crate) azimuth_deg: f32,
    pub(crate) elevation_deg: f32,
    pub(crate) fov_deg: f32,
    pub(crate) projection: String,
    pub(crate) resolution: [u32; 2],
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct CaptureFrame {
    pub(crate) sequence: u64,
    pub(crate) simulation_clock_sec: f64,
    pub(crate) robots: Vec<CaptureRobot>,
    pub(crate) servos: Vec<CaptureServo>,
    pub(crate) visual_transforms: BTreeMap<String, PgeCoreTransform>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub(crate) manipulation: Option<SimManipulationState>,
    pub(crate) overlays: CaptureOverlays,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct CaptureRobot {
    pub(crate) id: String,
    pub(crate) name: String,
    pub(crate) base_position_m: [f64; 3],
    pub(crate) base_rotation_rad: Option<[f64; 3]>,
    pub(crate) joints_rad: BTreeMap<String, f64>,
    pub(crate) tcp_world_m: Option<[f64; 3]>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct CaptureServo {
    pub(crate) bus_id: String,
    pub(crate) id: u8,
    pub(crate) present_tick: Option<i32>,
    pub(crate) target_tick: Option<i32>,
    pub(crate) angle_rad: Option<f64>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct CaptureOverlays {
    pub(crate) labels: Vec<CaptureLabel>,
    pub(crate) debug_markers: Vec<CaptureDebugMarker>,
    pub(crate) controller_arm_world_m: Option<[[f32; 3]; 5]>,
    pub(crate) world_from_base: Option<CaptureRigidTransform>,
    pub(crate) base_from_arm_base: Option<CaptureRigidTransform>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct CaptureLabel {
    pub(crate) id: String,
    pub(crate) text: String,
    pub(crate) row: usize,
    pub(crate) color: [f32; 4],
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct CaptureDebugMarker {
    pub(crate) robot_id: String,
    pub(crate) floor_z: f32,
    pub(crate) current_tcp: Option<[f32; 3]>,
    pub(crate) target_tcp: Option<[f32; 3]>,
}

#[derive(Clone, Copy, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct CaptureRigidTransform {
    pub(crate) translation_m: [f64; 3],
    pub(crate) rotation_matrix: [[f64; 3]; 3],
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct CaptureTraceV1 {
    pub(crate) schema: String,
    pub(crate) exact_visual_replay: bool,
    pub(crate) exact_saved_transforms: bool,
    pub(crate) pose_equivalent_render: bool,
    pub(crate) exact_dynamic_continuation: bool,
    pub(crate) fps: u32,
    pub(crate) project: CaptureProject,
    pub(crate) frames: Vec<CaptureTraceFrame>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct CaptureTraceFrame {
    pub(crate) frame_index: u32,
    pub(crate) camera: CaptureCamera,
    pub(crate) frame: CaptureFrame,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub(crate) struct ScreenshotCamera {
    pub(crate) target: [f32; 3],
    pub(crate) radius_m: f32,
    pub(crate) azimuth_deg: f32,
    pub(crate) elevation_deg: f32,
}

impl Default for ScreenshotCamera {
    fn default() -> Self {
        Self {
            target: [0.18, 0.0, 0.12],
            radius_m: 0.42,
            azimuth_deg: -48.0,
            elevation_deg: 24.0,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum RobotDreamsSerialBusError {
    Protocol,
    Poisoned,
}

struct RobotDreamsRuntimeState {
    dreams: RobotDreams,
    sequence: u64,
    visual_bindings: Vec<PreviewVisualBinding>,
    bus_id: String,
    drive_bus_id: String,
    read_buf: VecDeque<u8>,
    labels: Vec<RobotDreamsPgeTextLabel>,
    puppybot_target_tcp_mm: Option<(f32, f32, f32)>,
    controller_arm_chain_world_m: Option<ControllerArmChain>,
    tool_action_sequence: u64,
    last_tool_action: Option<SimToolActionResult>,
}

#[derive(Clone)]
pub(crate) struct RobotDreamsSerialBus {
    state: Arc<Mutex<RobotDreamsRuntimeState>>,
}

#[derive(Clone)]
pub(crate) struct RobotDreamsDriveActuator {
    state: Arc<Mutex<RobotDreamsRuntimeState>>,
}

pub(crate) struct SimulatedRuntimeBackend {
    state: Arc<Mutex<RobotDreamsRuntimeState>>,
    published_preview: Arc<Mutex<PublishedPreview>>,
    simulation_ups: Arc<Mutex<SimulationUpsCounter>>,
    project: CaptureProject,
    project_path: PathBuf,
    window_active: Arc<AtomicBool>,
    pub(crate) servo: StServo<RobotDreamsSerialBus>,
    pub(crate) drive_actuator: RobotDreamsDriveActuator,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub(crate) struct SimulationFrameTransforms {
    pub(crate) world_from_base: RigidTransform,
    pub(crate) base_from_arm_base: RigidTransform,
}

/// A screen-space direction from the mounted RobotDreams wrist camera.
///
/// This is deliberately distinct from the core TCP frames: it is a
/// simulation-owned sensor basis, sampled at gesture start and converted to an
/// immutable arm-base vector before the arm controller sees it.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum TcpCameraJogDirection {
    Forward,
    Back,
    Left,
    Right,
    Up,
    Down,
}

#[derive(Clone, Copy, Debug, PartialEq)]
struct ModelTelemetry {
    tcp_world_m: Option<[f64; 3]>,
    joint_angles_rad: [Option<f64>; 4],
}

#[derive(Clone, Copy, Debug, PartialEq)]
struct ControllerArmChain {
    points_world_m: [[f32; 3]; 5],
}

/// Immutable data consumed by the PGE window for one rendered frame.
///
/// The simulation worker owns the mutable RobotDreams model and can spend a
/// long time in virtual-servo handling or physics stepping. Keeping the
/// renderer on this separate, already-materialized snapshot means it never
/// waits for that worker's mutex.
#[derive(Clone)]
struct PreviewSnapshot {
    labels: Vec<RobotDreamsPgeTextLabel>,
    visual_transforms: BTreeMap<String, PgeCoreTransform>,
    debug_markers: Vec<CoordinateDebugMarkerPositions>,
    frames: Option<SimulationFrameTransforms>,
    controller_arm_chain: Option<ControllerArmChain>,
    wrist_camera: Option<ProjectCameraPose>,
    capture_frame: CaptureFrame,
}

/// The RobotDreams world-space pose and native optics of the project wrist camera.
/// This is kept in the immutable simulation snapshot so the camera window never
/// takes the simulation-state mutex or drives simulation/controller state itself.
#[derive(Clone, Copy, Debug, PartialEq)]
struct ProjectCameraPose {
    transform: PreviewCameraTransform,
    fov_deg: f32,
    resolution: [u32; 2],
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
struct InteractivePreviewWindowPlan {
    open_tcp_camera: bool,
    tcp_camera_resolution: [u32; 2],
}

fn interactive_preview_window_plan(
    wrist_camera: Option<ProjectCameraPose>,
) -> InteractivePreviewWindowPlan {
    InteractivePreviewWindowPlan {
        open_tcp_camera: wrist_camera.is_some(),
        tcp_camera_resolution: wrist_camera
            .map(|camera| camera.resolution)
            .unwrap_or(RobotDreamsPgeFrameOptions::default().resolution),
    }
}

#[derive(Clone)]
struct PublishedPreview {
    snapshot: Arc<PreviewSnapshot>,
    camera: CaptureCamera,
    capture_state: Arc<CaptureStateV1>,
}

impl SimulationFrameTransforms {
    fn world_from_arm_base(self) -> RigidTransform {
        self.world_from_base.compose(self.base_from_arm_base)
    }
}

#[derive(Clone)]
pub(crate) struct SimulatedPreview {
    state: Arc<Mutex<RobotDreamsRuntimeState>>,
    published: Arc<Mutex<PublishedPreview>>,
    simulation_ups: Arc<Mutex<SimulationUpsCounter>>,
    project: CaptureProject,
    project_path: PathBuf,
    window_active: Arc<AtomicBool>,
}

#[derive(Default)]
struct SimulationUpsCounter {
    sample_started_at: Option<Instant>,
    completed_since_sample: u64,
    last_completed_at: Option<Instant>,
    displayed_ups: Option<f64>,
}

impl SimulationUpsCounter {
    fn record_completion_at(&mut self, now: Instant) {
        let reset = self.last_completed_at.is_some_and(|last| {
            now < last || now.duration_since(last) >= SIMULATION_UPS_STALE_INTERVAL
        }) || self.sample_started_at.is_some_and(|started| now < started);
        if reset || self.sample_started_at.is_none() {
            self.sample_started_at = Some(now);
            self.completed_since_sample = 0;
            self.displayed_ups = None;
            self.last_completed_at = Some(now);
            return;
        }

        self.last_completed_at = Some(now);
        self.completed_since_sample = self.completed_since_sample.saturating_add(1);
        let started = self
            .sample_started_at
            .expect("simulation UPS sample start initialized above");
        let elapsed = now.duration_since(started);
        if elapsed >= SIMULATION_UPS_SAMPLE_INTERVAL {
            self.displayed_ups = Some(self.completed_since_sample as f64 / elapsed.as_secs_f64());
            self.sample_started_at = Some(now);
            self.completed_since_sample = 0;
        }
    }

    fn displayed_at(&self, now: Instant) -> Option<f64> {
        let last_completed = self.last_completed_at?;
        if now < last_completed {
            return None;
        }
        if now.duration_since(last_completed) >= SIMULATION_UPS_STALE_INTERVAL {
            return Some(0.0);
        }
        self.displayed_ups
    }
}

impl SimulatedRuntimeBackend {
    pub(crate) fn new(
        project_path: impl AsRef<Path>,
        config: &PuppybotConfigV1,
    ) -> Result<Self, String> {
        let project_path = project_path.as_ref();
        let project_bytes = fs::read(project_path)
            .map_err(|err| format!("read RobotDreams project {}: {err}", project_path.display()))?;
        let project = CaptureProject {
            file_name: project_path
                .file_name()
                .and_then(|value| value.to_str())
                .unwrap_or("project.json")
                .to_string(),
            content_sha1: sha1_hex(&project_bytes),
            hash_scope: "projectJsonPoseEquivalent".to_string(),
        };
        let mut dreams = RobotDreams::open(project_path)
            .map_err(|err| format!("open RobotDreams project {}: {err}", project_path.display()))?;
        let mappings = puppybot_runtime::sim_calibration::derive_simulation_joint_mappings(
            project_path,
            config,
        )
        .map_err(|err| format!("derive RobotDreams session servo mapping: {err}"))?;
        dreams
            .install_virtual_servo_joint_mappings(mappings.into_iter().map(|mapping| {
                VirtualServoJointMapping {
                    bus_id: mapping.bus_id,
                    servo_id: mapping.servo_id,
                    reference_tick: mapping.reference_tick,
                    alignment_reference_tick: mapping.alignment_reference_tick,
                    joint_position_at_reference_rad: mapping.joint_position_at_reference_rad,
                    radians_per_tick: mapping.radians_per_tick,
                    ticks_per_turn: mapping.ticks_per_turn,
                    wrapped: mapping.wrapped,
                }
            }))
            .map_err(|err| format!("install RobotDreams session servo mapping: {err}"))?;
        for joint in config.arm.joints {
            let tick = tick_for_joint_angle(joint, joint.reference_angle_rad);
            if !dreams.set_virtual_servo_target(SERVO_MAIN_BUS_ID, joint.servo_id, tick as i16) {
                log::warn!(
                    "RobotDreams virtual servo {} was not initialized from PuppyBot config",
                    joint.servo_id
                );
            }
        }
        // The controller uses wheel mode for arm holding, so settle the
        // session-mapped reference targets before its first zero-speed hold.
        dreams.advance_seconds(4.0);

        let visual_bindings = dreams
            .model()
            .map(|model| preview_visual_bindings(&model.robot_visual_meshes()))
            .unwrap_or_default();
        let state = Arc::new(Mutex::new(RobotDreamsRuntimeState {
            dreams,
            sequence: 0,
            visual_bindings,
            bus_id: SERVO_MAIN_BUS_ID.to_string(),
            drive_bus_id: DRIVE_BUS_ID.to_string(),
            read_buf: VecDeque::new(),
            labels: Vec::new(),
            puppybot_target_tcp_mm: None,
            controller_arm_chain_world_m: None,
            tool_action_sequence: 0,
            last_tool_action: None,
        }));
        let published_preview = {
            let state_guard = state
                .lock()
                .map_err(|_| "RobotDreams simulation state lock poisoned at startup")?;
            let snapshot = Arc::new(preview_snapshot_from_state(&state_guard, None));
            let camera = capture_camera_from_screenshot(ScreenshotCamera::default());
            Arc::new(Mutex::new(PublishedPreview {
                capture_state: published_capture_state(&project, &camera, &snapshot),
                snapshot,
                camera,
            }))
        };
        let bus = RobotDreamsSerialBus {
            state: Arc::clone(&state),
        };
        let drive_actuator = RobotDreamsDriveActuator {
            state: Arc::clone(&state),
        };

        Ok(Self {
            state,
            published_preview,
            simulation_ups: Arc::new(Mutex::new(SimulationUpsCounter::default())),
            project,
            project_path: project_path.to_path_buf(),
            window_active: Arc::new(AtomicBool::new(false)),
            servo: StServo::new(bus).with_timeout(Duration::from_millis(200)),
            drive_actuator,
        })
    }

    pub(crate) fn default_project_path() -> PathBuf {
        Path::new(env!("CARGO_MANIFEST_DIR")).join("../../robotdreams/project.json")
    }

    pub(crate) async fn run_once(&mut self, robot: &mut Puppybot, now_ms: u64) {
        robot
            .run_once_with_drive(&mut self.servo, &mut self.drive_actuator, now_ms, || None)
            .await;
        match self.state.lock() {
            Ok(mut state) => {
                state.dreams.advance_seconds(SIMULATION_STEP_SECONDS);
                state.sequence = state.sequence.wrapping_add(1);
            }
            Err(_) => log::warn!("RobotDreams simulation state lock poisoned while advancing"),
        }
        if self.update_labels(robot) {
            if let Ok(mut simulation_ups) = self.simulation_ups.lock() {
                simulation_ups.record_completion_at(Instant::now());
            }
        }
    }

    pub(crate) fn preview(&self) -> SimulatedPreview {
        SimulatedPreview {
            state: Arc::clone(&self.state),
            published: Arc::clone(&self.published_preview),
            simulation_ups: Arc::clone(&self.simulation_ups),
            project: self.project.clone(),
            project_path: self.project_path.clone(),
            window_active: Arc::clone(&self.window_active),
        }
    }

    pub(crate) fn debug_markers(&self, robot: &Puppybot) -> Vec<CoordinateDebugMarkerPositions> {
        let arm = robot.arm_telemetry();
        match self.state.lock() {
            Ok(state) => {
                let mut debug_markers = state.dreams.coordinate_debug_marker_positions(
                    robotdreams_core::CoordinateDebugOverlayOptions::default(),
                );
                let frames = simulation_frame_transforms(&state.dreams);
                override_debug_markers_with_puppybot_tcp(
                    &mut debug_markers,
                    arm.target_coords_mm,
                    frames,
                );
                debug_markers
            }
            Err(_) => {
                log::warn!(
                    "RobotDreams simulation state lock poisoned while reading debug markers"
                );
                Vec::new()
            }
        }
    }

    pub(crate) fn frame_transforms(&self) -> Option<SimulationFrameTransforms> {
        self.state
            .lock()
            .ok()
            .and_then(|state| simulation_frame_transforms(&state.dreams))
    }

    pub(crate) fn manipulation_state(&self) -> Result<SimManipulationState, String> {
        let state = self
            .state
            .lock()
            .map_err(|_| "RobotDreams simulation state lock poisoned")?;
        manipulation_state_from_dreams(&state.dreams, state.last_tool_action.clone())
    }

    pub(crate) fn tool_action(&mut self) -> Result<SimToolActionResult, String> {
        let mut state = self
            .state
            .lock()
            .map_err(|_| "RobotDreams simulation state lock poisoned")?;
        let tcp = observed_tcp_world_m(&state.dreams)?;
        let ball = state
            .dreams
            .scene_object_state(BALL_OBJECT_ID)
            .ok_or_else(|| "RobotDreams ball object is unavailable".to_string())?;
        let ball_center = ball.position;
        let distance = distance_f32(tcp, ball_center);
        let attached = ball.attachment.is_some();
        let result = if attached {
            state
                .dreams
                .detach_scene_object(BALL_OBJECT_ID)
                .map_err(|err| format!("release ball: {err}"))?;
            "released"
        } else {
            let attached = state
                .dreams
                .try_attach_scene_object_to_tcp(
                    BALL_OBJECT_ID,
                    ROBOT_ID,
                    BALL_PICKUP_TOLERANCE_M,
                    [0.0, 0.0, 0.0],
                )
                .map_err(|err| format!("attach ball: {err}"))?;
            if !attached {
                return Err(format!(
                    "Interact rejected: observed TCP is {distance:.4} m from ball; pickup tolerance is {BALL_PICKUP_TOLERANCE_M:.4} m"
                ));
            }
            "attached"
        };
        state.tool_action_sequence = state.tool_action_sequence.wrapping_add(1);
        let ball = state
            .dreams
            .scene_object_state(BALL_OBJECT_ID)
            .ok_or_else(|| "RobotDreams ball object disappeared after Interact".to_string())?;
        let action = SimToolActionResult {
            sequence: state.tool_action_sequence,
            action: "Interact".to_string(),
            result: result.to_string(),
            attached: ball.attachment.is_some(),
            observed_tcp_world_m: tcp,
            ball_center_world_m: ball.position,
            tcp_distance_m: distance,
        };
        state.last_tool_action = Some(action.clone());
        Ok(action)
    }

    /// Samples the live wrist-camera pose and arm-base frame under one state
    /// lock, returning a normalized direction in the controller's arm-base
    /// coordinate system.  A caller must latch this vector for the life of a
    /// held gesture; continuously re-sampling would create visual servoing and
    /// lets a moving target rotate away faster than the arm can follow.
    pub(crate) fn wrist_camera_jog_direction(
        &self,
        direction: TcpCameraJogDirection,
    ) -> Result<[f64; 3], String> {
        let state = self
            .state
            .lock()
            .map_err(|_| "wrist-camera pose unavailable: simulation state lock poisoned")?;
        wrist_camera_jog_direction(&state.dreams, direction)
    }

    fn update_labels(&self, robot: &Puppybot) -> bool {
        let arm = robot.arm_telemetry();
        let drive = robot.drive_output();

        let snapshot = match self.state.lock() {
            Ok(mut state) => {
                let model_telemetry = state
                    .dreams
                    .robot_state(ROBOT_ID)
                    .as_ref()
                    .map(model_telemetry);
                let controller_arm_chain = simulation_frame_transforms(&state.dreams)
                    .and_then(|frames| controller_arm_chain_world_m(&arm, frames));
                let mut labels = Vec::new();
                push_overlay_label(&mut labels, "title", "PUPPYBOT SIM");
                push_overlay_label(
                    &mut labels,
                    "drive",
                    format!(
                        "CTRL DRIVE L {} R {} STEER {} ACTIVE {}",
                        drive.left_speed, drive.right_speed, drive.steering_angle_deg, drive.active
                    ),
                );
                push_model_telemetry_labels(&mut labels, model_telemetry.as_ref());
                push_controller_tcp_alignment_label(
                    &mut labels,
                    controller_arm_chain.as_ref(),
                    model_telemetry.as_ref(),
                );
                if let Some((x, y, z)) = arm.coords_mm {
                    push_overlay_label(
                        &mut labels,
                        "tcp_current",
                        format!("CTRL CUR TCP ARM MM X {x:.1} Y {y:.1} Z {z:.1}"),
                    );
                }
                if let Some((x, y, z)) = arm.target_coords_mm {
                    push_overlay_label(
                        &mut labels,
                        "tcp_target",
                        format!("CTRL TGT TCP ARM MM X {x:.1} Y {y:.1} Z {z:.1}"),
                    );
                }
                for (index, joint) in arm.joints.iter().enumerate() {
                    push_overlay_label(
                        &mut labels,
                        format!("joint_{index}"),
                        format!(
                            "CTRL {} ID {} TICK {} TGT {} ANG DEG {}",
                            MODEL_JOINT_NAMES[index].to_ascii_uppercase(),
                            joint.servo_id,
                            option_i32(joint.tick),
                            option_i32(joint.target_tick),
                            joint
                                .angle_deg()
                                .map(|angle| format!("{angle:.1}"))
                                .unwrap_or_else(|| "NA".to_string()),
                        ),
                    );
                }
                state.labels = labels;
                state.puppybot_target_tcp_mm = arm.target_coords_mm;
                state.controller_arm_chain_world_m = controller_arm_chain;
                Some(preview_snapshot_from_state(&state, Some(&arm)))
            }
            Err(_) => {
                log::warn!("RobotDreams simulation state lock poisoned while updating labels");
                None
            }
        };
        let Some(snapshot) = snapshot else {
            return false;
        };
        match self.published_preview.lock() {
            Ok(mut published) => {
                let snapshot = Arc::new(snapshot);
                if !self.window_active.load(Ordering::Acquire) {
                    let camera = published.camera.clone();
                    published.capture_state =
                        published_capture_state(&self.project, &camera, &snapshot);
                }
                published.snapshot = snapshot;
                true
            }
            Err(_) => {
                log::warn!("simulation preview snapshot lock poisoned while publishing");
                false
            }
        }
    }
}

fn manipulation_state_from_dreams(
    dreams: &RobotDreams,
    last_action: Option<SimToolActionResult>,
) -> Result<SimManipulationState, String> {
    let tcp = observed_tcp_world_m(dreams).ok();
    let ball = dreams
        .scene_object_state(BALL_OBJECT_ID)
        .ok_or_else(|| "RobotDreams ball object is unavailable".to_string())?;
    let attached_to = ball
        .attachment
        .as_ref()
        .map(|attachment| format!("{}:{}", attachment.robot_id, attachment.frame_name));
    let attached = attached_to.is_some();
    let motion = match (attached, ball.dynamic) {
        (true, _) => "attached",
        (false, true) => "dynamic",
        (false, false) => "static",
    };
    let trigger = dreams
        .scene_trigger_state(BIN_TRIGGER_ID)
        .ok_or_else(|| "RobotDreams bin trigger is unavailable".to_string())?;
    Ok(SimManipulationState {
        simulation_only: true,
        action: "Interact".to_string(),
        pickup_tolerance_m: BALL_PICKUP_TOLERANCE_M,
        ball: SimBallState {
            object_id: ball.id.clone(),
            center_world_m: ball.position,
            linear_velocity_mps: ball.velocity_mps,
            motion: motion.to_string(),
            attached,
            attached_to,
            tcp_distance_m: tcp.map(|tcp| distance_f32(tcp, ball.position)),
        },
        bin_trigger: SimBinTriggerState {
            id: trigger.id.clone(),
            object_id: trigger.object_id.clone(),
            ball_detected: trigger.inside,
            entered: trigger.entered,
            entry_count: trigger.entry_count,
            entered_at_sec: trigger.entered_at_sec,
            settled: trigger.settled,
            triggered: trigger.triggered,
            triggered_at_sec: trigger.triggered_at_sec,
            settled_time_sec: trigger.settled_time_sec,
            source: "RobotDreams physics trigger".to_string(),
        },
        last_action,
    })
}

fn observed_tcp_world_m(dreams: &RobotDreams) -> Result<[f32; 3], String> {
    dreams
        .robot_state(ROBOT_ID)
        .and_then(|robot| robot.tcp)
        .and_then(|tcp| tcp.location)
        .map(|location| location.position.map(|value| value as f32))
        .ok_or_else(|| "RobotDreams observed PuppyBot TCP is unavailable".to_string())
}

fn distance_f32(left: [f32; 3], right: [f32; 3]) -> f32 {
    left.into_iter()
        .zip(right)
        .map(|(left, right)| (left - right).powi(2))
        .sum::<f32>()
        .sqrt()
}

pub(crate) async fn capture_simulation_screenshot(
    project_path: &Path,
    config: &PuppybotConfigV1,
    path: &Path,
    frames: u64,
    camera: ScreenshotCamera,
) -> Result<f64, String> {
    let mut robot = Puppybot::new_with_config(config, 0)
        .map_err(|err| format!("invalid runtime config: {err}"))?;
    robot.handle_event(
        ProtocolEvent::Arm(ArmCommand::SetSpeed(SCREENSHOT_ARM_SPEED)),
        0,
    );
    let mut backend = SimulatedRuntimeBackend::new(project_path, config)?;
    for frame in 1..=frames {
        backend.run_once(&mut robot, frame.saturating_mul(20)).await;
    }
    backend.preview().save_screenshot(path, camera)
}

pub(crate) async fn record_simulation_video(
    project_path: &Path,
    config: &PuppybotConfigV1,
    path: &Path,
    frames: u32,
) -> Result<f64, String> {
    if frames == 0 {
        return Err("recording frame count must be positive".to_string());
    }
    if path.extension().and_then(|value| value.to_str()) != Some("mp4") {
        return Err("recording output must use the .mp4 extension".to_string());
    }
    if let Some(parent) = path.parent()
        && !parent.as_os_str().is_empty()
    {
        fs::create_dir_all(parent).map_err(|err| {
            format!(
                "create simulation recording directory {}: {err}",
                parent.display()
            )
        })?;
    }

    let frame_dir =
        std::env::temp_dir().join(format!("puppybot-runtime-record-{}", std::process::id()));
    fs::create_dir(&frame_dir).map_err(|err| {
        format!(
            "create temporary simulation frame directory {}: {err}",
            frame_dir.display()
        )
    })?;

    let result = async {
        let mut robot = Puppybot::new_with_config(config, 0)
            .map_err(|err| format!("invalid runtime config: {err}"))?;
        robot.handle_event(
            ProtocolEvent::Arm(ArmCommand::SetSpeed(SCREENSHOT_ARM_SPEED)),
            0,
        );
        let mut backend = SimulatedRuntimeBackend::new(project_path, config)?;
        for tick in 1..=RECORDING_SETTLE_FRAMES {
            backend
                .run_once(&mut robot, u64::from(tick).saturating_mul(20))
                .await;
        }
        let mut renderer = WgpuRenderer::new()
            .map_err(|err| format!("create offscreen PGE WGPU renderer: {err}"))?;
        let mut last_delta_mm = None;

        for index in 0..frames {
            let tick = RECORDING_SETTLE_FRAMES.saturating_add(index + 1);
            backend
                .run_once(&mut robot, u64::from(tick).saturating_mul(20))
                .await;
            let (frame, delta_mm) = backend
                .preview()
                .offscreen_frame(ScreenshotCamera::default())?;
            let rgba = renderer
                .render_rgba(&frame.world, &frame.request)
                .map_err(|err| format!("render simulation recording frame {index}: {err}"))?;
            let frame_path = default_raw_rgba_frame_path(&frame_dir, index);
            fs::write(&frame_path, rgba.bytes).map_err(|err| {
                format!(
                    "write simulation recording frame {}: {err}",
                    frame_path.display()
                )
            })?;
            last_delta_mm = Some(delta_mm);
        }

        let resolution = RobotDreamsPgeFrameOptions::default().resolution;
        encode_raw_rgba_sequence_to_mp4(&RawRgbaMp4EncodeRequest::raw_rgba_sequence(
            &frame_dir,
            frames,
            resolution[0],
            resolution[1],
            RECORDING_FPS,
            path,
        ))
        .map_err(|err| format!("encode PuppyBot simulation MP4: {err}"))?;
        last_delta_mm.ok_or_else(|| "simulation recording produced no frames".to_string())
    }
    .await;

    if std::env::var_os("PUPPYBOT_KEEP_TRACE_FRAMES").is_some() {
        log::info!("kept trace frame directory {}", frame_dir.display());
    } else if let Err(err) = fs::remove_dir_all(&frame_dir) {
        log::warn!(
            "failed to remove temporary simulation frame directory {}: {err}",
            frame_dir.display()
        );
    }
    result
}

pub(crate) fn parse_capture_state_json(bytes: &[u8]) -> Result<CaptureStateV1, String> {
    let value: serde_json::Value =
        serde_json::from_slice(bytes).map_err(|err| format!("decode capture state json: {err}"))?;
    let candidate =
        if value.get("schema").and_then(|value| value.as_str()) == Some(CAPTURE_STATE_SCHEMA) {
            &value
        } else if let Some(value) = value.pointer("/sim/captureState") {
            value
        } else if let Some(value) = value.pointer("/state/sim/captureState") {
            value
        } else if let Some(value) = value.get("captureState") {
            value
        } else {
            return Err(format!(
                "json does not contain a {CAPTURE_STATE_SCHEMA} capture state"
            ));
        };
    let state: CaptureStateV1 = serde_json::from_value(candidate.clone())
        .map_err(|err| format!("decode {CAPTURE_STATE_SCHEMA}: {err}"))?;
    if state.schema != CAPTURE_STATE_SCHEMA {
        return Err(format!(
            "unsupported capture state schema '{}'; expected {CAPTURE_STATE_SCHEMA}",
            state.schema
        ));
    }
    if state.frames.is_empty() {
        return Err("capture state contains no frames".to_string());
    }
    validate_capture_state(&state)?;
    Ok(state)
}

pub(crate) fn capture_trace_from_states(
    states: &[Arc<CaptureStateV1>],
    fps: u32,
) -> Result<CaptureTraceV1, String> {
    let first = states
        .first()
        .ok_or_else(|| "capture trace contains no frames".to_string())?;
    let frames = states
        .iter()
        .enumerate()
        .map(|(index, state)| {
            let frame = state
                .frames
                .first()
                .cloned()
                .ok_or_else(|| format!("capture sample {index} contains no frame"))?;
            if state.project != first.project {
                return Err(format!("capture sample {index} project identity changed"));
            }
            Ok(CaptureTraceFrame {
                frame_index: index as u32,
                camera: state.camera.clone(),
                frame,
            })
        })
        .collect::<Result<Vec<_>, String>>()?;
    let trace = CaptureTraceV1 {
        schema: CAPTURE_TRACE_SCHEMA.to_string(),
        exact_visual_replay: false,
        exact_saved_transforms: true,
        pose_equivalent_render: true,
        exact_dynamic_continuation: false,
        fps,
        project: first.project.clone(),
        frames,
    };
    validate_capture_trace(&trace)?;
    Ok(trace)
}

pub(crate) fn parse_capture_trace_json(bytes: &[u8]) -> Result<CaptureTraceV1, String> {
    let trace: CaptureTraceV1 =
        serde_json::from_slice(bytes).map_err(|err| format!("decode capture trace json: {err}"))?;
    if trace.schema != CAPTURE_TRACE_SCHEMA {
        return Err(format!(
            "unsupported capture trace schema '{}'; expected {CAPTURE_TRACE_SCHEMA}",
            trace.schema
        ));
    }
    if trace.frames.is_empty() {
        return Err("capture trace contains no frames".to_string());
    }
    validate_capture_trace(&trace)?;
    Ok(trace)
}

pub(crate) fn render_capture_trace_mp4(
    project_path: &Path,
    trace: &CaptureTraceV1,
    output: &Path,
) -> Result<(), String> {
    validate_capture_trace(trace)?;
    validate_capture_project(project_path, &trace.project)?;
    let unique = format!(
        "puppybot-capture-trace-{}-{}",
        std::process::id(),
        std::thread::current().name().unwrap_or("worker")
    );
    let frame_dir = std::env::temp_dir().join(unique);
    if frame_dir.exists() {
        fs::remove_dir_all(&frame_dir)
            .map_err(|err| format!("clean temporary trace directory: {err}"))?;
    }
    fs::create_dir(&frame_dir).map_err(|err| format!("create temporary trace directory: {err}"))?;
    let result = (|| {
        let first = trace.frames.first().expect("trace checked nonempty");
        let first_state = CaptureStateV1 {
            schema: CAPTURE_STATE_SCHEMA.to_string(),
            exact_visual_replay: trace.exact_visual_replay,
            exact_saved_transforms: trace.exact_saved_transforms,
            pose_equivalent_render: trace.pose_equivalent_render,
            exact_dynamic_continuation: trace.exact_dynamic_continuation,
            project: trace.project.clone(),
            camera: first.camera.clone(),
            frames: vec![first.frame.clone()],
        };
        let mut renderer = PreparedCaptureRenderer::new(project_path, &first_state)?;
        for sample in &trace.frames {
            let state = CaptureStateV1 {
                schema: CAPTURE_STATE_SCHEMA.to_string(),
                exact_visual_replay: trace.exact_visual_replay,
                exact_saved_transforms: trace.exact_saved_transforms,
                pose_equivalent_render: trace.pose_equivalent_render,
                exact_dynamic_continuation: trace.exact_dynamic_continuation,
                project: trace.project.clone(),
                camera: sample.camera.clone(),
                frames: vec![sample.frame.clone()],
            };
            let png = renderer.render_png(&state, 0)?;
            fs::write(default_frame_path(&frame_dir, sample.frame_index), png).map_err(|err| {
                format!("write capture trace frame {}: {err}", sample.frame_index)
            })?;
        }
        encode_png_sequence_to_mp4(&Mp4EncodeRequest::png_sequence(
            &frame_dir,
            trace.frames.len() as u32,
            trace.fps,
            output,
        ))
        .map_err(|err| format!("encode capture trace MP4: {err}"))
    })();
    if std::env::var_os("PUPPYBOT_KEEP_TRACE_FRAMES").is_some() {
        log::info!("kept trace frame directory {}", frame_dir.display());
    } else if let Err(err) = fs::remove_dir_all(&frame_dir) {
        log::warn!(
            "failed to remove trace frame directory {}: {err}",
            frame_dir.display()
        );
    }
    result
}

fn validate_capture_trace(trace: &CaptureTraceV1) -> Result<(), String> {
    if !(1..=MAX_CAPTURE_TRACE_FPS).contains(&trace.fps) {
        return Err(format!(
            "capture trace fps must be between 1 and {MAX_CAPTURE_TRACE_FPS}"
        ));
    }
    let first = trace
        .frames
        .first()
        .ok_or_else(|| "capture trace contains no frames".to_string())?;
    if trace.frames.len() > MAX_CAPTURE_TRACE_FRAMES {
        return Err(format!(
            "capture trace has {} frames; limit is {MAX_CAPTURE_TRACE_FRAMES}",
            trace.frames.len()
        ));
    }
    for (index, sample) in trace.frames.iter().enumerate() {
        validate_capture_camera(&sample.camera)?;
        if sample.frame_index != index as u32 {
            return Err(format!(
                "capture trace frameIndex {} is not sequential; expected {index}",
                sample.frame_index
            ));
        }
        if sample.camera.resolution != first.camera.resolution {
            return Err(format!(
                "capture trace frame {index} resolution {:?} differs from fixed recording resolution {:?}",
                sample.camera.resolution, first.camera.resolution
            ));
        }
    }
    Ok(())
}

fn validate_capture_state(state: &CaptureStateV1) -> Result<(), String> {
    validate_capture_camera(&state.camera)?;
    if state.frames.is_empty() || state.frames.len() > MAX_CAPTURE_TRACE_FRAMES {
        return Err(format!(
            "capture state frame count must be between 1 and {MAX_CAPTURE_TRACE_FRAMES}"
        ));
    }
    Ok(())
}

fn validate_capture_camera(camera: &CaptureCamera) -> Result<(), String> {
    if camera.projection != "perspective" {
        return Err(format!(
            "unsupported capture camera projection '{}'; only perspective is supported",
            camera.projection
        ));
    }
    let [width, height] = camera.resolution;
    let pixels = u64::from(width)
        .checked_mul(u64::from(height))
        .ok_or_else(|| "capture camera resolution overflows pixel count".to_string())?;
    if width == 0
        || height == 0
        || width > MAX_CAPTURE_WIDTH
        || height > MAX_CAPTURE_HEIGHT
        || pixels > MAX_CAPTURE_PIXELS
    {
        return Err(format!(
            "capture camera resolution {width}x{height} exceeds supported 1..={MAX_CAPTURE_WIDTH} by 1..={MAX_CAPTURE_HEIGHT} and {MAX_CAPTURE_PIXELS} pixels"
        ));
    }
    let mut values = Vec::with_capacity(24);
    values.extend(camera.target_m);
    values.extend(camera.eye_m);
    values.extend(camera.rotation_matrix.into_iter().flatten());
    values.extend([
        camera.radius_m,
        camera.azimuth_deg,
        camera.elevation_deg,
        camera.fov_deg,
    ]);
    if values.iter().any(|value| !value.is_finite()) {
        return Err("capture camera values must be finite".to_string());
    }
    if camera.radius_m <= 0.0 || camera.fov_deg <= 0.0 || camera.fov_deg >= 180.0 {
        return Err("capture camera radius and FOV are out of range".to_string());
    }
    Ok(())
}

struct PreparedCaptureRenderer {
    frame: robotdreams_core::RobotDreamsPgeFrame,
    base_world: pge_core::WorldState,
    index: HashMap<String, PgeCoreArenaId<PgeCoreNode>>,
    renderer: WgpuRenderer,
    expected_visual_keys: BTreeSet<String>,
}

const MAX_STABLE_CAPTURE_RENDER_ATTEMPTS: usize = 3;

fn render_stable_capture_png<F>(mut render: F) -> Result<Vec<u8>, String>
where
    F: FnMut() -> Result<Vec<u8>, String>,
{
    let mut previous = render()?;
    for _ in 1..MAX_STABLE_CAPTURE_RENDER_ATTEMPTS {
        let current = render()?;
        if current == previous {
            return Ok(current);
        }
        previous = current;
    }
    Err(format!(
        "offscreen capture did not stabilize after {MAX_STABLE_CAPTURE_RENDER_ATTEMPTS} identical-state renders"
    ))
}

impl PreparedCaptureRenderer {
    fn new(project_path: &Path, state: &CaptureStateV1) -> Result<Self, String> {
        validate_capture_state(state)?;
        validate_capture_project(project_path, &state.project)?;
        let dreams = RobotDreams::open(project_path)
            .map_err(|err| format!("open RobotDreams project {}: {err}", project_path.display()))?;
        let mut options = RobotDreamsPgeFrameOptions::default();
        options.resolution = state.camera.resolution;
        let mut frame = robotdreams_pge_frame(&dreams, options);
        let expected_visual_keys = expected_visual_transform_keys(&dreams);
        insert_controller_arm_overlay(&mut frame.world);
        let index = index_world_nodes(&frame.world);
        hide_capture_dynamic_entities(&mut frame.world, &index);
        let base_world = frame.world.clone();
        let renderer = WgpuRenderer::new()
            .map_err(|err| format!("create offscreen PGE WGPU renderer: {err}"))?;
        Ok(Self {
            frame,
            base_world,
            index,
            renderer,
            expected_visual_keys,
        })
    }

    fn render_png(
        &mut self,
        state: &CaptureStateV1,
        frame_index: usize,
    ) -> Result<Vec<u8>, String> {
        let capture_frame = state.frames.get(frame_index).ok_or_else(|| {
            format!(
                "capture frame index {frame_index} is out of range for {} frames",
                state.frames.len()
            )
        })?;
        self.frame.world = self.base_world.clone();
        validate_visual_transform_keys(capture_frame, &self.expected_visual_keys)?;
        for (entity, transform) in &capture_frame.visual_transforms {
            set_world_node_transform(&mut self.frame.world, &self.index, entity, *transform);
        }
        // Prepared capture reuses one WGPU mesh cache across the trace. Keep
        // its procedural geometry immutable: changing the debug delta/arm
        // cylinder dimensions after cache preparation can evict mesh entries
        // that draws later in the same frame still reference, producing
        // incomplete tiles. The authoritative robot and scene-object visuals
        // still follow their per-frame transforms; these optional diagnostic
        // overlays remain hidden from `base_world`.
        if let (Some(world_from_base), Some(base_from_arm_base)) = (
            capture_frame.overlays.world_from_base,
            capture_frame.overlays.base_from_arm_base,
        ) {
            sync_debug_frame_roots(
                &mut self.frame.world,
                SimulationFrameTransforms {
                    world_from_base: rigid_transform_from_capture(world_from_base),
                    base_from_arm_base: rigid_transform_from_capture(base_from_arm_base),
                },
                &self.index,
            );
        }
        let mut labels = capture_frame
            .overlays
            .labels
            .iter()
            .map(|label| {
                RobotDreamsPgeTextLabel::overlay_with_color(
                    label.id.clone(),
                    label.text.clone(),
                    label.row,
                    label.color,
                )
            })
            .collect::<Vec<_>>();
        let legend_row_start = labels.len();
        labels.extend(coordinate_debug_legend_labels(legend_row_start));
        labels.push(RobotDreamsPgeTextLabel::overlay_with_color(
            "controller_arm_legend",
            CONTROLLER_ARM_LEGEND,
            labels.len(),
            [1.0, 0.2, 0.9, 1.0],
        ));
        self.frame.world.text_labels = labels.into_iter().map(pge_text_label).collect();
        set_world_camera_transform(
            &mut self.frame.world,
            &self.index,
            &self.frame.camera_entity.0,
            PreviewCameraTransform {
                translation: state.camera.eye_m,
                rotation_matrix: state.camera.rotation_matrix,
            },
        );
        if let Some(camera_node) = self
            .index
            .get(&self.frame.camera_entity.0)
            .and_then(|node_id| self.frame.world.nodes.get(node_id))
            && let Some(camera_id) = camera_node.camera
            && let Some(camera) = self.frame.world.cameras.get_mut(&camera_id)
        {
            camera.fov_deg = state.camera.fov_deg;
            camera.resolution = state.camera.resolution;
        }
        // Do not carry a render target/readback buffer across capture frames.
        // The NVIDIA Vulkan path can return deterministic but incomplete
        // regions after repeated map/unmap reuse, even though each individual
        // render call waits for submission. A fresh offscreen renderer makes
        // the frame's GPU cache, render target, and MAP_READ buffer private to
        // this immutable capture state.
        self.renderer = WgpuRenderer::new()
            .map_err(|err| format!("reset offscreen PGE WGPU renderer: {err}"))?;
        render_stable_capture_png(|| {
            let output = self
                .renderer
                .render(&self.frame.world, &self.frame.request)
                .map_err(|err| format!("render capture state frame {frame_index}: {err}"))?;
            output
                .frames
                .into_iter()
                .next()
                .map(|frame| frame.bytes)
                .ok_or_else(|| "offscreen PGE renderer returned no PNG frame".to_string())
        })
    }
}

pub(crate) fn render_capture_state_png(
    project_path: &Path,
    state: &CaptureStateV1,
    frame_index: usize,
) -> Result<Vec<u8>, String> {
    validate_capture_state(state)?;
    let mut renderer =
        WgpuRenderer::new().map_err(|err| format!("create offscreen PGE WGPU renderer: {err}"))?;
    render_capture_state_png_with_renderer(project_path, state, frame_index, &mut renderer)
}

fn render_capture_state_png_with_renderer(
    project_path: &Path,
    state: &CaptureStateV1,
    frame_index: usize,
    renderer: &mut WgpuRenderer,
) -> Result<Vec<u8>, String> {
    validate_capture_state(state)?;
    let capture_frame = state.frames.get(frame_index).ok_or_else(|| {
        format!(
            "capture frame index {frame_index} is out of range for {} frames",
            state.frames.len()
        )
    })?;
    validate_capture_project(project_path, &state.project)?;
    let dreams = RobotDreams::open(project_path)
        .map_err(|err| format!("open RobotDreams project {}: {err}", project_path.display()))?;
    let expected_visual_keys = expected_visual_transform_keys(&dreams);
    validate_visual_transform_keys(capture_frame, &expected_visual_keys)?;
    let labels = capture_frame
        .overlays
        .labels
        .iter()
        .map(|label| {
            RobotDreamsPgeTextLabel::overlay_with_color(
                label.id.clone(),
                label.text.clone(),
                label.row,
                label.color,
            )
        })
        .collect::<Vec<_>>();
    let mut options = RobotDreamsPgeFrameOptions::default();
    options.resolution = state.camera.resolution;
    options.text_labels = labels.clone();
    let mut pge_frame = robotdreams_pge_frame(&dreams, options);
    insert_controller_arm_overlay(&mut pge_frame.world);
    let index = index_world_nodes(&pge_frame.world);
    hide_capture_dynamic_entities(&mut pge_frame.world, &index);
    for (entity, transform) in &capture_frame.visual_transforms {
        set_world_node_transform(&mut pge_frame.world, &index, entity, *transform);
    }
    let debug_markers = capture_frame
        .overlays
        .debug_markers
        .iter()
        .map(|marker| CoordinateDebugMarkerPositions {
            robot_id: marker.robot_id.clone(),
            floor_z: marker.floor_z,
            current_tcp: marker.current_tcp,
            target_tcp: marker.target_tcp,
        })
        .collect::<Vec<_>>();
    sync_tcp_debug_markers(&mut pge_frame.world, &debug_markers, &index);
    let controller_arm_chain = capture_frame
        .overlays
        .controller_arm_world_m
        .map(|points_world_m| ControllerArmChain { points_world_m });
    sync_controller_arm_overlay(&mut pge_frame.world, controller_arm_chain.as_ref(), &index);
    if let (Some(world_from_base), Some(base_from_arm_base)) = (
        capture_frame.overlays.world_from_base,
        capture_frame.overlays.base_from_arm_base,
    ) {
        sync_debug_frame_roots(
            &mut pge_frame.world,
            SimulationFrameTransforms {
                world_from_base: rigid_transform_from_capture(world_from_base),
                base_from_arm_base: rigid_transform_from_capture(base_from_arm_base),
            },
            &index,
        );
    }
    let mut all_labels = labels;
    let legend_row_start = all_labels.len();
    all_labels.extend(coordinate_debug_legend_labels(legend_row_start));
    all_labels.push(RobotDreamsPgeTextLabel::overlay_with_color(
        "controller_arm_legend",
        CONTROLLER_ARM_LEGEND,
        all_labels.len(),
        [1.0, 0.2, 0.9, 1.0],
    ));
    pge_frame.world.text_labels = all_labels.into_iter().map(pge_text_label).collect();
    set_world_camera_transform(
        &mut pge_frame.world,
        &index,
        &pge_frame.camera_entity.0,
        PreviewCameraTransform {
            translation: state.camera.eye_m,
            rotation_matrix: state.camera.rotation_matrix,
        },
    );
    if let Some(camera_node) = index
        .get(&pge_frame.camera_entity.0)
        .and_then(|node_id| pge_frame.world.nodes.get(node_id))
        && let Some(camera_id) = camera_node.camera
        && let Some(camera) = pge_frame.world.cameras.get_mut(&camera_id)
    {
        camera.fov_deg = state.camera.fov_deg;
        camera.resolution = state.camera.resolution;
    }
    let output = renderer
        .render(&pge_frame.world, &pge_frame.request)
        .map_err(|err| format!("render capture state frame {frame_index}: {err}"))?;
    output
        .frames
        .into_iter()
        .next()
        .map(|frame| frame.bytes)
        .ok_or_else(|| "offscreen PGE renderer returned no PNG frame".to_string())
}

pub(crate) fn save_capture_state_screenshot(
    project_path: &Path,
    state: &CaptureStateV1,
    frame_index: usize,
    path: &Path,
) -> Result<(), String> {
    let png = render_capture_state_png(project_path, state, frame_index)?;
    if let Some(parent) = path.parent()
        && !parent.as_os_str().is_empty()
    {
        fs::create_dir_all(parent).map_err(|err| {
            format!(
                "create simulation screenshot directory {}: {err}",
                parent.display()
            )
        })?;
    }
    fs::write(path, png)
        .map_err(|err| format!("write simulation screenshot {}: {err}", path.display()))
}

fn validate_capture_project(project_path: &Path, expected: &CaptureProject) -> Result<(), String> {
    let bytes = fs::read(project_path)
        .map_err(|err| format!("read RobotDreams project {}: {err}", project_path.display()))?;
    let actual = sha1_hex(&bytes);
    if actual != expected.content_sha1 {
        return Err(format!(
            "RobotDreams project fingerprint mismatch: state requires {}, current project is {}",
            expected.content_sha1, actual
        ));
    }
    Ok(())
}

fn validate_visual_transform_keys(
    frame: &CaptureFrame,
    expected: &BTreeSet<String>,
) -> Result<(), String> {
    let actual = frame
        .visual_transforms
        .keys()
        .cloned()
        .collect::<BTreeSet<_>>();
    if &actual == expected {
        return Ok(());
    }
    let missing = expected.difference(&actual).cloned().collect::<Vec<_>>();
    let unexpected = actual.difference(expected).cloned().collect::<Vec<_>>();
    Err(format!(
        "capture visual transform key mismatch; missing={missing:?}; unexpected={unexpected:?}"
    ))
}

fn rigid_transform_from_capture(transform: CaptureRigidTransform) -> RigidTransform {
    RigidTransform {
        translation_m: transform.translation_m,
        rotation: transform.rotation_matrix,
    }
}

fn sha1_hex(bytes: &[u8]) -> String {
    Sha1::digest(bytes)
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

fn project_camera_pose(dreams: &RobotDreams, camera_id: &str) -> Option<ProjectCameraPose> {
    let camera = dreams.camera_spec(camera_id)?;
    let rotation_matrix = camera.transform.rotation_matrix?;
    let values = camera
        .transform
        .translation
        .into_iter()
        .chain(rotation_matrix.into_iter().flatten())
        .chain([camera.fov_deg])
        .collect::<Vec<_>>();
    if values.iter().any(|value| !value.is_finite())
        || !(0.0..180.0).contains(&camera.fov_deg)
        || camera.resolution.contains(&0)
    {
        return None;
    }
    Some(ProjectCameraPose {
        transform: PreviewCameraTransform {
            translation: camera.transform.translation,
            rotation_matrix,
        },
        fov_deg: camera.fov_deg,
        resolution: camera.resolution,
    })
}

fn wrist_camera_jog_direction(
    dreams: &RobotDreams,
    direction: TcpCameraJogDirection,
) -> Result<[f64; 3], String> {
    let camera = dreams.camera_spec(WRIST_CAMERA_ID).ok_or_else(|| {
        "wrist-camera POV jog requires RobotDreams camera:wrist_camera".to_string()
    })?;
    let camera_from_local = camera
        .transform
        .rotation_matrix
        .ok_or_else(|| "wrist-camera POV jog requires a valid camera rotation".to_string())?;
    let world_direction = camera_pov_world_direction(camera_from_local, direction)?;
    let world_from_arm_base = simulation_frame_transforms(dreams)
        .ok_or_else(|| "wrist-camera POV jog requires the PuppyBot arm-base frame".to_string())?
        .world_from_arm_base();
    let arm_base_from_world = world_from_arm_base.inverse().rotation;
    normalize_direction(matrix_vector(arm_base_from_world, world_direction))
        .ok_or_else(|| "wrist-camera POV jog produced an invalid arm-base direction".to_string())
}

/// RobotDreams normalizes a native camera matrix so its columns are optical
/// forward, image-left, and image-up.  This applies the authored camera roll;
/// screen Up/Down must therefore use column 2 rather than world Z.
fn camera_pov_world_direction(
    camera_from_local: [[f32; 3]; 3],
    direction: TcpCameraJogDirection,
) -> Result<[f64; 3], String> {
    let (column, sign) = match direction {
        TcpCameraJogDirection::Forward => (0, 1.0),
        TcpCameraJogDirection::Back => (0, -1.0),
        TcpCameraJogDirection::Left => (1, 1.0),
        TcpCameraJogDirection::Right => (1, -1.0),
        TcpCameraJogDirection::Up => (2, 1.0),
        TcpCameraJogDirection::Down => (2, -1.0),
    };
    let vector = [
        sign * f64::from(camera_from_local[0][column]),
        sign * f64::from(camera_from_local[1][column]),
        sign * f64::from(camera_from_local[2][column]),
    ];
    normalize_direction(vector)
        .ok_or_else(|| "wrist-camera POV jog produced an invalid camera basis".to_string())
}

fn matrix_vector(matrix: [[f64; 3]; 3], vector: [f64; 3]) -> [f64; 3] {
    [
        matrix[0][0] * vector[0] + matrix[0][1] * vector[1] + matrix[0][2] * vector[2],
        matrix[1][0] * vector[0] + matrix[1][1] * vector[1] + matrix[1][2] * vector[2],
        matrix[2][0] * vector[0] + matrix[2][1] * vector[1] + matrix[2][2] * vector[2],
    ]
}

fn normalize_direction(vector: [f64; 3]) -> Option<[f64; 3]> {
    let length_squared = vector.into_iter().map(|value| value * value).sum::<f64>();
    if !length_squared.is_finite() || length_squared <= f64::EPSILON {
        return None;
    }
    let length = length_squared.sqrt();
    Some(vector.map(|value| value / length))
}

fn preview_snapshot_from_state(
    state: &RobotDreamsRuntimeState,
    arm: Option<&PuppyarmTelemetry>,
) -> PreviewSnapshot {
    let robot_snapshot = state.dreams.snapshot();
    let mut debug_markers = state.dreams.coordinate_debug_marker_positions(
        robotdreams_core::CoordinateDebugOverlayOptions::default(),
    );
    let frames = simulation_frame_transforms(&state.dreams);
    override_debug_markers_with_puppybot_tcp(
        &mut debug_markers,
        state.puppybot_target_tcp_mm,
        frames,
    );
    let robot_visual_transforms = state
        .dreams
        .model()
        .map(|model| model.robot_visual_transforms())
        .unwrap_or_default();
    let mut visual_transforms = state
        .visual_bindings
        .iter()
        .zip(&robot_visual_transforms)
        .map(|(binding, transform)| {
            (
                binding.entity.clone(),
                PgeCoreTransform::matrix(transform.translation, transform.rotation_matrix),
            )
        })
        .collect::<BTreeMap<_, _>>();
    for object in &robot_snapshot.scene_objects {
        visual_transforms.insert(
            format!("object:{}", object.id),
            PgeCoreTransform {
                translation: object.position,
                rotation: object.rotation,
                rotation_matrix: None,
            },
        );
    }
    let robots = robot_snapshot
        .robots
        .iter()
        .map(|robot| CaptureRobot {
            id: robot.id.clone(),
            name: robot.name.clone(),
            base_position_m: robot.base.position,
            base_rotation_rad: robot.base.rotation,
            joints_rad: robot
                .joints
                .values()
                .map(|joint| {
                    (
                        joint
                            .semantic_name
                            .clone()
                            .unwrap_or_else(|| joint.urdf_name.clone()),
                        joint.position_rad,
                    )
                })
                .collect(),
            tcp_world_m: robot
                .tcp
                .as_ref()
                .and_then(|tcp| tcp.location.as_ref())
                .map(|location| location.position),
        })
        .collect();
    let servos = arm
        .map(|telemetry| {
            telemetry
                .joints
                .iter()
                .map(|joint| CaptureServo {
                    bus_id: SERVO_MAIN_BUS_ID.to_string(),
                    id: joint.servo_id,
                    present_tick: joint.tick,
                    target_tick: joint.target_tick,
                    angle_rad: joint.angle_rad,
                })
                .collect()
        })
        .unwrap_or_default();
    let labels = state.labels.clone();
    let wrist_camera = project_camera_pose(&state.dreams, WRIST_CAMERA_ID);
    let capture_frame = CaptureFrame {
        sequence: state.sequence,
        simulation_clock_sec: robot_snapshot.clock_sec,
        robots,
        servos,
        visual_transforms: visual_transforms.clone(),
        manipulation: manipulation_state_from_dreams(&state.dreams, state.last_tool_action.clone())
            .ok(),
        overlays: CaptureOverlays {
            labels: labels
                .iter()
                .enumerate()
                .map(|(row, label)| CaptureLabel {
                    id: label.id.clone(),
                    text: label.text.clone(),
                    row,
                    color: label.color,
                })
                .collect(),
            debug_markers: debug_markers
                .iter()
                .map(|marker| CaptureDebugMarker {
                    robot_id: marker.robot_id.clone(),
                    floor_z: marker.floor_z,
                    current_tcp: marker.current_tcp,
                    target_tcp: marker.target_tcp,
                })
                .collect(),
            controller_arm_world_m: state
                .controller_arm_chain_world_m
                .map(|chain| chain.points_world_m),
            world_from_base: frames.map(|frames| capture_rigid_transform(frames.world_from_base)),
            base_from_arm_base: frames
                .map(|frames| capture_rigid_transform(frames.base_from_arm_base)),
        },
    };
    PreviewSnapshot {
        labels,
        visual_transforms,
        debug_markers,
        frames,
        controller_arm_chain: state.controller_arm_chain_world_m,
        wrist_camera,
        capture_frame,
    }
}

fn capture_rigid_transform(transform: RigidTransform) -> CaptureRigidTransform {
    CaptureRigidTransform {
        translation_m: transform.translation_m,
        rotation_matrix: transform.rotation,
    }
}

fn sync_preview_snapshot_world(
    world: &mut pge_core::WorldState,
    index: &HashMap<String, PgeCoreArenaId<PgeCoreNode>>,
    _visual_bindings: &[PreviewVisualBinding],
    snapshot: &PreviewSnapshot,
    show_diagnostics: bool,
) {
    if show_diagnostics {
        let mut text_labels = snapshot.labels.clone();
        let legend_row_start = text_labels.len();
        text_labels.extend(coordinate_debug_legend_labels(legend_row_start));
        text_labels.push(RobotDreamsPgeTextLabel::overlay_with_color(
            "controller_arm_legend",
            CONTROLLER_ARM_LEGEND,
            text_labels.len(),
            [1.0, 0.2, 0.9, 1.0],
        ));
        world.text_labels = text_labels.into_iter().map(pge_text_label).collect();
    } else {
        world.text_labels.clear();
    }
    sync_visual_transforms(world, &snapshot.visual_transforms, index);
    sync_tcp_debug_markers(world, &snapshot.debug_markers, index);
    sync_controller_arm_overlay(world, snapshot.controller_arm_chain.as_ref(), index);
    if let Some(frames) = snapshot.frames {
        sync_debug_frame_roots(world, frames, index);
    }
}

fn model_telemetry(robot_state: &RobotState) -> ModelTelemetry {
    ModelTelemetry {
        tcp_world_m: robot_state
            .tcp
            .as_ref()
            .and_then(|tcp| tcp.location.as_ref())
            .map(|location| location.position),
        joint_angles_rad: MODEL_JOINT_NAMES.map(|semantic_name| {
            robot_state
                .joints
                .values()
                .find(|joint| joint.semantic_name.as_deref() == Some(semantic_name))
                .map(|joint| joint.position_rad)
        }),
    }
}

fn controller_arm_chain_world_m(
    telemetry: &PuppyarmTelemetry,
    frames: SimulationFrameTransforms,
) -> Option<ControllerArmChain> {
    let mut angles = [0.0; JOINT_COUNT];
    for (index, joint) in telemetry.joints.iter().enumerate() {
        if !joint.has_feedback {
            return None;
        }
        angles[index] = joint.angle_rad?;
    }
    let chain = kinematics::arm_chain_points(angles[0], angles[1], angles[2], angles[3]);
    let points_arm_mm = [
        chain.yaw,
        chain.shoulder,
        chain.elbow,
        chain.wrist,
        chain.tcp,
    ];
    let world_from_arm_base = frames.world_from_arm_base();
    Some(ControllerArmChain {
        points_world_m: points_arm_mm.map(|point_mm| {
            f64_vec3_to_f32(
                world_from_arm_base.transform_point(point_mm.map(|value| value * 0.001)),
            )
        }),
    })
}

fn push_model_telemetry_labels(
    labels: &mut Vec<RobotDreamsPgeTextLabel>,
    telemetry: Option<&ModelTelemetry>,
) {
    let tcp_text = telemetry
        .and_then(|telemetry| telemetry.tcp_world_m)
        .map(|[x, y, z]| format!("MODEL OBS TCP WORLD M X {x:.3} Y {y:.3} Z {z:.3}"))
        .unwrap_or_else(|| "MODEL OBS TCP WORLD M X NA Y NA Z NA".to_string());
    push_overlay_label(labels, "model_tcp_observed", tcp_text);

    let joint_angles = telemetry
        .map(|telemetry| telemetry.joint_angles_rad)
        .unwrap_or([None; 4]);
    push_overlay_label(
        labels,
        "model_joints_observed",
        format!(
            "MODEL URDF RAW Q DEG YAW {} SHOULDER {} ELBOW {} WRIST {}",
            option_degrees(joint_angles[0]),
            option_degrees(joint_angles[1]),
            option_degrees(joint_angles[2]),
            option_degrees(joint_angles[3]),
        ),
    );
}

fn push_controller_tcp_alignment_label(
    labels: &mut Vec<RobotDreamsPgeTextLabel>,
    controller_chain: Option<&ControllerArmChain>,
    model_telemetry: Option<&ModelTelemetry>,
) {
    let text = controller_tcp_model_delta_mm(controller_chain, model_telemetry)
        .map(|delta_mm| {
            let status = if delta_mm <= TCP_ALIGNMENT_TOLERANCE_MM {
                format!("ALIGNED <= {TCP_ALIGNMENT_TOLERANCE_MM:.1}")
            } else {
                format!("MISMATCH > {TCP_ALIGNMENT_TOLERANCE_MM:.1}")
            };
            format!("CTRL FK TCP DELTA TO MODEL MM {delta_mm:.1} ({status})")
        })
        .unwrap_or_else(|| "CTRL FK TCP DELTA TO MODEL MM NA".to_string());
    push_overlay_label(labels, "controller_tcp_model_delta", text);
}

fn controller_tcp_model_delta_mm(
    controller_chain: Option<&ControllerArmChain>,
    model_telemetry: Option<&ModelTelemetry>,
) -> Option<f64> {
    let controller_tcp = controller_chain?.points_world_m[4];
    let model_tcp = model_telemetry?.tcp_world_m?;
    let squared_distance: f64 = controller_tcp
        .into_iter()
        .map(f64::from)
        .zip(model_tcp)
        .map(|(controller, model)| (controller - model).powi(2))
        .sum();
    Some(squared_distance.sqrt() * 1000.0)
}

fn push_overlay_label(
    labels: &mut Vec<RobotDreamsPgeTextLabel>,
    id: impl Into<String>,
    text: impl Into<String>,
) {
    labels.push(RobotDreamsPgeTextLabel::overlay(id, text, labels.len()));
}

fn format_simulation_ups(ups: Option<f64>) -> String {
    match ups.filter(|ups| ups.is_finite() && *ups >= 0.0) {
        Some(ups) => format!("SIM {ups:.1} UPS"),
        None => "SIM -- UPS".to_string(),
    }
}

impl SimulatedPreview {
    pub(crate) fn capture_state(&self) -> Result<Arc<CaptureStateV1>, String> {
        let published = self
            .published
            .lock()
            .map_err(|_| "simulation published preview lock poisoned")?;
        Ok(Arc::clone(&published.capture_state))
    }

    pub(crate) fn project_path(&self) -> &Path {
        &self.project_path
    }

    fn offscreen_frame(
        &self,
        camera: ScreenshotCamera,
    ) -> Result<(robotdreams_core::RobotDreamsPgeFrame, f64), String> {
        let snapshot = self
            .published
            .lock()
            .map_err(|_| "RobotDreams preview snapshot lock poisoned before screenshot")?
            .snapshot
            .as_ref()
            .clone();
        let (mut frame, model_telemetry) = {
            let state = self
                .state
                .lock()
                .map_err(|_| "RobotDreams preview state lock poisoned before screenshot")?;
            let mut options = RobotDreamsPgeFrameOptions::default();
            options.text_labels = state.labels.clone();
            let frame = robotdreams_pge_frame(&state.dreams, options);
            let model_telemetry = state
                .dreams
                .robot_state(ROBOT_ID)
                .as_ref()
                .map(model_telemetry);
            (frame, model_telemetry)
        };

        insert_controller_arm_overlay(&mut frame.world);
        let world_node_index = index_world_nodes(&frame.world);
        set_world_camera_transform(
            &mut frame.world,
            &world_node_index,
            &frame.camera_entity.0,
            screenshot_camera_transform(camera),
        );
        let mut text_labels = snapshot.labels;
        let legend_row_start = text_labels.len();
        text_labels.extend(coordinate_debug_legend_labels(legend_row_start));
        text_labels.push(RobotDreamsPgeTextLabel::overlay_with_color(
            "controller_arm_legend",
            CONTROLLER_ARM_LEGEND,
            text_labels.len(),
            [1.0, 0.2, 0.9, 1.0],
        ));
        frame.world.text_labels = text_labels.into_iter().map(pge_text_label).collect();
        sync_visual_transforms(
            &mut frame.world,
            &snapshot.visual_transforms,
            &world_node_index,
        );
        sync_tcp_debug_markers(&mut frame.world, &snapshot.debug_markers, &world_node_index);
        sync_controller_arm_overlay(
            &mut frame.world,
            snapshot.controller_arm_chain.as_ref(),
            &world_node_index,
        );
        if let Some(frames) = snapshot.frames {
            sync_debug_frame_roots(&mut frame.world, frames, &world_node_index);
        }

        let delta_mm = controller_tcp_model_delta_mm(
            snapshot.controller_arm_chain.as_ref(),
            model_telemetry.as_ref(),
        )
        .ok_or_else(|| {
            "controller/model TCP alignment is unavailable after settling".to_string()
        })?;
        Ok((frame, delta_mm))
    }

    pub(crate) fn save_screenshot(
        &self,
        path: &Path,
        camera: ScreenshotCamera,
    ) -> Result<f64, String> {
        let (frame, delta_mm) = self.offscreen_frame(camera)?;
        let mut renderer = WgpuRenderer::new()
            .map_err(|err| format!("create offscreen PGE WGPU renderer: {err}"))?;
        let output = renderer
            .render(&frame.world, &frame.request)
            .map_err(|err| format!("render offscreen PuppyBot simulation: {err}"))?;
        let png = output
            .frames
            .into_iter()
            .next()
            .ok_or_else(|| "offscreen PGE renderer returned no RGB frame".to_string())?;
        if let Some(parent) = path.parent()
            && !parent.as_os_str().is_empty()
        {
            fs::create_dir_all(parent).map_err(|err| {
                format!(
                    "create simulation screenshot directory {}: {err}",
                    parent.display()
                )
            })?;
        }
        fs::write(path, png.bytes)
            .map_err(|err| format!("write simulation screenshot {}: {err}", path.display()))?;
        Ok(delta_mm)
    }

    pub(crate) fn run_blocking(self) -> Result<(), String> {
        self.window_active.store(true, Ordering::Release);
        let state = Arc::clone(&self.state);
        let published = Arc::clone(&self.published);
        let simulation_ups = Arc::clone(&self.simulation_ups);
        let ups_overlay = WindowOverlayLines::default();
        ups_overlay.set(vec![format_simulation_ups(None)]);
        let ups_overlay_for_update = ups_overlay.clone();
        let capture_project = self.project.clone();
        let options = RobotDreamsPgeFrameOptions::default();
        let target = options.target;
        let elevation_rad = options.camera_elevation_deg.to_radians();
        let eye = [
            target[0] + options.camera_radius_m * elevation_rad.cos(),
            target[1] - options.camera_radius_m * 0.45,
            target[2] + options.camera_radius_m * elevation_rad.sin(),
        ];
        let mut orbit_controller = OrbitController::default();
        orbit_controller.rot_speed = 0.008;
        orbit_controller.min_dist = 0.08;
        orbit_controller.max_dist = 20.0;
        orbit_controller.set_from_target_and_position(
            robotdreams_to_orbit_space(target),
            robotdreams_to_orbit_space(eye),
        );
        let mut orbit_state = PgeAppState::default();
        let orbit_camera_node_id = orbit_state.nodes.insert(PgeAppNode::default());
        orbit_controller.process(&mut orbit_state, orbit_camera_node_id, 0.0);

        let (mut frame, tcp_frame, visual_bindings, window_plan) = match state.lock() {
            Ok(state) => {
                let mut options = options.clone();
                options.text_labels = state.labels.clone();
                let frame = robotdreams_pge_frame(&state.dreams, options);
                let visual_bindings = state
                    .dreams
                    .model()
                    .map(|model| preview_visual_bindings(&model.robot_visual_meshes()))
                    .unwrap_or_default();
                let wrist_camera = project_camera_pose(&state.dreams, WRIST_CAMERA_ID);
                let window_plan = interactive_preview_window_plan(wrist_camera);
                let tcp_frame = wrist_camera.map(|camera| {
                    let mut tcp_options = RobotDreamsPgeFrameOptions::default();
                    tcp_options.resolution = camera.resolution;
                    robotdreams_pge_frame(&state.dreams, tcp_options)
                });
                (frame, tcp_frame, visual_bindings, window_plan)
            }
            Err(_) => return Err("RobotDreams preview state lock poisoned before startup".into()),
        };
        insert_controller_arm_overlay(&mut frame.world);
        let world_node_index = index_world_nodes(&frame.world);
        set_world_camera_transform(
            &mut frame.world,
            &world_node_index,
            &frame.camera_entity.0,
            orbit_camera_transform(&orbit_state, orbit_camera_node_id, &orbit_controller),
        );
        let main_camera_entity = frame.camera_entity.0.clone();

        let initial_snapshot = match published.lock() {
            Ok(published) => Arc::clone(&published.snapshot),
            Err(_) => {
                return Err("RobotDreams preview snapshot lock poisoned before startup".into());
            }
        };
        // The main window refreshes this once per rendered frame. The TCP window only
        // consumes it, preventing a second render surface from advancing the model.
        let primary_rendered_snapshot = Arc::new(Mutex::new(Arc::clone(&initial_snapshot)));

        let mut targets = vec![WindowRenderTarget {
            world: frame.world,
            request: frame.request,
            config: WindowRenderConfig {
                title: "PuppyBot RobotDreams Simulation".to_string(),
                resolution: options.resolution,
            },
            overlay_lines: ups_overlay,
        }];
        let tcp_window = tcp_frame.map(|mut tcp_frame| {
            insert_controller_arm_overlay(&mut tcp_frame.world);
            let tcp_index = index_world_nodes(&tcp_frame.world);
            // RobotDreams emits a real `camera:wrist_camera` node. Select it rather
            // than the synthetic PGE orbit camera that the primary preview uses.
            let tcp_camera_entity = format!("camera:{WRIST_CAMERA_ID}");
            tcp_frame.request.camera_id = Some(pge_core::EntityId(tcp_camera_entity.clone()));
            if let Some(wrist_camera) = initial_snapshot.wrist_camera {
                set_world_camera_transform(
                    &mut tcp_frame.world,
                    &tcp_index,
                    &tcp_camera_entity,
                    wrist_camera.transform,
                );
                set_world_camera_projection(
                    &mut tcp_frame.world,
                    &tcp_index,
                    &tcp_camera_entity,
                    wrist_camera.fov_deg,
                    wrist_camera.resolution,
                );
            }
            targets.push(WindowRenderTarget {
                world: tcp_frame.world,
                request: tcp_frame.request,
                config: WindowRenderConfig {
                    title: TCP_CAMERA_WINDOW_TITLE.to_string(),
                    resolution: window_plan.tcp_camera_resolution,
                },
                overlay_lines: WindowOverlayLines::default(),
            });
            (tcp_index, tcp_camera_entity)
        });
        if !window_plan.open_tcp_camera {
            log::warn!(
                "RobotDreams project has no usable {WRIST_CAMERA_ID}; TCP camera window disabled"
            );
        }

        let result = run_windows_with_overlay(targets, move |window_index, world, context| {
            if window_index == 0 {
                let [dx, dy] = context.input.right_drag_delta_px;
                if dx != 0.0 || dy != 0.0 {
                    orbit_controller.orbit(Vec2::new(dx, dy));
                }
                let [dx, dy] = context.input.middle_drag_delta_px;
                if dx != 0.0 || dy != 0.0 {
                    orbit_controller.pan(Vec2::new(dx, dy));
                }
                if context.input.scroll_delta_lines != 0.0 {
                    orbit_controller.zoom(context.input.scroll_delta_lines);
                }
                orbit_controller.process(&mut orbit_state, orbit_camera_node_id, 0.0);

                let rendered_snapshot = match published.lock() {
                    Ok(published) => Arc::clone(&published.snapshot),
                    Err(_) => {
                        log::warn!("simulation preview snapshot lock poisoned");
                        return Ok(false);
                    }
                };
                if let Ok(mut latest) = primary_rendered_snapshot.lock() {
                    *latest = Arc::clone(&rendered_snapshot);
                }
                let displayed_ups = simulation_ups
                    .lock()
                    .ok()
                    .and_then(|counter| counter.displayed_at(Instant::now()));
                ups_overlay_for_update.set(vec![format_simulation_ups(displayed_ups)]);
                sync_preview_snapshot_world(
                    world,
                    &world_node_index,
                    &visual_bindings,
                    rendered_snapshot.as_ref(),
                    true,
                );
                let camera_transform =
                    orbit_camera_transform(&orbit_state, orbit_camera_node_id, &orbit_controller);
                set_world_camera_transform(
                    world,
                    &world_node_index,
                    &main_camera_entity,
                    camera_transform,
                );
                if let Ok(mut published) = published.lock() {
                    let camera = capture_camera_from_orbit(
                        camera_transform,
                        &orbit_controller,
                        options.resolution,
                    );
                    published.capture_state =
                        published_capture_state(&capture_project, &camera, &rendered_snapshot);
                    published.camera = camera;
                }
                return Ok(true);
            }

            let Some((tcp_index, tcp_camera_entity)) = tcp_window.as_ref() else {
                return Ok(false);
            };
            let rendered_snapshot = match primary_rendered_snapshot.lock() {
                Ok(snapshot) => Arc::clone(&snapshot),
                Err(_) => {
                    log::warn!("primary simulation preview snapshot lock poisoned");
                    return Ok(false);
                }
            };
            sync_preview_snapshot_world(
                world,
                tcp_index,
                &visual_bindings,
                rendered_snapshot.as_ref(),
                false,
            );
            if let Some(wrist_camera) = rendered_snapshot.wrist_camera {
                set_world_camera_transform(
                    world,
                    tcp_index,
                    tcp_camera_entity,
                    wrist_camera.transform,
                );
                set_world_camera_projection(
                    world,
                    tcp_index,
                    tcp_camera_entity,
                    wrist_camera.fov_deg,
                    wrist_camera.resolution,
                );
            }
            Ok(true)
        });
        self.window_active.store(false, Ordering::Release);
        result.map_err(|err| err.to_string())
    }
}

fn published_capture_state(
    project: &CaptureProject,
    camera: &CaptureCamera,
    snapshot: &Arc<PreviewSnapshot>,
) -> Arc<CaptureStateV1> {
    Arc::new(CaptureStateV1 {
        schema: CAPTURE_STATE_SCHEMA.to_string(),
        exact_visual_replay: false,
        exact_saved_transforms: true,
        pose_equivalent_render: true,
        exact_dynamic_continuation: false,
        project: project.clone(),
        camera: camera.clone(),
        frames: vec![snapshot.capture_frame.clone()],
    })
}

#[derive(Clone, Copy, Debug, PartialEq)]
struct PreviewCameraTransform {
    translation: [f32; 3],
    rotation_matrix: [[f32; 3]; 3],
}

fn capture_camera_from_screenshot(camera: ScreenshotCamera) -> CaptureCamera {
    let transform = screenshot_camera_transform(camera);
    CaptureCamera {
        target_m: camera.target,
        eye_m: transform.translation,
        rotation_matrix: transform.rotation_matrix,
        radius_m: camera.radius_m,
        azimuth_deg: camera.azimuth_deg,
        elevation_deg: camera.elevation_deg,
        fov_deg: CAPTURE_FOV_DEG,
        projection: "perspective".to_string(),
        resolution: RobotDreamsPgeFrameOptions::default().resolution,
    }
}

fn capture_camera_from_orbit(
    transform: PreviewCameraTransform,
    orbit: &OrbitController,
    resolution: [u32; 2],
) -> CaptureCamera {
    let target_m = orbit_to_robotdreams_space(orbit.target);
    let delta = [
        transform.translation[0] - target_m[0],
        transform.translation[1] - target_m[1],
        transform.translation[2] - target_m[2],
    ];
    let radius_m = (delta[0] * delta[0] + delta[1] * delta[1] + delta[2] * delta[2]).sqrt();
    CaptureCamera {
        target_m,
        eye_m: transform.translation,
        rotation_matrix: transform.rotation_matrix,
        radius_m,
        azimuth_deg: delta[1].atan2(delta[0]).to_degrees(),
        elevation_deg: (delta[2] / radius_m.max(f32::EPSILON)).asin().to_degrees(),
        fov_deg: CAPTURE_FOV_DEG,
        projection: "perspective".to_string(),
        resolution,
    }
}

fn screenshot_camera_transform(camera: ScreenshotCamera) -> PreviewCameraTransform {
    let target = camera.target;
    let azimuth_rad = camera.azimuth_deg.to_radians();
    let elevation_rad = camera.elevation_deg.to_radians();
    let horizontal_radius = camera.radius_m * elevation_rad.cos();
    let eye = [
        target[0] + horizontal_radius * azimuth_rad.cos(),
        target[1] + horizontal_radius * azimuth_rad.sin(),
        target[2] + camera.radius_m * elevation_rad.sin(),
    ];
    let mut orbit_controller = OrbitController::default();
    orbit_controller.rot_speed = 0.008;
    orbit_controller.min_dist = 0.08;
    orbit_controller.max_dist = 20.0;
    orbit_controller.set_from_target_and_position(
        robotdreams_to_orbit_space(target),
        robotdreams_to_orbit_space(eye),
    );
    let mut orbit_state = PgeAppState::default();
    let orbit_camera_node_id = orbit_state.nodes.insert(PgeAppNode::default());
    orbit_controller.process(&mut orbit_state, orbit_camera_node_id, 0.0);
    orbit_camera_transform(&orbit_state, orbit_camera_node_id, &orbit_controller)
}

#[derive(Clone, Debug)]
struct PreviewVisualBinding {
    entity: String,
}

fn index_world_nodes(world: &pge_core::WorldState) -> HashMap<String, PgeCoreArenaId<PgeCoreNode>> {
    world
        .nodes
        .iter()
        .map(|(node_id, node)| (node.entity.0.clone(), node_id))
        .collect()
}

fn preview_visual_bindings(
    visual_meshes: &[robotdreams_core::project::RobotVisualMesh],
) -> Vec<PreviewVisualBinding> {
    visual_meshes
        .iter()
        .enumerate()
        .map(|(visual_index, visual)| PreviewVisualBinding {
            entity: format!(
                "robot:{}:visual:{}:{visual_index}",
                visual.robot_id, visual.link_name
            ),
        })
        .collect()
}

fn expected_visual_transform_keys(dreams: &RobotDreams) -> BTreeSet<String> {
    let mut keys = dreams
        .model()
        .map(|model| {
            preview_visual_bindings(&model.robot_visual_meshes())
                .into_iter()
                .map(|binding| binding.entity)
                .collect::<BTreeSet<_>>()
        })
        .unwrap_or_default();
    keys.extend(
        dreams
            .snapshot()
            .scene_objects
            .into_iter()
            .map(|object| format!("object:{}", object.id)),
    );
    keys
}

fn sync_visual_transforms(
    world: &mut pge_core::WorldState,
    visual_transforms: &BTreeMap<String, PgeCoreTransform>,
    index: &HashMap<String, PgeCoreArenaId<PgeCoreNode>>,
) {
    for (entity, transform) in visual_transforms {
        set_world_node_transform(world, index, entity, *transform);
    }
}

fn insert_controller_arm_overlay(world: &mut pge_core::WorldState) {
    let material = world.materials.insert(pge_core::Material {
        name: Some("PuppyArm controller FK overlay".to_string()),
        base_color_factor: [1.0, 0.08, 0.82, 1.0],
        emissive_factor: [0.35, 0.0, 0.25],
        ..pge_core::Material::default()
    });
    let point_mesh = world.meshes.insert(pge_core::Mesh {
        name: Some("PuppyArm controller FK point".to_string()),
        source: pge_core::MeshSource::Procedural(pge_core::Geometry::Sphere {
            radius: CONTROLLER_ARM_POINT_RADIUS_M,
        }),
        material: Some(material),
    });
    for point_name in CONTROLLER_ARM_POINT_NAMES {
        let mut node = pge_core::Node::new(format!(
            "debug:{ROBOT_ID}:controller_arm:point:{point_name}"
        ));
        node.mesh = Some(point_mesh);
        node.transform.translation = [0.0, 0.0, -10_000.0];
        world.nodes.insert(node);
    }
    for segment_name in CONTROLLER_ARM_SEGMENT_NAMES {
        let segment_mesh = world.meshes.insert(pge_core::Mesh {
            name: Some(format!("PuppyArm controller FK segment {segment_name}")),
            source: pge_core::MeshSource::Procedural(pge_core::Geometry::Box {
                size: [0.001, 0.006, 0.006],
            }),
            material: Some(material),
        });
        let mut node = pge_core::Node::new(format!(
            "debug:{ROBOT_ID}:controller_arm:segment:{segment_name}"
        ));
        node.mesh = Some(segment_mesh);
        node.transform.translation = [0.0, 0.0, -10_000.0];
        world.nodes.insert(node);
    }
    set_puppybot_current_tcp_marker_radius(world, PUPPYBOT_CURRENT_TCP_MARKER_RADIUS_M);
}

fn set_puppybot_current_tcp_marker_radius(world: &mut pge_core::WorldState, radius_m: f32) {
    let entity = format!("debug:{ROBOT_ID}:tcp:current");
    let mesh_id = world
        .nodes
        .iter()
        .find(|(_, node)| node.entity.0 == entity)
        .and_then(|(_, node)| node.mesh);
    let Some(mesh_id) = mesh_id else {
        return;
    };
    let Some(mesh) = world.meshes.get_mut(&mesh_id) else {
        return;
    };
    if let pge_core::MeshSource::Procedural(pge_core::Geometry::Sphere { radius }) =
        &mut mesh.source
    {
        *radius = radius_m;
    }
}

fn sync_controller_arm_overlay(
    world: &mut pge_core::WorldState,
    chain: Option<&ControllerArmChain>,
    index: &HashMap<String, PgeCoreArenaId<PgeCoreNode>>,
) {
    let Some(chain) = chain else {
        for point_name in CONTROLLER_ARM_POINT_NAMES {
            hide_world_node(
                world,
                index,
                &format!("debug:{ROBOT_ID}:controller_arm:point:{point_name}"),
            );
        }
        for segment_name in CONTROLLER_ARM_SEGMENT_NAMES {
            hide_world_line_segment(
                world,
                index,
                &format!("debug:{ROBOT_ID}:controller_arm:segment:{segment_name}"),
            );
        }
        return;
    };

    for (point_name, point) in CONTROLLER_ARM_POINT_NAMES.iter().zip(chain.points_world_m) {
        set_world_node_translation(
            world,
            index,
            &format!("debug:{ROBOT_ID}:controller_arm:point:{point_name}"),
            point,
        );
    }
    for (segment_name, points) in CONTROLLER_ARM_SEGMENT_NAMES
        .iter()
        .zip(chain.points_world_m.windows(2))
    {
        set_world_line_segment(
            world,
            index,
            &format!("debug:{ROBOT_ID}:controller_arm:segment:{segment_name}"),
            points[0],
            points[1],
        );
    }
}

fn sync_tcp_debug_markers(
    world: &mut pge_core::WorldState,
    markers: &[CoordinateDebugMarkerPositions],
    index: &HashMap<String, PgeCoreArenaId<PgeCoreNode>>,
) {
    for marker in markers {
        if let Some(position) = marker.current_tcp {
            set_world_node_translation(
                world,
                index,
                &format!("debug:{}:tcp:current", marker.robot_id),
                position,
            );
            set_world_node_translation(
                world,
                index,
                &format!("debug:{}:tcp:current:floor", marker.robot_id),
                [position[0], position[1], marker.floor_z],
            );
        } else {
            hide_world_node(
                world,
                index,
                &format!("debug:{}:tcp:current", marker.robot_id),
            );
            hide_world_node(
                world,
                index,
                &format!("debug:{}:tcp:current:floor", marker.robot_id),
            );
        }
        if let Some(position) = marker.target_tcp {
            set_world_node_translation(
                world,
                index,
                &format!("debug:{}:tcp:target", marker.robot_id),
                position,
            );
            set_world_node_translation(
                world,
                index,
                &format!("debug:{}:tcp:target:floor", marker.robot_id),
                [position[0], position[1], marker.floor_z],
            );
        } else {
            hide_world_node(
                world,
                index,
                &format!("debug:{}:tcp:target", marker.robot_id),
            );
            hide_world_node(
                world,
                index,
                &format!("debug:{}:tcp:target:floor", marker.robot_id),
            );
        }
        if let (Some(current), Some(target)) = (marker.current_tcp, marker.target_tcp)
            && length(sub(target, current)) > 0.001
        {
            set_world_line_segment(
                world,
                index,
                &format!("debug:{}:tcp:delta", marker.robot_id),
                current,
                target,
            );
        } else {
            hide_world_line_segment(
                world,
                index,
                &format!("debug:{}:tcp:delta", marker.robot_id),
            );
        }
    }
}

fn hide_capture_dynamic_entities(
    world: &mut pge_core::WorldState,
    index: &HashMap<String, PgeCoreArenaId<PgeCoreNode>>,
) {
    for entity in [
        "debug:puppybot:tcp:current",
        "debug:puppybot:tcp:current:floor",
        "debug:puppybot:tcp:target",
        "debug:puppybot:tcp:target:floor",
        "debug:puppybot:frame:base",
        "debug:puppybot:frame:armBase",
    ] {
        hide_world_node(world, index, entity);
    }
    hide_world_line_segment(world, index, "debug:puppybot:tcp:delta");
    sync_controller_arm_overlay(world, None, index);
}

fn sync_debug_frame_roots(
    world: &mut pge_core::WorldState,
    frames: SimulationFrameTransforms,
    index: &HashMap<String, PgeCoreArenaId<PgeCoreNode>>,
) {
    for (entity, transform) in [
        ("debug:puppybot:frame:base", frames.world_from_base),
        ("debug:puppybot:frame:armBase", frames.world_from_arm_base()),
    ] {
        set_world_node_transform(
            world,
            index,
            entity,
            PgeCoreTransform {
                translation: f64_vec3_to_f32(transform.translation_m),
                rotation: [0.0, 0.0, 0.0],
                rotation_matrix: Some(f64_matrix_to_f32(transform.rotation)),
            },
        );
    }
}

fn override_debug_markers_with_puppybot_tcp(
    markers: &mut [CoordinateDebugMarkerPositions],
    target_tcp_mm: Option<(f32, f32, f32)>,
    frames: Option<SimulationFrameTransforms>,
) {
    for marker in markers {
        if marker.robot_id != ROBOT_ID {
            continue;
        }
        let (Some(target_tcp_mm), Some(frames)) = (target_tcp_mm, frames) else {
            marker.target_tcp = None;
            continue;
        };
        let target_arm_m = [
            f64::from(target_tcp_mm.0) * 0.001,
            f64::from(target_tcp_mm.1) * 0.001,
            f64::from(target_tcp_mm.2) * 0.001,
        ];
        marker.target_tcp = Some(f64_vec3_to_f32(
            frames.world_from_arm_base().transform_point(target_arm_m),
        ));
    }
}

fn simulation_frame_transforms(dreams: &RobotDreams) -> Option<SimulationFrameTransforms> {
    let base = dreams.frame_state(ROBOT_ID, "base")?;
    let arm_base = dreams.frame_state(ROBOT_ID, "armBase")?;
    Some(SimulationFrameTransforms {
        world_from_base: base.world_transform,
        base_from_arm_base: arm_base.relative_transform,
    })
}

fn pge_text_label(label: RobotDreamsPgeTextLabel) -> pge_core::TextLabel {
    pge_core::TextLabel {
        entity: pge_core::EntityId(format!("label:{}", label.id)),
        text: label.text,
        position: label.position,
        color: label.color,
        background_color: label.background_color,
        font_size_px: label.font_size_px,
        billboard: label.billboard,
    }
}

fn set_world_node_translation(
    world: &mut pge_core::WorldState,
    index: &HashMap<String, PgeCoreArenaId<PgeCoreNode>>,
    entity: &str,
    translation: [f32; 3],
) {
    if let Some(node_id) = index.get(entity)
        && let Some(world_node) = world.nodes.get_mut(node_id)
    {
        world_node.transform.translation = translation;
    }
}

fn hide_world_node(
    world: &mut pge_core::WorldState,
    index: &HashMap<String, PgeCoreArenaId<PgeCoreNode>>,
    entity: &str,
) {
    set_world_node_translation(world, index, entity, [0.0, 0.0, -10_000.0]);
}

fn set_world_line_segment(
    world: &mut pge_core::WorldState,
    index: &HashMap<String, PgeCoreArenaId<PgeCoreNode>>,
    entity: &str,
    start: [f32; 3],
    end: [f32; 3],
) {
    let delta = sub(end, start);
    let segment_length = length(delta).max(0.001);
    let Some(node_id) = index.get(entity).copied() else {
        return;
    };
    let mesh_id = world.nodes.get(&node_id).and_then(|node| node.mesh);
    if let Some(world_node) = world.nodes.get_mut(&node_id) {
        world_node.transform = PgeCoreTransform {
            translation: scale_add(start, delta, 0.5),
            rotation: [0.0, 0.0, 0.0],
            rotation_matrix: Some(line_rotation_matrix(delta)),
        };
    }
    let Some(mesh_id) = mesh_id else {
        return;
    };
    let Some(mesh) = world.meshes.get_mut(&mesh_id) else {
        return;
    };
    if let pge_core::MeshSource::Procedural(pge_core::Geometry::Box { size }) = &mut mesh.source {
        size[0] = segment_length;
    }
}

fn hide_world_line_segment(
    world: &mut pge_core::WorldState,
    index: &HashMap<String, PgeCoreArenaId<PgeCoreNode>>,
    entity: &str,
) {
    set_world_line_segment(
        world,
        index,
        entity,
        [0.0, 0.0, -10_000.0],
        [0.0, 0.0, -10_000.0],
    );
}

fn set_world_node_transform(
    world: &mut pge_core::WorldState,
    index: &HashMap<String, PgeCoreArenaId<PgeCoreNode>>,
    entity: &str,
    transform: PgeCoreTransform,
) {
    if let Some(node_id) = index.get(entity)
        && let Some(world_node) = world.nodes.get_mut(node_id)
    {
        world_node.transform = transform;
    }
}

fn set_world_camera_transform(
    world: &mut pge_core::WorldState,
    index: &HashMap<String, PgeCoreArenaId<PgeCoreNode>>,
    camera_entity: &str,
    transform: PreviewCameraTransform,
) {
    if let Some(node_id) = index.get(camera_entity)
        && let Some(node) = world.nodes.get_mut(node_id)
    {
        node.transform.translation = transform.translation;
        node.transform.rotation_matrix = Some(transform.rotation_matrix);
    }
}

fn set_world_camera_projection(
    world: &mut pge_core::WorldState,
    index: &HashMap<String, PgeCoreArenaId<PgeCoreNode>>,
    camera_entity: &str,
    fov_deg: f32,
    resolution: [u32; 2],
) {
    if let Some(node_id) = index.get(camera_entity)
        && let Some(camera_id) = world.nodes.get(node_id).and_then(|node| node.camera)
        && let Some(camera) = world.cameras.get_mut(&camera_id)
    {
        camera.fov_deg = fov_deg;
        camera.resolution = resolution;
    }
}

fn orbit_camera_transform(
    orbit_state: &PgeAppState,
    camera_node_id: pge_app::ArenaId<PgeAppNode>,
    orbit_controller: &OrbitController,
) -> PreviewCameraTransform {
    let eye = orbit_state
        .nodes
        .get(&camera_node_id)
        .map(|node| orbit_to_robotdreams_space(node.translation))
        .unwrap_or_else(|| orbit_to_robotdreams_space(orbit_controller.target));
    let target = orbit_to_robotdreams_space(orbit_controller.target);
    PreviewCameraTransform {
        translation: eye,
        rotation_matrix: look_at_matrix(eye, target, [0.0, 0.0, 1.0]),
    }
}

fn robotdreams_to_orbit_space(position: [f32; 3]) -> Vec3 {
    Vec3::new(position[0], position[2], position[1])
}

fn orbit_to_robotdreams_space(position: Vec3) -> [f32; 3] {
    [position.x, position.z, position.y]
}

fn look_at_matrix(eye: [f32; 3], target: [f32; 3], world_up: [f32; 3]) -> [[f32; 3]; 3] {
    let forward = normalize(sub(eye, target));
    let mut left = cross(world_up, forward);
    if length(left) < 1.0e-5 {
        left = [0.0, 1.0, 0.0];
    }
    left = normalize(left);
    let up = normalize(cross(forward, left));
    [
        [-forward[0], left[0], up[0]],
        [-forward[1], left[1], up[1]],
        [-forward[2], left[2], up[2]],
    ]
}

fn cross(left: [f32; 3], right: [f32; 3]) -> [f32; 3] {
    [
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    ]
}

fn sub(left: [f32; 3], right: [f32; 3]) -> [f32; 3] {
    [left[0] - right[0], left[1] - right[1], left[2] - right[2]]
}

fn normalize(vector: [f32; 3]) -> [f32; 3] {
    let len = length(vector).max(f32::EPSILON);
    [vector[0] / len, vector[1] / len, vector[2] / len]
}

fn length(vector: [f32; 3]) -> f32 {
    (vector[0] * vector[0] + vector[1] * vector[1] + vector[2] * vector[2]).sqrt()
}

fn scale_add(origin: [f32; 3], vector: [f32; 3], scale: f32) -> [f32; 3] {
    [
        origin[0] + vector[0] * scale,
        origin[1] + vector[1] * scale,
        origin[2] + vector[2] * scale,
    ]
}

fn line_rotation_matrix(delta: [f32; 3]) -> [[f32; 3]; 3] {
    let x_axis = normalize(delta);
    let reference = if x_axis[2].abs() > 0.95 {
        [0.0, 1.0, 0.0]
    } else {
        [0.0, 0.0, 1.0]
    };
    let y_axis = normalize(cross(reference, x_axis));
    let z_axis = normalize(cross(x_axis, y_axis));
    // PGE's `rotation_matrix` is a row-major representation of a matrix
    // whose columns are the transformed local axes.  Keep the box's local X
    // axis on the segment direction; returning the axes as rows transposes
    // the basis and makes arbitrary segments point along unrelated axes.
    [
        [x_axis[0], y_axis[0], z_axis[0]],
        [x_axis[1], y_axis[1], z_axis[1]],
        [x_axis[2], y_axis[2], z_axis[2]],
    ]
}

fn f64_vec3_to_f32(value: [f64; 3]) -> [f32; 3] {
    [value[0] as f32, value[1] as f32, value[2] as f32]
}

fn f64_matrix_to_f32(value: [[f64; 3]; 3]) -> [[f32; 3]; 3] {
    value.map(|row| row.map(|component| component as f32))
}

impl SerialBus for RobotDreamsSerialBus {
    type Error = RobotDreamsSerialBusError;

    fn write(&mut self, bytes: &[u8]) -> Result<usize, Self::Error> {
        let mut state = self
            .state
            .lock()
            .map_err(|_| RobotDreamsSerialBusError::Poisoned)?;
        let bus_id = state.bus_id.clone();
        let (response, event) = state
            .dreams
            .handle_virtual_bus_frame_with_event(&bus_id, bytes);
        if let Some(error) = event.error {
            log::warn!("RobotDreams virtual bus event failed: {error}");
        }
        let response = response.map_err(|_| RobotDreamsSerialBusError::Protocol)?;
        if let Some(response) = response {
            state.read_buf.extend(response);
        }
        Ok(bytes.len())
    }

    fn flush(&mut self) -> Result<(), Self::Error> {
        Ok(())
    }

    fn read_buffered(&mut self, bytes: &mut [u8]) -> Result<usize, Self::Error> {
        let mut state = self
            .state
            .lock()
            .map_err(|_| RobotDreamsSerialBusError::Poisoned)?;
        let len = bytes.len().min(state.read_buf.len());
        for byte in bytes.iter_mut().take(len) {
            *byte = state
                .read_buf
                .pop_front()
                .expect("read buffer length should match pop count");
        }
        Ok(len)
    }
}

impl DriveActuator for RobotDreamsDriveActuator {
    type Error = RobotDreamsSerialBusError;

    fn apply_drive_output(&mut self, output: DriveOutput) -> Result<(), Self::Error> {
        let mut state = self
            .state
            .lock()
            .map_err(|_| RobotDreamsSerialBusError::Poisoned)?;
        let drive_bus_id = state.drive_bus_id.clone();
        if state.dreams.set_virtual_drive_output(
            &drive_bus_id,
            ROBOT_ID,
            u32::from(output.left_motor_id),
            u32::from(output.right_motor_id),
            output.left_speed,
            output.right_speed,
            f64::from(output.steering_angle_deg),
            90.0,
        ) {
            Ok(())
        } else {
            Err(RobotDreamsSerialBusError::Protocol)
        }
    }
}

fn tick_for_joint_angle(joint: JointCalibration, angle_rad: f64) -> u16 {
    let sign = if joint.angle_sign < 0 { -1.0 } else { 1.0 };
    let tick = f64::from(joint.reference_tick)
        + sign * (angle_rad - joint.reference_angle_rad) * SERVO_FULL_ROTATION_TICKS
            / std::f64::consts::TAU;
    tick.round().rem_euclid(SERVO_FULL_ROTATION_TICKS) as u16
}

fn option_degrees(value_rad: Option<f64>) -> String {
    value_rad
        .map(|value| format!("{:.1}", value.to_degrees()))
        .unwrap_or_else(|| "NA".to_string())
}

fn option_i32(value: Option<i32>) -> String {
    value
        .map(|value| value.to_string())
        .unwrap_or_else(|| "NA".to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    use puppybot_core::stservo::mock::block_on_ready;

    #[test]
    fn wrist_camera_pose_and_projection_come_from_live_robotdreams_camera_spec() {
        let project_path = SimulatedRuntimeBackend::default_project_path();
        let project_json: serde_json::Value = serde_json::from_slice(
            &std::fs::read(&project_path).expect("read PuppyBot RobotDreams project"),
        )
        .expect("parse PuppyBot RobotDreams project");
        let authored_rotation = project_json["scene"]["cameras"]
            .as_array()
            .and_then(|cameras| {
                cameras
                    .iter()
                    .find(|camera| camera["id"] == WRIST_CAMERA_ID)
            })
            .and_then(|camera| camera["rotation"].as_array())
            .expect("wrist camera authored rotation");
        assert_eq!(
            authored_rotation,
            &vec![
                serde_json::json!(0.0),
                serde_json::json!(0.0),
                serde_json::json!(1.5707964),
            ],
            "wrist camera must retain the President-selected clockwise 90-degree local yaw"
        );

        let dreams = RobotDreams::open(project_path).expect("open PuppyBot RobotDreams project");
        let live_spec = dreams
            .camera_spec(WRIST_CAMERA_ID)
            .expect("wrist camera configured in RobotDreams project");
        let pose = project_camera_pose(&dreams, WRIST_CAMERA_ID)
            .expect("wrist camera has a valid world-space projection");
        assert_eq!(pose.transform.translation, live_spec.transform.translation);
        assert_eq!(
            pose.transform.rotation_matrix,
            live_spec
                .transform
                .rotation_matrix
                .expect("native camera rotation")
        );
        assert_eq!(pose.fov_deg, live_spec.fov_deg);
        assert_eq!(pose.resolution, live_spec.resolution);

        let mut options = RobotDreamsPgeFrameOptions::default();
        options.resolution = pose.resolution;
        let mut frame = robotdreams_pge_frame(&dreams, options);
        let index = index_world_nodes(&frame.world);
        let entity = format!("camera:{WRIST_CAMERA_ID}");
        frame.request.camera_id = Some(pge_core::EntityId(entity.clone()));
        set_world_camera_transform(&mut frame.world, &index, &entity, pose.transform);
        set_world_camera_projection(
            &mut frame.world,
            &index,
            &entity,
            pose.fov_deg,
            pose.resolution,
        );
        let node = frame
            .world
            .nodes
            .get(index.get(&entity).expect("wrist camera node indexed"))
            .expect("wrist camera node present");
        assert_eq!(node.transform.translation, pose.transform.translation);
        assert_eq!(
            node.transform.rotation_matrix,
            Some(pose.transform.rotation_matrix)
        );
        let camera = frame
            .world
            .cameras
            .get(&node.camera.expect("wrist camera component"))
            .expect("wrist camera projection");
        assert_eq!(camera.fov_deg, live_spec.fov_deg);
        assert_eq!(camera.resolution, live_spec.resolution);
    }

    #[test]
    fn tcp_camera_pov_uses_native_screen_basis_and_live_wrist_pose() {
        // Native camera columns are optical forward, image-left, image-up.
        // This is a +90° roll around optical forward: screen axes must rotate
        // with it rather than being hard-coded to world horizontal/world Z.
        let rolled = [[1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]];
        assert_eq!(
            camera_pov_world_direction(rolled, TcpCameraJogDirection::Forward).unwrap(),
            [1.0, 0.0, 0.0]
        );
        assert_eq!(
            camera_pov_world_direction(rolled, TcpCameraJogDirection::Left).unwrap(),
            [0.0, 0.0, 1.0]
        );
        assert_eq!(
            camera_pov_world_direction(rolled, TcpCameraJogDirection::Up).unwrap(),
            [0.0, -1.0, 0.0]
        );

        let backend = SimulatedRuntimeBackend::new(
            SimulatedRuntimeBackend::default_project_path(),
            &PuppybotConfigV1::default(),
        )
        .expect("open simulated runtime backend");
        let before = backend
            .wrist_camera_jog_direction(TcpCameraJogDirection::Up)
            .expect("sample live wrist-camera up");
        {
            let state = backend.state.lock().expect("simulation state");
            let camera = state
                .dreams
                .camera_spec(WRIST_CAMERA_ID)
                .expect("live wrist-camera spec");
            let expected_world = camera_pov_world_direction(
                camera
                    .transform
                    .rotation_matrix
                    .expect("native wrist-camera basis"),
                TcpCameraJogDirection::Up,
            )
            .expect("valid screen-up basis");
            let expected = normalize_direction(matrix_vector(
                simulation_frame_transforms(&state.dreams)
                    .expect("live arm-base frame")
                    .world_from_arm_base()
                    .inverse()
                    .rotation,
                expected_world,
            ))
            .expect("valid arm-base screen-up");
            assert_eq!(before, expected);
        }
    }

    #[test]
    fn tcp_camera_pov_world_direction_turns_with_rover_while_base_command_stays_local() {
        let backend = SimulatedRuntimeBackend::new(
            SimulatedRuntimeBackend::default_project_path(),
            &PuppybotConfigV1::default(),
        )
        .expect("open simulated runtime backend");
        let before_base = backend
            .wrist_camera_jog_direction(TcpCameraJogDirection::Up)
            .expect("sample wrist-camera screen up");
        let (before_up, after_up, after_world_from_arm_base) = {
            let mut state = backend.state.lock().expect("simulation state");
            let before = state
                .dreams
                .camera_spec(WRIST_CAMERA_ID)
                .expect("initial wrist camera")
                .transform
                .rotation_matrix
                .expect("initial native camera basis");
            assert!(state.dreams.set_virtual_drive_output(
                DRIVE_BUS_ID,
                ROBOT_ID,
                1,
                2,
                45,
                20,
                120.0,
                90.0,
            ));
            state.dreams.advance_seconds(1.0);
            let after = state
                .dreams
                .camera_spec(WRIST_CAMERA_ID)
                .expect("wrist camera after rover turn")
                .transform
                .rotation_matrix
                .expect("turned native camera basis");
            (
                [before[0][2], before[1][2], before[2][2]],
                [after[0][2], after[1][2], after[2][2]],
                simulation_frame_transforms(&state.dreams)
                    .expect("live arm-base frame after rover turn")
                    .world_from_arm_base(),
            )
        };
        let after_base = backend
            .wrist_camera_jog_direction(TcpCameraJogDirection::Up)
            .expect("resample wrist-camera screen up after rover turn");

        assert_ne!(
            before_up, after_up,
            "rover turn must rotate camera image-up in world"
        );
        // Both the camera and arm base are mounted to the rover, so the Base
        // command is intentionally camera-relative and remains local.  Its
        // world realization must nevertheless follow the turned image-up axis.
        let command_world = matrix_vector(after_world_from_arm_base.rotation, after_base);
        for axis in 0..3 {
            assert!(
                (command_world[axis] - f64::from(after_up[axis])).abs() < 1.0e-5,
                "world command axis {axis} must match rotated screen-up"
            );
        }
        assert!(
            before_base
                .iter()
                .zip(after_base)
                .all(|(before, after)| (before - after).abs() < 1.0e-5),
            "arm-base camera direction stays local while its world direction follows the rover"
        );
    }

    #[test]
    fn interactive_preview_opens_tcp_window_only_for_a_valid_wrist_camera() {
        let pose = ProjectCameraPose {
            transform: PreviewCameraTransform {
                translation: [0.1, 0.2, 0.3],
                rotation_matrix: [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
            },
            fov_deg: 70.0,
            resolution: [640, 480],
        };
        assert_eq!(
            interactive_preview_window_plan(Some(pose)),
            InteractivePreviewWindowPlan {
                open_tcp_camera: true,
                tcp_camera_resolution: [640, 480],
            }
        );
        assert_eq!(
            interactive_preview_window_plan(None),
            InteractivePreviewWindowPlan {
                open_tcp_camera: false,
                tcp_camera_resolution: RobotDreamsPgeFrameOptions::default().resolution,
            }
        );
    }

    #[test]
    fn simulation_ups_counter_samples_completed_updates_and_detects_stall() {
        let mut counter = SimulationUpsCounter::default();
        let started = Instant::now();
        assert_eq!(counter.displayed_at(started), None);

        counter.record_completion_at(started);
        assert_eq!(counter.displayed_at(started), None);
        for update in 1..=5 {
            counter.record_completion_at(started + StdDuration::from_millis(update * 200));
        }
        let ups = counter
            .displayed_at(started + StdDuration::from_secs(1))
            .expect("one-second UPS sample");
        assert!((ups - 5.0).abs() < f64::EPSILON);

        assert_eq!(
            counter.displayed_at(started + StdDuration::from_secs(3)),
            Some(0.0)
        );
        counter.record_completion_at(started + StdDuration::from_millis(3_100));
        assert_eq!(
            counter.displayed_at(started + StdDuration::from_millis(3_100)),
            None
        );
    }

    #[test]
    fn simulation_ups_label_distinguishes_startup_and_measured_rate() {
        assert_eq!(format_simulation_ups(None), "SIM -- UPS");
        assert_eq!(format_simulation_ups(Some(5.45)), "SIM 5.5 UPS");
        assert_eq!(format_simulation_ups(Some(0.0)), "SIM 0.0 UPS");
        assert_eq!(format_simulation_ups(Some(f64::NAN)), "SIM -- UPS");
    }

    #[test]
    fn default_screenshot_camera_frames_reachable_ball_and_bin_fixture() {
        let camera = ScreenshotCamera::default();
        assert_eq!(camera.target, [0.18, 0.0, 0.12]);
        assert_eq!(camera.radius_m, 0.42);
        assert_eq!(camera.azimuth_deg, -48.0);
        assert_eq!(camera.elevation_deg, 24.0);

        let transform = screenshot_camera_transform(camera);
        let azimuth_rad = camera.azimuth_deg.to_radians();
        let elevation_rad = camera.elevation_deg.to_radians();
        let horizontal_radius = camera.radius_m * elevation_rad.cos();
        let expected = [
            camera.target[0] + horizontal_radius * azimuth_rad.cos(),
            camera.target[1] + horizontal_radius * azimuth_rad.sin(),
            camera.target[2] + camera.radius_m * elevation_rad.sin(),
        ];
        for (actual, expected) in transform.translation.into_iter().zip(expected) {
            assert!((actual - expected).abs() < 1.0e-5, "{actual} != {expected}");
        }
    }

    #[test]
    fn cached_model_labels_match_robotdreams_state_and_identify_provenance() {
        let config = PuppybotConfigV1::default();
        let backend =
            SimulatedRuntimeBackend::new(SimulatedRuntimeBackend::default_project_path(), &config)
                .expect("open simulated runtime backend");
        let robot = Puppybot::new_with_config(&config, 0).expect("create PuppyBot controller");

        backend.update_labels(&robot);

        let state = backend.state.lock().expect("simulation state");
        let robot_state = state
            .dreams
            .robot_state(ROBOT_ID)
            .expect("PuppyBot model state");
        let telemetry = model_telemetry(&robot_state);
        let [x, y, z] = telemetry.tcp_world_m.expect("observed model TCP");
        assert_eq!(
            label_text(&state.labels, "model_tcp_observed"),
            format!("MODEL OBS TCP WORLD M X {x:.3} Y {y:.3} Z {z:.3}")
        );
        assert_eq!(
            label_text(&state.labels, "model_joints_observed"),
            format!(
                "MODEL URDF RAW Q DEG YAW {} SHOULDER {} ELBOW {} WRIST {}",
                option_degrees(telemetry.joint_angles_rad[0]),
                option_degrees(telemetry.joint_angles_rad[1]),
                option_degrees(telemetry.joint_angles_rad[2]),
                option_degrees(telemetry.joint_angles_rad[3]),
            )
        );
        assert!(telemetry.joint_angles_rad.iter().all(Option::is_some));
        assert!(label_text(&state.labels, "drive").starts_with("CTRL DRIVE"));
        for (index, semantic_name) in MODEL_JOINT_NAMES.iter().enumerate() {
            assert!(
                label_text(&state.labels, &format!("joint_{index}"))
                    .starts_with(&format!("CTRL {}", semantic_name.to_ascii_uppercase()))
            );
        }
    }

    #[test]
    fn cached_model_labels_follow_live_robotdreams_joint_and_tcp_updates() {
        let config = PuppybotConfigV1::default();
        let backend =
            SimulatedRuntimeBackend::new(SimulatedRuntimeBackend::default_project_path(), &config)
                .expect("open simulated runtime backend");
        let robot = Puppybot::new_with_config(&config, 0).expect("create PuppyBot controller");

        backend.update_labels(&robot);
        let initial_joint_label = cached_label_text(&backend, "model_joints_observed");
        let initial_tcp_label = cached_label_text(&backend, "model_tcp_observed");

        {
            let mut state = backend.state.lock().expect("simulation state");
            state
                .dreams
                .set_joint_angle("yaw", 0.42)
                .expect("update model yaw");
        }
        backend.update_labels(&robot);
        let updated_joint_label = cached_label_text(&backend, "model_joints_observed");
        assert_ne!(updated_joint_label, initial_joint_label);
        assert!(updated_joint_label.contains("YAW 24.1"));

        {
            let mut state = backend.state.lock().expect("simulation state");
            assert!(state.dreams.set_virtual_drive_output(
                DRIVE_BUS_ID,
                ROBOT_ID,
                1,
                2,
                45,
                20,
                120.0,
                90.0,
            ));
            state.dreams.advance_seconds(1.0);
        }
        backend.update_labels(&robot);
        assert_ne!(
            cached_label_text(&backend, "model_tcp_observed"),
            initial_tcp_label
        );
    }

    #[test]
    fn controller_arm_chain_uses_observed_joint_feedback_and_live_frame_transform() {
        let mut robot = Puppybot::new(0);
        let angles = [0.2, -0.1, 0.4, -0.3];
        for (joint, angle) in robot.arm.joints.iter_mut().zip(angles) {
            joint.has_feedback = true;
            joint.tick = Some(joint.reference_tick);
            joint.angle_rad = Some(angle);
        }
        let frames = SimulationFrameTransforms {
            world_from_base: RigidTransform::from_translation_rpy(
                [0.4, -0.2, 0.1],
                [0.0, 0.0, std::f64::consts::FRAC_PI_2],
            ),
            base_from_arm_base: RigidTransform::from_translation_rpy(
                [0.03, 0.01, 0.06],
                [0.0, 0.0, 0.0],
            ),
        };

        let chain = controller_arm_chain_world_m(&robot.arm_telemetry(), frames)
            .expect("observed controller arm chain");
        let expected = kinematics::arm_chain_points(angles[0], angles[1], angles[2], angles[3]);
        assert_eq!(
            chain.points_world_m[4],
            f64_vec3_to_f32(
                frames
                    .world_from_arm_base()
                    .transform_point(expected.tcp.map(|value| value * 0.001))
            )
        );

        robot.arm.joints[2].has_feedback = false;
        assert_eq!(
            controller_arm_chain_world_m(&robot.arm_telemetry(), frames),
            None
        );
    }

    #[test]
    fn configured_reference_ticks_report_ninety_and_model_mapping_matches_wrap_edges() {
        let config_path = Path::new(env!("CARGO_MANIFEST_DIR")).join("puppybot.json");
        let config = crate::config::load_runtime_config(&config_path)
            .expect("load PuppyBot runtime config")
            .expect("PuppyBot runtime config exists");
        assert_eq!(
            config.arm.joints.map(|joint| joint.reference_tick),
            [1583, 2946, 1058, 2685]
        );
        for joint in config.arm.joints {
            assert!((joint.reference_angle_rad.to_degrees() - 90.0).abs() < 1.0e-9);
        }

        let project_path = SimulatedRuntimeBackend::default_project_path();
        let profile_path =
            Path::new(env!("CARGO_MANIFEST_DIR")).join("../../models/puppybot/robotdreams.json");
        let profile: serde_json::Value = serde_json::from_str(
            &fs::read_to_string(profile_path).expect("read PuppyBot model profile"),
        )
        .expect("parse PuppyBot model profile");
        let analytic_scales: [f64; JOINT_COUNT] = core::array::from_fn(|index| {
            profile["analyticToUrdf"]["joints"][MODEL_JOINT_NAMES[index]]["scale"]
                .as_f64()
                .expect("analytic-to-URDF scale")
        });
        let analytic_offsets: [f64; JOINT_COUNT] = core::array::from_fn(|index| {
            profile["analyticToUrdf"]["joints"][MODEL_JOINT_NAMES[index]]["offset"]
                .as_f64()
                .expect("analytic-to-URDF offset")
        });
        let mut backend = SimulatedRuntimeBackend::new(&project_path, &config)
            .expect("open mapped simulation backend");
        let mut robot =
            Puppybot::new_with_config(&config, 0).expect("create physical-calibration controller");

        let verify_pose =
            |state: &RobotDreamsRuntimeState, robot: &Puppybot, ticks: [i32; JOINT_COUNT]| {
                let model = model_telemetry(
                    &state
                        .dreams
                        .robot_state(ROBOT_ID)
                        .expect("RobotDreams model state"),
                );
                for index in 0..JOINT_COUNT {
                    let joint = robot.arm.joints[index];
                    let controller_angle = joint.tick_to_angle(ticks[index]);
                    let expected_q =
                        analytic_scales[index] * controller_angle + analytic_offsets[index];
                    let actual_q = model.joint_angles_rad[index].expect("model joint angle");
                    let delta = (actual_q - expected_q + std::f64::consts::PI)
                        .rem_euclid(std::f64::consts::TAU)
                        - std::f64::consts::PI;
                    assert!(
                        delta.abs() <= std::f64::consts::TAU / 8192.0,
                        "{} tick {} controller={} expected_q={} actual_q={} delta={delta}",
                        MODEL_JOINT_NAMES[index],
                        ticks[index],
                        controller_angle.to_degrees(),
                        expected_q.to_degrees(),
                        actual_q.to_degrees(),
                    );
                }
            };

        {
            let mut state = backend.state.lock().expect("simulation state");
            state.dreams.advance_seconds(3.0);
            verify_pose(
                &state,
                &robot,
                config.arm.joints.map(|joint| joint.reference_tick),
            );
        }
        for tick in 1..=8 {
            block_on_ready(backend.run_once(&mut robot, tick * 20));
        }
        for (telemetry, calibration) in robot
            .arm_telemetry()
            .joints
            .into_iter()
            .zip(config.arm.joints)
        {
            assert!(telemetry.has_feedback, "live servo feedback is present");
            assert_eq!(telemetry.tick, Some(calibration.reference_tick));
            assert!(
                (telemetry.angle_deg().expect("configured controller angle") - 90.0).abs() < 1.0e-9
            );
        }

        let asymmetric_ticks = [0, 4095, 17, 4095];
        {
            let mut state = backend.state.lock().expect("simulation state");
            for (joint, tick) in config.arm.joints.iter().zip(asymmetric_ticks) {
                assert!(state.dreams.set_virtual_servo_target(
                    SERVO_MAIN_BUS_ID,
                    joint.servo_id,
                    tick as i16,
                ));
            }
            state.dreams.advance_seconds(3.0);
            verify_pose(&state, &robot, asymmetric_ticks);
        }
    }

    #[test]
    fn runtime_config_controller_tcp_matches_robotdreams_tcp_at_live_feedback_pose() {
        let config_path = Path::new(env!("CARGO_MANIFEST_DIR")).join("puppybot.json");
        let config = crate::config::load_runtime_config(&config_path)
            .expect("load PuppyBot runtime config")
            .expect("PuppyBot runtime config exists");
        let backend =
            SimulatedRuntimeBackend::new(SimulatedRuntimeBackend::default_project_path(), &config)
                .expect("open simulated runtime backend");
        let mut robot =
            Puppybot::new_with_config(&config, 0).expect("create PuppyBot controller from config");
        // This asymmetric, live-feedback pose is deliberately close to the
        // simulation screenshot: it exercises every joint calibration and
        // makes a wrist-versus-TCP mix-up visible.
        let feedback_ticks = [3000, 2989, 3000, 3418];
        for (joint, tick) in robot.arm.joints.iter_mut().zip(feedback_ticks) {
            joint.has_feedback = true;
            joint.tick = Some(tick);
            joint.angle_rad = Some(joint.tick_to_angle(tick));
        }

        let (controller_chain, model_telemetry) = {
            let mut state = backend.state.lock().expect("simulation state");
            for (joint, tick) in config.arm.joints.iter().zip(feedback_ticks) {
                assert!(state.dreams.set_virtual_servo_target(
                    SERVO_MAIN_BUS_ID,
                    joint.servo_id,
                    tick as i16,
                ));
            }
            state.dreams.advance_seconds(3.0);
            let frames = simulation_frame_transforms(&state.dreams)
                .expect("RobotDreams resolves PuppyBot arm base frame");
            let model_telemetry = model_telemetry(
                &state
                    .dreams
                    .robot_state(ROBOT_ID)
                    .expect("RobotDreams reports PuppyBot model state"),
            );
            (
                controller_arm_chain_world_m(&robot.arm_telemetry(), frames)
                    .expect("controller chain uses complete feedback"),
                model_telemetry,
            )
        };

        let delta_mm =
            controller_tcp_model_delta_mm(Some(&controller_chain), Some(&model_telemetry))
                .expect("both controller and model TCP positions");
        assert!(
            delta_mm <= TCP_ALIGNMENT_TOLERANCE_MM,
            "controller FK TCP must coincide with the cyan RobotDreams TCP: \
             controller={:?} model={:?} delta_mm={delta_mm:.3}",
            controller_chain.points_world_m[4],
            model_telemetry.tcp_world_m,
        );
    }

    #[test]
    fn live_runtime_cached_chain_matches_preview_tcp_marker() {
        let config_path = Path::new(env!("CARGO_MANIFEST_DIR")).join("puppybot.json");
        let config = crate::config::load_runtime_config(&config_path)
            .expect("load PuppyBot runtime config")
            .expect("PuppyBot runtime config exists");
        let mut backend =
            SimulatedRuntimeBackend::new(SimulatedRuntimeBackend::default_project_path(), &config)
                .expect("open simulated runtime backend");
        let mut robot =
            Puppybot::new_with_config(&config, 0).expect("create PuppyBot controller from config");

        for tick in 1..=8 {
            block_on_ready(backend.run_once(&mut robot, tick * 20));
        }

        let snapshot = backend
            .published_preview
            .lock()
            .expect("preview snapshot")
            .snapshot
            .as_ref()
            .clone();
        let chain = snapshot
            .controller_arm_chain
            .expect("cached controller chain");
        let wrist_to_tcp = [
            chain.points_world_m[4][0] - chain.points_world_m[3][0],
            chain.points_world_m[4][1] - chain.points_world_m[3][1],
            chain.points_world_m[4][2] - chain.points_world_m[3][2],
        ];
        let wrist_to_tcp_horizontal_m = f32::hypot(wrist_to_tcp[0], wrist_to_tcp[1]);
        assert!(
            wrist_to_tcp_horizontal_m <= 0.005 && wrist_to_tcp[2] <= -0.035,
            "the default live feedback pose must put TCP downward beneath the wrist: \
             wrist={:?} tcp={:?} wrist_to_tcp={wrist_to_tcp:?}",
            chain.points_world_m[3],
            chain.points_world_m[4],
        );
        let marker = snapshot
            .debug_markers
            .into_iter()
            .find(|marker| marker.robot_id == ROBOT_ID)
            .expect("PuppyBot coordinate marker");
        let marker_tcp = marker.current_tcp.expect("cyan current TCP marker");
        let delta_mm = chain.points_world_m[4]
            .into_iter()
            .zip(marker_tcp)
            .map(|(controller, model)| f64::from(controller - model).powi(2))
            .sum::<f64>()
            .sqrt()
            * 1_000.0;
        assert!(
            delta_mm <= TCP_ALIGNMENT_TOLERANCE_MM,
            "live run cached controller FK TCP must match the RobotDreams cyan TCP marker: \
             controller={:?} marker={marker_tcp:?} delta_mm={delta_mm:.3}",
            chain.points_world_m[4],
        );

        let mut world = pge_core::WorldState::new();
        world
            .nodes
            .insert(pge_core::Node::new("debug:puppybot:tcp:current"));
        insert_controller_arm_overlay(&mut world);
        let index = index_world_nodes(&world);
        sync_tcp_debug_markers(&mut world, &[marker], &index);
        sync_controller_arm_overlay(&mut world, Some(&chain), &index);
        assert_eq!(
            marker_translation(&world, &index, "debug:puppybot:tcp:current"),
            marker_tcp
        );
        assert_eq!(
            marker_translation(&world, &index, "debug:puppybot:controller_arm:point:tcp",),
            chain.points_world_m[4]
        );

        let (frame, rendered_delta_mm) = backend
            .preview()
            .offscreen_frame(ScreenshotCamera::default())
            .expect("build the exact offscreen frame used by screenshot captures");
        assert!(
            rendered_delta_mm <= TCP_ALIGNMENT_TOLERANCE_MM,
            "rendered controller and model TCP must remain aligned: {rendered_delta_mm:.3} mm"
        );
        let rendered_index = index_world_nodes(&frame.world);
        let current_tcp_entity = "debug:puppybot:tcp:current";
        let controller_tcp_entity = "debug:puppybot:controller_arm:point:tcp";
        let rendered_tcp_delta_mm =
            marker_translation(&frame.world, &rendered_index, current_tcp_entity)
                .into_iter()
                .zip(marker_translation(
                    &frame.world,
                    &rendered_index,
                    controller_tcp_entity,
                ))
                .map(|(model, controller)| f64::from(model - controller).powi(2))
                .sum::<f64>()
                .sqrt()
                * 1_000.0;
        assert!(
            rendered_tcp_delta_mm <= TCP_ALIGNMENT_TOLERANCE_MM,
            "cyan marker center and magenta TCP must be concentric in the captured world: \
             {rendered_tcp_delta_mm:.3} mm"
        );
        assert_eq!(
            sphere_radius(&frame.world, &rendered_index, current_tcp_entity),
            PUPPYBOT_CURRENT_TCP_MARKER_RADIUS_M
        );
        assert_eq!(
            sphere_radius(&frame.world, &rendered_index, controller_tcp_entity),
            CONTROLLER_ARM_POINT_RADIUS_M
        );
        assert!(
            sphere_radius(&frame.world, &rendered_index, current_tcp_entity)
                < sphere_radius(&frame.world, &rendered_index, controller_tcp_entity),
            "the cyan marker must be smaller so the concentric magenta TCP remains visible"
        );
    }

    #[test]
    fn preview_snapshot_is_readable_while_robotdreams_state_is_locked() {
        let config = PuppybotConfigV1::default();
        let backend =
            SimulatedRuntimeBackend::new(SimulatedRuntimeBackend::default_project_path(), &config)
                .expect("open simulated runtime backend");

        // The preview must consume this independent snapshot rather than
        // waiting for a virtual-servo transaction or RobotDreams physics step
        // that owns the mutable simulation state.
        let _simulation_update = backend.state.lock().expect("simulation state");
        let snapshot = backend
            .published_preview
            .try_lock()
            .expect("preview snapshot must not share the simulation lock");
        assert!(!snapshot.snapshot.visual_transforms.is_empty());
        assert!(
            snapshot
                .snapshot
                .debug_markers
                .iter()
                .any(|marker| marker.robot_id == ROBOT_ID)
        );
    }

    #[test]
    fn controller_tcp_alignment_label_reports_delta_or_missing_data() {
        let controller = ControllerArmChain {
            points_world_m: [
                [0.0, 0.0, 0.0],
                [0.0, 0.0, 0.0],
                [0.0, 0.0, 0.0],
                [0.0, 0.0, 0.0],
                [0.1, -0.2, 0.3],
            ],
        };
        let model = ModelTelemetry {
            tcp_world_m: Some([0.101, -0.2, 0.3]),
            joint_angles_rad: [None; 4],
        };
        let mut labels = Vec::new();
        push_controller_tcp_alignment_label(&mut labels, Some(&controller), Some(&model));
        assert_eq!(
            label_text(&labels, "controller_tcp_model_delta"),
            "CTRL FK TCP DELTA TO MODEL MM 1.0 (ALIGNED <= 2.0)"
        );

        let mismatched_model = ModelTelemetry {
            tcp_world_m: Some([0.104, -0.2, 0.3]),
            joint_angles_rad: [None; 4],
        };
        labels.clear();
        push_controller_tcp_alignment_label(
            &mut labels,
            Some(&controller),
            Some(&mismatched_model),
        );
        assert_eq!(
            label_text(&labels, "controller_tcp_model_delta"),
            "CTRL FK TCP DELTA TO MODEL MM 4.0 (MISMATCH > 2.0)"
        );

        labels.clear();
        push_controller_tcp_alignment_label(&mut labels, None, Some(&model));
        assert_eq!(
            label_text(&labels, "controller_tcp_model_delta"),
            "CTRL FK TCP DELTA TO MODEL MM NA"
        );
    }

    #[test]
    fn controller_arm_overlay_updates_segments_and_stays_distinct_from_model_tcp() {
        let mut world = pge_core::WorldState::new();
        world
            .nodes
            .insert(pge_core::Node::new("debug:puppybot:tcp:current"));
        insert_controller_arm_overlay(&mut world);
        let index = index_world_nodes(&world);
        let controller_tcp = "debug:puppybot:controller_arm:point:tcp";
        let shoulder_segment = "debug:puppybot:controller_arm:segment:yaw_shoulder";
        assert!(index.contains_key("debug:puppybot:tcp:current"));
        assert!(index.contains_key(controller_tcp));

        let first = ControllerArmChain {
            points_world_m: [
                [0.0, 0.0, 0.1],
                [0.0, 0.0, 0.2],
                [0.1, 0.0, 0.2],
                [0.2, 0.0, 0.2],
                [0.25, 0.0, 0.2],
            ],
        };
        sync_controller_arm_overlay(&mut world, Some(&first), &index);
        assert_eq!(
            marker_translation(&world, &index, controller_tcp),
            first.points_world_m[4]
        );
        assert!((line_length(&world, &index, shoulder_segment) - 0.1).abs() < 1.0e-6);

        let second = ControllerArmChain {
            points_world_m: [
                [0.3, 0.1, 0.1],
                [0.3, 0.3, 0.1],
                [0.4, 0.3, 0.1],
                [0.5, 0.3, 0.1],
                [0.55, 0.3, 0.1],
            ],
        };
        sync_controller_arm_overlay(&mut world, Some(&second), &index);
        assert_eq!(
            marker_translation(&world, &index, controller_tcp),
            second.points_world_m[4]
        );
        assert!((line_length(&world, &index, shoulder_segment) - 0.2).abs() < 1.0e-6);

        sync_controller_arm_overlay(&mut world, None, &index);
        assert_eq!(
            marker_translation(&world, &index, controller_tcp),
            [0.0, 0.0, -10_000.0]
        );
    }

    #[test]
    fn controller_arm_segment_basis_points_local_x_along_segment() {
        let mut world = pge_core::WorldState::new();
        insert_controller_arm_overlay(&mut world);
        let index = index_world_nodes(&world);
        let entity = "debug:puppybot:controller_arm:segment:shoulder_elbow";
        let start = [0.1, -0.2, 0.3];
        let end = [0.4, 0.2, 0.8];
        set_world_line_segment(&mut world, &index, entity, start, end);

        let node = world
            .nodes
            .get(index.get(entity).expect("segment node indexed"))
            .expect("segment node present");
        let matrix = node
            .transform
            .rotation_matrix
            .expect("segment has rotation basis");
        let direction = normalize(sub(end, start));
        // PGE consumes the first matrix column as the transformed local X axis.
        assert_eq!([matrix[0][0], matrix[1][0], matrix[2][0]], direction);
    }

    #[test]
    fn runtime_debug_target_marker_uses_full_arm_base_point_transform() {
        let mut markers = vec![CoordinateDebugMarkerPositions {
            robot_id: "puppybot".to_string(),
            floor_z: 0.004,
            current_tcp: Some([1.0, 2.0, 3.0]),
            target_tcp: Some([9.0, 9.0, 9.0]),
        }];

        override_debug_markers_with_puppybot_tcp(
            &mut markers,
            Some((100.0, 200.0, 300.0)),
            Some(SimulationFrameTransforms {
                world_from_base: RigidTransform::from_translation_rpy(
                    [1.0, 2.0, 3.0],
                    [0.0, 0.0, std::f64::consts::FRAC_PI_2],
                ),
                base_from_arm_base: RigidTransform::from_translation_rpy(
                    [0.1, 0.2, 0.3],
                    [0.0, 0.0, 0.0],
                ),
            }),
        );

        let target = markers[0].target_tcp.expect("target tcp");
        assert!((target[0] - 0.6).abs() < 1.0e-5);
        assert!((target[1] - 2.2).abs() < 1.0e-5);
        assert!((target[2] - 3.6).abs() < 1.0e-5);
        assert_eq!(markers[0].current_tcp, Some([1.0, 2.0, 3.0]));
    }

    #[test]
    fn runtime_debug_target_marker_clears_target_without_puppybot_target() {
        let mut markers = vec![CoordinateDebugMarkerPositions {
            robot_id: "puppybot".to_string(),
            floor_z: 0.004,
            current_tcp: Some([1.0, 2.0, 3.0]),
            target_tcp: Some([9.0, 9.0, 9.0]),
        }];

        override_debug_markers_with_puppybot_tcp(
            &mut markers,
            None,
            Some(SimulationFrameTransforms {
                world_from_base: RigidTransform::identity(),
                base_from_arm_base: RigidTransform::identity(),
            }),
        );

        assert_eq!(markers[0].target_tcp, None);
    }

    #[test]
    fn runtime_debug_target_marker_requires_resolved_frames() {
        let mut markers = vec![CoordinateDebugMarkerPositions {
            robot_id: "puppybot".to_string(),
            floor_z: 0.004,
            current_tcp: Some([1.0, 2.0, 3.0]),
            target_tcp: Some([9.0, 9.0, 9.0]),
        }];

        override_debug_markers_with_puppybot_tcp(&mut markers, Some((150.0, 200.0, 300.0)), None);

        assert_eq!(markers[0].target_tcp, None);
    }

    #[test]
    fn cached_preview_frame_roots_follow_resolved_world_transforms() {
        let mut world = pge_core::WorldState::new();
        world
            .nodes
            .insert(pge_core::Node::new("debug:puppybot:frame:base"));
        world
            .nodes
            .insert(pge_core::Node::new("debug:puppybot:frame:armBase"));
        let index = index_world_nodes(&world);
        let frames = SimulationFrameTransforms {
            world_from_base: RigidTransform::from_translation_rpy(
                [0.4, -0.2, 0.1],
                [0.0, 0.0, 0.7],
            ),
            base_from_arm_base: RigidTransform::from_translation_rpy(
                [0.03, -0.01, 0.06],
                [0.0, 0.0, 0.12],
            ),
        };

        sync_debug_frame_roots(&mut world, frames, &index);

        assert_eq!(
            marker_translation(&world, &index, "debug:puppybot:frame:base"),
            f64_vec3_to_f32(frames.world_from_base.translation_m)
        );
        assert_eq!(
            marker_translation(&world, &index, "debug:puppybot:frame:armBase"),
            f64_vec3_to_f32(frames.world_from_arm_base().translation_m)
        );
        let arm_node = world
            .nodes
            .get(
                index
                    .get("debug:puppybot:frame:armBase")
                    .expect("arm frame indexed"),
            )
            .expect("arm frame node");
        assert_eq!(
            arm_node.transform.rotation_matrix,
            Some(f64_matrix_to_f32(frames.world_from_arm_base().rotation))
        );
    }

    #[test]
    fn live_robotdreams_frames_drive_runtime_marker_and_pge_sync() {
        let mut dreams = RobotDreams::open(SimulatedRuntimeBackend::default_project_path())
            .expect("open PuppyBot RobotDreams project");
        assert!(
            dreams.set_virtual_drive_output(DRIVE_BUS_ID, ROBOT_ID, 1, 2, 45, 20, 120.0, 90.0,)
        );
        dreams.advance_seconds(1.0);
        let frames = simulation_frame_transforms(&dreams).expect("resolved simulation frames");
        assert!(
            frames.world_from_base.translation_m[0].hypot(frames.world_from_base.translation_m[1])
                > 0.001,
            "live rover transform must include translation"
        );
        let base_yaw = dreams
            .robot_state(ROBOT_ID)
            .and_then(|robot| robot.base.rotation)
            .expect("live rover base rotation")[2];
        assert!(
            base_yaw.abs() > 0.001,
            "live rover transform must include yaw"
        );

        let mut markers = dreams.coordinate_debug_marker_positions(
            robotdreams_core::CoordinateDebugOverlayOptions::default(),
        );
        let current_before = markers
            .iter()
            .find(|marker| marker.robot_id == ROBOT_ID)
            .and_then(|marker| marker.current_tcp)
            .expect("cyan URDF TCP");
        let target_arm_mm = (100.0, -20.0, 50.0);
        override_debug_markers_with_puppybot_tcp(&mut markers, Some(target_arm_mm), Some(frames));
        let marker = markers
            .iter()
            .find(|marker| marker.robot_id == ROBOT_ID)
            .expect("PuppyBot marker");
        assert_eq!(marker.current_tcp, Some(current_before));
        let expected_target = f64_vec3_to_f32(frames.world_from_arm_base().transform_point([
            f64::from(target_arm_mm.0) * 0.001,
            f64::from(target_arm_mm.1) * 0.001,
            f64::from(target_arm_mm.2) * 0.001,
        ]));
        assert_eq!(marker.target_tcp, Some(expected_target));

        let mut world = pge_core::WorldState::new();
        for entity in [
            "debug:puppybot:frame:base",
            "debug:puppybot:frame:armBase",
            "debug:puppybot:tcp:current",
            "debug:puppybot:tcp:target",
        ] {
            world.nodes.insert(pge_core::Node::new(entity));
        }
        let index = index_world_nodes(&world);
        sync_debug_frame_roots(&mut world, frames, &index);
        sync_tcp_debug_markers(&mut world, &markers, &index);

        assert_eq!(
            marker_translation(&world, &index, "debug:puppybot:frame:base"),
            f64_vec3_to_f32(frames.world_from_base.translation_m)
        );
        assert_eq!(
            marker_translation(&world, &index, "debug:puppybot:frame:armBase"),
            f64_vec3_to_f32(frames.world_from_arm_base().translation_m)
        );
        assert_eq!(
            marker_translation(&world, &index, "debug:puppybot:tcp:current"),
            current_before
        );
        assert_eq!(
            marker_translation(&world, &index, "debug:puppybot:tcp:target"),
            expected_target
        );
    }

    #[test]
    fn cached_preview_tcp_debug_markers_move_with_robotdreams_state() {
        let mut world = pge_core::WorldState::new();
        world
            .nodes
            .insert(pge_core::Node::new("debug:puppybot:tcp:current"));
        world
            .nodes
            .insert(pge_core::Node::new("debug:puppybot:tcp:current:floor"));
        world
            .nodes
            .insert(pge_core::Node::new("debug:puppybot:tcp:target"));
        world
            .nodes
            .insert(pge_core::Node::new("debug:puppybot:tcp:target:floor"));
        let delta_mesh = world.meshes.insert(pge_core::Mesh {
            name: Some("delta".to_string()),
            source: pge_core::MeshSource::Procedural(pge_core::Geometry::Box {
                size: [0.001, 0.004, 0.004],
            }),
            material: None,
        });
        let delta_node = world
            .nodes
            .insert(pge_core::Node::new("debug:puppybot:tcp:delta"));
        world
            .nodes
            .get_mut(&delta_node)
            .expect("delta node exists")
            .mesh = Some(delta_mesh);
        let index = index_world_nodes(&world);

        sync_tcp_debug_markers(
            &mut world,
            &[CoordinateDebugMarkerPositions {
                robot_id: "puppybot".to_string(),
                floor_z: 0.024,
                current_tcp: Some([0.1, 0.2, 0.3]),
                target_tcp: Some([0.4, 0.2, 0.5]),
            }],
            &index,
        );

        assert_eq!(
            marker_translation(&world, &index, "debug:puppybot:tcp:current"),
            [0.1, 0.2, 0.3]
        );
        assert_eq!(
            marker_translation(&world, &index, "debug:puppybot:tcp:current:floor"),
            [0.1, 0.2, 0.024]
        );
        assert_eq!(
            marker_translation(&world, &index, "debug:puppybot:tcp:target"),
            [0.4, 0.2, 0.5]
        );
        assert_eq!(
            marker_translation(&world, &index, "debug:puppybot:tcp:target:floor"),
            [0.4, 0.2, 0.024]
        );
        assert!((delta_line_length(&world, &index) - 0.36055514).abs() < 1.0e-5);

        sync_tcp_debug_markers(
            &mut world,
            &[CoordinateDebugMarkerPositions {
                robot_id: "puppybot".to_string(),
                floor_z: 0.024,
                current_tcp: Some([-0.2, 0.0, 0.1]),
                target_tcp: Some([-0.1, 0.0, 0.15]),
            }],
            &index,
        );

        assert_eq!(
            marker_translation(&world, &index, "debug:puppybot:tcp:current"),
            [-0.2, 0.0, 0.1]
        );
        assert_eq!(
            marker_translation(&world, &index, "debug:puppybot:tcp:target"),
            [-0.1, 0.0, 0.15]
        );
        assert!((delta_line_length(&world, &index) - 0.1118034).abs() < 1.0e-5);

        sync_tcp_debug_markers(
            &mut world,
            &[CoordinateDebugMarkerPositions {
                robot_id: "puppybot".to_string(),
                floor_z: 0.024,
                current_tcp: Some([-0.2, 0.0, 0.1]),
                target_tcp: None,
            }],
            &index,
        );

        assert_eq!(
            marker_translation(&world, &index, "debug:puppybot:tcp:target"),
            [0.0, 0.0, -10_000.0]
        );
        assert_eq!(
            marker_translation(&world, &index, "debug:puppybot:tcp:target:floor"),
            [0.0, 0.0, -10_000.0]
        );
        assert!((delta_line_length(&world, &index) - 0.001).abs() < 1.0e-6);
    }

    fn marker_translation(
        world: &pge_core::WorldState,
        index: &HashMap<String, PgeCoreArenaId<PgeCoreNode>>,
        entity: &str,
    ) -> [f32; 3] {
        world
            .nodes
            .get(index.get(entity).expect("marker node indexed"))
            .expect("marker node present")
            .transform
            .translation
    }

    fn sphere_radius(
        world: &pge_core::WorldState,
        index: &HashMap<String, PgeCoreArenaId<PgeCoreNode>>,
        entity: &str,
    ) -> f32 {
        let node = world
            .nodes
            .get(index.get(entity).expect("sphere node indexed"))
            .expect("sphere node present");
        let mesh = world
            .meshes
            .get(&node.mesh.expect("sphere node has mesh"))
            .expect("sphere mesh present");
        match &mesh.source {
            pge_core::MeshSource::Procedural(pge_core::Geometry::Sphere { radius, .. }) => *radius,
            _ => panic!("marker should be a sphere"),
        }
    }

    #[test]
    fn capture_state_and_trace_round_trip_exact_float_bits_and_per_frame_camera() {
        let config = PuppybotConfigV1::default();
        let backend =
            SimulatedRuntimeBackend::new(SimulatedRuntimeBackend::default_project_path(), &config)
                .expect("simulated backend");
        let first = backend.preview().capture_state().expect("capture state");
        let encoded = serde_json::to_vec(first.as_ref()).expect("encode capture state");
        let decoded: CaptureStateV1 =
            serde_json::from_slice(&encoded).expect("decode capture state");
        assert_eq!(decoded.schema, CAPTURE_STATE_SCHEMA);
        assert_eq!(
            decoded.camera.eye_m[0].to_bits(),
            first.camera.eye_m[0].to_bits()
        );
        assert!(!decoded.exact_visual_replay);
        assert!(decoded.exact_saved_transforms);
        assert!(!decoded.exact_dynamic_continuation);

        let mut second = first.as_ref().clone();
        second.camera.eye_m[0] += 0.125;
        second.frames[0].sequence += 1;
        second.frames[0].simulation_clock_sec += 0.02;
        let trace =
            capture_trace_from_states(&[first, Arc::new(second)], 50).expect("capture trace");
        let encoded = serde_json::to_vec(&trace).expect("encode capture trace");
        let decoded: CaptureTraceV1 = serde_json::from_slice(&encoded).expect("decode trace");
        assert_eq!(decoded.schema, CAPTURE_TRACE_SCHEMA);
        assert_eq!(decoded.frames.len(), 2);
        assert_ne!(
            decoded.frames[0].camera.eye_m,
            decoded.frames[1].camera.eye_m
        );
        assert!(
            decoded.frames[0].frame.simulation_clock_sec
                < decoded.frames[1].frame.simulation_clock_sec
        );
        let mut mixed_resolution = decoded.clone();
        mixed_resolution.frames[1].camera.resolution = [640, 480];
        assert!(
            validate_capture_trace(&mixed_resolution)
                .expect_err("mixed resolution must fail")
                .contains("fixed recording resolution")
        );
        let mut invalid = decoded.clone();
        invalid.fps = 51;
        assert!(validate_capture_trace(&invalid).is_err());
        invalid = decoded.clone();
        invalid.frames[0].camera.projection = "orthographic".to_string();
        assert!(validate_capture_trace(&invalid).is_err());
        invalid = decoded.clone();
        invalid.frames[0].camera.resolution = [0, 540];
        assert!(validate_capture_trace(&invalid).is_err());
        invalid = decoded;
        while invalid.frames.len() <= MAX_CAPTURE_TRACE_FRAMES {
            let mut frame = invalid.frames[0].clone();
            frame.frame_index = invalid.frames.len() as u32;
            invalid.frames.push(frame);
        }
        assert!(validate_capture_trace(&invalid).is_err());
    }

    #[test]
    fn stable_capture_gate_retries_warmup_and_rejects_inconsistent_readback() {
        let mut attempts = vec![
            Ok(vec![0_u8, 1, 2]),
            Ok(vec![3_u8, 4, 5]),
            Ok(vec![3_u8, 4, 5]),
        ]
        .into_iter();
        assert_eq!(
            render_stable_capture_png(|| attempts.next().expect("bounded render attempt"))
                .expect("second and third render stabilize"),
            vec![3_u8, 4, 5]
        );

        let mut inconsistent = vec![Ok(vec![0_u8]), Ok(vec![1_u8]), Ok(vec![2_u8])].into_iter();
        let error = render_stable_capture_png(|| {
            inconsistent.next().expect("bounded inconsistent attempt")
        })
        .expect_err("capture must fail closed when identical-state output never stabilizes");
        assert!(error.contains("did not stabilize after 3 identical-state renders"));
    }

    #[test]
    fn capture_replay_rejects_missing_and_unexpected_visual_transform_keys() {
        let config = PuppybotConfigV1::default();
        let backend =
            SimulatedRuntimeBackend::new(SimulatedRuntimeBackend::default_project_path(), &config)
                .expect("simulated backend");
        let state = backend.preview().capture_state().expect("capture state");
        let expected = state.frames[0]
            .visual_transforms
            .keys()
            .cloned()
            .collect::<BTreeSet<_>>();
        let mut missing = state.frames[0].clone();
        let removed = missing
            .visual_transforms
            .pop_first()
            .expect("at least one visual transform");
        let error =
            validate_visual_transform_keys(&missing, &expected).expect_err("missing key must fail");
        assert!(error.contains(&removed.0));

        let mut unexpected = state.frames[0].clone();
        unexpected.visual_transforms.insert(
            "robot:puppybot:visual:unexpected".to_string(),
            PgeCoreTransform::default(),
        );
        let error = validate_visual_transform_keys(&unexpected, &expected)
            .expect_err("unexpected key must fail");
        assert!(error.contains("unexpected"));
    }

    #[test]
    fn prepared_capture_base_hides_optional_dynamic_overlays() {
        let mut world = pge_core::WorldState::default();
        for entity in [
            "debug:puppybot:tcp:current",
            "debug:puppybot:tcp:current:floor",
            "debug:puppybot:tcp:target",
            "debug:puppybot:tcp:target:floor",
            "debug:puppybot:tcp:delta",
            "debug:puppybot:frame:base",
            "debug:puppybot:frame:armBase",
        ] {
            let mut node = pge_core::Node::new(entity);
            node.transform.translation = [1.0, 2.0, 3.0];
            world.nodes.insert(node);
        }
        insert_controller_arm_overlay(&mut world);
        let index = index_world_nodes(&world);
        hide_capture_dynamic_entities(&mut world, &index);
        for entity in [
            "debug:puppybot:tcp:current",
            "debug:puppybot:tcp:current:floor",
            "debug:puppybot:tcp:target",
            "debug:puppybot:tcp:target:floor",
            "debug:puppybot:frame:base",
            "debug:puppybot:frame:armBase",
        ] {
            assert_eq!(marker_translation(&world, &index, entity)[2], -10_000.0);
        }
        sync_tcp_debug_markers(
            &mut world,
            &[CoordinateDebugMarkerPositions {
                robot_id: ROBOT_ID.to_string(),
                floor_z: 0.0,
                current_tcp: None,
                target_tcp: None,
            }],
            &index,
        );
        assert_eq!(
            marker_translation(&world, &index, "debug:puppybot:tcp:current")[2],
            -10_000.0
        );
    }

    fn delta_line_length(
        world: &pge_core::WorldState,
        index: &HashMap<String, PgeCoreArenaId<PgeCoreNode>>,
    ) -> f32 {
        let node = world
            .nodes
            .get(
                index
                    .get("debug:puppybot:tcp:delta")
                    .expect("delta node indexed"),
            )
            .expect("delta node present");
        let mesh = world
            .meshes
            .get(&node.mesh.expect("delta node has mesh"))
            .expect("delta mesh present");
        match &mesh.source {
            pge_core::MeshSource::Procedural(pge_core::Geometry::Box { size }) => size[0],
            _ => panic!("delta mesh should be a box"),
        }
    }

    fn line_length(
        world: &pge_core::WorldState,
        index: &HashMap<String, PgeCoreArenaId<PgeCoreNode>>,
        entity: &str,
    ) -> f32 {
        let node = world
            .nodes
            .get(index.get(entity).expect("line node indexed"))
            .expect("line node present");
        let mesh = world
            .meshes
            .get(&node.mesh.expect("line node has mesh"))
            .expect("line mesh present");
        match &mesh.source {
            pge_core::MeshSource::Procedural(pge_core::Geometry::Box { size }) => size[0],
            _ => panic!("line mesh should be a box"),
        }
    }

    fn label_text<'a>(labels: &'a [RobotDreamsPgeTextLabel], id: &str) -> &'a str {
        labels
            .iter()
            .find(|label| label.id == id)
            .map(|label| label.text.as_str())
            .expect("cached label")
    }

    fn cached_label_text(backend: &SimulatedRuntimeBackend, id: &str) -> String {
        let state = backend.state.lock().expect("simulation state");
        label_text(&state.labels, id).to_string()
    }
}
