#!/usr/bin/env python3
"""Independent validator for a bottle-to-bin autonomy episode."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"{path} is not a JSON object")
    return value


def state_machine_order_is_valid(path: Path) -> bool:
    if not path.is_file():
        return False
    states = [
        json.loads(line).get("state")
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    expected = ["IDLE", "SEARCH", "APPROACH", "PICKUP", "DRIVE_TO_BIN", "DROP_TO_BIN", "SEARCH"]
    index = 0
    for state in states:
        if index < len(expected) and state == expected[index]:
            index += 1
    return index == len(expected)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy-artifacts", type=Path, required=True)
    parser.add_argument("--judge-state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    policy = read_json(args.policy_artifacts / "policy-result.json")
    final_state = read_json(args.judge_state)
    commands = (args.policy_artifacts / "commands.jsonl").read_text(encoding="utf-8").splitlines()
    state_machine_completed = state_machine_order_is_valid(args.policy_artifacts / "state-transitions.jsonl")
    used_only_restricted_surface = all(
        "/api/autonomy/" in line for line in commands if '"path": "/api/' in line
    )
    sim = final_state.get("sim", {})
    manipulation = sim.get("manipulation", {}) if isinstance(sim, dict) else {}
    trigger = manipulation.get("binTrigger", {}) if isinstance(manipulation, dict) else {}
    result = policy.get("result", {})
    success = bool(
        policy.get("success")
        and isinstance(result, dict)
        and isinstance(result.get("detection"), dict)
        and used_only_restricted_surface
        and state_machine_completed
        and trigger.get("triggered") is True
        and trigger.get("ballDetected") is True
        and manipulation.get("ball", {}).get("attached") is False
    )
    verdict = {
        "schema": "puppybot.bottle-yolo.judge.v1",
        "success": success,
        "requirements": {
            "policyCompleted": policy.get("success") is True,
            "yoloBottleDetectionLogged": isinstance(result.get("detection"), dict),
            "policyUsedOnlyAutonomyApi": used_only_restricted_surface,
            "stateMachineCompletedCycle": state_machine_completed,
            "bottleInBinSettled": trigger.get("triggered") is True,
            "bottleInBinOccupied": trigger.get("ballDetected") is True,
            "bottleDetached": manipulation.get("ball", {}).get("attached") is False,
        },
    }
    args.output.write_text(json.dumps(verdict, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(verdict, indent=2))
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
