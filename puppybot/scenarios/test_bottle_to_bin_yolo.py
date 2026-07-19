#!/usr/bin/env python3
"""Focused controller checks for the standalone bottle detector policy."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import ANY, patch


MODULE_PATH = Path(__file__).with_name("bottle_to_bin_yolo.py")
SPEC = importlib.util.spec_from_file_location("bottle_to_bin_yolo", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
policy = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = policy
SPEC.loader.exec_module(policy)


class FakeSearchApi:
    def __init__(self) -> None:
        self.drive_commands: list[tuple[int, int]] = []
        self.stop_count = 0

    def drive(self, throttle: int, steering: int) -> None:
        self.drive_commands.append((throttle, steering))

    def stop_drive(self) -> None:
        self.stop_count += 1


class FakeDriveRetryApi:
    preview = None

    def __init__(self) -> None:
        self.stop_count = 0
        self.observations = 0

    def stop_drive(self) -> None:
        self.stop_count += 1

    def observation(self) -> dict:
        self.observations += 1
        return {
            "sim": {
                "frames": {
                    "worldFromBase": {
                        "translationM": [0.12, -0.08, 0.0],
                        "rotationMatrix": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
                    },
                },
            },
        }


class FakeShortApproachApi:
    """A rover at the standoff point but facing the wrong direction."""

    preview = None

    def __init__(self) -> None:
        self.drive_commands: list[tuple[int, int]] = []
        self.stop_count = 0

    def observation(self) -> dict:
        return {
            "sim": {
                "frames": {
                    "worldFromBase": {
                        "translationM": [0.0, 0.0, 0.0],
                        "rotationMatrix": [[0.0, 1.0, 0.0], [-1.0, 0.0, 0.0], [0.0, 0.0, 1.0]],
                    },
                },
            },
        }

    def drive(self, throttle: int, steering: int) -> None:
        self.drive_commands.append((throttle, steering))

    def stop_drive(self) -> None:
        self.stop_count += 1


class FakeInteractionApi:
    def __init__(self, response: dict) -> None:
        self.response = response
        self.paths: list[str] = []

    def post(self, path: str) -> dict:
        self.paths.append(path)
        return self.response


class ContinuousSearchTests(unittest.TestCase):
    def test_pickup_accepts_only_explicit_attachment_acknowledgement(self) -> None:
        """A 200 release toggle must never be treated as a fresh grasp."""
        attached = FakeInteractionApi({
            "ok": True,
            "interaction": {"sequence": 4, "result": "attached", "attached": True},
        })
        self.assertTrue(policy.try_pickup_interaction(attached))
        self.assertEqual(attached.paths, ["/api/sim/interact"])

        released = FakeInteractionApi({
            "ok": True,
            "interaction": {"sequence": 5, "result": "released", "attached": False},
        })
        with self.assertRaisesRegex(RuntimeError, "reported release"):
            policy.try_pickup_interaction(released)

    def test_pickup_calibration_is_detector_specific(self) -> None:
        """A YOLO box-centre correction must not displace Tinygrad contact."""
        self.assertEqual(
            policy.pickup_refinements_mm(type("Tinygrad", (), {"name": "native-tinygrad-v6"})()),
            ((0.0, 0.0),),
        )
        self.assertEqual(
            policy.pickup_refinements_mm(type("Yolo", (), {"name": "onnx-yolo-baseline"})()),
            ((0.0, -30.0),),
        )

    def test_search_repeats_sweeps_until_a_three_frame_lock(self) -> None:
        """No-detection sweeps are waiting, not a policy error."""
        api = FakeSearchApi()
        detection = policy.Detection("bottle", 0.9, (100.0, 100.0, 140.0, 160.0))
        observations = [None, None, None, None,
                        (detection, [0.2, 0.1, 0.1]),
                        (detection, [0.2, 0.1, 0.1]),
                        (detection, [0.2, 0.1, 0.1])]
        with tempfile.TemporaryDirectory() as temporary:
            artifacts = Path(temporary)
            with patch.object(policy, "SEARCH_SCAN_ARC_PRESETS", ((16, 72),)), \
                 patch.object(policy, "SEARCH_SCAN_DURATION_SEC", 0.0), \
                 patch.object(policy, "wrist_camera_detection", side_effect=observations), \
                 patch.object(policy.time, "sleep"):
                found, world, next_sequence = policy.search_for_bottle(api, object(), artifacts, 0)

            self.assertEqual(found, detection)
            self.assertEqual(world, [0.2, 0.1, 0.1])
            self.assertEqual(next_sequence, len(observations))
            # Two complete no-detection sweeps ran before a later sweep locked.
            self.assertEqual(api.drive_commands, [(16, 72), (16, 72)])
            self.assertEqual(api.stop_count, 2)
            cycles = [json.loads(line) for line in (artifacts / "search-cycles.jsonl").read_text().splitlines()]
            # The third sweep received two coherent frames at its final
            # positions; the fourth starts stationary and accepts the third.
            self.assertEqual([cycle["cycle"] for cycle in cycles], [0, 1, 2])

    def test_bounded_jsonl_log_keeps_a_fixed_retention_window(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "events.jsonl"
            log = policy.BoundedJsonlLog(path)
            for sequence in range(policy.ARTIFACT_LOG_MAX_EVENTS + policy.ARTIFACT_LOG_COMPACT_BATCH):
                log.append({"sequence": sequence})
            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), policy.ARTIFACT_LOG_MAX_EVENTS - policy.ARTIFACT_LOG_COMPACT_BATCH)
            self.assertEqual(json.loads(lines[0])["sequence"], policy.ARTIFACT_LOG_COMPACT_BATCH * 2)
            self.assertEqual(json.loads(lines[-1])["sequence"],
                             policy.ARTIFACT_LOG_MAX_EVENTS + policy.ARTIFACT_LOG_COMPACT_BATCH - 1)

    def test_nonconvergent_drive_segment_stops_and_returns_false(self) -> None:
        """A segment timeout is recoverable, while its stop remains mandatory."""
        api = FakeDriveRetryApi()
        self.assertFalse(policy.drive_to_pose(api, [0.0, 0.0], timeout_sec=0.0))
        self.assertEqual(api.stop_count, 1)

    def test_short_visual_approach_turns_when_standoff_position_is_close_but_yaw_is_wrong(self) -> None:
        """The standoff's arm-facing direction is part of approach convergence."""
        api = FakeShortApproachApi()
        with patch.object(policy.time, "sleep"):
            policy.drive_toward_world(api, [0.03, 0.0], timeout_sec=0.001, target_yaw=0.0)
        self.assertTrue(api.drive_commands)
        self.assertEqual(api.stop_count, 1)

    def test_pickup_standoff_rotates_the_arm_forward_offset_into_world_coordinates(self) -> None:
        """A search turn must not leave the world-+X standoff hard-coded."""
        state = FakeShortApproachApi().observation()
        state["sim"]["frames"]["baseFromArmBase"] = {
            "translationM": [0.04, 0.0, 0.0],
            "rotationMatrix": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
        }
        # worldFromBase above has yaw -90 degrees, so arm +X is world -Y.
        waypoint, yaw = policy.pickup_approach_pose(state, [0.2, 0.3, 0.1])
        self.assertAlmostEqual(waypoint[0], 0.2)
        self.assertAlmostEqual(waypoint[1], 0.5)
        self.assertAlmostEqual(yaw, -1.5707963267948966)

    def test_pickup_standoff_can_hold_the_camera_lock_frame_across_a_rover_turn(self) -> None:
        """Fresh detections refine bottle position without making the goal orbit it."""
        state = FakeShortApproachApi().observation()
        state["sim"]["frames"]["baseFromArmBase"] = {
            "translationM": [0.04, 0.0, 0.0],
            "rotationMatrix": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
        }
        lock_rotation = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
        waypoint, yaw = policy.pickup_approach_pose(
            state, [0.2, 0.3, 0.1], lock_rotation, 0.0,
        )
        self.assertAlmostEqual(waypoint[0], 0.0)
        self.assertAlmostEqual(waypoint[1], 0.3)
        self.assertEqual(yaw, 0.0)

    def test_configured_drive_retries_only_after_a_fresh_observation(self) -> None:
        """Map navigation retries safely; it never raises on one timeout."""
        api = FakeDriveRetryApi()
        with tempfile.TemporaryDirectory() as temporary, \
             patch.object(policy, "drive_to_pose", side_effect=[False, True]) as segment:
            policy.drive_to_configured_pose_forever(
                api, Path(temporary), [0.5, -0.2], phase="DRIVE_TO_BIN",
            )
            self.assertEqual(segment.call_count, 2)
            self.assertEqual(api.observations, 1)
            retries = [
                json.loads(line)
                for line in (Path(temporary) / "drive-retries.jsonl").read_text().splitlines()
            ]
            self.assertEqual(len(retries), 1)
            self.assertEqual(retries[0]["phase"], "DRIVE_TO_BIN")
            self.assertEqual(retries[0]["freshBaseWorldM"], [0.12, -0.08, 0.0])

    def test_confirmed_grasp_hands_off_without_reacquiring_carried_bottle(self) -> None:
        """A successful gripper acknowledgement must end wrist-vision pickup.

        The carried bottle remains visible to the TCP camera, so a third
        visual-servo call here would reproduce the self-chasing APPROACH loop.
        Carry clearance instead uses arm waypoint feedback and the result is
        returned directly to the DRIVE_TO_BIN state transition.
        """
        detection = policy.Detection("bottle", 0.91, (100.0, 100.0, 140.0, 160.0))
        contact = policy.PickupObservation(
            detection,
            [0.18, 0.04, 0.10],
            {
                "tcpObservationId": 77,
                "arm": {"currentTcpMm": [120.0, 20.0, 55.0]},
                "sim": {"frames": {
                    "worldFromBase": {
                        "translationM": [0.0, 0.0, 0.0],
                        "rotationMatrix": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
                    },
                    "baseFromArmBase": {
                        "translationM": [0.0, 0.0, 0.0],
                        "rotationMatrix": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
                    },
                }},
            },
        )
        with tempfile.TemporaryDirectory() as temporary:
            artifacts = Path(temporary)
            with patch.object(policy, "move_default_pose"), \
                 patch.object(policy, "fresh_pickup_observation", return_value=(contact, 8)), \
                 patch.object(policy, "visual_servo_move", side_effect=[(contact, 8), (contact, 8)]) as servo, \
                 patch.object(policy, "try_pickup_interaction", return_value=True), \
                 patch.object(policy, "move_arm") as carry_move:
                result, sequence = policy.pickup_with_continuous_tcp_detection(
                    object(), object(), artifacts, 7, detection, [0.18, 0.04, 0.10],
                )

            self.assertIsNotNone(result)
            assert result is not None
            self.assertEqual(sequence, 8)
            self.assertEqual(result.state, contact.state)
            self.assertEqual([call.args[4] for call in servo.call_args_list], [
                "PICKUP_PRE_PICK_0", "PICKUP_CONTACT_0",
            ])
            carry_move.assert_called_once_with(
                ANY, [120.0, 20.0, 165.0], "confirmed-grasp carry lift",
            )
            handoff = [
                json.loads(line)
                for line in (artifacts / "grasp-handoff.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual([event["outcome"] for event in handoff], [
                "grasp-confirmed-leaving-vision", "carry-clearance-settled",
            ])


if __name__ == "__main__":
    unittest.main()
