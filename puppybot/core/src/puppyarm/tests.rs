use core::f64::consts::PI;

use super::{
    kinematics::*,
    puppyarm::{ArmCommand, ArmMode, PuppyArm, TcpFrame},
    servo_safety::*,
    types::{ControllerError, JOINT_COUNT, Joint},
};
use crate::config::PuppyArmConfig;

const EPS: f64 = 1.0e-6;
const COORD_EPS_MM: f32 = 1.0;
const ANGLE_EPS_DEG: f32 = 1.0e-4;
const TARGET_ANGLE_EPS_DEG: f32 = 0.1;
const YAW_REFERENCE_TICK: u16 = 2048;
const SHOULDER_REFERENCE_TICK: u16 = 530;
const ELBOW_REFERENCE_TICK: u16 = 3565;
const TIP_REFERENCE_TICK: u16 = 1783;

fn assert_close(left: f64, right: f64) {
    assert!(
        (left - right).abs() <= EPS,
        "left={left} right={right} diff={}",
        (left - right).abs()
    );
}

fn assert_close_f32(left: f32, right: f32) {
    assert!(
        (left - right).abs() <= ANGLE_EPS_DEG,
        "left={left} right={right} diff={}",
        (left - right).abs()
    );
}

fn assert_close_f32_eps(left: f32, right: f32, epsilon: f32) {
    assert!(
        (left - right).abs() <= epsilon,
        "left={left} right={right} diff={}",
        (left - right).abs()
    );
}

fn assert_close_mm(left: f32, right: f32) {
    assert_close_f32_eps(left, right, COORD_EPS_MM);
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
    target_arm.handle_arm_cmd(ArmCommand::GotoAngles(angles), 0);
    let target_state = target_arm.telemetry_snapshot(0);

    let mut feedback_arm = PuppyArm::new(0);
    for (index, joint) in target_state.joints.iter().enumerate() {
        feedback_arm.record_feedback(index, joint.target_tick.unwrap() as u16, 0);
    }
    feedback_arm
}

fn target_ticks(arm: &PuppyArm) -> [Option<i32>; JOINT_COUNT] {
    let telemetry = arm.telemetry_snapshot(0);
    core::array::from_fn(|index| telemetry.joints[index].target_tick)
}

fn feedback_ticks(arm: &PuppyArm) -> [Option<i32>; JOINT_COUNT] {
    let telemetry = arm.telemetry_snapshot(0);
    core::array::from_fn(|index| telemetry.joints[index].tick.map(i32::from))
}

fn assert_target_ticks_close(left: [Option<i32>; JOINT_COUNT], right: [Option<i32>; JOINT_COUNT]) {
    for (left, right) in left.iter().zip(right.iter()) {
        let left = left.unwrap();
        let right = right.unwrap();
        assert!(
            (left - right).abs() <= 5,
            "left={left} right={right} diff={}",
            (left - right).abs()
        );
    }
}

fn target_angles_deg(arm: &PuppyArm) -> [f32; JOINT_COUNT] {
    arm.telemetry_snapshot(0)
        .joints
        .map(|joint| joint.target_angle_deg.unwrap())
}

fn tool_phi_deg(angles_deg: [f32; JOINT_COUNT]) -> f32 {
    angles_deg[1] - angles_deg[2] - angles_deg[3]
}

#[test]
fn fk_straight_forward_pose_maps_to_positive_x_extent() {
    let (x, y, z) = fk(0.0, 0.0, 0.0, 0.0);
    assert_close(x, 432.0);
    assert_close(y, 0.0);
    assert_close(z, 0.0);
}

#[test]
fn fk_tip_down_pose_adds_tool_height_in_z() {
    let (x, y, z) = fk(0.0, 0.0, 0.0, PI / 2.0);
    assert_close(x, 302.0);
    assert_close(y, 0.0);
    assert_close(z, -130.0);
}

