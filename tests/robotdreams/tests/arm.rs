use puppybot_core::puppyarm::types::{ArmCommand, TcpFrame};

use harness::{
    MODEL_UP_TOLERANCE_M, PuppybotRobotDreamsHarness, assert_close_m, distance,
    puppybot_model_up_axis,
};

#[path = "support/harness.rs"]
mod harness;

// Repeated moves compare the exported CAD TCP against PuppyArm's simplified controller model.
const REPEATED_MOVE_STABLE_AXIS_TOLERANCE_M: f64 = 0.006;
const FLOOR_TOP_Z_M: f64 = -0.001;
const TCP_FLOOR_TOUCH_TOLERANCE_M: f64 = 0.020;
const TCP_ABOVE_BODY_CLEARANCE_Z_M: f64 = 0.180;

fn assert_coordinate_forward_preserves_model_up_axis(frame: TcpFrame) {
    let model_up_axis = puppybot_model_up_axis();
    let mut harness = test_harness();
    let start_tcp = harness.tcp_position();

    harness.run_arm_command(
        ArmCommand::MoveTcpRelative {
            frame,
            dx_mm: 10.0,
            dy_mm: 0.0,
            dz_mm: 0.0,
        },
        160,
    );
    let moved_tcp = harness.tcp_position();

    assert!(
        distance(start_tcp, moved_tcp) > 0.005,
        "{frame:?} coordinate forward should move RobotDreams TCP: start={start_tcp:?} moved={moved_tcp:?}"
    );
    assert!(
        moved_tcp[0] > start_tcp[0],
        "{frame:?} coordinate forward should increase ROS X: start={start_tcp:?} moved={moved_tcp:?}"
    );
    assert_close_m(
        moved_tcp[model_up_axis],
        start_tcp[model_up_axis],
        MODEL_UP_TOLERANCE_M,
    );
}

#[derive(Clone, Copy, Debug)]
struct CoordinateButtonCase {
    name: &'static str,
    dx_mm: f64,
    dy_mm: f64,
    dz_mm: f64,
    movement_axes: &'static [usize],
    stable_axes: &'static [usize],
    button_presses: usize,
    jog_hold_cycles: usize,
    minimum_movement_m: f64,
    jog_minimum_m: f64,
}

#[derive(Clone, Copy, Debug)]
struct WorkspaceDirection {
    name: &'static str,
    yaw_rad: f64,
}

const CARDINAL_WORKSPACE_DIRECTIONS: [WorkspaceDirection; 4] = [
    WorkspaceDirection {
        name: "front",
        yaw_rad: 0.0,
    },
    WorkspaceDirection {
        name: "left",
        yaw_rad: std::f64::consts::FRAC_PI_2,
    },
    WorkspaceDirection {
        name: "back",
        yaw_rad: std::f64::consts::PI,
    },
    WorkspaceDirection {
        name: "right",
        yaw_rad: -std::f64::consts::FRAC_PI_2,
    },
];

const FORWARD: CoordinateButtonCase = CoordinateButtonCase {
    name: "Forward",
    dx_mm: 10.0,
    dy_mm: 0.0,
    dz_mm: 0.0,
    movement_axes: &[0, 1],
    stable_axes: &[2],
    button_presses: 3,
    jog_hold_cycles: 70,
    minimum_movement_m: 0.010,
    jog_minimum_m: 0.010,
};

const BACK: CoordinateButtonCase = CoordinateButtonCase {
    name: "Back",
    dx_mm: -10.0,
    dy_mm: 0.0,
    dz_mm: 0.0,
    movement_axes: &[0, 1],
    stable_axes: &[2],
    button_presses: 3,
    jog_hold_cycles: 70,
    minimum_movement_m: 0.010,
    jog_minimum_m: 0.010,
};

const LEFT: CoordinateButtonCase = CoordinateButtonCase {
    name: "Left",
    dx_mm: 0.0,
    dy_mm: 10.0,
    dz_mm: 0.0,
    movement_axes: &[0, 1],
    stable_axes: &[2],
    button_presses: 3,
    jog_hold_cycles: 70,
    minimum_movement_m: 0.010,
    jog_minimum_m: 0.010,
};

