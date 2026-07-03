#!/usr/bin/env python3
"""Validate PuppyBot move-tcp with actor artifacts and RobotDreams trace evidence."""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Iterable, Sequence

from place_ball_to_bin import PuppyBotRuntime, discover_layout


DEFAULT_RUNTIME_ADDR = "127.0.0.1:18094"
DEFAULT_RUNTIME_UI_ADDR = "127.0.0.1:18095"
EXPECTED_SERVO_IDS = [1, 2, 3, 4]
SAFE_POSE_TICKS = ["2048", "794", "3115", "1998"]
SAFE_POSE_TICK_TOLERANCE = 20


def print_step(message: str) -> None:
    print(f"[validate_move_tcp] {message}", flush=True)


def unix_millis() -> int:
    return int(time.time() * 1000)


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def append_jsonl(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, sort_keys=True) + "\n")


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_optional_json(path: Path | None) -> dict | None:
    if path is None:
        return None
    if not path.exists():
        return {"ok": False, "failureReason": f"inspect JSON does not exist: {path}"}
    try:
        return load_json(path)
    except json.JSONDecodeError as err:
        return {"ok": False, "failureReason": f"inspect JSON is invalid: {err}"}


def parse_coords(output: str) -> list[float]:
    match = re.search(r"coords_mm=([-0-9.]+),([-0-9.]+),([-0-9.]+)", output)
    if not match:
        raise RuntimeError(f"arm state did not contain coords_mm:\n{output}")
    return [float(match.group(1)), float(match.group(2)), float(match.group(3))]


def parse_limits(value: str) -> dict:
    match = re.fullmatch(r"(-?\d+)\.\.(-?\d+)(!)?", value)
    if not match:
        return {"raw": value, "limitMin": None, "limitMax": None, "limitReached": False}
    return {
        "raw": value,
        "limitMin": int(match.group(1)),
        "limitMax": int(match.group(2)),
        "limitReached": bool(match.group(3)),
    }


def parse_arm_state(output: str, label: str, started_unix_ms: int) -> dict:
    coords = parse_coords(output)
    joints = []
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) != 9 or parts[0] == "servo":
            continue
        limits = parse_limits(parts[6])
        fault = None if parts[8] == "-" else parts[8]
        joints.append(
            {
                "servoId": int(parts[0]),
                "online": parts[1] == "yes",
                "hasFeedback": parts[2] == "yes",
                "tick": int(parts[3]),
                "targetTick": None if parts[4] == "-" else int(parts[4]),
                "speed": int(parts[5]),
                "limits": limits["raw"],
                "limitMin": limits["limitMin"],
                "limitMax": limits["limitMax"],
                "limitReached": limits["limitReached"],
                "angleDeg": float(parts[7]),
                "fault": fault,
                "hasFault": fault is not None,
            }
        )

    now = unix_millis()
    return {
        "label": label,
        "unixMs": now,
        "elapsedMs": now - started_unix_ms,
        "source": "cli-arm-state",
        "coordsMm": coords,
        "joints": joints,
        "allOnline": bool(joints) and all(joint["online"] for joint in joints),
        "allHaveFeedback": bool(joints) and all(joint["hasFeedback"] for joint in joints),
        "allStopped": bool(joints)
        and all(joint["targetTick"] is None and joint["speed"] == 0 for joint in joints),
        "anyLimitReached": any(joint["limitReached"] for joint in joints),
        "anyFault": any(joint["hasFault"] for joint in joints),
        "faultNames": [joint["fault"] for joint in joints if joint["fault"]],
        "maxAbsTickError": max_abs_tick_error(joints),
        "rawOutput": output,
    }


def max_abs_tick_error(joints: list[dict]) -> int | None:
    errors = [
        abs(joint["targetTick"] - joint["tick"])
        for joint in joints
        if joint.get("targetTick") is not None
    ]
    return max(errors) if errors else None


def xy_distance(left: list[float], right: list[float]) -> float:
    return math.hypot(left[0] - right[0], left[1] - right[1])


def list_value(value: Any) -> list:
    return value if isinstance(value, list) else []


