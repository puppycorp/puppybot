use std::{
    collections::{HashMap, VecDeque},
    path::{Path, PathBuf},
    sync::{Arc, Mutex},
};

use embassy_time::Duration;
use pge_app::{
    Node as PgeAppNode, OrbitController, State as PgeAppState, Vec2, Vec3, WindowRenderConfig,
    run_windowed,
};
use pge_core::{ArenaId as PgeCoreArenaId, Node as PgeCoreNode, Transform as PgeCoreTransform};
use puppybot_core::{
    config::{JointCalibration, PuppybotConfigV1},
    drive::{DriveActuator, DriveOutput},
    puppyarm::servo_safety::TICK_WRAP,
    robot::Puppybot,
    stservo::{SerialBus, StServo},
};
use robotdreams_core::{
    CoordinateDebugMarkerPositions, RigidTransform, RobotDreams, RobotDreamsPgeFrameOptions,
    RobotDreamsPgeTextLabel, coordinate_debug_legend_labels, robotdreams_pge_frame,
};

const SERVO_FULL_ROTATION_TICKS: f64 = TICK_WRAP as f64;
const SIMULATION_STEP_SECONDS: f32 = 0.02;
const SERVO_MAIN_BUS_ID: &str = "main_bus";
const DRIVE_BUS_ID: &str = "drive_bus";
const ROBOT_ID: &str = "puppybot";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum RobotDreamsSerialBusError {
    Protocol,
    Poisoned,
}

