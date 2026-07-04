use puppybot_core::puppyarm::types::{ArmCommand, TcpFrame};

use harness::{
    MODEL_UP_TOLERANCE_M, PuppybotRobotDreamsHarness, assert_close_m, distance,
    puppybot_model_up_axis,
};

#[path = "support/harness.rs"]
mod harness;

#[test]
fn base_coordinate_forward_command_moves_robotdreams_tcp_without_pitching_up_axis() {
    assert_coordinate_forward_preserves_model_up_axis(TcpFrame::Base);
}

#[test]
fn yaw_flat_coordinate_forward_command_moves_robotdreams_tcp_without_pitching_up_axis() {
    assert_coordinate_forward_preserves_model_up_axis(TcpFrame::YawFlat);
}

fn assert_coordinate_forward_preserves_model_up_axis(frame: TcpFrame) {
    let model_up_axis = puppybot_model_up_axis();
    let mut harness = PuppybotRobotDreamsHarness::with_arm_pose([
        0.0,
        std::f64::consts::FRAC_PI_2,
        std::f64::consts::FRAC_PI_2,
        std::f64::consts::FRAC_PI_2,
    ]);
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
