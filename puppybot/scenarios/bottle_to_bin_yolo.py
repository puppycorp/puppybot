#!/usr/bin/env python3
"""Run the seeded, camera-only PuppyBot bottle-to-bin autonomy scenario.

The actor is deliberately not told the random bottle coordinate.  It receives
only PNG frames produced by the simulator and the configured bin coordinate;
the simulator's bottle pose and bin trigger remain judge-only evidence.

The model must be a YOLO detection checkpoint trained to emit the ``bottle``
class for the RobotDreams bottle fixture.  A missing model or detection fails
closed.  Do not replace this detector with scene-state or colour heuristics.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from PIL import Image


TARGET_CLASS = "bottle"
# This is calibrated against the RobotDreams-specific one-class checkpoint,
# not a COCO checkpoint.  The policy receives it explicitly at launch so an
# operator cannot silently substitute a detector with incompatible scores.
DEFAULT_DETECTION_CONFIDENCE = 0.04
PICKUP_STANDOFF_MM = (230.0, -90.0)
PICKUP_HEIGHT_MM = 55.0
DROP_HEIGHT_MM = 180.0
BOTTLE_CENTER_HEIGHT_M = 0.10
WAYPOINT_TIMEOUT_SEC = 18.0
DRIVE_TIMEOUT_SEC = 60.0
DRIVE_REFRESH_SEC = 0.18
ROVER_WHEELBASE_M = 0.22
ROVER_MAX_SPEED_MPS = 0.40


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_stage(path: Path | None, stage: str) -> None:
    """Emit a local launcher cue without giving the policy a privileged API."""
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"stage": stage, "monotonicSec": time.monotonic()}) + "\n")


class EpisodeState(str, Enum):
    IDLE = "IDLE"
    SEARCH = "SEARCH"
    APPROACH = "APPROACH"
    PICKUP = "PICKUP"
    DRIVE_TO_BIN = "DRIVE_TO_BIN"
    DROP_TO_BIN = "DROP_TO_BIN"


ALLOWED_TRANSITIONS = {
    EpisodeState.IDLE: {EpisodeState.SEARCH},
    EpisodeState.SEARCH: {EpisodeState.APPROACH, EpisodeState.IDLE},
    EpisodeState.APPROACH: {EpisodeState.PICKUP, EpisodeState.IDLE},
    EpisodeState.PICKUP: {EpisodeState.DRIVE_TO_BIN, EpisodeState.IDLE},
    EpisodeState.DRIVE_TO_BIN: {EpisodeState.DROP_TO_BIN, EpisodeState.IDLE},
    EpisodeState.DROP_TO_BIN: {EpisodeState.SEARCH, EpisodeState.IDLE},
}


class EpisodeStateMachine:
    """Bounded one-cycle controller matching the President's V1 stages."""

    def __init__(self, log_path: Path) -> None:
        self.log_path = log_path
        self.state: EpisodeState | None = None
        self.transitions: list[dict[str, Any]] = []

    def transition(self, state: EpisodeState, reason: str) -> None:
        if self.state is not None and state not in ALLOWED_TRANSITIONS[self.state]:
            raise RuntimeError(f"invalid state transition {self.state.value} -> {state.value}")
        event = {
            "sequence": len(self.transitions),
            "state": state.value,
            "reason": reason,
            "monotonicSec": time.monotonic(),
        }
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")
        self.transitions.append(event)
        self.state = state

    def summary(self) -> dict[str, Any]:
        return {
            "schema": "puppybot.trash-collector.state-machine.v1",
            "finalState": self.state.value if self.state is not None else None,
            "transitions": self.transitions,
        }


def distance(left: list[float], right: list[float]) -> float:
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right, strict=True)))


@dataclass(frozen=True)
class Detection:
    label: str
    confidence: float
    # [left, top, right, bottom] in pixels in the native PNG frame.
    xyxy: tuple[float, float, float, float]

    @property
    def center(self) -> tuple[float, float]:
        left, top, right, bottom = self.xyxy
        return ((left + right) * 0.5, (top + bottom) * 0.5)


