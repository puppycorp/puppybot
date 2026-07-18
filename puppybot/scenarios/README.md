# PuppyBot Scenarios

Scenario scripts are host-side "brain process" harnesses. They talk to:

- PuppyBot Rust runtime HTTP/WebSocket API for robot control.
- The runtime's in-process RobotDreams virtual hardware.
- A camera/video device for perception.
- RobotDreams-owned physics and trigger state for completion checks.

`place_ball_to_bin.robotdreams.json` documents the semantic task. The live
fixture, physics, and `ball_in_bin` trigger are authored in the canonical
`../../robotdreams/project.json` manifest.

The current scripts use scripted policy while the video/perception side is being
connected. The intended next step is a RobotDreams virtual webcam device that a
Python brain can open exactly like a physical camera.

## Ball-To-Bin Completion

`place_ball_to_bin.py` uses a preprogrammed tool-down Cartesian sequence:

`pre-pick -> pick -> Interact -> lift -> transfer -> drop -> Interact -> retreat`

The checked-in `runtime/puppybot.sim.json` profile persists the exact
UI-calibrated simulation limits (yaw `69..3000`, shoulder `2000..3920`, elbow
`560..3593`, wrist `2400..3006`) with all four limits enabled. These values are
not physical PuppyArm mechanical-limit measurements. The old `pick` waypoint is
outside this calibrated profile. Plain `--sim` now loads this profile
automatically, so the default runner fails safely at `pick` until the waypoint
sequence is retuned. Do not weaken the calibrated limits to preserve an old
path.

An explicit config can still be selected for diagnostic comparisons:

```sh
python3 scenarios/place_ball_to_bin.py \
  --recording-dir workdir/recordings/place-ball-to-bin-retune-001 \
  --runtime-config runtime/puppybot.json
```

This override reproduces the historical disabled-limit behavior; it is not the
current simulation acceptance path. Until retuning is complete, the default
command is expected to reject the old `pick` waypoint as unreachable rather
than complete the demo.

The first `Interact` can attach only near the observed live TCP. The second
releases the dynamic ball, after which RobotDreams gravity and collision advance
it independently. Completion requires the `ball_in_bin` trigger to become
settled and triggered. The runner never supplies ball positions or a synthetic
sensor value.

## Run Artifacts

Use `--recording-dir` to save machine-readable proof for a deterministic E2E
run:

```sh
python3 scenarios/place_ball_to_bin.py --recording-dir workdir/recordings/place-ball-to-bin-001
```

Record the same deterministic task from the moving TCP camera with a clean
sensor view (no simulator diagnostic overlays):

```sh
python3 scenarios/place_ball_to_bin.py \
  --recording-dir workdir/recordings/place-ball-to-bin-tcp-001 \
  --capture-camera tcp
```

TCP-camera runs write `tcp-camera.mp4` and
`tcp-camera-capture-trace.json` so they cannot be mistaken for the default
external-camera evidence. The trace identifies every frame's camera source,
pose, FOV, and resolution; validation requires the requested source on every
frame and audits decoded RGB at the source camera's aspect ratio.

The runner refuses an existing non-empty recording directory before starting
the runtime or writing any artifact. Use a new directory for every invocation
so logs and capture-job evidence cannot be mixed across runs.

The directory contains:

- `run.json`
- `commands.jsonl`
- `observations.jsonl`
- `final-state.json`
- `capture-trace.json`
- `run.mp4`
- `runtime.log`
- `validation.json`

The runner starts one live 50 fps REST capture before motion. Its trace frames
include the RobotDreams manipulation and trigger snapshots. `validation.json`
passes only when trace order proves attach, release, downward physics motion,
and settled bin detection, GStreamer identifies H.264, and an explicit
`qtdemux -> h264parse -> openh264dec` pipeline decodes the entire MP4 to a
240x135 RGB audit stream. The validator requires the exact expected frame count
and rejects every frame with a large near-black area, implausibly low mean
brightness, or an abrupt whole-frame brightness discontinuity. Both `run.json`
and `validation.json` also identify the one completed REST capture job used to
produce the trace and video.

## Move-TCP Actor Validation

`validate_move_tcp.py` is the first narrow arm-control validation slice. It does
not post RobotDreams scenario observations or treat PuppyBot's own command
success as proof. PuppyBot is driven through the public runtime CLI/WebSocket
path, and final `validation.json` fails unless a RobotDreams trace captured
during the same run contains virtual-bus command and servo snapshot evidence.

