use core::f64::consts::PI;

use super::{
    kinematics::*,
    puppyarm::{ArmCommand, PuppyArm},
    servo_safety::*,
    types::{JOINT_COUNT, Joint},
};

const EPS: f64 = 1.0e-6;

fn assert_close(left: f64, right: f64) {
    assert!(
        (left - right).abs() <= EPS,
        "left={left} right={right} diff={}",
        (left - right).abs()
    );
}

#[test]
fn fk_straight_forward_pose_maps_to_negative_x_extent() {
    let (x, y, z) = fk(0.0, 0.0, 0.0, 0.0);
    assert_close(x, -432.0);
    assert_close(y, 0.0);
    assert_close(z, 0.0);
}

#[test]
fn fk_tip_down_pose_adds_tool_height_in_z() {
    let (x, y, z) = fk(0.0, 0.0, 0.0, PI / 2.0);
    assert_close(x, -302.0);
    assert_close(y, 0.0);
    assert_close(z, -130.0);
}

#[test]
fn ik_straight_reach_along_x_uses_roboband_yaw_convention() {
    let result = ik(ARM_L1_MM + ARM_L2_MM, 0.0, -ARM_L3_MM);
    assert!(result.reachable);
    assert_close(result.yaw, PI);
    assert_close(result.shoulder, 0.0);
    assert_close(result.elbow, 0.0);
}

#[test]
fn ik_target_along_positive_y_has_positive_half_pi_yaw() {
    let result = ik(0.0, ARM_L1_MM + ARM_L2_MM, -ARM_L3_MM);
    assert!(result.reachable);
    assert_close(result.yaw, PI / 2.0);
}

#[test]
fn ik_fk_round_trip_for_reachable_target() {
    let result = ik(200.0, 0.0, 0.0);
    assert!(result.reachable);
    let (x, y, z) = fk(
        result.yaw,
        result.shoulder,
        result.elbow,
        solve_tip_angle_down(result.shoulder, result.elbow, ARM_TOOL_PHI_RAD),
    );
    assert_close(x, 200.0);
    assert_close(y, 0.0);
    assert_close(z, 0.0);
}

#[test]
fn solve_coords_with_tool_pitch_round_trips_requested_pose() {
    let tool_phi = -PI / 4.0;
    let (yaw, shoulder, elbow, wrist) =
        solve_coords_with_tool_pitch(180.0, 40.0, 20.0, tool_phi).unwrap();
    let (x, y, z) = fk(yaw, shoulder, elbow, wrist);
    assert_close(x, 180.0);
    assert_close(y, 40.0);
    assert_close(z, 20.0);
    assert_close(wrap_pi(shoulder - elbow - wrist), tool_phi);
}

#[test]
fn solve_coords_rejects_unreachable_target() {
    assert_eq!(
        solve_coords_tool_down(ARM_L1_MM + ARM_L2_MM + 500.0, 0.0, 0.0),
        Err(IkError::Unreachable)
    );
}

#[test]
fn hold_requires_feedback() {
    let mut arm = PuppyArm::new(0);

    arm.handle_arm_cmd(ArmCommand::Hold, 0);

    assert!(arm.telemetry_snapshot(0).joints[0].target_tick.is_none());
}

#[test]
fn hold_targets_current_feedback_ticks() {
    let mut arm = PuppyArm::new(0);
    for index in 0..JOINT_COUNT {
        arm.record_feedback(index, 1000 + index as u16, 0);
    }

    arm.handle_arm_cmd(ArmCommand::Hold, 10);
    let telemetry = arm.telemetry_snapshot(0);

    assert_eq!(telemetry.joints[0].target_tick, Some(1000));
    assert_eq!(telemetry.joints[3].target_tick, Some(1003));
}

#[test]
fn goto_coords_rejects_unreachable_target() {
    let mut arm = PuppyArm::new(0);

    arm.handle_arm_cmd(
        ArmCommand::GotoCoords {
            x: 1000.0,
            y: 0.0,
            z: 0.0,
        },
        10,
    );

    assert!(arm.telemetry_snapshot(0).joints[0].target_tick.is_none());
}

#[test]
fn set_speed_updates_active_spin_on_next_step() {
    let mut arm = PuppyArm::new(0);
    arm.record_feedback(0, 0, 0);
    arm.handle_arm_cmd(
        ArmCommand::Spin {
            joint: 0,
            direction: 1,
        },
        0,
    );
    arm.handle_arm_cmd(ArmCommand::SetSpeed(321), 10);

    let commands = arm.update(10);

    assert_eq!(commands[0].speed, 321);
}

#[test]
fn target_error_prefers_small_wrap_near_deadband() {
    assert_eq!(target_tick_error(2, 4094), 4);
}

#[test]
fn target_error_keeps_large_naive_error_when_wrap_is_not_near_target() {
    assert_eq!(target_tick_error(100, 3900), -3800);
}