const RIGHT: CoordinateButtonCase = CoordinateButtonCase {
    name: "Right",
    dx_mm: 0.0,
    dy_mm: -10.0,
    dz_mm: 0.0,
    movement_axes: &[0, 1],
    stable_axes: &[2],
    button_presses: 3,
    jog_hold_cycles: 70,
    minimum_movement_m: 0.010,
    jog_minimum_m: 0.010,
};

const UP: CoordinateButtonCase = CoordinateButtonCase {
    name: "Up",
    dx_mm: 0.0,
    dy_mm: 0.0,
    dz_mm: 10.0,
    movement_axes: &[2],
    stable_axes: &[],
    button_presses: 3,
    jog_hold_cycles: 50,
    minimum_movement_m: 0.009,
    jog_minimum_m: 0.0003,
};

const DOWN: CoordinateButtonCase = CoordinateButtonCase {
    name: "Down",
    dx_mm: 0.0,
    dy_mm: 0.0,
    dz_mm: -10.0,
    movement_axes: &[2],
    stable_axes: &[0, 1],
    button_presses: 1,
    jog_hold_cycles: 100,
    // The default exported CAD TCP starts close to the floor in this motion-valid pose.
    minimum_movement_m: 0.002,
    jog_minimum_m: 0.0003,
};

fn assert_coordinate_button_until_unreachable_preserves_other_axes(
    frame: TcpFrame,
    case: CoordinateButtonCase,
) {
    const BUTTON_STEP_MM: f64 = 10.0;
    const CYCLES_PER_PRESS: usize = 160;
    const SAMPLE_EVERY_CYCLES: usize = 8;

    let mut harness = test_harness_for_coordinate_move(case);
    let start_tcp = harness.tcp_position();
    let mut accepted_presses = 0;
    let mut samples = Vec::new();

    while accepted_presses < case.button_presses {
        let next_samples = harness.run_arm_command_sampled(
            coordinate_move(frame, case),
            CYCLES_PER_PRESS,
            SAMPLE_EVERY_CYCLES,
        );
        accepted_presses += 1;
        samples.extend(next_samples);
        samples.push(harness.tcp_position());
    }

    let actual_movement = samples
        .iter()
        .map(|tcp| {
            case.movement_axes
                .iter()
                .map(|axis| {
                    let delta = tcp[*axis] - start_tcp[*axis];
                    delta * delta
                })
                .sum::<f64>()
                .sqrt()
        })
        .fold(0.0, f64::max);

    assert!(
        accepted_presses > 0,
        "{frame:?} coordinate {} should accept at least one button press",
        case.name
    );
    assert!(
        actual_movement > case.minimum_movement_m,
        "{frame:?} repeated coordinate {} should move on commanded axes: start={start_tcp:?} actual_movement_mm={:.3} accepted_presses={accepted_presses}",
        case.name,
        actual_movement * 1000.0
    );
    assert_final_sample_preserves_axes(
        frame,
        case,
        start_tcp,
        &samples,
        accepted_presses,
        BUTTON_STEP_MM,
        actual_movement,
    );
}

fn test_harness_for_coordinate_move(case: CoordinateButtonCase) -> PuppybotRobotDreamsHarness {
    if case.dx_mm == 0.0 && case.dy_mm == 0.0 && case.dz_mm < 0.0 {
        return PuppybotRobotDreamsHarness::with_arm_pose([
            0.0,
            52.0_f64.to_radians(),
            36.0_f64.to_radians(),
            (-30.0_f64).to_radians(),
        ]);
    }
    test_harness()
}

fn test_harness() -> PuppybotRobotDreamsHarness {
    test_harness_with_yaw(0.0)
}

fn test_harness_with_yaw(yaw_rad: f64) -> PuppybotRobotDreamsHarness {
    PuppybotRobotDreamsHarness::with_arm_pose([
        yaw_rad,
        90.0_f64.to_radians(),
        90.0_f64.to_radians(),
        90.0_f64.to_radians(),
    ])
}