def sample_data(row: dict) -> dict:
    data = row.get("data")
    return data if isinstance(data, dict) else {}


def nested_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def servo_position(snapshot: dict, *keys: str) -> int | None:
    for key in keys:
        value = snapshot.get(key)
        if isinstance(value, int):
            return value
    return None


def collect_event_servo_ids(event: dict) -> set[int]:
    ids = set()
    for value in list_value(event.get("ids")):
        if isinstance(value, int):
            ids.add(value)
    if isinstance(event.get("id"), int):
        ids.add(event["id"])
    for write in list_value(event.get("writes")):
        if isinstance(write, dict) and isinstance(write.get("id"), int):
            ids.add(write["id"])
    return ids


def event_has_target(event: dict) -> bool:
    if isinstance(event.get("targetPosition"), int):
        return True
    for write in list_value(event.get("writes")):
        if isinstance(write, dict) and isinstance(write.get("targetPosition"), int):
            return True
    return False


def trace_has_recording_end(trace_path: Path) -> bool:
    if not trace_path.exists():
        return False
    for line in trace_path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line) if line.strip() else {}
        except json.JSONDecodeError:
            return False
        if row.get("type") == "recordingEnd":
            return True
    return False


def wait_for_trace_complete(trace_path: Path, timeout_seconds: float) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if trace_has_recording_end(trace_path):
            return
        time.sleep(0.2)


def command_event_count_in_window(events: list[dict], start_ms: int | None, end_ms: int | None) -> int:
    if start_ms is None or end_ms is None:
        return len(events)
    return sum(
        1
        for event in events
        if start_ms <= event.get("unixMs", start_ms) <= end_ms
    )


