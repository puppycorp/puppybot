#!/usr/bin/env python3
"""Validate PuppyBot arm control surfaces against RobotDreams simulator evidence."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Sequence

from place_ball_to_bin import PuppyBotRuntime, discover_layout
from validate_move_tcp import (
    DEFAULT_RUNTIME_ADDR,
    DEFAULT_RUNTIME_UI_ADDR,
    EXPECTED_SERVO_IDS,
    SAFE_POSE_TICKS,
    PuppyBotCli,
    arm_state,
    failed_robotdreams_evidence,
    max_target_error,
    read_command_events,
    robotdreams_trace_evidence,
    unix_millis,
    wait_for_trace_complete,
    write_json,
)


STAGE = "runtime_in_loop"
SAFE_POSE_TOLERANCE_TICKS = 20
TICK_TOLERANCE = 25
ANGLE_TOLERANCE_DEG = 5.0
COORD_TOLERANCE_MM = 35.0
RETURN_TOLERANCE_MM = 25.0
MIN_MOTION_MM = 8.0
SPEED = 300

TICKS_HIGH_Z = ["2048", "892", "3357", "2154"]
ANGLES_HIGH_Z_DEG = ["0.0", "58.18", "18.28", "32.61"]
COORD_TARGET = [-200.0, 0.0, 135.0]
MIN_COORD_MOTION_MM = 30.0
UNREACHABLE_COORD = [1000.0, 0.0, 0.0]


def print_step(message: str) -> None:
    print(f"[validate_arm_sim_suite] {message}", flush=True)


def default_recording_dir(args: argparse.Namespace) -> Path:
    if args.recording_dir:
        return args.recording_dir
    if args.report:
        return args.report.parent
    return Path(tempfile.gettempdir()) / f"puppybot-arm-sim-suite-{unix_millis()}"


def state_health_failures(state: dict) -> list[str]:
    failures = []
    if not state["allOnline"] or not state["allHaveFeedback"]:
        failures.append(f"{state['label']} missing online feedback")
    if state["anyFault"]:
        failures.append(f"{state['label']} reported arm faults")
    if state["anyLimitReached"]:
        failures.append(f"{state['label']} reported joint limit contact")
    if not state["allStopped"]:
        failures.append(f"{state['label']} was sampled before arm motion settled")
    return failures


def tick_error(state: dict, targets: Sequence[int]) -> int | None:
    return max_target_error(state, targets)


def angle_error(state: dict, targets: Sequence[float]) -> float | None:
    joints = state.get("joints", [])
    if len(joints) != len(targets):
        return None
    return max(abs(joint["angleDeg"] - target) for joint, target in zip(joints, targets))


def coord_error(state: dict, target: Sequence[float]) -> float:
    coords = state["coordsMm"]
    return math.sqrt(sum((coords[index] - target[index]) ** 2 for index in range(3)))


def coord_distance(left: dict, right: dict) -> float:
    return coord_error(left, right["coordsMm"])


def axis_delta(start: dict, end: dict, axis: int) -> float:
    return end["coordsMm"][axis] - start["coordsMm"][axis]


def write_case(run_dir: Path, case: dict) -> None:
    write_json(run_dir / "cases" / f"{case['caseId']}.json", case)


def case_result(
    run_dir: Path,
    *,
    case_id: str,
    primitive: str,
    samples: list[dict],
    metrics: dict,
    failure_reasons: list[str],
) -> dict:
    case = {
        "schema": "puppycorp.arm_validation.case.v1",
        "caseId": case_id,
        "stage": STAGE,
        "primitive": primitive,
        "status": "passed" if not failure_reasons else "failed",
        "ok": not failure_reasons,
        "failureReasons": failure_reasons,
        "metrics": metrics,
        "samples": samples,
        "completedUnixMs": unix_millis(),
    }
    write_case(run_dir, case)
    return case


class ArmSuiteActor:
    def __init__(
        self,
        cli: PuppyBotCli,
        run_dir: Path,
        *,
        speed: int,
        settle_seconds: float,
        seed_timeout_seconds: float,
        started_unix_ms: int,
    ) -> None:
        self.cli = cli
        self.run_dir = run_dir
        self.speed = speed
        self.settle_seconds = settle_seconds
        self.seed_timeout_seconds = seed_timeout_seconds
        self.started_unix_ms = started_unix_ms
        self.state_log = run_dir / "puppybot.state.jsonl"

    def sample(self, label: str) -> dict:
        return arm_state(self.cli, label, self.state_log, self.started_unix_ms)

    def wait_stopped(self, label: str, timeout_seconds: float = 3.0) -> dict:
        deadline = time.monotonic() + timeout_seconds
        last_state: dict | None = None
        while time.monotonic() < deadline:
            last_state = self.sample(label)
            if (
                last_state["allOnline"]
                and last_state["allHaveFeedback"]
                and not last_state["anyFault"]
                and not last_state["anyLimitReached"]
                and last_state["allStopped"]
            ):
                return last_state
            time.sleep(0.25)
        if last_state is not None:
            return last_state
        raise RuntimeError(f"{label} did not produce arm telemetry")

    def settle_ticks(
        self,
        *,
        case_id: str,
        label: str,
        ticks: Sequence[str],
        tolerance: int,
        step: str,
        timeout_seconds: float | None = None,
    ) -> dict:
        targets = [int(value) for value in ticks]
        deadline = time.monotonic() + (timeout_seconds or self.seed_timeout_seconds)
        attempt = 0
        last_state: dict | None = None

        while time.monotonic() < deadline:
            attempt += 1
            self.cli.run(
                ["arm", "goto-ticks", "--speed", str(self.speed), *ticks],
                label=f"{case_id}: {label} attempt {attempt}",
                step=step,
            )
            time.sleep(0.45)
            last_state = self.sample(f"{case_id}: {label} poll {attempt}")
            error = tick_error(last_state, targets)
            if (
                error is not None
                and error <= tolerance
                and last_state["allOnline"]
                and last_state["allHaveFeedback"]
                and not last_state["anyFault"]
                and not last_state["anyLimitReached"]
            ):
                self.cli.run(["arm", "stop"], label=f"{case_id}: stop after {label}", step=step)
                time.sleep(0.15)
                return self.sample(f"{case_id}: {label} settled")

        raise RuntimeError(
            f"{case_id}: {label} did not settle"
            + (f"; last max tick error={tick_error(last_state, targets)}" if last_state else "")
        )

    def settle_coords(
        self,
        *,
        case_id: str,
        label: str,
        coords: Sequence[float],
        tolerance: float,
        step: str,
        timeout_seconds: float | None = None,
    ) -> dict:
        deadline = time.monotonic() + (timeout_seconds or self.seed_timeout_seconds)
        attempt = 0
        last_state: dict | None = None

        while time.monotonic() < deadline:
            attempt += 1
            self.cli.run(
                [
                    "arm",
                    "goto-coords",
                    "--speed",
                    str(self.speed),
                    "--",
                    *(str(value) for value in coords),
                ],
                label=f"{case_id}: {label} attempt {attempt}",
                step=step,
            )
            time.sleep(0.45)
            last_state = self.sample(f"{case_id}: {label} poll {attempt}")
            error = coord_error(last_state, coords)
            if (
                error <= tolerance
                and last_state["allOnline"]
                and last_state["allHaveFeedback"]
                and not last_state["anyFault"]
                and not last_state["anyLimitReached"]
            ):
                self.cli.run(["arm", "stop"], label=f"{case_id}: stop after {label}", step=step)
                time.sleep(0.15)
                return self.sample(f"{case_id}: {label} settled")

        raise RuntimeError(
            f"{case_id}: {label} did not settle"
            + (f"; last coordinate error={coord_error(last_state, coords):.1f} mm" if last_state else "")
        )

    def seed_safe_pose(self, case_id: str) -> dict:
        return self.settle_ticks(
            case_id=case_id,
            label="safe seed pose",
            ticks=SAFE_POSE_TICKS,
            tolerance=SAFE_POSE_TOLERANCE_TICKS,
            step="precondition",
        )

    def run_goto_ticks_case(self) -> dict:
        case_id = "goto-ticks"
        sample = self.settle_ticks(
            case_id=case_id,
            label="target ticks",
            ticks=TICKS_HIGH_Z,
            tolerance=TICK_TOLERANCE,
            step="action",
        )
        targets = [int(value) for value in TICKS_HIGH_Z]
        error = tick_error(sample, targets)
        failures = state_health_failures(sample)
        if error is None or error > TICK_TOLERANCE:
            failures.append("goto-ticks did not reach target tick tolerance")
        self.seed_safe_pose(case_id)
        return case_result(
            self.run_dir,
            case_id=case_id,
            primitive="arm goto-ticks",
            samples=[sample],
            metrics={"maxTickError": error, "targetTicks": targets},
            failure_reasons=failures,
        )

    def run_goto_angles_case(self) -> dict:
        case_id = "goto-angles"
        self.seed_safe_pose(case_id)
        self.cli.run(
            ["arm", "goto-angles", "--speed", str(self.speed), *ANGLES_HIGH_Z_DEG],
            label=f"{case_id}: target angles",
            step="action",
        )
        time.sleep(self.settle_seconds)
        sample = self.wait_stopped(f"{case_id}: after target angles")
        targets = [float(value) for value in ANGLES_HIGH_Z_DEG]
        error = angle_error(sample, targets)
        failures = state_health_failures(sample)
        if error is None or error > ANGLE_TOLERANCE_DEG:
            failures.append("goto-angles did not reach target angle tolerance")
        self.seed_safe_pose(case_id)
        return case_result(
            self.run_dir,
            case_id=case_id,
            primitive="arm goto-angles",
            samples=[sample],
            metrics={"maxAngleErrorDeg": error, "targetAnglesDeg": targets},
            failure_reasons=failures,
        )

    def run_goto_coords_case(self) -> dict:
        case_id = "goto-coords"
        start = self.seed_safe_pose(case_id)
        start_error = coord_error(start, COORD_TARGET)
        sample = self.settle_coords(
            case_id=case_id,
            label="target coords",
            coords=COORD_TARGET,
            tolerance=COORD_TOLERANCE_MM,
            step="action",
        )
        error = coord_error(sample, COORD_TARGET)
        movement = coord_distance(sample, start)
        target_distance_reduction = start_error - error
        failures = state_health_failures(sample)
        if error > COORD_TOLERANCE_MM:
            failures.append("goto-coords did not reach coordinate tolerance")
        if movement < MIN_COORD_MOTION_MM:
            failures.append("goto-coords did not move far enough from baseline")
        if target_distance_reduction < MIN_COORD_MOTION_MM:
            failures.append("goto-coords did not converge toward the requested target")
        self.seed_safe_pose(case_id)
        return case_result(
            self.run_dir,
            case_id=case_id,
            primitive="arm goto-coords",
            samples=[start, sample],
            metrics={
                "coordErrorMm": error,
                "movementMm": movement,
                "startCoordErrorMm": start_error,
                "targetCoordsMm": COORD_TARGET,
                "targetDistanceReductionMm": target_distance_reduction,
            },
            failure_reasons=failures,
        )

    def run_move_tcp_axis_case(
        self,
        *,
        case_id: str,
        first_arg: str,
        second_arg: str,
        axis: int,
        expected_sign: int,
        delta_mm: float,
    ) -> dict:
        start = self.seed_safe_pose(case_id)
        self.cli.run(
            [
                "arm",
                "move-tcp",
                "--frame",
                "base",
                first_arg,
                str(delta_mm),
                "--speed",
                str(self.speed),
            ],
            label=f"{case_id}: first move",
            step="action",
        )
        time.sleep(self.settle_seconds)
        moved = self.wait_stopped(f"{case_id}: after first move")
        self.cli.run(
            [
                "arm",
                "move-tcp",
                "--frame",
                "base",
                second_arg,
                str(delta_mm),
                "--speed",
                str(self.speed),
            ],
            label=f"{case_id}: return move",
            step="action",
        )
        time.sleep(self.settle_seconds)
        returned = self.wait_stopped(f"{case_id}: after return move")

        movement = axis_delta(start, moved, axis)
        return_error = coord_distance(returned, start)
        failures = []
        for sample in [start, moved, returned]:
            failures.extend(state_health_failures(sample))
        if movement * expected_sign < MIN_MOTION_MM:
            failures.append("move-tcp did not move far enough along expected axis")
        if return_error > RETURN_TOLERANCE_MM:
            failures.append("move-tcp did not return near start pose")
        return case_result(
            self.run_dir,
            case_id=case_id,
            primitive="arm move-tcp",
            samples=[start, moved, returned],
            metrics={
                "axis": axis,
                "axisDeltaMm": movement,
                "returnErrorMm": return_error,
                "requestedDeltaMm": delta_mm,
            },
            failure_reasons=failures,
        )

    def run_unreachable_coords_case(self) -> dict:
        case_id = "unreachable-goto-coords"
        start = self.seed_safe_pose(case_id)
        self.cli.run(
            [
                "arm",
                "goto-coords",
                "--speed",
                str(self.speed),
                "--",
                *(str(value) for value in UNREACHABLE_COORD),
            ],
            label=f"{case_id}: unreachable target",
            step="action",
        )
        time.sleep(0.3)
        after = self.sample(f"{case_id}: after unreachable target")
        drift = coord_distance(after, start)
        failures = state_health_failures(after)
        if drift > 5.0:
            failures.append("unreachable goto-coords changed arm pose")
        return case_result(
            self.run_dir,
            case_id=case_id,
            primitive="arm goto-coords",
            samples=[start, after],
            metrics={"poseDriftMm": drift, "targetCoordsMm": UNREACHABLE_COORD},
            failure_reasons=failures,
        )

    def run_cases(self, selected_cases: Sequence[str]) -> list[dict]:
        available = {
            "goto-ticks": self.run_goto_ticks_case,
            "goto-angles": self.run_goto_angles_case,
            "goto-coords": self.run_goto_coords_case,
            "move-tcp-z": lambda: self.run_move_tcp_axis_case(
                case_id="move-tcp-z",
                first_arg="--up",
                second_arg="--down",
                axis=2,
                expected_sign=1,
                delta_mm=20.0,
            ),
            "move-tcp-x": lambda: self.run_move_tcp_axis_case(
                case_id="move-tcp-x",
                first_arg="--back",
                second_arg="--forward",
                axis=0,
                expected_sign=1,
                delta_mm=20.0,
            ),
            "move-tcp-y": lambda: self.run_move_tcp_axis_case(
                case_id="move-tcp-y",
                first_arg="--left",
                second_arg="--right",
                axis=1,
                expected_sign=1,
                delta_mm=20.0,
            ),
            "unreachable-goto-coords": self.run_unreachable_coords_case,
        }

        cases = []
        for case_id in selected_cases:
            if case_id not in available:
                raise RuntimeError(f"unknown case: {case_id}")
            print_step(f"run case {case_id}")
            try:
                cases.append(available[case_id]())
            except Exception as err:
                case = case_result(
                    self.run_dir,
                    case_id=case_id,
                    primitive="unknown",
                    samples=[],
                    metrics={},
                    failure_reasons=[str(err)],
                )
                cases.append(case)
                break
        return cases


def run_actor(args: argparse.Namespace, run_dir: Path, artifacts: dict) -> dict:
    layout = discover_layout(Path(__file__))
    runtime: PuppyBotRuntime | None = None
    started_unix_ms = unix_millis()
    command_log = run_dir / "puppybot.commands.jsonl"
    runtime_url = args.runtime_url
    run_metadata = {
        "schema": "puppycorp.arm_validation.run.v1",
        "suiteId": "arm-sim-suite",
        "stage": STAGE,
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
        cli.run(["ping"], label="suite: ping", step="precondition")
        cli.run(["arm", "clear-faults"], label="suite: clear faults", step="precondition")
        cli.run(["arm", "stop"], label="suite: stop", step="precondition")
        actor = ArmSuiteActor(
            cli,
            run_dir,
            speed=args.speed,
            settle_seconds=args.settle_seconds,
            seed_timeout_seconds=args.seed_timeout_seconds,
            started_unix_ms=started_unix_ms,
        )
        cases = actor.run_cases(args.cases)
        failure_reasons = [
            f"{case['caseId']}: {reason}"
            for case in cases
            for reason in case.get("failureReasons", [])
        ]
        summary = {
            "schema": "puppycorp.arm_validation.actor_summary.v1",
            "suiteId": "arm-sim-suite",
            "stage": STAGE,
            "status": "completed" if not failure_reasons else "failed",
            "ok": not failure_reasons,
            "failureReasons": failure_reasons,
            "caseCount": len(cases),
            "passedCaseIds": [case["caseId"] for case in cases if case["ok"]],
            "failedCaseIds": [case["caseId"] for case in cases if not case["ok"]],
            "cases": cases,
            "completedUnixMs": unix_millis(),
        }
        write_json(run_dir / "actor_summary.json", summary)
        run_metadata["status"] = summary["status"]
        run_metadata["actorCompletedUnixMs"] = summary["completedUnixMs"]
        write_json(run_dir / "run.json", run_metadata)
        return summary
    except Exception as err:
        summary = {
            "schema": "puppycorp.arm_validation.actor_summary.v1",
            "suiteId": "arm-sim-suite",
            "stage": STAGE,
            "status": "failed",
            "ok": False,
            "failureReasons": [str(err)],
            "caseCount": 0,
            "passedCaseIds": [],
            "failedCaseIds": [],
            "cases": [],
            "completedUnixMs": unix_millis(),
        }
        write_json(run_dir / "actor_summary.json", summary)
        run_metadata["status"] = "failed"
        run_metadata["failureReason"] = str(err)
        run_metadata["actorCompletedUnixMs"] = summary["completedUnixMs"]
        write_json(run_dir / "run.json", run_metadata)
        return summary
    finally:
        if runtime is not None and not args.keep_runtime_running:
            runtime.stop()


def run_robotdreams_assert(args: argparse.Namespace, run_dir: Path) -> dict:
    output_path = run_dir / "robotdreams-assert.json"
    if args.robotdreams_trace is None:
        result = {"ok": False, "failureReasons": ["RobotDreams trace path was not provided"]}
        write_json(output_path, result)
        return result
    if args.robotdreams_ready is None:
        result = {"ok": False, "failureReasons": ["RobotDreams ready file was not provided"]}
        write_json(output_path, result)
        return result

    layout = discover_layout(Path(__file__))
    cmd = [
        "cargo",
        "run",
        "-p",
        "robotdreams",
        "--",
        "recording",
        "assert",
        "--trace",
        str(args.robotdreams_trace),
        "--ready",
        str(args.robotdreams_ready),
        "--expect-servo-moved",
        "2,3,4",
        "--expect-target-write",
        "1,2,3,4",
        "--allow-servo-id",
        "1,2,3,4",
        "--require-transform-change",
        "--json",
    ]
    completed = subprocess.run(
        cmd,
        cwd=layout.robotdreams_root,
        text=True,
        capture_output=True,
    )
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError:
        result = {
            "ok": False,
            "failureReasons": ["RobotDreams recording assert did not emit valid JSON"],
        }
    result["command"] = cmd
    result["returncode"] = completed.returncode
    result["stdout"] = completed.stdout
    result["stderr"] = completed.stderr
    if completed.returncode != 0:
        result["ok"] = False
        if not result.get("failureReasons"):
            failed_cases = [
                case.get("name", "unknown")
                for case in result.get("cases", [])
                if case.get("ok") is False
            ]
            if failed_cases:
                result["failureReasons"] = [
                    f"RobotDreams recording assert failed cases: {', '.join(failed_cases)}"
                ]
            else:
                result["failureReasons"] = ["RobotDreams recording assert exited nonzero"]
    write_json(output_path, result)
    return result


def build_validation(actor: dict, robotdreams: dict, robotdreams_assert: dict, artifacts: dict) -> dict:
    failure_reasons = []
    failure_reasons.extend(actor.get("failureReasons", []))
    failure_reasons.extend(robotdreams.get("failureReasons", []))
    failure_reasons.extend(robotdreams_assert.get("failureReasons", []))
    passed = (
        actor.get("ok") is True
        and robotdreams.get("ok") is True
        and robotdreams_assert.get("ok") is True
    )
    return {
        "schema": "puppycorp.arm_validation.validation.v1",
        "suiteId": "arm-sim-suite",
        "stage": STAGE,
        "status": "passed" if passed else "failed",
        "pass": passed,
        "failureReasons": failure_reasons,
        "actor": actor,
        "judge": {
            "robotdreams": robotdreams,
            "robotdreamsAssert": robotdreams_assert,
            "ignoredProofSources": ["RobotDreams scenario payload success"],
        },
        "artifacts": artifacts,
        "completedUnixMs": unix_millis(),
    }


def write_summary(path: Path, validation: dict) -> None:
    robotdreams = validation["judge"]["robotdreams"]
    robotdreams_assert = validation["judge"]["robotdreamsAssert"]
    actor = validation["actor"]
    summary = {
        "schema": "puppycorp.arm_validation.summary.v1",
        "suiteId": "arm-sim-suite",
        "stage": validation["stage"],
        "status": validation["status"],
        "pass": validation["pass"],
        "failureReasons": validation["failureReasons"],
        "metrics": {
            "caseCount": actor.get("caseCount", 0),
            "passedCaseIds": actor.get("passedCaseIds", []),
            "failedCaseIds": actor.get("failedCaseIds", []),
            "robotdreamsCommandEventCount": robotdreams["commandEventCount"],
            "robotdreamsExpectedTargetCommandServoIds": robotdreams[
                "expectedTargetCommandServoIds"
            ],
            "robotdreamsExpectedPresentMovingServoIds": robotdreams[
                "expectedPresentMovingServoIds"
            ],
            "robotdreamsSampleErrorCount": robotdreams["sampleErrorCount"],
            "robotdreamsTransformEvidence": robotdreams["transformEvidence"],
            "robotdreamsAssertOk": robotdreams_assert.get("ok"),
        },
        "evidencePresent": {
            "puppybotTelemetry": actor.get("caseCount", 0) > 0,
            "robotdreamsTrace": robotdreams["sampleCount"] > 0,
            "robotdreamsBusTargetWrites": bool(robotdreams["expectedTargetCommandServoIds"]),
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
            validation["artifacts"]["robotdreamsAssert"],
            validation["artifacts"]["robotdreamsTrace"],
        ],
    }
    write_json(path, summary)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-addr", default=DEFAULT_RUNTIME_ADDR)
    parser.add_argument("--runtime-ui-addr", default=DEFAULT_RUNTIME_UI_ADDR)
    parser.add_argument("--runtime-url", help="Use an already-running PuppyBot runtime URL.")
    parser.add_argument("--servo-device", help="RobotDreams virtual STServo PTY for PuppyBot runtime.")
    parser.add_argument("--robotdreams-trace", type=Path, help="RobotDreams trace JSONL captured during this run.")
    parser.add_argument("--robotdreams-ready", type=Path, help="RobotDreams ready JSON captured during this run.")
    parser.add_argument("--robotdreams-trace-timeout", type=float, default=30.0)
    parser.add_argument("--recording-dir", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--keep-runtime-running", action="store_true")
    parser.add_argument("--speed", type=int, default=SPEED)
    parser.add_argument("--settle-seconds", type=float, default=0.8)
    parser.add_argument("--seed-timeout-seconds", type=float, default=12.0)
    parser.add_argument(
        "--cases",
        nargs="+",
        default=[
            "goto-ticks",
            "goto-angles",
            "goto-coords",
            "move-tcp-z",
            "move-tcp-x",
            "move-tcp-y",
            "unreachable-goto-coords",
        ],
    )
    return parser.parse_args()


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
        "puppybotCommands": str(run_dir / "puppybot.commands.jsonl"),
        "puppybotState": str(run_dir / "puppybot.state.jsonl"),
        "robotdreamsTrace": str(args.robotdreams_trace) if args.robotdreams_trace else None,
        "robotdreamsReady": str(args.robotdreams_ready) if args.robotdreams_ready else None,
        "robotdreamsEvidence": str(run_dir / "robotdreams_evidence.json"),
        "robotdreamsAssert": str(run_dir / "robotdreams-assert.json"),
    }
    actor = run_actor(args, run_dir, artifacts)
    command_events = read_command_events(run_dir / "puppybot.commands.jsonl")

    if args.robotdreams_trace:
        wait_for_trace_complete(args.robotdreams_trace, args.robotdreams_trace_timeout)
        robotdreams = robotdreams_trace_evidence(
            args.robotdreams_trace,
            args.servo_device,
            EXPECTED_SERVO_IDS,
        )
    else:
        robotdreams = failed_robotdreams_evidence(["RobotDreams trace path was not provided"])
    robotdreams["actorCommandCount"] = len(command_events)
    write_json(run_dir / "robotdreams_evidence.json", robotdreams)

    robotdreams_assert = run_robotdreams_assert(args, run_dir)
    validation = build_validation(actor, robotdreams, robotdreams_assert, artifacts)
    write_json(validation_path, validation)
    write_summary(run_dir / "summary.json", validation)
    print(json.dumps(validation, indent=2, sort_keys=True))
    return 0 if validation["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
