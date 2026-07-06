use std::collections::HashMap;
use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::time::Instant;

use pge_core::{
    ArenaId, EntityId as PgeEntityId, Node as PgeNode, Transform as PgeTransform, WorldState,
};
use pge_renderer::{RenderRequest, RenderView};
use pge_video::{
    RawRgbaMp4EncodeRequest, default_raw_rgba_frame_path, encode_raw_rgba_sequence_to_mp4,
};
use pge_wgpu_renderer::WgpuRenderer;
use puppybot_core::drive::{DriveCommand, DriveConfig, DriveController, DriveOutput};
use robotdreams_core::scene_graph::{
    CameraProjection, CameraSpec, EntityId, EntityMetadata, SceneNode, SceneNodeKind, Transform,
};
use robotdreams_core::{RobotDreams, RobotDreamsSnapshot, world_state_from_scene_graph};

const CAMERA_ID: &str = "orbit_camera";
const DRIVE_BUS_ID: &str = "drive_bus";
const ROBOT_ID: &str = "puppybot";

#[derive(Default)]
struct TimingTotals {
    command_sec: f64,
    advance_sec: f64,
    visual_sec: f64,
    sync_sec: f64,
    render_sec: f64,
    write_sec: f64,
}

impl TimingTotals {
    fn add_command(&mut self, start: Instant) {
        self.command_sec += start.elapsed().as_secs_f64();
    }

    fn add_advance(&mut self, start: Instant) {
        self.advance_sec += start.elapsed().as_secs_f64();
    }

    fn add_visual(&mut self, start: Instant) {
        self.visual_sec += start.elapsed().as_secs_f64();
    }

    fn add_sync(&mut self, start: Instant) {
        self.sync_sec += start.elapsed().as_secs_f64();
    }

    fn add_render(&mut self, start: Instant) {
        self.render_sec += start.elapsed().as_secs_f64();
    }

    fn add_write(&mut self, start: Instant) {
        self.write_sec += start.elapsed().as_secs_f64();
    }
}

fn add_orbit_camera(
    scene: &mut robotdreams_core::scene_graph::SceneGraph,
    eye: [f32; 3],
    target: [f32; 3],
    resolution: [u32; 2],
) {
    let entity = EntityId(format!("camera:{CAMERA_ID}"));
    scene.entities.insert(
        entity.clone(),
        EntityMetadata {
            id: entity.clone(),
            name: "Orbit Camera".to_string(),
            kind: "camera".to_string(),
            robot_id: None,
            link_name: None,
        },
    );
    scene.root.children.retain(
        |node| !matches!(&node.kind, SceneNodeKind::Camera(camera) if camera.id == CAMERA_ID),
    );
    scene.root.children.push(SceneNode::camera(
        entity.0,
        "Orbit Camera",
        CameraSpec {
            id: CAMERA_ID.to_string(),
            name: "Orbit Camera".to_string(),
            transform: Transform::matrix(eye, look_at_matrix(eye, target, [0.0, 0.0, 1.0])),
            fov_deg: 55.0,
            projection: CameraProjection::Perspective,
            resolution,
            intrinsics: None,
            distortion: None,
            depth_range_m: None,
            sensor_effects: None,
        },
    ));
}

fn apply_drive_output(dreams: &mut RobotDreams, output: DriveOutput) -> Result<(), String> {
    if dreams.set_virtual_drive_output(
        DRIVE_BUS_ID,
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
        Err(format!("failed to apply drive output {output:?}"))
    }
}

fn arg_path_or_existing(index: usize, candidates: &[&str]) -> PathBuf {
    if let Some(value) = env::args().nth(index) {
        return PathBuf::from(value);
    }
    candidates
        .iter()
        .map(PathBuf::from)
        .find(|path| path.exists())
        .unwrap_or_else(|| PathBuf::from(candidates[0]))
}

fn arg_u32(index: usize, default: u32) -> u32 {
    env::args()
        .nth(index)
        .and_then(|value| value.parse().ok())
        .unwrap_or(default)
}

fn cross(left: [f32; 3], right: [f32; 3]) -> [f32; 3] {
    [
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    ]
}

fn joint_angle(snapshot: &RobotDreamsSnapshot, joint_name: &str) -> Option<f64> {
    snapshot
        .robots
        .iter()
        .find(|robot| robot.id == ROBOT_ID)
        .and_then(|robot| robot.joints.get(joint_name))
        .map(|joint| joint.position_rad)
}

fn index_world_nodes(world: &WorldState) -> HashMap<String, ArenaId<PgeNode>> {
    world
        .nodes
        .iter()
        .map(|(node_id, node)| (node.entity.0.clone(), node_id))
        .collect()
}

