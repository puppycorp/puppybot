#!/usr/bin/env python3
"""Run and record the deterministic in-process RobotDreams ball-to-bin demo."""

from __future__ import annotations

import argparse
import json
import math
import os
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_UI_ADDR = "127.0.0.1:18083"
DEFAULT_WS_ADDR = "127.0.0.1:18082"
DEFAULT_CAPTURE_FRAMES = 380
WAYPOINT_TOLERANCE_MM = 7.0
WAYPOINT_TIMEOUT_SEC = 15.0
VISUAL_AUDIT_WIDTH = 240
VISUAL_AUDIT_HEIGHT = 135
VISUAL_AUDIT_NEAR_BLACK_MAX = 8
VISUAL_AUDIT_MAX_NEAR_BLACK_FRACTION = 0.05
VISUAL_AUDIT_MIN_MEAN_CHANNEL = 25.0
VISUAL_AUDIT_MAX_ADJACENT_MEAN_DELTA = 15.0
TCP_VISUAL_AUDIT_MIN_MEAN_CHANNEL = 10.0
TCP_VISUAL_AUDIT_MAX_ADJACENT_MEAN_DELTA = 35.0
WAYPOINTS = {
    "pre_pick": [230.0, -90.0, 80.0],
    "pick": [230.0, -90.0, -34.0],
    "lift": [230.0, -90.0, 130.0],
    "transfer": [190.0, 0.0, 180.0],
    "drop": [130.0, 70.0, 240.0],
    "retreat": [180.0, 0.0, 160.0],
}


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def append_jsonl(path: Path, value: Any) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, sort_keys=True) + "\n")


def distance_mm(left: list[float], right: list[float]) -> float:
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right, strict=True)))


class RuntimeApi:
    def __init__(self, base_url: str, command_log: Path, state_log: Path):
        self.base_url = base_url.rstrip("/")
        self.command_log = command_log
        self.state_log = state_log

    def request(self, method: str, path: str, body: dict | None = None) -> tuple[Any, bytes]:
        encoded = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + path,
            data=encoded,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        started = time.time_ns() // 1_000_000
        try:
            with urllib.request.urlopen(request, timeout=5.0) as response:
                raw = response.read()
                content_type = response.headers.get("Content-Type", "")
                value = json.loads(raw) if "json" in content_type else None
                status = response.status
        except urllib.error.HTTPError as error:
            raw = error.read()
            try:
                value = json.loads(raw)
            except json.JSONDecodeError:
                value = {"error": raw.decode("utf-8", errors="replace")}
            append_jsonl(
                self.command_log,
                {"unixMs": started, "method": method, "path": path, "body": body,
                 "status": error.code, "response": value},
            )
            raise RuntimeError(f"{method} {path} failed ({error.code}): {value}") from error
        append_jsonl(
            self.command_log,
            {"unixMs": started, "method": method, "path": path, "body": body,
             "status": status, "response": value},
        )
        return value, raw

    def state(self, label: str) -> dict:
        value, _ = self.request("GET", "/api/state")
        if not isinstance(value, dict):
            raise RuntimeError("runtime state was not a JSON object")
        append_jsonl(self.state_log, {"unixMs": time.time_ns() // 1_000_000,
                                      "label": label, "state": value})
        return value

    def post(self, path: str, body: dict | None = None) -> dict:
        value, _ = self.request("POST", path, body or {})
        if not isinstance(value, dict):
            raise RuntimeError(f"{path} response was not a JSON object")
        return value

    def move(self, name: str) -> dict:
        x, y, z = WAYPOINTS[name]
        command = {"xMm": x, "yMm": y, "zMm": z, "toolPhiDeg": -90.0}
        self.post("/api/arm/coordinates/move", command)
        deadline = time.monotonic() + WAYPOINT_TIMEOUT_SEC
        next_refresh = time.monotonic() + 0.5
        while time.monotonic() < deadline:
            state = self.state(f"move:{name}")
            current = state.get("arm", {}).get("currentTcpMm")
            if isinstance(current, list) and len(current) == 3:
                error = distance_mm([float(value) for value in current], WAYPOINTS[name])
                if error <= WAYPOINT_TOLERANCE_MM:
                    return state
            if time.monotonic() >= next_refresh:
                # The physical controller deadman requires a continuing intent
                # during long multi-joint moves. Reposting the same immutable
                # waypoint refreshes that intent without changing the plan.
                self.post("/api/arm/coordinates/move", command)
                next_refresh = time.monotonic() + 0.5
            time.sleep(0.05)
        raise RuntimeError(f"waypoint {name} did not settle within {WAYPOINT_TIMEOUT_SEC:.1f}s")


