use std::collections::HashMap;
use std::path::{Path, PathBuf};

use puppybot_core::config::{JointCalibration, PuppyArmConfig};
use puppybot_core::puppyarm::puppyarm::{ArmCommand, PuppyArm, TcpFrame};
use puppybot_core::puppyarm::types::JOINT_COUNT;
use puppybot_state::PuppyBotState;
use robotdreams_core::project::{
    DeviceConfig, ProjectSceneObjectGeometry, load_model_profile, project_config_from_manifest,
    resolve_urdf_path,
};
use robotdreams_core::scene_harness::UrdfSceneHarness;
use robotdreams_core::{RobotDreams, SceneLocation};

mod puppybot_state;

const YAW_REFERENCE_TICK: u16 = 2048;
const SHOULDER_REFERENCE_TICK: u16 = 530;
const ELBOW_REFERENCE_TICK: u16 = 3565;
const TIP_REFERENCE_TICK: u16 = 1783;
const CORE_Z_TOLERANCE_MM: f32 = 1.0;
const MODEL_UP_TOLERANCE_M: f64 = 0.010;
const MODEL_POSE_TOLERANCE_M: f64 = 0.015;
const SCENE_TEST_POSE: [f64; JOINT_COUNT] = [
    0.0,
    90.0_f64.to_radians(),
    90.0_f64.to_radians(),
    90.0_f64.to_radians(),
];

fn model_dir() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../models/puppybot")
}

fn model_profile_path() -> PathBuf {
    model_dir().join("robotdreams.json")
}

fn project_path() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../robotdreams/project.json")
}

fn distance(left: [f64; 3], right: [f64; 3]) -> f64 {
    let dx = left[0] - right[0];
    let dy = left[1] - right[1];
    let dz = left[2] - right[2];
    (dx * dx + dy * dy + dz * dz).sqrt()
}

fn model_axis_index(axis: &str) -> usize {
    match axis {
        "x" => 0,
        "y" => 1,
        "z" => 2,
        other => panic!("unsupported model axis: {other}"),
    }
}

fn semantic_to_urdf(profile_joint_names: &HashMap<String, String>) -> HashMap<String, String> {
    profile_joint_names
        .iter()
        .map(|(urdf, semantic)| (semantic.clone(), urdf.clone()))
        .collect()
}

fn ancestor_joint_names(harness: &UrdfSceneHarness, link_name: &str) -> Vec<String> {
    let mut child_to_joint = HashMap::new();
    for joint in &harness.robot().joints {
        child_to_joint.insert(joint.child.link.as_str(), joint);
    }

    let mut link = link_name;
    let mut ancestors = Vec::new();
    while let Some(joint) = child_to_joint.get(link) {
        ancestors.push(joint.name.clone());
        link = joint.parent.link.as_str();
    }
    ancestors.reverse();
    ancestors
}

fn arm_with_reference_feedback() -> PuppyArm {
    let mut arm = PuppyArm::new(0);
    arm.record_feedback(0, YAW_REFERENCE_TICK, 0);
    arm.record_feedback(1, SHOULDER_REFERENCE_TICK, 0);
    arm.record_feedback(2, ELBOW_REFERENCE_TICK, 0);
    arm.record_feedback(3, TIP_REFERENCE_TICK, 0);
    arm
}

fn arm_with_angle_feedback(angles: [f64; JOINT_COUNT]) -> PuppyArm {
    let mut target_arm = arm_with_reference_feedback();
    target_arm
        .try_handle_arm_cmd(ArmCommand::GotoAngles(angles), 0)
        .expect("seed angle target");
    let target_state = target_arm.telemetry_snapshot(0);

    let mut feedback_arm = PuppyArm::new(0);
    for (index, joint) in target_state.joints.iter().enumerate() {
        feedback_arm.record_feedback(index, joint.target_tick.unwrap() as u16, 0);
    }
    feedback_arm
}

