use std::collections::HashMap;
use std::path::{Path, PathBuf};

use puppybot_core::config::{
    JointCalibration, PUPPYBOT_CONFIG_VERSION, PuppyArmConfig, PuppybotConfigV1, SERIAL_LEN,
};
use puppybot_core::protocol::ProtocolEvent;
use puppybot_core::puppyarm::types::{ArmCommand, JOINT_COUNT};
use puppybot_core::robot::{PuppyBotSystem, Puppybot};
use puppybot_core::stservo::mock::{FakeSerialBus, FakeServo, block_on_ready};
use robotdreams_core::RobotDreams;
use robotdreams_core::project::{
    DeviceConfig, ProjectConfig, ServoDeviceConfig, load_model_profile,
    project_config_from_manifest,
};

pub const MODEL_UP_TOLERANCE_M: f64 = 0.010;

const SERVO_FULL_ROTATION_TICKS: f64 = 4096.0;
const SIMULATION_STEP_TICKS: i32 = 32;

pub struct PuppybotRobotDreamsHarness {
    project: ProjectConfig,
    system: PuppyBotSystem<FakeSerialBus>,
    dreams: RobotDreams,
}

impl PuppybotRobotDreamsHarness {
    pub fn with_arm_pose(angles_rad: [f64; JOINT_COUNT]) -> Self {
        let project = project_config_from_manifest(&project_path()).expect("load PuppyBot project");
        let config = simulation_config_from_robotdreams_project(&project);
        let bus = fake_bus_with_pose(&config, angles_rad);
        let system = PuppyBotSystem::new(
            Puppybot::new_with_config(&config, 0).expect("simulation PuppyBot config"),
            bus,
        );
        let dreams = RobotDreams::open(project_path()).expect("open PuppyBot RobotDreams project");
        let mut harness = Self {
            project,
            system,
            dreams,
        };
        harness.apply_bus_to_robotdreams();
        harness
    }

    pub fn run_arm_command(&mut self, command: ArmCommand, cycles: usize) {
        let mut event = Some(ProtocolEvent::Arm(command));
        for cycle in 0..cycles {
            block_on_ready(self.system.run_once_at(cycle as u64 * 20, || event.take()));
            step_fake_bus_motion(self.system.servo_mut().bus_mut());
        }
        self.apply_bus_to_robotdreams();
    }

    pub fn tcp_position(&self) -> [f64; 3] {
        self.dreams
            .robot_state("puppybot")
            .expect("puppybot robot state")
            .tcp
            .and_then(|tcp| tcp.location)
            .expect("puppybot TCP location")
            .position
    }

    fn apply_bus_to_robotdreams(&mut self) {
        apply_fake_bus_to_robotdreams(&mut self.dreams, &self.project, self.system.servo().bus());
    }
}

pub fn model_dir() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../models/puppybot")
}

pub fn model_profile_path() -> PathBuf {
    model_dir().join("robotdreams.json")
}

pub fn project_path() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../robotdreams/project.json")
}

pub fn puppybot_model_up_axis() -> usize {
    let profile = load_model_profile(model_profile_path()).expect("load PuppyBot model profile");
    model_axis_index(
        &profile
            .frame_mapping
            .as_ref()
            .expect("frame mapping")
            .model
            .up_axis,
    )
}

pub fn distance(left: [f64; 3], right: [f64; 3]) -> f64 {
    let dx = left[0] - right[0];
    let dy = left[1] - right[1];
    let dz = left[2] - right[2];
    (dx * dx + dy * dy + dz * dz).sqrt()
}

