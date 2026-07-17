use puppybot_core::drive::DriveCommand;
use puppybot_core::puppyarm::kinematics::{solve_tip_angle_down, tool_pitch};
use puppybot_core::puppyarm::types::{ArmCommand, TcpFrame};
use robotdreams_core::RobotDreams;

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
        ArmCommand::MoveTcp {
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
    jog_hold_cycles: 250,
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
    jog_hold_cycles: 250,
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
    jog_hold_cycles: 200,
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
    jog_hold_cycles: 200,
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
            55.0_f64.to_radians(),
            65.0_f64.to_radians(),
            10.0_f64.to_radians(),
        ]);
    }
    test_harness()
}

fn test_harness() -> PuppybotRobotDreamsHarness {
    test_harness_with_yaw(0.0)
}

fn reference_default_pose() -> ([f64; 4], [f64; 3], [f64; 3]) {
    let project =
        std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../robotdreams/project.json");
    let mut dreams = RobotDreams::open(project).expect("open reference RobotDreams project");
    let q = [
        -2133.0 * std::f64::consts::TAU / 4096.0,
        37.0 * std::f64::consts::TAU / 4096.0,
        -2568.0 * std::f64::consts::TAU / 4096.0,
        1485.0 * std::f64::consts::TAU / 4096.0,
    ];
    for (joint, angle) in ["revolute_2_3", "revolute_1_1", "revolute_1_2", "revolute_1"]
        .into_iter()
        .zip(q)
    {
        dreams
            .set_joint_angle(joint, angle)
            .unwrap_or_else(|error| panic!("set reference joint {joint}: {error}"));
    }
    let tcp = dreams
        .robot_state("puppybot")
        .and_then(|state| state.tcp)
        .and_then(|tcp| tcp.location)
        .expect("reference TCP")
        .position;
    let wrist = dreams
        .location_of("part_1_4")
        .expect("reference wrist link")
        .position;
    (q, wrist, tcp)
}

#[test]
fn default_ninety_pose_converges_to_physical_reference_from_multiple_starts() {
    const SETTLE_TOLERANCE_RAD: f64 = 8.5 * std::f64::consts::TAU / 4096.0;
    const POSITION_TOLERANCE_M: f64 = 0.005;
    let (reference_q, reference_wrist, reference_tcp) = reference_default_pose();
    let starts = [
        [0.0, 55.0, 65.0, 10.0],
        [-45.0, 110.0, 35.0, -30.0],
        [150.0, 20.0, 125.0, 160.0],
    ];

    for start_deg in starts {
        let mut harness = PuppybotRobotDreamsHarness::with_arm_pose(start_deg.map(f64::to_radians));
        harness.run_arm_command_until_settled(
            ArmCommand::GotoAngles([std::f64::consts::FRAC_PI_2; 4]),
            900,
        );
        let telemetry = harness.arm_telemetry();
        for (joint, expected_q) in ["yaw", "shoulder", "elbow", "wrist"]
            .into_iter()
            .zip(reference_q)
        {
            let actual_q = harness.joint_position_rad(joint);
            let delta = (actual_q - expected_q + std::f64::consts::PI)
                .rem_euclid(std::f64::consts::TAU)
                - std::f64::consts::PI;
            assert!(
                delta.abs() <= SETTLE_TOLERANCE_RAD,
                "Default from {start_deg:?}: {joint} q delta {} deg",
                delta.to_degrees()
            );
        }
        for joint in telemetry.joints {
            assert!(
                (joint.angle_deg().expect("Default feedback angle") - 90.0).abs() <= 0.75,
                "Default from {start_deg:?} must report 90 degrees: {joint:?}"
            );
        }
        let wrist = harness.location_position("part_1_4");
        assert!(
            distance(wrist, reference_wrist) <= POSITION_TOLERANCE_M,
            "Default wrist transform differs from physical reference for {start_deg:?}: actual={wrist:?} reference={reference_wrist:?} delta_mm={:.3}",
            distance(wrist, reference_wrist) * 1000.0,
        );
        assert!(
            distance(harness.tcp_position(), reference_tcp) <= POSITION_TOLERANCE_M,
            "Default TCP differs from physical reference for {start_deg:?}: actual={:?} reference={reference_tcp:?}",
            harness.tcp_position(),
        );
    }
}

