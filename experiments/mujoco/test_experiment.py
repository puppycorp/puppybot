import importlib.util
import math
from pathlib import Path
import unittest


EXPERIMENT_DIR = Path(__file__).parent
SPEC = importlib.util.spec_from_file_location("puppybot_mujoco", EXPERIMENT_DIR / "run.py")
EXPERIMENT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EXPERIMENT)


class AnalyticKinematicsTests(unittest.TestCase):
    def test_arm_to_world_keeps_arm_origin(self):
        self.assertEqual(
            EXPERIMENT.arm_to_world((0.0, 0.0, 0.0)),
            EXPERIMENT.ARM_BASE_POSITION_M,
        )

    def test_tcp_is_finite_for_ready_pose(self):
        tcp = EXPERIMENT.arm_tcp_m(map(math.radians, (0.0, 45.0, 135.0, 0.0)))
        self.assertTrue(all(math.isfinite(value) for value in tcp))

    def test_pose_parser_requires_four_joints(self):
        with self.assertRaises(Exception):
            EXPERIMENT.parse_pose_degrees(("0", "45", "135"))


@unittest.skipUnless(importlib.util.find_spec("mujoco"), "mujoco is not installed")
class MujocoModelTests(unittest.TestCase):
    def test_model_tcp_matches_puppybot_analytic_fk(self):
        import mujoco

        model = mujoco.MjModel.from_xml_path(str(EXPERIMENT_DIR / "puppybot_arm.xml"))
        data = mujoco.MjData(model)
        mujoco.mj_resetDataKeyframe(model, data, 0)
        poses_degrees = (
            (0.0, 45.0, 135.0, 0.0),
            (20.0, 60.0, 120.0, -15.0),
            (-20.0, 30.0, 180.0, 30.0),
        )

        for pose_degrees in poses_degrees:
            with self.subTest(pose_degrees=pose_degrees):
                pose = tuple(map(math.radians, pose_degrees))
                for name, value in zip(EXPERIMENT.JOINT_NAMES, pose):
                    data.joint(name).qpos[0] = value
                mujoco.mj_forward(model, data)

                expected = EXPERIMENT.arm_to_world(EXPERIMENT.arm_tcp_m(pose))
                observed = tuple(float(value) for value in data.site("tcp").xpos)

                self.assertLess(1000.0 * math.dist(expected, observed), 0.01)


if __name__ == "__main__":
    unittest.main()