#[test]
fn ik_straight_reach_along_positive_x_uses_zero_yaw() {
    let result = ik(ARM_L1_MM + ARM_L2_MM, 0.0, -ARM_L3_MM);
    assert!(result.reachable);
    assert_close(result.yaw, 0.0);
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
fn tick_to_angle_matches_joint_calibration_reference_points() {
    let arm = arm_with_reference_feedback();
    let telemetry = arm.telemetry_snapshot(0);

    assert_close_f32(telemetry.joints[0].angle_deg.unwrap(), 0.0);
    assert_close_f32(telemetry.joints[1].angle_deg.unwrap(), 90.0);
    assert_close_f32(telemetry.joints[2].angle_deg.unwrap(), 0.0);
    assert_close_f32(telemetry.joints[3].angle_deg.unwrap(), 0.0);
}

#[test]
fn goto_ticks_telemetry_exposes_target_angles() {
    let mut arm = PuppyArm::new(0);

    arm.handle_arm_cmd(
        ArmCommand::GotoTicks([
            i32::from(YAW_REFERENCE_TICK),
            i32::from(SHOULDER_REFERENCE_TICK),
            i32::from(ELBOW_REFERENCE_TICK),
            i32::from(TIP_REFERENCE_TICK),
        ]),
        10,
    );
    let telemetry = arm.telemetry_snapshot(0);

    assert_close_f32(telemetry.joints[0].target_angle_deg.unwrap(), 0.0);
    assert_close_f32(telemetry.joints[1].target_angle_deg.unwrap(), 90.0);
    assert_close_f32(telemetry.joints[2].target_angle_deg.unwrap(), 0.0);
    assert_close_f32(telemetry.joints[3].target_angle_deg.unwrap(), 0.0);
    assert!(telemetry.target_coords_mm.is_some());
}

#[test]
fn goto_angles_telemetry_exposes_target_angles_and_coords() {
    let mut arm = PuppyArm::new(0);
    let target_angles_deg = [10.0_f32, 70.0, 25.0, -15.0];

    arm.handle_arm_cmd(
        ArmCommand::GotoAngles([
            (target_angles_deg[0] as f64).to_radians(),
            (target_angles_deg[1] as f64).to_radians(),
            (target_angles_deg[2] as f64).to_radians(),
            (target_angles_deg[3] as f64).to_radians(),
        ]),
        10,
    );
    let telemetry = arm.telemetry_snapshot(0);

    for (joint, expected) in telemetry.joints.iter().zip(target_angles_deg) {
        assert_close_f32_eps(
            joint.target_angle_deg.unwrap(),
            expected,
            TARGET_ANGLE_EPS_DEG,
        );
    }
    assert!(telemetry.target_coords_mm.is_some());
}

#[test]
fn telemetry_wraps_equivalent_joint_angles_for_display() {
    let mut config = PuppyArmConfig::default();
    config.joints[3].angle_sign = -1;
    config.joints[3].reference_tick = 1978;
    config.joints[3].reference_angle_rad = (-46.8_f64).to_radians();
    config.joints[3].limit_enabled = false;

    let mut target_arm = PuppyArm::new_with_config(&config, 0).unwrap();
    target_arm.record_feedback(0, YAW_REFERENCE_TICK, 0);
    target_arm.record_feedback(1, SHOULDER_REFERENCE_TICK, 0);
    target_arm.record_feedback(2, ELBOW_REFERENCE_TICK, 0);
    target_arm.record_feedback(3, 1978, 0);

    target_arm.handle_arm_cmd(
        ArmCommand::SetJointAngle {
            joint: 3,
            angle_rad: (-271.0_f64).to_radians(),
        },
        10,
    );

    let target_telemetry = target_arm.telemetry_snapshot(0);
    let wrist_target_tick = target_telemetry.joints[3].target_tick.unwrap() as u16;
    assert_close_f32_eps(
        target_telemetry.joints[3].target_angle_deg.unwrap(),
        89.0,
        TARGET_ANGLE_EPS_DEG,
    );

    let mut feedback_arm = PuppyArm::new_with_config(&config, 0).unwrap();
    feedback_arm.record_feedback(0, YAW_REFERENCE_TICK, 0);
    feedback_arm.record_feedback(1, SHOULDER_REFERENCE_TICK, 0);
    feedback_arm.record_feedback(2, ELBOW_REFERENCE_TICK, 0);
    feedback_arm.record_feedback(3, wrist_target_tick, 0);

    assert_close_f32_eps(
        feedback_arm.telemetry_snapshot(0).joints[3]
            .angle_deg
            .unwrap(),
        89.0,
        TARGET_ANGLE_EPS_DEG,
    );
}

#[test]
fn set_joint_reference_maps_current_tick_to_requested_angle() {
    let mut arm = arm_with_reference_feedback();
    arm.record_feedback(0, YAW_REFERENCE_TICK + 100, 0);
    let reference_angle_rad = 15.0_f64.to_radians();

    let before = arm.telemetry_snapshot(0).joints[0].angle_deg.unwrap();
    assert!(before.abs() > 1.0);

    let result = arm.try_handle_arm_cmd(
        ArmCommand::SetJointReference {
            joint: 0,
            tick: i32::from(YAW_REFERENCE_TICK + 100),
            angle_rad: reference_angle_rad,
        },
        10,
    );
    let telemetry = arm.telemetry_snapshot(0);

    assert_eq!(result, Ok(()));
    assert_eq!(
        telemetry.joints[0].reference_tick,
        i32::from(YAW_REFERENCE_TICK + 100)
    );
    assert_eq!(telemetry.joints[0].reference_angle_rad, reference_angle_rad);
    assert_close_f32(telemetry.joints[0].angle_deg.unwrap(), 15.0);

    arm.handle_arm_cmd(
        ArmCommand::SetJointAngle {
            joint: 0,
            angle_rad: reference_angle_rad,
        },
        20,
    );
    assert_eq!(
        arm.telemetry_snapshot(0).joints[0].target_tick,
        Some(i32::from(YAW_REFERENCE_TICK + 100))
    );
}

#[test]
fn set_joint_reference_accepts_tick_outside_movement_range() {
    let mut arm = arm_with_reference_feedback();
    arm.record_feedback(1, 2045, 0);

    let result = arm.try_handle_arm_cmd(
        ArmCommand::SetJointReference {
            joint: 1,
            tick: 2045,
            angle_rad: 0.0,
        },
        10,
    );
    let telemetry = arm.telemetry_snapshot(0);

    assert_eq!(result, Ok(()));
    assert_close_f32(telemetry.joints[1].angle_deg.unwrap(), 0.0);
}

#[test]
fn set_joint_reference_stops_active_motion() {
    let mut arm = arm_with_reference_feedback();
    arm.handle_arm_cmd(
        ArmCommand::Spin {
            joint: 0,
            direction: 1,
        },
        0,
    );
    assert_eq!(
        arm.mode(),
        ArmMode::Jogging {
            joint: 0,
            direction: 1
        }
    );

    let result = arm.try_handle_arm_cmd(
        ArmCommand::SetJointReference {
            joint: 0,
            tick: i32::from(YAW_REFERENCE_TICK),
            angle_rad: 0.0,
        },
        10,
    );
    let telemetry = arm.telemetry_snapshot(0);

    assert_eq!(result, Ok(()));
    assert_eq!(arm.mode(), ArmMode::Idle);
    assert!(
        telemetry
            .joints
            .iter()
            .all(|joint| joint.target_tick.is_none())
    );
    assert!(telemetry.joints.iter().all(|joint| joint.speed == 0));
}

#[test]
fn angle_to_tick_matches_joint_calibration_reference_points() {
    let mut arm = arm_with_reference_feedback();

    arm.handle_arm_cmd(ArmCommand::GotoAngles([0.0, PI / 2.0, 0.0, 0.0]), 0);
    let telemetry = arm.telemetry_snapshot(0);

    assert_eq!(
        telemetry.joints[0].target_tick,
        Some(YAW_REFERENCE_TICK as i32)
    );
    assert_eq!(
        telemetry.joints[1].target_tick,
        Some(SHOULDER_REFERENCE_TICK as i32)
    );
    assert_eq!(
        telemetry.joints[2].target_tick,
        Some(ELBOW_REFERENCE_TICK as i32)
    );
    assert_eq!(
        telemetry.joints[3].target_tick,
        Some(TIP_REFERENCE_TICK as i32)
    );
}

#[test]
fn tip_full_rotation_maps_ninety_degrees_to_plus_1024_ticks() {
    let mut arm = arm_with_reference_feedback();

    arm.handle_arm_cmd(
        ArmCommand::SetJointAngle {
            joint: 3,
            angle_rad: PI / 2.0,
        },
        0,
    );
    let telemetry = arm.telemetry_snapshot(0);

    assert_eq!(
        telemetry.joints[3].target_tick,
        Some(TIP_REFERENCE_TICK as i32 + TICK_WRAP / 4)
    );
}

#[test]
fn elbow_angle_sign_flips_around_zero_reference() {
    let mut arm = arm_with_reference_feedback();

    arm.handle_arm_cmd(
        ArmCommand::SetJointAngle {
            joint: 2,
            angle_rad: 0.02,
        },
        0,
    );
    let positive = arm.telemetry_snapshot(0).joints[2].target_tick.unwrap();

    arm.handle_arm_cmd(
        ArmCommand::SetJointAngle {
            joint: 2,
            angle_rad: -0.02,
        },
        10,
    );
    let negative = arm.telemetry_snapshot(0).joints[2].target_tick.unwrap();

    assert!(positive < ELBOW_REFERENCE_TICK as i32);
    assert!(negative > ELBOW_REFERENCE_TICK as i32);
}

#[test]
fn yaw_angle_to_tick_uses_full_servo_rotation() {
    let mut arm = arm_with_reference_feedback();
    arm.handle_arm_cmd(
        ArmCommand::SetTickLimits {
            joint: 0,
            min: -100,
            max: 100,
        },
        0,
    );
    arm.handle_arm_cmd(
        ArmCommand::SetTickLimitsEnabled {
            joint: 0,
            enabled: false,
        },
        0,
    );

    arm.handle_arm_cmd(
        ArmCommand::SetJointAngle {
            joint: 0,
            angle_rad: PI / 2.0,
        },
        0,
    );
    let telemetry = arm.telemetry_snapshot(0);

    assert_eq!(
        telemetry.joints[0].target_tick,
        Some(YAW_REFERENCE_TICK as i32 + TICK_WRAP / 4)
    );
}

#[test]
fn yaw_jog_from_st3215_center_allows_both_directions() {
    let mut arm = PuppyArm::new(0);

    arm.record_feedback(0, YAW_REFERENCE_TICK, 0);
    arm.handle_arm_cmd(
        ArmCommand::Spin {
            joint: 0,
            direction: 1,
        },
        0,
    );
    let positive = arm.update(10)[0].speed;

    arm.handle_arm_cmd(ArmCommand::Stop { joint: 0 }, 20);
    arm.record_feedback(0, YAW_REFERENCE_TICK, 20);
    arm.handle_arm_cmd(
        ArmCommand::Spin {
            joint: 0,
            direction: -1,
        },
        20,
    );
    let negative = arm.update(30)[0].speed;

    assert!(positive > 0);
    assert!(negative < 0);
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
fn try_goto_coords_reports_unreachable_target() {
    let mut arm = PuppyArm::new(0);

    let result = arm.try_handle_arm_cmd(
        ArmCommand::GotoCoords {
            x: 1000.0,
            y: 0.0,
            z: 0.0,
        },
        10,
    );

    assert_eq!(result, Err(ControllerError::Ik(IkError::Unreachable)));
    assert!(arm.telemetry_snapshot(0).joints[0].target_tick.is_none());
}

#[test]
fn goto_coords_searches_wrist_pitch_to_stay_inside_joint_limits() {
    let mut arm = PuppyArm::new(0);

    let result = arm.try_handle_arm_cmd(
        ArmCommand::GotoCoords {
            x: 200.0,
            y: 0.0,
            z: 75.0,
        },
        10,
    );
    let telemetry = arm.telemetry_snapshot(0);

    assert_eq!(result, Ok(()));
    assert_eq!(
        telemetry.joints[0].target_tick,
        Some(YAW_REFERENCE_TICK as i32)
    );
    assert!(
        telemetry
            .joints
            .iter()
            .all(|joint| joint.target_angle_deg.is_some())
    );
    assert!(telemetry.target_coords_mm.is_some());
    assert!(telemetry.joints[3].target_tick.unwrap() <= TIP_TICK_MAX);
}

#[test]
fn goto_coords_to_current_position_preserves_current_joint_pose() {
    let mut arm = arm_with_angle_feedback([
        0.0,
        66.0_f64.to_radians(),
        39.0_f64.to_radians(),
        20.0_f64.to_radians(),
    ]);
    let start = arm.telemetry_snapshot(0);
    let (x, y, z_table) = start.coords_mm.unwrap();
    let current_ticks = feedback_ticks(&arm);

    arm.handle_arm_cmd(
        ArmCommand::GotoCoords {
            x: x as f64,
            y: y as f64,
            z: table_to_shoulder_z(z_table as f64),
        },
        10,
    );

    assert_target_ticks_close(target_ticks(&arm), current_ticks);
}

#[test]
fn goto_coords_rejects_target_below_table_floor() {
    let mut arm = arm_with_reference_feedback();

    let result = arm.try_handle_arm_cmd(
        ArmCommand::GotoCoords {
            x: -200.0,
            y: 0.0,
            z: table_to_shoulder_z(-10.0),
        },
        10,
    );

    assert_eq!(result, Err(ControllerError::Ik(IkError::Unreachable)));
    assert!(arm.telemetry_snapshot(0).joints[0].target_tick.is_none());
}

#[test]
fn goto_pose_rejects_target_below_table_floor() {
    let mut arm = arm_with_reference_feedback();

    let result = arm.try_handle_arm_cmd(
        ArmCommand::GotoPose {
            x: -200.0,
            y: 0.0,
            z: table_to_shoulder_z(-10.0),
            tool_phi_rad: ARM_TOOL_PHI_RAD,
        },
        10,
    );

    assert_eq!(result, Err(ControllerError::Ik(IkError::Unreachable)));
    assert!(arm.telemetry_snapshot(0).joints[0].target_tick.is_none());
}

#[test]
fn goto_pose_rejects_exact_tool_pitch_when_joint_limits_would_clip() {
    let mut arm = PuppyArm::new(0);

    let result = arm.try_handle_arm_cmd(
        ArmCommand::GotoPose {
            x: -200.0,
            y: 0.0,
            z: 75.0,
            tool_phi_rad: ARM_TOOL_PHI_RAD,
        },
        10,
    );

    assert_eq!(result, Err(ControllerError::Ik(IkError::Unreachable)));
    assert!(arm.telemetry_snapshot(0).joints[0].target_tick.is_none());
}

#[test]
fn move_tcp_relative_base_matches_absolute_coordinate_target() {
    let mut relative = arm_with_reference_feedback();
    let start = relative.telemetry_snapshot(0).coords_mm.unwrap();

    let mut absolute = arm_with_reference_feedback();
    absolute.handle_arm_cmd(
        ArmCommand::GotoCoords {
            x: start.0 as f64 - 10.0,
            y: start.1 as f64 + 5.0,
            z: table_to_shoulder_z(start.2 as f64 + 20.0),
        },
        10,
    );

    relative.handle_arm_cmd(
        ArmCommand::MoveTcpRelative {
            frame: TcpFrame::Base,
            dx_mm: -10.0,
            dy_mm: 5.0,
            dz_mm: 20.0,
        },
        10,
    );

    assert_eq!(target_ticks(&relative), target_ticks(&absolute));
}

#[test]
fn move_tcp_relative_base_repeated_command_extends_active_target() {
    let pose = [
        0.0,
        90.0_f64.to_radians(),
        90.0_f64.to_radians(),
        90.0_f64.to_radians(),
    ];
    let mut relative = arm_with_angle_feedback(pose);
    let start = relative.telemetry_snapshot(0).coords_mm.unwrap();

    relative
        .try_handle_arm_cmd(
            ArmCommand::MoveTcpRelative {
                frame: TcpFrame::Base,
                dx_mm: 5.0,
                dy_mm: 0.0,
                dz_mm: 0.0,
            },
            10,
        )
        .unwrap();
    relative
        .try_handle_arm_cmd(
            ArmCommand::MoveTcpRelative {
                frame: TcpFrame::Base,
                dx_mm: 5.0,
                dy_mm: 0.0,
                dz_mm: 0.0,
            },
            20,
        )
        .unwrap();

    let mut absolute = arm_with_angle_feedback(pose);
    absolute
        .try_handle_arm_cmd(
            ArmCommand::GotoPose {
                x: start.0 as f64 + 10.0,
                y: start.1 as f64,
                z: table_to_shoulder_z(start.2 as f64),
                tool_phi_rad: -PI / 2.0,
            },
            10,
        )
        .unwrap();

    assert_target_ticks_close(target_ticks(&relative), target_ticks(&absolute));
}

#[test]
fn move_tcp_relative_base_rejects_instead_of_changing_tool_pitch() {
    let pose = [
        0.0,
        (-30.0_f64).to_radians(),
        40.0_f64.to_radians(),
        120.0_f64.to_radians(),
    ];
    let mut relative = arm_with_angle_feedback(pose);
    let before = target_ticks(&relative);
    let relative_result = relative.try_handle_arm_cmd(
        ArmCommand::MoveTcpRelative {
            frame: TcpFrame::Base,
            dx_mm: 5.0,
            dy_mm: 0.0,
            dz_mm: 0.0,
        },
        10,
    );

    assert_eq!(
        relative_result,
        Err(ControllerError::Ik(IkError::Unreachable))
    );
    assert_eq!(target_ticks(&relative), before);
}

#[test]
fn move_tcp_relative_yaw_flat_matches_absolute_coordinate_target() {
    let pose = [
        0.0,
        90.0_f64.to_radians(),
        90.0_f64.to_radians(),
        90.0_f64.to_radians(),
    ];
    let mut relative = arm_with_angle_feedback(pose);
    let start = relative.telemetry_snapshot(0).coords_mm.unwrap();

    let mut absolute = arm_with_angle_feedback(pose);
    absolute.handle_arm_cmd(
        ArmCommand::GotoCoords {
            x: start.0 as f64 + 5.0,
            y: start.1 as f64,
            z: table_to_shoulder_z(start.2 as f64),
        },
        10,
    );

    relative.handle_arm_cmd(
        ArmCommand::MoveTcpRelative {
            frame: TcpFrame::YawFlat,
            dx_mm: 5.0,
            dy_mm: 0.0,
            dz_mm: 0.0,
        },
        10,
    );

    assert_target_ticks_close(target_ticks(&relative), target_ticks(&absolute));
}

#[test]
fn yaw_flat_coordinate_jog_preserves_reachable_current_tool_pitch() {
    let pose = [
        0.0,
        60.0_f64.to_radians(),
        70.0_f64.to_radians(),
        100.0_f64.to_radians(),
    ];
    let mut arm = arm_with_angle_feedback(pose);
    let start = arm.telemetry_snapshot(0).coords_mm.unwrap();

    let result = arm.try_handle_arm_cmd(
        ArmCommand::MoveTcpRelative {
            frame: TcpFrame::YawFlat,
            dx_mm: 10.0,
            dy_mm: 0.0,
            dz_mm: 0.0,
        },
        10,
    );

    assert_eq!(result, Ok(()));
    let target = arm.telemetry_snapshot(0).target_coords_mm.unwrap();
    assert_close_mm(target.0, start.0 + 10.0);
    assert_close_mm(target.1, start.1);
    assert_close_mm(target.2, start.2);
    assert_close_f32_eps(tool_phi_deg(target_angles_deg(&arm)), -110.0, 1.0);
}

#[test]
fn yaw_flat_forward_at_zero_yaw_moves_positive_x_and_preserves_z() {
    let mut arm = arm_with_angle_feedback([
        0.0,
        90.0_f64.to_radians(),
        90.0_f64.to_radians(),
        90.0_f64.to_radians(),
    ]);
    let start = arm.telemetry_snapshot(0).coords_mm.unwrap();

    arm.handle_arm_cmd(
        ArmCommand::MoveTcpRelative {
            frame: TcpFrame::YawFlat,
            dx_mm: 10.0,
            dy_mm: 0.0,
            dz_mm: 0.0,
        },
        10,
    );

    let target = arm.telemetry_snapshot(0).target_coords_mm.unwrap();
    assert_close_mm(target.0, start.0 + 10.0);
    assert_close_mm(target.1, start.1);
    assert_close_mm(target.2, start.2);
}

#[test]
fn yaw_flat_forward_at_ninety_yaw_moves_positive_y_and_preserves_z() {
    let mut arm = arm_with_angle_feedback([
        90.0_f64.to_radians(),
        90.0_f64.to_radians(),
        90.0_f64.to_radians(),
        90.0_f64.to_radians(),
    ]);
    let start = arm.telemetry_snapshot(0).coords_mm.unwrap();

    arm.handle_arm_cmd(
        ArmCommand::MoveTcpRelative {
            frame: TcpFrame::YawFlat,
            dx_mm: 10.0,
            dy_mm: 0.0,
            dz_mm: 0.0,
        },
        10,
    );

    let target = arm.telemetry_snapshot(0).target_coords_mm.unwrap();
    assert_close_mm(target.0, start.0);
    assert_close_mm(target.1, start.1 + 10.0);
    assert_close_mm(target.2, start.2);
}

#[test]
fn yaw_flat_left_at_zero_yaw_moves_positive_y_and_preserves_z() {
    let mut arm = arm_with_angle_feedback([
        0.0,
        50.0_f64.to_radians(),
        40.0_f64.to_radians(),
        100.0_f64.to_radians(),
    ]);
    let start = arm.telemetry_snapshot(0).coords_mm.unwrap();

    arm.handle_arm_cmd(
        ArmCommand::MoveTcpRelative {
            frame: TcpFrame::YawFlat,
            dx_mm: 0.0,
            dy_mm: 10.0,
            dz_mm: 0.0,
        },
        10,
    );

    let target = arm.telemetry_snapshot(0).target_coords_mm.unwrap();
    assert_close_mm(target.0, start.0);
    assert_close_mm(target.1, start.1 + 10.0);
    assert_close_mm(target.2, start.2);
}

#[test]
fn yaw_flat_xy_relative_moves_preserve_target_z() {
    let poses = [
        [
            0.0_f64.to_radians(),
            50.0_f64.to_radians(),
            40.0_f64.to_radians(),
            100.0_f64.to_radians(),
        ],
        [
            45.0_f64.to_radians(),
            55.0_f64.to_radians(),
            35.0_f64.to_radians(),
            110.0_f64.to_radians(),
        ],
        [
            (-60.0_f64).to_radians(),
            60.0_f64.to_radians(),
            45.0_f64.to_radians(),
            105.0_f64.to_radians(),
        ],
    ];
    let xy_deltas = [
        (10.0, 0.0),
        (-10.0, 0.0),
        (0.0, 10.0),
        (0.0, -10.0),
        (25.0, 0.0),
        (-25.0, 0.0),
        (0.0, 25.0),
        (0.0, -25.0),
        (50.0, 0.0),
        (-50.0, 0.0),
        (7.0, 7.0),
        (-7.0, 7.0),
        (7.0, -7.0),
        (25.0, 25.0),
        (-25.0, 25.0),
        (25.0, -25.0),
    ];

    let mut checked_moves = 0;
    for pose in poses {
        let start = arm_with_angle_feedback(pose).telemetry_snapshot(0);
        let start_z = start.coords_mm.unwrap().2;

        for (dx_mm, dy_mm) in xy_deltas {
            let mut arm = arm_with_angle_feedback(pose);
            let result = arm.try_handle_arm_cmd(
                ArmCommand::MoveTcpRelative {
                    frame: TcpFrame::YawFlat,
                    dx_mm,
                    dy_mm,
                    dz_mm: 0.0,
                },
                10,
            );

            if result == Err(ControllerError::Ik(IkError::Unreachable)) {
                continue;
            }
            assert_eq!(result, Ok(()), "pose={pose:?} dx={dx_mm} dy={dy_mm}");
            let target_z = arm.telemetry_snapshot(0).target_coords_mm.unwrap().2;
            assert_close_f32_eps(target_z, start_z, 2.0);
            checked_moves += 1;
        }
    }
    assert!(checked_moves >= 16, "checked_moves={checked_moves}");
}

#[test]
fn move_tcp_relative_cardinal_xy_moves_cover_supported_frames() {
    let table_xy_pose = [
        0.0,
        90.0_f64.to_radians(),
        90.0_f64.to_radians(),
        90.0_f64.to_radians(),
    ];
    let flat_tool_pose = [0.0, 90.0_f64.to_radians(), 90.0_f64.to_radians(), 0.0];
    let moves = [
        ("forward", 10.0, 0.0, 10.0, 0.0),
        ("backward", -10.0, 0.0, -10.0, 0.0),
        ("left", 0.0, 10.0, 0.0, 10.0),
        ("right", 0.0, -10.0, 0.0, -10.0),
    ];

    for frame in [TcpFrame::Base, TcpFrame::YawFlat, TcpFrame::Tool] {
        for (name, dx_mm, dy_mm, expected_base_dx, expected_base_dy) in moves {
            let pose = match frame {
                TcpFrame::Base | TcpFrame::YawFlat => table_xy_pose,
                TcpFrame::Tool => flat_tool_pose,
            };
            let mut arm = arm_with_angle_feedback(pose);
            let start = arm.telemetry_snapshot(0).coords_mm.unwrap();

            let result = arm.try_handle_arm_cmd(
                ArmCommand::MoveTcpRelative {
                    frame,
                    dx_mm,
                    dy_mm,
                    dz_mm: 0.0,
                },
                10,
            );

            assert_eq!(result, Ok(()), "frame={frame:?} move={name}");
            let target = arm.telemetry_snapshot(0).target_coords_mm.unwrap();
            assert_close_mm(target.2, start.2);

            match frame {
                TcpFrame::Base | TcpFrame::YawFlat => {
                    assert_close_mm(target.0, start.0 + expected_base_dx);
                    assert_close_mm(target.1, start.1 + expected_base_dy);
                }
                TcpFrame::Tool => {
                    let changed_xy = (target.0 - start.0).abs() > COORD_EPS_MM
                        || (target.1 - start.1).abs() > COORD_EPS_MM;
                    assert!(changed_xy, "move={name} start={start:?} target={target:?}");
                }
            }
        }
    }
}

#[test]
fn move_tcp_relative_tool_forward_uses_current_tool_orientation() {
    let pose = [
        0.0,
        50.0_f64.to_radians(),
        40.0_f64.to_radians(),
        100.0_f64.to_radians(),
    ];
    let mut relative = arm_with_angle_feedback(pose);
    let mut expected = arm_with_angle_feedback(pose);

    relative.handle_arm_cmd(
        ArmCommand::MoveTcpRelative {
            frame: TcpFrame::Tool,
            dx_mm: 10.0,
            dy_mm: 0.0,
            dz_mm: 0.0,
        },
        10,
    );
    expected.handle_arm_cmd(
        ArmCommand::MoveTcpRelative {
            frame: TcpFrame::Base,
            dx_mm: 0.0,
            dy_mm: 0.0,
            dz_mm: -10.0,
        },
        10,
    );

    assert_target_ticks_close(target_ticks(&relative), target_ticks(&expected));
}

#[test]
fn move_tcp_relative_requires_feedback() {
    let mut arm = PuppyArm::new(0);

    arm.handle_arm_cmd(
        ArmCommand::MoveTcpRelative {
            frame: TcpFrame::Base,
            dx_mm: 0.0,
            dy_mm: 0.0,
            dz_mm: 20.0,
        },
        10,
    );

    assert_eq!(target_ticks(&arm), [None; JOINT_COUNT]);
}

#[test]
fn move_tcp_relative_unreachable_target_keeps_existing_targets() {
    let mut arm = arm_with_reference_feedback();
    arm.handle_arm_cmd(ArmCommand::GotoTicks([1000, 1001, 1002, 1003]), 0);
    let before = target_ticks(&arm);

    arm.handle_arm_cmd(
        ArmCommand::MoveTcpRelative {
            frame: TcpFrame::Base,
            dx_mm: 1000.0,
            dy_mm: 0.0,
            dz_mm: 0.0,
        },
        10,
    );

    assert_eq!(target_ticks(&arm), before);
}

#[test]
fn yaw_flat_unreachable_xy_move_keeps_existing_target_and_z() {
    let mut arm = arm_with_angle_feedback([
        0.0,
        90.0_f64.to_radians(),
        90.0_f64.to_radians(),
        90.0_f64.to_radians(),
    ]);
    arm.handle_arm_cmd(
        ArmCommand::MoveTcpRelative {
            frame: TcpFrame::YawFlat,
            dx_mm: 10.0,
            dy_mm: 0.0,
            dz_mm: 0.0,
        },
        0,
    );
    let before = arm.telemetry_snapshot(0);
    let before_ticks = target_ticks(&arm);
    let before_target_z = before.target_coords_mm.unwrap().2;

    let result = arm.try_handle_arm_cmd(
        ArmCommand::MoveTcpRelative {
            frame: TcpFrame::YawFlat,
            dx_mm: 1000.0,
            dy_mm: 0.0,
            dz_mm: 0.0,
        },
        10,
    );
    let after = arm.telemetry_snapshot(0);

    assert_eq!(result, Err(ControllerError::Ik(IkError::Unreachable)));
    assert_eq!(target_ticks(&arm), before_ticks);
    assert_close_mm(after.target_coords_mm.unwrap().2, before_target_z);
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
fn target_error_prefers_short_wrap_when_substantially_shorter() {
    assert_eq!(target_tick_error(100, 3900), 296);
}

#[test]
fn default_wrist_target_uses_short_wrap_with_flipped_calibration() {
    let mut config = PuppyArmConfig::default();
    config.joints[3].angle_sign = -1;
    config.joints[3].reference_tick = 1978;
    config.joints[3].reference_angle_rad = (-46.8_f64).to_radians();
    config.joints[3].limit_enabled = false;

    let mut arm = PuppyArm::new_with_config(&config, 0).unwrap();
    arm.record_feedback(0, YAW_REFERENCE_TICK, 0);
    arm.record_feedback(1, SHOULDER_REFERENCE_TICK, 0);
    arm.record_feedback(2, ELBOW_REFERENCE_TICK, 0);
    arm.record_feedback(3, 3579, 0);
    arm.handle_arm_cmd(ArmCommand::SetSpeed(220), 0);
    arm.handle_arm_cmd(
        ArmCommand::GotoAngles([
            90.0_f64.to_radians(),
            90.0_f64.to_radians(),
            90.0_f64.to_radians(),
            90.0_f64.to_radians(),
        ]),
        0,
    );

    assert!(arm.update(10)[3].speed > 0);
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
fn goto_ticks_from_wrapped_out_of_bounds_tick_recovers_toward_interval() {
    let mut arm = PuppyArm::new(0);
    arm.handle_arm_cmd(ArmCommand::SetSpeed(791), 0);
    arm.handle_arm_cmd(
        ArmCommand::SetTickLimits {
            joint: 0,
            min: -500,
            max: 1300,
        },
        0,
    );
    arm.record_feedback(0, 3452, 0);
    arm.handle_arm_cmd(
        ArmCommand::GotoTicks([85, SHOULDER_TICK_MIN, ELBOW_TICK_MIN, TIP_TICK_MIN]),
        0,
    );

    let commands = arm.update(10);
    let telemetry = arm.telemetry_snapshot(0);

    assert!(telemetry.joints[0].limit_reached);
    assert!(commands[0].speed > 0);
}

#[test]
fn goto_ticks_wrap_boundary_does_not_oscillate_direction() {
    let mut arm = PuppyArm::new(0);
    arm.handle_arm_cmd(ArmCommand::SetSpeed(200), 0);
    arm.handle_arm_cmd(
        ArmCommand::SetTickLimits {
            joint: 0,
            min: -500,
            max: 1300,
        },
        0,
    );
    arm.handle_arm_cmd(
        ArmCommand::GotoTicks([20, SHOULDER_TICK_MIN, ELBOW_TICK_MIN, TIP_TICK_MIN]),
        0,
    );

    let speeds = [3595, 3597, 3595, 3597].map(|tick| {
        arm.record_feedback(0, tick, 0);
        arm.update(10)[0].speed
    });

    assert!(speeds.iter().all(|speed| *speed >= 0), "{speeds:?}");
    assert!(speeds.iter().any(|speed| *speed > 0), "{speeds:?}");
}

#[test]
fn unrelated_joint_limit_does_not_block_yaw_jog() {
    let mut arm = PuppyArm::new(0);
    arm.record_feedback(0, 0, 0);
    arm.record_feedback(3, (TIP_TICK_MAX + 4) as u16, 0);
    arm.handle_arm_cmd(
        ArmCommand::Spin {
            joint: 0,
            direction: 1,
        },
        0,
    );

    let commands = arm.update(10);
    let telemetry = arm.telemetry_snapshot(0);

    assert!(telemetry.joints[3].limit_reached);
    assert_eq!(commands[0].speed, 200);
}

#[test]
fn disabled_limits_allow_target_motion() {
    let mut arm = PuppyArm::new(0);
    arm.handle_arm_cmd(ArmCommand::SetSpeed(80), 0);
    arm.handle_arm_cmd(
        ArmCommand::SetTickLimits {
            joint: 0,
            min: 4000,
            max: 100,
        },
        0,
    );
    arm.handle_arm_cmd(
        ArmCommand::SetTickLimitsEnabled {
            joint: 0,
            enabled: false,
        },
        0,
    );
    arm.record_feedback(0, 2000, 0);
    arm.handle_arm_cmd(
        ArmCommand::GotoTicks([4050, SHOULDER_TICK_MIN, ELBOW_TICK_MIN, TIP_TICK_MIN]),
        0,
    );

    let commands = arm.update(10);

    assert_eq!(commands[0].speed, 80);
}

#[test]
fn goto_ticks_uses_default_speed() {
    let mut arm = PuppyArm::new(0);
    arm.handle_arm_cmd(ArmCommand::SetSpeed(80), 0);
    arm.record_feedback(0, 0, 0);
    arm.handle_arm_cmd(
        ArmCommand::GotoTicks([100, SHOULDER_TICK_MIN, ELBOW_TICK_MIN, TIP_TICK_MIN]),
        0,
    );

    let commands = arm.update(10);

    assert_eq!(commands[0].speed, 80);
}

#[test]
fn goto_ticks_stops_at_target() {
    let mut arm = PuppyArm::new(0);
    arm.handle_arm_cmd(ArmCommand::SetSpeed(80), 0);
    arm.record_feedback(0, 100, 0);
    arm.handle_arm_cmd(
        ArmCommand::GotoTicks([100, SHOULDER_TICK_MIN, ELBOW_TICK_MIN, TIP_TICK_MIN]),
        0,
    );

    let commands = arm.update(10);
    let telemetry = arm.telemetry_snapshot(0);

    assert_eq!(commands[0].speed, 0);
    assert_eq!(telemetry.joints[0].target_tick, None);
}

#[test]
fn goto_ticks_retargeting_changes_direction_after_reaching_previous_target() {
    let mut arm = PuppyArm::new(0);
    arm.handle_arm_cmd(ArmCommand::SetSpeed(80), 0);
    arm.record_feedback(0, 0, 0);
    arm.handle_arm_cmd(
        ArmCommand::GotoTicks([100, SHOULDER_TICK_MIN, ELBOW_TICK_MIN, TIP_TICK_MIN]),
        0,
    );

    let first_commands = arm.update(10);
    arm.record_feedback(0, 100, 20);
    let reached_commands = arm.update(30);
    arm.handle_arm_cmd(
        ArmCommand::GotoTicks([40, SHOULDER_TICK_MIN, ELBOW_TICK_MIN, TIP_TICK_MIN]),
        40,
    );
    let retargeted_commands = arm.update(50);

    assert!(first_commands[0].speed > 0);
    assert_eq!(reached_commands[0].speed, 0);
    assert!(retargeted_commands[0].speed < 0);
}

#[test]
fn goto_ticks_stops_within_deadband() {
    let mut arm = PuppyArm::new(0);
    arm.handle_arm_cmd(ArmCommand::SetSpeed(80), 0);
    arm.record_feedback(0, 96, 0);
    arm.handle_arm_cmd(
        ArmCommand::GotoTicks([100, SHOULDER_TICK_MIN, ELBOW_TICK_MIN, TIP_TICK_MIN]),
        0,
    );

    let commands = arm.update(10);
    let telemetry = arm.telemetry_snapshot(0);

    assert_eq!(commands[0].speed, 0);
    assert_eq!(telemetry.joints[0].target_tick, None);
}

#[test]
fn goto_ticks_reduces_speed_when_close() {
    let mut arm = PuppyArm::new(0);
    arm.handle_arm_cmd(ArmCommand::SetSpeed(80), 0);
    arm.record_feedback(0, 40, 0);
    arm.handle_arm_cmd(
        ArmCommand::GotoTicks([100, SHOULDER_TICK_MIN, ELBOW_TICK_MIN, TIP_TICK_MIN]),
        0,
    );

    let commands = arm.update(10);

    assert_eq!(commands[0].speed, 60);
}

#[test]
fn stop_cancels_active_target() {
    let mut arm = PuppyArm::new(0);
    arm.record_feedback(0, 0, 0);
    arm.handle_arm_cmd(
        ArmCommand::GotoTicks([100, SHOULDER_TICK_MIN, ELBOW_TICK_MIN, TIP_TICK_MIN]),
        0,
    );

    arm.handle_arm_cmd(ArmCommand::Stop { joint: 0 }, 10);
    let telemetry = arm.telemetry_snapshot(0);

    assert_eq!(telemetry.joints[0].target_tick, None);
    assert_eq!(telemetry.joints[0].speed, 0);
}

#[test]
fn spin_cancels_active_target() {
    let mut arm = PuppyArm::new(0);
    arm.record_feedback(0, YAW_REFERENCE_TICK, 0);
    arm.handle_arm_cmd(
        ArmCommand::GotoTicks([100, SHOULDER_TICK_MIN, ELBOW_TICK_MIN, TIP_TICK_MIN]),
        0,
    );

    assert_eq!(arm.telemetry_snapshot(0).joints[0].target_tick, Some(100));

    arm.handle_arm_cmd(
        ArmCommand::Spin {
            joint: 0,
            direction: -1,
        },
        10,
    );
    let commands = arm.update(10);
    let telemetry = arm.telemetry_snapshot(0);

    assert_eq!(telemetry.joints[0].target_tick, None);
    assert_eq!(commands[0].speed, -200);
}

#[test]
fn zero_default_speed_stops_spinning_joint() {
    let mut arm = PuppyArm::new(0);
    arm.record_feedback(0, 0, 0);
    arm.handle_arm_cmd(
        ArmCommand::Spin {
            joint: 0,
            direction: 1,
        },
        0,
    );
    arm.handle_arm_cmd(ArmCommand::SetSpeed(0), 10);

    let commands = arm.update(10);

    assert_eq!(commands[0].speed, 0);
}

#[test]
fn zero_default_speed_stops_active_goto_motion() {
    let mut arm = PuppyArm::new(0);
    arm.record_feedback(0, 0, 0);
    arm.handle_arm_cmd(
        ArmCommand::GotoTicks([500, SHOULDER_TICK_MIN, ELBOW_TICK_MIN, TIP_TICK_MIN]),
        0,
    );
    arm.handle_arm_cmd(ArmCommand::SetSpeed(0), 10);

    let commands = arm.update(10);
    let telemetry = arm.telemetry_snapshot(0);

    assert_eq!(commands[0].speed, 0);
    assert_eq!(telemetry.joints[0].target_tick, Some(500));
}

#[test]
fn target_tracking_speed_scales_with_positive_tick_error() {
    let mut arm = PuppyArm::new(0);
    arm.handle_arm_cmd(ArmCommand::SetSpeed(200), 0);
    arm.record_feedback(0, 40, 0);
    arm.handle_arm_cmd(
        ArmCommand::GotoTicks([80, SHOULDER_TICK_MIN, ELBOW_TICK_MIN, TIP_TICK_MIN]),
        0,
    );

    let commands = arm.update(10);

    assert_eq!(commands[0].speed, 100);
}

#[test]
fn target_tracking_speed_scales_with_negative_tick_error() {
    let mut arm = PuppyArm::new(0);
    arm.handle_arm_cmd(ArmCommand::SetSpeed(200), 0);
    arm.record_feedback(0, 200, 0);
    arm.handle_arm_cmd(
        ArmCommand::GotoTicks([160, SHOULDER_TICK_MIN, ELBOW_TICK_MIN, TIP_TICK_MIN]),
        0,
    );

    let commands = arm.update(10);

    assert_eq!(commands[0].speed, -100);
}

#[test]
fn shoulder_target_tracking_preserves_drive_direction() {
    let mut arm = PuppyArm::new(0);
    arm.record_feedback(0, 0, 0);
    arm.record_feedback(1, 530, 0);
    arm.record_feedback(2, 3565, 0);
    arm.record_feedback(3, 1783, 0);
    arm.handle_arm_cmd(
        ArmCommand::SetJointAngle {
            joint: 1,
            angle_rad: PI / 2.0 + 0.25,
        },
        0,
    );

    let commands = arm.update(10);
    let telemetry = arm.telemetry_snapshot(0);

    assert!(telemetry.joints[1].target_tick.unwrap() < 530);
    assert_eq!(commands[1].speed, -200);
}

#[test]
fn elbow_target_tracking_preserves_drive_direction() {
    let mut arm = PuppyArm::new(0);
    arm.record_feedback(0, 0, 0);
    arm.record_feedback(1, 530, 0);
    arm.record_feedback(2, 3565, 0);
    arm.record_feedback(3, 1783, 0);
    arm.handle_arm_cmd(
        ArmCommand::SetJointAngle {
            joint: 2,
            angle_rad: 0.25,
        },
        0,
    );

    let commands = arm.update(10);
    let telemetry = arm.telemetry_snapshot(0);

    assert!(telemetry.joints[2].target_tick.unwrap() < 3565);
    assert_eq!(commands[2].speed, -200);
}

#[test]
fn slew_limit_bounds_acceleration() {
    let mut arm = PuppyArm::new(0);
    arm.handle_arm_cmd(ArmCommand::SetSpeed(400), 0);
    arm.record_feedback(0, 0, 0);
    arm.handle_arm_cmd(
        ArmCommand::GotoTicks([1000, SHOULDER_TICK_MIN, ELBOW_TICK_MIN, TIP_TICK_MIN]),
        0,
    );
    arm.record_wheel_speed_result(0, 1, 0, true, 0);

    let commands = arm.update(10);

    assert_eq!(commands[0].speed, 200);
}

#[test]
fn slew_limit_bounds_deceleration() {
    let mut arm = PuppyArm::new(0);
    arm.handle_arm_cmd(ArmCommand::SetSpeed(400), 0);
    arm.record_feedback(0, 0, 0);
    arm.handle_arm_cmd(
        ArmCommand::GotoTicks([20, SHOULDER_TICK_MIN, ELBOW_TICK_MIN, TIP_TICK_MIN]),
        0,
    );
    arm.record_wheel_speed_result(0, 1, 400, true, 0);

    let commands = arm.update(10);

    assert_eq!(commands[0].speed, 100);
}

#[test]
fn overtemperature_fault_stops_motion() {
    let mut arm = PuppyArm::new(0);
    arm.handle_arm_cmd(ArmCommand::SetSpeed(120), 0);
    arm.record_feedback(0, 100, 0);
    arm.handle_arm_cmd(
        ArmCommand::Spin {
            joint: 0,
            direction: 1,
        },
        0,
    );
    arm.record_temperature(0, Some(MAX_TEMP_C + 1));

    let commands = arm.update(10);
    let telemetry = arm.telemetry_snapshot(10);

    assert_eq!(commands[0].speed, 0);
    assert_eq!(telemetry.joints[0].speed, 0);
    assert_eq!(telemetry.joints[0].temp_c, Some(MAX_TEMP_C + 1));
    assert_eq!(
        telemetry.joints[0].fault,
        Some(SafetyFault::OverTemperature)
    );
}

#[test]
fn clear_faults_command_clears_selected_and_all_faults() {
    let mut arm = PuppyArm::new(0);
    arm.handle_arm_cmd(ArmCommand::SetSpeed(120), 0);
    arm.record_feedback(0, 0, 0);
    arm.record_feedback(1, 200, 0);
    arm.record_temperature(0, Some(MAX_TEMP_C + 1));
    arm.record_temperature(1, Some(MAX_TEMP_C + 1));
    arm.handle_arm_cmd(
        ArmCommand::GotoTicks([1000, 300, ELBOW_TICK_MIN, TIP_TICK_MIN]),
        0,
    );

    arm.update(10);
    let faulted = arm.telemetry_snapshot(0);
    assert_eq!(faulted.joints[0].fault, Some(SafetyFault::OverTemperature));
    assert_eq!(faulted.joints[1].fault, Some(SafetyFault::OverTemperature));

    arm.handle_arm_cmd(ArmCommand::ClearFaults { joint: Some(0) }, 20);
    let selected_clear = arm.telemetry_snapshot(0);
    assert_eq!(selected_clear.joints[0].fault, None);
    assert_eq!(
        selected_clear.joints[1].fault,
        Some(SafetyFault::OverTemperature)
    );

    arm.update(DEADMAN_FEEDBACK_TIMEOUT_MS + 1);
    assert_eq!(arm.mode(), ArmMode::Fault);

    arm.handle_arm_cmd(ArmCommand::ClearFaults { joint: None }, 30);
    let all_clear = arm.telemetry_snapshot(0);

    assert!(all_clear.joints.iter().all(|joint| joint.fault.is_none()));
    assert_eq!(arm.mode(), ArmMode::Idle);
}

#[test]
fn stall_fault_stops_motion_when_ticks_do_not_change() {
    let mut arm = PuppyArm::new(0);
    arm.handle_arm_cmd(ArmCommand::SetSpeed(STALL_SPEED_MIN), 0);
    arm.record_feedback(0, 0, 0);
    arm.handle_arm_cmd(
        ArmCommand::GotoTicks([1000, SHOULDER_TICK_MIN, ELBOW_TICK_MIN, TIP_TICK_MIN]),
        0,
    );

    let moving_commands = arm.update(10);
    arm.record_feedback(0, 0, 10 + STALL_TRIP_MS);
    let stalled_commands = arm.update(10 + STALL_TRIP_MS);
    let telemetry = arm.telemetry_snapshot(0);

    assert_eq!(moving_commands[0].speed, STALL_SPEED_MIN);
    assert_eq!(stalled_commands[0].speed, 0);
    assert_eq!(telemetry.joints[0].speed, 0);
    assert_eq!(telemetry.joints[0].fault, Some(SafetyFault::Stall));
}

#[test]
fn stale_feedback_forces_zero_speed() {
    let mut arm = PuppyArm::new(0);
    arm.record_feedback(0, 0, 0);
    arm.handle_arm_cmd(
        ArmCommand::Spin {
            joint: 0,
            direction: 1,
        },
        0,
    );
    arm.record_feedback(1, 200, JOINT_FEEDBACK_TIMEOUT_MS + 1);

    let commands = arm.update(JOINT_FEEDBACK_TIMEOUT_MS + 1);
    let telemetry = arm.telemetry_snapshot(0);

    assert_eq!(commands[0].speed, 0);
    assert_eq!(telemetry.joints[0].fault, Some(SafetyFault::FeedbackStale));
}

#[test]
fn feedback_read_failure_stops_free_spin() {
    let mut arm = PuppyArm::new(0);
    arm.handle_arm_cmd(ArmCommand::SetSpeed(120), 0);
    arm.record_feedback(0, 100, 0);
    arm.handle_arm_cmd(
        ArmCommand::Spin {
            joint: 0,
            direction: 1,
        },
        0,
    );

    let spinning_commands = arm.update(10);
    arm.record_feedback_error(0);
    let stopped_commands = arm.update(20);
    let telemetry = arm.telemetry_snapshot(0);

    assert_eq!(spinning_commands[0].speed, 120);
    assert_eq!(stopped_commands[0].speed, 0);
    assert_eq!(telemetry.joints[0].speed, 0);
    assert_eq!(
        telemetry.joints[0].fault,
        Some(SafetyFault::FeedbackUnavailable)
    );
}

#[test]
fn deadman_stops_free_spin() {
    let mut arm = PuppyArm::new(0);
    arm.record_feedback(0, 100, 0);
    arm.handle_arm_cmd(
        ArmCommand::Spin {
            joint: 0,
            direction: 1,
        },
        0,
    );
    arm.record_wheel_speed_result(0, 2, 200, true, 0);
    arm.record_feedback(0, 100, DEADMAN_CMD_TIMEOUT_MS + 1);

    let commands = arm.update(DEADMAN_CMD_TIMEOUT_MS + 1);

    assert_eq!(commands[0].speed, 0);
}

#[test]
fn deadman_command_timeout_does_not_cancel_target_tracking() {
    let mut arm = PuppyArm::new(0);
    arm.handle_arm_cmd(ArmCommand::SetSpeed(80), 0);
    arm.record_feedback(0, 0, 0);
    arm.handle_arm_cmd(
        ArmCommand::GotoTicks([100, SHOULDER_TICK_MIN, ELBOW_TICK_MIN, TIP_TICK_MIN]),
        0,
    );
    arm.record_feedback(0, 0, DEADMAN_CMD_TIMEOUT_MS + 1);

    let commands = arm.update(DEADMAN_CMD_TIMEOUT_MS + 1);
    let telemetry = arm.telemetry_snapshot(0);

    assert_eq!(commands[0].speed, 80);
    assert_eq!(telemetry.joints[0].target_tick, Some(100));
    assert_eq!(telemetry.joints[0].fault, None);
}

#[test]
fn target_approach_slows_down_near_limit() {
    let mut arm = PuppyArm::new(0);
    arm.record_feedback(0, (YAW_TICK_MAX - 20) as u16, 0);
    arm.handle_arm_cmd(ArmCommand::GotoTicks([YAW_TICK_MAX, 200, 2300, 600]), 0);

    let commands = arm.update(10);

    assert!(commands[0].speed > 0);
    assert!(commands[0].speed < 200);
}