fn assert_vertical_workspace_endpoint_matches_robotdreams(
    name: &str,
    target_coords_mm: [f64; 3],
    target_angles_deg: [f64; 4],
) {
    const TARGET_MODEL_TOLERANCE_M: f64 = 0.002;
    let mut harness =
        PuppybotRobotDreamsHarness::with_arm_pose_without_physics([std::f64::consts::FRAC_PI_2; 4]);
    harness.set_urdf_from_analytic_pose(target_angles_deg.map(f64::to_radians));
    let model_tcp = harness.tcp_position();
    let world_target = harness.frame_world_transform("armBase").transform_point([
        target_coords_mm[0] * 0.001,
        target_coords_mm[1] * 0.001,
        target_coords_mm[2] * 0.001,
    ]);
    assert!(
        distance(model_tcp, world_target) <= TARGET_MODEL_TOLERANCE_M,
        "{name} controller target and RobotDreams TCP differ: target={world_target:?} model={model_tcp:?} delta_mm={:.3}",
        distance(model_tcp, world_target) * 1000.0,
    );
    println!(
        "{name}: controller endpoint={target_coords_mm:?}; RobotDreams TCP={model_tcp:?}; target-model={:.3} mm",
        distance(model_tcp, world_target) * 1000.0,
    );
}

#[test]
fn vertical_workspace_endpoint_analytic_poses_match_robotdreams_world_tcp() {
    // The controller boundary/outward-probe/release behavior is covered in
    // puppybot-core. Down lies below the collision floor, so this verifies the
    // exact RobotDreams FK/render transform without stepping collision physics.
    assert_vertical_workspace_endpoint_matches_robotdreams(
        "down",
        [160.390, -1.718, -17.983],
        [90.0, 118.21289, 60.64453, 32.34375],
    );
    assert_vertical_workspace_endpoint_matches_robotdreams(
        "up",
        [160.390, -1.718, 178.094],
        [90.0, 92.90039, 109.86328, 106.96289],
    );
}

fn test_harness_with_yaw(yaw_rad: f64) -> PuppybotRobotDreamsHarness {
    let shoulder = 55.0_f64.to_radians();
    let elbow = 65.0_f64.to_radians();
    PuppybotRobotDreamsHarness::with_arm_pose([
        yaw_rad,
        shoulder,
        elbow,
        solve_tip_angle_down(shoulder, elbow, (-73.3004_f64).to_radians()),
    ])
}

fn floor_test_harness_with_yaw(yaw_rad: f64) -> PuppybotRobotDreamsHarness {
    let shoulder = (-20.0_f64).to_radians();
    let elbow = 70.0_f64.to_radians();
    PuppybotRobotDreamsHarness::with_arm_pose([
        yaw_rad,
        shoulder,
        elbow,
        solve_tip_angle_down(shoulder, elbow, (-103.3004_f64).to_radians()),
    ])
}

