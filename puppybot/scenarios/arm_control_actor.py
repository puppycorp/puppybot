#!/usr/bin/env python3
"""Drive PuppyBot arm public APIs and record simulator-validation actor artifacts."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from place_ball_to_bin import PuppyBotRuntime, discover_layout


DEFAULT_RUNTIME_ADDR = "127.0.0.1:18104"
DEFAULT_RUNTIME_UI_ADDR = "127.0.0.1:18105"
EXPECTED_SERVO_IDS = [1, 2, 3, 4]
SAFE_POSE_TICKS = [2048, 794, 3115, 1998]
CASE_CHOICES = [
    "all",
    "goto-ticks",
    "goto-angles",
    "goto-coords",
    "move-tcp",
    "stop-hold-jog",
]


def print_step(message: str) -> None:
    print(f"[arm_control_actor] {message}", flush=True)


def unix_millis() -> int:
    return int(time.time() * 1000)


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def append_jsonl(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, sort_keys=True) + "\n")


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


def parse_coords(output: str) -> list[float] | None:
    match = re.search(r"coords_mm=([-0-9.]+),([-0-9.]+),([-0-9.]+)", output)
    if not match:
        return None
    return [float(match.group(1)), float(match.group(2)), float(match.group(3))]


def max_abs_tick_error(joints: list[dict]) -> int | None:
    errors = [
        abs(joint["targetTick"] - joint["tick"])
        for joint in joints
        if joint.get("targetTick") is not None
    ]
    return max(errors) if errors else None


def parse_arm_state(output: str, label: str, case_id: str, started_unix_ms: int) -> dict:
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
        "caseId": case_id,
        "label": label,
        "unixMs": now,
        "elapsedMs": now - started_unix_ms,
        "source": "cli-arm-state",
        "coordsMm": parse_coords(output),
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


def state_failure_reasons(state: dict) -> list[str]:
    reasons = []
    if not state.get("joints"):
        reasons.append("PuppyBot arm state did not include joint telemetry")
    if not state.get("allOnline"):
        reasons.append("not all joints were online")
    if not state.get("allHaveFeedback"):
        reasons.append("not all joints had feedback")
    if state.get("anyFault"):
        reasons.append("PuppyBot telemetry reported arm faults")
    if state.get("anyLimitReached"):
        reasons.append("PuppyBot telemetry reported joint limit contact")
    return reasons


def target_ticks_from_state(state: dict, offsets: Sequence[int]) -> list[int]:
    ticks = []
    for joint, offset in zip(state["joints"], offsets):
        target = joint["tick"] + offset
        limit_min = joint.get("limitMin")
        limit_max = joint.get("limitMax")
        if isinstance(limit_min, int) and isinstance(limit_max, int):
            target = max(limit_min + 15, min(limit_max - 15, target))
        ticks.append(target)
    return ticks


@dataclass
class CaseResult:
    case_id: str
    status: str
    failure_reasons: list[str]
    warnings: list[str]
    command_labels: list[str]
    sample_labels: list[str]
    expected: dict

    @property
    def ok(self) -> bool:
        return not self.failure_reasons

    def to_json(self) -> dict:
        return {
            "caseId": self.case_id,
            "status": self.status,
            "ok": self.ok,
            "failureReasons": self.failure_reasons,
            "warnings": self.warnings,
            "commandLabels": self.command_labels,
            "sampleLabels": self.sample_labels,
            "expected": self.expected,
        }


class PuppyBotCli:
    def __init__(self, layout, runtime_url: str, command_log: Path, started_unix_ms: int):
        self.layout = layout
        self.runtime_url = runtime_url
        self.command_log = command_log
        self.started_unix_ms = started_unix_ms

    def run(self, args: Sequence[str], *, label: str, case_id: str, step: str) -> str:
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
            "schema": "puppycorp.arm_validation.command.v1",
            "caseId": case_id,
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


class Actor:
    def __init__(self, args: argparse.Namespace, run_dir: Path, runtime_url: str, started_unix_ms: int):
        self.args = args
        self.run_dir = run_dir
        self.started_unix_ms = started_unix_ms
        self.command_log = run_dir / "puppybot.commands.jsonl"
        self.state_log = run_dir / "puppybot.state.jsonl"
        self.cli = PuppyBotCli(discover_layout(Path(__file__)), runtime_url, self.command_log, started_unix_ms)

    def command(self, case_id: str, label: str, step: str, args: Sequence[str]) -> str:
        return self.cli.run(args, label=label, case_id=case_id, step=step)

    def state(self, case_id: str, label: str) -> dict:
        output = self.command(case_id, label, "telemetry", ["arm", "state"])
        state = parse_arm_state(output, label, case_id, self.started_unix_ms)
        append_jsonl(self.state_log, state)
        coords = state.get("coordsMm")
        if coords:
            print_step(f"{case_id}:{label} coords_mm={coords[0]:.1f},{coords[1]:.1f},{coords[2]:.1f}")
        return state

    def precondition(self, case_id: str) -> dict:
        self.command(case_id, "ping", "precondition", ["ping"])
        self.command(case_id, "clear faults", "precondition", ["arm", "clear-faults"])
        self.command(case_id, "stop", "precondition", ["arm", "stop"])
        ticks = [str(value) for value in SAFE_POSE_TICKS]
        self.command(
            case_id,
            "seed safe pose",
            "precondition",
            ["arm", "goto-ticks", "--speed", str(self.args.speed), *ticks],
        )
        time.sleep(self.args.settle_seconds)
        return self.state(case_id, "baseline")

    def settle_state(self, case_id: str, label: str) -> dict:
        time.sleep(self.args.settle_seconds)
        return self.state(case_id, label)

    def run_goto_ticks(self) -> CaseResult:
        case_id = "goto-ticks"
        baseline = self.precondition(case_id)
        target = target_ticks_from_state(baseline, [40, 25, -35, 30])
        self.command(
            case_id,
            "goto ticks target",
            "action",
            ["arm", "goto-ticks", "--speed", str(self.args.speed), *[str(value) for value in target]],
        )
        final = self.settle_state(case_id, "after goto ticks")
        return self.case_result(
            case_id,
            [baseline, final],
            ["ping", "clear faults", "stop", "seed safe pose", "goto ticks target"],
            {"commandPrimitive": "arm goto-ticks", "targetTicks": target, "speed": self.args.speed},
        )

    def run_goto_angles(self) -> CaseResult:
        case_id = "goto-angles"
        baseline = self.precondition(case_id)
        baseline_angles = [joint["angleDeg"] for joint in baseline["joints"]]
        target = [
            baseline_angles[0] + 4.0,
            baseline_angles[1] - 3.0,
            baseline_angles[2] + 3.0,
            baseline_angles[3] - 4.0,
        ]
        self.command(
            case_id,
            "goto angles target",
            "action",
            ["arm", "goto-angles", "--speed", str(self.args.speed), *[f"{value:.3f}" for value in target]],
        )
        final = self.settle_state(case_id, "after goto angles")
        return self.case_result(
            case_id,
            [baseline, final],
            ["ping", "clear faults", "stop", "seed safe pose", "goto angles target"],
            {"commandPrimitive": "arm goto-angles", "targetAnglesDeg": target, "speed": self.args.speed},
        )

    def run_goto_coords(self) -> CaseResult:
        case_id = "goto-coords"
        baseline = self.precondition(case_id)
        coords = baseline.get("coordsMm")
        if not coords:
            return CaseResult(
                case_id,
                "telemetryUnavailable",
                ["baseline PuppyBot telemetry did not include coordsMm"],
                [],
                ["ping", "clear faults", "stop", "seed safe pose"],
                ["baseline"],
                {"commandPrimitive": "arm goto-coords"},
            )
        target = [coords[0], coords[1], coords[2] + self.args.coords_delta_mm]
        self.command(
            case_id,
            "goto coords target",
            "action",
            [
                "arm",
                "goto-coords",
                "--speed",
                str(self.args.speed),
                "--",
                f"{target[0]:.3f}",
                f"{target[1]:.3f}",
                f"{target[2]:.3f}",
            ],
        )
        final = self.settle_state(case_id, "after goto coords")
        return self.case_result(
            case_id,
            [baseline, final],
            ["ping", "clear faults", "stop", "seed safe pose", "goto coords target"],
            {"commandPrimitive": "arm goto-coords", "targetCoordsMm": target, "speed": self.args.speed},
        )

    def run_move_tcp(self) -> CaseResult:
        case_id = "move-tcp"
        samples = [self.precondition(case_id)]
        command_labels = ["ping", "clear faults", "stop", "seed safe pose"]
        distance = self.args.move_tcp_mm
        moves = [
            ("base up", ["--frame", "base", "--up", str(distance)]),
            ("base down", ["--frame", "base", "--down", str(distance)]),
            ("base left", ["--frame", "base", "--left", str(distance)]),
            ("base right", ["--frame", "base", "--right", str(distance)]),
            ("base forward", ["--frame", "base", "--forward", str(distance)]),
            ("base back", ["--frame", "base", "--back", str(distance)]),
            ("tool forward", ["--frame", "tool", "--forward", str(distance)]),
            ("tool back", ["--frame", "tool", "--back", str(distance)]),
            ("tool up", ["--frame", "tool", "--up", str(distance)]),
            ("tool down", ["--frame", "tool", "--down", str(distance)]),
        ]
        for label, move_args in moves:
            self.command(
                case_id,
                label,
                "action",
                ["arm", "move-tcp", *move_args, "--speed", str(self.args.speed)],
            )
            command_labels.append(label)
            samples.append(self.settle_state(case_id, f"after {label}"))
        return self.case_result(
            case_id,
            samples,
            command_labels,
            {
                "commandPrimitive": "arm move-tcp",
                "directions": [label for label, _ in moves],
                "distanceMm": distance,
                "speed": self.args.speed,
            },
        )

    def run_stop_hold_jog(self) -> CaseResult:
        case_id = "stop-hold-jog"
        samples = [self.precondition(case_id)]
        self.command(case_id, "hold", "action", ["arm", "hold", "--speed", str(self.args.speed)])
        samples.append(self.settle_state(case_id, "after hold"))
        self.command(
            case_id,
            "jog joint 0 positive",
            "action",
            [
                "arm",
                "jog",
                "--joint",
                "0",
                "--direction",
                "1",
                "--speed",
                str(self.args.jog_speed),
                "--duration-ms",
                str(self.args.jog_duration_ms),
            ],
        )
        samples.append(self.settle_state(case_id, "after timed jog"))
        self.command(case_id, "stop all", "action", ["arm", "stop"])
        samples.append(self.settle_state(case_id, "after stop all"))
        return self.case_result(
            case_id,
            samples,
            ["ping", "clear faults", "stop", "seed safe pose", "hold", "jog joint 0 positive", "stop all"],
            {
                "commandPrimitives": ["arm hold", "arm jog", "arm stop"],
                "jog": {"joint": 0, "direction": 1, "speed": self.args.jog_speed, "durationMs": self.args.jog_duration_ms},
                "holdSpeed": self.args.speed,
            },
        )

    def case_result(
        self,
        case_id: str,
        samples: list[dict],
        command_labels: list[str],
        expected: dict,
    ) -> CaseResult:
        failure_reasons = []
        warnings = []
        for sample in samples:
            reasons = state_failure_reasons(sample)
            if reasons:
                failure_reasons.extend(f"{sample['label']}: {reason}" for reason in reasons)
            if sample.get("coordsMm") is None:
                warnings.append(f"{sample['label']}: coordsMm unavailable")
        return CaseResult(
            case_id=case_id,
            status="completed" if not failure_reasons else "faultObserved",
            failure_reasons=failure_reasons,
            warnings=warnings,
            command_labels=command_labels,
            sample_labels=[sample["label"] for sample in samples],
            expected=expected,
        )


def selected_cases(case_args: Sequence[str]) -> list[str]:
    cases = list(case_args)
    if not cases or "all" in cases:
        return ["goto-ticks", "goto-angles", "goto-coords", "move-tcp", "stop-hold-jog"]
    return cases


def default_recording_dir(args: argparse.Namespace) -> Path:
    if args.recording_dir:
        return args.recording_dir
    return Path(tempfile.gettempdir()) / f"puppybot-arm-control-actor-{unix_millis()}"


def build_judge_inputs(run_dir: Path, args: argparse.Namespace, cases: list[CaseResult]) -> dict:
    return {
        "schema": "puppycorp.arm_validation.judge_inputs.v1",
        "suiteId": "arm-control-public-api",
        "stage": "runtime_in_loop",
        "actorBoundary": "PuppyBot was driven only through the public runtime CLI/WebSocket API.",
        "expectedServoIds": EXPECTED_SERVO_IDS,
        "servoDevice": args.servo_device,
        "runtimeUrl": args.runtime_url or f"ws://{args.runtime_addr}/ws",
        "caseInputs": [case.to_json() for case in cases],
        "judgeRequirements": {
            "mustUseIndependentSimulatorEvidence": True,
            "requiredEvidence": [
                "RobotDreams virtual-bus events after each PuppyBot command window",
                "RobotDreams servo snapshots for expected servo IDs",
                "RobotDreams-derived transform or equivalent motion evidence where available",
                "No PuppyBot-side faults, limit contact, or missing feedback in actor telemetry",
            ],
            "ignoredProofSources": ["PuppyBot command success alone", "scripted scenario payload success"],
        },
        "artifacts": {
            "run": str(run_dir / "run.json"),
            "actorSummary": str(run_dir / "actor_summary.json"),
            "puppybotCommands": str(run_dir / "puppybot.commands.jsonl"),
            "puppybotState": str(run_dir / "puppybot.state.jsonl"),
            "judgeInputs": str(run_dir / "judge_inputs.json"),
        },
    }


def build_actor_summary(cases: list[CaseResult], started_unix_ms: int) -> dict:
    failure_reasons = []
    for case in cases:
        failure_reasons.extend(f"{case.case_id}: {reason}" for reason in case.failure_reasons)
    if not failure_reasons:
        status = "completed"
    elif any(case.status == "commandRejected" for case in cases):
        status = "commandRejected"
    elif any(case.status == "telemetryUnavailable" for case in cases):
        status = "telemetryUnavailable"
    else:
        status = "faultObserved"
    completed = unix_millis()
    return {
        "schema": "puppycorp.arm_validation.actor_summary.v1",
        "suiteId": "arm-control-public-api",
        "stage": "runtime_in_loop",
        "status": status,
        "ok": not failure_reasons,
        "failureReasons": failure_reasons,
        "caseCount": len(cases),
        "cases": [case.to_json() for case in cases],
        "startedUnixMs": started_unix_ms,
        "completedUnixMs": completed,
        "durationMs": completed - started_unix_ms,
        "validationPass": None,
        "validationNote": "Actor summary is not an independent simulator pass/fail verdict.",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", action="append", choices=CASE_CHOICES)
    parser.add_argument("--runtime-addr", default=DEFAULT_RUNTIME_ADDR)
    parser.add_argument("--runtime-ui-addr", default=DEFAULT_RUNTIME_UI_ADDR)
    parser.add_argument("--runtime-url", help="Use an already-running PuppyBot runtime URL.")
    parser.add_argument("--servo-device", help="RobotDreams virtual STServo PTY for PuppyBot runtime.")
    parser.add_argument("--speed", type=int, default=300)
    parser.add_argument("--jog-speed", type=int, default=180)
    parser.add_argument("--jog-duration-ms", type=int, default=350)
    parser.add_argument("--coords-delta-mm", type=float, default=15.0)
    parser.add_argument("--move-tcp-mm", type=float, default=10.0)
    parser.add_argument("--settle-seconds", type=float, default=0.8)
    parser.add_argument("--recording-dir", type=Path)
    parser.add_argument("--keep-runtime-running", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_dir = default_recording_dir(args)
    run_dir.mkdir(parents=True, exist_ok=True)
    started_unix_ms = unix_millis()
    layout = discover_layout(Path(__file__))
    runtime: PuppyBotRuntime | None = None
    runtime_url = args.runtime_url
    cases_to_run = selected_cases(args.case)
    run_metadata = {
        "schema": "puppycorp.arm_validation.run.v1",
        "suiteId": "arm-control-public-api",
        "stage": "runtime_in_loop",
        "status": "running",
        "caseIds": cases_to_run,
        "startedUnixMs": started_unix_ms,
        "recordingDir": str(run_dir),
        "runtimeAddr": args.runtime_addr,
        "runtimeUiAddr": args.runtime_ui_addr,
        "runtimeUrl": runtime_url or f"ws://{args.runtime_addr}/ws",
        "servoDevice": args.servo_device,
        "nonCheatingBoundary": {
            "puppybotControl": "public CLI/WebSocket/runtime APIs only",
            "robotdreamsUse": "external PTY/trace/judge evidence only",
        },
        "artifacts": {
            "actorSummary": str(run_dir / "actor_summary.json"),
            "judgeInputs": str(run_dir / "judge_inputs.json"),
            "puppybotCommands": str(run_dir / "puppybot.commands.jsonl"),
            "puppybotState": str(run_dir / "puppybot.state.jsonl"),
        },
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

        actor = Actor(args, run_dir, runtime_url, started_unix_ms)
        runners = {
            "goto-ticks": actor.run_goto_ticks,
            "goto-angles": actor.run_goto_angles,
            "goto-coords": actor.run_goto_coords,
            "move-tcp": actor.run_move_tcp,
            "stop-hold-jog": actor.run_stop_hold_jog,
        }
        case_results = []
        for case_id in cases_to_run:
            try:
                case_results.append(runners[case_id]())
            except Exception as err:
                case_results.append(
                    CaseResult(
                        case_id=case_id,
                        status="commandRejected",
                        failure_reasons=[str(err)],
                        warnings=[],
                        command_labels=[],
                        sample_labels=[],
                        expected={"caseAborted": True},
                    )
                )
        summary = build_actor_summary(case_results, started_unix_ms)
        write_json(run_dir / "actor_summary.json", summary)
        write_json(run_dir / "judge_inputs.json", build_judge_inputs(run_dir, args, case_results))
        run_metadata["status"] = summary["status"]
        run_metadata["completedUnixMs"] = summary["completedUnixMs"]
        write_json(run_dir / "run.json", run_metadata)
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0 if summary["ok"] else 2
    except Exception as err:
        summary = {
            "schema": "puppycorp.arm_validation.actor_summary.v1",
            "suiteId": "arm-control-public-api",
            "stage": "runtime_in_loop",
            "status": "failedToStart",
            "ok": False,
            "failureReasons": [str(err)],
            "caseCount": 0,
            "cases": [],
            "startedUnixMs": started_unix_ms,
            "completedUnixMs": unix_millis(),
            "validationPass": None,
            "validationNote": "Actor summary is not an independent simulator pass/fail verdict.",
        }
        write_json(run_dir / "actor_summary.json", summary)
        write_json(run_dir / "judge_inputs.json", build_judge_inputs(run_dir, args, []))
        run_metadata["status"] = "failedToStart"
        run_metadata["failureReason"] = str(err)
        run_metadata["completedUnixMs"] = summary["completedUnixMs"]
        write_json(run_dir / "run.json", run_metadata)
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 1
    finally:
        if runtime is not None and not args.keep_runtime_running:
            runtime.stop()


if __name__ == "__main__":
    raise SystemExit(main())