fn assert_angle_equivalent_rad(actual: f64, expected: f64, tolerance: f64, label: &str) {
    let error = (actual - expected + std::f64::consts::PI)
        .rem_euclid(std::f64::consts::TAU)
        - std::f64::consts::PI;
    assert!(
        error.abs() <= tolerance,
        "{label} angle mismatch: actual_rad={actual:.6} expected_rad={expected:.6} error_rad={error:.6} tolerance_rad={tolerance:.6}"
    );
}

fn coordinate_move(frame: TcpFrame, case: CoordinateButtonCase) -> ArmCommand {
    ArmCommand::MoveTcpRelative {
        frame,
        dx_mm: case.dx_mm,
        dy_mm: case.dy_mm,
        dz_mm: case.dz_mm,
    }
}

fn coordinate_jog(frame: TcpFrame, case: CoordinateButtonCase) -> ArmCommand {
    ArmCommand::StartTcpJog {
        frame,
        direction: [
            axis_sign(case.dx_mm),
            axis_sign(case.dy_mm),
            axis_sign(case.dz_mm),
        ],
        speed_mm_s: 20.0,
    }
}

fn axis_sign(value: f64) -> f64 {
    if value == 0.0 { 0.0 } else { value.signum() }
}

fn assert_coordinate_jog_preserves_other_axes(frame: TcpFrame, case: CoordinateButtonCase) {
    const SAMPLE_EVERY_CYCLES: usize = 5;
    const STOP_SETTLE_CYCLES: usize = 30;
    const STOP_DRIFT_TOLERANCE_M: f64 = 0.002;

    let mut harness = test_harness();
    let start_tcp = harness.tcp_position();
    let mut samples = harness.run_arm_command_sampled(
        coordinate_jog(frame, case),
        case.jog_hold_cycles,
        SAMPLE_EVERY_CYCLES,
    );
    samples.push(harness.tcp_position());

    let actual_movement = samples
        .iter()
        .map(|tcp| {
            case.movement_axes
                .iter()
                .map(|axis| {
                    let delta = tcp[*axis] - start_tcp[*axis];
                    delta * delta
                })
                .sum::<f64>()
                .sqrt()
        })
        .fold(0.0, f64::max);

    assert!(
        actual_movement > case.jog_minimum_m,
        "{frame:?} coordinate {} jog should move on commanded axes: start={start_tcp:?} actual_movement_mm={:.3}",
        case.name,
        actual_movement * 1000.0
    );
    assert_all_samples_preserve_axes(
        frame,
        case,
        start_tcp,
        &samples,
        1,
        20.0 * case.jog_hold_cycles as f64 * 20.0 / 1000.0,
        actual_movement,
    );

    let stop_samples = harness.run_arm_command_sampled(
        ArmCommand::StopTcpJog,
        STOP_SETTLE_CYCLES,
        SAMPLE_EVERY_CYCLES,
    );
    let stop_start = *stop_samples.first().unwrap_or_else(|| {
        panic!(
            "{frame:?} coordinate {} stop should produce samples",
            case.name
        )
    });
    let stop_end = *stop_samples.last().unwrap_or_else(|| {
        panic!(
            "{frame:?} coordinate {} stop should produce samples",
            case.name
        )
    });
    assert!(
        distance(stop_start, stop_end) <= STOP_DRIFT_TOLERANCE_M,
        "{frame:?} coordinate {} should stop after release: first_stop={stop_start:?} last_stop={stop_end:?} drift_mm={:.3} tolerance_mm={:.3}",
        case.name,
        distance(stop_start, stop_end) * 1000.0,
        STOP_DRIFT_TOLERANCE_M * 1000.0
    );
}

