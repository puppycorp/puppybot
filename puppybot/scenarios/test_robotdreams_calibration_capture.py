#!/usr/bin/env python3
"""Regression checks for the passive RobotDreams calibration handoff."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCENARIOS = Path(__file__).parent
MODULE_PATH = SCENARIOS / "capture_robotdreams_calibration.py"
TEMPLATE_PATH = SCENARIOS.parent.parent / "robotdreams/calibration/robotdreams.calibration.v1.template.json"
SERVO_TRACE_TEMPLATE_PATH = SCENARIOS.parent.parent / "robotdreams/calibration/servo-trace.csv.template"
SPEC = importlib.util.spec_from_file_location("capture_robotdreams_calibration", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
capture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(capture)


def measured_metadata() -> dict:
    return {
        "format": "robotdreams.calibration.v1",
        "hardware_revision": "puppybot-r1-lab-2026-07-20",
        "provenance": {
            "measured_at": "2026-07-20T12:00:00Z",
            "operator": "Mika",
            "method": "scale, calipers, tachometer, and servo feedback log",
            "source": "lab-notebook/puppybot-r1/run-001",
        },
        "vehicle": {
            "mass_kg": 2.4,
            "center_of_mass_m": [0.0, 0.0, 0.06],
            "wheel_radius_m": 0.0325,
            "gear_ratio": 1.0,
            "motor_stall_torque_nm": 0.45,
            "motor_no_load_rpm": 120.0,
        },
        "servos": [{"servo_id": 5, "max_speed_ticks_per_sec": 1000.0}],
    }


class RobotDreamsCalibrationCaptureTests(unittest.TestCase):
    def test_capture_emits_robotdreams_schema_from_recorded_observations(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metadata_path = root / "metadata.json"
            drive_path = root / "drive.csv"
            servo_path = root / "servo.csv"
            output_path = root / "calibration.json"
            metadata_path.write_text(json.dumps(measured_metadata()), encoding="utf-8")
            drive_path.write_text(
                "time_sec,left_command,right_command,observed_linear_mps,observed_yaw_rps\n"
                "0.0,0.0,0.0,0.0,0.0\n"
                "1.0,0.5,0.5,0.15,0.0\n",
                encoding="utf-8",
            )
            servo_path.write_text(
                "time_sec,servo_id,target_ticks,observed_present_ticks\n"
                "0.0,5,2000,1900\n"
                "0.2,5,2000,2000\n",
                encoding="utf-8",
            )

            capture.capture(metadata_path, drive_path, servo_path, output_path)
            record = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(record["format"], "robotdreams.calibration.v1")
        self.assertEqual(
            set(record),
            {"format", "hardware_revision", "provenance", "vehicle", "servos", "drive_trace", "servo_trace"},
        )
        self.assertEqual(record["drive_trace"][1]["observed_linear_mps"], 0.15)
        self.assertEqual(record["servo_trace"][1]["observed_present_ticks"], 2000)
        self.assertEqual(capture.validate_record(record), (True, []))

    def test_template_is_deliberately_rejected_until_real_measurements_replace_it(self) -> None:
        template = json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))
        valid, issues = capture.validate_record(template)

        self.assertFalse(valid)
        self.assertTrue(any("placeholder" in issue for issue in issues))

    def test_servo_trace_template_uses_completed_optional_schema_names(self) -> None:
        self.assertEqual(
            SERVO_TRACE_TEMPLATE_PATH.read_text(encoding="utf-8").splitlines(),
            [",".join(capture.SERVO_COLUMNS + capture.SERVO_OPTIONAL_COLUMNS)],
        )

    def test_capture_preserves_optional_measured_servo_load_and_raw_current(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metadata_path = root / "metadata.json"
            drive_path = root / "drive.csv"
            servo_path = root / "servo.csv"
            output_path = root / "calibration.json"
            metadata_path.write_text(json.dumps(measured_metadata()), encoding="utf-8")
            drive_path.write_text(
                "time_sec,left_command,right_command,observed_linear_mps,observed_yaw_rps\n"
                "0.0,0.0,0.0,0.0,0.0\n"
                "1.0,0.5,0.5,0.15,0.0\n",
                encoding="utf-8",
            )
            servo_path.write_text(
                "time_sec,servo_id,target_ticks,observed_present_ticks,observed_load,observed_current_raw\n"
                "0.0,5,2000,1900,-120,1720\n"
                "0.2,5,2000,2000,90,1515\n",
                encoding="utf-8",
            )

            capture.capture(metadata_path, drive_path, servo_path, output_path)
            record = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(record["servo_trace"][0]["observed_load"], -120)
        self.assertEqual(record["servo_trace"][1]["observed_current_raw"], 1515)
        self.assertEqual(capture.validate_record(record), (True, []))

    def test_servo_optional_columns_must_follow_required_columns(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            trace_path = Path(temporary) / "servo.csv"
            trace_path.write_text(
                "time_sec,observed_load,servo_id,target_ticks,observed_present_ticks\n"
                "0.0,0,5,2000,1900\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "required columns in this order"):
                capture.read_csv(trace_path, capture.SERVO_COLUMNS, capture.SERVO_OPTIONAL_COLUMNS)

    def test_servo_raw_current_must_remain_a_measured_12_bit_value(self) -> None:
        rows = [{
            "time_sec": "0.0",
            "servo_id": "5",
            "target_ticks": "2000",
            "observed_present_ticks": "1900",
            "observed_current_raw": "4096",
        }]

        with self.assertRaisesRegex(ValueError, "observed_current_raw must be in \\[0, 4095\\]"):
            capture.canonical_servo_trace(rows, measured_metadata()["servos"])

    def test_capture_rejects_provisional_identity_and_non_observed_servo_data(self) -> None:
        metadata = measured_metadata()
        metadata["hardware_revision"] = "prototype-unmeasured"
        with self.assertRaisesRegex(ValueError, "placeholder or provisional"):
            capture.measured_metadata(metadata)

        rows = [
            {"time_sec": "0.0", "servo_id": "5", "target_ticks": "2000", "observed_present_ticks": "1900"},
            {"time_sec": "0.1", "servo_id": "5", "target_ticks": "2000", "observed_present_ticks": "2100"},
        ]
        with self.assertRaisesRegex(ValueError, "faster than measured speed"):
            capture.canonical_servo_trace(rows, measured_metadata()["servos"])


if __name__ == "__main__":
    unittest.main()