fn runtime_arm_config() -> PuppyArmConfig {
    PuppyArmConfig {
        joints: [
            JointCalibration {
                servo_id: 1,
                tick_min: 0,
                tick_max: 4095,
                reference_tick: 2048,
                reference_angle_rad: 0.0,
                angle_sign: 1,
                drive_sign: 1,
                limit_enabled: true,
            },
            JointCalibration {
                servo_id: 2,
                tick_min: 1000,
                tick_max: 3000,
                reference_tick: 2011,
                reference_angle_rad: 90.0_f64.to_radians(),
                angle_sign: -1,
                drive_sign: 1,
                limit_enabled: true,
            },
            JointCalibration {
                servo_id: 3,
                tick_min: 3500,
                tick_max: 2500,
                reference_tick: 500,
                reference_angle_rad: 0.0,
                angle_sign: -1,
                drive_sign: 1,
                limit_enabled: true,
            },
            JointCalibration {
                servo_id: 4,
                tick_min: 1700,
                tick_max: 300,
                reference_tick: 2510,
                reference_angle_rad: 0.0,
                angle_sign: 1,
                drive_sign: 1,
                limit_enabled: true,
            },
        ],
    }
}

fn runtime_arm_with_reference_feedback() -> PuppyArm {
    let config = runtime_arm_config();
    let mut arm = PuppyArm::new_with_config(&config, 0).expect("runtime arm config");
    for (index, joint) in config.joints.iter().enumerate() {
        arm.record_feedback(index, joint.reference_tick as u16, 0);
    }
    arm
}

fn runtime_arm_with_angle_feedback(angles: [f64; JOINT_COUNT]) -> PuppyArm {
    let config = runtime_arm_config();
    let mut target_arm = runtime_arm_with_reference_feedback();
    target_arm
        .try_handle_arm_cmd(ArmCommand::GotoAngles(angles), 0)
        .expect("seed runtime angle target");
    let target_state = target_arm.telemetry_snapshot(0);

    let mut feedback_arm = PuppyArm::new_with_config(&config, 0).expect("runtime arm config");
    for (index, joint) in target_state.joints.iter().enumerate() {
        feedback_arm.record_feedback(index, joint.target_tick.unwrap() as u16, 0);
    }
    feedback_arm
}

fn apply_puppybot_target_angles(
    harness: &mut UrdfSceneHarness,
    semantic_joints: &HashMap<String, String>,
    angles: [f64; JOINT_COUNT],
) {
    let names = ["yaw", "shoulder", "elbow", "wrist"];
    for (index, semantic_name) in names.iter().enumerate() {
        let urdf_name = semantic_joints
            .get(*semantic_name)
            .unwrap_or_else(|| panic!("missing semantic joint {semantic_name}"));
        harness.set_joint_angle(urdf_name, angles[index]);
    }
}

fn target_angles_rad(arm: &PuppyArm) -> [f64; JOINT_COUNT] {
    let telemetry = arm.telemetry_snapshot(0);
    telemetry.joints.map(|joint| {
        f64::from(
            joint
                .target_angle_deg
                .expect("expected target angle after movement"),
        )
        .to_radians()
    })
}

fn target_ticks(arm: &PuppyArm) -> [i32; JOINT_COUNT] {
    let telemetry = arm.telemetry_snapshot(0);
    telemetry.joints.map(|joint| {
        joint
            .target_tick
            .expect("expected target tick after movement")
    })
}

fn servo_target_radians(tick: i32, zero_offset: i16, direction: i8) -> f64 {
    let direction = if direction < 0 { -1.0 } else { 1.0 };
    direction * f64::from(tick - i32::from(zero_offset)) * std::f64::consts::TAU / 4096.0
}