fn assert_vertical_coordinate_jog_changes_z(frame: TcpFrame, case: CoordinateButtonCase) {
    const HOLD_CYCLES: usize = 120;
    const SAMPLE_EVERY_CYCLES: usize = 10;
    const MIN_Z_MOVEMENT_M: f64 = 0.005;
    const STOP_SETTLE_CYCLES: usize = 30;
    const STOP_DRIFT_TOLERANCE_M: f64 = 0.002;

    let mut harness = test_harness();
    let start_tcp = harness.tcp_position();
    let samples = harness.run_arm_command_sampled(
        coordinate_jog(frame, case),
        HOLD_CYCLES,
        SAMPLE_EVERY_CYCLES,
    );
    let end_tcp = *samples.last().unwrap_or_else(|| {
        panic!(
            "{frame:?} coordinate {} jog should produce samples",
            case.name
        )
    });
    let z_delta = end_tcp[2] - start_tcp[2];
    let expected_sign = case.dz_mm.signum();

    assert!(
        z_delta * expected_sign > MIN_Z_MOVEMENT_M,
        "{frame:?} coordinate {} jog should move ROS Z with sign {expected_sign}: start={start_tcp:?} end={end_tcp:?} z_delta_mm={:.3}",
        case.name,
        z_delta * 1000.0
    );

    let stop_samples = harness.run_arm_command_sampled(
        ArmCommand::StopTcpJog,
        STOP_SETTLE_CYCLES,
        SAMPLE_EVERY_CYCLES,
    );
    let stop_start = *stop_samples.first().unwrap_or_else(|| {
        panic!(
            "{frame:?} coordinate {} stop should produce samples",
            case.name
        )
    });
    let stop_end = *stop_samples.last().unwrap_or_else(|| {
        panic!(
            "{frame:?} coordinate {} stop should produce samples",
            case.name
        )
    });
    assert!(
        distance(stop_start, stop_end) <= STOP_DRIFT_TOLERANCE_M,
        "{frame:?} coordinate {} should stop after release: first_stop={stop_start:?} last_stop={stop_end:?} drift_mm={:.3}",
        case.name,
        distance(stop_start, stop_end) * 1000.0
    );
}

fn assert_down_jog_reaches_floor_threshold(frame: TcpFrame) {
    let mut harness = test_harness();
    assert_down_jog_reaches_floor_threshold_with_harness(frame, "default", &mut harness);
}

fn assert_down_jog_reaches_floor_threshold_with_harness(
    frame: TcpFrame,
    direction_name: &str,
    harness: &mut PuppybotRobotDreamsHarness,
) -> [f64; 3] {
    const HOLD_CYCLES: usize = 500;
    const SAMPLE_EVERY_CYCLES: usize = 10;
    const JOG_SPEED_MM_S: f64 = 120.0;

    let start_tcp = harness.tcp_position();
    let samples = harness
        .try_run_arm_command_sampled(
            ArmCommand::StartTcpJog {
                frame,
                direction: [0.0, 0.0, -1.0],
                speed_mm_s: JOG_SPEED_MM_S,
            },
            HOLD_CYCLES,
            SAMPLE_EVERY_CYCLES,
        )
        .expect("down jog command should be accepted");
    let final_tcp = harness.tcp_position();
    let min_tcp = samples
        .iter()
        .copied()
        .chain(std::iter::once(final_tcp))
        .min_by(|left, right| left[2].total_cmp(&right[2]))
        .expect("down jog should produce samples");
    let wrist_link = harness.location_position("part_1_4");
    let telemetry = harness.arm_telemetry();
    let floor_threshold = FLOOR_TOP_Z_M + TCP_FLOOR_TOUCH_TOLERANCE_M;

    assert!(
        min_tcp[2] <= floor_threshold,
        "{frame:?} coordinate down jog should bring RobotDreams TCP close to the floor in {direction_name} direction: \
         floor_top_z_m={FLOOR_TOP_Z_M:.3} threshold_z_m={floor_threshold:.3} \
         start_tcp={start_tcp:?} min_tcp={min_tcp:?} final_tcp={final_tcp:?} \
         puppybot_coords_mm={:?} puppybot_target_coords_mm={:?} \
         wrist_link={wrist_link:?} \
         yaw_rad={:.3} shoulder_rad={:.3} elbow_rad={:.3} wrist_rad={:.3} \
         servo_targets=[{:?}, {:?}, {:?}, {:?}] \
         servo_present=[{:?}, {:?}, {:?}, {:?}]",
        telemetry.coords_mm,
        telemetry.target_coords_mm,
        harness.joint_position_rad("yaw"),
        harness.joint_position_rad("shoulder"),
        harness.joint_position_rad("elbow"),
        harness.joint_position_rad("wrist"),
        harness.servo_target_position(1),
        harness.servo_target_position(2),
        harness.servo_target_position(3),
        harness.servo_target_position(4),
        harness.servo_present_position(1),
        harness.servo_present_position(2),
        harness.servo_present_position(3),
        harness.servo_present_position(4),
    );
    min_tcp
}