#[test]
fn analytic_tcp_matches_urdf_tcp_through_arm_base_at_multiple_rover_poses() {
    const MAX_RESIDUAL_M: f64 = 0.002;
    let poses = [
        [0.0, 1.2, 0.7, -0.4],
        [0.5, 0.8, 1.4, 0.3],
        [-0.8, 1.6, 0.4, 1.0],
        [1.1, 1.0, 1.8, -0.7],
    ];
    let mut analytic_points = Vec::new();
    let mut max_residual: f64 = 0.0;

    for pose in poses {
        let mut harness = PuppybotRobotDreamsHarness::with_arm_pose(pose);
        harness.run_idle_cycles(4);
        harness.run_repeated_drive_command(
            DriveCommand::DriveSteer {
                throttle: 45,
                steering: 35,
            },
            35,
        );
        harness.run_drive_command(DriveCommand::Stop, 1);
        let base = harness.base_position();
        let base_yaw = harness.base_yaw();
        assert!(
            base[0].hypot(base[1]) > 0.001,
            "rover translation must be nonzero"
        );
        assert!(base_yaw.abs() > 0.001, "rover yaw must be nonzero");

        let telemetry = harness.arm_telemetry();
        let analytic_angles = telemetry
            .joints
            .map(|joint| joint.angle_rad.expect("analytic joint feedback"));
        harness.set_urdf_from_analytic_pose(analytic_angles);
        let (x, y, z) = telemetry.coords_mm.expect("analytic TCP");
        let analytic_m = [
            f64::from(x) * 0.001,
            f64::from(y) * 0.001,
            f64::from(z) * 0.001,
        ];
        let expected_world = harness
            .frame_world_transform("armBase")
            .transform_point(analytic_m);
        let urdf_world = harness.tcp_position();
        max_residual = max_residual.max(distance(expected_world, urdf_world));
        analytic_points.push(analytic_m);
    }

    let first = vector_between(analytic_points[0], analytic_points[1]);
    let second = vector_between(analytic_points[0], analytic_points[2]);
    assert!(
        vector_length(cross_product(first, second)) > 1.0e-4,
        "fit poses must be non-collinear"
    );
    assert!(
        max_residual <= MAX_RESIDUAL_M,
        "armBase rigid transform residual exceeds tolerance: max_residual_mm={:.3}",
        max_residual * 1000.0,
    );
}

#[test]
fn serialized_puppybot_commands_match_urdf_tcp_after_rover_motion() {
    const MAX_RESIDUAL_M: f64 = 0.002;
    const MAX_SETTLE_CYCLES: usize = 1_200;
    let poses = [
        [
            0.20,
            55.0_f64.to_radians(),
            65.0_f64.to_radians(),
            10.0_f64.to_radians(),
        ],
        [
            -0.55,
            62.0_f64.to_radians(),
            82.0_f64.to_radians(),
            35.0_f64.to_radians(),
        ],
        [
            0.85,
            50.0_f64.to_radians(),
            95.0_f64.to_radians(),
            -5.0_f64.to_radians(),
        ],
    ];
    let mut harness = PuppybotRobotDreamsHarness::with_arm_pose([
        0.0,
        55.0_f64.to_radians(),
        65.0_f64.to_radians(),
        10.0_f64.to_radians(),
    ]);
    harness.run_repeated_drive_command(
        DriveCommand::DriveSteer {
            throttle: 45,
            steering: 35,
        },
        35,
    );
    harness.run_drive_command(DriveCommand::Stop, 1);
    let base = harness.base_position();
    assert!(
        base[0].hypot(base[1]) > 0.001,
        "rover translation must be nonzero"
    );
    assert!(
        harness.base_yaw().abs() > 0.001,
        "rover yaw must be nonzero"
    );

    let mut analytic_points = Vec::new();
    let mut max_residual: f64 = 0.0;
    for pose in poses {
        harness.clear_bus_events();
        harness.run_arm_command_until_settled(ArmCommand::GotoAngles(pose), MAX_SETTLE_CYCLES);
        harness.assert_no_bus_errors();
        let events = harness.bus_events();
        assert!(
            events.iter().any(|event| {
                event.instruction == "write"
                    && event.id.is_some_and(|id| (1..=4).contains(&id))
                    && event.responded
            }),
            "arm pose must pass through responded serialized servo writes: {events:?}"
        );

        let telemetry = harness.arm_telemetry();
        let (x, y, z) = telemetry.coords_mm.expect("settled controller TCP");
        let analytic_m = [
            f64::from(x) * 0.001,
            f64::from(y) * 0.001,
            f64::from(z) * 0.001,
        ];
        let transformed_current = harness
            .frame_world_transform("armBase")
            .transform_point(analytic_m);
        let cyan_urdf_tcp = harness.tcp_position();
        max_residual = max_residual.max(distance(transformed_current, cyan_urdf_tcp));
        analytic_points.push(analytic_m);
    }

    let first = vector_between(analytic_points[0], analytic_points[1]);
    let second = vector_between(analytic_points[0], analytic_points[2]);
    assert!(
        vector_length(cross_product(first, second)) > 1.0e-4,
        "settled live-path poses must be non-collinear"
    );
    assert!(
        max_residual <= MAX_RESIDUAL_M,
        "serialized Puppybot -> virtual bus -> RobotDreams TCP residual exceeds tolerance: max_residual_mm={:.3}",
        max_residual * 1000.0,
    );
}