fn apply_puppybot_servo_target_ticks(
    harness: &mut UrdfSceneHarness,
    project: &robotdreams_core::project::ProjectConfig,
    ticks: [i32; JOINT_COUNT],
) {
    for bus in &project.hardware.buses {
        for device in &bus.devices {
            let DeviceConfig::Servo(servo) = device else {
                continue;
            };
            let Some(drives) = &servo.drives else {
                continue;
            };
            let Some(index) = servo.id.checked_sub(1).map(|index| index as usize) else {
                continue;
            };
            if index >= JOINT_COUNT {
                continue;
            }
            harness.set_joint_angle(
                drives.target.clone(),
                servo_target_radians(
                    ticks[index],
                    servo.calibration.zero_offset,
                    servo.calibration.direction,
                ),
            );
        }
    }
}

fn assert_close_mm(left: f32, right: f32, tolerance: f32) {
    assert!(
        (left - right).abs() <= tolerance,
        "left={left:.3} right={right:.3} diff={:.3} tolerance={tolerance:.3}",
        (left - right).abs()
    );
}

fn assert_close_m(left: f64, right: f64, tolerance: f64) {
    assert!(
        (left - right).abs() <= tolerance,
        "left={left:.6} right={right:.6} diff={:.6} tolerance={tolerance:.6}",
        (left - right).abs()
    );
}

fn assert_scene_location(location: &SceneLocation) {
    assert!(
        location.position.iter().all(|value| value.is_finite()),
        "scene location should have finite coordinates: {location:?}"
    );
}

#[test]
fn puppybot_model_profile_resolves_and_loads_urdf() {
    let profile = load_model_profile(model_profile_path()).expect("load PuppyBot model profile");
    assert_eq!(profile.name, "puppybot");

    let urdf_path = resolve_urdf_path(Some(profile.manifest_path.clone()))
        .expect("resolve PuppyBot model URDF path");
    assert!(urdf_path.ends_with("final2/urdf/final2.urdf"));

    let harness = UrdfSceneHarness::from_urdf_path(urdf_path).expect("load PuppyBot URDF");
    assert!(harness.has_link("part_1_4"));
}

#[test]
fn puppybot_robotdreams_project_resolves_owned_model_and_assets() {
    let project_path = project_path();
    let project = project_config_from_manifest(&project_path).expect("load PuppyBot project");
    assert_eq!(project.name, "PuppyBot Bin And Ball");
    assert_eq!(project.robots.len(), 1);
    assert_eq!(project.robots[0].id, "puppybot");
    assert_eq!(
        project.robots[0].model.path,
        "../models/puppybot/final2/urdf/final2.urdf"
    );

    let urdf_path =
        resolve_urdf_path(Some(project_path)).expect("resolve PuppyBot project URDF path");
    assert!(urdf_path.ends_with("models/puppybot/final2/urdf/final2.urdf"));

    let trashbin = project
        .scene
        .objects
        .iter()
        .find(|object| object.id == "trashbin")
        .expect("trashbin object");
    let ProjectSceneObjectGeometry::Mesh { asset } = &trashbin.geometry else {
        panic!("trashbin should use mesh geometry");
    };
    assert!(
        project.base_dir.join(asset).exists(),
        "missing scene asset: {asset}"
    );
}

#[test]
fn puppybot_robotdreams_project_opens_from_test_crate_path() {
    let dreams = RobotDreams::open(project_path()).expect("open PuppyBot RobotDreams project");
    let model = dreams.model().expect("loaded RobotDreams model");

    assert_eq!(
        model.project().expect("project config").name,
        "PuppyBot Bin And Ball"
    );
}

