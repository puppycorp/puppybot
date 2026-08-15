#!/usr/bin/env python3
"""Run the lightweight PuppyBot arm model in MuJoCo."""

import argparse
import json
import math
from pathlib import Path
import time


JOINT_NAMES = ("yaw", "shoulder", "elbow", "wrist")
ARM_BASE_POSITION_M = (0.0369572, -0.00974321, 0.1239591)
ARM_BASE_YAW_RAD = 0.1248338
ARM_YAW_TO_SHOULDER_X_M = 0.0000007026911535341386
ARM_YAW_TO_SHOULDER_Y_M = -0.019150050229126062
ARM_YAW_TO_SHOULDER_Z_M = 0.02000000056097148
ARM_L1_M = 0.14900090135823393
ARM_L2_M = 0.15500027915891692
ARM_L3_M = 0.03800009136344675
ARM_YAW_PHASE_RAD = 1.4404079598246167
ARM_L1_PHASE_RAD = 0.021156497956719415
ARM_L2_PHASE_RAD = 3.1272689969908543
ARM_L3_PHASE_RAD = -3.1709794666200595
NEAR_ZERO_XY = 1.0e-12


def parse_pose_degrees(values):
    if len(values) != len(JOINT_NAMES):
        raise argparse.ArgumentTypeError("pose requires yaw shoulder elbow wrist")
    return [math.radians(float(value)) for value in values]


def wrap_pi(angle):
    return math.atan2(math.sin(angle), math.cos(angle))


def tool_pitch(pose):
    _, shoulder, elbow, wrist = pose
    return wrap_pi(shoulder - elbow + wrist + ARM_L3_PHASE_RAD)


def arm_tcp_m(pose):
    yaw, shoulder, elbow, wrist = pose
    yaw += ARM_YAW_PHASE_RAD
    link1_pitch = shoulder + ARM_L1_PHASE_RAD
    link2_pitch = shoulder - elbow + ARM_L2_PHASE_RAD
    tool_pitch = shoulder - elbow + wrist + ARM_L3_PHASE_RAD
    radial = (
        ARM_YAW_TO_SHOULDER_X_M
        + ARM_L1_M * math.cos(link1_pitch)
        + ARM_L2_M * math.cos(link2_pitch)
        + ARM_L3_M * math.cos(tool_pitch)
    )
    x = radial * math.cos(yaw) - ARM_YAW_TO_SHOULDER_Y_M * math.sin(yaw)
    y = radial * math.sin(yaw) + ARM_YAW_TO_SHOULDER_Y_M * math.cos(yaw)
    z = (
        ARM_YAW_TO_SHOULDER_Z_M
        + ARM_L1_M * math.sin(link1_pitch)
        + ARM_L2_M * math.sin(link2_pitch)
        + ARM_L3_M * math.sin(tool_pitch)
    )
    return (x, y, z)


def arm_to_world(point, base_pose=(0.0, 0.0, 0.0)):
    cos_yaw = math.cos(ARM_BASE_YAW_RAD)
    sin_yaw = math.sin(ARM_BASE_YAW_RAD)
    x, y, z = point
    base_x = ARM_BASE_POSITION_M[0] + x * cos_yaw - y * sin_yaw
    base_y = ARM_BASE_POSITION_M[1] + x * sin_yaw + y * cos_yaw
    base_cos_yaw = math.cos(base_pose[2])
    base_sin_yaw = math.sin(base_pose[2])
    return (
        base_pose[0] + base_x * base_cos_yaw - base_y * base_sin_yaw,
        base_pose[1] + base_x * base_sin_yaw + base_y * base_cos_yaw,
        ARM_BASE_POSITION_M[2] + z,
    )


