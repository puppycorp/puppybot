use puppybot_core::puppyarm::{
    kinematics::IkError,
    types::{ArmCommand, ControllerError, TcpFrame},
};

use harness::{
    MODEL_UP_TOLERANCE_M, PuppybotRobotDreamsHarness, assert_close_m, distance,
    puppybot_model_up_axis,
};

#[path = "support/harness.rs"]
mod harness;

// Repeated moves compare the exported CAD TCP against PuppyArm's simplified controller model.
const REPEATED_MOVE_STABLE_AXIS_TOLERANCE_M: f64 = 0.005;

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

fn assert_coordinate_forward_preserves_tool_vector(frame: TcpFrame) {
    let mut harness = test_harness();
    let start_tool = harness.tool_vector();

    harness.run_arm_command(
        ArmCommand::MoveTcpRelative {
            frame,
            dx_mm: 10.0,
            dy_mm: 0.0,
            dz_mm: 0.0,
        },
        160,
    );
    let moved_tool = harness.tool_vector();
    assert_vector_close(start_tool, moved_tool, 0.001);
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
    minimum_movement_m: f64,
}

const FORWARD: CoordinateButtonCase = CoordinateButtonCase {
    name: "Forward",
    dx_mm: 10.0,
    dy_mm: 0.0,
    dz_mm: 0.0,
    movement_axes: &[0],
    stable_axes: &[2],
    button_presses: 3,
    minimum_movement_m: 0.010,
};

const BACK: CoordinateButtonCase = CoordinateButtonCase {
    name: "Back",
    dx_mm: -10.0,
    dy_mm: 0.0,
    dz_mm: 0.0,
    movement_axes: &[0],
    stable_axes: &[2],
    button_presses: 3,
    minimum_movement_m: 0.010,
};

const LEFT: CoordinateButtonCase = CoordinateButtonCase {
    name: "Left",
    dx_mm: 0.0,
    dy_mm: 10.0,
    dz_mm: 0.0,
    movement_axes: &[0, 1],
    stable_axes: &[2],
    button_presses: 3,
    minimum_movement_m: 0.010,
};

const RIGHT: CoordinateButtonCase = CoordinateButtonCase {
    name: "Right",
    dx_mm: 0.0,
    dy_mm: -10.0,
    dz_mm: 0.0,
    movement_axes: &[0, 1],
    stable_axes: &[2],
    button_presses: 3,
    minimum_movement_m: 0.010,
};

const UP: CoordinateButtonCase = CoordinateButtonCase {
    name: "Up",
    dx_mm: 0.0,
    dy_mm: 0.0,
    dz_mm: 10.0,
    movement_axes: &[2],
    stable_axes: &[0, 1],
    button_presses: 3,
    minimum_movement_m: 0.010,
};

const DOWN: CoordinateButtonCase = CoordinateButtonCase {
    name: "Down",
    dx_mm: 0.0,
    dy_mm: 0.0,
    dz_mm: -10.0,
    movement_axes: &[2],
    stable_axes: &[0, 1],
    button_presses: 1,
    // The exported CAD TCP starts close to the floor in this motion-valid pose.
    minimum_movement_m: 0.002,
};

fn assert_coordinate_button_until_unreachable_preserves_other_axes(
    frame: TcpFrame,
    case: CoordinateButtonCase,
) {
    const BUTTON_STEP_MM: f64 = 10.0;
    const CYCLES_PER_PRESS: usize = 160;
    const SAMPLE_EVERY_CYCLES: usize = 8;

    let mut harness = test_harness();
    let start_tcp = harness.tcp_position();
    let mut accepted_presses = 0;
    let mut samples = Vec::new();

    while accepted_presses < case.button_presses {
        match harness.try_run_arm_command_sampled(
            coordinate_move(frame, case),
            CYCLES_PER_PRESS,
            SAMPLE_EVERY_CYCLES,
        ) {
            Ok(next_samples) => {
                accepted_presses += 1;
                samples.extend(next_samples);
            }
            Err(ControllerError::Ik(IkError::Unreachable)) => {
                panic!(
                    "{frame:?} coordinate {} became unreachable before {} button presses: accepted_presses={accepted_presses}",
                    case.name, case.button_presses
                );
            }
            Err(err) => {
                panic!(
                    "{frame:?} coordinate {} failed with unexpected error: {err:?}",
                    case.name
                )
            }
        }
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
    assert_all_samples_preserve_axes(
        frame,
        case,
        start_tcp,
        &samples,
        accepted_presses,
        BUTTON_STEP_MM,
        actual_movement,
    );
}

fn test_harness() -> PuppybotRobotDreamsHarness {
    PuppybotRobotDreamsHarness::with_arm_pose([
        0.0,
        std::f64::consts::FRAC_PI_2,
        std::f64::consts::FRAC_PI_2,
        std::f64::consts::FRAC_PI_2,
    ])
}

fn coordinate_move(frame: TcpFrame, case: CoordinateButtonCase) -> ArmCommand {
    ArmCommand::MoveTcpRelative {
        frame,
        dx_mm: case.dx_mm,
        dy_mm: case.dy_mm,
        dz_mm: case.dz_mm,
    }
}

trait ArmHarnessExt {
    fn tool_vector(&self) -> [f64; 3];
}

impl ArmHarnessExt for PuppybotRobotDreamsHarness {
    fn tool_vector(&self) -> [f64; 3] {
        let tcp = self.tcp_position();
        let wrist_link = self.location_position("part_1_4");
        [
            tcp[0] - wrist_link[0],
            tcp[1] - wrist_link[1],
            tcp[2] - wrist_link[2],
        ]
    }
}

fn assert_vector_close(left: [f64; 3], right: [f64; 3], tolerance_m: f64) {
    for axis in 0..3 {
        assert!(
            (left[axis] - right[axis]).abs() <= tolerance_m,
            "tool vector axis {axis} changed: start={left:?} moved={right:?} diff_m={:.6} tolerance_m={tolerance_m:.6}",
            (left[axis] - right[axis]).abs()
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
fn base_move_forward_tool_vector_no_change() {
    assert_coordinate_forward_preserves_tool_vector(TcpFrame::Base);
}

#[test]
fn yaw_flat_move_forward_tool_vector_no_change() {
    assert_coordinate_forward_preserves_tool_vector(TcpFrame::YawFlat);
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
fn base_move_up_xy_no_change() {
    assert_coordinate_button_until_unreachable_preserves_other_axes(TcpFrame::Base, UP);
}

#[test]
fn yaw_flat_move_up_xy_no_change() {
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