class YoloDetector:
    """Pinned YOLO11 ONNX detector.  This is the only perception source."""

    def __init__(self, model: Path, bottle_class_index: int, confidence: float) -> None:
        if not model.is_file():
            raise RuntimeError(f"YOLO checkpoint does not exist: {model}")
        try:
            import numpy as np
            import onnxruntime as ort
        except ImportError as error:
            raise RuntimeError(
                "YOLO ONNX runtime missing; install scenarios/requirements-yolo.txt before running"
            ) from error
        self.np = np
        self.session = ort.InferenceSession(str(model), providers=["CPUExecutionProvider"])
        self.input_name = self.session.get_inputs()[0].name
        self.input_size = 640
        self.bottle_class_index = bottle_class_index
        self.confidence = confidence

    @staticmethod
    def _iou(left: Detection, right: Detection) -> float:
        lx1, ly1, lx2, ly2 = left.xyxy
        rx1, ry1, rx2, ry2 = right.xyxy
        intersection = max(0.0, min(lx2, rx2) - max(lx1, rx1)) * max(0.0, min(ly2, ry2) - max(ly1, ry1))
        left_area = max(0.0, lx2 - lx1) * max(0.0, ly2 - ly1)
        right_area = max(0.0, rx2 - rx1) * max(0.0, ry2 - ry1)
        return intersection / max(left_area + right_area - intersection, 1.0e-9)

    def detect(self, image_path: Path) -> Detection | None:
        with Image.open(image_path) as source:
            image = source.convert("RGB")
        width, height = image.size
        scale = min(self.input_size / width, self.input_size / height)
        resized = image.resize((round(width * scale), round(height * scale)))
        pad_x = (self.input_size - resized.width) // 2
        pad_y = (self.input_size - resized.height) // 2
        letterboxed = Image.new("RGB", (self.input_size, self.input_size), (114, 114, 114))
        letterboxed.paste(resized, (pad_x, pad_y))
        tensor = self.np.asarray(letterboxed, dtype=self.np.float32).transpose(2, 0, 1)[None] / 255.0
        output = self.session.run(None, {self.input_name: tensor})[0][0]
        # YOLO detect export: 4 xywh channels followed by class scores.  The
        # checked-in RobotDreams model has one `bottle` class at index zero.
        class_channel = 4 + self.bottle_class_index
        if output.shape[0] <= class_channel:
            raise RuntimeError(
                f"YOLO output has {output.shape[0]} channels; no bottle class {self.bottle_class_index}"
            )
        bottle_scores = output[class_channel]
        candidates: list[Detection] = []
        for index, score in enumerate(bottle_scores):
            confidence = float(score)
            if confidence < self.confidence:
                continue
            center_x, center_y, box_width, box_height = (float(output[channel][index]) for channel in range(4))
            left = (center_x - box_width * 0.5 - pad_x) / scale
            top = (center_y - box_height * 0.5 - pad_y) / scale
            right = (center_x + box_width * 0.5 - pad_x) / scale
            bottom = (center_y + box_height * 0.5 - pad_y) / scale
            candidates.append(Detection(TARGET_CLASS, confidence, (
                max(0.0, left), max(0.0, top), min(float(width), right), min(float(height), bottom)
            )))
        kept: list[Detection] = []
        for candidate in sorted(candidates, key=lambda item: item.confidence, reverse=True):
            if all(self._iou(candidate, previous) < 0.45 for previous in kept):
                kept.append(candidate)
        return kept[0] if kept else None


