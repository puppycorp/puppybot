#!/usr/bin/env python3
"""Center on and pick up the MuJoCo bottle with Tinygrad TCP-camera detections."""

import argparse
import base64
import json
import math
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request


MAX_CAMERA_JOG_MM = 18.0
DEFAULT_CENTER_TOLERANCE_PX = 20.0
DEFAULT_DESCENT_STEP_MM = 10.0
DEFAULT_LIFT_MM = 108.0
MAX_LIFT_MM = 8.0 * MAX_CAMERA_JOG_MM
GRASP_GATE_TOLERANCE_PX = 40.0


class SimulationApi:
    def __init__(self, base_url):
        self.base_url = base_url.rstrip("/")

    def request(self, method, path, body=None):
        encoded = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + path,
            data=encoded,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=8.0) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as error:
            payload = json.loads(error.read() or b"{}")
            raise RuntimeError(f"{method} {path} failed ({error.code}): {payload}") from error

    def state(self):
        return self.request("GET", "/api/state")

    def camera_rgba(self, np):
        observation = self.request("GET", "/api/camera/tcp/raw")
        if observation.get("schema") != "puppybot.mujoco.tcp-frame.v1":
            raise RuntimeError("MuJoCo TCP camera returned an unexpected schema")
        image = observation.get("image")
        if not isinstance(image, dict) or image.get("pixelFormat") != "rgba8":
            raise RuntimeError("MuJoCo TCP camera did not return RGBA8")
        width, height = image.get("width"), image.get("height")
        size = image.get("sizeBytes")
        raw = base64.b64decode(image.get("base64", ""), validate=True)
        if not isinstance(width, int) or not isinstance(height, int) or len(raw) != size:
            raise RuntimeError("MuJoCo TCP camera returned inconsistent image dimensions")
        return observation, np.frombuffer(raw, dtype=np.uint8).reshape((height, width, 4))

    def tcp_jog(self, camera_delta_mm):
        return self.request(
            "POST",
            "/api/arm/tcp-jog",
            {"cameraDeltaMm": camera_delta_mm},
        )

    def close_gripper(self):
        return self.request("POST", "/api/gripper/close", {})

    def stop(self):
        return self.request("POST", "/api/arm/stop", {})

    def wait_arm(self, timeout_sec=4.0):
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            state = self.state()
            if state.get("arm", {}).get("settled") is True:
                return state
            time.sleep(0.04)
        raise RuntimeError("Puppybot firmware-controlled arm did not settle")


def clamp(value, limit):
    return max(-limit, min(limit, value))


def detection_center_error(detection, width, height):
    center_x, center_y = detection.center
    return (
        center_x - (width - 1.0) * 0.5,
        center_y - (height - 1.0) * 0.5,
    )


def centering_jog(detection, width, height, tolerance_px):
    error_x, error_y = detection_center_error(detection, width, height)
    if math.hypot(error_x, error_y) <= tolerance_px:
        return None
    # Convert normalized image error to a bounded camera-plane correction.
    # Positive camera X is image-right; positive camera Y is image-up.
    right_mm = clamp(40.0 * error_x / width, MAX_CAMERA_JOG_MM)
    up_mm = clamp(-40.0 * error_y / height, MAX_CAMERA_JOG_MM)
    magnitude = math.hypot(right_mm, up_mm)
    if magnitude > MAX_CAMERA_JOG_MM:
        scale = MAX_CAMERA_JOG_MM / magnitude
        right_mm *= scale
        up_mm *= scale
    return [right_mm, up_mm, 0.0]


def tinygrad_detector(checkpoint, threshold):
    scenarios = Path(__file__).resolve().parents[2] / "puppybot" / "scenarios"
    if str(scenarios) not in sys.path:
        sys.path.insert(0, str(scenarios))
    try:
        from bottle_to_bin_yolo import TinygradV6Detector
    except ImportError as error:
        raise RuntimeError(
            "Tinygrad detector dependencies are unavailable; initialize examples/tinygrad "
            "and install experiments/mujoco/requirements.txt"
        ) from error
    return TinygradV6Detector(checkpoint, threshold)


def lift_after_grasp(api, lift_mm):
    steps = []
    remaining = lift_mm
    while remaining > 0.0:
        distance = min(MAX_CAMERA_JOG_MM, remaining)
        step = [0.0, 0.0, -distance]
        response = api.tcp_jog(step)
        api.wait_arm()
        steps.append({"cameraDeltaMm": step, "response": response})
        remaining -= distance
    return steps


