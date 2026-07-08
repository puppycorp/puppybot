#![allow(dead_code)]

use std::cell::RefCell;
use std::collections::VecDeque;
use std::fs;
use std::path::{Path, PathBuf};
use std::rc::Rc;

use puppybot_core::config::{
    CoordinateCalibration, JointCalibration, PuppyArmConfig, PuppybotConfigV1, SERIAL_LEN,
};
use puppybot_core::drive::{DriveActuator, DriveCommand, DriveConfig, DriveOutput};
use puppybot_core::protocol::ProtocolEvent;
use puppybot_core::puppyarm::types::{ArmCommand, ControllerError, JOINT_COUNT, PuppyarmTelemetry};
use puppybot_core::robot::{PuppyBotSystem, Puppybot};
use puppybot_core::stservo::mock::block_on_ready;
use puppybot_core::stservo::{SerialBus, StServo};
use robotdreams_core::RobotDreams;
use robotdreams_core::project::load_model_profile;
use serde_json::Value;

pub const MODEL_UP_TOLERANCE_M: f64 = 0.0015;

const SERVO_FULL_ROTATION_TICKS: f64 = 4096.0;
const SIMULATION_STEP_SECONDS: f32 = 0.02;
const SERVO_MAIN_BUS_ID: &str = "main_bus";
const DRIVE_BUS_ID: &str = "drive_bus";