class RuntimeApi:
    def __init__(self, base_url: str, log: Path) -> None:
        self.base_url = base_url.rstrip("/")
        self.log = log

    def request(self, method: str, path: str, body: dict | None = None) -> tuple[Any, bytes]:
        encoded = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + path, data=encoded, method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=8.0) as response:
                raw = response.read()
                value = json.loads(raw) if "json" in response.headers.get("Content-Type", "") else None
                status = response.status
        except urllib.error.HTTPError as error:
            raw = error.read()
            value = json.loads(raw) if raw else {"error": "empty response"}
            status = error.code
            self._log(method, path, body, status, value)
            raise RuntimeError(f"{method} {path} failed ({status}): {value}") from error
        self._log(method, path, body, status, value)
        return value, raw

    def _log(self, method: str, path: str, body: dict | None, status: int, response: Any) -> None:
        with self.log.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"method": method, "path": path, "body": body,
                                     "status": status, "response": response}, sort_keys=True) + "\n")

    def observation(self) -> dict:
        value, _ = self.request("GET", "/api/autonomy/state")
        if not isinstance(value, dict):
            raise RuntimeError("autonomy observation was not a JSON object")
        return value

    def post(self, path: str, body: dict | None = None) -> dict:
        if path.startswith("/api/") and not path.startswith("/api/autonomy/"):
            path = "/api/autonomy/" + path.removeprefix("/api/")
        value, _ = self.request("POST", path, body or {})
        if not isinstance(value, dict):
            raise RuntimeError(f"{path} did not return an object")
        return value

    def stop_drive(self) -> None:
        self.post("/api/drive/stop")

    def drive(self, throttle: int, steering: int) -> None:
        self.post("/api/drive", {"throttle": throttle, "steering": steering})

    def overhead_camera_frame(self, output: Path) -> None:
        _, png = self.request("GET", "/api/autonomy/cameras/overhead_camera/frame")
        if not png.startswith(b"\x89PNG\r\n\x1a\n"):
            raise RuntimeError("named overhead camera endpoint did not return PNG data")
        output.write_bytes(png)


def matrix_vector(matrix: list[list[float]], vector: list[float]) -> list[float]:
    return [sum(matrix[row][column] * vector[column] for column in range(3)) for row in range(3)]


def transpose_matrix_vector(matrix: list[list[float]], vector: list[float]) -> list[float]:
    return [sum(matrix[row][column] * vector[row] for row in range(3)) for column in range(3)]


def normalize(vector: list[float]) -> list[float]:
    length = math.sqrt(sum(value * value for value in vector))
    if length <= 1.0e-8:
        raise RuntimeError("camera ray had zero length")
    return [value / length for value in vector]


def detection_floor_point(detection: Detection, camera: dict, image_size: tuple[int, int]) -> list[float]:
    """Project the YOLO box centre ray onto the calibrated bottle-centre plane.

    This uses camera calibration published by the capture API, never an object
    transform.  RobotDreams declares matrix columns as optical forward,
    image-left, image-up; pixels therefore map to -left / -up at the image
    centre convention used here.
    """
    width, height = image_size
    pixel_x, pixel_y = detection.center
    # RobotDreams declares fovDeg as vertical FOV. Match its renderer's
    # intrinsics exactly: fx == fy and cx/cy are pixel-centre based.
    tangent = math.tan(math.radians(float(camera["fovDeg"])) * 0.5)
    focal = height * 0.5 / tangent
    sensor_x = (pixel_x - (width - 1.0) * 0.5) / focal
    sensor_y = (pixel_y - (height - 1.0) * 0.5) / focal
    local_ray = normalize([1.0, -sensor_x, -sensor_y])
    rotation = camera["rotationMatrix"]
    ray = normalize(matrix_vector(rotation, local_ray))
    eye = [float(value) for value in camera["eyeM"]]
    if ray[2] >= -1.0e-5:
        raise RuntimeError("camera does not view the bottle plane")
    scale = (BOTTLE_CENTER_HEIGHT_M - eye[2]) / ray[2]
    if scale <= 0.0:
        raise RuntimeError("floor intersection lies behind camera")
    return [eye[index] + ray[index] * scale for index in range(3)]


def camera_detection(api: RuntimeApi, detector: YoloDetector, artifacts: Path, sequence: int) -> tuple[Detection, list[float]]:
    image_path = artifacts / f"camera-{sequence:03d}.png"
    api.overhead_camera_frame(image_path)
    detection = detector.detect(image_path)
    if detection is None:
        raise RuntimeError("YOLO produced no qualifying bottle detection")
    with Image.open(image_path) as image:
        state = api.observation()
        camera = state["sim"]["overheadCamera"]
        if not isinstance(camera, dict):
            raise RuntimeError("autonomy observation has no overhead-camera calibration")
        projected = detection_floor_point(detection, camera, image.size)
    return detection, projected