fn length(vector: [f32; 3]) -> f32 {
    (vector[0] * vector[0] + vector[1] * vector[1] + vector[2] * vector[2]).sqrt()
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

fn normalize(vector: [f32; 3]) -> [f32; 3] {
    let len = length(vector).max(f32::EPSILON);
    [vector[0] / len, vector[1] / len, vector[2] / len]
}

fn prepare_output(out: &Path, frames_dir: &Path) -> Result<(), Box<dyn std::error::Error>> {
    if frames_dir.exists() {
        fs::remove_dir_all(frames_dir)?;
    }
    fs::create_dir_all(frames_dir)?;
    if let Some(parent) = out.parent() {
        if !parent.as_os_str().is_empty() {
            fs::create_dir_all(parent)?;
        }
    }
    if out.exists() {
        fs::remove_file(out)?;
    }
    Ok(())
}

fn robot_base_xy_yaw(snapshot: &RobotDreamsSnapshot) -> Option<[f64; 3]> {
    let robot = snapshot.robots.iter().find(|robot| robot.id == ROBOT_ID)?;
    let yaw = robot
        .base
        .rotation
        .map(|rotation| rotation[2])
        .unwrap_or(0.0);
    Some([robot.base.position[0], robot.base.position[1], yaw])
}

fn sub(left: [f32; 3], right: [f32; 3]) -> [f32; 3] {
    [left[0] - right[0], left[1] - right[1], left[2] - right[2]]
}

fn set_world_node_transform(
    world: &mut WorldState,
    index: &HashMap<String, ArenaId<PgeNode>>,
    entity: &str,
    transform: PgeTransform,
) {
    if let Some(node_id) = index.get(entity)
        && let Some(world_node) = world.nodes.get_mut(node_id)
    {
        world_node.transform = transform;
    }
}

fn sync_robot_visual_transforms(
    world: &mut WorldState,
    visual_meshes: &[robotdreams_core::project::RobotVisualMesh],
    index: &HashMap<String, ArenaId<PgeNode>>,
) {
    for (visual_index, visual) in visual_meshes.iter().enumerate() {
        let entity = format!(
            "robot:{}:visual:{}:{visual_index}",
            visual.robot_id, visual.link_name
        );
        set_world_node_transform(
            world,
            index,
            &entity,
            PgeTransform {
                translation: visual.translation,
                rotation: [0.0, 0.0, 0.0],
                rotation_matrix: Some(visual.rotation_matrix),
            },
        );
    }
}

fn pge_transform(transform: Transform) -> PgeTransform {
    PgeTransform {
        translation: transform.translation,
        rotation: transform.rotation,
        rotation_matrix: transform.rotation_matrix,
    }
}

fn write_metadata(
    out: &Path,
    project: &Path,
    frames_dir: &Path,
    frame_count: u32,
    fps: u32,
    seconds: u32,
    resolution: [u32; 2],
    render_elapsed: f64,
    timings: &TimingTotals,
    start_snapshot: &RobotDreamsSnapshot,
    end_snapshot: &RobotDreamsSnapshot,
) -> Result<(), Box<dyn std::error::Error>> {
    let metadata_path = out.with_extension("metadata.json");
    let metadata = serde_json::json!({
        "project": project.display().to_string(),
        "video": out.display().to_string(),
        "framesDirectory": frames_dir.display().to_string(),
        "cameraId": CAMERA_ID,
        "target": [0.03_f32, 0.08_f32, 0.16_f32],
        "radiusM": 0.82_f32,
        "elevationDeg": 45.0_f32,
        "seconds": seconds,
        "fps": fps,
        "frames": frame_count,
        "resolution": resolution,
        "renderWallSeconds": render_elapsed,
        "renderThroughputFps": frame_count as f64 / render_elapsed.max(f64::EPSILON),
        "timingSeconds": {
            "command": timings.command_sec,
            "advance": timings.advance_sec,
            "robotVisuals": timings.visual_sec,
            "syncWorldTransforms": timings.sync_sec,
            "renderReadback": timings.render_sec,
            "writeFrames": timings.write_sec
        },
        "renderer": {
            "name": "pge-wgpu-renderer",
            "source": "RobotDreams scene graph exported as pge_core::WorldState",
            "pgeRevision": "d0c0e7231b92af47c9dd2daa2cb53b2ceae61c6a"
        },
        "driveCommand": {
            "source": "puppybot_core::drive::DriveController",
            "command": "DriveSteer",
            "throttle": 45,
            "steering": 70
        },
        "robotBaseStart": robot_base_xy_yaw(start_snapshot),
        "robotBaseEnd": robot_base_xy_yaw(end_snapshot),
        "elbowStartRad": joint_angle(start_snapshot, "elbow"),
        "elbowEndRad": joint_angle(end_snapshot, "elbow"),
        "elbowJointAnimation": {
            "joint": "elbow",
            "amplitudeDeg": 22.0,
            "periodSec": 2.0
        }
    });
    fs::write(metadata_path, serde_json::to_vec_pretty(&metadata)?)?;
    Ok(())
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let project = arg_path_or_existing(
        1,
        &["robotdreams/project.json", "../../robotdreams/project.json"],
    );
    let out = arg_path_or_existing(
        2,
        &[
            "workdir/puppybot-circles.mp4",
            "../../workdir/puppybot-circles.mp4",
        ],
    );
    let width = arg_u32(3, 320);
    let height = arg_u32(4, 180);
    let fps = arg_u32(5, 24);
    let seconds = arg_u32(6, 10);
    let frames_dir = out.with_file_name("puppybot-circles-frames");
    let frame_count = (fps * seconds).max(1);
    let resolution = [width, height];

    prepare_output(&out, &frames_dir)?;

    let mut dreams = RobotDreams::open(&project).map_err(|err| format!("{err}"))?;
    let mut renderer = WgpuRenderer::new().map_err(|err| format!("{err}"))?;
    let dt = 1.0_f32 / fps as f32;
    let mut drive = DriveController::new(
        DriveConfig {
            left_motor_id: 1,
            right_motor_id: 2,
            steering_servo_id: 5,
            steering_center_deg: 90,
            steering_range_deg: 45,
            command_timeout_ms: 2_000,
        },
        0,
    );

    let start_snapshot = dreams.snapshot();
    let target = [0.03_f32, 0.08_f32, 0.16_f32];
    let radius = 0.82_f32;
    let elevation_rad = 45.0_f32.to_radians();
    let initial_eye = [
        target[0] + radius * elevation_rad.cos(),
        target[1],
        target[2] + radius * elevation_rad.sin(),
    ];
    let mut initial_scene = dreams.scene_graph();
    add_orbit_camera(&mut initial_scene, initial_eye, target, resolution);
    let mut world = world_state_from_scene_graph(&initial_scene);
    let world_node_index = index_world_nodes(&world);
    let request = RenderRequest {
        camera_id: Some(PgeEntityId(format!("camera:{CAMERA_ID}"))),
        views: vec![RenderView::Rgb],
        resolution,
        settings: None,
    };
    let render_start = Instant::now();
    let mut timings = TimingTotals::default();

    for index in 0..frame_count {
        let command_start = Instant::now();
        let elapsed_sec = index as f32 * dt;
        let now_ms = (elapsed_sec * 1000.0).round() as u64;
        drive.handle_command(
            DriveCommand::DriveSteer {
                throttle: 45,
                steering: 70,
            },
            now_ms,
        );
        apply_drive_output(&mut dreams, drive.output())?;

        let elbow_angle = 22.0_f32.to_radians() * (elapsed_sec * std::f32::consts::TAU / 2.0).sin();
        dreams.set_joint_angle("elbow", f64::from(elbow_angle))?;
        timings.add_command(command_start);

        let advance_start = Instant::now();
        if index > 0 {
            dreams.advance_rover_drive_seconds(dt);
        }
        timings.add_advance(advance_start);

        let phase = index as f32 / frame_count as f32;
        let azimuth = phase * std::f32::consts::TAU;
        let eye = [
            target[0] + radius * elevation_rad.cos() * azimuth.cos(),
            target[1] + radius * elevation_rad.cos() * azimuth.sin(),
            target[2] + radius * elevation_rad.sin(),
        ];
        let visual_start = Instant::now();
        let visual_meshes = dreams
            .model()
            .map(|model| model.robot_visual_meshes())
            .unwrap_or_default();
        timings.add_visual(visual_start);

        let sync_start = Instant::now();
        sync_robot_visual_transforms(&mut world, &visual_meshes, &world_node_index);
        set_world_node_transform(
            &mut world,
            &world_node_index,
            &format!("camera:{CAMERA_ID}"),
            pge_transform(Transform::matrix(
                eye,
                look_at_matrix(eye, target, [0.0, 0.0, 1.0]),
            )),
        );
        timings.add_sync(sync_start);

        let render_frame_start = Instant::now();
        let frame = renderer
            .render_rgba(&world, &request)
            .map_err(|err| format!("render frame {index}: {err}"))?;
        timings.add_render(render_frame_start);

        let write_start = Instant::now();
        fs::write(
            default_raw_rgba_frame_path(&frames_dir, index),
            &frame.bytes,
        )?;
        timings.add_write(write_start);
        println!("frame {}/{}", index + 1, frame_count);
    }

    let render_elapsed = render_start.elapsed().as_secs_f64();
    encode_raw_rgba_sequence_to_mp4(&RawRgbaMp4EncodeRequest::raw_rgba_sequence(
        &frames_dir,
        frame_count,
        width,
        height,
        fps,
        &out,
    ))?;
    write_metadata(
        &out,
        &project,
        &frames_dir,
        frame_count,
        fps,
        seconds,
        resolution,
        render_elapsed,
        &timings,
        &start_snapshot,
        &dreams.snapshot(),
    )?;
    println!("encoded {}", out.display());
    println!(
        "render throughput {:.2} fps",
        frame_count as f64 / render_elapsed.max(f64::EPSILON)
    );
    println!(
        "timing seconds command={:.3} advance={:.3} visuals={:.3} sync={:.3} render={:.3} write={:.3}",
        timings.command_sec,
        timings.advance_sec,
        timings.visual_sec,
        timings.sync_sec,
        timings.render_sec,
        timings.write_sec
    );

    Ok(())
}
