#!/usr/bin/env python3
"""Create one seeded bottle fixture, run the camera-only policy, then judge it."""

from __future__ import annotations

import argparse
import json
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
    """Two synchronized low-rate native captures from one policy episode."""

    def __init__(self, base_url: str, output_dir: Path) -> None:
        self.base_url = base_url
        self.output_dir = output_dir
        self.jobs: list[dict[str, str]] = []
        self.error: str | None = None

    def start(self) -> None:
        try:
            for clip, camera in (("overhead", "overhead"), ("tcp", "tcp")):
                created, _ = request(
                    self.base_url + "/api/sim/captures/record",
                    "POST",
                    {"frames": 500, "camera": camera, "sampleEveryTicks": 10},
                )
                job = created.get("job") if isinstance(created, dict) else None
                if not isinstance(job, dict) or not all(
                    isinstance(job.get(key), str) for key in ("status", "state", "artifact")
                ):
                    raise RuntimeError(f"continuous {camera} capture returned incomplete job URLs")
                self.jobs.append({"clip": clip, "camera": camera, **job})
        except Exception as error:
            self.error = str(error)

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
            self.error = str(error)

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
                "source": "one state-machine episode",
                "clips": saved,
            })
        except Exception as error:
            self.error = str(error)


def build_fixture(template: Path, output: Path, seed: int) -> list[float]:
    project = json.loads(template.read_text(encoding="utf-8"))
    puppybot_project = template.parents[2]
    robotdreams_project = puppybot_project.parent / "RobotDreams"
    project["modelProfile"] = str((puppybot_project / "models/puppybot/robotdreams.json").resolve())
    project["robots"][0]["model"]["path"] = str((puppybot_project / "models/puppybot/final2/urdf/final2.urdf").resolve())
    rng = random.Random(seed)
    # A camera-visible random search patch in front of the rover. The policy
    # never receives this coordinate; the fixture and final state remain private.
    bottle_xy = [rng.uniform(-0.18, 0.18), rng.uniform(0.24, 0.42)]
    for item in project["scene"]["objects"]:
        if item["id"] == "bottle":
            item["position"] = [*bottle_xy, 0.10]
            item["asset"] = str((puppybot_project / "models/water-bottle.glb").resolve())
        elif item["id"] == "trashbin":
            item["position"] = [*BIN_XY, 0.0]
            item["asset"] = str((robotdreams_project / "examples/trashbin.gltf").resolve())
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
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--ui-addr", default="127.0.0.1:18183")
    parser.add_argument("--ws-addr", default="127.0.0.1:18182")
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
    args = parser.parse_args()
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
    try:
        base_url = f"http://{args.ws_addr}"
        wait_runtime(base_url, process)
        policy_dir = args.artifacts / "policy"
        stage_log = args.artifacts / "judge-private" / "video-stage-log.jsonl"
        if args.record_continuous_episode:
            continuous_captures = ContinuousEpisodeCaptures(base_url, args.artifacts / "continuous-video")
            continuous_captures.start()
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
        policy_status = subprocess.call([
            sys.executable, str(script.with_name("bottle_to_bin_yolo.py")),
            "--model", str(args.model), "--artifacts", str(policy_dir),
            "--base-url", base_url, "--bin-x", str(BIN_XY[0]), "--bin-y", str(BIN_XY[1]),
            "--stage-log", str(stage_log),
            "--state-log", str(policy_dir / "state-transitions.jsonl"),
        ])
        time.sleep(3.0)
        write_json(private / "final-state.json", request_json(base_url + "/api/state"))
        if continuous_captures is not None:
            continuous_captures.stop_and_save()
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
        if isinstance(detection, dict):
            continuous_captures.render_overhead_yolo_overlay(detection, puppybot_dir, project)
        else:
            continuous_captures.error = "continuous overhead overlay has no policy detection"
    judge = subprocess.call([
        sys.executable, str(script.with_name("judge_bottle_to_bin.py")),
        "--policy-artifacts", str(args.artifacts / "policy"),
        "--judge-state", str(private / "final-state.json"),
        "--output", str(args.artifacts / "validation.json"),
    ])
    video_status = 0
    for video_capture in video_captures:
        if video_capture.error is not None:
            print(f"video capture failed: {video_capture.error}", file=sys.stderr)
            video_status = 1
    if continuous_captures is not None and continuous_captures.error is not None:
        print(f"continuous video capture failed: {continuous_captures.error}", file=sys.stderr)
        video_status = 1
    return 0 if policy_status == 0 and judge == 0 and video_status == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
