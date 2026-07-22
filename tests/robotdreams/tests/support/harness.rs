#![allow(dead_code)]

use std::cell::RefCell;
use std::collections::VecDeque;
use std::fs;
use std::path::{Path, PathBuf};
use std::rc::Rc;
use std::sync::atomic::{AtomicUsize, Ordering};

use puppybot_core::config::{
    CoordinateCalibration, JointCalibration, PuppyArmConfig, PuppybotConfigV1, SERIAL_LEN,
};
use puppybot_core::drive::{DriveActuator, DriveCommand, DriveConfig, DriveOutput};
use puppybot_core::protocol::ProtocolEvent;
use puppybot_core::puppyarm::types::{ArmCommand, ControllerError, PuppyarmTelemetry, JOINT_COUNT};
use puppybot_core::robot::{PuppyBotSystem, Puppybot};
use puppybot_core::stservo::mock::block_on_ready;
use puppybot_core::stservo::{SerialBus, StServo};
use robotdreams_core::project::load_model_profile;
use robotdreams_core::{RigidTransform, RobotDreams, VirtualServoJointMapping};
use serde_json::Value;

#[path = "../../../../puppybot/runtime/src/sim_calibration.rs"]
mod sim_calibration;
use sim_calibration::derive_simulation_joint_mappings;

pub const MODEL_UP_TOLERANCE_M: f64 = 0.0015;

const SERVO_FULL_ROTATION_TICKS: f64 = 4096.0;
const SIMULATION_STEP_SECONDS: f32 = 0.02;
const SERVO_MAIN_BUS_ID: &str = "main_bus";
const DRIVE_BUS_ID: &str = "drive_bus";
const DRIVE_CLEAR_LANE_REMOVED_OBJECTS: [&str; 5] = [
    "trashbin",
    "trashbin_wall_front",
    "trashbin_wall_back",
    "trashbin_wall_left",
    "trashbin_wall_right",
];
static DRIVE_PROJECT_SEQUENCE: AtomicUsize = AtomicUsize::new(0);