#[test]
fn puppybot_robotdreams_servo_calibration_matches_runtime_config() {
    let project = project_config_from_manifest(&project_path()).expect("load PuppyBot project");
    let bus = project
        .hardware
        .buses
        .iter()
        .find(|bus| bus.id == "main_bus")
        .expect("main bus");
    let expected = [
        (1, "revolute_2_3", 2048, 1),
        (2, "revolute_1_1", 3035, -1),
        (3, "revolute_1_2", 500, -1),
        (4, "revolute_1", 2510, 1),
    ];

    for (id, joint_name, zero_offset, direction) in expected {
        let servo = bus
            .devices
            .iter()
            .find_map(|device| match device {
                DeviceConfig::Servo(servo) if servo.id == id => Some(servo),
                _ => None,
            })
            .unwrap_or_else(|| panic!("missing servo {id}"));

        assert_eq!(
            servo.drives.as_ref().map(|drives| drives.target.as_str()),
            Some(joint_name)
        );
        assert_eq!(servo.calibration.zero_offset, zero_offset);
        assert_eq!(servo.calibration.direction, direction);
    }
}

#[test]
fn puppybot_robotdreams_scene_locations_include_trashbin_and_ball() {
    let dreams = RobotDreams::open(project_path()).expect("open PuppyBot RobotDreams project");
    let trashbin = dreams.location_of("trashbin").expect("trashbin location");
    let ball = dreams.location_of("ball").expect("ball location");

    assert_scene_location(&trashbin);
    assert_scene_location(&ball);
}

#[test]
fn puppybot_robotdreams_robot_state_parses_semantic_arm_state() {
    let dreams = RobotDreams::open(project_path()).expect("open PuppyBot RobotDreams project");
    let robot_state = dreams
        .robot_state("puppybot")
        .expect("puppybot robot state");
    let puppybot_state = PuppyBotState::parse(robot_state).expect("parse PuppyBot state");

    assert_scene_location(&puppybot_state.base);
    assert_scene_location(&puppybot_state.tcp);
    assert!(puppybot_state.yaw_rad.is_finite());
    assert!(puppybot_state.shoulder_rad.is_finite());
    assert!(puppybot_state.elbow_rad.is_finite());
    assert!(puppybot_state.wrist_rad.is_finite());
}

#[test]
fn puppybot_robotdreams_joint_update_changes_parsed_yaw_and_tcp() {
    let mut dreams = RobotDreams::open(project_path()).expect("open PuppyBot RobotDreams project");
    let first_state = PuppyBotState::parse(
        dreams
            .robot_state("puppybot")
            .expect("initial puppybot robot state"),
    )
    .expect("parse initial PuppyBot state");

    dreams
        .set_joint_angle("yaw", 0.5)
        .expect("set semantic yaw joint");
    let moved_state = PuppyBotState::parse(
        dreams
            .robot_state("puppybot")
            .expect("moved puppybot robot state"),
    )
    .expect("parse moved PuppyBot state");

    assert_close_m(moved_state.yaw_rad, 0.5, 1.0e-9);
    assert!(
        distance(first_state.tcp.position, moved_state.tcp.position) > 1.0e-6,
        "expected TCP location to change after updating its URDF ancestor joint"
    );
}

