#!/usr/bin/env python3
"""Create and validate evidence-carrying RobotDreams calibration records.

The tool consumes already-recorded observations. It deliberately has no serial,
motor, servo, network, or RobotDreams-control code, so collecting an artifact
cannot move PuppyBot or turn provisional simulation parameters into measurements.
"""

from __future__ import annotations

import argparse
import csv
import datetime as datetime_module
import json
import math
import sys
from pathlib import Path
from typing import Any


CALIBRATION_FORMAT = "robotdreams.calibration.v1"
DRIVE_COLUMNS = (
    "time_sec",
    "left_command",
    "right_command",
    "observed_linear_mps",
    "observed_yaw_rps",
)
SERVO_COLUMNS = (
    "time_sec",
    "servo_id",
    "target_ticks",
    "observed_present_ticks",
)
SERVO_OPTIONAL_COLUMNS = (
    "observed_load",
    "observed_current_raw",
)
PLACEHOLDER_WORDS = ("replace", "placeholder", "provisional", "unmeasured", "unknown", "todo")
VEHICLE_POSITIVE_FIELDS = (
    "mass_kg",
    "wheel_radius_m",
    "gear_ratio",
    "motor_stall_torque_nm",
    "motor_no_load_rpm",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    capture = commands.add_parser("capture", help="combine measured metadata and recorded CSV traces")
    capture.add_argument("--metadata", type=Path, required=True, help="completed calibration metadata JSON")
    capture.add_argument("--drive-trace", type=Path, required=True, help="recorded drive-observation CSV")
    capture.add_argument("--servo-trace", type=Path, required=True, help="recorded servo-observation CSV")
    capture.add_argument("--output", type=Path, required=True, help="output RobotDreams calibration JSON")

    validate = commands.add_parser("validate", help="validate a RobotDreams calibration JSON")
    validate.add_argument("--input", type=Path, required=True, help="calibration JSON to validate")
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ValueError(f"could not read '{path}': {error}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid JSON in '{path}': {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"'{path}' must contain a JSON object")
    return value


def read_csv(
    path: Path,
    columns: tuple[str, ...],
    optional_columns: tuple[str, ...] = (),
) -> list[dict[str, str]]:
    try:
        with path.open(newline="", encoding="utf-8") as source:
            reader = csv.DictReader(source)
            headers = reader.fieldnames
            accepted_headers = [
                list(columns) + [
                    optional
                    for optional, present in zip(optional_columns, inclusion)
                    if present
                ]
                for inclusion in (
                    tuple(bool(mask & (1 << index)) for index in range(len(optional_columns)))
                    for mask in range(1 << len(optional_columns))
                )
            ]
            if headers not in accepted_headers:
                required = ",".join(columns)
                optional = ",".join(optional_columns)
                raise ValueError(
                    f"'{path}' must use required columns in this order: {required}; "
                    f"optional trailing columns: {optional}"
                )
            rows = list(reader)
    except OSError as error:
        raise ValueError(f"could not read '{path}': {error}") from error
    if not rows:
        raise ValueError(f"'{path}' has no observations")
    return rows


def finite_float(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a number")
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field} must be a number") from error
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def integer(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be an integer")
    try:
        number = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field} must be an integer") from error
    if str(number) != str(value).strip():
        raise ValueError(f"{field} must be an integer")
    return number


def measured_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"missing {field}")
    normalized = value.strip()
    if any(word in normalized.lower() for word in PLACEHOLDER_WORDS):
        raise ValueError(f"{field} contains a placeholder or provisional marker")
    return normalized


def measured_timestamp(value: Any) -> str:
    timestamp = measured_text(value, "provenance.measured_at")
    try:
        datetime_module.datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("provenance.measured_at must be ISO 8601") from error
    return timestamp


def required_object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    return value


def measured_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    if metadata.get("format") != CALIBRATION_FORMAT:
        raise ValueError(f"format must be '{CALIBRATION_FORMAT}'")

    provenance = required_object(metadata.get("provenance"), "provenance")
    hardware_revision = measured_text(metadata.get("hardware_revision"), "hardware_revision")
    canonical_provenance = {
        "measured_at": measured_timestamp(provenance.get("measured_at")),
        "operator": measured_text(provenance.get("operator"), "provenance.operator"),
        "method": measured_text(provenance.get("method"), "provenance.method"),
        "source": measured_text(provenance.get("source"), "provenance.source"),
    }
    vehicle = required_object(metadata.get("vehicle"), "vehicle")
    center_of_mass = vehicle.get("center_of_mass_m")
    if not isinstance(center_of_mass, list) or len(center_of_mass) != 3:
        raise ValueError("vehicle.center_of_mass_m must contain three coordinates")

    canonical_vehicle = {
        field: finite_float(vehicle.get(field), f"vehicle.{field}")
        for field in VEHICLE_POSITIVE_FIELDS
    }
    for field, value in canonical_vehicle.items():
        if value <= 0.0:
            raise ValueError(f"vehicle.{field} must be positive")
    canonical_vehicle["center_of_mass_m"] = [
        finite_float(value, "vehicle.center_of_mass_m") for value in center_of_mass
    ]

    servos = metadata.get("servos")
    if not isinstance(servos, list) or not servos:
        raise ValueError("servos must contain at least one measured servo")
    canonical_servos = []
    observed_ids = set()
    for index, servo in enumerate(servos):
        servo = required_object(servo, f"servos[{index}]")
        servo_id = integer(servo.get("servo_id"), f"servos[{index}].servo_id")
        max_speed = finite_float(servo.get("max_speed_ticks_per_sec"), f"servos[{index}].max_speed_ticks_per_sec")
        if not 0 <= servo_id <= 253:
            raise ValueError(f"servos[{index}].servo_id must be in [0, 253]")
        if servo_id in observed_ids:
            raise ValueError(f"servos has duplicate servo_id {servo_id}")
        if max_speed <= 0.0:
            raise ValueError(f"servos[{index}].max_speed_ticks_per_sec must be positive")
        observed_ids.add(servo_id)
        canonical_servos.append({"servo_id": servo_id, "max_speed_ticks_per_sec": max_speed})

    return {
        "format": CALIBRATION_FORMAT,
        "hardware_revision": hardware_revision,
        "provenance": canonical_provenance,
        "vehicle": canonical_vehicle,
        "servos": canonical_servos,
    }


def canonical_drive_trace(rows: list[dict[str, str]]) -> list[dict[str, float]]:
    trace = []
    previous_time: float | None = None
    for index, row in enumerate(rows, start=2):
        sample = {field: finite_float(row[field], f"drive trace row {index} {field}") for field in DRIVE_COLUMNS}
        if abs(sample["left_command"]) > 1.0 or abs(sample["right_command"]) > 1.0:
            raise ValueError(f"drive trace row {index} commands must be normalized to [-1, 1]")
        if previous_time is not None and sample["time_sec"] <= previous_time:
            raise ValueError(f"drive trace row {index} time_sec must increase")
        previous_time = sample["time_sec"]
        trace.append(sample)
    return trace


def canonical_servo_trace(rows: list[dict[str, str]], servos: list[dict[str, Any]]) -> list[dict[str, int | float]]:
    speed_by_id = {servo["servo_id"]: servo["max_speed_ticks_per_sec"] for servo in servos}
    previous_by_id: dict[int, dict[str, int | float]] = {}
    trace = []
    for index, row in enumerate(rows, start=2):
        servo_id = integer(row["servo_id"], f"servo trace row {index} servo_id")
        if servo_id not in speed_by_id:
            raise ValueError(f"servo trace row {index} references unmeasured servo {servo_id}")
        sample: dict[str, int | float] = {
            "time_sec": finite_float(row["time_sec"], f"servo trace row {index} time_sec"),
            "servo_id": servo_id,
            "target_ticks": integer(row["target_ticks"], f"servo trace row {index} target_ticks"),
            "observed_present_ticks": integer(row["observed_present_ticks"], f"servo trace row {index} observed_present_ticks"),
        }
        if "observed_load" in row:
            observed_load = integer(row["observed_load"], f"servo trace row {index} observed_load")
            if not -1000 <= observed_load <= 1000:
                raise ValueError(f"servo trace row {index} observed_load must be in [-1000, 1000]")
            sample["observed_load"] = observed_load
        if "observed_current_raw" in row:
            observed_current_raw = integer(
                row["observed_current_raw"],
                f"servo trace row {index} observed_current_raw",
            )
            if not 0 <= observed_current_raw <= 4095:
                raise ValueError(
                    f"servo trace row {index} observed_current_raw must be in [0, 4095]"
                )
            sample["observed_current_raw"] = observed_current_raw
        previous = previous_by_id.get(servo_id)
        if previous is not None:
            dt = float(sample["time_sec"]) - float(previous["time_sec"])
            if dt <= 0.0:
                raise ValueError(f"servo {servo_id} timestamps must increase")
            speed = abs(int(sample["observed_present_ticks"]) - int(previous["observed_present_ticks"])) / dt
            if speed > speed_by_id[servo_id] * 1.1:
                raise ValueError(f"servo {servo_id} observed position changes faster than measured speed")
        previous_by_id[servo_id] = sample
        trace.append(sample)
    return trace


def validate_record(record: dict[str, Any]) -> tuple[bool, list[str]]:
    try:
        metadata = measured_metadata(record)
        drive_trace = record.get("drive_trace")
        servo_trace = record.get("servo_trace")
        if not isinstance(drive_trace, list) or not drive_trace:
            raise ValueError("missing observed drive trace")
        if not isinstance(servo_trace, list) or not servo_trace:
            raise ValueError("missing observed servo trace")
        canonical_drive_trace([{field: str(sample.get(field, "")) for field in DRIVE_COLUMNS} for sample in drive_trace])
        canonical_servo_trace(
            [
                {
                    field: str(sample[field])
                    for field in SERVO_COLUMNS + SERVO_OPTIONAL_COLUMNS
                    if field in sample
                }
                for sample in servo_trace
            ],
            metadata["servos"],
        )
        theoretical_speed = (
            metadata["vehicle"]["motor_no_load_rpm"]
            * math.tau
            / 60.0
            * metadata["vehicle"]["wheel_radius_m"]
            / metadata["vehicle"]["gear_ratio"]
        )
        observed_speed = max(abs(float(sample["observed_linear_mps"])) for sample in drive_trace)
        if observed_speed > theoretical_speed * 1.1:
            raise ValueError(
                f"observed drive speed {observed_speed:.3f} m/s exceeds no-load model {theoretical_speed:.3f} m/s by >10%"
            )
    except ValueError as error:
        return False, [str(error)]
    return True, []


def capture(metadata_path: Path, drive_path: Path, servo_path: Path, output_path: Path) -> None:
    record = measured_metadata(load_json(metadata_path))
    record["drive_trace"] = canonical_drive_trace(read_csv(drive_path, DRIVE_COLUMNS))
    record["servo_trace"] = canonical_servo_trace(
        read_csv(servo_path, SERVO_COLUMNS, SERVO_OPTIONAL_COLUMNS),
        record["servos"],
    )
    valid, issues = validate_record(record)
    if not valid:
        raise ValueError("record failed validation: " + "; ".join(issues))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    try:
        if args.command == "capture":
            capture(args.metadata, args.drive_trace, args.servo_trace, args.output)
            print(f"wrote measured calibration record to {args.output}")
            return 0
        record = load_json(args.input)
        valid, issues = validate_record(record)
        if valid:
            print(f"valid {CALIBRATION_FORMAT} record: {args.input}")
            return 0
        for issue in issues:
            print(f"invalid: {issue}", file=sys.stderr)
        return 1
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
