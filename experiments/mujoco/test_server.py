import contextlib
import importlib.util
import io
import math
import os
from pathlib import Path
import sys
import unittest


EXPERIMENT_DIR = Path(__file__).parent
REPOSITORY_ROOT = EXPERIMENT_DIR.parents[1]
os.environ.setdefault("MUJOCO_GL", "egl")
sys.path.insert(0, str(EXPERIMENT_DIR))

from controller import centering_jog, run as run_visual_servo
from firmware_core import default_library_path


MUJOCO_AVAILABLE = importlib.util.find_spec("mujoco") is not None
FIRMWARE_CORE_AVAILABLE = default_library_path().is_file()


class FakeDetection:
    def __init__(self, center):
        self.center = center


class VisualControllerTests(unittest.TestCase):
    def test_centered_detection_needs_no_lateral_jog(self):
        detection = FakeDetection((319.5, 239.5))
        self.assertIsNone(centering_jog(detection, 640, 480, 14.0))

    def test_detection_below_and_right_moves_camera_down_and_right(self):
        detection = FakeDetection((480.0, 360.0))
        right, up, forward = centering_jog(detection, 640, 480, 14.0)
        self.assertGreater(right, 0.0)
        self.assertLess(up, 0.0)
        self.assertEqual(forward, 0.0)
        self.assertLessEqual(math.hypot(right, up), 18.0)