#[test]
fn current_and_hold_targets_match_transformed_current_and_urdf_tcp() {
    const MAX_TCP_DRIFT_M: f64 = 0.002;
    let mut harness = PuppybotRobotDreamsHarness::with_arm_pose([
        0.0,
        55.0_f64.to_radians(),
        65.0_f64.to_radians(),
        10.0_f64.to_radians(),
    ]);
    harness.run_idle_cycles(8);
    harness.run_repeated_drive_command(
        DriveCommand::DriveSteer {
            throttle: 40,
            steering: 30,
        },
        30,
    );
    harness.run_drive_command(DriveCommand::Stop, 1);
    let base = harness.base_position();
    assert!(
        base[0].hypot(base[1]) > 0.001,
        "rover translation must be nonzero"
    );
    assert!(
        harness.base_yaw().abs() > 0.001,
        "rover yaw must be nonzero"
    );
    let before = harness.tcp_position();
    let telemetry = harness.arm_telemetry();
    let (x, y, z) = telemetry.coords_mm.expect("current analytic TCP");
    let angles = telemetry
        .joints
        .map(|joint| joint.angle_rad.expect("current analytic joint angle"));
    let tool_phi_rad = tool_pitch(angles[1], angles[2], angles[3]);
    let world_from_arm_base = harness.frame_world_transform("armBase");
    let transformed_current = world_from_arm_base.transform_point([
        f64::from(x) * 0.001,
        f64::from(y) * 0.001,
        f64::from(z) * 0.001,
    ]);
    assert!(
        distance(transformed_current, before) <= MAX_TCP_DRIFT_M,
        "transformed controller current disagrees with cyan URDF TCP: transformed={transformed_current:?} urdf={before:?} residual_mm={:.3}",
        distance(transformed_current, before) * 1000.0,
    );

    harness.run_arm_command(ArmCommand::Hold, 1);
    let hold = harness.arm_telemetry();
    let hold_target = hold
        .effective_target_coords_mm
        .expect("Hold effective analytic target");
    let transformed_hold_target = world_from_arm_base.transform_point([
        f64::from(hold_target.0) * 0.001,
        f64::from(hold_target.1) * 0.001,
        f64::from(hold_target.2) * 0.001,
    ]);
    assert!(
        distance(transformed_hold_target, harness.tcp_position()) <= MAX_TCP_DRIFT_M,
        "transformed Hold target disagrees with cyan URDF TCP: transformed={transformed_hold_target:?} urdf={:?} residual_mm={:.3}",
        harness.tcp_position(),
        distance(transformed_hold_target, harness.tcp_position()) * 1000.0,
    );

    harness.run_arm_command(
        ArmCommand::GotoCoords {
            x: f64::from(x),
            y: f64::from(y),
            z: f64::from(z),
            tool_phi_rad,
        },
        160,
    );

    let after = harness.tcp_position();
    assert!(
        distance(before, after) <= MAX_TCP_DRIFT_M,
        "Current -> Move changed URDF TCP: before={before:?} after={after:?} drift_mm={:.3}",
        distance(before, after) * 1000.0,
    );
}