class PuppyBotCli:
    def __init__(self, layout, runtime_url: str, command_log: Path, started_unix_ms: int):
        self.layout = layout
        self.runtime_url = runtime_url
        self.command_log = command_log
        self.started_unix_ms = started_unix_ms

    def run(self, args: Sequence[str], *, label: str, step: str) -> str:
        args = list(args)
        started = unix_millis()
        cmd = [
            "cargo",
            "run",
            "-p",
            "puppybot",
            "--",
            "--url",
            self.runtime_url,
            *args,
        ]
        print_step("$ " + " ".join(cmd))
        result = subprocess.run(
            cmd,
            cwd=self.layout.puppybot_root,
            text=True,
            capture_output=True,
        )
        completed = unix_millis()
        event = {
            "label": label,
            "step": step,
            "api": "cli",
            "unixMs": started,
            "elapsedMs": started - self.started_unix_ms,
            "completedUnixMs": completed,
            "completedElapsedMs": completed - self.started_unix_ms,
            "durationMs": completed - started,
            "argv": cmd,
            "args": args,
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
        append_jsonl(self.command_log, event)
        output = result.stdout.strip()
        if output:
            print(output)
        if result.returncode != 0:
            if result.stderr:
                print(result.stderr, end="")
            raise RuntimeError(f"PuppyBot CLI command failed: {' '.join(args)}")
        return output


def arm_state(
    cli: PuppyBotCli,
    label: str,
    state_log: Path,
    started_unix_ms: int,
) -> dict:
    output = cli.run(["arm", "state"], label=label, step="telemetry")
    state = parse_arm_state(output, label, started_unix_ms)
    coords = state["coordsMm"]
    print_step(f"{label} coords_mm={coords[0]:.1f},{coords[1]:.1f},{coords[2]:.1f}")
    append_jsonl(state_log, state)
    return state


def max_target_error(state: dict, targets: Sequence[int]) -> int | None:
    joints = state.get("joints", [])
    if len(joints) != len(targets):
        return None
    return max(abs(joint["tick"] - target) for joint, target in zip(joints, targets))


def seed_safe_pose(
    cli: PuppyBotCli,
    state_log: Path,
    started_unix_ms: int,
    *,
    speed: int,
    timeout_seconds: float,
) -> dict:
    targets = [int(value) for value in SAFE_POSE_TICKS]
    deadline = time.monotonic() + timeout_seconds
    attempt = 0
    last_state: dict | None = None

    while time.monotonic() < deadline:
        attempt += 1
        cli.run(
            ["arm", "goto-ticks", "--speed", str(speed), *SAFE_POSE_TICKS],
            label=f"safe seed pose attempt {attempt}",
            step="precondition",
        )
        time.sleep(0.45)
        last_state = arm_state(
            cli,
            f"safe seed pose poll {attempt}",
            state_log,
            started_unix_ms,
        )
        target_error = max_target_error(last_state, targets)
        if (
            target_error is not None
            and target_error <= SAFE_POSE_TICK_TOLERANCE
            and last_state["allOnline"]
            and last_state["allHaveFeedback"]
            and not last_state["anyFault"]
            and not last_state["anyLimitReached"]
        ):
            cli.run(["arm", "stop"], label="settle safe seed pose", step="precondition")
            time.sleep(0.15)
            return arm_state(cli, "baseline", state_log, started_unix_ms)

    raise RuntimeError(
        "safe seed pose did not settle near requested ticks"
        + (f"; last max tick error={max_target_error(last_state, targets)}" if last_state else "")
    )


def actor_motion_evidence(samples: list[dict], delta_mm: float) -> dict:
    if len(samples) != 3:
        return {
            "ok": False,
            "failureReasons": ["PuppyBot telemetry did not include baseline/up/down samples"],
            "samples": samples,
            "deltas": {},
        }

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
    fault_samples = [
        {"label": sample["label"], "faultNames": sample["faultNames"]}
        for sample in samples
        if sample["anyFault"]
    ]
    missing_feedback_samples = [
        sample["label"]
        for sample in samples
        if not sample["allOnline"] or not sample["allHaveFeedback"]
    ]
    limit_samples = [sample["label"] for sample in samples if sample["anyLimitReached"]]
    unsettled_samples = [sample["label"] for sample in samples if not sample["allStopped"]]

    passed = (
        up_delta_z >= minimum_expected_motion
        and down_delta_z <= -minimum_expected_motion
        and abs(return_delta_z) <= return_tolerance
        and up_xy_drift <= xy_tolerance
        and return_xy_drift <= xy_tolerance
        and not fault_samples
        and not missing_feedback_samples
        and not limit_samples
        and not unsettled_samples
    )
    failure_reasons = []
    if up_delta_z < minimum_expected_motion:
        failure_reasons.append("PuppyBot telemetry did not move up far enough")
    if down_delta_z > -minimum_expected_motion:
        failure_reasons.append("PuppyBot telemetry did not move down far enough")
    if abs(return_delta_z) > return_tolerance:
        failure_reasons.append("PuppyBot telemetry did not return near baseline Z")
    if up_xy_drift > xy_tolerance or return_xy_drift > xy_tolerance:
        failure_reasons.append("PuppyBot telemetry XY drift exceeded tolerance")
    if fault_samples:
        failure_reasons.append("PuppyBot telemetry reported arm faults")
    if missing_feedback_samples:
        failure_reasons.append("PuppyBot telemetry was missing online feedback")
    if limit_samples:
        failure_reasons.append("PuppyBot telemetry reported joint limit contact")
    if unsettled_samples:
        failure_reasons.append("PuppyBot telemetry was sampled before arm motion settled")

    return {
        "ok": passed,
        "failureReasons": failure_reasons,
        "commandDeltaMm": delta_mm,
        "minimumExpectedMotionMm": minimum_expected_motion,
        "returnToleranceMm": return_tolerance,
        "xyToleranceMm": xy_tolerance,
        "faultSamples": fault_samples,
        "missingFeedbackSamples": missing_feedback_samples,
        "limitSamples": limit_samples,
        "unsettledSamples": unsettled_samples,
        "deltas": {
            "upDeltaZMm": up_delta_z,
            "downDeltaZMm": down_delta_z,
            "returnDeltaZMm": return_delta_z,
            "upXyDriftMm": up_xy_drift,
            "returnXyDriftMm": return_xy_drift,
        },
        "samples": samples,
    }


def read_command_events(command_log: Path) -> list[dict]:
    if not command_log.exists():
        return []
    return [
        json.loads(line)
        for line in command_log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def command_window(command_events: list[dict]) -> dict:
    motion_events = [
        event
        for event in command_events
        if event.get("step") == "action" and event.get("ok") is True
    ]
    if not motion_events:
        return {"startUnixMs": None, "endUnixMs": None}
    return {
        "startUnixMs": motion_events[0].get("unixMs"),
        "endUnixMs": motion_events[-1].get("completedUnixMs"),
    }


def actor_action_command_count(command_events: list[dict]) -> int:
    window = command_window(command_events)
    return command_event_count_in_window(
        command_events,
        window["startUnixMs"],
        window["endUnixMs"],
    )


def write_judge_inputs(
    path: Path,
    *,
    run_dir: Path,
    command_events: list[dict],
    actor: dict,
    args: argparse.Namespace,
) -> dict:
    window = command_window(command_events)
    value = {
        "schema": "puppycorp.arm_validation.judge_inputs.v1",
        "caseId": "move-tcp",
        "stage": "runtime_in_loop",
        "actorBoundary": "PuppyBot was driven only through the public runtime CLI/WebSocket API.",
        "commandPrimitive": "arm move-tcp",
        "expectedServoIds": EXPECTED_SERVO_IDS,
        "servoDevice": args.servo_device,
        "runtimeUrl": args.runtime_url or f"ws://{args.runtime_addr}/ws",
        "requestedMotion": {
            "frame": "base",
            "upMm": args.delta_mm,
            "downMm": args.delta_mm,
            "speed": args.speed,
        },
        "commandWindow": window,
        "tolerances": {
            "minimumExpectedMotionMm": actor.get("minimumExpectedMotionMm"),
            "returnToleranceMm": actor.get("returnToleranceMm"),
            "xyToleranceMm": actor.get("xyToleranceMm"),
        },
        "artifacts": {
            "run": str(run_dir / "run.json"),
            "actorSummary": str(run_dir / "actor_summary.json"),
            "puppybotCommands": str(run_dir / "puppybot.commands.jsonl"),
            "puppybotState": str(run_dir / "puppybot.state.jsonl"),
            "robotdreamsTrace": str(args.robotdreams_trace) if args.robotdreams_trace else None,
            "robotdreamsInspect": str(args.robotdreams_inspect) if args.robotdreams_inspect else None,
        },
    }
    write_json(path, value)
    return value


def robotdreams_trace_evidence(
    trace_path: Path | None,
    expected_bus_path: str | None,
    expected_servo_ids: Iterable[int],
) -> dict:
    if trace_path is None:
        return failed_robotdreams_evidence(["RobotDreams trace path was not provided"])
    if not trace_path.exists():
        return failed_robotdreams_evidence([f"RobotDreams trace does not exist: {trace_path}"])

    expected = set(expected_servo_ids)
    start_count = 0
    end_count = 0
    sample_count = 0
    sample_error_count = 0
    running_sample_count = 0
    bus_paths = set()
    command_events: list[dict] = []
    command_servo_ids: set[int] = set()
    command_target_servo_ids: set[int] = set()
    snapshots_by_servo: dict[int, dict[str, list[int]]] = {}
    previous_transforms: Any = None
    transform_change_count = 0

    for line_number, line in enumerate(trace_path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as err:
            return failed_robotdreams_evidence(
                [f"RobotDreams trace line {line_number} is invalid JSON: {err}"]
            )
        row_type = row.get("type")
        if row_type == "recordingStart":
            start_count += 1
            continue
        if row_type == "recordingEnd":
            end_count += 1
            continue
        if row_type == "sampleError":
            sample_error_count += 1
            continue
        if row_type != "sample":
            continue

        sample_count += 1
        data = sample_data(row)
        if data.get("status") == "running":
            running_sample_count += 1
        for path in (
            row.get("virtualBusPath"),
            data.get("virtualBusPath"),
            nested_dict(data.get("virtualBus")).get("path"),
        ):
            if isinstance(path, str) and path:
                bus_paths.add(path)

        for event in list_value(data.get("busEvents")):
            if not isinstance(event, dict):
                continue
            event_ids = collect_event_servo_ids(event)
            command_events.append(event)
            command_servo_ids.update(event_ids)
            if event_has_target(event):
                command_target_servo_ids.update(event_ids)

        for snapshot in list_value(data.get("servoSnapshots")):
            if not isinstance(snapshot, dict) or not isinstance(snapshot.get("id"), int):
                continue
            servo_id = snapshot["id"]
            servo = snapshots_by_servo.setdefault(
                servo_id,
                {"presentPositions": [], "targetPositions": []},
            )
            present = servo_position(snapshot, "presentPosition", "present_position")
            target = servo_position(snapshot, "targetPosition", "target_position")
            if present is not None:
                servo["presentPositions"].append(present)
            if target is not None:
                servo["targetPositions"].append(target)

        transforms = nested_dict(
            nested_dict(data.get("robotScene")).get("dynamicState")
        ).get("transforms")
        if transforms is not None:
            if previous_transforms is not None and transforms != previous_transforms:
                transform_change_count += 1
            previous_transforms = transforms

    servo_movement = {}
    moving_servo_ids = set()
    target_moving_servo_ids = set()
    for servo_id, values in snapshots_by_servo.items():
        present_positions = values["presentPositions"]
        target_positions = values["targetPositions"]
        present_delta = max(present_positions) - min(present_positions) if present_positions else 0
        target_delta = max(target_positions) - min(target_positions) if target_positions else 0
        if present_delta > 0:
            moving_servo_ids.add(servo_id)
        if target_delta > 0:
            target_moving_servo_ids.add(servo_id)
        servo_movement[str(servo_id)] = {
            "presentSampleCount": len(present_positions),
            "targetSampleCount": len(target_positions),
            "firstPresentPosition": present_positions[0] if present_positions else None,
            "lastPresentPosition": present_positions[-1] if present_positions else None,
            "maxPresentDelta": present_delta,
            "firstTargetPosition": target_positions[0] if target_positions else None,
            "lastTargetPosition": target_positions[-1] if target_positions else None,
            "maxTargetDelta": target_delta,
        }

    missing_servo_ids = sorted(expected - set(snapshots_by_servo.keys()))
    expected_command_ids = sorted(expected & command_servo_ids)
    expected_target_command_ids = sorted(expected & command_target_servo_ids)
    expected_present_moving_ids = sorted(expected & moving_servo_ids)
    expected_target_moving_ids = sorted(expected & target_moving_servo_ids)
    failure_reasons = []
    if start_count != 1:
        failure_reasons.append("RobotDreams trace missing single recordingStart")
    if end_count < 1:
        failure_reasons.append("RobotDreams trace missing recordingEnd")
    if sample_count == 0:
        failure_reasons.append("RobotDreams trace has no samples")
    if sample_error_count:
        failure_reasons.append("RobotDreams trace contains sampleError rows")
    if running_sample_count == 0:
        failure_reasons.append("RobotDreams trace has no running samples")
    if expected_bus_path and expected_bus_path not in bus_paths:
        failure_reasons.append("RobotDreams trace virtual bus path does not match PuppyBot bus")
    if not expected_bus_path:
        failure_reasons.append("PuppyBot servo device path was not provided for RobotDreams comparison")
    if not command_events or not expected_command_ids:
        failure_reasons.append("RobotDreams trace has no expected servo bus command events")
    if not expected_target_command_ids:
        failure_reasons.append("RobotDreams trace has no target-position writes for expected servos")
    if missing_servo_ids:
        failure_reasons.append(f"RobotDreams trace missing servo snapshots for {missing_servo_ids}")
    if not expected_present_moving_ids:
        failure_reasons.append("RobotDreams trace has no expected servo present-position movement")

    return {
        "ok": not failure_reasons,
        "failureReasons": failure_reasons,
        "trace": str(trace_path),
        "startCount": start_count,
        "endCount": end_count,
        "sampleCount": sample_count,
        "sampleErrorCount": sample_error_count,
        "runningSampleCount": running_sample_count,
        "virtualBusPaths": sorted(bus_paths),
        "commandEventCount": len(command_events),
        "commandServoIds": sorted(command_servo_ids),
        "commandTargetServoIds": sorted(command_target_servo_ids),
        "expectedCommandServoIds": expected_command_ids,
        "expectedTargetCommandServoIds": expected_target_command_ids,
        "snapshotServoIds": sorted(snapshots_by_servo.keys()),
        "missingServoIds": missing_servo_ids,
        "expectedPresentMovingServoIds": expected_present_moving_ids,
        "expectedTargetMovingServoIds": expected_target_moving_ids,
        "servoMovement": servo_movement,
        "transformChangeCount": transform_change_count,
        "transformEvidence": "present" if transform_change_count > 0 else "unavailable",
    }


def failed_robotdreams_evidence(failure_reasons: list[str]) -> dict:
    return {
        "ok": False,
        "failureReasons": failure_reasons,
        "trace": None,
        "startCount": 0,
        "endCount": 0,
        "sampleCount": 0,
        "sampleErrorCount": 0,
        "runningSampleCount": 0,
        "virtualBusPaths": [],
        "commandEventCount": 0,
        "commandServoIds": [],
        "commandTargetServoIds": [],
        "expectedCommandServoIds": [],
        "expectedTargetCommandServoIds": [],
        "snapshotServoIds": [],
        "missingServoIds": EXPECTED_SERVO_IDS,
        "expectedPresentMovingServoIds": [],
        "expectedTargetMovingServoIds": [],
        "servoMovement": {},
        "transformChangeCount": 0,
        "transformEvidence": "unavailable",
    }


def build_validation(
    *,
    actor: dict,
    robotdreams: dict,
    inspect: dict | None,
    artifacts: dict,
) -> dict:
    failure_reasons = []
    failure_reasons.extend(actor.get("failureReasons", []))
    failure_reasons.extend(robotdreams.get("failureReasons", []))
    passed = actor.get("ok") is True and robotdreams.get("ok") is True
    return {
        "schema": "puppycorp.arm_validation.validation.v1",
        "caseId": "move-tcp",
        "stage": "runtime_in_loop",
        "status": "passed" if passed else "failed",
        "pass": passed,
        "failureReasons": failure_reasons,
        "actor": actor,
        "judge": {
            "robotdreams": robotdreams,
            "inspect": inspect,
            "ignoredProofSources": ["RobotDreams scenario payload success"],
        },
        "artifacts": artifacts,
        "completedUnixMs": unix_millis(),
    }


def write_summary(path: Path, validation: dict) -> None:
    robotdreams = validation["judge"]["robotdreams"]
    summary = {
        "schema": "puppycorp.arm_validation.summary.v1",
        "caseId": validation["caseId"],
        "stage": validation["stage"],
        "status": validation["status"],
        "pass": validation["pass"],
        "failureReasons": validation["failureReasons"],
        "metrics": {
            "puppybotDeltas": validation["actor"].get("deltas", {}),
            "robotdreamsCommandEventCount": robotdreams["commandEventCount"],
            "robotdreamsExpectedPresentMovingServoIds": robotdreams[
                "expectedPresentMovingServoIds"
            ],
            "robotdreamsExpectedTargetMovingServoIds": robotdreams[
                "expectedTargetMovingServoIds"
            ],
            "robotdreamsTransformEvidence": robotdreams["transformEvidence"],
        },
        "evidencePresent": {
            "puppybotTelemetry": bool(validation["actor"].get("samples")),
            "robotdreamsTrace": robotdreams["sampleCount"] > 0,
            "robotdreamsBusCommands": robotdreams["commandEventCount"] > 0,
            "robotdreamsServoMotion": bool(robotdreams["expectedPresentMovingServoIds"]),
            "robotdreamsTransformMotion": robotdreams["transformChangeCount"] > 0,
        },
        "artifacts": validation["artifacts"],
        "nextDebugFiles": [
            validation["artifacts"]["validation"],
            validation["artifacts"]["actorSummary"],
            validation["artifacts"]["puppybotCommands"],
            validation["artifacts"]["puppybotState"],
            validation["artifacts"]["robotdreamsEvidence"],
            validation["artifacts"]["robotdreamsTrace"],
        ],
    }
    write_json(path, summary)


def default_recording_dir(args: argparse.Namespace) -> Path:
    if args.recording_dir:
        return args.recording_dir
    if args.report:
        return args.report.parent
    return Path(tempfile.gettempdir()) / f"puppybot-move-tcp-validation-{unix_millis()}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-addr", default=DEFAULT_RUNTIME_ADDR)
    parser.add_argument("--runtime-ui-addr", default=DEFAULT_RUNTIME_UI_ADDR)
    parser.add_argument("--runtime-url", help="Use an already-running PuppyBot runtime URL.")
    parser.add_argument("--servo-device", help="RobotDreams virtual STServo PTY for PuppyBot runtime.")
    parser.add_argument("--robotdreams-trace", type=Path, help="RobotDreams trace JSONL captured during this run.")
    parser.add_argument("--robotdreams-inspect", type=Path, help="Optional RobotDreams recording inspect JSON.")
    parser.add_argument("--robotdreams-trace-timeout", type=float, default=30.0)
    parser.add_argument("--delta-mm", type=float, default=20.0)
    parser.add_argument("--speed", type=int, default=300)
    parser.add_argument("--settle-seconds", type=float, default=0.8)
    parser.add_argument("--seed-timeout-seconds", type=float, default=12.0)
    parser.add_argument("--recording-dir", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--keep-runtime-running", action="store_true")
    return parser.parse_args()


def run_actor(args: argparse.Namespace, run_dir: Path, artifacts: dict) -> dict:
    layout = discover_layout(Path(__file__))
    runtime: PuppyBotRuntime | None = None
    started_unix_ms = unix_millis()
    command_log = run_dir / "puppybot.commands.jsonl"
    state_log = run_dir / "puppybot.state.jsonl"
    runtime_url = args.runtime_url
    run_metadata = {
        "schema": "puppycorp.arm_validation.run.v1",
        "caseId": "move-tcp",
        "stage": "runtime_in_loop",
        "status": "running",
        "startedUnixMs": started_unix_ms,
        "recordingDir": str(run_dir),
        "runtimeAddr": args.runtime_addr,
        "runtimeUiAddr": args.runtime_ui_addr,
        "runtimeUrl": runtime_url or f"ws://{args.runtime_addr}/ws",
        "servoDevice": args.servo_device,
        "nonCheatingBoundary": {
            "puppybotControl": "public CLI/WebSocket/runtime APIs only",
            "robotdreamsUse": "external PTY/trace evidence only; no scenario payload success accepted",
        },
        "artifacts": artifacts,
    }
    write_json(run_dir / "run.json", run_metadata)
    try:
        if runtime_url is None:
            if not args.servo_device:
                raise RuntimeError("--servo-device is required when --runtime-url is not supplied")
            runtime = PuppyBotRuntime(
                layout,
                runtime_addr=args.runtime_addr,
                ui_addr=args.runtime_ui_addr,
                servo_device=args.servo_device,
            )
            runtime.start()
            runtime_url = runtime.url
            run_metadata["runtimeUrl"] = runtime_url
            write_json(run_dir / "run.json", run_metadata)

        cli = PuppyBotCli(layout, runtime_url, command_log, started_unix_ms)
        cli.run(["ping"], label="ping", step="precondition")
        cli.run(["arm", "clear-faults"], label="clear faults", step="precondition")
        cli.run(["arm", "stop"], label="stop", step="precondition")
        samples = [
            seed_safe_pose(
                cli,
                state_log,
                started_unix_ms,
                speed=args.speed,
                timeout_seconds=args.seed_timeout_seconds,
            )
        ]
        cli.run(
            [
                "arm",
                "move-tcp",
                "--frame",
                "base",
                "--up",
                str(args.delta_mm),
                "--speed",
                str(args.speed),
            ],
            label="move tcp up",
            step="action",
        )
        time.sleep(args.settle_seconds)
        samples.append(arm_state(cli, "after up", state_log, started_unix_ms))
        cli.run(
            [
                "arm",
                "move-tcp",
                "--frame",
                "base",
                "--down",
                str(args.delta_mm),
                "--speed",
                str(args.speed),
            ],
            label="move tcp down",
            step="action",
        )
        time.sleep(args.settle_seconds)
        samples.append(arm_state(cli, "after down", state_log, started_unix_ms))
        actor = actor_motion_evidence(samples, args.delta_mm)
        actor["schema"] = "puppycorp.arm_validation.actor_summary.v1"
        actor["caseId"] = "move-tcp"
        actor["stage"] = "runtime_in_loop"
        actor["status"] = "completed" if actor["ok"] else "failed"
        actor["completedUnixMs"] = unix_millis()
        write_json(run_dir / "actor_summary.json", actor)
        run_metadata["status"] = actor["status"]
        run_metadata["actorCompletedUnixMs"] = actor["completedUnixMs"]
        write_json(run_dir / "run.json", run_metadata)
        return actor
    except Exception as err:
        actor = {
            "schema": "puppycorp.arm_validation.actor_summary.v1",
            "caseId": "move-tcp",
            "stage": "runtime_in_loop",
            "status": "failed",
            "ok": False,
            "failureReasons": [str(err)],
            "samples": [],
            "deltas": {},
            "completedUnixMs": unix_millis(),
        }
        write_json(run_dir / "actor_summary.json", actor)
        run_metadata["status"] = "failed"
        run_metadata["failureReason"] = str(err)
        run_metadata["actorCompletedUnixMs"] = actor["completedUnixMs"]
        write_json(run_dir / "run.json", run_metadata)
        return actor
    finally:
        if runtime is not None and not args.keep_runtime_running:
            runtime.stop()


def main() -> int:
    args = parse_args()
    run_dir = default_recording_dir(args)
    run_dir.mkdir(parents=True, exist_ok=True)
    validation_path = args.report or (run_dir / "validation.json")
    artifacts = {
        "run": str(run_dir / "run.json"),
        "summary": str(run_dir / "summary.json"),
        "validation": str(validation_path),
        "actorSummary": str(run_dir / "actor_summary.json"),
        "judgeInputs": str(run_dir / "judge_inputs.json"),
        "puppybotCommands": str(run_dir / "puppybot.commands.jsonl"),
        "puppybotState": str(run_dir / "puppybot.state.jsonl"),
        "robotdreamsTrace": str(args.robotdreams_trace) if args.robotdreams_trace else None,
        "robotdreamsInspect": str(args.robotdreams_inspect) if args.robotdreams_inspect else None,
        "robotdreamsEvidence": str(run_dir / "robotdreams_evidence.json"),
    }

    actor = run_actor(args, run_dir, artifacts)
    command_events = read_command_events(run_dir / "puppybot.commands.jsonl")
    write_judge_inputs(
        run_dir / "judge_inputs.json",
        run_dir=run_dir,
        command_events=command_events,
        actor=actor,
        args=args,
    )

    if args.robotdreams_trace:
        wait_for_trace_complete(args.robotdreams_trace, args.robotdreams_trace_timeout)
    robotdreams = robotdreams_trace_evidence(
        args.robotdreams_trace,
        args.servo_device,
        EXPECTED_SERVO_IDS,
    )
    robotdreams["actorActionCommandCount"] = actor_action_command_count(command_events)
    write_json(run_dir / "robotdreams_evidence.json", robotdreams)
    inspect = load_optional_json(args.robotdreams_inspect)
    validation = build_validation(
        actor=actor,
        robotdreams=robotdreams,
        inspect=inspect,
        artifacts=artifacts,
    )
    write_json(validation_path, validation)
    write_summary(run_dir / "summary.json", validation)
    print(json.dumps(validation, indent=2, sort_keys=True))
    return 0 if validation["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