struct RobotDreamsSerialBusState {
    dreams: RobotDreams,
    bus_id: String,
    drive_bus_id: String,
    read_buf: VecDeque<u8>,
    bus_events: Vec<RobotDreamsBusEvent>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RobotDreamsBusEvent {
    pub instruction: String,
    pub id: Option<u8>,
    pub target_position: Option<i16>,
    pub responded: bool,
    pub error: Option<String>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum RobotDreamsSerialBusError {
    Protocol,
}

#[derive(Clone)]
struct RobotDreamsSerialBus {
    state: Rc<RefCell<RobotDreamsSerialBusState>>,
}

#[derive(Clone)]
struct RobotDreamsDriveActuator {
    state: Rc<RefCell<RobotDreamsSerialBusState>>,
}

impl RobotDreamsDriveActuator {
    fn new(state: Rc<RefCell<RobotDreamsSerialBusState>>) -> Self {
        Self { state }
    }
}

impl DriveActuator for RobotDreamsDriveActuator {
    type Error = RobotDreamsSerialBusError;

    fn apply_drive_output(&mut self, output: DriveOutput) -> Result<(), Self::Error> {
        let mut state = self.state.borrow_mut();
        let drive_bus_id = state.drive_bus_id.clone();
        if state.dreams.set_virtual_drive_output(
            &drive_bus_id,
            "puppybot",
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

impl RobotDreamsSerialBus {
    fn new(state: Rc<RefCell<RobotDreamsSerialBusState>>) -> Self {
        Self { state }
    }
}

impl SerialBus for RobotDreamsSerialBus {
    type Error = RobotDreamsSerialBusError;

    fn write(&mut self, bytes: &[u8]) -> Result<usize, Self::Error> {
        let mut state = self.state.borrow_mut();
        let bus_id = state.bus_id.clone();
        let (response, event) = state
            .dreams
            .handle_virtual_bus_frame_with_event(&bus_id, bytes);
        let responded = response.as_ref().ok().and_then(Option::as_ref).is_some();
        state.bus_events.push(RobotDreamsBusEvent {
            instruction: event.instruction.clone(),
            id: event.id,
            target_position: event.target_position,
            responded,
            error: event.error.clone(),
        });
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
        let mut state = self.state.borrow_mut();
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

pub struct PuppybotRobotDreamsHarness {
    state: Rc<RefCell<RobotDreamsSerialBusState>>,
    system: PuppyBotSystem<RobotDreamsSerialBus, RobotDreamsDriveActuator>,
    cycle: u64,
}

pub struct RuntimeLikePuppybotRobotDreamsHarness {
    state: Rc<RefCell<RobotDreamsSerialBusState>>,
    robot: Puppybot,
    servo: StServo<RobotDreamsSerialBus>,
    drive_actuator: RobotDreamsDriveActuator,
    cycle: u64,
}

impl PuppybotRobotDreamsHarness {
    pub fn with_arm_pose(angles_rad: [f64; JOINT_COUNT]) -> Self {
        let config = runtime_config();
        let state = initialized_state(&config, angles_rad);
        let bus = RobotDreamsSerialBus::new(Rc::clone(&state));
        let drive_actuator = RobotDreamsDriveActuator::new(Rc::clone(&state));
        let system = PuppyBotSystem::with_servo_and_drive(
            Puppybot::new_with_config(&config, 0).expect("simulation PuppyBot config"),
            StServo::new(bus),
            drive_actuator,
        );
        Self {
            state,
            system,
            cycle: 0,
        }
    }

    pub fn run_arm_command(&mut self, command: ArmCommand, cycles: usize) {
        let _ = self.run_arm_command_sampled(command, cycles, 0);
    }

    pub fn run_arm_command_sampled(
        &mut self,
        command: ArmCommand,
        cycles: usize,
        sample_every_cycles: usize,
    ) -> Vec<[f64; 3]> {
        self.prime_feedback();
        let mut event = Some(ProtocolEvent::Arm(command));
        let mut samples = Vec::new();
        for cycle in 0..cycles {
            block_on_ready(self.system.run_once_at(self.cycle * 20, || event.take()));
            self.cycle = self.cycle.wrapping_add(1);
            self.advance_robotdreams();
            if sample_every_cycles > 0 && (cycle + 1) % sample_every_cycles == 0 {
                samples.push(self.tcp_position());
            }
        }
        self.advance_robotdreams();
        samples
    }

    pub fn try_run_arm_command_sampled(
        &mut self,
        command: ArmCommand,
        cycles: usize,
        sample_every_cycles: usize,
    ) -> Result<Vec<[f64; 3]>, ControllerError> {
        self.prime_feedback();
        let mut event = Some(ProtocolEvent::Arm(command));
        let samples =
            self.try_run_cycles_sampled_with_event(cycles, sample_every_cycles, || event.take())?;
        Ok(samples)
    }

    pub fn run_drive_command(&mut self, command: DriveCommand, cycles: usize) {
        let mut event = Some(ProtocolEvent::Drive(command));
        for _ in 0..cycles {
            block_on_ready(self.system.run_once_at(self.cycle * 20, || event.take()));
            self.cycle = self.cycle.wrapping_add(1);
            self.advance_robotdreams();
        }
        self.advance_robotdreams();
    }

    pub fn run_repeated_drive_command(&mut self, command: DriveCommand, cycles: usize) {
        for _ in 0..cycles {
            let mut event = Some(ProtocolEvent::Drive(command));
            block_on_ready(self.system.run_once_at(self.cycle * 20, || event.take()));
            self.cycle = self.cycle.wrapping_add(1);
            self.advance_robotdreams();
        }
        self.advance_robotdreams();
    }

    pub fn run_idle_cycles(&mut self, cycles: usize) {
        for _ in 0..cycles {
            block_on_ready(self.system.run_once_at(self.cycle * 20, || None));
            self.cycle = self.cycle.wrapping_add(1);
            self.advance_robotdreams();
        }
        self.advance_robotdreams();
    }

    pub fn base_position(&self) -> [f64; 3] {
        self.state
            .borrow()
            .dreams
            .robot_state("puppybot")
            .expect("puppybot robot state")
            .base
            .position
    }

    pub fn base_yaw(&self) -> f64 {
        self.state
            .borrow()
            .dreams
            .robot_state("puppybot")
            .expect("puppybot robot state")
            .base
            .rotation
            .expect("puppybot base rotation")[2]
    }

    pub fn clear_bus_events(&mut self) {
        self.state.borrow_mut().bus_events.clear();
    }

    pub fn bus_events(&self) -> Vec<RobotDreamsBusEvent> {
        self.state.borrow().bus_events.clone()
    }

    pub fn assert_no_bus_errors(&self) {
        let events = self.bus_events();
        let errors = events
            .iter()
            .filter(|event| event.error.is_some())
            .collect::<Vec<_>>();
        assert!(errors.is_empty(), "RobotDreams bus errors: {errors:?}");
    }

    pub fn servo_target_position(&self, servo_id: u8) -> Option<i16> {
        self.state
            .borrow()
            .dreams
            .servo_snapshots(SERVO_MAIN_BUS_ID)?
            .into_iter()
            .find(|snapshot| snapshot.id == servo_id)
            .map(|snapshot| snapshot.target_position)
    }

    pub fn servo_present_position(&self, servo_id: u8) -> Option<i16> {
        self.state
            .borrow()
            .dreams
            .servo_snapshots(SERVO_MAIN_BUS_ID)?
            .into_iter()
            .find(|snapshot| snapshot.id == servo_id)
            .map(|snapshot| snapshot.present_position)
    }

    pub fn joint_position_rad(&self, joint: &str) -> f64 {
        self.state
            .borrow()
            .dreams
            .robot_state("puppybot")
            .expect("puppybot robot state")
            .joints
            .get(joint)
            .unwrap_or_else(|| panic!("{joint} joint state"))
            .position_rad
    }

    pub fn tcp_position(&self) -> [f64; 3] {
        self.state
            .borrow()
            .dreams
            .robot_state("puppybot")
            .expect("puppybot robot state")
            .tcp
            .and_then(|tcp| tcp.location)
            .expect("puppybot TCP location")
            .position
    }

    pub fn location_position(&self, name: &str) -> [f64; 3] {
        self.state
            .borrow()
            .dreams
            .location_of(name)
            .unwrap_or_else(|| panic!("{name} location"))
            .position
    }

    pub fn arm_telemetry(&self) -> PuppyarmTelemetry {
        self.system.robot().arm_telemetry()
    }

    fn prime_feedback(&mut self) {
        for _ in 0..JOINT_COUNT {
            block_on_ready(self.system.run_once_at(self.cycle * 20, || None));
            self.cycle = self.cycle.wrapping_add(1);
            self.advance_robotdreams();
        }
    }

    fn run_cycles_sampled(&mut self, cycles: usize, sample_every_cycles: usize) -> Vec<[f64; 3]> {
        self.run_cycles_sampled_with_event(cycles, sample_every_cycles, || None)
    }

    fn run_cycles_sampled_with_event<F>(
        &mut self,
        cycles: usize,
        sample_every_cycles: usize,
        mut event: F,
    ) -> Vec<[f64; 3]>
    where
        F: FnMut() -> Option<ProtocolEvent>,
    {
        let mut samples = Vec::new();
        for cycle in 0..cycles {
            block_on_ready(self.system.run_once_at(self.cycle * 20, &mut event));
            self.cycle = self.cycle.wrapping_add(1);
            self.advance_robotdreams();
            if sample_every_cycles > 0 && (cycle + 1) % sample_every_cycles == 0 {
                samples.push(self.tcp_position());
            }
        }
        self.advance_robotdreams();
        samples
    }

    fn try_run_cycles_sampled_with_event<F>(
        &mut self,
        cycles: usize,
        sample_every_cycles: usize,
        mut event: F,
    ) -> Result<Vec<[f64; 3]>, ControllerError>
    where
        F: FnMut() -> Option<ProtocolEvent>,
    {
        let mut samples = Vec::new();
        for cycle in 0..cycles {
            block_on_ready(self.system.try_run_once_at(self.cycle * 20, &mut event))?;
            self.cycle = self.cycle.wrapping_add(1);
            self.advance_robotdreams();
            if sample_every_cycles > 0 && (cycle + 1) % sample_every_cycles == 0 {
                samples.push(self.tcp_position());
            }
        }
        self.advance_robotdreams();
        Ok(samples)
    }

    fn advance_robotdreams(&mut self) {
        self.state
            .borrow_mut()
            .dreams
            .advance_seconds(SIMULATION_STEP_SECONDS);
    }
}

impl RuntimeLikePuppybotRobotDreamsHarness {
    pub fn with_arm_pose(angles_rad: [f64; JOINT_COUNT]) -> Self {
        let config = runtime_config();
        let state = initialized_state(&config, angles_rad);
        let bus = RobotDreamsSerialBus::new(Rc::clone(&state));
        let drive_actuator = RobotDreamsDriveActuator::new(Rc::clone(&state));
        Self {
            state,
            robot: Puppybot::new_with_config(&config, 0).expect("simulation PuppyBot config"),
            servo: StServo::new(bus),
            drive_actuator,
            cycle: 0,
        }
    }

    pub fn run_repeated_drive_command(&mut self, command: DriveCommand, cycles: usize) {
        for _ in 0..cycles {
            let mut event = Some(ProtocolEvent::Drive(command));
            block_on_ready(self.robot.run_once_with_drive(
                &mut self.servo,
                &mut self.drive_actuator,
                self.cycle * 20,
                || event.take(),
            ));
            self.cycle = self.cycle.wrapping_add(1);
            self.advance_robotdreams();
        }
        self.advance_robotdreams();
    }

    pub fn base_position(&self) -> [f64; 3] {
        self.state
            .borrow()
            .dreams
            .robot_state("puppybot")
            .expect("puppybot robot state")
            .base
            .position
    }

    pub fn assert_no_bus_errors(&self) {
        let events = self.bus_events();
        let errors = events
            .iter()
            .filter(|event| event.error.is_some())
            .collect::<Vec<_>>();
        assert!(errors.is_empty(), "RobotDreams bus errors: {errors:?}");
    }

    pub fn bus_events(&self) -> Vec<RobotDreamsBusEvent> {
        self.state.borrow().bus_events.clone()
    }

    fn advance_robotdreams(&mut self) {
        self.state
            .borrow_mut()
            .dreams
            .advance_seconds(SIMULATION_STEP_SECONDS);
    }
}

fn initialized_state(
    config: &PuppybotConfigV1,
    angles_rad: [f64; JOINT_COUNT],
) -> Rc<RefCell<RobotDreamsSerialBusState>> {
    let mut dreams = RobotDreams::open(project_path()).expect("open PuppyBot RobotDreams project");
    let bus_id = SERVO_MAIN_BUS_ID.to_string();
    let drive_bus_id = DRIVE_BUS_ID.to_string();
    for (joint, angle_rad) in config.arm.joints.iter().zip(angles_rad) {
        let tick = tick_for_joint_angle(joint, angle_rad);
        assert!(
            dreams.set_virtual_servo_target(&bus_id, joint.servo_id, tick as i16),
            "initialize RobotDreams virtual servo {}",
            joint.servo_id
        );
    }
    dreams.advance_seconds(3.0);

    Rc::new(RefCell::new(RobotDreamsSerialBusState {
        dreams,
        bus_id,
        drive_bus_id,
        read_buf: VecDeque::new(),
        bus_events: Vec::new(),
    }))
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

fn tick_for_joint_angle(joint: &JointCalibration, angle_rad: f64) -> u16 {
    let sign = if joint.angle_sign < 0 { -1.0 } else { 1.0 };
    let tick = f64::from(joint.reference_tick)
        + sign * (angle_rad - joint.reference_angle_rad) * SERVO_FULL_ROTATION_TICKS
            / std::f64::consts::TAU;
    tick.round().rem_euclid(SERVO_FULL_ROTATION_TICKS) as u16
}

fn runtime_config_path() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../puppybot/runtime/puppybot.json")
}

fn runtime_config() -> PuppybotConfigV1 {
    let contents = fs::read_to_string(runtime_config_path()).expect("read PuppyBot runtime config");
    let root: Value = serde_json::from_str(&contents).expect("parse PuppyBot runtime config JSON");
    let config = PuppybotConfigV1 {
        version: u16_value(&root, &["version"]),
        serial: serial_value(&root, &["serial"]),
        drive: DriveConfig {
            left_motor_id: u8_value(&root, &["drive", "left_motor_id"]),
            right_motor_id: u8_value(&root, &["drive", "right_motor_id"]),
            steering_servo_id: u8_value(&root, &["drive", "steering_servo_id"]),
            steering_center_deg: u16_value(&root, &["drive", "steering_center_deg"]),
            steering_range_deg: u16_value(&root, &["drive", "steering_range_deg"]),
            command_timeout_ms: u64_value(&root, &["drive", "command_timeout_ms"]),
        },
        arm: PuppyArmConfig {
            joints: core::array::from_fn(|index| joint_value(&root, index)),
        },
        coordinate: CoordinateCalibration {
            forward_sign: i8_value(&root, &["coordinate", "forward_sign"]),
            left_sign: i8_value(&root, &["coordinate", "left_sign"]),
            base_yaw_offset_deg: f64_value(&root, &["coordinate", "base_yaw_offset_deg"]),
        },
    };
    config.validate().expect("valid PuppyBot runtime config");
    config
}

fn joint_value(root: &Value, index: usize) -> JointCalibration {
    let path = ["arm", "joints"];
    let joint = path_value(root, &path)
        .as_array()
        .and_then(|joints| joints.get(index))
        .unwrap_or_else(|| panic!("arm joint {index}"));
    JointCalibration {
        servo_id: u8_value(joint, &["servo_id"]),
        tick_min: i32_value(joint, &["tick_min"]),
        tick_max: i32_value(joint, &["tick_max"]),
        reference_tick: i32_value(joint, &["reference_tick"]),
        reference_angle_rad: f64_value(joint, &["reference_angle_deg"]).to_radians(),
        angle_sign: i8_value(joint, &["angle_sign"]),
        drive_sign: i8_value(joint, &["drive_sign"]),
        limit_enabled: bool_value(joint, &["limit_enabled"]),
    }
}

fn path_value<'a>(root: &'a Value, path: &[&str]) -> &'a Value {
    let mut value = root;
    for key in path {
        value = value
            .get(*key)
            .unwrap_or_else(|| panic!("missing JSON field {}", path.join(".")));
    }
    value
}

fn bool_value(root: &Value, path: &[&str]) -> bool {
    path_value(root, path)
        .as_bool()
        .unwrap_or_else(|| panic!("{} must be bool", path.join(".")))
}

fn f64_value(root: &Value, path: &[&str]) -> f64 {
    path_value(root, path)
        .as_f64()
        .unwrap_or_else(|| panic!("{} must be number", path.join(".")))
}

fn i8_value(root: &Value, path: &[&str]) -> i8 {
    path_value(root, path)
        .as_i64()
        .and_then(|value| i8::try_from(value).ok())
        .unwrap_or_else(|| panic!("{} must fit in i8", path.join(".")))
}

fn i32_value(root: &Value, path: &[&str]) -> i32 {
    path_value(root, path)
        .as_i64()
        .and_then(|value| i32::try_from(value).ok())
        .unwrap_or_else(|| panic!("{} must fit in i32", path.join(".")))
}

fn u8_value(root: &Value, path: &[&str]) -> u8 {
    path_value(root, path)
        .as_u64()
        .and_then(|value| u8::try_from(value).ok())
        .unwrap_or_else(|| panic!("{} must fit in u8", path.join(".")))
}

fn u16_value(root: &Value, path: &[&str]) -> u16 {
    path_value(root, path)
        .as_u64()
        .and_then(|value| u16::try_from(value).ok())
        .unwrap_or_else(|| panic!("{} must fit in u16", path.join(".")))
}

fn u64_value(root: &Value, path: &[&str]) -> u64 {
    path_value(root, path)
        .as_u64()
        .unwrap_or_else(|| panic!("{} must fit in u64", path.join(".")))
}

fn serial_value(root: &Value, path: &[&str]) -> [u8; SERIAL_LEN] {
    let value = path_value(root, path)
        .as_str()
        .unwrap_or_else(|| panic!("{} must be string", path.join(".")));
    assert!(
        value.len() <= SERIAL_LEN,
        "{} must fit in {SERIAL_LEN} bytes",
        path.join(".")
    );
    let mut serial = [0; SERIAL_LEN];
    serial[..value.len()].copy_from_slice(value.as_bytes());
    serial
}