fn vector_between(from: [f64; 3], to: [f64; 3]) -> [f64; 3] {
    [to[0] - from[0], to[1] - from[1], to[2] - from[2]]
}

fn cross_product(left: [f64; 3], right: [f64; 3]) -> [f64; 3] {
    [
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    ]
}

fn vector_length(value: [f64; 3]) -> f64 {
    (value[0] * value[0] + value[1] * value[1] + value[2] * value[2]).sqrt()
}

fn assert_angle_equivalent_rad(actual: f64, expected: f64, tolerance: f64, label: &str) {
    let error = (actual - expected + std::f64::consts::PI).rem_euclid(std::f64::consts::TAU)
        - std::f64::consts::PI;
    assert!(
        error.abs() <= tolerance,
        "{label} angle mismatch: actual_rad={actual:.6} expected_rad={expected:.6} error_rad={error:.6} tolerance_rad={tolerance:.6}"
    );
}

fn coordinate_move(frame: TcpFrame, case: CoordinateButtonCase) -> ArmCommand {
    ArmCommand::MoveTcp {
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
    harness.run_arm_command(ArmCommand::SetSpeed(20), 1);
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
    const HOLD_CYCLES: usize = 140;
    const SAMPLE_EVERY_CYCLES: usize = 10;
    const MIN_Z_MOVEMENT_M: f64 = 0.005;
    const STOP_SETTLE_CYCLES: usize = 30;
    const STOP_DRIFT_TOLERANCE_M: f64 = 0.002;

    let mut harness = test_harness();
    let start_tcp = harness.tcp_position();
    harness.run_arm_command(ArmCommand::SetSpeed(20), 1);
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
    let mut harness = floor_test_harness_with_yaw(0.0);
    assert_down_jog_reaches_floor_threshold_with_harness(frame, "default", &mut harness);
}

fn assert_down_jog_reaches_floor_threshold_with_harness(
    frame: TcpFrame,
    direction_name: &str,
    harness: &mut PuppybotRobotDreamsHarness,
) -> [f64; 3] {
    const HOLD_CYCLES: usize = 500;
    const SAMPLE_EVERY_CYCLES: usize = 10;
    const JOG_SPEED_MM_S: i16 = 120;

    let start_tcp = harness.tcp_position();
    harness.run_arm_command(ArmCommand::SetSpeed(JOG_SPEED_MM_S), 1);
    let samples = harness
        .try_run_arm_command_sampled(
            ArmCommand::StartTcpJog {
                frame,
                direction: [0.0, 0.0, -1.0],
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
    const JOG_SPEED_MM_S: i16 = 120;

    let start_tcp = harness.tcp_position();
    harness.run_arm_command(ArmCommand::SetSpeed(JOG_SPEED_MM_S), 1);
    let samples = harness.run_arm_command_sampled(
        ArmCommand::StartTcpJog {
            frame,
            direction: [0.0, 0.0, 1.0],
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
        let mut floor_harness = floor_test_harness_with_yaw(direction.yaw_rad);
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
fn puppybot_runtime_ninety_pose_maps_through_analytic_model_contract() {
    let harness = PuppybotRobotDreamsHarness::with_arm_pose([
        std::f64::consts::FRAC_PI_2,
        std::f64::consts::FRAC_PI_2,
        std::f64::consts::FRAC_PI_2,
        std::f64::consts::FRAC_PI_2,
    ]);

    assert_angle_equivalent_rad(
        harness.joint_position_rad("yaw"),
        std::f64::consts::FRAC_PI_2,
        0.005,
        "yaw",
    );
    assert_angle_equivalent_rad(
        harness.joint_position_rad("shoulder"),
        -0.0089501963813258,
        0.005,
        "shoulder",
    );
    assert_angle_equivalent_rad(
        harness.joint_position_rad("elbow"),
        -3.1826878522682254,
        0.005,
        "elbow",
    );
    assert_angle_equivalent_rad(
        harness.joint_position_rad("wrist"),
        -3.2412117779955514,
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