In terminal 1, start RobotDreams trace recording from `projects/RobotDreams`
and leave it running while the actor runs. The ready file exposes the virtual
STServo bus PTY:

```sh
cargo run -p robotdreams -- \
  --project examples/scenes/puppybot-bin-ball/project.json \
  simulation record \
  --trace-only \
  --seconds 60 \
  --trace-out /tmp/move-tcp.trace.jsonl \
  --ready-file /tmp/move-tcp-ready.json
```

In terminal 2, run the PuppyBot actor from `projects/PuppyBot/puppybot` against
that PTY and pass the trace back for the final comparator:

```sh
python3 scenarios/validate_move_tcp.py \
  --servo-device "$(jq -r .virtualBusPath /tmp/move-tcp-ready.json)" \
  --robotdreams-trace /tmp/move-tcp.trace.jsonl \
  --recording-dir workdir/recordings/move-tcp-001
```

The run directory contains:

- `run.json`
- `actor_summary.json`
- `judge_inputs.json`
- `puppybot.commands.jsonl`
- `puppybot.state.jsonl`

## Combined Arm Simulator Validation

`validate_arm_sim_suite.py` runs the PuppyBot actor and final comparator in one
script while RobotDreams records the simulator from the outside. It still keeps
the proof boundary explicit: PuppyBot is driven only through the public
CLI/WebSocket/runtime path, while pass/fail also requires RobotDreams trace and
`recording assert` evidence from the virtual STServo bus and scene transforms.

Start RobotDreams recording from `projects/RobotDreams`:

```sh
cargo run -p robotdreams -- \
  simulation record \
  --project puppybot-bin-and-ball \
  --trace-only \
  --seconds 100 \
  --trace-out /tmp/arm-sim-suite.trace.jsonl \
  --ready-file /tmp/arm-sim-suite-ready.json
```

Then run the suite from `projects/PuppyBot/puppybot`:

```sh
python3 scenarios/validate_arm_sim_suite.py \
  --servo-device "$(jq -r .virtualBusPath /tmp/arm-sim-suite-ready.json)" \
  --robotdreams-trace /tmp/arm-sim-suite.trace.jsonl \
  --robotdreams-ready /tmp/arm-sim-suite-ready.json \
  --recording-dir workdir/recordings/arm-sim-suite-001
```

The default suite validates:

- `arm goto-ticks`
- `arm goto-angles`
- `arm goto-coords`
- `arm move-tcp` on base Z, X, and Y axes
- unreachable `arm goto-coords` rejection

The run directory contains:

- `run.json`
- `summary.json`
- `validation.json`
- `actor_summary.json`
- `robotdreams_evidence.json`
- `robotdreams-assert.json`
- `puppybot.commands.jsonl`
- `puppybot.state.jsonl`
- `robotdreams.trace.jsonl`
- `robotdreams_evidence.json`
- `summary.json`
- `validation.json`

## Arm Control Public API Actor

`arm_control_actor.py` expands the PuppyBot actor side beyond the first
move-tcp slice. It drives only public PuppyBot runtime CLI/WebSocket commands
and records actor evidence for:

- `arm goto-ticks`
- `arm goto-angles`
- `arm goto-coords`
- `arm move-tcp` in base and tool directions
- `arm hold`, timed `arm jog`, and `arm stop`

It does not inspect RobotDreams traces or claim an independent simulator pass.
Hand its `judge_inputs.json`, `puppybot.commands.jsonl`, and
`puppybot.state.jsonl` to the RobotDreams judge.

With RobotDreams recording already running and a ready file available:

```sh
python3 scenarios/arm_control_actor.py \
  --servo-device "$(jq -r .virtualBusPath /tmp/move-tcp-ready.json)" \
  --recording-dir workdir/recordings/arm-control-public-api-001
```

Run one narrower case by repeating `--case`:

```sh
python3 scenarios/arm_control_actor.py \
  --case goto-coords \
  --case move-tcp \
  --servo-device "$(jq -r .virtualBusPath /tmp/move-tcp-ready.json)" \
  --recording-dir workdir/recordings/arm-control-coords-tcp-001
```

The run directory contains:

- `run.json`
- `actor_summary.json`
- `judge_inputs.json`
- `puppybot.commands.jsonl`
- `puppybot.state.jsonl`