#[test]
fn puppybot_model_declares_arm_joint_and_frame_metadata() {
    let profile = load_model_profile(model_profile_path()).expect("load PuppyBot model profile");
    let semantic_joints = semantic_to_urdf(&profile.joint_names);
    let expected_semantic_joints = [
        ("yaw", "revolute_2_3"),
        ("shoulder", "revolute_1_1"),
        ("elbow", "revolute_1_2"),
        ("wrist", "revolute_1"),
    ];

    for (semantic_name, expected_urdf_name) in expected_semantic_joints {
        let urdf_name = semantic_joints
            .get(semantic_name)
            .unwrap_or_else(|| panic!("missing semantic joint {semantic_name}"));
        assert_eq!(urdf_name, expected_urdf_name);
        assert!(
            profile.joint_names.contains_key(urdf_name),
            "missing URDF joint mapping for {semantic_name}"
        );
    }

    let urdf_path = resolve_urdf_path(Some(profile.manifest_path.clone()))
        .expect("resolve PuppyBot model URDF path");
    let harness = UrdfSceneHarness::from_urdf_path(urdf_path).expect("load PuppyBot URDF");
    for urdf_name in semantic_joints.values() {
        assert!(
            harness.has_joint(urdf_name),
            "missing URDF joint {urdf_name}"
        );
    }

    let frame_mapping = profile.frame_mapping.expect("frame mapping");
    assert_eq!(frame_mapping.core.forward_axis, "x");
    assert_eq!(frame_mapping.core.left_axis, "y");
    assert_eq!(frame_mapping.core.up_axis, "z");
    assert_eq!(frame_mapping.model.up_axis, "y");

    let tcp = profile.tcp.expect("tcp metadata");
    assert_eq!(tcp.link, "part_1_4");
    let tcp_ancestors = ancestor_joint_names(&harness, &tcp.link);
    let semantic_chain: Vec<_> = ["yaw", "shoulder", "elbow", "wrist"]
        .iter()
        .map(|semantic_name| {
            semantic_joints
                .get(*semantic_name)
                .expect("semantic joint")
                .as_str()
        })
        .collect();
    let mut next_index = 0;
    for ancestor in &tcp_ancestors {
        if next_index < semantic_chain.len() && ancestor == semantic_chain[next_index] {
            next_index += 1;
        }
    }
    assert_eq!(
        next_index,
        semantic_chain.len(),
        "TCP link {} must descend through semantic arm chain {:?}; ancestors were {:?}",
        tcp.link,
        semantic_chain,
        tcp_ancestors
    );
}

#[test]
#[ignore = "full CAD scene invariant; opt-in because it loads the PuppyBot URDF model"]
fn yaw_flat_xy_moves_preserve_core_and_cad_height() {
    for (dx_mm, dy_mm) in [(10.0, 0.0), (0.0, 10.0)] {
        assert_yaw_flat_xy_move_preserves_height(dx_mm, dy_mm);
    }
}

#[test]
#[ignore = "full CAD scene invariant; opt-in because it loads the PuppyBot URDF model"]
fn yaw_flat_xy_moves_preserve_cad_height_through_virtual_servo_calibration() {
    let profile = load_model_profile(model_profile_path()).expect("load PuppyBot model profile");
    let frame_mapping = profile.frame_mapping.clone().expect("frame mapping");
    let tcp = profile.tcp.clone().expect("tcp metadata");
    let model_up_axis = model_axis_index(&frame_mapping.model.up_axis);
    let project = project_config_from_manifest(&project_path()).expect("load PuppyBot project");
    let urdf_path = resolve_urdf_path(Some(project_path())).expect("resolve PuppyBot URDF path");

    let mut seed_arm = runtime_arm_with_reference_feedback();
    seed_arm
        .try_handle_arm_cmd(ArmCommand::GotoAngles(SCENE_TEST_POSE), 0)
        .expect("seed scene pose target");
    let semantic_joints = semantic_to_urdf(&profile.joint_names);
    let mut direct_start_harness =
        UrdfSceneHarness::from_urdf_path(&urdf_path).expect("load PuppyBot URDF");
    apply_puppybot_target_angles(&mut direct_start_harness, &semantic_joints, SCENE_TEST_POSE);
    let direct_start_tcp = direct_start_harness
        .link_point_world(
            &tcp.link,
            [
                f64::from(tcp.offset[0]),
                f64::from(tcp.offset[1]),
                f64::from(tcp.offset[2]),
            ],
        )
        .expect("sample direct start TCP");

    let mut start_harness =
        UrdfSceneHarness::from_urdf_path(&urdf_path).expect("load PuppyBot URDF");
    apply_puppybot_servo_target_ticks(&mut start_harness, &project, target_ticks(&seed_arm));
    let start_tcp = start_harness
        .link_point_world(
            &tcp.link,
            [
                f64::from(tcp.offset[0]),
                f64::from(tcp.offset[1]),
                f64::from(tcp.offset[2]),
            ],
        )
        .expect("sample start TCP");
    assert!(
        distance(start_tcp, direct_start_tcp) <= MODEL_POSE_TOLERANCE_M,
        "virtual-servo start TCP should match direct core-angle TCP: servo={start_tcp:?} direct={direct_start_tcp:?}"
    );

    let mut arm = runtime_arm_with_angle_feedback(SCENE_TEST_POSE);
    arm.try_handle_arm_cmd(
        ArmCommand::MoveTcpRelative {
            frame: TcpFrame::YawFlat,
            dx_mm: 10.0,
            dy_mm: 0.0,
            dz_mm: 0.0,
        },
        0,
    )
    .expect("reachable yaw-flat movement");

    let mut direct_moved_harness =
        UrdfSceneHarness::from_urdf_path(&urdf_path).expect("load PuppyBot URDF");
    apply_puppybot_target_angles(
        &mut direct_moved_harness,
        &semantic_joints,
        target_angles_rad(&arm),
    );
    let direct_moved_tcp = direct_moved_harness
        .link_point_world(
            &tcp.link,
            [
                f64::from(tcp.offset[0]),
                f64::from(tcp.offset[1]),
                f64::from(tcp.offset[2]),
            ],
        )
        .expect("sample direct moved TCP");

    let mut moved_harness =
        UrdfSceneHarness::from_urdf_path(urdf_path).expect("load PuppyBot URDF");
    apply_puppybot_servo_target_ticks(&mut moved_harness, &project, target_ticks(&arm));
    let moved_tcp = moved_harness
        .link_point_world(
            &tcp.link,
            [
                f64::from(tcp.offset[0]),
                f64::from(tcp.offset[1]),
                f64::from(tcp.offset[2]),
            ],
        )
        .expect("sample moved TCP");
    assert!(
        distance(moved_tcp, direct_moved_tcp) <= MODEL_POSE_TOLERANCE_M,
        "virtual-servo moved TCP should match direct core-angle TCP: servo={moved_tcp:?} direct={direct_moved_tcp:?}"
    );

    assert_close_m(
        moved_tcp[model_up_axis],
        start_tcp[model_up_axis],
        MODEL_UP_TOLERANCE_M,
    );
}