def world_to_arm(point, base_pose=(0.0, 0.0, 0.0)):
    world_x = point[0] - base_pose[0]
    world_y = point[1] - base_pose[1]
    base_cos_yaw = math.cos(base_pose[2])
    base_sin_yaw = math.sin(base_pose[2])
    x = world_x * base_cos_yaw + world_y * base_sin_yaw - ARM_BASE_POSITION_M[0]
    y = -world_x * base_sin_yaw + world_y * base_cos_yaw - ARM_BASE_POSITION_M[1]
    z = point[2] - ARM_BASE_POSITION_M[2]
    cos_yaw = math.cos(ARM_BASE_YAW_RAD)
    sin_yaw = math.sin(ARM_BASE_YAW_RAD)
    return (
        x * cos_yaw + y * sin_yaw,
        -x * sin_yaw + y * cos_yaw,
        z,
    )


def ik_branch(target, tool_phi_rad, radial_sign, elbow_sign):
    x, y, z = (value * 1000.0 for value in target)
    offset_x = ARM_YAW_TO_SHOULDER_X_M * 1000.0
    offset_y = ARM_YAW_TO_SHOULDER_Y_M * 1000.0
    offset_z = ARM_YAW_TO_SHOULDER_Z_M * 1000.0
    link1 = ARM_L1_M * 1000.0
    link2 = ARM_L2_M * 1000.0
    link3 = ARM_L3_M * 1000.0
    radius_squared = x * x + y * y
    lateral_squared = offset_y * offset_y
    radial = radial_sign * math.sqrt(max(radius_squared - lateral_squared, 0.0))
    geometric_yaw = (
        0.0
        if radius_squared < NEAR_ZERO_XY
        else math.atan2(y, x) - math.atan2(offset_y, radial)
    )
    radial_backoff = link3 * math.cos(tool_phi_rad)
    vertical_backoff = link3 * math.sin(tool_phi_rad)
    wrist_x = radial - offset_x - radial_backoff
    wrist_z = z - offset_z - vertical_backoff
    distance_squared = wrist_x * wrist_x + wrist_z * wrist_z
    cos_delta = (
        distance_squared - link1 * link1 - link2 * link2
    ) / (2.0 * link1 * link2)
    reachable = radius_squared >= lateral_squared and -1.0 <= cos_delta <= 1.0
    cos_delta = max(-1.0, min(1.0, cos_delta))
    delta = elbow_sign * math.acos(cos_delta)
    link1_x = link1 + link2 * math.cos(delta)
    link1_z = link2 * math.sin(delta)
    link1_angle = math.atan2(wrist_z, wrist_x) - math.atan2(link1_z, link1_x)
    link2_angle = link1_angle + delta
    shoulder = link1_angle - ARM_L1_PHASE_RAD
    elbow = shoulder + ARM_L2_PHASE_RAD - link2_angle
    wrist = wrap_pi(tool_phi_rad - shoulder + elbow - ARM_L3_PHASE_RAD)
    return (
        (wrap_pi(geometric_yaw - ARM_YAW_PHASE_RAD), shoulder, elbow, wrist),
        reachable,
    )


def fit_angle_to_range(angle, minimum, maximum):
    candidates = (angle - 2.0 * math.pi, angle, angle + 2.0 * math.pi)
    return [value for value in candidates if minimum <= value <= maximum]


def solve_tcp_pose(target, tool_phi_rad, current, ranges):
    solutions = []
    for radial_sign in (1.0, -1.0):
        for elbow_sign in (1.0, -1.0):
            pose, reachable = ik_branch(target, tool_phi_rad, radial_sign, elbow_sign)
            if not reachable:
                continue
            fitted = [[]]
            for angle, (minimum, maximum) in zip(pose, ranges):
                choices = fit_angle_to_range(angle, minimum, maximum)
                fitted = [prefix + [choice] for prefix in fitted for choice in choices]
            solutions.extend(fitted)
    if not solutions:
        raise ValueError("TCP target is unreachable within calibrated joint limits")
    return min(
        solutions,
        key=lambda pose: sum(wrap_pi(value - previous) ** 2 for value, previous in zip(pose, current)),
    )