@unittest.skipUnless(
    MUJOCO_AVAILABLE and FIRMWARE_CORE_AVAILABLE,
    "mujoco and the compiled firmware-core bridge are required",
)
class MujocoFirmwareSimulationTests(unittest.TestCase):
    def setUp(self):
        from server import PuppybotMujocoSimulation

        self.simulation = PuppybotMujocoSimulation(
            EXPERIMENT_DIR / "puppybot_arm.xml",
            REPOSITORY_ROOT / "puppybot" / "runtime" / "puppybot.sim.json",
        )

    def tearDown(self):
        self.simulation.close()

    def test_camera_and_state_identify_firmware_controller(self):
        observation_id, state, rgba = self.simulation.camera_rgba()
        self.assertEqual(observation_id, 1)
        self.assertEqual(state["controller"], "puppybot-core")
        self.assertEqual(rgba.shape, (480, 640, 4))

    def test_orbit_camera_renders_external_scene(self):
        rgb = self.simulation.orbit_rgb(135.0, -25.0, 0.8)
        self.assertEqual(rgb.shape, (480, 640, 3))

    def test_camera_relative_jog_moves_through_firmware_core(self):
        import numpy as np

        before = self.simulation.state()["arm"]["tcpWorldM"]
        with self.simulation.lock:
            camera_right = self.simulation.data.camera("tcp_camera").xmat.reshape(3, 3)[:, 0].copy()
        response = self.simulation.command_tcp_jog([5.0, 0.0, 0.0])
        self.simulation.step_for_test(1000)
        after = self.simulation.state()["arm"]["tcpWorldM"]
        displacement = np.asarray(after) - np.asarray(before)

        self.assertEqual(response["controller"], "puppybot-core")
        self.assertGreater(float(displacement @ camera_right), 0.003)
        self.assertLess(abs(after[2] - before[2]), 0.005)

    def test_base_drive_moves_chassis_and_attached_arm_then_deadman_stops(self):
        before_tcp = self.simulation.state()["arm"]["tcpWorldM"]
        response = self.simulation.command_base_drive(0.2, 0.0)
        self.simulation.step_for_test(300)
        stopped_state = self.simulation.state()
        stopped_x = stopped_state["base"]["pose"]["xM"]
        self.simulation.step_for_test(100)
        final_state = self.simulation.state()

        self.assertEqual(response["drive"], "differential")
        self.assertGreater(stopped_x, 0.045)
        self.assertAlmostEqual(final_state["base"]["pose"]["xM"], stopped_x)
        self.assertEqual(final_state["base"]["command"]["linearMps"], 0.0)
        self.assertGreater(final_state["arm"]["tcpWorldM"][0] - before_tcp[0], 0.045)

    def test_base_drive_turns_in_place(self):
        self.simulation.command_base_drive(0.0, 1.0)
        self.simulation.step_for_test(100)
        pose = self.simulation.state()["base"]["pose"]

        self.assertAlmostEqual(pose["xM"], 0.0)
        self.assertAlmostEqual(pose["yM"], 0.0)
        self.assertGreater(pose["yawRad"], 0.19)

    def test_virtual_gripper_can_attach_floor_bottle_after_core_jogs(self):
        import numpy as np

        self.simulation.step_for_test(100)
        attached = False
        for _ in range(24):
            with self.simulation.lock:
                self.simulation.mujoco.mj_forward(
                    self.simulation.model,
                    self.simulation.data,
                )
                world_delta = np.asarray(self.simulation._bottle_grasp_world()) - np.asarray(
                    self.simulation._tcp_world()
                )
                camera_rotation = self.simulation.data.camera("tcp_camera").xmat.reshape(3, 3).copy()
            if np.linalg.norm(world_delta) < 0.044:
                attached = self.simulation.close_gripper()["attached"]
                break
            local_delta = camera_rotation.T @ world_delta
            camera_delta_mm = np.asarray(
                [local_delta[0], local_delta[1], -local_delta[2]]
            ) * 1000.0
            magnitude = np.linalg.norm(camera_delta_mm)
            if magnitude > 18.0:
                camera_delta_mm *= 18.0 / magnitude
            self.simulation.command_tcp_jog(camera_delta_mm.tolist())
            self.simulation.step_for_test(600)

        self.assertTrue(attached)

    def test_camera_only_loop_centers_descends_and_lifts_bottle(self):
        import numpy as np

        class TestBlueBottleDetector:
            def __init__(self):
                self.np = np

            def detect_rgba(self, rgba):
                rgb = rgba[..., :3]
                mask = (
                    (rgb[..., 2] > 140)
                    & (rgb[..., 2] > rgb[..., 0] * 1.3)
                    & (rgb[..., 2] > rgb[..., 1] * 1.05)
                )
                y, x = np.where(mask)
                if len(x) < 20:
                    return None
                detection = FakeDetection(
                    (float((x.min() + x.max()) * 0.5), float((y.min() + y.max()) * 0.5))
                )
                detection.xyxy = tuple(map(float, (x.min(), y.min(), x.max(), y.max())))
                detection.confidence = 1.0
                detection.label = "bottle"
                return detection

        class DirectSimulationApi:
            def __init__(self, simulation):
                self.simulation = simulation

            def camera_rgba(self, _np):
                observation_id, _state, rgba = self.simulation.camera_rgba()
                return {"id": observation_id}, rgba

            def tcp_jog(self, delta):
                return self.simulation.command_tcp_jog(delta)

            def close_gripper(self):
                return self.simulation.close_gripper()

            def stop(self):
                return self.simulation.stop_arm()

            def wait_arm(self, timeout_sec=4.0):
                del timeout_sec
                self.simulation.step_for_test(600)
                return self.simulation.state()

        initial_bottle_height = self.simulation._bottle_grasp_world()[2]
        with contextlib.redirect_stdout(io.StringIO()):
            events = run_visual_servo(
                DirectSimulationApi(self.simulation),
                TestBlueBottleDetector(),
                max_iterations=60,
                center_tolerance_px=20.0,
                descent_step_mm=10.0,
                maximum_misses=3,
            )

        final_state = self.simulation.state()
        self.assertTrue(events[-1]["success"])
        self.assertTrue(final_state["gripper"]["bottleAttached"])
        self.assertGreater(
            self.simulation._bottle_grasp_world()[2],
            initial_bottle_height + 0.03,
            msg=f"final state: {final_state}; final event: {events[-1]}",
        )


if __name__ == "__main__":
    unittest.main()