def yaw_from_world_from_base(frames: dict) -> float:
    rotation = frames["worldFromBase"]["rotationMatrix"]
    return math.atan2(float(rotation[1][0]), float(rotation[0][0]))


def robot_base_position(state: dict) -> list[float]:
    return [float(value) for value in state["sim"]["frames"]["worldFromBase"]["translationM"]]


def wrap_angle(angle: float) -> float:
    return math.atan2(math.sin(angle), math.cos(angle))


def bicycle_step(pose: tuple[float, float, float], throttle: int, steering: int, dt: float) -> tuple[float, float, float]:
    """Match RobotDreams' virtual Ackermann integration for one control tick."""
    x, y, yaw = pose
    speed = ROVER_MAX_SPEED_MPS * throttle / 100.0
    steering_rad = math.radians(steering * 45.0 / 100.0)
    yaw_rate = speed * math.tan(steering_rad) / ROVER_WHEELBASE_M
    return (x + speed * math.cos(yaw) * dt, y + speed * math.sin(yaw) * dt, wrap_angle(yaw + yaw_rate * dt))


def choose_drive_command(
    pose: tuple[float, float, float], target_xy: list[float], target_yaw: float | None = None
) -> tuple[int, int]:
    """A bounded receding-horizon plan over the real virtual-drive controls.

    This is deliberately computed from rover odometry plus a camera-derived
    goal; it has no access to bottle or trigger state.
    """
    actions = [(throttle, steering) for throttle in (-24, -14, -6, 6, 14, 24)
               for steering in (-65, -35, 0, 35, 65)]
    beams: list[tuple[float, tuple[float, float, float], tuple[int, int]]] = [(0.0, pose, (0, 0))]
    for _ in range(18):
        candidates: list[tuple[float, tuple[float, float, float], tuple[int, int]]] = []
        for _, current, first_action in beams:
            for action in actions:
                stepped = bicycle_step(current, action[0], action[1], DRIVE_REFRESH_SEC)
                dx, dy = target_xy[0] - stepped[0], target_xy[1] - stepped[1]
                remaining = math.hypot(dx, dy)
                travel_heading = stepped[2] if action[0] > 0 else wrap_angle(stepped[2] + math.pi)
                heading_error = abs(wrap_angle(math.atan2(dy, dx) - travel_heading))
                # Favour arriving at the waypoint, then a useful direction of
                # travel. Tiny command penalties avoid unnecessary chattering.
                yaw_error = 0.0 if target_yaw is None else abs(wrap_angle(target_yaw - stepped[2]))
                score = remaining * 30.0 + heading_error * 0.20 + yaw_error * 0.45 + abs(action[1]) * 0.001
                candidates.append((score, stepped, action if first_action == (0, 0) else first_action))
        candidates.sort(key=lambda item: item[0])
        beams = candidates[:48]
    return beams[0][2]


def drive_to_world(
    api: RuntimeApi, target_xy: list[float], target_yaw: float | None = None, timeout_sec: float = DRIVE_TIMEOUT_SEC
) -> None:
    """Closed-loop low-speed drive using base pose, never target-object truth."""
    deadline = time.monotonic() + timeout_sec
    try:
        while time.monotonic() < deadline:
            state = api.observation()
            position = robot_base_position(state)
            dx, dy = target_xy[0] - position[0], target_xy[1] - position[1]
            remaining = math.hypot(dx, dy)
            yaw_error = 0.0 if target_yaw is None else abs(wrap_angle(target_yaw - yaw_from_world_from_base(state["sim"]["frames"])))
            if remaining <= 0.025 and yaw_error <= 0.14:
                return
            throttle, steering = choose_drive_command(
                (position[0], position[1], yaw_from_world_from_base(state["sim"]["frames"])), target_xy, target_yaw
            )
            api.drive(throttle, steering)
            time.sleep(DRIVE_REFRESH_SEC)
    finally:
        api.stop_drive()
    raise RuntimeError(f"drive did not reach configured target {target_xy} yaw={target_yaw}")


