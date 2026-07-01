#!/usr/bin/env python3
"""Validate PuppyBot move-tcp against RobotDreams virtual servo bus telemetry."""

from __future__ import annotations

import argparse
import json
import math
import re
import time
from pathlib import Path

from place_ball_to_bin import (
    DEFAULT_SENSOR_POLL_SEC,
    PuppyBotCli,
    PuppyBotRuntime,
    RobotDreamsSession,
    discover_layout,
    print_step,
    unix_millis,
)


DEFAULT_RUNTIME_ADDR = "127.0.0.1:18094"
DEFAULT_RUNTIME_UI_ADDR = "127.0.0.1:18095"
DEFAULT_ROBOTDREAMS_BIND = "127.0.0.1:18372"
DEFAULT_ROBOTDREAMS_SOCKET = "/tmp/robotdreams-move-tcp-validation.sock"
SAFE_POSE_TICKS = ["2048", "800", "3000", "2000"]


def parse_coords(output: str) -> list[float]:
    match = re.search(r"coords_mm=([-0-9.]+),([-0-9.]+),([-0-9.]+)", output)
    if not match:
        raise RuntimeError(f"arm state did not contain coords_mm:\n{output}")
    return [float(match.group(1)), float(match.group(2)), float(match.group(3))]


def xy_distance(left: list[float], right: list[float]) -> float:
    return math.hypot(left[0] - right[0], left[1] - right[1])


def arm_coords(cli: PuppyBotCli, label: str) -> dict:
    output = cli.run(["arm", "state"])
    coords = parse_coords(output)
    print_step(f"{label} coords_mm={coords[0]:.1f},{coords[1]:.1f},{coords[2]:.1f}")
    return {"label": label, "coordsMm": coords, "output": output}


def validate_motion(samples: list[dict], delta_mm: float) -> dict:
    baseline = samples[0]["coordsMm"]
    up = samples[1]["coordsMm"]
    down = samples[2]["coordsMm"]
    up_delta_z = up[2] - baseline[2]
    down_delta_z = down[2] - up[2]
    return_delta_z = down[2] - baseline[2]
    up_xy_drift = xy_distance(baseline, up)
    return_xy_drift = xy_distance(baseline, down)
    minimum_expected_motion = max(5.0, delta_mm * 0.5)
    return_tolerance = max(15.0, delta_mm)
    xy_tolerance = max(30.0, delta_mm * 2.0)
    passed = (
        up_delta_z >= minimum_expected_motion
        and down_delta_z <= -minimum_expected_motion
        and abs(return_delta_z) <= return_tolerance
        and up_xy_drift <= xy_tolerance
        and return_xy_drift <= xy_tolerance
    )
    return {
        "schema": "puppybot.move_tcp.validation.v1",
        "status": "passed" if passed else "failed",
        "commandDeltaMm": delta_mm,
        "minimumExpectedMotionMm": minimum_expected_motion,
        "returnToleranceMm": return_tolerance,
        "xyToleranceMm": xy_tolerance,
        "deltas": {
            "upDeltaZMm": up_delta_z,
            "downDeltaZMm": down_delta_z,
            "returnDeltaZMm": return_delta_z,
            "upXyDriftMm": up_xy_drift,
            "returnXyDriftMm": return_xy_drift,
        },
        "samples": samples,
    }


def write_report(path: Path | None, report: dict) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print_step(f"wrote move-tcp validation report to {path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-addr", default=DEFAULT_RUNTIME_ADDR)
    parser.add_argument("--runtime-ui-addr", default=DEFAULT_RUNTIME_UI_ADDR)
    parser.add_argument("--robotdreams-bind", default=DEFAULT_ROBOTDREAMS_BIND)
    parser.add_argument("--robotdreams-socket", default=DEFAULT_ROBOTDREAMS_SOCKET)
    parser.add_argument("--delta-mm", type=float, default=20.0)
    parser.add_argument("--speed", type=int, default=600)
    parser.add_argument("--settle-seconds", type=float, default=2.0)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--keep-robotdreams-running", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    layout = discover_layout(Path(__file__))
    robotdreams = RobotDreamsSession(
        layout,
        socket_path=args.robotdreams_socket,
        bind=args.robotdreams_bind,
    )
    runtime: PuppyBotRuntime | None = None
    report: dict | None = None
    try:
        bus_path = robotdreams.start_virtual_bus()
        runtime = PuppyBotRuntime(
            layout,
            runtime_addr=args.runtime_addr,
            ui_addr=args.runtime_ui_addr,
            servo_device=bus_path,
        )
        runtime.start()
        cli = PuppyBotCli(layout, runtime.url)
        cli.run(["ping"])
        cli.run(["arm", "stop"])
        cli.run(["arm", "goto-ticks", "--speed", str(args.speed), *SAFE_POSE_TICKS])
        time.sleep(args.settle_seconds)
        samples = [arm_coords(cli, "baseline")]
        cli.run(["arm", "move-tcp", "--up", str(args.delta_mm), "--speed", str(args.speed)])
        time.sleep(args.settle_seconds)
        samples.append(arm_coords(cli, "after up"))
        cli.run(["arm", "move-tcp", "--down", str(args.delta_mm), "--speed", str(args.speed)])
        time.sleep(args.settle_seconds)
        samples.append(arm_coords(cli, "after down"))
        report = validate_motion(samples, args.delta_mm)
        report["robotdreams"] = {
            "socket": args.robotdreams_socket,
            "bind": args.robotdreams_bind,
            "virtualBusPath": bus_path,
        }
        report["runtime"] = {"addr": args.runtime_addr, "url": runtime.url}
        report["completedUnixMs"] = unix_millis()
        write_report(args.report, report)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report["status"] == "passed" else 1
    finally:
        if runtime is not None:
            runtime.stop()
        if not args.keep_robotdreams_running:
            robotdreams.shutdown()
        if report is None and args.report:
            write_report(
                args.report,
                {
                    "schema": "puppybot.move_tcp.validation.v1",
                    "status": "failed",
                    "completedUnixMs": unix_millis(),
                },
            )


if __name__ == "__main__":
    raise SystemExit(main())