fn assert_up_jog_reaches_body_clearance_with_harness(
    frame: TcpFrame,
    direction_name: &str,
    harness: &mut PuppybotRobotDreamsHarness,
) -> [f64; 3] {
    const HOLD_CYCLES: usize = 300;
    const SAMPLE_EVERY_CYCLES: usize = 10;
    const JOG_SPEED_MM_S: f64 = 120.0;

    let start_tcp = harness.tcp_position();
    let samples = harness.run_arm_command_sampled(
        ArmCommand::StartTcpJog {
            frame,
            direction: [0.0, 0.0, 1.0],
            speed_mm_s: JOG_SPEED_MM_S,
        },
        HOLD_CYCLES,
        SAMPLE_EVERY_CYCLES,
    );
    let final_tcp = harness.tcp_position();
    let max_tcp = samples
        .iter()
        .copied()
        .chain(std::iter::once(final_tcp))
        .max_by(|left, right| left[2].total_cmp(&right[2]))
        .expect("up jog should produce samples");

    assert!(
        max_tcp[2] >= TCP_ABOVE_BODY_CLEARANCE_Z_M,
        "{frame:?} coordinate up jog should lift RobotDreams TCP above the PuppyBot body in {direction_name} direction: \
         body_clearance_z_m={TCP_ABOVE_BODY_CLEARANCE_Z_M:.3} \
         start_tcp={start_tcp:?} max_tcp={max_tcp:?} final_tcp={final_tcp:?} \
         yaw_rad={:.3} shoulder_rad={:.3} elbow_rad={:.3} wrist_rad={:.3} \
         servo_targets=[{:?}, {:?}, {:?}, {:?}]",
        harness.joint_position_rad("yaw"),
        harness.joint_position_rad("shoulder"),
        harness.joint_position_rad("elbow"),
        harness.joint_position_rad("wrist"),
        harness.servo_target_position(1),
        harness.servo_target_position(2),
        harness.servo_target_position(3),
        harness.servo_target_position(4),
    );
    max_tcp
}

fn assert_floor_and_body_clearance_in_cardinal_directions(frame: TcpFrame) {
    for direction in CARDINAL_WORKSPACE_DIRECTIONS {
        let mut floor_harness = test_harness_with_yaw(direction.yaw_rad);
        assert_down_jog_reaches_floor_threshold_with_harness(
            frame,
            direction.name,
            &mut floor_harness,
        );

        let mut clearance_harness = test_harness_with_yaw(direction.yaw_rad);
        assert_up_jog_reaches_body_clearance_with_harness(
            frame,
            direction.name,
            &mut clearance_harness,
        );
    }
}

fn assert_final_sample_preserves_axes(
    frame: TcpFrame,
    case: CoordinateButtonCase,
    start_tcp: [f64; 3],
    samples: &[[f64; 3]],
    accepted_presses: usize,
    button_step_mm: f64,
    actual_movement: f64,
) {
    let final_tcp = *samples
        .last()
        .unwrap_or_else(|| panic!("{frame:?} {} should produce final TCP sample", case.name));
    for stable_axis in case.stable_axes {
        let drift = (final_tcp[*stable_axis] - start_tcp[*stable_axis]).abs();
        assert!(
            drift <= REPEATED_MOVE_STABLE_AXIS_TOLERANCE_M,
            "{frame:?} {} final target changed stable axis {stable_axis}: start={start_tcp:?} final={final_tcp:?} accepted_presses={accepted_presses} commanded_mm={:.1} actual_movement_mm={:.3} drift_m={drift:.6} drift_mm={:.3} tolerance_m={REPEATED_MOVE_STABLE_AXIS_TOLERANCE_M:.6}",
            case.name,
            accepted_presses as f64 * button_step_mm,
            actual_movement * 1000.0,
            drift * 1000.0
        );
    }
}