def pickup_approach_pose(state: dict, bottle_world: list[float]) -> tuple[list[float], float]:
    """Place the rover so the arm sees the camera-derived bottle at 160 mm forward."""
    arm = state["sim"]["frames"]["baseFromArmBase"]
    arm_translation = [float(value) for value in arm["translationM"]]
    arm_rotation = arm["rotationMatrix"]
    local_reach = [0.160, 0.0, 0.0]
    in_base = matrix_vector(arm_rotation, local_reach)
    offset = [arm_translation[index] + in_base[index] for index in range(3)]
    # The initial RobotDreams base heading makes positive arm X point along
    # world +X. Holding it gives the controller a reachable, repeatable pose.
    return ([bottle_world[0] - offset[0], bottle_world[1] - offset[1]], 0.0)


def world_to_arm_base_mm(state: dict, world: list[float]) -> list[float]:
    frames = state["sim"]["frames"]
    world_from_base = frames["worldFromBase"]
    base_from_arm = frames["baseFromArmBase"]
    base_translation = [float(value) for value in world_from_base["translationM"]]
    base_rotation = world_from_base["rotationMatrix"]
    in_base = transpose_matrix_vector(base_rotation, [world[index] - base_translation[index] for index in range(3)])
    arm_translation = [float(value) for value in base_from_arm["translationM"]]
    arm_rotation = base_from_arm["rotationMatrix"]
    in_arm = transpose_matrix_vector(arm_rotation, [in_base[index] - arm_translation[index] for index in range(3)])
    return [value * 1000.0 for value in in_arm]


def move_arm(api: RuntimeApi, target: list[float], label: str) -> None:
    command = {"xMm": target[0], "yMm": target[1], "zMm": target[2], "toolPhiDeg": -90.0}
    api.post("/api/arm/coordinates/move", command)
    deadline = time.monotonic() + WAYPOINT_TIMEOUT_SEC
    while time.monotonic() < deadline:
        state = api.observation()
        current = state["arm"].get("currentTcpMm")
        if isinstance(current, list) and distance([float(value) for value in current], target) <= 8.0:
            return
        api.post("/api/arm/coordinates/move", command)
        time.sleep(0.35)
    raise RuntimeError(f"arm waypoint {label} did not settle")


def run(
    api: RuntimeApi,
    detector: YoloDetector,
    artifacts: Path,
    bin_xy: list[float],
    stage_log: Path | None,
    state_machine: EpisodeStateMachine,
) -> dict:
    state_machine.transition(EpisodeState.IDLE, "episode initialized; waiting for cleaning cycle")
    api.post("/api/arm/speed", {"speed": 300})
    state_machine.transition(EpisodeState.SEARCH, "cleaning cycle started")
    # Search must obtain its target from an RGB frame.  The returned projected
    # coordinate is the sole trash-location input to approach and pickup.
    detection, bottle_world = camera_detection(api, detector, artifacts, 0)
    state = api.observation()
    target_arm = world_to_arm_base_mm(state, bottle_world)
    # Position the rover so the detected location will land at the retuned
    # relative arm standoff; the configured bin remains a navigation landmark.
    approach_xy, _approach_yaw = pickup_approach_pose(state, bottle_world)
    # The planned position places the bottle in the arm workspace. The rover
    # does not need to force an exact final yaw; its current odometry is used
    # below to transform the re-detected point into the arm frame.
    state_machine.transition(EpisodeState.APPROACH, "YOLO bottle detection accepted")
    write_stage(stage_log, "drive-to-bottle")
    drive_to_world(api, approach_xy)
    # Re-detect after moving.  This prevents stale search evidence becoming a
    # ground-truth shortcut and makes the pose estimate camera-derived twice.
    detection, bottle_world = camera_detection(api, detector, artifacts, 1)
    state = api.observation()
    target_arm = world_to_arm_base_mm(state, bottle_world)
    pre_pick = [target_arm[0], target_arm[1], max(target_arm[2] + 110.0, PICKUP_HEIGHT_MM + 110.0)]
    pick = [target_arm[0], target_arm[1], PICKUP_HEIGHT_MM]
    state_machine.transition(EpisodeState.PICKUP, "approach reached and bottle re-detected")
    # Private native-video capture starts here, before the descent.  This is a
    # local file cue only; the robot policy remains autonomy-API-only.
    write_stage(stage_log, "pickup")
    move_arm(api, pre_pick, "pre-pick")
    move_arm(api, pick, "pick")
    api.post("/api/sim/interact")
    move_arm(api, pre_pick, "lift")
    bin_approach_xy, _bin_approach_yaw = pickup_approach_pose(state, [bin_xy[0], bin_xy[1], 0.0])
    state_machine.transition(EpisodeState.DRIVE_TO_BIN, "pickup interaction accepted")
    # This is only a local cue for the private video launcher.  The policy
    # still controls the robot solely through /api/autonomy/*.
    write_stage(stage_log, "drive-to-bin")
    drive_to_world(api, bin_approach_xy)
    state = api.observation()
    drop_arm = world_to_arm_base_mm(state, [bin_xy[0], bin_xy[1], DROP_HEIGHT_MM / 1000.0])
    state_machine.transition(EpisodeState.DROP_TO_BIN, "bin approach reached")
    move_arm(api, drop_arm, "drop")
    api.post("/api/sim/interact")
    # Completion is deliberately not observed by this policy.  The launcher
    # records the private RobotDreams state and a separate judge decides whether
    # the detached bottle subsequently settled in the bin.
    state_machine.transition(EpisodeState.SEARCH, "drop issued; next cleaning cycle may begin")
    return {
        "detection": detection.__dict__,
        "projectedBottleWorldM": bottle_world,
        "stateMachine": state_machine.summary(),
    }