#[test]
#[ignore = "full CAD scene invariant; opt-in because it loads the PuppyBot URDF model"]
fn unreachable_yaw_flat_xy_move_preserves_target_height() {
    let profile = load_model_profile(model_profile_path()).expect("load PuppyBot model profile");
    let frame_mapping = profile.frame_mapping.clone().expect("frame mapping");
    let tcp = profile.tcp.clone().expect("tcp metadata");
    let model_up_axis = model_axis_index(&frame_mapping.model.up_axis);
    let semantic_joints = semantic_to_urdf(&profile.joint_names);
    let urdf_path = resolve_urdf_path(Some(profile.manifest_path.clone()))
        .expect("resolve PuppyBot model URDF path");

    let mut arm = arm_with_angle_feedback(SCENE_TEST_POSE);
    arm.try_handle_arm_cmd(
        ArmCommand::MoveTcpRelative {
            frame: TcpFrame::YawFlat,
            dx_mm: 10.0,
            dy_mm: 0.0,
            dz_mm: 0.0,
        },
        0,
    )
    .expect("seed reachable yaw-flat movement");
    let before = arm.telemetry_snapshot(0);
    let before_target_z = before.target_coords_mm.expect("target coords").2;
    let before_target_ticks = before.joints.map(|joint| joint.target_tick);
    let before_angles = target_angles_rad(&arm);

    let mut before_harness =
        UrdfSceneHarness::from_urdf_path(&urdf_path).expect("load PuppyBot URDF");
    apply_puppybot_target_angles(&mut before_harness, &semantic_joints, before_angles);
    let before_tcp = before_harness
        .link_point_world(
            &tcp.link,
            [
                f64::from(tcp.offset[0]),
                f64::from(tcp.offset[1]),
                f64::from(tcp.offset[2]),
            ],
        )
        .expect("sample TCP before unreachable move");

    assert!(
        arm.try_handle_arm_cmd(
            ArmCommand::MoveTcpRelative {
                frame: TcpFrame::YawFlat,
                dx_mm: 1000.0,
                dy_mm: 0.0,
                dz_mm: 0.0,
            },
            0,
        )
        .is_err(),
        "unreachable move should be rejected"
    );

    let after = arm.telemetry_snapshot(0);
    assert_close_mm(
        after.target_coords_mm.expect("target coords").2,
        before_target_z,
        CORE_Z_TOLERANCE_MM,
    );
    assert_eq!(
        after.joints.map(|joint| joint.target_tick),
        before_target_ticks
    );

    let mut after_harness =
        UrdfSceneHarness::from_urdf_path(urdf_path).expect("load PuppyBot URDF");
    apply_puppybot_target_angles(
        &mut after_harness,
        &semantic_joints,
        target_angles_rad(&arm),
    );
    let after_tcp = after_harness
        .link_point_world(
            &tcp.link,
            [
                f64::from(tcp.offset[0]),
                f64::from(tcp.offset[1]),
                f64::from(tcp.offset[2]),
            ],
        )
        .expect("sample TCP after unreachable move");
    assert_close_m(
        after_tcp[model_up_axis],
        before_tcp[model_up_axis],
        MODEL_UP_TOLERANCE_M,
    );
}