def wait_ready(api: RuntimeApi, process: subprocess.Popen, timeout_sec: float = 60.0) -> dict:
    deadline = time.monotonic() + timeout_sec
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"runtime exited during startup with code {process.returncode}")
        try:
            return api.state("runtime-ready")
        except (OSError, RuntimeError) as error:
            last_error = error
            time.sleep(0.1)
    raise RuntimeError(f"runtime did not become ready: {last_error}")


def wait_capture(api: RuntimeApi, status_path: str, timeout_sec: float = 120.0) -> dict:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        response, _ = api.request("GET", status_path)
        status = response.get("job", {})
        if status.get("status") == "complete":
            return status
        if status.get("status") == "failed":
            raise RuntimeError(f"capture failed: {status.get('error')}")
        time.sleep(0.2)
    raise RuntimeError("capture did not become ready")


def download(api: RuntimeApi, path: str, output: Path) -> None:
    _, raw = api.request("GET", path)
    output.write_bytes(raw)


def manipulation(state: dict) -> dict:
    value = state.get("sim", {}).get("manipulation")
    if not isinstance(value, dict):
        raise RuntimeError("runtime did not publish sim.manipulation")
    return value


def trace_proof(trace_path: Path, capture_camera: str) -> dict:
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    frames = trace.get("frames")
    if not isinstance(frames, list) or not frames:
        raise RuntimeError("capture trace contains no frames")
    samples: list[dict] = []
    cameras: list[dict] = []
    transforms_present = True
    transform_matches_state = True
    for index, sample in enumerate(frames):
        camera = sample.get("camera")
        if not isinstance(camera, dict):
            raise RuntimeError(f"capture frame {index} has no camera state")
        cameras.append(camera)
        frame = sample.get("frame", {})
        state = frame.get("manipulation")
        if not isinstance(state, dict):
            raise RuntimeError(f"capture frame {index} has no simulator manipulation state")
        ball = state.get("ball", {})
        center = ball.get("centerWorldM")
        transform = frame.get("visualTransforms", {}).get("object:ball")
        if not isinstance(transform, dict):
            transforms_present = False
        else:
            translation = transform.get("translation")
            if not (isinstance(center, list) and isinstance(translation, list)):
                transform_matches_state = False
            elif distance_mm([float(value) * 1000.0 for value in center],
                             [float(value) * 1000.0 for value in translation]) > 0.2:
                transform_matches_state = False
        samples.append({"index": index, "state": state, "ball": ball})

    attached_indexes = [sample["index"] for sample in samples if sample["ball"].get("attached") is True]
    if not attached_indexes:
        raise RuntimeError("capture trace never observed the attached ball")
    first_attached = attached_indexes[0]
    first_center = samples[first_attached]["ball"].get("centerWorldM")
    carry_distance_m = max(
        math.dist(first_center, samples[index]["ball"].get("centerWorldM"))
        for index in attached_indexes
    )
    release_indexes = [
        sample["index"] for sample in samples[first_attached + 1:]
        if sample["ball"].get("attached") is False
        and sample["ball"].get("motion") == "dynamic"
        and sample["state"].get("lastAction", {}).get("result") == "released"
    ]
    if not release_indexes:
        raise RuntimeError("capture trace never observed simulator-owned dynamic release")
    released = release_indexes[0]
    release_z = float(samples[released]["ball"]["centerWorldM"][2])
    post_release_z = [
        float(sample["ball"]["centerWorldM"][2])
        for sample in samples[released + 1:]
    ]
    downward_motion_m = release_z - min(post_release_z, default=release_z)
    triggered_indexes = [
        sample["index"] for sample in samples[released + 1:]
        if sample["state"].get("binTrigger", {}).get("triggered") is True
    ]
    action_sequences = {
        sample["state"].get("lastAction", {}).get("sequence")
        for sample in samples
        if isinstance(sample["state"].get("lastAction"), dict)
    }
    expected_camera_source = "wrist_camera" if capture_camera == "tcp" else "external"
    camera_sources = {camera.get("source") for camera in cameras}
    camera_positions = [camera.get("eyeM") for camera in cameras]
    if any(not isinstance(position, list) or len(position) != 3 for position in camera_positions):
        raise RuntimeError("capture trace contains an invalid camera position")
    camera_motion_m = max(
        math.dist(camera_positions[0], position) for position in camera_positions
    )
    camera_pov_proof = {
        "requested": capture_camera,
        "expectedSource": expected_camera_source,
        "sources": sorted(str(source) for source in camera_sources),
        "resolution": cameras[0].get("resolution"),
        "fovDeg": cameras[0].get("fovDeg"),
        "motionM": camera_motion_m,
    }
    camera_pov_proof["success"] = (
        camera_sources == {expected_camera_source}
        and all(camera.get("resolution") == cameras[0].get("resolution") for camera in cameras)
        and (capture_camera != "tcp" or (
            cameras[0].get("resolution") == [640, 480]
            and abs(float(cameras[0].get("fovDeg", 0.0)) - 70.0) <= 1.0e-5
            and camera_motion_m >= 0.05
        ))
    )
    proof = {
        "frameCount": len(samples),
        "firstAttachedFrame": first_attached,
        "firstReleasedDynamicFrame": released,
        "firstTriggeredFrame": triggered_indexes[0] if triggered_indexes else None,
        "carryDistanceM": carry_distance_m,
        "downwardMotionM": downward_motion_m,
        "ballTransformPresentEveryFrame": transforms_present,
        "ballTransformMatchesManipulationState": transform_matches_state,
        "interactActionSequences": sorted(value for value in action_sequences if isinstance(value, int)),
        "cameraPov": camera_pov_proof,
    }
    proof["success"] = (
        carry_distance_m >= 0.10
        and downward_motion_m >= 0.03
        and bool(triggered_indexes)
        and transforms_present
        and transform_matches_state
        and {1, 2}.issubset(action_sequences)
        and camera_pov_proof["success"]
    )
    if not proof["success"]:
        raise RuntimeError(f"capture trace proof failed: {proof}")
    return proof


