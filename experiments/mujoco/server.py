#!/usr/bin/env python3
"""Serve the PuppyBot MuJoCo room through a loopback visual-control API."""

import argparse
import base64
from http.server import BaseHTTPRequestHandler, HTTPServer
import io
import ipaddress
import json
import math
import os
from pathlib import Path
import sys
import threading
import time
from urllib.parse import parse_qs, urlsplit

if sys.platform.startswith("linux"):
    os.environ.setdefault("MUJOCO_GL", "egl")

from firmware_core import FirmwareCore
from run import ARM_BASE_YAW_RAD, JOINT_NAMES


CAMERA_WIDTH = 640
CAMERA_HEIGHT = 480
MAX_REQUEST_BYTES = 4096
MAX_TCP_JOG_MM = 25.0
GRASP_TOLERANCE_M = 0.055
CONTROL_PAGE = Path(__file__).with_name("control.html")
BASE_COMMAND_TIMEOUT_SEC = 0.25
BASE_POSITION_LIMIT_M = 0.8
MAX_BASE_LINEAR_MPS = 0.35
MAX_BASE_ANGULAR_RADPS = 1.8


class ApiProblem(ValueError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class PuppybotMujocoSimulation:
    def __init__(self, model_path, config_path, firmware_library=None):
        import mujoco

        self.mujoco = mujoco
        self.model = mujoco.MjModel.from_xml_path(str(model_path))
        self.data = mujoco.MjData(self.model)
        self.renderer = mujoco.Renderer(
            self.model,
            height=CAMERA_HEIGHT,
            width=CAMERA_WIDTH,
        )
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.worker = None
        self.firmware = FirmwareCore(config_path, firmware_library)
        self.last_firmware_update_ms = -20
        self.bottle_attached = False
        self.observation_sequence = 0
        self.base_linear_mps = 0.0
        self.base_angular_radps = 0.0
        self.base_command_until_sec = 0.0
        self.base_pose = [0.0, 0.0, 0.0]
        self.reset()

    def reset(self):
        with self.lock:
            self.mujoco.mj_resetDataKeyframe(self.model, self.data, 0)
            self.bottle_attached = False
            self.observation_sequence = 0
            self.base_linear_mps = 0.0
            self.base_angular_radps = 0.0
            self.base_command_until_sec = 0.0
            self.base_pose = list(self._base_pose())
            self.mujoco.mj_forward(self.model, self.data)
            self.firmware.reset()
            self.last_firmware_update_ms = -20
            self._update_firmware_locked(force=True)

    def _joint_pose(self):
        return tuple(float(self.data.joint(name).qpos[0]) for name in JOINT_NAMES)

    def _base_pose(self):
        return tuple(
            float(self.data.joint(name).qpos[0])
            for name in ("base_x", "base_y", "base_yaw")
        )

    def _tcp_world(self):
        return tuple(float(value) for value in self.data.site("tcp").xpos)

    def _bottle_grasp_world(self):
        return tuple(float(value) for value in self.data.site("bottle_grasp").xpos)

    def _follow_tcp_with_bottle(self):
        if not self.bottle_attached:
            return
        bottle_joint = self.data.joint("bottle_free")
        tcp = self.data.site("tcp").xpos
        bottle_joint.qpos[:3] = tcp
        bottle_joint.qpos[3:7] = (1.0, 0.0, 0.0, 0.0)
        bottle_joint.qvel[:] = 0.0

    def _advance_base_locked(self):
        if self.data.time >= self.base_command_until_sec:
            self.base_linear_mps = 0.0
            self.base_angular_radps = 0.0
        timestep = float(self.model.opt.timestep)
        yaw = self.base_pose[2]
        self.base_pose[0] = max(
            -BASE_POSITION_LIMIT_M,
            min(BASE_POSITION_LIMIT_M, self.base_pose[0] + self.base_linear_mps * math.cos(yaw) * timestep),
        )
        self.base_pose[1] = max(
            -BASE_POSITION_LIMIT_M,
            min(BASE_POSITION_LIMIT_M, self.base_pose[1] + self.base_linear_mps * math.sin(yaw) * timestep),
        )
        self.base_pose[2] = math.atan2(
            math.sin(yaw + self.base_angular_radps * timestep),
            math.cos(yaw + self.base_angular_radps * timestep),
        )
        for name, value in zip(("base_x", "base_y", "base_yaw"), self.base_pose):
            self.data.joint(name).qpos[0] = value
            self.data.joint(name).qvel[0] = 0.0

    def _restore_base_pose_locked(self):
        for name, value in zip(("base_x", "base_y", "base_yaw"), self.base_pose):
            self.data.joint(name).qpos[0] = value
            self.data.joint(name).qvel[0] = 0.0

    def _step_locked(self, steps=1):
        for _ in range(steps):
            self._update_firmware_locked()
            self._advance_base_locked()
            self.mujoco.mj_step(self.model, self.data)
            self._restore_base_pose_locked()
            self._follow_tcp_with_bottle()
        self.mujoco.mj_forward(self.model, self.data)

    def _update_firmware_locked(self, force=False):
        now_ms = round(float(self.data.time) * 1000.0)
        if not force and now_ms - self.last_firmware_update_ms < 20:
            return
        targets = self.firmware.feedback(self._joint_pose(), now_ms)
        self.data.ctrl[:] = targets
        self.last_firmware_update_ms = now_ms

    def step_for_test(self, steps):
        with self.lock:
            self._step_locked(steps)

    def start(self):
        if self.worker is not None:
            return
        self.worker = threading.Thread(target=self._run, name="puppybot-mujoco", daemon=True)
        self.worker.start()

    def _run(self):
        timestep = float(self.model.opt.timestep)
        deadline = time.monotonic()
        while not self.stop_event.is_set():
            with self.lock:
                self._step_locked()
            deadline += timestep
            remaining = deadline - time.monotonic()
            if remaining > 0.0:
                self.stop_event.wait(remaining)
            elif remaining < -0.1:
                deadline = time.monotonic()

    def close(self):
        self.stop_event.set()
        if self.worker is not None:
            self.worker.join(timeout=2.0)
        self.renderer.close()
        self.firmware.close()

    def state(self):
        with self.lock:
            return self._state_locked()

    def _state_locked(self):
        actual = self._joint_pose()
        target = tuple(float(value) for value in self.data.ctrl)
        velocity = [float(self.data.joint(name).qvel[0]) for name in JOINT_NAMES]
        return {
            "schema": "puppybot.mujoco.state.v1",
            "controller": "puppybot-core",
            "simulationTimeSec": float(self.data.time),
            "base": {
                "pose": {
                    "xM": self.base_pose[0],
                    "yM": self.base_pose[1],
                    "yawRad": self.base_pose[2],
                },
                "command": {
                    "linearMps": self.base_linear_mps,
                    "angularRadps": self.base_angular_radps,
                },
            },
            "arm": {
                "jointNames": JOINT_NAMES,
                "actualJointDeg": [math.degrees(value) for value in actual],
                "targetJointDeg": [math.degrees(value) for value in target],
                "tcpWorldM": self._tcp_world(),
                "settled": max(map(abs, velocity), default=0.0) < 0.03
                and max((abs(a - b) for a, b in zip(actual, target)), default=0.0) < 0.01,
            },
            "gripper": {"bottleAttached": self.bottle_attached},
            "contacts": int(self.data.ncon),
        }

    def camera_rgba(self):
        import numpy as np

        with self.lock:
            self.mujoco.mj_forward(self.model, self.data)
            self.renderer.update_scene(self.data, camera="tcp_camera")
            rgb = self.renderer.render().copy()
            alpha = np.full((CAMERA_HEIGHT, CAMERA_WIDTH, 1), 255, dtype=np.uint8)
            rgba = np.concatenate((rgb, alpha), axis=2)
            self.observation_sequence += 1
            observation_id = self.observation_sequence
            state = self._state_locked()
        return observation_id, state, rgba

    def orbit_rgb(self, azimuth, elevation, distance):
        values = (azimuth, elevation, distance)
        if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in values):
            raise ApiProblem(400, "orbit camera values must be finite numbers")
        if not -360.0 <= azimuth <= 360.0:
            raise ApiProblem(400, "orbit azimuth must be in [-360, 360] degrees")
        if not -85.0 <= elevation <= 10.0:
            raise ApiProblem(400, "orbit elevation must be in [-85, 10] degrees")
        if not 0.3 <= distance <= 2.5:
            raise ApiProblem(400, "orbit distance must be in [0.3, 2.5] metres")

        camera = self.mujoco.MjvCamera()
        self.mujoco.mjv_defaultFreeCamera(self.model, camera)
        camera.azimuth = azimuth
        camera.elevation = elevation
        camera.distance = distance
        with self.lock:
            camera.lookat[:] = (self.base_pose[0] + 0.08, self.base_pose[1], 0.16)
            self.mujoco.mj_forward(self.model, self.data)
            self.renderer.update_scene(self.data, camera=camera)
            return self.renderer.render().copy()

    def command_tcp_jog(self, camera_delta_mm):
        import numpy as np

        if not isinstance(camera_delta_mm, list) or len(camera_delta_mm) != 3:
            raise ApiProblem(400, "cameraDeltaMm must contain [right, up, forward]")
        if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in camera_delta_mm):
            raise ApiProblem(400, "cameraDeltaMm values must be finite numbers")
        magnitude = math.sqrt(sum(float(value) ** 2 for value in camera_delta_mm))
        if magnitude <= 0.0 or magnitude > MAX_TCP_JOG_MM:
            raise ApiProblem(400, f"cameraDeltaMm magnitude must be in (0, {MAX_TCP_JOG_MM}] mm")

        with self.lock:
            self.mujoco.mj_forward(self.model, self.data)
            camera_rotation = self.data.camera("tcp_camera").xmat.reshape(3, 3).copy()
            camera_vector_m = np.asarray(
                [camera_delta_mm[0], camera_delta_mm[1], -camera_delta_mm[2]],
                dtype=float,
            ) / 1000.0
            world_delta = camera_rotation @ camera_vector_m
            target_world = np.asarray(self._tcp_world()) + world_delta
            if target_world[2] < 0.02:
                raise ApiProblem(409, "TCP jog would cross the room floor clearance")
            arm_base_yaw = self.base_pose[2] + ARM_BASE_YAW_RAD
            cos_yaw = math.cos(arm_base_yaw)
            sin_yaw = math.sin(arm_base_yaw)
            arm_delta_mm = (
                world_delta[0] * cos_yaw + world_delta[1] * sin_yaw,
                -world_delta[0] * sin_yaw + world_delta[1] * cos_yaw,
                world_delta[2],
            )
            arm_delta_mm = tuple(float(value) * 1000.0 for value in arm_delta_mm)
            now_ms = round(float(self.data.time) * 1000.0)
            try:
                self.firmware.feedback(self._joint_pose(), now_ms)
                self.firmware.move_tcp_relative(arm_delta_mm, now_ms)
                target_pose = self.firmware.feedback(self._joint_pose(), now_ms)
            except ValueError as error:
                raise ApiProblem(409, str(error)) from error
            self.data.ctrl[:] = target_pose
            return {
                "ok": True,
                "frame": "tcp_camera",
                "cameraAxes": ["image-right", "image-up", "optical-forward"],
                "cameraDeltaMm": camera_delta_mm,
                "targetTcpWorldM": tuple(float(value) for value in target_world),
                "targetJointDeg": [math.degrees(value) for value in target_pose],
                "controller": "puppybot-core",
            }

    def command_base_drive(self, linear_mps, angular_radps):
        values = (linear_mps, angular_radps)
        if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in values):
            raise ApiProblem(400, "base drive values must be finite numbers")
        if abs(linear_mps) > MAX_BASE_LINEAR_MPS:
            raise ApiProblem(400, f"linearMps magnitude must not exceed {MAX_BASE_LINEAR_MPS}")
        if abs(angular_radps) > MAX_BASE_ANGULAR_RADPS:
            raise ApiProblem(400, f"angularRadps magnitude must not exceed {MAX_BASE_ANGULAR_RADPS}")
        with self.lock:
            self.base_linear_mps = float(linear_mps)
            self.base_angular_radps = float(angular_radps)
            self.base_command_until_sec = float(self.data.time) + BASE_COMMAND_TIMEOUT_SEC
        return {
            "ok": True,
            "drive": "differential",
            "linearMps": self.base_linear_mps,
            "angularRadps": self.base_angular_radps,
        }

    def stop_base(self):
        with self.lock:
            self.base_linear_mps = 0.0
            self.base_angular_radps = 0.0
            self.base_command_until_sec = float(self.data.time)
        return {"ok": True}

    def stop_arm(self):
        with self.lock:
            now_ms = round(float(self.data.time) * 1000.0)
            self.firmware.stop(now_ms)
            self.data.ctrl[:] = self.firmware.feedback(self._joint_pose(), now_ms)
        return {"ok": True}

    def close_gripper(self):
        with self.lock:
            self.mujoco.mj_forward(self.model, self.data)
            distance_m = math.dist(self._tcp_world(), self._bottle_grasp_world())
            if distance_m <= GRASP_TOLERANCE_M:
                self.bottle_attached = True
                self._follow_tcp_with_bottle()
                self.mujoco.mj_forward(self.model, self.data)
            return {
                "ok": True,
                "attached": self.bottle_attached,
                "result": "attached" if self.bottle_attached else "no-contact",
            }

    def open_gripper(self):
        with self.lock:
            self.bottle_attached = False
        return {"ok": True, "attached": False, "result": "released"}