fn assert_yaw_flat_xy_move_preserves_height(dx_mm: f64, dy_mm: f64) {
    let profile = load_model_profile(model_profile_path()).expect("load PuppyBot model profile");
    let frame_mapping = profile.frame_mapping.clone().expect("frame mapping");
    let tcp = profile.tcp.clone().expect("tcp metadata");
    let model_up_axis = model_axis_index(&frame_mapping.model.up_axis);
    let semantic_joints = semantic_to_urdf(&profile.joint_names);
    let urdf_path = resolve_urdf_path(Some(profile.manifest_path.clone()))
        .expect("resolve PuppyBot model URDF path");

    let mut arm = arm_with_angle_feedback(SCENE_TEST_POSE);
    let start_z = arm.telemetry_snapshot(0).coords_mm.expect("start coords").2;

    let mut start_harness =
        UrdfSceneHarness::from_urdf_path(&urdf_path).expect("load PuppyBot URDF");
    apply_puppybot_target_angles(&mut start_harness, &semantic_joints, SCENE_TEST_POSE);
    let start_tcp = start_harness
        .link_point_world(
            &tcp.link,
            [
                f64::from(tcp.offset[0]),
                f64::from(tcp.offset[1]),
                f64::from(tcp.offset[2]),
            ],
        )
        .expect("sample start TCP");

    arm.try_handle_arm_cmd(
        ArmCommand::MoveTcpRelative {
            frame: TcpFrame::YawFlat,
            dx_mm,
            dy_mm,
            dz_mm: 0.0,
        },
        0,
    )
    .expect("reachable yaw-flat movement");

    let target_z = arm
        .telemetry_snapshot(0)
        .target_coords_mm
        .expect("target coords")
        .2;
    assert_close_mm(target_z, start_z, CORE_Z_TOLERANCE_MM);

    let mut moved_harness =
        UrdfSceneHarness::from_urdf_path(urdf_path).expect("load PuppyBot URDF");
    apply_puppybot_target_angles(
        &mut moved_harness,
        &semantic_joints,
        target_angles_rad(&arm),
    );
    let moved_tcp = moved_harness
        .link_point_world(
            &tcp.link,
            [
                f64::from(tcp.offset[0]),
                f64::from(tcp.offset[1]),
                f64::from(tcp.offset[2]),
            ],
        )
        .expect("sample moved TCP");

    assert_close_m(
        moved_tcp[model_up_axis],
        start_tcp[model_up_axis],
        MODEL_UP_TOLERANCE_M,
    );
}