def decoded_frame_quality(
    raw_path: Path,
    expected_frames: int,
    audit_resolution: list[int],
    minimum_mean_channel: float,
    maximum_adjacent_mean_delta: float,
) -> dict:
    audit_width, audit_height = audit_resolution
    pixels_per_frame = audit_width * audit_height
    bytes_per_frame = pixels_per_frame * 3
    byte_count = raw_path.stat().st_size
    decoded_frames, trailing_bytes = divmod(byte_count, bytes_per_frame)
    means: list[float] = []
    near_black_fractions: list[float] = []
    incomplete_frames: list[int] = []
    with raw_path.open("rb") as raw:
        for frame_index in range(decoded_frames):
            frame = raw.read(bytes_per_frame)
            mean_channel = sum(frame) / bytes_per_frame
            near_black_pixels = sum(
                1
                for red, green, blue in zip(frame[0::3], frame[1::3], frame[2::3], strict=True)
                if red <= VISUAL_AUDIT_NEAR_BLACK_MAX
                and green <= VISUAL_AUDIT_NEAR_BLACK_MAX
                and blue <= VISUAL_AUDIT_NEAR_BLACK_MAX
            )
            near_black_fraction = near_black_pixels / pixels_per_frame
            means.append(mean_channel)
            near_black_fractions.append(near_black_fraction)
            if (
                mean_channel < minimum_mean_channel
                or near_black_fraction > VISUAL_AUDIT_MAX_NEAR_BLACK_FRACTION
            ):
                incomplete_frames.append(frame_index)
    adjacent_deltas = [
        abs(current - previous)
        for previous, current in zip(means, means[1:])
    ]
    abrupt_frames = [
        frame_index
        for frame_index, delta in enumerate(adjacent_deltas, start=1)
        if delta > maximum_adjacent_mean_delta
    ]
    proof = {
        "auditResolution": audit_resolution,
        "expectedFrameCount": expected_frames,
        "decodedFrameCount": decoded_frames,
        "decodedByteCount": byte_count,
        "trailingBytes": trailing_bytes,
        "nearBlackChannelMaximum": VISUAL_AUDIT_NEAR_BLACK_MAX,
        "maximumAllowedNearBlackFraction": VISUAL_AUDIT_MAX_NEAR_BLACK_FRACTION,
        "minimumAllowedMeanChannel": minimum_mean_channel,
        "maximumAllowedAdjacentMeanDelta": maximum_adjacent_mean_delta,
        "minimumMeanChannel": min(means) if means else None,
        "maximumMeanChannel": max(means) if means else None,
        "maximumNearBlackFraction": max(near_black_fractions)
        if near_black_fractions
        else None,
        "maximumAdjacentMeanDelta": max(adjacent_deltas) if adjacent_deltas else 0.0,
        "incompleteFrameIndexes": incomplete_frames,
        "abruptFrameIndexes": abrupt_frames,
        "frames": [
            {
                "frameIndex": frame_index,
                "meanChannel": mean_channel,
                "nearBlackFraction": near_black_fraction,
            }
            for frame_index, (mean_channel, near_black_fraction) in enumerate(
                zip(means, near_black_fractions, strict=True)
            )
        ],
    }
    proof["success"] = (
        decoded_frames == expected_frames
        and trailing_bytes == 0
        and not incomplete_frames
        and not abrupt_frames
    )
    return proof


