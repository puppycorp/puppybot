use puppybot_core::drive::DriveCommand;
use puppybot_core::stservo::angle_to_position;

use harness::{
    assert_close_m, distance, PuppybotRobotDreamsHarness, RobotDreamsBusEvent,
    RuntimeLikePuppybotRobotDreamsHarness,
};

#[path = "support/harness.rs"]
mod harness;

const DRIVE_Z_TOLERANCE_M: f64 = 0.001;
const DRIVE_STATIONARY_TOLERANCE_M: f64 = 0.001;
const ARM_YAW_SERVO_ID: u8 = 1;
const STEERING_SERVO_ID: u8 = 5;
const STEERING_CENTER_DEG: u16 = 90;
const STEERING_LEFT_DEG: u16 = 66;
const STEERING_RIGHT_DEG: u16 = 114;
const FRONT_LEFT_STEERING_JOINT: &str = "revolute_4";
const FRONT_RIGHT_STEERING_JOINT: &str = "revolute_6";

fn test_harness() -> PuppybotRobotDreamsHarness {
    PuppybotRobotDreamsHarness::with_arm_pose([
        0.0,
        std::f64::consts::FRAC_PI_2,
        std::f64::consts::FRAC_PI_2,
        std::f64::consts::FRAC_PI_2,
    ])
}

fn unobstructed_drive_test_harness() -> PuppybotRobotDreamsHarness {
    PuppybotRobotDreamsHarness::with_arm_pose_on_unobstructed_drive_lane([
        0.0,
        std::f64::consts::FRAC_PI_2,
        std::f64::consts::FRAC_PI_2,
        std::f64::consts::FRAC_PI_2,
    ])
}

fn unobstructed_runtime_like_test_harness() -> RuntimeLikePuppybotRobotDreamsHarness {
    RuntimeLikePuppybotRobotDreamsHarness::with_arm_pose_on_unobstructed_drive_lane([
        0.0,
        std::f64::consts::FRAC_PI_2,
        std::f64::consts::FRAC_PI_2,
        std::f64::consts::FRAC_PI_2,
    ])
}

fn drive_steer(throttle: i8, steering: i8) -> DriveCommand {
    DriveCommand::DriveSteer { throttle, steering }
}

fn steering_center_position() -> i16 {
    angle_to_position(STEERING_CENTER_DEG) as i16
}

fn steering_position(angle_deg: u16) -> i16 {
    angle_to_position(angle_deg) as i16
}

fn steering_center_write(events: &[RobotDreamsBusEvent]) -> Option<&RobotDreamsBusEvent> {
    events.iter().find(|event| {
        event.id == Some(STEERING_SERVO_ID)
            && event.target_position == Some(steering_center_position())
    })
}

fn assert_front_steering_joints(harness: &PuppybotRobotDreamsHarness, expected_rad: f64) {
    let left = harness.joint_position_rad(FRONT_LEFT_STEERING_JOINT);
    let right = harness.joint_position_rad(FRONT_RIGHT_STEERING_JOINT);
    assert!(
        (left - expected_rad).abs() <= 1.0e-9,
        "left front steering joint should be {expected_rad:.6} rad, got {left:.6}"
    );
    assert!(
        (right - expected_rad).abs() <= 1.0e-9,
        "right front steering joint should be {expected_rad:.6} rad, got {right:.6}"
    );
}

#[test]
fn drive_forward_x_increases_z_no_change() {
    let mut harness = unobstructed_drive_test_harness();
    let start = harness.base_position();
    harness.clear_bus_events();

    harness.run_repeated_drive_command(drive_steer(50, 0), 50);
    let moved = harness.base_position();

    harness.assert_no_bus_errors();
    assert!(
        moved[0] > start[0] + 0.05,
        "forward drive should increase ROS X: start={start:?} moved={moved:?}"
    );
    assert_close_m(moved[2], start[2], DRIVE_Z_TOLERANCE_M);
}

#[test]
fn runtime_like_drive_forward_x_increases_z_no_change() {
    let mut harness = unobstructed_runtime_like_test_harness();
    let start = harness.base_position();

    harness.run_repeated_drive_command(drive_steer(50, 0), 50);
    let moved = harness.base_position();

    harness.assert_no_bus_errors();
    assert!(
        moved[0] > start[0] + 0.05,
        "runtime-like forward drive should increase ROS X through the RobotDreams bridge: start={start:?} moved={moved:?}"
    );
    assert_close_m(moved[2], start[2], DRIVE_Z_TOLERANCE_M);
}

#[test]
fn drive_forward_centers_steering_servo_5_over_serial() {
    let mut harness = test_harness();
    harness.clear_bus_events();

    harness.run_drive_command(drive_steer(50, 0), 1);
    let events = harness.bus_events();
    let steering_event = steering_center_write(&events)
        .unwrap_or_else(|| panic!("missing steering center write in events: {events:?}"));

    harness.assert_no_bus_errors();
    assert!(
        steering_event.responded,
        "steering servo write should receive a RobotDreams serial response: {steering_event:?}"
    );
    assert_eq!(
        harness.servo_target_position(STEERING_SERVO_ID),
        Some(steering_center_position())
    );
}