#[test]
fn limit_blocks_only_when_moving_farther_out() {
    let mut joint = Joint::new(1, 100, 200);
    joint.tick = Some(200);
    assert!(limit_blocks_for_speed(&joint, 50));
    assert!(!limit_blocks_for_speed(&joint, -50));
}

#[test]
fn joint_limit_exceeded_blocks_farther_out_motion() {
    let mut joint = Joint::new(1, 100, 200);
    joint.tick = Some(250);

    assert!(is_outside_limits(&joint));
    assert!(limit_blocks_for_speed(&joint, 80));
}

#[test]
fn joint_limit_exceeded_allows_return_toward_valid_range() {
    let mut joint = Joint::new(1, 100, 200);
    joint.tick = Some(250);

    assert!(is_outside_limits(&joint));
    assert!(!limit_blocks_for_speed(&joint, -80));
}

#[test]
fn wrapped_tick_limits_behave_near_zero() {
    let mut joint = Joint::new(1, 4000, 100);
    joint.tick = Some(100);

    assert!(!is_outside_limits(&joint));
    assert!(limit_blocks_for_speed(&joint, 80));
    assert!(!limit_blocks_for_speed(&joint, -80));
}

#[test]
fn negative_min_limit_treats_high_modulo_tick_as_inside() {
    let mut joint = Joint::new(1, -500, 1300);
    joint.tick = Some(3976);

    assert!(!is_outside_limits(&joint));
    assert!(!limit_blocks_for_speed(&joint, 120));
    assert!(!limit_blocks_for_speed(&joint, -120));
}

#[test]
fn extended_max_limit_allows_motion_back_toward_interval() {
    let mut joint = Joint::new(1, 3300, 4100);
    joint.tick = Some(88);

    assert!(is_outside_limits(&joint));
    assert!(limit_blocks_for_speed(&joint, 120));
    assert!(!limit_blocks_for_speed(&joint, -120));
}

#[test]
fn unrelated_joint_limit_does_not_block_yaw_jog() {
    let mut safety = default_arm_safety(0);
    safety.record_feedback(0, 0, 0).unwrap();
    safety.record_feedback(3, TIP_TICK_MAX + 4, 0).unwrap();
    safety.spin(0, 1, 0).unwrap();

    let commands = safety.speed_commands(10);

    assert!(is_outside_limits(&safety.joints[3]));
    assert_eq!(commands[0].speed, safety.default_speed);
}

#[test]
fn disabled_limits_allow_target_motion() {
    let mut safety = ServoSafety::new([Joint::new(1, 4000, 100)], 0);
    safety.default_speed = 80;
    safety.joints[0].limit_enabled = false;
    safety.record_feedback(0, 2000, 0).unwrap();
    safety.goto_ticks(&[4050], 0).unwrap();

    let commands = safety.speed_commands(10);

    assert_eq!(commands[0].speed, 80);
}

#[test]
fn goto_ticks_uses_default_speed() {
    let mut safety = ServoSafety::new([Joint::new(1, -1000, 1000)], 0);
    safety.default_speed = 80;
    safety.record_feedback(0, 0, 0).unwrap();
    safety.goto_ticks(&[100], 0).unwrap();

    let commands = safety.speed_commands(10);

    assert_eq!(commands[0].speed, 80);
}

#[test]
fn goto_ticks_stops_at_target() {
    let mut safety = ServoSafety::new([Joint::new(1, -1000, 1000)], 0);
    safety.default_speed = 80;
    safety.record_feedback(0, 100, 0).unwrap();
    safety.goto_ticks(&[100], 0).unwrap();

    let commands = safety.speed_commands(10);

    assert_eq!(commands[0].speed, 0);
    assert_eq!(safety.joints[0].target_tick, None);
}

#[test]
fn goto_ticks_stops_within_deadband() {
    let mut safety = ServoSafety::new([Joint::new(1, -1000, 1000)], 0);
    safety.default_speed = 80;
    safety.record_feedback(0, 96, 0).unwrap();
    safety.goto_ticks(&[100], 0).unwrap();

    let commands = safety.speed_commands(10);

    assert_eq!(commands[0].speed, 0);
    assert_eq!(safety.joints[0].target_tick, None);
}

#[test]
fn goto_ticks_reduces_speed_when_close() {
    let mut safety = ServoSafety::new([Joint::new(1, -1000, 1000)], 0);
    safety.default_speed = 80;
    safety.record_feedback(0, 40, 0).unwrap();
    safety.goto_ticks(&[100], 0).unwrap();

    let commands = safety.speed_commands(10);

    assert_eq!(commands[0].speed, 60);
}