def video_proof(
    video_path: Path,
    expected_frames: int,
    source_resolution: list[int],
    capture_camera: str,
) -> dict:
    source_width, source_height = source_resolution
    audit_width = VISUAL_AUDIT_WIDTH
    audit_height = round(audit_width * source_height / source_width)
    audit_resolution = [audit_width, audit_height]
    minimum_mean_channel = (
        TCP_VISUAL_AUDIT_MIN_MEAN_CHANNEL
        if capture_camera == "tcp"
        else VISUAL_AUDIT_MIN_MEAN_CHANNEL
    )
    maximum_adjacent_mean_delta = (
        TCP_VISUAL_AUDIT_MAX_ADJACENT_MEAN_DELTA
        if capture_camera == "tcp"
        else VISUAL_AUDIT_MAX_ADJACENT_MEAN_DELTA
    )
    discover = subprocess.run(
        ["gst-discoverer-1.0", str(video_path)],
        text=True,
        capture_output=True,
        timeout=30.0,
    )
    discover_output = discover.stdout + discover.stderr
    with tempfile.TemporaryDirectory(prefix="puppybot-video-audit-") as audit_dir:
        raw_path = Path(audit_dir) / f"decoded-{audit_width}x{audit_height}.rgb"
        decode_command = [
            "gst-launch-1.0",
            "-q",
            "filesrc",
            f"location={video_path.resolve()}",
            "!",
            "qtdemux",
            "!",
            "h264parse",
            "!",
            "openh264dec",
            "!",
            "videoconvert",
            "!",
            "videoscale",
            "!",
            (
                "video/x-raw,format=RGB,"
                f"width={audit_width},height={audit_height},"
                "pixel-aspect-ratio=1/1"
            ),
            "!",
            "filesink",
            f"location={raw_path}",
        ]
        decode = subprocess.run(
            decode_command,
            text=True,
            capture_output=True,
            timeout=30.0,
        )
        quality = (
            decoded_frame_quality(
                raw_path,
                expected_frames,
                audit_resolution,
                minimum_mean_channel,
                maximum_adjacent_mean_delta,
            )
            if decode.returncode == 0 and raw_path.exists()
            else {"success": False, "error": "decoded RGB audit artifact was not produced"}
        )
    proof = {
        "discoveryTool": "gst-discoverer-1.0",
        "discoveryExitCode": discover.returncode,
        "h264": "H.264" in discover_output or "video/x-h264" in discover_output,
        "discoveryOutput": discover_output,
        "decodeTool": "gst-launch-1.0 openh264dec",
        "decodeCommand": decode_command,
        "decodeExitCode": decode.returncode,
        "decodeOutput": decode.stdout + decode.stderr,
        "decodedFrameQuality": quality,
    }
    proof["success"] = (
        discover.returncode == 0
        and proof["h264"]
        and decode.returncode == 0
        and quality.get("success") is True
    )
    if not proof["success"]:
        raise RuntimeError(
            f"recorded MP4 was not a complete, frame-audited H.264 video: {proof}"
        )
    return proof


