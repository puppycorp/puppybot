#!/usr/bin/env python3
"""Canonical ball-to-bin entry point plus compatibility helpers for arm validators.

The executable path delegates to :mod:`place_ball_to_bin_sim`, which uses the
embedded RobotDreams simulation, public PuppyBot HTTP commands, simulator-owned
object physics, and the simulator-owned bin trigger.  The small compatibility
surface remains because the independent arm validation scripts import the
external-bus runtime launcher from this module.
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True)
class RepoLayout:
    puppybot_root: Path
    company_root: Path
    robotdreams_root: Path
    robotdreams_project: Path
    robotdreams_scenario: Path


def discover_layout(script_path: Path) -> RepoLayout:
    puppybot_root = script_path.resolve().parents[1]
    company_root = puppybot_root.parents[2]
    robotdreams_root = company_root / "projects" / "RobotDreams"
    return RepoLayout(
        puppybot_root=puppybot_root,
        company_root=company_root,
        robotdreams_root=robotdreams_root,
        robotdreams_project=robotdreams_root / "examples" / "puppyarm" / "project.json",
        robotdreams_scenario=puppybot_root / "scenarios" / "place_ball_to_bin.robotdreams.json",
    )


def wait_for_tcp(addr: str, timeout_seconds: float) -> None:
    host, port_text = addr.rsplit(":", 1)
    deadline = time.monotonic() + timeout_seconds
    last_error: OSError | None = None
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, int(port_text)), timeout=0.25):
                return
        except OSError as error:
            last_error = error
            time.sleep(0.1)
    raise RuntimeError(f"timed out waiting for {addr}: {last_error}")


class ManagedProcess:
    def __init__(self, args: Sequence[str], *, cwd: Path, env: dict[str, str] | None = None):
        self.process = subprocess.Popen(
            args,
            cwd=cwd,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )

    def stop(self) -> None:
        if self.process.poll() is not None:
            return
        self.process.send_signal(signal.SIGINT)
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            self.process.wait(timeout=5)

    def drain_output(self) -> str:
        if not self.process.stdout:
            return ""
        return self.process.stdout.read() or ""


class PuppyBotRuntime:
    """Legacy external-servo-bus launcher used only by focused arm validators."""

    def __init__(self, layout: RepoLayout, runtime_addr: str, ui_addr: str, servo_device: str):
        self.layout = layout
        self.runtime_addr = runtime_addr
        self.ui_addr = ui_addr
        self.servo_device = servo_device
        self.process: ManagedProcess | None = None

    @property
    def url(self) -> str:
        return f"ws://{self.runtime_addr}/ws"

    def start(self) -> None:
        env = os.environ.copy()
        env["PUPPYBOT_RUNTIME_ADDR"] = self.runtime_addr
        self.process = ManagedProcess(
            ["./scripts/run-runtime.sh", "--servo-device", self.servo_device,
             "--ui-bind", self.ui_addr],
            cwd=self.layout.puppybot_root,
            env=env,
        )
        wait_for_tcp(self.runtime_addr, timeout_seconds=20)

    def stop(self) -> None:
        if self.process:
            self.process.stop()
            output = self.process.drain_output()
            if output.strip():
                print(output, end="")
            self.process = None


if __name__ == "__main__":
    from place_ball_to_bin_sim import main

    sys.exit(main())