fn assert_all_samples_preserve_axes(
    frame: TcpFrame,
    case: CoordinateButtonCase,
    start_tcp: [f64; 3],
    samples: &[[f64; 3]],
    accepted_presses: usize,
    button_step_mm: f64,
    actual_movement: f64,
) {
    assert!(
        !samples.is_empty(),
        "{frame:?} {} should produce TCP samples",
        case.name
    );
    for stable_axis in case.stable_axes {
        let mut worst_index = 0;
        let mut worst_tcp = samples[0];
        let mut worst_drift = 0.0;
        for (index, tcp) in samples.iter().enumerate() {
            let drift = (tcp[*stable_axis] - start_tcp[*stable_axis]).abs();
            if drift > worst_drift {
                worst_index = index;
                worst_tcp = *tcp;
                worst_drift = drift;
            }
        }
        assert!(
            worst_drift <= REPEATED_MOVE_STABLE_AXIS_TOLERANCE_M,
            "{frame:?} {} sample {worst_index} changed stable axis {stable_axis}: start={start_tcp:?} sample={worst_tcp:?} accepted_presses={accepted_presses} commanded_mm={:.1} actual_movement_mm={:.3} drift_m={worst_drift:.6} drift_mm={:.3} tolerance_m={REPEATED_MOVE_STABLE_AXIS_TOLERANCE_M:.6}",
            case.name,
            accepted_presses as f64 * button_step_mm,
            actual_movement * 1000.0,
            worst_drift * 1000.0
        );
    }
}

#[test]
fn base_move_forward_once_z_no_change() {
    assert_coordinate_forward_preserves_model_up_axis(TcpFrame::Base);
}

#[test]
fn yaw_flat_move_forward_once_z_no_change() {
    assert_coordinate_forward_preserves_model_up_axis(TcpFrame::YawFlat);
}

#[test]
fn puppybot_runtime_ninety_pose_maps_to_robotdreams_reference_pose() {
    let harness = PuppybotRobotDreamsHarness::with_arm_pose([
        std::f64::consts::FRAC_PI_2,
        std::f64::consts::FRAC_PI_2,
        std::f64::consts::FRAC_PI_2,
        std::f64::consts::FRAC_PI_2,
    ]);

    assert_angle_equivalent_rad(
        harness.joint_position_rad("yaw"),
        std::f64::consts::PI,
        0.005,
        "yaw",
    );
    assert_angle_equivalent_rad(harness.joint_position_rad("shoulder"), 0.0, 0.005, "shoulder");
    assert_angle_equivalent_rad(
        harness.joint_position_rad("elbow"),
        std::f64::consts::FRAC_PI_2,
        0.005,
        "elbow",
    );
    assert_angle_equivalent_rad(
        harness.joint_position_rad("wrist"),
        std::f64::consts::PI,
        0.005,
        "wrist",
    );
}

#[test]
fn base_move_forward_z_no_change() {
    assert_coordinate_button_until_unreachable_preserves_other_axes(TcpFrame::Base, FORWARD);
}

#[test]
fn yaw_flat_move_forward_z_no_change() {
    assert_coordinate_button_until_unreachable_preserves_other_axes(TcpFrame::YawFlat, FORWARD);
}

#[test]
fn base_move_back_z_no_change() {
    assert_coordinate_button_until_unreachable_preserves_other_axes(TcpFrame::Base, BACK);
}

#[test]
fn yaw_flat_move_back_z_no_change() {
    assert_coordinate_button_until_unreachable_preserves_other_axes(TcpFrame::YawFlat, BACK);
}