def run_demo(api: RuntimeApi, capture_frames: int, capture_camera: str) -> tuple[dict, dict]:
    initial = api.state("initial")
    initial_manipulation = manipulation(initial)
    if initial_manipulation.get("simulationOnly") is not True:
        raise RuntimeError("Interact did not advertise simulationOnly=true")

    api.post("/api/arm/speed", {"speed": 300})
    api.move("pre_pick")

    rejected_far = False
    try:
        api.post("/api/sim/interact")
    except RuntimeError:
        rejected_far = True
    if not rejected_far:
        raise RuntimeError("Interact incorrectly attached the ball while TCP was far away")

    capture = api.post(
        "/api/sim/captures/record",
        {"frames": capture_frames, "camera": capture_camera},
    )["job"]
    api.move("pick")
    pickup_ball = manipulation(api.state("pickup-aligned"))["ball"]
    if float(pickup_ball.get("tcpDistanceM", 1.0)) > 0.007:
        raise RuntimeError("pickup pose did not align the observed TCP to the ball within 7 mm")
    attached_response = api.post("/api/sim/interact")
    attached_state = attached_response["state"]
    if manipulation(attached_state)["ball"].get("attached") is not True:
        raise RuntimeError("Interact did not attach the ball at the pickup pose")

    api.move("lift")
    lifted = api.state("ball-lifted")
    lifted_manipulation = manipulation(lifted)
    if lifted_manipulation["ball"].get("attached") is not True:
        raise RuntimeError("ball detached during lift")
    if float(lifted_manipulation["ball"].get("tcpDistanceM", 1.0)) > 0.006:
        raise RuntimeError("attached ball did not track the observed RobotDreams TCP")

    api.move("transfer")
    api.move("drop")
    released_response = api.post("/api/sim/interact")
    released_state = released_response["state"]
    if manipulation(released_state)["ball"].get("attached") is not False:
        raise RuntimeError("second Interact did not release the ball")

    deadline = time.monotonic() + 5.0
    final = released_state
    while time.monotonic() < deadline:
        final = api.state("wait-bin-trigger")
        trigger = manipulation(final)["binTrigger"]
        if trigger.get("triggered") is True and trigger.get("ballDetected") is True:
            break
        time.sleep(0.05)
    else:
        raise RuntimeError("RobotDreams physics trigger did not detect the released ball in the bin")

    api.move("retreat")
    final = api.state("complete")
    final_manipulation = manipulation(final)
    if final_manipulation["ball"].get("attached") is not False:
        raise RuntimeError("ball was attached after completion")
    if final_manipulation["binTrigger"].get("triggered") is not True:
        raise RuntimeError("settled bin trigger was not present in final simulator state")

    capture_status = wait_capture(api, capture["status"])
    return final, {"job": capture, "status": capture_status, "rejectedFarPickup": rejected_far}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", "--recording-dir", dest="artifacts", type=Path, required=True)
    parser.add_argument("--ui-addr", default=DEFAULT_UI_ADDR)
    parser.add_argument("--ws-addr", default=DEFAULT_WS_ADDR)
    parser.add_argument("--capture-frames", type=int, default=DEFAULT_CAPTURE_FRAMES)
    parser.add_argument("--capture-camera", choices=("external", "tcp"), default="external")
    return parser.parse_args()


def prepare_artifacts_dir(path: Path) -> None:
    if path.exists():
        if not path.is_dir():
            raise RuntimeError(f"recording path exists and is not a directory: {path}")
        if any(path.iterdir()):
            raise RuntimeError(
                f"refusing non-empty recording directory: {path}; choose a new or empty directory"
            )
        return
    path.mkdir(parents=True)


