#!/usr/bin/env python3
"""Create one seeded bottle fixture, run the camera-only policy, then judge it."""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path


BIN_XY = [-0.52, 0.32]
BOTTLE_CENTER_Z_M = 0.1922
# The lowest range-checked virtual-arm TCP is 92.2 mm above the floor bottle.
# Keep the dynamic bottle at that measured centre height on a static support;
# the seeded X/Y distribution remains unchanged for camera-policy evaluation.
PICKUP_PEDESTAL_HEIGHT_M = BOTTLE_CENTER_Z_M - 0.10 + 0.001
PICKUP_PEDESTAL_CENTER_Z_M = (BOTTLE_CENTER_Z_M - 0.10 - 0.001) * 0.5
BIN_WALL_OFFSETS = {
    "trashbin_wall_front": [0.084, 0.0, 0.09],
    "trashbin_wall_back": [-0.084, 0.0, 0.09],
    "trashbin_wall_left": [0.0, 0.084, 0.09],
    "trashbin_wall_right": [0.0, -0.084, 0.09],
}


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def request_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=5) as response:
        value = json.loads(response.read())
    if not isinstance(value, dict):
        raise RuntimeError(f"{url} did not return a JSON object")
    return value


def request(url: str, method: str = "GET", body: dict | None = None) -> tuple[dict | None, bytes]:
    encoded = None if body is None else json.dumps(body).encode("utf-8")
    http_request = urllib.request.Request(
        url, data=encoded, method=method, headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(http_request, timeout=10) as response:
        raw = response.read()
        value = json.loads(raw) if "json" in response.headers.get("Content-Type", "") else None
    return value, raw


class NativeVideoCapture:
    """Private harness-only native recording triggered by a local policy cue."""

    def __init__(
        self,
        base_url: str,
        stage_log: Path,
        output_dir: Path,
        stage: str,
        frames: int,
        clip: str,
        camera: str,
    ) -> None:
        self.base_url = base_url
        self.stage_log = stage_log
        self.output_dir = output_dir
        self.stage = stage
        self.frames = frames
        self.clip = clip
        self.camera = camera
        self.error: str | None = None
        self.thread = threading.Thread(target=self._run, name="bottle-video-capture", daemon=True)

    def start(self) -> None:
        self.thread.start()

    def join(self) -> None:
        self.thread.join(timeout=300)
        if self.thread.is_alive():
            self.error = "native video capture did not finish within 300 seconds"

    def _wait_for_stage(self) -> None:
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            if self.stage_log.is_file() and any(
                json.loads(line).get("stage") == self.stage
                for line in self.stage_log.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ):
                return
            time.sleep(0.05)
        raise RuntimeError(f"policy never reached the {self.stage} video cue")

    def _run(self) -> None:
        try:
            self._wait_for_stage()
            created, _ = request(
                self.base_url + "/api/sim/captures/record",
                "POST",
                {"frames": self.frames, "camera": self.camera},
            )
            if not isinstance(created, dict) or not isinstance(created.get("job"), dict):
                raise RuntimeError("record endpoint returned no capture job")
            job = created["job"]
            status_path = job.get("status")
            state_path = job.get("state")
            artifact_path = job.get("artifact")
            if not all(isinstance(path, str) for path in (status_path, state_path, artifact_path)):
                raise RuntimeError("record endpoint returned incomplete job URLs")
            deadline = time.monotonic() + 240
            while time.monotonic() < deadline:
                status = request_json(self.base_url + status_path)
                capture = status.get("job", {})
                if capture.get("status") == "complete":
                    self.output_dir.mkdir(parents=True, exist_ok=True)
                    state, state_bytes = request(self.base_url + state_path)
                    _artifact, artifact_bytes = request(self.base_url + artifact_path)
                    if not isinstance(state, dict) or state.get("schema") != "puppybot.sim.capture-trace.v1":
                        raise RuntimeError("native recording did not return a capture trace")
                    if len(artifact_bytes) == 0:
                        raise RuntimeError("native recording artifact is empty")
                    camera_label = "tcp" if self.camera == "tcp" else "overhead"
                    (self.output_dir / f"{self.clip}.trace.json").write_bytes(state_bytes)
                    (self.output_dir / f"verified-{camera_label}-{self.clip}.mp4").write_bytes(artifact_bytes)
                    write_json(self.output_dir / "video.json", {
                        "schema": "puppybot.bottle-yolo.video.v1",
                        "captureCamera": "wrist_camera" if self.camera == "tcp" else "overhead_camera",
                        "clip": self.clip,
                        "frames": len(state.get("frames", [])),
                        "source": "native exact visual replay capture",
                    })
                    return
                if capture.get("status") == "failed":
                    raise RuntimeError(f"native recording failed: {capture.get('error')}")
                time.sleep(0.1)
            raise RuntimeError("native video capture did not complete")
        except Exception as error:
            self.error = str(error)


class ContinuousEpisodeCaptures:
    """Native camera capture(s) spanning one complete policy episode."""

    def __init__(
        self,
        base_url: str,
        output_dir: Path,
        cameras: tuple[tuple[str, str], ...] = (("overhead", "overhead"), ("tcp", "tcp")),
    ) -> None:
        self.base_url = base_url
        self.output_dir = output_dir
        self.cameras = cameras
        self.jobs: list[dict[str, str]] = []
        self.error: str | None = None

    def fail(self, error: Exception) -> None:
        self.error = str(error)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        write_json(self.output_dir / "capture-error.json", {
            "schema": "puppybot.bottle-yolo.continuous-video-error.v1",
            "error": self.error,
        })

    def start(self) -> None:
        try:
            for clip, camera in self.cameras:
                created, _ = request(
                    self.base_url + "/api/sim/captures/record",
                    "POST",
                    {"camera": camera},
                )
                job = created.get("job") if isinstance(created, dict) else None
                if not isinstance(job, dict) or not all(
                    isinstance(job.get(key), str) for key in ("status", "state", "artifact")
                ):
                    raise RuntimeError(f"continuous {camera} capture returned incomplete job URLs")
                self.jobs.append({"clip": clip, "camera": camera, **job})
        except Exception as error:
            self.fail(error)

    def render_overhead_yolo_overlay(
        self, detection: dict, puppybot_dir: Path, project: Path,
    ) -> None:
        """Replay only model-produced Search boxes onto the overhead trace."""
        if self.error is not None:
            return
        try:
            xyxy = detection.get("xyxy")
            confidence = detection.get("confidence")
            label = detection.get("label")
            if (
                not isinstance(xyxy, list)
                or len(xyxy) != 4
                or not isinstance(confidence, (int, float))
                or label != "bottle"
            ):
                raise RuntimeError("continuous overhead overlay has no valid YOLO bottle detection")
            trace_path = self.output_dir / "continuous-overhead.trace.json"
            trace = json.loads(trace_path.read_text(encoding="utf-8"))
            frames = trace.get("frames")
            if not isinstance(frames, list) or not frames:
                raise RuntimeError("continuous overhead trace has no frames")
            # Search happens before rover motion.  The first two seconds are
            # camera-stationary and therefore share the exact policy RGB box.
            for sample in frames[:10]:
                sample["frame"]["detectionBoxes"] = [{
                    "label": label,
                    "confidence": confidence,
                    "xyxy": xyxy,
                }]
            annotated_trace = self.output_dir / "continuous-overhead-yolo.trace.json"
            write_json(annotated_trace, trace)
            output = self.output_dir / "continuous-overhead-yolo.mp4"
            subprocess.run([
                "cargo", "run", "-q", "-p", "puppybot-runtime", "--", "record", "--sim",
                "--state", str(annotated_trace), "--out", str(output),
                "--robotdreams-project", str(project),
            ], cwd=puppybot_dir, check=True, timeout=300)
            manifest_path = self.output_dir / "continuous-video.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["overheadYoloVideo"] = output.name
            manifest["overheadDetectionOverlay"] = {
                "label": label,
                "confidence": confidence,
                "traceFrames": list(range(10)),
            }
            write_json(manifest_path, manifest)
        except Exception as error:
            self.fail(error)

    def render_tcp_yolo_overlay(self, detections_path: Path, puppybot_dir: Path, project: Path) -> None:
        """Render TCP boxes only where a policy atomic observation matches a TCP audit frame."""
        if self.error is not None:
            return
        try:
            events = [
                json.loads(line) for line in detections_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            trace_path = self.output_dir / "continuous-tcp.trace.json"
            trace = json.loads(trace_path.read_text(encoding="utf-8"))
            frames = trace.get("frames")
            if not isinstance(frames, list) or not frames:
                raise RuntimeError("continuous TCP trace has no frames")
            matched: dict[int, dict[str, object]] = {}
            for event in events:
                if not isinstance(event, dict) or event.get("schema") != "puppybot.bottle-yolo.tcp-detection.v1":
                    continue
                detection = event.get("detection")
                observation = event.get("atomicObservation")
                if not isinstance(detection, dict) or not isinstance(observation, dict):
                    continue
                xyxy = detection.get("xyxy")
                confidence = detection.get("confidence")
                camera = observation.get("camera")
                if (
                    detection.get("label") != "bottle"
                    or not isinstance(xyxy, list)
                    or len(xyxy) != 4
                    or not isinstance(confidence, (int, float))
                    or not isinstance(camera, dict)
                    or camera.get("source") != "wrist_camera"
                    or not isinstance(camera.get("eyeM"), list)
                ):
                    continue
                eye = camera["eyeM"]
                candidates: list[tuple[float, int]] = []
                for index, sample in enumerate(frames):
                    trace_camera = sample.get("camera") if isinstance(sample, dict) else None
                    trace_eye = trace_camera.get("eyeM") if isinstance(trace_camera, dict) else None
                    if not isinstance(trace_eye, list) or len(trace_eye) != 3 or len(eye) != 3:
                        continue
                    distance_m = math.sqrt(sum((float(eye[i]) - float(trace_eye[i])) ** 2 for i in range(3)))
                    candidates.append((distance_m, index))
                if not candidates:
                    continue
                distance_m, index = min(candidates)
                # At 5 fps a moving capture frame can be close but not be the
                # policy RGB image.  Preserve only the same-pose evidence.
                if distance_m > 0.001:
                    continue
                previous = matched.get(index)
                if previous is None or float(confidence) > float(previous["confidence"]):
                    matched[index] = {
                        "sequence": event.get("sequence"),
                        "phase": event.get("phase"),
                        "confidence": confidence,
                        "xyxy": xyxy,
                        "atomicObservationId": observation.get("id"),
                        "poseDistanceM": distance_m,
                    }
            if not matched:
                raise RuntimeError("no policy TCP YOLO detection exactly matched a TCP audit frame")
            for index, match in matched.items():
                frames[index]["frame"]["detectionBoxes"] = [{
                    "label": "bottle",
                    "confidence": match["confidence"],
                    "xyxy": match["xyxy"],
                }]
            annotated_trace = self.output_dir / "continuous-tcp-yolo.trace.json"
            write_json(annotated_trace, trace)
            output = self.output_dir / "continuous-tcp-yolo.mp4"
            subprocess.run([
                "cargo", "run", "-q", "-p", "puppybot-runtime", "--", "record", "--sim",
                "--state", str(annotated_trace), "--out", str(output),
                "--robotdreams-project", str(project),
            ], cwd=puppybot_dir, check=True, timeout=300)
            manifest_path = self.output_dir / "continuous-video.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["tcpYoloVideo"] = output.name
            manifest["tcpYoloDetectionOverlay"] = {
                "source": "policy/tcp-yolo-detections.jsonl",
                "matching": "atomic camera-eye pose within 1 mm of TCP audit trace",
                "matchedTraceFrames": [
                    {"frameIndex": index, **match} for index, match in sorted(matched.items())
                ],
            }
            write_json(manifest_path, manifest)
        except Exception as error:
            self.fail(error)

    def stop_and_save(self) -> None:
        if self.error is not None:
            return
        try:
            for job in self.jobs:
                request(self.base_url + job["status"] + "/stop", "POST", {})
            deadline = time.monotonic() + 300
            saved: list[dict[str, object]] = []
            for job in self.jobs:
                while time.monotonic() < deadline:
                    status = request_json(self.base_url + job["status"])
                    capture = status.get("job", {})
                    if capture.get("status") == "complete":
                        self.output_dir.mkdir(parents=True, exist_ok=True)
                        state, state_bytes = request(self.base_url + job["state"])
                        _artifact, artifact_bytes = request(self.base_url + job["artifact"])
                        if not isinstance(state, dict) or state.get("schema") != "puppybot.sim.capture-trace.v1":
                            raise RuntimeError(f"continuous {job['clip']} capture did not return a trace")
                        clip = job["clip"]
                        (self.output_dir / f"continuous-{clip}.trace.json").write_bytes(state_bytes)
                        (self.output_dir / f"continuous-{clip}.mp4").write_bytes(artifact_bytes)
                        saved.append({
                            "clip": clip,
                            "camera": state["frames"][0]["camera"]["source"],
                            "frames": len(state["frames"]),
                            "fps": state["fps"],
                        })
                        break
                    if capture.get("status") == "failed":
                        raise RuntimeError(f"continuous {job['clip']} capture failed: {capture.get('error')}")
                    time.sleep(0.1)
                else:
                    raise RuntimeError(f"continuous {job['clip']} capture did not complete")
            write_json(self.output_dir / "continuous-video.json", {
                "schema": "puppybot.bottle-yolo.continuous-video.v1",
                "source": "one live raw-RGBA encoder stream per camera across one state-machine episode",
                "clips": saved,
            })
        except Exception as error:
            self.fail(error)


class DeferredTcpReplayCapture:
    """Capture only compact TCP pose state while autonomy runs.

    The render/MP4 work occurs after the policy passed its completion judge and
    the episode runtime has stopped.  This keeps a second WGPU renderer and
    encoder entirely out of the visual-servo timing path.
    """

    def __init__(self, base_url: str, output_dir: Path) -> None:
        self.base_url = base_url
        self.output_dir = output_dir
        self.job: dict[str, str] | None = None
        self.error: str | None = None
        self.trace_path = output_dir / "continuous-tcp.trace.json"

    def start(self) -> None:
        try:
            created, _ = request(
                self.base_url + "/api/sim/captures/record",
                "POST",
                {
                    "camera": "tcp",
                    "mode": "trace",
                    # Five pose samples/sec are enough for an audit/replay
                    # video and avoid perturbing the 20+ Hz detector path.
                    "sampleEveryTicks": 10,
                },
            )
            job = created.get("job") if isinstance(created, dict) else None
            if not isinstance(job, dict) or not all(
                isinstance(job.get(key), str) for key in ("status", "state")
            ):
                raise RuntimeError("trace-only TCP capture returned incomplete job URLs")
            self.job = {key: str(value) for key, value in job.items() if isinstance(value, str)}
        except Exception as error:
            self.error = str(error)

    def stop_and_save(self) -> None:
        if self.error is not None or self.job is None:
            return
        try:
            request(self.base_url + self.job["status"] + "/stop", "POST", {})
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                status = request_json(self.base_url + self.job["status"])
                capture = status.get("job", {})
                if capture.get("status") == "complete":
                    state, state_bytes = request(self.base_url + self.job["state"])
                    if (
                        not isinstance(state, dict)
                        or state.get("schema") != "puppybot.sim.capture-trace.v1"
                        or not isinstance(state.get("frames"), list)
                        or not state["frames"]
                    ):
                        raise RuntimeError("trace-only TCP capture did not return a non-empty trace")
                    self.output_dir.mkdir(parents=True, exist_ok=True)
                    self.trace_path.write_bytes(state_bytes)
                    return
                if capture.get("status") == "failed":
                    raise RuntimeError(f"trace-only TCP capture failed: {capture.get('error')}")
                time.sleep(0.05)
            raise RuntimeError("trace-only TCP capture did not complete")
        except Exception as error:
            self.error = str(error)

    def render_after_success(
        self,
        detections_path: Path,
        puppybot_dir: Path,
        project: Path,
        validation_path: Path,
    ) -> None:
        if self.error is not None:
            return
        try:
            if not self.trace_path.is_file():
                raise RuntimeError("trace-only TCP capture trace is unavailable")
            validation = json.loads(validation_path.read_text(encoding="utf-8"))
            if not isinstance(validation, dict) or validation.get("success") is not True:
                raise RuntimeError("refusing TCP replay render because the episode judge did not pass")
            trace = json.loads(self.trace_path.read_text(encoding="utf-8"))
            frames = trace.get("frames") if isinstance(trace, dict) else None
            if not isinstance(frames, list) or not frames:
                raise RuntimeError("trace-only TCP capture has no frames")
            detections = [
                json.loads(line) for line in detections_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            matched: dict[int, dict[str, object]] = {}
            for event in detections:
                if not isinstance(event, dict) or event.get("schema") not in (
                    "puppybot.bottle-yolo.tcp-detection.v1",
                    "puppybot.bottle-detector.tcp-detection.v2",
                ):
                    continue
                detection = event.get("detection")
                observation = event.get("atomicObservation")
                if not isinstance(detection, dict) or not isinstance(observation, dict):
                    continue
                camera = observation.get("camera")
                xyxy = detection.get("xyxy")
                confidence = detection.get("confidence")
                if (
                    detection.get("label") != "bottle"
                    or not isinstance(camera, dict)
                    or not isinstance(camera.get("eyeM"), list)
                    or not isinstance(xyxy, list)
                    or len(xyxy) != 4
                    or not isinstance(confidence, (int, float))
                ):
                    continue
                eye = camera["eyeM"]
                choices: list[tuple[float, int]] = []
                for index, sample in enumerate(frames):
                    trace_camera = sample.get("camera") if isinstance(sample, dict) else None
                    trace_eye = trace_camera.get("eyeM") if isinstance(trace_camera, dict) else None
                    if not isinstance(trace_eye, list) or len(trace_eye) != 3 or len(eye) != 3:
                        continue
                    choices.append((
                        math.sqrt(sum((float(eye[i]) - float(trace_eye[i])) ** 2 for i in range(3))),
                        index,
                    ))
                if not choices:
                    continue
                distance_m, index = min(choices)
                # This is a five-fps trace, not an inference input: allow the
                # nearest stable-pose audit sample, never scene truth.
                if distance_m > 0.025:
                    continue
                previous = matched.get(index)
                if previous is None or float(confidence) > float(previous["confidence"]):
                    matched[index] = {
                        "confidence": float(confidence),
                        "xyxy": xyxy,
                        "detector": event.get("detector"),
                        "phase": event.get("phase"),
                        "atomicObservationId": observation.get("id"),
                        "poseDistanceM": distance_m,
                    }
            for index, match in matched.items():
                frames[index]["frame"]["detectionBoxes"] = [{
                    "label": "bottle",
                    "confidence": match["confidence"],
                    "xyxy": match["xyxy"],
                }]
            annotated_trace = self.output_dir / "continuous-tcp-tinygrad-v6.trace.json"
            write_json(annotated_trace, trace)
            output = self.output_dir / "continuous-tcp-tinygrad-v6.mp4"
            subprocess.run([
                "cargo", "run", "-q", "-p", "puppybot-runtime", "--", "record", "--sim",
                "--state", str(annotated_trace), "--out", str(output),
                "--robotdreams-project", str(project),
            ], cwd=puppybot_dir, check=True, timeout=300)
            if not output.is_file() or output.stat().st_size == 0:
                raise RuntimeError("post-success TCP replay MP4 is missing or empty")
            write_json(self.output_dir / "continuous-tcp-tinygrad-v6.manifest.json", {
                "schema": "puppybot.bottle-detector.post-success-tcp-replay.v1",
                "detector": "tinygrad-v6",
                "video": output.name,
                "trace": annotated_trace.name,
                "rawTrace": self.trace_path.name,
                "validation": str(validation_path),
                "validationSuccess": True,
                "frames": len(frames),
                "fps": trace.get("fps"),
                "detectionBoxes": {
                    "source": "policy/tcp-yolo-detections.jsonl",
                    "matchedTraceFrames": [
                        {"frameIndex": index, **match} for index, match in sorted(matched.items())
                    ],
                },
                "recordingArchitecture": (
                    "trace-only TCP pose samples during policy; replay renderer and MP4 encoder "
                    "start only after independent episode judge success"
                ),
            })
        except Exception as error:
            self.error = str(error)


def build_fixture(template: Path, output: Path, seed: int) -> list[float]:
    project = json.loads(template.read_text(encoding="utf-8"))
    puppybot_project = template.parents[2]
    robotdreams_project = puppybot_project.parent / "RobotDreams"
    project["modelProfile"] = str((puppybot_project / "models/puppybot/robotdreams.json").resolve())
    project["robots"][0]["model"]["path"] = str((puppybot_project / "models/puppybot/final2/urdf/final2.urdf").resolve())
    vehicle = project["robots"][0].get("physics", {}).get("vehicle", {})
    collision_profile = vehicle.get("collisionProfile")
    if isinstance(collision_profile, str):
        vehicle["collisionProfile"] = str((template.parent / collision_profile).resolve())
    rng = random.Random(seed)
    # Judge-only sample from the calibrated overlap of the home wrist camera's
    # floor footprint and the arm's post-dock reach annulus.  The policy never
    # receives this coordinate: it must still acquire the bottle from TCP RGB.
    # Keeping V1 within this observable set avoids scoring a wrist-only policy
    # against placements that disappear beneath the mounted camera before a
    # safe handoff is possible.
    bottle_xy = [rng.uniform(0.11, 0.17), rng.uniform(0.13, 0.17)]
    for item in project["scene"]["objects"]:
        if item["id"] == "bottle":
            item["position"] = [*bottle_xy, BOTTLE_CENTER_Z_M]
            item["asset"] = str((puppybot_project / "models/water-bottle.glb").resolve())
        elif item["id"] == "pickup_pedestal":
            item["position"] = [*bottle_xy, PICKUP_PEDESTAL_CENTER_Z_M]
        elif item["id"] == "trashbin":
            item["position"] = [*BIN_XY, 0.0]
            item["asset"] = str((robotdreams_project / "examples/trashbin.gltf").resolve())
        elif item["id"] in BIN_WALL_OFFSETS:
            offset = BIN_WALL_OFFSETS[item["id"]]
            item["position"] = [BIN_XY[0] + offset[0], BIN_XY[1] + offset[1], offset[2]]
    for trigger in project["scene"]["triggers"]:
        if trigger["id"] == "bottle_in_bin":
            trigger["position"] = [*BIN_XY, 0.125]
    output.write_text(json.dumps(project, indent=2) + "\n", encoding="utf-8")
    return bottle_xy


def wait_runtime(url: str, process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"runtime exited during startup: {process.returncode}")
        try:
            request_json(url + "/api/state")
            return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("runtime did not become ready")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, help="ONNX YOLO baseline model")
    parser.add_argument("--detector", choices=("tinygrad-v6", "onnx-yolo"), default="tinygrad-v6")
    parser.add_argument("--tinygrad-model", type=Path, help="native Tinygrad V6 safetensors checkpoint")
    parser.add_argument("--tinygrad-threshold", type=float, default=0.40)
    parser.add_argument("--policy-python", type=Path, default=Path(sys.executable), help="Python interpreter for detector policy")
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--ui-addr", default="127.0.0.1:18183")
    parser.add_argument("--ws-addr", default="127.0.0.1:18182")
    parser.add_argument(
        "--preview", action="store_true",
        help=(
            "open the detector policy's local OpenCV TCP-camera preview; "
            "the simulator remains headless because the preview is an external policy window"
        ),
    )
    parser.add_argument("--record-video", action="store_true",
                        help="save a native overhead-camera drive-to-bin replay clip")
    parser.add_argument("--record-drive-to-bottle-video", action="store_true",
                        help="save a native overhead-camera drive-to-bottle replay clip")
    parser.add_argument("--record-pickup-video", action="store_true",
                        help="save a native overhead-camera pickup-and-lift replay clip")
    parser.add_argument("--record-tcp-pickup-video", action="store_true",
                        help="save a native wrist/TCP-camera pickup-and-lift replay clip")
    parser.add_argument("--record-continuous-episode", action="store_true",
                        help="record synchronized overhead and TCP views across one complete episode")
    parser.add_argument("--record-continuous-tcp-episode", action="store_true",
                        help="record only the wrist/TCP view across one complete episode")
    parser.add_argument("--record-policy-tcp-video", action="store_true",
                        help="stream policy-consumed TCP frames to one full-episode annotated MP4")
    parser.add_argument("--record-postrun-tcp-replay", action="store_true",
                        help="replay a low-rate TCP pose trace only after the completion judge passes")
    parser.add_argument("--policy-test-force-visual-loss-phase",
                        help="test only: suppress one matching fresh pickup observation in the policy")
    args = parser.parse_args()
    if args.detector == "tinygrad-v6" and args.tinygrad_model is None:
        parser.error("--tinygrad-model is required with --detector tinygrad-v6")
    if args.detector == "onnx-yolo" and args.model is None:
        parser.error("--model is required with --detector onnx-yolo")
    # The runtime itself starts from `puppybot/`, so its RobotDreams project
    # argument must not depend on the caller's working directory.
    args.artifacts = args.artifacts.resolve()
    if args.artifacts.exists() and any(args.artifacts.iterdir()):
        raise RuntimeError("refusing non-empty artifacts directory")
    args.artifacts.mkdir(parents=True)
    private = args.artifacts / "judge-private"
    private.mkdir()
    script = Path(__file__).resolve()
    puppybot_dir = script.parents[1]
    project = private / "seeded-project.json"
    bottle_xy = build_fixture(script.with_name("bottle_to_bin.robotdreams.template.json"), project, args.seed)
    write_json(private / "fixture.json", {"seed": args.seed, "bottleWorldM": bottle_xy, "binWorldM": BIN_XY})
    write_json(args.artifacts / "run.json", {
        "schema": "puppybot.bottle-yolo.run.v2",
        "seed": args.seed,
        "binWorldM": BIN_XY,
        "previewRequested": args.preview,
        "stateMachine": ["IDLE", "SEARCH", "APPROACH", "PICKUP", "DRIVE_TO_BIN", "DROP_TO_BIN"],
    })
    env = os.environ | {"PUPPYBOT_RUNTIME_ADDR": args.ws_addr}
    process = subprocess.Popen(
        ["cargo", "run", "-p", "puppybot-runtime", "--", "--sim", "--headless", "--robotdreams-project", str(project), "--ui-bind", args.ui_addr],
        cwd=puppybot_dir, env=env, text=True,
        stdout=(args.artifacts / "runtime.log").open("w", encoding="utf-8"), stderr=subprocess.STDOUT,
    )
    policy_status = 1
    video_captures: list[NativeVideoCapture] = []
    continuous_captures: ContinuousEpisodeCaptures | None = None
    deferred_tcp_replay: DeferredTcpReplayCapture | None = None
    try:
        base_url = f"http://{args.ws_addr}"
        wait_runtime(base_url, process)
        policy_dir = args.artifacts / "policy"
        stage_log = args.artifacts / "judge-private" / "video-stage-log.jsonl"
        if args.record_continuous_episode:
            continuous_captures = ContinuousEpisodeCaptures(base_url, args.artifacts / "continuous-video")
            continuous_captures.start()
        elif args.record_continuous_tcp_episode:
            continuous_captures = ContinuousEpisodeCaptures(
                base_url,
                args.artifacts / "continuous-video",
                (("tcp", "tcp"),),
            )
            continuous_captures.start()
        if args.record_postrun_tcp_replay:
            deferred_tcp_replay = DeferredTcpReplayCapture(
                base_url, args.artifacts / "continuous-video",
            )
            deferred_tcp_replay.start()
        if args.record_drive_to_bottle_video:
            video_captures.append(NativeVideoCapture(
                base_url,
                stage_log,
                args.artifacts / "video",
                "drive-to-bottle",
                500,
                "drive-to-bottle",
                "overhead",
            ))
        if args.record_video:
            video_captures.append(NativeVideoCapture(
                base_url, stage_log, args.artifacts / "video", "drive-to-bin", 500, "drive-to-bin", "overhead",
            ))
        if args.record_pickup_video:
            video_captures.append(NativeVideoCapture(
                base_url, stage_log, args.artifacts / "video", "pickup", 500, "pickup-and-lift", "overhead",
            ))
        if args.record_tcp_pickup_video:
            video_captures.append(NativeVideoCapture(
                base_url,
                stage_log,
                args.artifacts / "video",
                "pickup",
                500,
                "tcp-pickup-and-lift",
                "tcp",
            ))
        for video_capture in video_captures:
            video_capture.start()
        policy_command = [
            str(args.policy_python), str(script.with_name("bottle_to_bin_yolo.py")),
            "--detector", args.detector, "--artifacts", str(policy_dir),
            "--base-url", base_url, "--bin-x", str(BIN_XY[0]), "--bin-y", str(BIN_XY[1]),
            "--stage-log", str(stage_log),
            "--state-log", str(policy_dir / "state-transitions.jsonl"),
        ]
        if args.detector == "tinygrad-v6":
            policy_command.extend(["--tinygrad-model", str(args.tinygrad_model), "--tinygrad-threshold", str(args.tinygrad_threshold)])
        else:
            policy_command.extend(["--model", str(args.model)])
        if args.policy_test_force_visual_loss_phase:
            policy_command.extend([
                "--test-force-visual-loss-phase",
                args.policy_test_force_visual_loss_phase,
            ])
        if args.preview:
            policy_command.append("--preview")
        if args.record_policy_tcp_video:
            policy_command.extend([
                "--record-tcp-video",
                str(args.artifacts / "continuous-video" / "continuous-tcp.mp4"),
            ])
        policy_status = subprocess.call(policy_command)
        time.sleep(3.0)
        write_json(private / "final-state.json", request_json(base_url + "/api/state"))
        if continuous_captures is not None:
            continuous_captures.stop_and_save()
        if deferred_tcp_replay is not None:
            deferred_tcp_replay.stop_and_save()
        for video_capture in video_captures:
            video_capture.join()
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGINT)
            process.wait(timeout=10)
    if continuous_captures is not None and continuous_captures.error is None:
        policy_result = json.loads((args.artifacts / "policy" / "policy-result.json").read_text(encoding="utf-8"))
        result = policy_result.get("result") if isinstance(policy_result, dict) else None
        detection = result.get("detection") if isinstance(result, dict) else None
        captured_clips = {job["clip"] for job in continuous_captures.jobs}
        if "overhead" in captured_clips and isinstance(detection, dict):
            continuous_captures.render_overhead_yolo_overlay(detection, puppybot_dir, project)
        elif "overhead" in captured_clips:
            continuous_captures.error = "continuous overhead overlay has no policy detection"
        if "tcp" in captured_clips:
            continuous_captures.render_tcp_yolo_overlay(
                args.artifacts / "policy" / "tcp-yolo-detections.jsonl", puppybot_dir, project,
            )
    policy_dir = args.artifacts / "policy"
    policy_result_path = policy_dir / "policy-result.json"
    policy_result: dict[str, object] | None = None
    if policy_result_path.is_file():
        candidate = json.loads(policy_result_path.read_text(encoding="utf-8"))
        if isinstance(candidate, dict):
            policy_result = candidate
    policy_error = policy_result.get("error") if policy_result is not None else None
    operator_stopped = (
        isinstance(policy_error, str)
        and policy_error == "operator closed the live TCP preview"
    )
    judge_inputs = [
        policy_dir / "policy-result.json",
        policy_dir / "commands.jsonl",
        private / "final-state.json",
    ]
    missing_judge_inputs = [str(path.relative_to(args.artifacts)) for path in judge_inputs if not path.is_file()]
    if operator_stopped:
        # Closing the local preview deliberately ends the policy after it has
        # sent its safety stop. A completion judge would only report a false
        # failure for an episode the operator intentionally interrupted.
        print("skipping completion judge: operator closed the live TCP preview", file=sys.stderr)
        judge = 0
        completion_judge_run = False
    elif missing_judge_inputs:
        # A detector/model preflight failure can happen before RuntimeApi opens
        # commands.jsonl. The judge requires that audit trail, so invoking it
        # would only hide the primary policy error behind a file traceback.
        print(
            "skipping judge: policy did not produce required artifacts: "
            + ", ".join(missing_judge_inputs),
            file=sys.stderr,
        )
        judge = 1
        completion_judge_run = False
    else:
        judge = subprocess.call([
            sys.executable, str(script.with_name("judge_bottle_to_bin.py")),
            "--policy-artifacts", str(policy_dir),
            "--judge-state", str(private / "final-state.json"),
            "--output", str(args.artifacts / "validation.json"),
        ])
        completion_judge_run = True
    write_json(args.artifacts / "episode-result.json", {
        "schema": "puppybot.bottle-yolo.episode-result.v1",
        "outcome": "operator-stopped" if operator_stopped else ("completed" if policy_status == 0 else "policy-failed"),
        "policyExitCode": policy_status,
        "policyError": policy_error,
        "previewRequested": args.preview,
        "completionJudgeRun": completion_judge_run,
    })
    if deferred_tcp_replay is not None:
        if policy_status == 0 and judge == 0:
            deferred_tcp_replay.render_after_success(
                policy_dir / "tcp-yolo-detections.jsonl",
                puppybot_dir,
                project,
                args.artifacts / "validation.json",
            )
        elif deferred_tcp_replay.error is None:
            deferred_tcp_replay.error = "TCP replay was not rendered because the policy or completion judge failed"
    video_status = 0
    for video_capture in video_captures:
        if video_capture.error is not None:
            print(f"video capture failed: {video_capture.error}", file=sys.stderr)
            video_status = 1
    if continuous_captures is not None and continuous_captures.error is not None:
        print(f"continuous video capture failed: {continuous_captures.error}", file=sys.stderr)
        video_status = 1
    if deferred_tcp_replay is not None and deferred_tcp_replay.error is not None:
        print(f"post-run TCP replay capture failed: {deferred_tcp_replay.error}", file=sys.stderr)
        video_status = 1
    return 0 if policy_status == 0 and judge == 0 and video_status == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