#[derive(Clone, Copy)]
enum SimulationProject {
    Canonical,
    UnobstructedDriveLane,
}

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
        Self::with_arm_pose_for_project(angles_rad, SimulationProject::Canonical)
    }

    pub fn with_arm_pose_on_unobstructed_drive_lane(angles_rad: [f64; JOINT_COUNT]) -> Self {
        Self::with_arm_pose_for_project(angles_rad, SimulationProject::UnobstructedDriveLane)
    }

    fn with_arm_pose_for_project(
        angles_rad: [f64; JOINT_COUNT],
        project: SimulationProject,
    ) -> Self {
        let config = runtime_config();
        let state = initialized_state(&config, angles_rad, project);
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

    pub fn with_arm_pose_without_physics(angles_rad: [f64; JOINT_COUNT]) -> Self {
        let config = runtime_config();
        let state = initialized_state_without_physics(&config, angles_rad);
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

    pub fn run_arm_command_until_settled(
        &mut self,
        command: ArmCommand,
        max_cycles: usize,
    ) -> usize {
        self.prime_feedback();
        let mut event = Some(ProtocolEvent::Arm(command));
        let mut saw_target = false;
        for cycle in 1..=max_cycles {
            block_on_ready(self.system.run_once_at(self.cycle * 20, || event.take()));
            self.cycle = self.cycle.wrapping_add(1);
            self.advance_robotdreams();
            let telemetry = self.arm_telemetry();
            let has_target = telemetry
                .joints
                .iter()
                .any(|joint| joint.target_tick.is_some());
            saw_target |= has_target;
            if saw_target && !has_target {
                self.advance_robotdreams();
                return cycle;
            }
        }
        panic!("arm command did not settle within {max_cycles} cycles: {command:?}");
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

    pub fn run_arm_command_state_sampled(
        &mut self,
        command: ArmCommand,
        cycles: usize,
        sample_every_cycles: usize,
    ) -> Vec<(PuppyarmTelemetry, [f64; 3])> {
        self.prime_feedback();
        let mut event = Some(ProtocolEvent::Arm(command));
        let mut samples = Vec::new();
        for cycle in 0..cycles {
            block_on_ready(self.system.run_once_at(self.cycle * 20, || event.take()));
            self.cycle = self.cycle.wrapping_add(1);
            self.advance_robotdreams();
            if (cycle + 1) % sample_every_cycles == 0 {
                samples.push((self.arm_telemetry(), self.tcp_position()));
            }
        }
        self.advance_robotdreams();
        samples
    }

    pub fn run_held_arm_command_state_sampled(
        &mut self,
        command: ArmCommand,
        cycles: usize,
        refresh_every_cycles: usize,
        sample_every_cycles: usize,
    ) -> Vec<(PuppyarmTelemetry, [f64; 3])> {
        self.prime_feedback();
        let mut samples = Vec::new();
        for cycle in 0..cycles {
            let event =
                ((cycle % refresh_every_cycles) == 0).then_some(ProtocolEvent::Arm(command));
            block_on_ready(self.system.run_once_at(self.cycle * 20, || event));
            self.cycle = self.cycle.wrapping_add(1);
            self.advance_robotdreams();
            if (cycle + 1) % sample_every_cycles == 0 {
                samples.push((self.arm_telemetry(), self.tcp_position()));
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

    pub fn frame_world_transform(&self, frame: &str) -> RigidTransform {
        self.state
            .borrow()
            .dreams
            .frame_state("puppybot", frame)
            .unwrap_or_else(|| panic!("PuppyBot frame {frame}"))
            .world_transform
    }

    pub fn set_urdf_from_analytic_pose(&mut self, angles_rad: [f64; JOINT_COUNT]) {
        let contents =
            fs::read_to_string(model_profile_path()).expect("read PuppyBot model profile");
        let profile: Value = serde_json::from_str(&contents).expect("parse PuppyBot model profile");
        assert_eq!(
            path_value(&profile, &["analyticToUrdf", "unit"]).as_str(),
            Some("rad")
        );
        for (semantic, angle_rad) in ["yaw", "shoulder", "elbow", "wrist"]
            .into_iter()
            .zip(angles_rad)
        {
            let mapping = path_value(&profile, &["analyticToUrdf", "joints", semantic]);
            let joint = path_value(mapping, &["joint"])
                .as_str()
                .expect("analyticToUrdf joint name");
            let urdf_angle =
                angle_rad * f64_value(mapping, &["scale"]) + f64_value(mapping, &["offset"]);
            self.state
                .borrow_mut()
                .dreams
                .set_joint_angle(joint, urdf_angle)
                .unwrap_or_else(|error| {
                    panic!("set analytic {semantic} on URDF joint {joint}: {error}")
                });
        }
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

    pub fn preview_target_angles(
        &self,
        coords_mm: [f64; 3],
        tool_pitch_rad: f64,
    ) -> Option<[f64; JOINT_COUNT]> {
        self.system.robot().arm.preview_target_angles(
            coords_mm[0],
            coords_mm[1],
            coords_mm[2],
            tool_pitch_rad,
        )
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
        Self::with_arm_pose_for_project(angles_rad, SimulationProject::Canonical)
    }

    pub fn with_arm_pose_on_unobstructed_drive_lane(angles_rad: [f64; JOINT_COUNT]) -> Self {
        Self::with_arm_pose_for_project(angles_rad, SimulationProject::UnobstructedDriveLane)
    }

    fn with_arm_pose_for_project(
        angles_rad: [f64; JOINT_COUNT],
        project: SimulationProject,
    ) -> Self {
        let config = runtime_config();
        let state = initialized_state(&config, angles_rad, project);
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
    project: SimulationProject,
) -> Rc<RefCell<RobotDreamsSerialBusState>> {
    let (path, remove_after_open) = simulation_project_path(project);
    let mut dreams = RobotDreams::open(&path).expect("open PuppyBot RobotDreams project");
    if remove_after_open {
        fs::remove_file(path).expect("remove unobstructed PuppyBot drive project");
    }
    install_simulation_mappings(&mut dreams, config);
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

fn initialized_state_without_physics(
    config: &PuppybotConfigV1,
    angles_rad: [f64; JOINT_COUNT],
) -> Rc<RefCell<RobotDreamsSerialBusState>> {
    let mut dreams = RobotDreams::open(project_path()).expect("open PuppyBot RobotDreams project");
    install_simulation_mappings(&mut dreams, config);
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

    let contents = fs::read_to_string(model_profile_path()).expect("read PuppyBot model profile");
    let profile: Value = serde_json::from_str(&contents).expect("parse PuppyBot model profile");
    for (semantic, angle_rad) in ["yaw", "shoulder", "elbow", "wrist"]
        .into_iter()
        .zip(angles_rad)
    {
        let mapping = path_value(&profile, &["analyticToUrdf", "joints", semantic]);
        let urdf_joint = path_value(mapping, &["joint"])
            .as_str()
            .expect("analyticToUrdf joint name");
        let urdf_angle =
            angle_rad * f64_value(mapping, &["scale"]) + f64_value(mapping, &["offset"]);
        dreams
            .set_joint_angle(urdf_joint, urdf_angle)
            .unwrap_or_else(|error| panic!("set no-physics {semantic} pose: {error}"));
    }

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

fn simulation_project_path(project: SimulationProject) -> (PathBuf, bool) {
    match project {
        SimulationProject::Canonical => (project_path(), false),
        SimulationProject::UnobstructedDriveLane => (unobstructed_drive_project_path(), true),
    }
}

fn unobstructed_drive_project_path() -> PathBuf {
    let source_path = project_path();
    let contents = fs::read_to_string(&source_path).expect("read canonical PuppyBot project");
    let mut project: Value =
        serde_json::from_str(&contents).expect("parse canonical PuppyBot project");
    project["modelProfile"] = Value::String(model_profile_path().display().to_string());
    project["robots"][0]["model"]["path"] = Value::String(
        model_dir()
            .join("final2/urdf/final2.urdf")
            .display()
            .to_string(),
    );
    project["robots"][0]["physics"]["vehicle"]["collisionProfile"] = Value::String(
        source_path
            .parent()
            .expect("canonical project parent")
            .join("puppybot-physics-prototype.json")
            .display()
            .to_string(),
    );
    project["robots"][0]["physics"]["linkCollisionProfile"] = Value::String(
        source_path
            .parent()
            .expect("canonical project parent")
            .join("collision/final2-link-collision-profile.v1.json")
            .display()
            .to_string(),
    );
    let objects = project["scene"]["objects"]
        .as_array_mut()
        .expect("canonical project scene objects");
    objects.retain(|object| {
        object["id"]
            .as_str()
            .is_none_or(|id| !DRIVE_CLEAR_LANE_REMOVED_OBJECTS.contains(&id))
    });

    let sequence = DRIVE_PROJECT_SEQUENCE.fetch_add(1, Ordering::Relaxed);
    let path = std::env::temp_dir().join(format!(
        "puppybot-unobstructed-drive-{}-{sequence}.robotdreams.json",
        std::process::id()
    ));
    fs::write(
        &path,
        serde_json::to_vec_pretty(&project).expect("serialize unobstructed PuppyBot drive project"),
    )
    .expect("write unobstructed PuppyBot drive project");
    path
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

pub fn runtime_config() -> PuppybotConfigV1 {
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

pub fn install_simulation_mappings(dreams: &mut RobotDreams, config: &PuppybotConfigV1) {
    let mappings = derive_simulation_joint_mappings(project_path(), config)
        .expect("derive RobotDreams session servo mappings");
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
        .expect("install RobotDreams session servo mappings");
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