def main() -> int:
    args = parse_args()
    script = Path(__file__).resolve()
    puppybot_dir = script.parents[1]
    project = puppybot_dir.parent / "robotdreams" / "project.json"
    try:
        prepare_artifacts_dir(args.artifacts)
    except (OSError, RuntimeError) as error:
        print(f"place_ball_to_bin: {error}", file=sys.stderr)
        return 2
    command_log = args.artifacts / "commands.jsonl"
    state_log = args.artifacts / "observations.jsonl"
    runtime_log_path = args.artifacts / "runtime.log"
    run_path = args.artifacts / "run.json"
    validation_path = args.artifacts / "validation.json"
    tcp_capture = args.capture_camera == "tcp"
    video_path = args.artifacts / ("tcp-camera.mp4" if tcp_capture else "run.mp4")
    trace_path = args.artifacts / (
        "tcp-camera-capture-trace.json" if tcp_capture else "capture-trace.json"
    )
    final_state_path = args.artifacts / "final-state.json"
    started_ms = time.time_ns() // 1_000_000
    run = {
        "schema": "puppybot.ball-to-bin.run.v1",
        "status": "running",
        "startedUnixMs": started_ms,
        "project": str(project),
        "waypointsArmBaseMm": WAYPOINTS,
        "action": "Interact",
        "simulationOnly": True,
        "captureCamera": args.capture_camera,
    }
    write_json(run_path, run)
    env = os.environ.copy()
    env["PUPPYBOT_RUNTIME_ADDR"] = args.ws_addr
    runtime_log = runtime_log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        ["cargo", "run", "-p", "puppybot-runtime", "--", "--sim", "--headless",
         "--config", "runtime/puppybot.json",
         "--robotdreams-project", str(project), "--ui-bind", args.ui_addr],
        cwd=puppybot_dir,
        env=env,
        stdout=runtime_log,
        stderr=subprocess.STDOUT,
        text=True,
    )
    api = RuntimeApi(f"http://{args.ws_addr}", command_log, state_log)
    error: str | None = None
    final: dict = {}
    capture: dict = {}
    trace_evidence: dict = {}
    video_evidence: dict = {}
    try:
        wait_ready(api, process)
        final, capture = run_demo(api, args.capture_frames, args.capture_camera)
        download(api, capture["job"]["state"], trace_path)
        download(api, capture["job"]["artifact"], video_path)
        trace_evidence = trace_proof(trace_path, args.capture_camera)
        video_evidence = video_proof(
            video_path,
            int(trace_evidence["frameCount"]),
            trace_evidence["cameraPov"]["resolution"],
            args.capture_camera,
        )
        write_json(final_state_path, final)
    except Exception as exception:
        error = str(exception)
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=10.0)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=10.0)
        runtime_log.close()

    final_manipulation = final.get("sim", {}).get("manipulation", {})
    capture_job = capture.get("status", {})
    capture_job_complete = (
        isinstance(capture_job.get("id"), str)
        and capture_job.get("status") == "complete"
        and capture_job.get("camera")
        == ("wrist_camera" if tcp_capture else "external")
    )
    success = (
        error is None
        and capture.get("rejectedFarPickup") is True
        and capture_job_complete
        and final_manipulation.get("ball", {}).get("attached") is False
        and final_manipulation.get("binTrigger", {}).get("triggered") is True
        and final_manipulation.get("binTrigger", {}).get("ballDetected") is True
        and trace_path.exists() and trace_path.stat().st_size > 0
        and video_path.exists() and video_path.stat().st_size > 0
        and trace_evidence.get("success") is True
        and video_evidence.get("success") is True
        and process.poll() is not None
    )
    validation = {
        "schema": "puppybot.ball-to-bin.validation.v1",
        "success": success,
        "error": error,
        "requirements": {
            "farPickupRejected": capture.get("rejectedFarPickup") is True,
            "sameInteractActionAttachedAndReleased": (
                final_manipulation.get("lastAction", {}).get("sequence") == 2
            ),
            "ballDetached": final_manipulation.get("ball", {}).get("attached") is False,
            "robotDreamsBinTriggerEntered": final_manipulation.get("binTrigger", {}).get("entered") is True,
            "robotDreamsBinTriggerSettled": final_manipulation.get("binTrigger", {}).get("triggered") is True,
            "robotDreamsBinTriggerOccupied": final_manipulation.get("binTrigger", {}).get("ballDetected") is True,
            "captureTracePresent": trace_path.exists() and trace_path.stat().st_size > 0,
            "videoPresent": video_path.exists() and video_path.stat().st_size > 0,
            "captureJobCompleted": capture_job_complete,
            "captureTraceProvesOrderedPhysicsTask": trace_evidence.get("success") is True,
            "captureUsesRequestedCameraPov": (
                trace_evidence.get("cameraPov", {}).get("success") is True
            ),
            "videoIsPlayableH264": video_evidence.get("success") is True,
            "runtimeExited": process.poll() is not None,
        },
        "runtimeExitCode": process.returncode,
        "captureJob": capture_job,
        "finalManipulation": final_manipulation,
        "traceEvidence": trace_evidence,
        "videoEvidence": video_evidence,
        "artifacts": {
            "video": str(video_path), "captureTrace": str(trace_path),
            "commands": str(command_log), "observations": str(state_log),
            "finalState": str(final_state_path),
            "runtimeLog": str(runtime_log_path),
        },
    }
    write_json(validation_path, validation)
    run.update({"status": "complete" if success else "failed",
                "completedUnixMs": time.time_ns() // 1_000_000,
                "captureJob": capture_job,
                "validation": str(validation_path)})
    write_json(run_path, run)
    if not success:
        print(json.dumps(validation, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(validation, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
