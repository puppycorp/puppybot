use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};

use puppybot_state::PuppyBotState;
use robotdreams_core::project::{
    DeviceConfig, ProjectSceneBodyKind, ProjectSceneColliderGeometry, ProjectSceneObjectGeometry,
    load_model_profile, project_config_from_manifest, resolve_urdf_path,
};
use robotdreams_core::scene_harness::UrdfSceneHarness;
use robotdreams_core::{RobotDreams, SceneLocation};

#[path = "support/harness.rs"]
mod harness;
mod puppybot_state;
use harness::{install_simulation_mappings, runtime_config};

fn model_dir() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../models/puppybot")
}

fn model_profile_path() -> PathBuf {
    model_dir().join("robotdreams.json")
}

fn project_path() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../robotdreams/project.json")
}

fn runtime_config_path() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../puppybot/runtime/puppybot.json")
}

fn distance(left: [f64; 3], right: [f64; 3]) -> f64 {
    let dx = left[0] - right[0];
    let dy = left[1] - right[1];
    let dz = left[2] - right[2];
    (dx * dx + dy * dy + dz * dz).sqrt()
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
fn puppybot_robotdreams_project_authors_ball_and_bin_physics() {
    let project = project_config_from_manifest(&project_path()).expect("load PuppyBot project");

    let ball = project
        .scene
        .objects
        .iter()
        .find(|object| object.id == "ball")
        .expect("ball object");
    assert!(matches!(
        ball.geometry,
        ProjectSceneObjectGeometry::Sphere { radius } if radius == 0.025
    ));
    let ball_physics = ball.physics.as_ref().expect("ball physics");
    assert_eq!(ball_physics.body_kind, ProjectSceneBodyKind::Dynamic);
    assert!(matches!(
        ball_physics.collider.geometry,
        ProjectSceneColliderGeometry::Sphere { radius } if radius == 0.025
    ));

    let trashbin = project
        .scene
        .objects
        .iter()
        .find(|object| object.id == "trashbin")
        .expect("trashbin object");
    let bin_physics = trashbin.physics.as_ref().expect("trashbin physics");
    assert_eq!(bin_physics.body_kind, ProjectSceneBodyKind::Static);
    assert_eq!(bin_physics.collider.offset, [0.0, 0.0, 0.01]);
    assert!(matches!(
        bin_physics.collider.geometry,
        ProjectSceneColliderGeometry::Box { size } if size == [0.18, 0.18, 0.02]
    ));

    let trigger = project
        .scene
        .triggers
        .iter()
        .find(|trigger| trigger.id == "ball_in_bin")
        .expect("ball-in-bin trigger");
    assert_eq!(trigger.object_id, "ball");
    assert_eq!(trigger.position, [0.157243, 0.075899, 0.125]);
    assert_eq!(trigger.size, [0.15, 0.15, 0.22]);
    assert_eq!(trigger.settle_speed_mps, 0.05);
    assert_eq!(trigger.settle_time_sec, 0.25);
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
fn puppybot_robotdreams_virtual_servos_drive_semantic_arm_joints() {
    let profile = load_model_profile(model_profile_path()).expect("load PuppyBot model profile");
    let semantic_joints = semantic_to_urdf(&profile.joint_names);
    let project = project_config_from_manifest(&project_path()).expect("load PuppyBot project");
    let bus = project
        .hardware
        .buses
        .iter()
        .find(|bus| bus.id == "main_bus")
        .expect("main bus");
    let expected = ["yaw", "shoulder", "elbow", "wrist"];

    for semantic_name in expected {
        let joint_name = semantic_joints
            .get(semantic_name)
            .unwrap_or_else(|| panic!("missing semantic joint {semantic_name}"));
        let servos: Vec<_> = bus
            .devices
            .iter()
            .filter_map(|device| match device {
                DeviceConfig::Servo(servo) => (servo.drives.as_ref().map(|drives| &drives.target)
                    == Some(joint_name))
                .then_some(servo),
                _ => None,
            })
            .collect();
        assert_eq!(
            servos.len(),
            1,
            "semantic joint {semantic_name} should have exactly one driving servo"
        );
        assert!((0..4096).contains(&i32::from(servos[0].calibration.zero_offset)));
        assert!(matches!(servos[0].calibration.direction, -1 | 1));
    }
}

#[test]
fn puppybot_fixed_servo_ticks_preserve_installed_urdf_angles() {
    let mut dreams = RobotDreams::open(project_path()).expect("open PuppyBot RobotDreams project");
    let runtime = runtime_config();
    install_simulation_mappings(&mut dreams, &runtime);
    let cases = [
        ("yaw", 1_u8, 3200_i16),
        ("shoulder", 2, 2500),
        ("elbow", 3, 3100),
        ("wrist", 4, 2800),
    ];
    for (_, servo_id, tick) in cases {
        assert!(dreams.set_virtual_servo_target("main_bus", servo_id, tick));
    }
    dreams.advance_seconds(3.0);
    let state = dreams
        .robot_state("puppybot")
        .expect("PuppyBot robot state");
    let model: serde_json::Value = serde_json::from_str(
        &fs::read_to_string(model_profile_path()).expect("read model profile"),
    )
    .expect("parse model profile");

    for (index, (semantic, _, tick)) in cases.into_iter().enumerate() {
        let runtime_joint = runtime.arm.joints[index];
        let reference_tick = f64::from(runtime_joint.reference_tick);
        let reference_angle = runtime_joint.reference_angle_rad;
        let angle_sign = f64::from(runtime_joint.angle_sign);
        let mapping = &model["analyticToUrdf"]["joints"][semantic];
        let analytic_angle = reference_angle
            + angle_sign * (f64::from(tick) - reference_tick) * (std::f64::consts::TAU / 4096.0);
        let expected = analytic_angle * mapping["scale"].as_f64().expect("analytic mapping scale")
            + mapping["offset"].as_f64().expect("analytic mapping offset");
        let actual = state
            .joints
            .get(semantic)
            .unwrap_or_else(|| panic!("semantic joint {semantic}"))
            .position_rad;
        let modulo_error = (actual - expected + std::f64::consts::PI)
            .rem_euclid(std::f64::consts::TAU)
            - std::f64::consts::PI;
        assert_close_m(modulo_error, 0.0, std::f64::consts::TAU / 8192.0);
    }
}

#[test]
fn puppybot_robotdreams_scene_locations_include_trashbin_and_ball() {
    let dreams = RobotDreams::open(project_path()).expect("open PuppyBot RobotDreams project");
    let trashbin = dreams.location_of("trashbin").expect("trashbin location");
    let ball = dreams.location_of("ball").expect("ball location");

    assert_scene_location(&trashbin);
    assert_scene_location(&ball);
    assert_close_m(trashbin.position[0], 0.157243, 1.0e-6);
    assert_close_m(trashbin.position[1], 0.075899, 1.0e-6);
    assert_close_m(trashbin.position[2], 0.0, 1.0e-6);
    let trashbin_rotation = trashbin.rotation.expect("trashbin rotation");
    assert_close_m(trashbin_rotation[0], 0.0, 1.0e-6);
    assert_close_m(trashbin_rotation[1], 0.0, 1.0e-6);
    assert_close_m(trashbin_rotation[2], 0.0, 1.0e-6);
    assert_close_m(ball.position[0], 0.276407, 1.0e-6);
    assert_close_m(ball.position[1], -0.070398, 1.0e-6);
    assert_close_m(ball.position[2], 0.025, 1.0e-6);
}

#[test]
fn puppybot_robotdreams_model_transformation_orients_urdf_to_ros_frame() {
    let dreams = RobotDreams::open(project_path()).expect("open PuppyBot RobotDreams project");
    let right_wheel = dreams
        .location_of("wheel_base")
        .expect("right wheel base location");
    let left_wheel = dreams
        .location_of("wheel_base_1")
        .expect("left wheel base location");

    let wheel_delta = [
        left_wheel.position[0] - right_wheel.position[0],
        left_wheel.position[1] - right_wheel.position[1],
        left_wheel.position[2] - right_wheel.position[2],
    ];

    assert!(
        wheel_delta[1] > 0.10,
        "PuppyBot left/right wheel width should point along ROS +Y: right={:?} left={:?} delta={:?}",
        right_wheel.position,
        left_wheel.position,
        wheel_delta
    );
    assert!(
        wheel_delta[1].abs() > wheel_delta[0].abs() * 10.0,
        "PuppyBot wheel width should be Y-dominant, not X-dominant: delta={wheel_delta:?}"
    );
    assert_close_m(wheel_delta[2], 0.0, 1.0e-3);
}

#[test]
fn puppybot_robotdreams_steering_servo_is_virtual_but_not_arm_mapped() {
    let project = project_config_from_manifest(&project_path()).expect("load PuppyBot project");
    let bus = project
        .hardware
        .buses
        .iter()
        .find(|bus| bus.id == "main_bus")
        .expect("main bus");
    let steering_servo = bus
        .devices
        .iter()
        .find_map(|device| match device {
            DeviceConfig::Servo(servo) if servo.id == 5 => Some(servo),
            _ => None,
        })
        .expect("steering servo 5");

    assert_eq!(steering_servo.name, "Steering Servo");
    assert!(
        steering_servo.drives.is_none(),
        "steering servo 5 should not drive an arm URDF joint"
    );
    let steers = steering_servo
        .steers
        .as_ref()
        .expect("steering servo should map to front steering joints");
    assert_eq!(steers.robot, "puppybot");
    assert_eq!(steers.joints, ["revolute_4", "revolute_6"]);
    assert_eq!(steering_servo.calibration.zero_offset, 1535);
}

#[test]
fn puppybot_runtime_drive_devices_exist_in_robotdreams_project() {
    let runtime_config: serde_json::Value = serde_json::from_str(
        &fs::read_to_string(runtime_config_path()).expect("read PuppyBot runtime config"),
    )
    .expect("parse PuppyBot runtime config");
    let drive = runtime_config
        .get("drive")
        .and_then(serde_json::Value::as_object)
        .expect("runtime drive config");
    let steering_servo_id = drive
        .get("steering_servo_id")
        .and_then(serde_json::Value::as_u64)
        .expect("runtime steering_servo_id") as u32;
    let left_motor_id = drive
        .get("left_motor_id")
        .and_then(serde_json::Value::as_u64)
        .expect("runtime left_motor_id") as u32;
    let right_motor_id = drive
        .get("right_motor_id")
        .and_then(serde_json::Value::as_u64)
        .expect("runtime right_motor_id") as u32;

    let project = project_config_from_manifest(&project_path()).expect("load PuppyBot project");
    let main_bus = project
        .hardware
        .buses
        .iter()
        .find(|bus| bus.id == "main_bus")
        .expect("main bus");
    let drive_bus = project
        .hardware
        .buses
        .iter()
        .find(|bus| bus.id == "drive_bus")
        .expect("drive bus");

    assert!(
        main_bus.devices.iter().any(|device| matches!(
            device,
            DeviceConfig::Servo(servo)
                if servo.id == steering_servo_id && servo.drives.is_none()
        )),
        "runtime steering servo {steering_servo_id} should exist on main_bus and not drive an arm joint"
    );
    for motor_id in [left_motor_id, right_motor_id] {
        assert!(
            drive_bus.devices.iter().any(|device| matches!(
                device,
                DeviceConfig::DcMotor(motor) if motor.id == motor_id
            )),
            "runtime drive motor {motor_id} should exist on drive_bus"
        );
    }
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
    assert_eq!(frame_mapping.model.forward_axis, "x");
    assert_eq!(frame_mapping.model.left_axis, "y");
    assert_eq!(frame_mapping.model.up_axis, "z");

    let arm_base = profile
        .frames
        .iter()
        .find(|frame| frame.id == "armBase")
        .expect("armBase frame");
    assert_eq!(arm_base.name, "Arm Base");
    assert_eq!(arm_base.relative_to, "base");
    for (actual, expected) in
        arm_base
            .translation_m
            .into_iter()
            .zip([0.0369572, -0.00974321, 0.0589591])
    {
        assert_close_m(actual, expected, 1.0e-9);
    }
    for (actual, expected) in arm_base
        .rotation_rpy_rad
        .into_iter()
        .zip([0.0, 0.0, 0.1248338])
    {
        assert_close_m(actual, expected, 1.0e-9);
    }

    let tcp = profile.tcp.expect("tcp metadata");
    assert_eq!(tcp.link, "part_1_4");
    assert_close_m(f64::from(tcp.offset[0]), 0.0383, 1.0e-6);
    assert_close_m(f64::from(tcp.offset[1]), 0.0, 1.0e-6);
    assert_close_m(f64::from(tcp.offset[2]), -0.045, 1.0e-6);
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
