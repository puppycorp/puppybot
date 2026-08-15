"""ctypes bridge to the same PuppyArm controller used by the Rust firmware."""

import ctypes
import json
import math
from pathlib import Path
import sys


JOINT_COUNT = 4


class FirmwareJointConfig(ctypes.Structure):
    _fields_ = (
        ("servo_id", ctypes.c_uint8),
        ("angle_sign", ctypes.c_int8),
        ("drive_sign", ctypes.c_int8),
        ("limit_enabled", ctypes.c_uint8),
        ("tick_min", ctypes.c_int32),
        ("tick_max", ctypes.c_int32),
        ("reference_tick", ctypes.c_int32),
        ("reference_angle_rad", ctypes.c_double),
    )


def library_name():
    if sys.platform == "darwin":
        return "libpuppybot_mujoco_firmware_core.dylib"
    if sys.platform == "win32":
        return "puppybot_mujoco_firmware_core.dll"
    return "libpuppybot_mujoco_firmware_core.so"


def default_library_path():
    return Path(__file__).with_name("firmware-core") / "target" / "debug" / library_name()


class FirmwareCore:
    def __init__(self, config_path, library_path=None):
        self.config_path = Path(config_path)
        self.library_path = Path(library_path) if library_path else default_library_path()
        if not self.library_path.is_file():
            raise RuntimeError(
                "Puppybot firmware-core bridge is not built; run: cargo build "
                "--manifest-path experiments/mujoco/firmware-core/Cargo.toml"
            )
        self.library = ctypes.CDLL(str(self.library_path))
        self._configure_abi()
        self.handle = None
        self.reset()

    def _configure_abi(self):
        joint_pointer = ctypes.POINTER(FirmwareJointConfig)
        double_pointer = ctypes.POINTER(ctypes.c_double)
        self.library.puppybot_arm_new.argtypes = (joint_pointer, ctypes.c_size_t)
        self.library.puppybot_arm_new.restype = ctypes.c_void_p
        self.library.puppybot_arm_free.argtypes = (ctypes.c_void_p,)
        self.library.puppybot_arm_feedback.argtypes = (
            ctypes.c_void_p,
            double_pointer,
            ctypes.c_uint64,
            double_pointer,
        )
        self.library.puppybot_arm_feedback.restype = ctypes.c_int32
        self.library.puppybot_arm_move_tcp_relative.argtypes = (
            ctypes.c_void_p,
            ctypes.c_double,
            ctypes.c_double,
            ctypes.c_double,
            ctypes.c_uint64,
        )
        self.library.puppybot_arm_move_tcp_relative.restype = ctypes.c_int32
        self.library.puppybot_arm_stop.argtypes = (ctypes.c_void_p, ctypes.c_uint64)
        self.library.puppybot_arm_stop.restype = ctypes.c_int32

    def _configs(self):
        raw = json.loads(self.config_path.read_text(encoding="utf-8"))
        joints = raw.get("arm", {}).get("joints")
        if not isinstance(joints, list) or len(joints) != JOINT_COUNT:
            raise RuntimeError("Puppybot simulation config must contain four arm joints")
        values = []
        for joint in joints:
            values.append(FirmwareJointConfig(
                servo_id=int(joint["servo_id"]),
                angle_sign=int(joint["angle_sign"]),
                drive_sign=int(joint["drive_sign"]),
                limit_enabled=int(bool(joint["limit_enabled"])),
                tick_min=int(joint["tick_min"]),
                tick_max=int(joint["tick_max"]),
                reference_tick=int(joint["reference_tick"]),
                reference_angle_rad=math.radians(float(joint["reference_angle_deg"])),
            ))
        return (FirmwareJointConfig * JOINT_COUNT)(*values)

    def reset(self):
        if self.handle:
            self.library.puppybot_arm_free(self.handle)
        configs = self._configs()
        self.handle = self.library.puppybot_arm_new(configs, JOINT_COUNT)
        if not self.handle:
            raise RuntimeError("Puppybot firmware-core rejected the simulation calibration")

    def feedback(self, angles, now_ms):
        if len(angles) != JOINT_COUNT or not all(math.isfinite(value) for value in angles):
            raise ValueError("firmware feedback requires four finite joint angles")
        inputs = (ctypes.c_double * JOINT_COUNT)(*angles)
        targets = (ctypes.c_double * JOINT_COUNT)()
        result = self.library.puppybot_arm_feedback(self.handle, inputs, now_ms, targets)
        if result != 0:
            raise RuntimeError(f"Puppybot firmware-core feedback failed ({result})")
        return tuple(targets)

    def move_tcp_relative(self, delta_mm, now_ms):
        result = self.library.puppybot_arm_move_tcp_relative(
            self.handle,
            *delta_mm,
            now_ms,
        )
        if result != 0:
            reasons = {
                10: "target is geometrically unreachable",
                11: "target exceeds calibrated joint limits",
                12: "joint feedback is unavailable",
                13: "relative jog is invalid",
            }
            reason = reasons.get(result, f"controller error {result}")
            raise ValueError(f"Puppybot firmware-core rejected the relative TCP jog: {reason}")

    def stop(self, now_ms):
        result = self.library.puppybot_arm_stop(self.handle, now_ms)
        if result != 0:
            raise RuntimeError(f"Puppybot firmware-core stop failed ({result})")

    def close(self):
        if self.handle:
            self.library.puppybot_arm_free(self.handle)
            self.handle = None

    def __del__(self):
        self.close()