pub fn assert_close_m(left: f64, right: f64, tolerance: f64) {
    assert!(
        (left - right).abs() <= tolerance,
        "left={left:.6} right={right:.6} diff={:.6} tolerance={tolerance:.6}",
        (left - right).abs()
    );
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

fn serial(value: &str) -> [u8; SERIAL_LEN] {
    let mut serial = [0; SERIAL_LEN];
    serial[..value.len()].copy_from_slice(value.as_bytes());
    serial
}

fn tick_for_joint_angle(joint: &JointCalibration, angle_rad: f64) -> u16 {
    let sign = if joint.angle_sign < 0 { -1.0 } else { 1.0 };
    let tick = f64::from(joint.reference_tick)
        + sign * (angle_rad - joint.reference_angle_rad) * SERVO_FULL_ROTATION_TICKS
            / std::f64::consts::TAU;
    tick.round().rem_euclid(SERVO_FULL_ROTATION_TICKS) as u16
}

fn servo_ticks_to_robotdreams_radians(tick: u16, servo: &ServoDeviceConfig) -> f64 {
    let direction = if servo.calibration.direction < 0 {
        -1.0
    } else {
        1.0
    };
    direction
        * f64::from(i32::from(tick) - i32::from(servo.calibration.zero_offset))
        * std::f64::consts::TAU
        / SERVO_FULL_ROTATION_TICKS
}

fn semantic_joint_index(name: &str) -> Option<usize> {
    match name {
        "yaw" => Some(0),
        "shoulder" => Some(1),
        "elbow" => Some(2),
        "wrist" => Some(3),
        _ => None,
    }
}

fn simulation_joint_model_mapping(semantic_name: &str) -> (i8, f64) {
    match semantic_name {
        "yaw" => (1, 0.0),
        "shoulder" => (-1, -std::f64::consts::FRAC_PI_2),
        "elbow" => (-1, std::f64::consts::FRAC_PI_2),
        "wrist" => (-1, std::f64::consts::PI),
        other => panic!("missing simulation joint mapping for {other}"),
    }
}

fn simulation_joint_calibration(
    semantic_name: &str,
    servo: &ServoDeviceConfig,
) -> JointCalibration {
    let (model_sign, model_offset_rad) = simulation_joint_model_mapping(semantic_name);
    let robotdreams_direction = servo.calibration.direction;
    let direction = if robotdreams_direction < 0 { -1.0 } else { 1.0 };
    let reference_tick = (i32::from(servo.calibration.zero_offset)
        + (direction * model_offset_rad * SERVO_FULL_ROTATION_TICKS / std::f64::consts::TAU).round()
            as i32)
        .rem_euclid(SERVO_FULL_ROTATION_TICKS as i32);

    JointCalibration {
        servo_id: u8::try_from(servo.id).expect("servo id should fit in u8"),
        tick_min: 0,
        tick_max: 4095,
        reference_tick,
        reference_angle_rad: 0.0,
        angle_sign: model_sign * robotdreams_direction,
        drive_sign: 1,
        limit_enabled: false,
    }
}

fn simulation_config_from_robotdreams_project(project: &ProjectConfig) -> PuppybotConfigV1 {
    let profile = load_model_profile(model_profile_path()).expect("load PuppyBot model profile");
    let semantic_joints = semantic_to_urdf(&profile.joint_names);
    let mut joints = [JointCalibration {
        servo_id: 1,
        tick_min: 0,
        tick_max: 4095,
        reference_tick: 2048,
        reference_angle_rad: 0.0,
        angle_sign: 1,
        drive_sign: 1,
        limit_enabled: false,
    }; JOINT_COUNT];

    for bus in &project.hardware.buses {
        for device in &bus.devices {
            let DeviceConfig::Servo(servo) = device else {
                continue;
            };
            let Some(drives) = &servo.drives else {
                continue;
            };
            let Some((semantic_name, _)) = semantic_joints
                .iter()
                .find(|(_, urdf_name)| *urdf_name == &drives.target)
            else {
                continue;
            };
            let Some(index) = semantic_joint_index(semantic_name) else {
                continue;
            };

            joints[index] = simulation_joint_calibration(semantic_name, servo);
        }
    }

    PuppybotConfigV1 {
        version: PUPPYBOT_CONFIG_VERSION,
        serial: serial("PB-SIM-0001"),
        drive: Default::default(),
        arm: PuppyArmConfig { joints },
        coordinate: Default::default(),
    }
}

fn fake_bus_with_pose(config: &PuppybotConfigV1, angles_rad: [f64; JOINT_COUNT]) -> FakeSerialBus {
    let mut bus = FakeSerialBus::new();
    for (joint, angle_rad) in config.arm.joints.iter().zip(angles_rad) {
        bus.set_servo(FakeServo::new(
            joint.servo_id,
            tick_for_joint_angle(joint, angle_rad),
        ));
    }
    bus
}

fn step_fake_bus_motion(bus: &mut FakeSerialBus) {
    for servo_id in 1..=4 {
        let Some(servo) = bus.servo(servo_id) else {
            continue;
        };
        if servo.wheel_speed == 0 {
            continue;
        }
        let direction = i32::from(servo.wheel_speed.signum());
        let next = (i32::from(servo.position) + direction * SIMULATION_STEP_TICKS).rem_euclid(4096);
        bus.set_position(servo_id, next as u16);
    }
}

fn apply_fake_bus_to_robotdreams(
    dreams: &mut RobotDreams,
    project: &ProjectConfig,
    bus: &FakeSerialBus,
) {
    for hardware_bus in &project.hardware.buses {
        for device in &hardware_bus.devices {
            let DeviceConfig::Servo(servo) = device else {
                continue;
            };
            let Some(drives) = &servo.drives else {
                continue;
            };
            let Some(fake_servo) = u8::try_from(servo.id)
                .ok()
                .and_then(|servo_id| bus.servo(servo_id))
            else {
                continue;
            };
            dreams
                .set_joint_angle(
                    &drives.target,
                    servo_ticks_to_robotdreams_radians(fake_servo.position, servo),
                )
                .expect("apply virtual servo position to RobotDreams joint");
        }
    }
}