#[test]
fn drive_left_turns_steering_servo_5_and_front_wheel_joints() {
    let mut harness = test_harness();
    harness.clear_bus_events();

    harness.run_drive_command(drive_steer(0, -55), 1);
    let events = harness.bus_events();
    let expected_position = steering_position(STEERING_LEFT_DEG);
    let steering_event = events
        .iter()
        .find(|event| {
            event.id == Some(STEERING_SERVO_ID) && event.target_position == Some(expected_position)
        })
        .unwrap_or_else(|| panic!("missing steering left write in events: {events:?}"));

    harness.assert_no_bus_errors();
    assert!(
        steering_event.responded,
        "steering servo write should receive a RobotDreams serial response: {steering_event:?}"
    );
    assert_eq!(
        harness.servo_target_position(STEERING_SERVO_ID),
        Some(expected_position)
    );
    assert_front_steering_joints(
        &harness,
        f64::from(STEERING_LEFT_DEG as i16 - STEERING_CENTER_DEG as i16).to_radians(),
    );
}

#[test]
fn drive_right_turns_front_wheel_joints() {
    let mut harness = test_harness();
    harness.clear_bus_events();

    harness.run_drive_command(drive_steer(0, 55), 1);

    harness.assert_no_bus_errors();
    assert_front_steering_joints(
        &harness,
        f64::from(STEERING_RIGHT_DEG as i16 - STEERING_CENTER_DEG as i16).to_radians(),
    );
}

#[test]
fn drive_forward_does_not_write_arm_yaw_servo_1() {
    let mut harness = test_harness();
    harness.clear_bus_events();

    harness.run_drive_command(drive_steer(50, 0), 1);
    let events = harness.bus_events();

    harness.assert_no_bus_errors();
    assert!(
        !events.iter().any(|event| event.id == Some(ARM_YAW_SERVO_ID)
            && event.target_position == Some(steering_center_position())),
        "drive forward should not send steering center to arm yaw servo: {events:?}"
    );
}

#[test]
fn drive_back_x_decreases_z_no_change() {
    let mut harness = unobstructed_drive_test_harness();
    let start = harness.base_position();

    harness.run_repeated_drive_command(drive_steer(-50, 0), 50);
    let moved = harness.base_position();

    assert!(
        moved[0] < start[0] - 0.05,
        "back drive should decrease ROS X: start={start:?} moved={moved:?}"
    );
    assert_close_m(moved[2], start[2], DRIVE_Z_TOLERANCE_M);
}

#[test]
fn drive_forward_positive_right_steering_yaw_decreases() {
    let mut harness = unobstructed_drive_test_harness();
    let start_yaw = harness.base_yaw();

    harness.run_repeated_drive_command(drive_steer(50, 50), 50);
    let moved_yaw = harness.base_yaw();

    assert!(
        moved_yaw < start_yaw - 0.1,
        "positive/right steering should decrease ROS yaw: start_yaw={start_yaw:.6} moved_yaw={moved_yaw:.6}"
    );
}

#[test]
fn drive_backward_positive_right_steering_yaw_increases() {
    let mut harness = unobstructed_drive_test_harness();
    let start_yaw = harness.base_yaw();

    harness.run_repeated_drive_command(drive_steer(-50, 50), 50);
    let moved_yaw = harness.base_yaw();

    assert!(
        moved_yaw > start_yaw + 0.1,
        "positive/right steering while reversing should increase ROS yaw: start_yaw={start_yaw:.6} moved_yaw={moved_yaw:.6}"
    );
}

#[test]
fn drive_forward_into_canonical_bin_wall_is_blocked() {
    let mut harness = test_harness();
    let start = harness.base_position();

    harness.run_repeated_drive_command(drive_steer(50, 0), 50);
    let moved = harness.base_position();

    harness.assert_no_bus_errors();
    assert!(
        moved[0] > start[0] + 0.001,
        "the live vehicle should reach the canonical bin wall: start={start:?} moved={moved:?}"
    );
    assert!(
        moved[0] < start[0] + 0.05,
        "the live vehicle must not pass through the canonical bin wall: start={start:?} moved={moved:?}"
    );
    assert_close_m(moved[2], start[2], DRIVE_Z_TOLERANCE_M);
}

#[test]
fn drive_stop_holds_base_position() {
    let mut harness = test_harness();

    harness.run_repeated_drive_command(drive_steer(50, 0), 20);
    harness.run_drive_command(DriveCommand::Stop, 1);
    let stopped = harness.base_position();
    harness.run_idle_cycles(30);
    let after_idle = harness.base_position();

    assert!(
        distance(stopped, after_idle) <= DRIVE_STATIONARY_TOLERANCE_M,
        "stop should hold base position: stopped={stopped:?} after_idle={after_idle:?}"
    );
}

#[test]
fn drive_command_timeout_holds_base_position() {
    let mut harness = test_harness();

    harness.run_drive_command(drive_steer(50, 0), 30);
    let timed_out = harness.base_position();
    harness.run_idle_cycles(30);
    let after_idle = harness.base_position();

    assert!(
        distance(timed_out, after_idle) <= DRIVE_STATIONARY_TOLERANCE_M,
        "drive timeout should hold base position: timed_out={timed_out:?} after_idle={after_idle:?}"
    );
}