def run(
    api,
    detector,
    max_iterations,
    center_tolerance_px,
    descent_step_mm,
    maximum_misses,
    lift_mm=DEFAULT_LIFT_MM,
):
    misses = 0
    events = []
    for sequence in range(max_iterations):
        observation, rgba = api.camera_rgba(detector.np)
        detection = detector.detect_rgba(rgba)
        if detection is None:
            misses += 1
            event = {"sequence": sequence, "detection": None, "action": "stop"}
            events.append(event)
            print(json.dumps(event), flush=True)
            api.stop()
            if misses >= maximum_misses:
                raise RuntimeError("Tinygrad lost the bottle; refusing blind arm motion")
            time.sleep(0.08)
            continue
        misses = 0
        height, width = rgba.shape[:2]
        center_error = detection_center_error(detection, width, height)
        if math.hypot(*center_error) <= GRASP_GATE_TOLERANCE_PX:
            grasp = api.close_gripper()
            if grasp.get("attached") is True:
                lift_steps = lift_after_grasp(api, lift_mm)
                event = {
                    "sequence": sequence,
                    "observationId": observation.get("id"),
                    "detection": detection.__dict__,
                    "action": {"kind": "grasp-and-lift", "liftSteps": lift_steps},
                    "success": True,
                }
                events.append(event)
                print(json.dumps(event), flush=True)
                return events
        jog = centering_jog(detection, width, height, center_tolerance_px)
        if jog is not None:
            action_kind = "center"
            if math.hypot(jog[0], jog[1]) <= 8.0:
                jog[2] = descent_step_mm
                action_kind = "center-and-descend"
            response = api.tcp_jog(jog)
            action = {"kind": action_kind, "cameraDeltaMm": jog, "response": response}
        else:
            response = api.tcp_jog([0.0, 0.0, descent_step_mm])
            action = {"kind": "descend", "cameraDeltaMm": [0.0, 0.0, descent_step_mm], "response": response}
        event = {
            "sequence": sequence,
            "observationId": observation.get("id"),
            "detection": detection.__dict__,
            "action": action,
        }
        events.append(event)
        print(json.dumps(event), flush=True)
        api.wait_arm()
    raise RuntimeError(f"pickup did not finish within {max_iterations} visual corrections")


def argument_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8090")
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=Path(__file__).resolve().parents[2]
        / "workdir"
        / "training-dataset"
        / "tinygrad-v6-grid-018"
        / "bottle-v6-grid.safetensors",
    )
    parser.add_argument("--threshold", type=float, default=0.40)
    parser.add_argument("--max-iterations", type=int, default=80)
    parser.add_argument("--maximum-misses", type=int, default=3)
    parser.add_argument("--center-tolerance-px", type=float, default=DEFAULT_CENTER_TOLERANCE_PX)
    parser.add_argument("--descent-step-mm", type=float, default=DEFAULT_DESCENT_STEP_MM)
    parser.add_argument("--lift-mm", type=float, default=DEFAULT_LIFT_MM)
    return parser


def main():
    args = argument_parser().parse_args()
    if not args.checkpoint.is_file():
        raise SystemExit(f"Tinygrad checkpoint does not exist: {args.checkpoint}")
    if not 0.0 < args.threshold <= 1.0:
        raise SystemExit("--threshold must be in (0, 1]")
    if args.max_iterations <= 0 or args.maximum_misses <= 0:
        raise SystemExit("iteration and miss limits must be positive")
    if not 0.0 < args.descent_step_mm <= MAX_CAMERA_JOG_MM:
        raise SystemExit(f"--descent-step-mm must be in (0, {MAX_CAMERA_JOG_MM}]")
    if not 0.0 < args.lift_mm <= MAX_LIFT_MM:
        raise SystemExit(f"--lift-mm must be in (0, {MAX_LIFT_MM}]")

    api = SimulationApi(args.base_url)
    detector = tinygrad_detector(args.checkpoint, args.threshold)
    try:
        events = run(
            api,
            detector,
            args.max_iterations,
            args.center_tolerance_px,
            args.descent_step_mm,
            args.maximum_misses,
            args.lift_mm,
        )
    except Exception:
        try:
            api.stop()
        except Exception:
            pass
        raise
    print(json.dumps({"success": True, "visualCorrections": len(events)}, indent=2))


if __name__ == "__main__":
    main()