#[test]
fn base_move_left_z_no_change() {
    assert_coordinate_button_until_unreachable_preserves_other_axes(TcpFrame::Base, LEFT);
}

#[test]
fn yaw_flat_move_left_z_no_change() {
    assert_coordinate_button_until_unreachable_preserves_other_axes(TcpFrame::YawFlat, LEFT);
}

#[test]
fn base_move_right_z_no_change() {
    assert_coordinate_button_until_unreachable_preserves_other_axes(TcpFrame::Base, RIGHT);
}

#[test]
fn yaw_flat_move_right_z_no_change() {
    assert_coordinate_button_until_unreachable_preserves_other_axes(TcpFrame::YawFlat, RIGHT);
}

#[test]
fn base_move_up_z_changes() {
    assert_coordinate_button_until_unreachable_preserves_other_axes(TcpFrame::Base, UP);
}

#[test]
fn yaw_flat_move_up_z_changes() {
    assert_coordinate_button_until_unreachable_preserves_other_axes(TcpFrame::YawFlat, UP);
}

#[test]
fn base_move_down_xy_no_change() {
    assert_coordinate_button_until_unreachable_preserves_other_axes(TcpFrame::Base, DOWN);
}

#[test]
fn yaw_flat_move_down_xy_no_change() {
    assert_coordinate_button_until_unreachable_preserves_other_axes(TcpFrame::YawFlat, DOWN);
}

#[test]
fn base_jog_forward_z_no_change() {
    assert_coordinate_jog_preserves_other_axes(TcpFrame::Base, FORWARD);
}

#[test]
fn yaw_flat_jog_forward_z_no_change() {
    assert_coordinate_jog_preserves_other_axes(TcpFrame::YawFlat, FORWARD);
}

#[test]
fn base_jog_back_z_no_change() {
    assert_coordinate_jog_preserves_other_axes(TcpFrame::Base, BACK);
}

#[test]
fn yaw_flat_jog_back_z_no_change() {
    assert_coordinate_jog_preserves_other_axes(TcpFrame::YawFlat, BACK);
}

#[test]
fn base_jog_left_z_no_change() {
    assert_coordinate_jog_preserves_other_axes(TcpFrame::Base, LEFT);
}

#[test]
fn yaw_flat_jog_left_z_no_change() {
    assert_coordinate_jog_preserves_other_axes(TcpFrame::YawFlat, LEFT);
}

#[test]
fn base_jog_right_z_no_change() {
    assert_coordinate_jog_preserves_other_axes(TcpFrame::Base, RIGHT);
}

#[test]
fn yaw_flat_jog_right_z_no_change() {
    assert_coordinate_jog_preserves_other_axes(TcpFrame::YawFlat, RIGHT);
}

#[test]
fn base_jog_up_z_changes() {
    assert_coordinate_jog_preserves_other_axes(TcpFrame::Base, UP);
}

#[test]
fn yaw_flat_jog_up_z_changes() {
    assert_coordinate_jog_preserves_other_axes(TcpFrame::YawFlat, UP);
}

#[test]
fn base_jog_up_z_increases() {
    assert_vertical_coordinate_jog_changes_z(TcpFrame::Base, UP);
}

#[test]
fn yaw_flat_jog_up_z_increases() {
    assert_vertical_coordinate_jog_changes_z(TcpFrame::YawFlat, UP);
}

#[test]
fn base_jog_down_z_decreases() {
    assert_vertical_coordinate_jog_changes_z(TcpFrame::Base, DOWN);
}

#[test]
fn yaw_flat_jog_down_z_decreases() {
    assert_vertical_coordinate_jog_changes_z(TcpFrame::YawFlat, DOWN);
}

#[test]
fn base_jog_down_reaches_floor_threshold() {
    assert_down_jog_reaches_floor_threshold(TcpFrame::Base);
}

#[test]
fn base_jog_reaches_floor_and_body_clearance_in_cardinal_directions() {
    assert_floor_and_body_clearance_in_cardinal_directions(TcpFrame::Base);
}
