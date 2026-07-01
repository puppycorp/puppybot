#!/usr/bin/env python3
"""Run the PuppyBot ball-to-bin flow through RobotDreams and the Rust runtime.

This is intentionally shaped like the real robot brain process:

1. RobotDreams provides the simulated STServo bus.
2. PuppyBot Rust runtime opens that bus and exposes the robot WebSocket API.
3. This Python process opens the runtime API and a camera/perception seam.

The control policy is still scripted. Once RobotDreams exposes a virtual webcam
device, the CameraFeed class should open that device and feed frames into the
brain/perception model.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


DEFAULT_RUNTIME_ADDR = "127.0.0.1:18082"
DEFAULT_RUNTIME_UI_ADDR = "127.0.0.1:18083"
DEFAULT_ROBOTDREAMS_BIND = "127.0.0.1:18345"
DEFAULT_ROBOTDREAMS_SOCKET = "/tmp/robotdreams-place-ball-to-bin.sock"
DEFAULT_ROBOTDREAMS_PRESSURE_FILE = "/tmp/robotdreams-bin-pressure.json"
DEFAULT_COMPLETION_TIMEOUT_SEC = 10.0
DEFAULT_SENSOR_POLL_SEC = 0.1
PICKUP_TOOL_POSITION = [-0.18, 0.055, -0.34]
DROP_TOOL_POSITION = [0.38, 0.24, -0.28]
EXPECTED_PROGRESS_SEQUENCE = ["seekingBall", "grasped", "carrying", "complete"]


@dataclass(frozen=True)
class RepoLayout:
    puppybot_root: Path
    company_root: Path
    robotdreams_root: Path
    robotdreams_project: Path
    robotdreams_scenario: Path


def discover_layout(script_path: Path) -> RepoLayout:
    puppybot_root = script_path.resolve().parents[1]
    company_root = puppybot_root.parents[2]
    robotdreams_root = company_root / "projects" / "RobotDreams"
    robotdreams_project = robotdreams_root / "examples" / "puppyarm" / "project.json"
    robotdreams_scenario = puppybot_root / "scenarios" / "place_ball_to_bin.robotdreams.json"
    return RepoLayout(
        puppybot_root=puppybot_root,
        company_root=company_root,
        robotdreams_root=robotdreams_root,
        robotdreams_project=robotdreams_project,
        robotdreams_scenario=robotdreams_scenario,
    )


def print_step(message: str) -> None:
    print(f"[place_ball_to_bin] {message}", flush=True)


def unix_millis() -> int:
    return int(time.time() * 1000)


def sequence_contains_ordered(values: Sequence[str], expected: Sequence[str]) -> bool:
    expected_index = 0
    for value in values:
        if expected_index < len(expected) and value == expected[expected_index]:
            expected_index += 1
    return expected_index == len(expected)


def run_checked(
    cmd: Sequence[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    capture: bool = True,
) -> subprocess.CompletedProcess[str]:
    print_step("$ " + " ".join(cmd))
    result = subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=capture,
    )
    if result.returncode != 0:
        if result.stdout:
            print(result.stdout, end="", file=sys.stderr)
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        raise subprocess.CalledProcessError(
            result.returncode,
            result.args,
            output=result.stdout,
            stderr=result.stderr,
        )
    return result


class RecordingArtifacts:
    def __init__(self, path: Path, layout: RepoLayout, args: argparse.Namespace):
        self.path = path
        self.layout = layout
        self.args = args
        self.started_unix_ms = unix_millis()
        self.progress_events: list[dict] = []
        self.command_events: list[dict] = []
        self.sensor_events: list[dict] = []
        self.run_metadata: dict = {
            "schema": "puppybot.scenario.run.v1",
            "scenario": "place_ball_to_bin",
            "status": "running",
            "startedUnixMs": self.started_unix_ms,
            "robotdreamsProject": str(layout.robotdreams_project),
            "robotdreamsScenario": str(layout.robotdreams_scenario),
            "robotdreamsBind": args.robotdreams_bind,
            "robotdreamsSocket": args.robotdreams_socket,
            "runtimeAddr": args.runtime_addr,
            "runtimeUiAddr": args.runtime_ui_addr,
        }
        self.path.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(layout.robotdreams_scenario, self.path / "scenario.json")
        self._write_json("run.json", self.run_metadata)

    @property
    def completion_path(self) -> Path:
        return self.path / "completion.json"

    def set_runtime_context(self, bus_path: str) -> None:
        self.run_metadata["virtualBusPath"] = bus_path
        self._write_json("run.json", self.run_metadata)

    def log_progress(self, label: str, observation: dict | None, state: dict) -> None:
        event = {
            "unixMs": unix_millis(),
            "elapsedMs": unix_millis() - self.started_unix_ms,
            "label": label,
            "observation": observation,
            "progress": state.get("progress"),
            "status": state.get("status"),
            "success": state.get("success"),
            "state": state,
        }
        self.progress_events.append(event)
        self._append_jsonl("progress.jsonl", event)

    def log_command(self, args: Sequence[str], output: str) -> None:
        event = {
            "unixMs": unix_millis(),
            "elapsedMs": unix_millis() - self.started_unix_ms,
            "args": list(args),
            "ok": True,
            "stdout": output,
        }
        self.command_events.append(event)
        self._append_jsonl("robot_commands.jsonl", event)

    def log_sensor(self, event: dict) -> None:
        event = {
            "unixMs": unix_millis(),
            "elapsedMs": unix_millis() - self.started_unix_ms,
            **event,
        }
        self.sensor_events.append(event)
        self._append_jsonl("sensor.jsonl", event)

    def complete(self, completion: dict) -> None:
        self.run_metadata["status"] = "complete"
        self.run_metadata["completedUnixMs"] = completion.get("completedUnixMs", unix_millis())
        self._write_json("run.json", self.run_metadata)
        self._write_json("completion.json", completion)
        self.write_validation()

    def fail(self, reason: str) -> None:
        self.run_metadata["status"] = "failed"
        self.run_metadata["failedUnixMs"] = unix_millis()
        self.run_metadata["failureReason"] = reason
        self._write_json("run.json", self.run_metadata)
        self.write_validation(extra_failure=reason)

    def write_validation(self, extra_failure: str | None = None) -> dict:
        progress_sequence = [
            event["progress"] for event in self.progress_events if event.get("progress")
        ]
        final_progress = progress_sequence[-1] if progress_sequence else None
        final_state = self.progress_events[-1]["state"] if self.progress_events else {}
        scenario_complete = (
            final_state.get("status") == "complete"
            or final_state.get("success") is True
            or final_progress == "complete"
        )
        progress_sequence_valid = sequence_contains_ordered(
            progress_sequence,
            EXPECTED_PROGRESS_SEQUENCE,
        )
        runtime_commands_succeeded = bool(self.command_events) and all(
            event.get("ok") is True for event in self.command_events
        )
        pressure_detected = any(
            event.get("pressed") is True
            or event.get("value", {}).get("pressed") is True
            or event.get("sensorData", {}).get("value", {}).get("pressed") is True
            for event in self.sensor_events
        )

        failure_reasons = []
        if extra_failure:
            failure_reasons.append(extra_failure)
        if not scenario_complete:
            failure_reasons.append("scenario did not complete")
        if not progress_sequence_valid:
            failure_reasons.append("expected progress sequence was not observed")
        if not runtime_commands_succeeded:
            failure_reasons.append("no successful PuppyBot runtime commands were recorded")
        if not pressure_detected:
            failure_reasons.append("bin pressure was not detected")

        validation = {
            "schema": "puppybot.scenario.validation.v1",
            "scenario": "place_ball_to_bin",
            "recordingDir": str(self.path),
            "scenarioComplete": scenario_complete,
            "progressSequence": progress_sequence,
            "expectedProgressSequence": EXPECTED_PROGRESS_SEQUENCE,
            "progressSequenceValid": progress_sequence_valid,
            "runtimeCommandsSucceeded": runtime_commands_succeeded,
            "runtimeCommandCount": len(self.command_events),
            "pressureDetected": pressure_detected,
            "traceCapturedDuringRun": False,
            "videoHasMotion": False,
            "usableAsDeterministicE2ETest": (
                scenario_complete
                and progress_sequence_valid
                and runtime_commands_succeeded
                and pressure_detected
            ),
            "usableAsMotionProof": False,
            "failureReasons": failure_reasons,
            "artifacts": {
                "run": str(self.path / "run.json"),
                "scenario": str(self.path / "scenario.json"),
                "progress": str(self.path / "progress.jsonl"),
                "robotCommands": str(self.path / "robot_commands.jsonl"),
                "sensor": str(self.path / "sensor.jsonl"),
                "completion": str(self.path / "completion.json"),
            },
        }
        self._write_json("validation.json", validation)
        return validation

    def _append_jsonl(self, name: str, value: dict) -> None:
        with (self.path / name).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(value, sort_keys=True) + "\n")

    def _write_json(self, name: str, value: dict) -> None:
        (self.path / name).write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def wait_for_tcp(addr: str, timeout_seconds: float) -> None:
    host, port_text = addr.rsplit(":", 1)
    port = int(port_text)
    deadline = time.monotonic() + timeout_seconds
    last_error: OSError | None = None
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.25):
                return
        except OSError as err:
            last_error = err
            time.sleep(0.1)
    raise RuntimeError(f"timed out waiting for {addr}: {last_error}")


def parse_virtual_bus_path(output: str) -> str:
    for pattern in (
        r'"virtualBusPath"\s*:\s*"([^"]+)"',
        r"Virtual bus path:\s*(\S+)",
        r"virtual bus listening at\s*(\S+)",
    ):
        match = re.search(pattern, output)
        if match:
            return match.group(1)
    raise RuntimeError(f"could not find RobotDreams virtual bus path in:\n{output}")


class ManagedProcess:
    def __init__(self, args: Sequence[str], *, cwd: Path, env: dict[str, str] | None = None):
        print_step("$ " + " ".join(args))
        self.process = subprocess.Popen(
            args,
            cwd=cwd,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )

    def stop(self) -> None:
        if self.process.poll() is not None:
            return
        self.process.send_signal(signal.SIGINT)
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)

    def drain_output(self) -> str:
        if not self.process.stdout:
            return ""
        try:
            return self.process.stdout.read() or ""
        except ValueError:
            return ""


class RobotDreamsSession:
    def __init__(self, layout: RepoLayout, socket_path: str, bind: str):
        self.layout = layout
        self.socket_path = socket_path
        self.bind = bind

    def command(self, args: Sequence[str], *, capture: bool = True) -> subprocess.CompletedProcess[str]:
        cmd = [
            "cargo",
            "run",
            "-p",
            "robotdreams",
            "--",
            "--socket",
            self.socket_path,
            "--daemon-bind",
            self.bind,
            "--project",
            str(self.layout.robotdreams_project),
            *args,
        ]
        return run_checked(cmd, cwd=self.layout.robotdreams_root, capture=capture)

    def start_virtual_bus(self) -> str:
        result = self.command(["bus", "start"])
        output = result.stdout + result.stderr
        bus_path = parse_virtual_bus_path(output)
        print_step(f"RobotDreams virtual bus: {bus_path}")
        return bus_path

    def scenario_load(self) -> dict:
        result = self.command(
            ["scenario", "load", "--path", str(self.layout.robotdreams_scenario), "--json"]
        )
        return json.loads(result.stdout)

    def scenario_smoke(self) -> dict:
        result = self.command(
            ["scenario", "smoke", "--path", str(self.layout.robotdreams_scenario), "--json"]
        )
        return json.loads(result.stdout)

    def scenario_state(self, observation: dict | None = None) -> dict:
        args = ["scenario", "state"]
        if observation is not None:
            args.extend(["--payload", json.dumps(observation)])
        args.append("--json")
        result = self.command(args)
        return json.loads(result.stdout)

    def scenario_reset(self) -> dict:
        result = self.command(["scenario", "reset", "--json"])
        return json.loads(result.stdout)

    def export_sensor(self, out: Path, sensor: str = "bin_pressure") -> dict:
        payload = json.dumps({"out": str(out), "sensor": sensor})
        result = self.command(
            [
                "scenario",
                "export-sensors",
                "--payload",
                payload,
                "--json",
            ]
        )
        return json.loads(result.stdout)

    def shutdown(self) -> None:
        subprocess.run(
            [
                "cargo",
                "run",
                "-p",
                "robotdreams",
                "--",
                "--socket",
                self.socket_path,
                "daemon",
                "stop",
            ],
            cwd=self.layout.robotdreams_root,
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )


class PuppyBotRuntime:
    def __init__(self, layout: RepoLayout, runtime_addr: str, ui_addr: str, servo_device: str):
        self.layout = layout
        self.runtime_addr = runtime_addr
        self.ui_addr = ui_addr
        self.servo_device = servo_device
        self.process: ManagedProcess | None = None

    @property
    def url(self) -> str:
        return f"ws://{self.runtime_addr}/ws"

    def start(self) -> None:
        env = os.environ.copy()
        env["PUPPYBOT_RUNTIME_ADDR"] = self.runtime_addr
        self.process = ManagedProcess(
            [
                "./scripts/run-runtime.sh",
                "--servo-device",
                self.servo_device,
                "--ui-bind",
                self.ui_addr,
            ],
            cwd=self.layout.puppybot_root,
            env=env,
        )
        wait_for_tcp(self.runtime_addr, timeout_seconds=20)
        print_step(f"PuppyBot Rust runtime: {self.url}")

    def stop(self) -> None:
        if self.process:
            self.process.stop()
            output = self.process.drain_output()
            if output.strip():
                print(output, end="")
            self.process = None


class PuppyBotCli:
    def __init__(
        self,
        layout: RepoLayout,
        runtime_url: str,
        artifacts: RecordingArtifacts | None = None,
    ):
        self.layout = layout
        self.runtime_url = runtime_url
        self.artifacts = artifacts

    def run(self, args: Iterable[str]) -> str:
        args = list(args)
        result = run_checked(
            [
                "cargo",
                "run",
                "-p",
                "puppybot",
                "--",
                "--url",
                self.runtime_url,
                *args,
            ],
            cwd=self.layout.puppybot_root,
        )
        output = result.stdout.strip()
        if output:
            print(output)
        if self.artifacts:
            self.artifacts.log_command(args, output)
        return output


class CameraFeed:
    def __init__(self, device: str | None):
        self.device = device

    def observe(self) -> None:
        if self.device:
            print_step(f"camera feed configured: {self.device}")
        else:
            print_step("camera feed not configured; using scripted policy only")


class BinPressureSensor:
    def wait_for_ball(self, timeout_seconds: float, poll_seconds: float) -> bool:
        raise NotImplementedError


class ScriptedBinPressureSensor(BinPressureSensor):
    def __init__(self, artifacts: RecordingArtifacts | None = None):
        self.artifacts = artifacts

    def wait_for_ball(self, timeout_seconds: float, poll_seconds: float) -> bool:
        del timeout_seconds, poll_seconds
        print_step("bin pressure sensor scripted: ball detected")
        if self.artifacts:
            self.artifacts.log_sensor(
                {
                    "source": "scripted",
                    "sensor": "bin_pressure",
                    "pressed": True,
                    "pressure": 1.0,
                }
            )
        return True


class FileBinPressureSensor(BinPressureSensor):
    def __init__(
        self,
        path: Path,
        threshold: float,
        artifacts: RecordingArtifacts | None = None,
    ):
        self.path = path
        self.threshold = threshold
        self.artifacts = artifacts

    def wait_for_ball(self, timeout_seconds: float, poll_seconds: float) -> bool:
        print_step(f"waiting for bin pressure signal from {self.path}")
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            pressed, value = self._read_value()
            if pressed:
                print_step("bin pressure sensor: ball detected")
                if self.artifacts:
                    self.artifacts.log_sensor(
                        {
                            "source": "file",
                            "sensor": "bin_pressure",
                            "path": str(self.path),
                            "pressed": True,
                            "value": value,
                        }
                    )
                return True
            time.sleep(poll_seconds)
        if self.artifacts:
            self.artifacts.log_sensor(
                {
                    "source": "file",
                    "sensor": "bin_pressure",
                    "path": str(self.path),
                    "pressed": False,
                    "event": "timeout",
                }
            )
        return False

    def _is_pressed(self) -> bool:
        pressed, _value = self._read_value()
        return pressed

    def _read_value(self) -> tuple[bool, object | None]:
        try:
            raw = self.path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return False, None

        if not raw:
            return False, None

        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            value = raw

        return self._value_is_pressed(value), value

    def _value_is_pressed(self, value: object) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, int | float):
            return float(value) >= self.threshold
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "pressed", "detected", "complete"}:
                return True
            try:
                return float(normalized) >= self.threshold
            except ValueError:
                return False
        if isinstance(value, dict):
            for key in ("pressed", "detected", "ballPresent", "complete"):
                if key in value:
                    return self._value_is_pressed(value[key])
            for key in ("pressure", "weight", "value"):
                if key in value:
                    return self._value_is_pressed(value[key])
        return False


class RobotDreamsBinPressureSensor(FileBinPressureSensor):
    def __init__(
        self,
        robotdreams: RobotDreamsSession,
        path: Path,
        threshold: float,
        artifacts: RecordingArtifacts | None = None,
    ):
        super().__init__(path, threshold, artifacts)
        self.robotdreams = robotdreams

    def wait_for_ball(self, timeout_seconds: float, poll_seconds: float) -> bool:
        sensor_data = self.robotdreams.export_sensor(self.path)
        if self.artifacts:
            self.artifacts.log_sensor(
                {
                    "source": "robotdreams",
                    "sensor": "bin_pressure",
                    "path": str(self.path),
                    "sensorData": sensor_data,
                    "pressed": sensor_data.get("value", {}).get("pressed"),
                    "pressure": sensor_data.get("value", {}).get("pressure"),
                }
            )
        return super().wait_for_ball(timeout_seconds, poll_seconds)


def make_bin_pressure_sensor(
    args: argparse.Namespace,
    robotdreams: RobotDreamsSession,
    artifacts: RecordingArtifacts | None = None,
) -> BinPressureSensor:
    if args.bin_pressure_file:
        return FileBinPressureSensor(
            Path(args.bin_pressure_file),
            args.bin_pressure_threshold,
            artifacts,
        )
    return RobotDreamsBinPressureSensor(
        robotdreams,
        Path(args.robotdreams_pressure_file),
        args.bin_pressure_threshold,
        artifacts,
    )


def mark_scenario_complete(output_path: str | None) -> dict:
    result = {
        "scenario": "place_ball_to_bin",
        "status": "complete",
        "completedUnixMs": unix_millis(),
    }
    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print_step(f"wrote scenario completion marker to {path}")
    print_step("SCENARIO_COMPLETE place_ball_to_bin")
    return result


class PlaceBallToBinBrain:
    def __init__(
        self,
        cli: PuppyBotCli,
        robotdreams: RobotDreamsSession,
        camera: CameraFeed,
        bin_pressure_sensor: BinPressureSensor,
        completion_timeout_seconds: float,
        sensor_poll_seconds: float,
        completion_output: str | None,
        artifacts: RecordingArtifacts | None = None,
    ):
        self.cli = cli
        self.robotdreams = robotdreams
        self.camera = camera
        self.bin_pressure_sensor = bin_pressure_sensor
        self.completion_timeout_seconds = completion_timeout_seconds
        self.sensor_poll_seconds = sensor_poll_seconds
        self.completion_output = completion_output
        self.artifacts = artifacts

    def print_scenario_progress(self, label: str, observation: dict | None = None) -> dict:
        state = self.robotdreams.scenario_state(observation)
        print_step(
            "scenario progress after "
            f"{label}: {state.get('progress')} status={state.get('status')}"
        )
        if self.artifacts:
            self.artifacts.log_progress(label, observation, state)
        return state

    def run(self) -> None:
        self.camera.observe()
        self.cli.run(["ping"])
        self.cli.run(["config", "get"])
        self.cli.run(["arm", "state"])
        self.print_scenario_progress("initial state")

        print_step("close gripper around ball")
        self.cli.run(["arm", "set-joint-tick", "--joint", "3", "--tick", "2700", "--speed", "300"])
        self.print_scenario_progress(
            "gripper close",
            {
                "toolPosition": PICKUP_TOOL_POSITION,
                "ballPosition": PICKUP_TOOL_POSITION,
                "gripperTick": 2700,
            },
        )

        print_step("move arm toward drop zone")
        self.cli.run(["arm", "goto-ticks", "--speed", "300", "2102", "2048", "2048", "2700"])
        self.print_scenario_progress(
            "move to drop zone",
            {"toolPosition": DROP_TOOL_POSITION, "gripperTick": 2700},
        )

        print_step("release ball into bin")
        self.cli.run(["arm", "set-joint-tick", "--joint", "3", "--tick", "2000", "--speed", "300"])
        self.cli.run(["arm", "state"])
        self.print_scenario_progress(
            "release",
            {"toolPosition": DROP_TOOL_POSITION, "gripperTick": 2000},
        )

        if not self.bin_pressure_sensor.wait_for_ball(
            self.completion_timeout_seconds,
            self.sensor_poll_seconds,
        ):
            raise RuntimeError("timed out waiting for bin pressure sensor completion signal")
        final_state = self.print_scenario_progress("pressure detection")
        if final_state.get("status") != "complete":
            raise RuntimeError(f"scenario did not complete: {final_state}")
        completion = mark_scenario_complete(self.completion_output)
        if self.artifacts:
            self.artifacts.complete(completion)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--camera-device", help="Camera device/path once RobotDreams exposes one")
    parser.add_argument("--runtime-addr", default=DEFAULT_RUNTIME_ADDR)
    parser.add_argument("--runtime-ui-addr", default=DEFAULT_RUNTIME_UI_ADDR)
    parser.add_argument("--robotdreams-bind", default=DEFAULT_ROBOTDREAMS_BIND)
    parser.add_argument("--robotdreams-socket", default=DEFAULT_ROBOTDREAMS_SOCKET)
    parser.add_argument("--robotdreams-pressure-file", default=DEFAULT_ROBOTDREAMS_PRESSURE_FILE)
    parser.add_argument(
        "--bin-pressure-file",
        help=(
            "Read completion from a file written by a real or virtual bin sensor; "
            "overrides the default RobotDreams pressure export"
        ),
    )
    parser.add_argument("--bin-pressure-threshold", type=float, default=0.5)
    parser.add_argument(
        "--completion-timeout-sec",
        type=float,
        default=DEFAULT_COMPLETION_TIMEOUT_SEC,
    )
    parser.add_argument(
        "--sensor-poll-sec",
        type=float,
        default=DEFAULT_SENSOR_POLL_SEC,
    )
    parser.add_argument(
        "--completion-output",
        help="Optional JSON file to write when the scenario completes",
    )
    parser.add_argument(
        "--recording-dir",
        help=(
            "Optional directory for machine-readable run artifacts: run.json, "
            "scenario.json, progress.jsonl, robot_commands.jsonl, sensor.jsonl, "
            "completion.json, and validation.json"
        ),
    )
    parser.add_argument(
        "--skip-robotdreams-smoke",
        action="store_true",
        help="Skip the RobotDreams scenario engine smoke check",
    )
    parser.add_argument(
        "--keep-daemon",
        action="store_true",
        help="Leave the RobotDreams daemon running after the scenario",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    layout = discover_layout(Path(__file__))
    robotdreams = RobotDreamsSession(layout, args.robotdreams_socket, args.robotdreams_bind)
    runtime: PuppyBotRuntime | None = None
    artifacts = (
        RecordingArtifacts(Path(args.recording_dir), layout, args)
        if args.recording_dir
        else None
    )
    completion_output = args.completion_output
    if artifacts and completion_output is None:
        completion_output = str(artifacts.completion_path)

    try:
        bus_path = robotdreams.start_virtual_bus()
        if artifacts:
            artifacts.set_runtime_context(bus_path)
        robotdreams.scenario_load()
        robotdreams.scenario_reset()
        runtime = PuppyBotRuntime(layout, args.runtime_addr, args.runtime_ui_addr, bus_path)
        runtime.start()
        brain = PlaceBallToBinBrain(
            PuppyBotCli(layout, runtime.url, artifacts),
            robotdreams,
            CameraFeed(args.camera_device),
            make_bin_pressure_sensor(args, robotdreams, artifacts),
            args.completion_timeout_sec,
            args.sensor_poll_sec,
            completion_output,
            artifacts,
        )
        brain.run()

        if not args.skip_robotdreams_smoke:
            report = robotdreams.scenario_smoke()
            if not report.get("success"):
                raise RuntimeError(f"RobotDreams scenario smoke failed: {report}")
            print_step("RobotDreams scenario smoke passed")
    except Exception as err:
        if artifacts:
            artifacts.fail(str(err))
        raise
    finally:
        if runtime:
            runtime.stop()
        if not args.keep_daemon:
            robotdreams.shutdown()

    return 0


if __name__ == "__main__":
    sys.exit(main())