def png_bytes(rgb):
    from PIL import Image

    output = io.BytesIO()
    Image.fromarray(rgb, mode="RGB").save(output, format="PNG")
    return output.getvalue()


class PuppybotApiHandler(BaseHTTPRequestHandler):
    server_version = "PuppybotMujoco/1"

    @property
    def simulation(self):
        return self.server.simulation

    def _json(self, status, value):
        body = json.dumps(value).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _bytes(self, status, content_type, body):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _request_json(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise ApiProblem(400, "invalid Content-Length") from error
        if length < 0 or length > MAX_REQUEST_BYTES:
            raise ApiProblem(413, f"request body exceeds {MAX_REQUEST_BYTES} bytes")
        try:
            value = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError as error:
            raise ApiProblem(400, "request body must be valid JSON") from error
        if not isinstance(value, dict):
            raise ApiProblem(400, "request body must be a JSON object")
        return value

    def do_GET(self):
        request_url = urlsplit(self.path)
        path = request_url.path
        try:
            if path == "/health":
                self._json(200, {"ok": True, "backend": "mujoco"})
                return
            if path == "/":
                self._bytes(200, "text/html; charset=utf-8", CONTROL_PAGE.read_bytes())
                return
            if path == "/api/state":
                self._json(200, self.simulation.state())
                return
            if path in ("/api/camera/tcp", "/api/camera/tcp/raw"):
                observation_id, state, rgba = self.simulation.camera_rgba()
                if path.endswith("/raw"):
                    self._json(200, {
                        "schema": "puppybot.mujoco.tcp-frame.v1",
                        "id": observation_id,
                        "state": state,
                        "image": {
                            "pixelFormat": "rgba8",
                            "width": CAMERA_WIDTH,
                            "height": CAMERA_HEIGHT,
                            "strideBytes": CAMERA_WIDTH * 4,
                            "sizeBytes": int(rgba.nbytes),
                            "base64": base64.b64encode(rgba.tobytes()).decode("ascii"),
                        },
                    })
                else:
                    self._bytes(200, "image/png", png_bytes(rgba[..., :3]))
                return
            if path == "/api/camera/orbit":
                query = parse_qs(request_url.query)
                try:
                    azimuth = float(query.get("azimuth", ("135",))[0])
                    elevation = float(query.get("elevation", ("-25",))[0])
                    distance = float(query.get("distance", ("0.8",))[0])
                except (TypeError, ValueError) as error:
                    raise ApiProblem(400, "invalid orbit camera query") from error
                self._bytes(
                    200,
                    "image/png",
                    png_bytes(self.simulation.orbit_rgb(azimuth, elevation, distance)),
                )
                return
            raise ApiProblem(404, "unknown endpoint")
        except ApiProblem as error:
            self._json(error.status, {"ok": False, "error": str(error)})
        except Exception as error:
            self._json(500, {"ok": False, "error": str(error)})

    def do_POST(self):
        path = urlsplit(self.path).path
        try:
            body = self._request_json()
            if path == "/api/arm/tcp-jog":
                self._json(200, self.simulation.command_tcp_jog(body.get("cameraDeltaMm")))
                return
            if path == "/api/arm/stop":
                self._json(200, self.simulation.stop_arm())
                return
            if path == "/api/base/drive":
                self._json(
                    200,
                    self.simulation.command_base_drive(
                        body.get("linearMps"),
                        body.get("angularRadps"),
                    ),
                )
                return
            if path == "/api/base/stop":
                self._json(200, self.simulation.stop_base())
                return
            if path == "/api/gripper/close":
                self._json(200, self.simulation.close_gripper())
                return
            if path == "/api/gripper/open":
                self._json(200, self.simulation.open_gripper())
                return
            if path == "/api/reset":
                self.simulation.reset()
                self._json(200, {"ok": True})
                return
            raise ApiProblem(404, "unknown endpoint")
        except ApiProblem as error:
            self._json(error.status, {"ok": False, "error": str(error)})
        except Exception as error:
            self._json(500, {"ok": False, "error": str(error)})

    def log_message(self, message, *args):
        print(f"{self.client_address[0]} - {message % args}")


def argument_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1", help="loopback bind address")
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument(
        "--model",
        type=Path,
        default=Path(__file__).with_name("puppybot_arm.xml"),
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).parents[2] / "puppybot" / "runtime" / "puppybot.sim.json",
        help="Puppybot calibration used by the firmware-core bridge",
    )
    parser.add_argument(
        "--firmware-library",
        type=Path,
        help="override the compiled puppybot-core bridge library",
    )
    return parser


def main():
    args = argument_parser().parse_args()
    try:
        address = ipaddress.ip_address(args.host)
    except ValueError as error:
        raise SystemExit("--host must be a numeric loopback address") from error
    if not address.is_loopback:
        raise SystemExit("the experimental camera/control API may bind only to loopback")
    if not 1 <= args.port <= 65535:
        raise SystemExit("--port must be in [1, 65535]")

    server = HTTPServer((args.host, args.port), PuppybotApiHandler)
    try:
        simulation = PuppybotMujocoSimulation(args.model, args.config, args.firmware_library)
    except Exception:
        server.server_close()
        raise
    server.simulation = simulation
    simulation.start()
    print(f"PuppyBot MuJoCo API listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever(poll_interval=0.1)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        simulation.close()


if __name__ == "__main__":
    main()