struct RobotDreamsRuntimeState {
    dreams: RobotDreams,
    bus_id: String,
    drive_bus_id: String,
    read_buf: VecDeque<u8>,
    labels: Vec<RobotDreamsPgeTextLabel>,
    puppybot_target_tcp_mm: Option<(f32, f32, f32)>,
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
    pub(crate) servo: StServo<RobotDreamsSerialBus>,
    pub(crate) drive_actuator: RobotDreamsDriveActuator,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub(crate) struct SimulationFrameTransforms {
    pub(crate) world_from_base: RigidTransform,
    pub(crate) base_from_arm_base: RigidTransform,
}

impl SimulationFrameTransforms {
    fn world_from_arm_base(self) -> RigidTransform {
        self.world_from_base.compose(self.base_from_arm_base)
    }
}

#[derive(Clone)]
pub(crate) struct SimulatedPreview {
    state: Arc<Mutex<RobotDreamsRuntimeState>>,
}

impl SimulatedRuntimeBackend {
    pub(crate) fn new(
        project_path: impl AsRef<Path>,
        config: &PuppybotConfigV1,
    ) -> Result<Self, String> {
        let project_path = project_path.as_ref();
        let mut dreams = RobotDreams::open(project_path)
            .map_err(|err| format!("open RobotDreams project {}: {err}", project_path.display()))?;
        for joint in config.arm.joints {
            let tick = tick_for_joint_angle(joint, joint.reference_angle_rad);
            if !dreams.set_virtual_servo_target(SERVO_MAIN_BUS_ID, joint.servo_id, tick as i16) {
                log::warn!(
                    "RobotDreams virtual servo {} was not initialized from PuppyBot config",
                    joint.servo_id
                );
            }
        }
        dreams.advance_seconds(1.0);

        let state = Arc::new(Mutex::new(RobotDreamsRuntimeState {
            dreams,
            bus_id: SERVO_MAIN_BUS_ID.to_string(),
            drive_bus_id: DRIVE_BUS_ID.to_string(),
            read_buf: VecDeque::new(),
            labels: Vec::new(),
            puppybot_target_tcp_mm: None,
        }));
        let bus = RobotDreamsSerialBus {
            state: Arc::clone(&state),
        };
        let drive_actuator = RobotDreamsDriveActuator {
            state: Arc::clone(&state),
        };

        Ok(Self {
            state,
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
        self.update_labels(robot);
        match self.state.lock() {
            Ok(mut state) => state.dreams.advance_seconds(SIMULATION_STEP_SECONDS),
            Err(_) => log::warn!("RobotDreams simulation state lock poisoned while advancing"),
        }
    }

    pub(crate) fn preview(&self) -> SimulatedPreview {
        SimulatedPreview {
            state: Arc::clone(&self.state),
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

    fn update_labels(&self, robot: &Puppybot) {
        let arm = robot.arm_telemetry();
        let drive = robot.drive_output();
        let mut labels = vec![
            RobotDreamsPgeTextLabel::overlay("title", "PUPPYBOT SIM", 0),
            RobotDreamsPgeTextLabel::overlay(
                "drive",
                format!(
                    "DRIVE L {} R {} STEER {} ACTIVE {}",
                    drive.left_speed, drive.right_speed, drive.steering_angle_deg, drive.active
                ),
                1,
            ),
        ];
        if let Some((x, y, z)) = arm.coords_mm {
            labels.push(RobotDreamsPgeTextLabel::overlay(
                "tcp_current",
                format!("TCP CUR {x:.1} {y:.1} {z:.1} MM"),
                2,
            ));
        }
        if let Some((x, y, z)) = arm.target_coords_mm {
            labels.push(RobotDreamsPgeTextLabel::overlay(
                "tcp_target",
                format!("TCP TGT {x:.1} {y:.1} {z:.1} MM"),
                3,
            ));
        }
        for (index, joint) in arm.joints.iter().enumerate() {
            labels.push(RobotDreamsPgeTextLabel::overlay(
                format!("joint_{index}"),
                format!(
                    "J{} ID {} TICK {} TGT {} ANG {}",
                    index + 1,
                    joint.servo_id,
                    option_i32(joint.tick),
                    option_i32(joint.target_tick),
                    joint
                        .angle_deg()
                        .map(|angle| format!("{angle:.1}"))
                        .unwrap_or_else(|| "NA".to_string())
                ),
                4 + index,
            ));
        }

        match self.state.lock() {
            Ok(mut state) => {
                state.labels = labels;
                state.puppybot_target_tcp_mm = arm.target_coords_mm;
            }
            Err(_) => {
                log::warn!("RobotDreams simulation state lock poisoned while updating labels")
            }
        }
    }
}

impl SimulatedPreview {
    pub(crate) fn run_blocking(self) -> Result<(), String> {
        let state = Arc::clone(&self.state);
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

        let (mut frame, visual_bindings) = match state.lock() {
            Ok(state) => {
                let mut options = options.clone();
                options.text_labels = state.labels.clone();
                let frame = robotdreams_pge_frame(&state.dreams, options);
                let visual_bindings = state
                    .dreams
                    .model()
                    .map(|model| preview_visual_bindings(&model.robot_visual_meshes()))
                    .unwrap_or_default();
                (frame, visual_bindings)
            }
            Err(_) => return Err("RobotDreams preview state lock poisoned before startup".into()),
        };
        let world_node_index = index_world_nodes(&frame.world);
        set_world_camera_transform(
            &mut frame.world,
            &world_node_index,
            &frame.camera_entity.0,
            orbit_camera_transform(&orbit_state, orbit_camera_node_id, &orbit_controller),
        );

        run_windowed(
            frame.world,
            frame.request,
            WindowRenderConfig {
                title: "PuppyBot RobotDreams Simulation".to_string(),
                resolution: options.resolution,
            },
            move |world, context| {
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

                let (labels, visual_transforms, debug_markers, frames) = match state.lock() {
                    Ok(state) => {
                        let mut debug_markers = state.dreams.coordinate_debug_marker_positions(
                            robotdreams_core::CoordinateDebugOverlayOptions::default(),
                        );
                        let frames = simulation_frame_transforms(&state.dreams);
                        override_debug_markers_with_puppybot_tcp(
                            &mut debug_markers,
                            state.puppybot_target_tcp_mm,
                            frames,
                        );
                        (
                            state.labels.clone(),
                            state
                                .dreams
                                .model()
                                .map(|model| model.robot_visual_transforms())
                                .unwrap_or_default(),
                            debug_markers,
                            frames,
                        )
                    }
                    Err(_) => {
                        log::warn!("RobotDreams preview state lock poisoned");
                        return Ok(false);
                    }
                };
                let mut text_labels = labels;
                let legend_row_start = text_labels.len();
                text_labels.extend(coordinate_debug_legend_labels(legend_row_start));
                world.text_labels = text_labels.into_iter().map(pge_text_label).collect();
                sync_robot_visual_transforms(
                    world,
                    &visual_bindings,
                    &visual_transforms,
                    &world_node_index,
                );
                sync_tcp_debug_markers(world, &debug_markers, &world_node_index);
                if let Some(frames) = frames {
                    sync_debug_frame_roots(world, frames, &world_node_index);
                }
                set_world_camera_transform(
                    world,
                    &world_node_index,
                    &frame.camera_entity.0,
                    orbit_camera_transform(&orbit_state, orbit_camera_node_id, &orbit_controller),
                );
                Ok(true)
            },
        )
        .map_err(|err| err.to_string())
    }
}

struct PreviewCameraTransform {
    translation: [f32; 3],
    rotation_matrix: [[f32; 3]; 3],
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

fn sync_robot_visual_transforms(
    world: &mut pge_core::WorldState,
    visual_bindings: &[PreviewVisualBinding],
    visual_transforms: &[robotdreams_core::project::RobotVisualTransform],
    index: &HashMap<String, PgeCoreArenaId<PgeCoreNode>>,
) {
    for (binding, visual) in visual_bindings.iter().zip(visual_transforms.iter()) {
        set_world_node_transform(
            world,
            index,
            &binding.entity,
            PgeCoreTransform {
                translation: visual.translation,
                rotation: [0.0, 0.0, 0.0],
                rotation_matrix: Some(visual.rotation_matrix),
            },
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
    [x_axis, y_axis, z_axis]
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

fn option_i32(value: Option<i32>) -> String {
    value
        .map(|value| value.to_string())
        .unwrap_or_else(|| "NA".to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

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
}
