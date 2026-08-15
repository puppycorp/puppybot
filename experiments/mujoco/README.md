# PuppyBot MuJoCo room experiment

This experiment places PuppyBot and an upright bottle in a small MuJoCo room.
The arm has a TCP-mounted 640x480 camera, calibrated joint limits, position
actuators, floor contact, and a simulation-only gripper attachment. A separate
Python policy consumes only camera pixels and public arm state while it aligns
the TCP, descends, and attempts pickup.

The initial arm posture is an in-limit forward/down camera pose derived from
PuppyBot's existing `DRIVE_SCAN` posture. It retains elbow-limit margin for
relative approach while giving Tinygrad a side-on bottle silhouette before the
first correction.

The detailed glTF render meshes are replaced with primitive collision/render
geometry because MuJoCo does not load those repository assets directly. This
is a control/perception feasibility fixture, not a hardware-validated dynamics
model.

## Firmware reuse

The API server does not implement PuppyArm IK or safety in Python. A small C
ABI library wraps `puppybot-core`, the same Rust controller library used by the
ESP32 firmware and host runtime. MuJoCo joint angles are converted to simulated
ST3215 feedback every 20 ms; relative TCP commands pass through the real Rust
kinematics, calibrated limits, target tracking, and safety governor before
MuJoCo receives actuator targets.

This reuses firmware logic, but it does not execute the compiled ESP32 image or
emulate ESP32 peripherals. Full-binary use would require MCU emulation or
hardware-in-the-loop with a virtual servo transport.

## Build and run

From the repository root:

```sh
python3 -m venv .venv
.venv/bin/pip install -r experiments/mujoco/requirements.txt
cargo build --locked --manifest-path experiments/mujoco/firmware-core/Cargo.toml
MUJOCO_GL=egl .venv/bin/python experiments/mujoco/server.py
```

The service binds only to loopback and defaults to
`http://127.0.0.1:8090`. Open the keyboard control page in a browser at:

```text
http://127.0.0.1:8090/
```

Hold the up/down arrow keys to drive the rover forward/reverse and left/right
to turn. The arm uses `W`/`S` for camera image up/down, `A`/`D` for image
left/right, and `Q`/`E` for optical-forward/backward. `Space` stops both systems
immediately; `G` and `O` close and open the virtual gripper. The page includes
the live TCP image and arm telemetry. A second scene view orbits around PuppyBot
by dragging and zooms with the mouse wheel.

The original finite headless kinematics experiment remains available:

```sh
.venv/bin/python experiments/mujoco/run.py
```

## Control API

- `GET /health` reports backend readiness.
- `GET /` serves the local keyboard control page.
- `GET /api/state` reports arm targets, feedback, TCP position, and attachment
  state. It deliberately omits the bottle coordinate.
- `GET /api/camera/tcp` returns a PNG from the camera mounted at the TCP.
- `GET /api/camera/tcp/raw` returns an atomic RGBA8 frame plus public arm state.
- `GET /api/camera/orbit` returns the movable external scene camera as a PNG.
- `POST /api/arm/tcp-jog` executes one bounded relative TCP move through
  `puppybot-core`.
- `POST /api/arm/stop` stops arm movement through `puppybot-core`.
- `POST /api/base/drive` refreshes a bounded differential-drive command.
- `POST /api/base/stop` stops the simulated rover immediately.
- `POST /api/gripper/close` attempts contact and reports `attached` or
  `no-contact`; it does not reveal distance or bottle position.
- `POST /api/gripper/open` releases an attached bottle.
- `POST /api/reset` restores the room, bottle, arm, and firmware-core state.

One relative jog accepts `[image-right, image-up, optical-forward]` in
millimetres, with a maximum vector length of 25 mm:

```sh
curl -X POST http://127.0.0.1:8090/api/arm/tcp-jog \
  -H 'Content-Type: application/json' \
  -d '{"cameraDeltaMm":[6,-4,0]}'
```

## Tinygrad visual servo

The controller reuses PuppyBot's native Tinygrad V6 grid detector. Initialize
the checked-in Tinygrad submodule and provide the trained safetensors
checkpoint used by the RobotDreams policy:

```sh
git submodule update --init examples/tinygrad
.venv/bin/python experiments/mujoco/controller.py \
  --checkpoint workdir/training-dataset/tinygrad-v6-grid-018/bottle-v6-grid.safetensors
```

For every correction, the process fetches a new TCP frame and runs Tinygrad.
It makes bounded camera-plane corrections and adds a 10 mm optical descent once
the lateral correction is modest. A grasp is attempted only while the detection
is centered. Three lost detections stop the arm rather than continuing with
stale geometry; a confirmed attachment is followed by a camera-backward lift.

The current V6 checkpoint was trained on RobotDreams renders. MuJoCo's simpler
appearance is a domain shift, so the service/controller path can be validated
now, but reliable autonomous pickup may require adding MuJoCo camera frames to
the Tinygrad training corpus.

## Verify

```sh
cargo test --locked --manifest-path experiments/mujoco/firmware-core/Cargo.toml
MUJOCO_GL=egl .venv/bin/python -m unittest discover \
  -s experiments/mujoco -p 'test_*.py'
```

The tests verify the Rust firmware-core FFI, TCP/FK agreement, camera output,
camera-relative motion through `puppybot-core`, bounded rover motion with a
deadman stop, visual correction directions, and a complete camera-only
approach, attachment, and bottle lift after bounded core-controlled jogs.

## Parameter sources and scope

- Arm link dimensions and phase rotations mirror
  `puppybot/core/src/puppyarm/kinematics.rs`.
- The arm-base transform mirrors `models/puppybot/robotdreams.json`.
- Servo calibration and joint limits come from
  `puppybot/runtime/puppybot.sim.json`.
- Base, wheel, gravity, and bottle values start from the current RobotDreams
  prototype manifests.

The fixture uses a planar kinematic differential-drive approximation rather
than wheel contact dynamics. It does not yet implement detailed reviewed
collision hulls, finger dynamics, Tinygrad retraining, or hardware-measured
motors and contacts.
