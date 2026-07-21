#!/usr/bin/env python3
"""Regression checks for the dynamic PuppyBot bottle-collection fixture."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCENARIOS = Path(__file__).parent
TEMPLATE = SCENARIOS / "bottle_to_bin.robotdreams.template.json"
RUNNER = SCENARIOS / "run_bottle_to_bin_episode.py"
SPEC = importlib.util.spec_from_file_location("run_bottle_to_bin_episode", RUNNER)
assert SPEC is not None and SPEC.loader is not None
episode = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(episode)


class PhysicsFixtureTests(unittest.TestCase):
    def test_dynamic_vehicle_profile_is_complete(self) -> None:
        project = json.loads(TEMPLATE.read_text(encoding="utf-8"))
        vehicle = project["robots"][0]["physics"]["vehicle"]

        self.assertEqual(vehicle["mode"], "dynamic")
        for key in (
            "massKg",
            "maxWheelSpeedMps",
            "linearDamping",
            "angularDamping",
            "wheelbaseM",
            "trackWidthM",
            "maxDriveForceN",
            "lateralGripNPerMps",
            "steeringResponseDegPerSec",
        ):
            self.assertGreater(vehicle[key], 0.0, key)
        for key in (
            "wheelRadiusM",
            "gearRatio",
            "stallTorqueNm",
            "noLoadRpm",
            "brakeTorqueNm",
            "rollingResistanceN",
        ):
            self.assertGreater(vehicle["motor"][key], 0.0, key)
        self.assertEqual(vehicle["centerOfMass"], [0.0, 0.0, 0.06])
        self.assertEqual(vehicle["colliders"], [])
        profile_path = TEMPLATE.parent / vehicle["collisionProfile"]
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        self.assertEqual(profile["generation"]["tool"], "pge-collision")
        self.assertEqual(profile["generation"]["inputFrame"], "lowerbody")
        self.assertEqual(profile["generation"]["outputFrame"], "puppybot root")
        self.assertEqual(len(profile["colliders"]), 4)
        self.assertEqual(profile["vehicleParameters"]["centerOfMass"], vehicle["centerOfMass"])
        self.assertEqual(profile["vehicleParameters"]["maxWheelSpeedMps"], vehicle["maxWheelSpeedMps"])
        self.assertEqual(profile["vehicleParameters"]["motor"], vehicle["motor"])

    def test_seeded_fixture_preserves_vehicle_and_repositions_bin_walls(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Path(temporary) / "seeded-project.json"
            episode.build_fixture(TEMPLATE, fixture, seed=7)
            project = json.loads(fixture.read_text(encoding="utf-8"))

        vehicle = project["robots"][0]["physics"]["vehicle"]
        self.assertEqual(vehicle["mode"], "dynamic")
        self.assertTrue(Path(vehicle["collisionProfile"]).is_file())
        self.assertTrue(Path(project["robots"][0]["physics"]["linkCollisionProfile"]).is_file())
        objects = {item["id"]: item for item in project["scene"]["objects"]}
        self.assertEqual(objects["bottle"]["physics"]["body"], "dynamic")
        self.assertEqual(objects["bottle"]["physics"]["collider"]["shape"], "cylinder")
        self.assertEqual(objects["bottle"]["rotation"], [1.57079633, 0.0, 0.0])
        self.assertNotIn("visualTransform", objects["bottle"])
        self.assertEqual(objects["bottle"]["scale"], [0.76793, 0.76793, 0.76793])
        self.assertEqual(objects["bottle"]["radius"], 0.042)
        self.assertEqual(objects["bottle"]["physics"]["collider"], {"shape": "cylinder", "radius": 0.042, "height": 0.20})
        self.assertEqual(objects["bottle"]["position"][2], episode.BOTTLE_CENTER_Z_M)
        self.assertEqual(
            objects["pickup_pedestal"]["position"],
            [*objects["bottle"]["position"][:2], episode.PICKUP_PEDESTAL_CENTER_Z_M],
        )
        self.assertEqual(objects["pickup_pedestal"]["physics"]["body"], "static")
        self.assertEqual(
            objects["pickup_pedestal"]["physics"]["collider"]["size"],
            [0.20, 0.20, episode.PICKUP_PEDESTAL_HEIGHT_M],
        )
        for wall_id, offset in episode.BIN_WALL_OFFSETS.items():
            self.assertEqual(
                objects[wall_id]["position"],
                [episode.BIN_XY[0] + offset[0], episode.BIN_XY[1] + offset[1], offset[2]],
            )
            self.assertEqual(objects[wall_id]["physics"]["body"], "static")

    def test_template_keeps_dynamic_bottle_on_static_reachable_support(self) -> None:
        project = json.loads(TEMPLATE.read_text(encoding="utf-8"))
        objects = {item["id"]: item for item in project["scene"]["objects"]}
        bottle = objects["bottle"]
        pedestal = objects["pickup_pedestal"]

        self.assertEqual(bottle["position"][2], episode.BOTTLE_CENTER_Z_M)
        self.assertEqual(bottle["rotation"], [1.57079633, 0.0, 0.0])
        self.assertNotIn("visualTransform", bottle)
        self.assertEqual(bottle["scale"], [0.76793, 0.76793, 0.76793])
        self.assertEqual(bottle["radius"], 0.042)
        self.assertEqual(bottle["physics"]["collider"], {"shape": "cylinder", "radius": 0.042, "height": 0.20})
        self.assertEqual(bottle["physics"]["body"], "dynamic")
        self.assertFalse(pedestal["includeInFit"])
        self.assertEqual(pedestal["physics"]["body"], "static")
        self.assertEqual(pedestal["size"], [0.20, 0.20, episode.PICKUP_PEDESTAL_HEIGHT_M])
        self.assertEqual(pedestal["position"][2], episode.PICKUP_PEDESTAL_CENTER_Z_M)


if __name__ == "__main__":
    unittest.main()