def validate_pose(model, pose):
    errors = []
    for name, value in zip(JOINT_NAMES, pose):
        joint = model.joint(name)
        minimum, maximum = joint.range
        if value < minimum or value > maximum:
            errors.append(
                f"{name}={math.degrees(value):.3f} degrees is outside "
                f"[{math.degrees(minimum):.3f}, {math.degrees(maximum):.3f}]"
            )
    if errors:
        raise ValueError("; ".join(errors))


def simulate(model, data, pose, duration, show_viewer):
    import mujoco

    mujoco.mj_resetDataKeyframe(model, data, 0)
    data.ctrl[:] = pose
    finish_time = data.time + duration
    if not show_viewer:
        while data.time < finish_time:
            mujoco.mj_step(model, data)
        return

    import mujoco.viewer

    with mujoco.viewer.launch_passive(model, data) as viewer:
        while viewer.is_running() and data.time < finish_time:
            step_started = time.monotonic()
            mujoco.mj_step(model, data)
            viewer.sync()
            remaining = model.opt.timestep - (time.monotonic() - step_started)
            if remaining > 0:
                time.sleep(remaining)


def simulation_summary(model, data, pose, mujoco_version):
    actual = [float(data.joint(name).qpos[0]) for name in JOINT_NAMES]
    base_pose = tuple(
        float(data.joint(name).qpos[0]) for name in ("base_x", "base_y", "base_yaw")
    )
    tcp_world = tuple(float(value) for value in data.site("tcp").xpos)
    analytic_tcp_world = arm_to_world(arm_tcp_m(actual), base_pose)
    tcp_error_mm = 1000.0 * math.dist(tcp_world, analytic_tcp_world)
    return {
        "mujocoVersion": mujoco_version,
        "simulationTimeSec": data.time,
        "targetJointDeg": dict(zip(JOINT_NAMES, map(math.degrees, pose))),
        "actualJointDeg": dict(zip(JOINT_NAMES, map(math.degrees, actual))),
        "basePose": {"xM": base_pose[0], "yM": base_pose[1], "yawRad": base_pose[2]},
        "tcpWorldM": tcp_world,
        "analyticTcpWorldM": analytic_tcp_world,
        "tcpAgreementMm": tcp_error_mm,
        "contacts": data.ncon,
    }


def argument_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pose-deg",
        nargs=4,
        metavar=("YAW", "SHOULDER", "ELBOW", "WRIST"),
        default=(0.0, 45.0, 135.0, 0.0),
        help="PuppyBot semantic joint targets in degrees",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=2.0,
        help="simulation duration in seconds (default: 2)",
    )
    parser.add_argument(
        "--viewer",
        action="store_true",
        help="open MuJoCo's interactive viewer and run in real time",
    )
    parser.add_argument(
        "--model",
        type=Path,
        default=Path(__file__).with_name("puppybot_arm.xml"),
        help="MJCF model to load",
    )
    return parser


def main():
    args = argument_parser().parse_args()
    if not math.isfinite(args.duration) or args.duration <= 0:
        raise SystemExit("--duration must be finite and positive")
    try:
        pose = parse_pose_degrees(args.pose_deg)
    except (ValueError, argparse.ArgumentTypeError) as error:
        raise SystemExit(f"invalid --pose-deg: {error}") from error

    try:
        import mujoco
    except ImportError as error:
        raise SystemExit(
            "MuJoCo is not installed; run: python3 -m pip install -r "
            "experiments/mujoco/requirements.txt"
        ) from error

    model = mujoco.MjModel.from_xml_path(str(args.model))
    data = mujoco.MjData(model)
    try:
        validate_pose(model, pose)
    except ValueError as error:
        raise SystemExit(str(error)) from error
    simulate(model, data, pose, args.duration, args.viewer)
    print(json.dumps(simulation_summary(model, data, pose, mujoco.__version__), indent=2))


if __name__ == "__main__":
    main()