def wait_ready(api: RuntimeApi) -> None:
    deadline = time.monotonic() + 60.0
    while time.monotonic() < deadline:
        try:
            api.observation()
            return
        except (OSError, RuntimeError):
            time.sleep(0.1)
    raise RuntimeError("runtime did not become ready")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True, help="YOLO bottle detector checkpoint")
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--base-url", required=True, help="restricted runtime HTTP endpoint")
    parser.add_argument("--bin-x", type=float, required=True)
    parser.add_argument("--bin-y", type=float, required=True)
    parser.add_argument("--stage-log", type=Path,
                        help="optional local launcher cues; never sent to the runtime")
    parser.add_argument("--state-log", type=Path,
                        help="required-by-default append-only V1 state-machine transition log")
    parser.add_argument("--bottle-class-index", type=int, default=0)
    parser.add_argument("--confidence", type=float, default=DEFAULT_DETECTION_CONFIDENCE)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.artifacts.exists() and any(args.artifacts.iterdir()):
        print("refusing non-empty artifacts directory", file=sys.stderr)
        return 2
    args.artifacts.mkdir(parents=True, exist_ok=True)
    bin_xy = [args.bin_x, args.bin_y]
    write_json(args.artifacts / "policy.json", {
        "schema": "puppybot.bottle-yolo.policy.v2",
        "model": str(args.model),
        "binWorldM": bin_xy,
        "observationApi": "/api/autonomy/",
        "stateMachine": [state.value for state in EpisodeState],
    })
    log = args.artifacts / "commands.jsonl"
    result: dict[str, Any] = {}
    error: str | None = None
    try:
        if not 0.0 < args.confidence <= 1.0:
            raise RuntimeError("YOLO confidence must be in (0, 1]")
        detector = YoloDetector(args.model, args.bottle_class_index, args.confidence)
        api = RuntimeApi(args.base_url, log)
        wait_ready(api)
        state_log = args.state_log or args.artifacts / "state-transitions.jsonl"
        result = run(api, detector, args.artifacts, bin_xy, args.stage_log, EpisodeStateMachine(state_log))
    except Exception as exception:
        error = str(exception)
    validation = {"schema": "puppybot.bottle-yolo.policy-result.v1", "success": error is None,
                  "error": error, "result": result}
    write_json(args.artifacts / "policy-result.json", validation)
    print(json.dumps(validation, indent=2))
    return 0 if error is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