#[test]
fn stop_cancels_active_target() {
    let mut safety = ServoSafety::new([Joint::new(1, -1000, 1000)], 0);
    safety.record_feedback(0, 0, 0).unwrap();
    safety.goto_ticks(&[100], 0).unwrap();

    safety.stop_joint(0, 10).unwrap();

    assert_eq!(safety.joints[0].target_tick, None);
    assert_eq!(safety.joints[0].speed, 0);
}

#[test]
fn zero_default_speed_stops_spinning_joint() {
    let mut safety = ServoSafety::new([Joint::new(1, -1000, 1000)], 0);
    safety.default_speed = 200;
    safety.record_feedback(0, 0, 0).unwrap();
    safety.spin(0, 1, 0).unwrap();
    safety.set_default_speed(0, 10);

    let commands = safety.speed_commands(10);

    assert_eq!(commands[0].speed, 0);
}

#[test]
fn zero_default_speed_stops_active_goto_motion() {
    let mut safety = ServoSafety::new([Joint::new(1, -1000, 1000)], 0);
    safety.default_speed = 200;
    safety.record_feedback(0, 0, 0).unwrap();
    safety.goto_ticks(&[500], 0).unwrap();
    safety.set_default_speed(0, 10);

    let commands = safety.speed_commands(10);

    assert_eq!(commands[0].speed, 0);
    assert_eq!(safety.joints[0].target_tick, Some(500));
}

#[test]
fn target_tracking_speed_scales_with_positive_tick_error() {
    let mut safety = ServoSafety::new([Joint::new(1, -1000, 1000)], 0);
    safety.default_speed = 200;
    safety.record_feedback(0, 40, 0).unwrap();
    safety.goto_ticks(&[80], 0).unwrap();

    let commands = safety.speed_commands(10);

    assert_eq!(commands[0].speed, 100);
}

#[test]
fn target_tracking_speed_scales_with_negative_tick_error() {
    let mut safety = ServoSafety::new([Joint::new(1, -1000, 1000)], 0);
    safety.default_speed = 200;
    safety.record_feedback(0, 80, 0).unwrap();
    safety.goto_ticks(&[40], 0).unwrap();

    let commands = safety.speed_commands(10);

    assert_eq!(commands[0].speed, -100);
}

#[test]
fn slew_limit_bounds_acceleration() {
    let mut safety = ServoSafety::new([Joint::new(1, -2000, 2000)], 0);
    safety.default_speed = 400;
    safety.record_feedback(0, 0, 0).unwrap();
    safety.goto_ticks(&[1000], 0).unwrap();
    safety.mark_speed_sent(0, 0, 0).unwrap();

    let commands = safety.speed_commands(10);

    assert_eq!(commands[0].speed, 200);
}

#[test]
fn slew_limit_bounds_deceleration() {
    let mut safety = ServoSafety::new([Joint::new(1, -2000, 2000)], 0);
    safety.default_speed = 400;
    safety.record_feedback(0, 0, 0).unwrap();
    safety.goto_ticks(&[20], 0).unwrap();
    safety.mark_speed_sent(0, 400, 0).unwrap();

    let commands = safety.speed_commands(10);

    assert_eq!(commands[0].speed, 100);
}

#[test]
fn stale_feedback_forces_zero_speed() {
    let mut safety = default_arm_safety(0);
    safety.record_feedback(0, 0, 0).unwrap();
    safety.spin(0, 1, 0).unwrap();
    safety
        .record_feedback(1, 200, JOINT_FEEDBACK_TIMEOUT_MS + 1)
        .unwrap();
    let commands = safety.speed_commands(JOINT_FEEDBACK_TIMEOUT_MS + 1);
    assert_eq!(commands[0].speed, 0);
    assert_eq!(safety.joints[0].fault, Some(SafetyFault::FeedbackStale));
}

#[test]
fn deadman_stops_free_spin() {
    let mut safety = default_arm_safety(0);
    safety.record_feedback(0, 100, 0).unwrap();
    safety.spin(0, 1, 0).unwrap();
    safety.mark_speed_sent(0, 200, 0).unwrap();
    safety
        .record_feedback(0, 100, DEADMAN_CMD_TIMEOUT_MS + 1)
        .unwrap();
    let commands = safety.speed_commands(DEADMAN_CMD_TIMEOUT_MS + 1);
    assert_eq!(commands[0].speed, 0);
    assert_eq!(safety.last_error, Some(SafetyFault::DeadmanCommandStale));
}

#[test]
fn target_approach_slows_down_near_limit() {
    let mut safety = default_arm_safety(0);
    safety.record_feedback(0, YAW_TICK_MAX - 20, 0).unwrap();
    safety
        .goto_ticks(&[YAW_TICK_MAX, 200, 2300, 600], 0)
        .unwrap();
    let commands = safety.speed_commands(10);
    assert!(commands[0].speed > 0);
    assert!(commands[0].speed < safety.default_speed);
}
