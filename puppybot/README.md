# Puppybot ESP32 Rust Bare Metal

Minimal Rust firmware project for a classic ESP32 using `esp-hal`.

The Rust code is split into a small workspace:

- `core/` contains reusable protocol, arm control, kinematics, safety, and
  STServo packet logic.
- `esp32/` contains the firmware binary and ESP32 hardware/network glue.
- `runtime/` contains the OS runtime binary.

## Setup

Install the Espressif Rust toolchain and flashing dependencies. This is still
a bare-metal project: it targets `xtensa-esp32-none-elf` and does not use
ESP-IDF or FreeRTOS.

```sh
./scripts/install.sh
```

If the board is visible but the serial port cannot be opened, add your user to
the serial port group:

```sh
sudo usermod -aG dialout "$USER"
newgrp dialout
```

## Build

```sh
./scripts/build.sh
```

To build firmware that connects to Wi-Fi, provide credentials at build time:

```sh
WIFI_SSID="your-network" WIFI_PASSWORD="your-password" ./scripts/build.sh
```

Or put them in a local `.env` file:

```sh
cp .env.example .env
```

Then edit `.env`:

```sh
WIFI_SSID=your-network
WIFI_PASSWORD=your-password
```

Without those variables the firmware still runs, but Wi-Fi is disabled.
When Wi-Fi is enabled and DHCP succeeds, the firmware advertises
`PuppyBot._ws._tcp.local` on port 80 with hostname `puppybot.local`.
The HTTP server responds on port 80, and WebSocket clients can connect to
`ws://puppybot.local/ws`. The Rust firmware accepts the v1 command frames,
executes PuppyArm and steering commands through the STServo bus, publishes arm
telemetry, and replies to protocol pings. Physical rear DC motor actuation is
not wired into the bare-metal Rust entry point yet.

The Android app still contains its historical Bluetooth control mode, but the
Rust ESP32 firmware does not provide a BLE service. Use the app's Network mode
with the `/ws` endpoint.

For a debug build:

```sh
./scripts/build.sh debug
```

## Runtime

The Rust app can also run as a normal OS process through the `runtime/` crate.
It uses the same arm controller and STServo packet code, backed by a fake
byte-level servo bus, and exposes the Android-compatible WebSocket endpoint on
`/ws`.

```sh
./scripts/run-runtime.sh
```

To use a hardware STServo bus, pass the serial device:

```sh
./scripts/run-runtime.sh --servo-device /dev/ttyUSB0
```

By default it listens on `0.0.0.0:8080`, so the WebSocket URL is
`ws://<runtime-ip>:8080/ws`. It also advertises
`PuppyBot Runtime._ws._tcp.local` with hostname `puppybot-runtime.local` on the
bound port. The local WGUI dashboard listens at `http://127.0.0.1:8081/`.
The dashboard includes drive controls, arm jog controls, arm hold/stop, fault
clearing, and press-and-hold TCP-relative forward/back/left/right jog buttons
with a base/tool frame toggle; these send commands to the same runtime robot
instance used by the WebSocket endpoint.
To bind different addresses:

```sh
PUPPYBOT_RUNTIME_ADDR=127.0.0.1:8082 ./scripts/run-runtime.sh
./scripts/run-runtime.sh --ui-bind 127.0.0.1:9090
```

At startup the runtime looks for a local `puppybot.json` in the current working
directory. If the file is missing, it uses built-in defaults. To load another
file, pass `--config` or set `PUPPYBOT_RUNTIME_CONFIG`:

```sh
./scripts/run-runtime.sh --config ./puppybot.json
```

The runtime UI can adjust arm joint soft tick limits live. Click
`Save Calibration` after testing the new limits to write them to the configured
JSON file. The runtime writes a normalized `puppybot.json` atomically via a temp
file and rename.

The runtime WebSocket listener also exposes a read-only JSON view for agents and
scripts:

```sh
curl http://127.0.0.1:8080/api/config.json
```

The response includes the active config path, dirty flag, and normalized config.

```json
{
  "version": 1,
  "serial": "PB-DEV-0001",
  "drive": {
    "left_motor_id": 1,
    "right_motor_id": 2,
    "steering_servo_id": 1,
    "steering_center_deg": 90,
    "steering_range_deg": 45,
    "command_timeout_ms": 500
  },
  "arm": {
    "joints": [
      {
        "servo_id": 1,
        "tick_min": 0,
        "tick_max": 4095,
        "reference_tick": 2048,
        "reference_angle_deg": 0.0,
        "angle_sign": 1,
        "drive_sign": 1,
        "limit_enabled": true
      },
      {
        "servo_id": 2,
        "tick_min": 100,
        "tick_max": 1000,
        "reference_tick": 530,
        "reference_angle_deg": 90.0,
        "angle_sign": -1,
        "drive_sign": 1,
        "limit_enabled": true
      },
      {
        "servo_id": 3,
        "tick_min": 2200,
        "tick_max": 3600,
        "reference_tick": 3565,
        "reference_angle_deg": 0.0,
        "angle_sign": -1,
        "drive_sign": 1,
        "limit_enabled": true
      },
      {
        "servo_id": 4,
        "tick_min": 500,
        "tick_max": 3000,
        "reference_tick": 1783,
        "reference_angle_deg": 0.0,
        "angle_sign": 1,
        "drive_sign": 1,
        "limit_enabled": true
      }
    ]
  }
}
```

## Simulation capture and replay

Run simulation capture servers on loopback. The runtime command/control API is
unauthenticated, and capture creation is deliberately rejected when
`PUPPYBOT_RUNTIME_ADDR` is bound to a non-loopback address. Note that the
normal runtime default is `0.0.0.0:8080`, so set the address explicitly:

```sh
PUPPYBOT_RUNTIME_ADDR=127.0.0.1:8080 \
  ./scripts/run-runtime.sh --sim --headless \
  --config runtime/puppybot.json \
  --robotdreams-project ../robotdreams/project.json
```

### Live state

`GET /api/state` returns `puppybot.runtime.state.v1` JSON with controller time,
arm joints and TCP positions, drive output, UI state, simulation frame/marker
data, and `sim.captureState` when running with `--sim`:

```sh
mkdir -p workdir/captures
curl -fsS http://127.0.0.1:8080/api/state \
  -o workdir/captures/runtime-state.json
```

The nested capture state uses schema `puppybot.sim.capture-state.v1`. It records
the RobotDreams project filename and content SHA-1, the active camera and
resolution, robot/joint/servo values, scene-node transforms, and the overlays
needed to reproduce the saved pose. It explicitly reports:

- `exactSavedTransforms: true`
- `poseEquivalentRender: true`
- `exactVisualReplay: false`
- `exactDynamicContinuation: false`

In other words, replay uses the exact saved transforms, pose, overlays, and
camera. It is not a checkpoint of physics, controller internals, servo dynamics,
or pending commands, and it cannot continue the original run. Pixel-for-pixel
output is also not promised across renderer, driver, or platform changes.

### Finite screenshots and camera control

Render a real offscreen PGE/WGPU frame after a finite number of simulation
updates, then exit without opening the preview window or starting the HTTP/UI
servers:

```sh
./scripts/run-runtime.sh \
  --sim --screenshot workdir/captures/settled.png --frames 120 \
  --config runtime/puppybot.json \
  --robotdreams-project ../robotdreams/project.json
```

`--screenshot` requires `--sim`. `--frames` must be positive and defaults to
120. The command creates parent directories, writes one PNG, prints the final
controller/model TCP delta, and exits. A custom orbit camera can be selected in
RobotDreams world meters and degrees:

```sh
./scripts/run-runtime.sh \
  --sim --screenshot workdir/captures/rear-high.png --frames 120 \
  --camera-target 0,0,0.22 --camera-radius 0.68 \
  --camera-azimuth -140 --camera-elevation 48 \
  --robotdreams-project ../robotdreams/project.json
```

Camera values must be finite, radius must be positive, and elevation must be
strictly between -90 and 90 degrees. Azimuth is normalized to `[-180, 180)`.
Camera flags require `--screenshot`.

To replay the saved pose and saved camera from either `GET /api/state` or a
capture job's state artifact, use `--state`. No simulation steps are run:

```sh
./scripts/run-runtime.sh \
  --sim --screenshot workdir/captures/replayed.png \
  --state workdir/captures/runtime-state.json --state-frame 0 \
  --robotdreams-project ../robotdreams/project.json
```

`--state` requires `--screenshot`; `--state-frame` is a zero-based index and
defaults to 0. Replay rejects out-of-range frame indices and a RobotDreams
project whose content SHA-1 differs from the saved state. `--frames` and
`--camera-*` cannot be combined with `--state`: the saved pose and camera are
authoritative.

### Finite MP4 recording

The `record` subcommand renders exactly the requested number of frames at 50
fps after 120 settling updates, encodes H.264 MP4, removes its temporary raw
frames, prints the final controller/model TCP delta, and exits:

```sh
./scripts/run-runtime.sh record \
  --sim --out workdir/captures/settled.mp4 --frames 150 \
  --config runtime/puppybot.json \
  --robotdreams-project ../robotdreams/project.json
```

`record` requires `--sim` and `--out`. Live recording requires a positive
`--frames` value and an output path ending in `.mp4`. Encoding requires
`gst-launch-1.0` and GStreamer plugins providing
`rawvideoparse`, `videoconvert`, `openh264enc`, `h264parse`, and `mp4mux`.
Saved-trace and REST recording replay also requires the `pngdec` plugin.
Failure to launch GStreamer or a nonzero encoder result makes the command fail.

To render a downloaded `puppybot.sim.capture-trace.v1` without running or
stepping the simulation, replace `--frames` with `--state`:

```sh
./scripts/run-runtime.sh record \
  --sim --out workdir/captures/replayed.mp4 \
  --state workdir/captures/job-trace.json \
  --robotdreams-project ../robotdreams/project.json
```

`record --state` accepts both `--state PATH` and `--state=PATH`; it is mutually
exclusive with `--frames`. Every trace sample supplies its saved transforms,
overlays, and camera. As with screenshot state replay, this is pose-equivalent
rendering of saved frames, not dynamic continuation of the original run.

### REST screenshot and recording jobs

Screenshot work is asynchronous. Create an empty screenshot request, extract
the returned URLs, poll its status, and then fetch the saved state and PNG:

```sh
BASE=http://127.0.0.1:8080
poll_capture() {
  while :; do
    JOB=$(curl -fsS "$1") || return 1
    STATUS=$(printf '%s' "$JOB" | jq -r '.job.status')
    case "$STATUS" in
      complete) return 0 ;;
      failed) printf '%s\n' "$JOB" >&2; return 1 ;;
      *) sleep 0.1 ;;
    esac
  done
}

CREATE=$(curl -fsS -X POST \
  -H 'content-type: application/json' -d '{}' \
  "$BASE/api/sim/captures/screenshot")
STATUS_URL=$(printf '%s' "$CREATE" | jq -r '.job.status')
STATE_URL=$(printf '%s' "$CREATE" | jq -r '.job.state')
ARTIFACT_URL=$(printf '%s' "$CREATE" | jq -r '.job.artifact')

poll_capture "$BASE$STATUS_URL"
curl -fsS "$BASE$STATE_URL" -o workdir/captures/job-state.json
curl -fsS "$BASE$ARTIFACT_URL" -o workdir/captures/job.png
```

Create a recording with a required frame count from 1 through 500. At 50 fps,
the largest request records ten seconds, enough for the deterministic
ball-to-bin waypoint run:

```sh
RECORD_CREATE=$(curl -fsS -X POST \
  -H 'content-type: application/json' -d '{"frames":150}' \
  "$BASE/api/sim/captures/record")
RECORD_STATUS=$(printf '%s' "$RECORD_CREATE" | jq -r '.job.status')
RECORD_STATE=$(printf '%s' "$RECORD_CREATE" | jq -r '.job.state')
RECORD_ARTIFACT=$(printf '%s' "$RECORD_CREATE" | jq -r '.job.artifact')

poll_capture "$BASE$RECORD_STATUS"
curl -fsS "$BASE$RECORD_STATE" -o workdir/captures/job-trace.json
curl -fsS "$BASE$RECORD_ARTIFACT" -o workdir/captures/job.mp4
```

Recording samples the latest coherent published visual state once per 20 ms
controller tick. In headless mode, the controller path publishes after each
simulation update. With an active preview window, publication happens in the
render callback so each state atomically pairs the rendered pose and camera.
If that callback is slow or the window is minimized, several controller ticks
can sample the same published state; the trace can therefore contain repeated
sequence, simulation time, and camera values. Requested `frames` counts trace
and output samples, not guaranteed unique simulation advances.

Recording status progresses through `capturing`, `queued`, `rendering`, and
`complete`, or ends as `failed`. Screenshot jobs use `queued`, `rendering`,
`complete`, or `failed`. A failed job includes its error string. Fetch state or
artifact only after `complete`, otherwise the server returns `409 Conflict`.
Screenshot state is `puppybot.sim.capture-state.v1` JSON with an `image/png`
artifact. Recording state is `puppybot.sim.capture-trace.v1` JSON with a
`video/mp4` artifact; download the trace to replay it with `record --state`.

The screenshot request body is currently restricted to an empty JSON object,
and the HTTP body limit is 8 KiB. Recording requests accept only an integer
`frames` field; missing, extra, zero, or greater-than-500 values return
`400 Bad Request`. At most four screenshot jobs may be active, and only one
recording may capture at a time; saturation returns `429 Too Many Requests`.
PNG artifacts are capped at 16 MiB, trace JSON at 16 MiB, and MP4 artifacts at
64 MiB. Retained PNG/MP4 artifacts are capped at 128 MiB total, and only the
newest eight terminal jobs are retained across both kinds; the oldest terminal
jobs are evicted until both limits are met. Invalid or evicted IDs return
`404 Not Found`.
Capture creation outside simulation mode or through a non-loopback runtime bind
returns `409 Conflict`. Rendering, encoding, and artifact work run off the
controller loop, so clients must poll instead of waiting on the creation
request. REST recording requires the same GStreamer/OpenH264 tools as CLI
recording; encoder errors leave the job in `failed` with its error message.

## CLI

The `puppybot` CLI talks to the runtime WebSocket API. By default it connects to
`ws://127.0.0.1:8080/ws`.

```sh
cargo run -p puppybot -- ping
cargo run -p puppybot -- config get
cargo run -p puppybot -- arm state
cargo run -p puppybot -- arm jog --joint 0 --direction 1 --speed 300 --duration-ms 500
cargo run -p puppybot -- arm stop --joint 0
cargo run -p puppybot -- arm goto-ticks --speed 300 2048 2048 2048 2048
cargo run -p puppybot -- arm move-tcp --up 20
cargo run -p puppybot -- arm move-tcp --frame tool --forward 20
cargo run -p puppybot -- arm tcp-jog start --frame yaw-flat --forward 1 --speed-mm-s 20 --duration-ms 500
cargo run -p puppybot -- arm tcp-jog stop
```

`arm move-tcp` moves the tool center point relative to its current pose. The
default frame is `base`, where `up/down` use table Z, `forward/back` use the
robot base X axis, and `left/right` use the robot base Y axis. With
`--frame tool`, `forward/back` follows the gripper approach axis and the current
tool pitch is preserved.

`arm tcp-jog start` starts continuous TCP motion in the given direction at
`--speed-mm-s` until `arm tcp-jog stop` is sent. Passing `--duration-ms` makes
the CLI send stop automatically after that many milliseconds, which is useful
for shell-scripted press-and-hold tests.

To validate `move-tcp` end-to-end against RobotDreams' virtual STServo bus and
PuppyBot runtime telemetry:

```sh
python3 scenarios/validate_move_tcp.py --report workdir/recordings/move-tcp-validation/report.json
```

To test against RobotDreams, start RobotDreams' virtual bus, read its
`/dev/pts/...` path, and pass that path to the runtime:

```sh
./scripts/run-runtime.sh --servo-device /dev/pts/15
cargo run -p puppybot -- arm jog --joint 0 --direction 1 --duration-ms 500
```

Scenario brain-process harnesses live in `scenarios/`. The deterministic
ball-to-bin flow starts the in-process RobotDreams runtime, drives Cartesian
waypoints through the public HTTP command API, and uses one simulation-only
`Interact` action to attach and release the ball:

```sh
python3 scenarios/place_ball_to_bin.py
```

The canonical physics fixture is `../robotdreams/project.json`: a 25 mm-radius
dynamic ball and the bin are inside the stationary arm workspace. Pickup is
accepted only when the observed RobotDreams TCP is within 35 mm. After release,
gravity moves the ball and RobotDreams' `ball_in_bin` volume must report both
`settled` and `triggered`; the harness cannot post ball coordinates or success.

To write the same-run trace, MP4, state observations, commands, and validation:

```sh
python3 scenarios/place_ball_to_bin.py --recording-dir workdir/recordings/place-ball-to-bin-001
```

This writes `run.json`, `commands.jsonl`, `observations.jsonl`,
`final-state.json`, `capture-trace.json`, `run.mp4`, `runtime.log`, and
`validation.json`. The live REST recording is started before the first waypoint
and records up to 500 coherent 50 fps frames. Each trace frame includes the
RobotDreams ball/attachment/velocity and complete trigger state, and validation
requires the ordered attach, release, gravity, and settled-trigger sequence.

## Flash

```sh
./scripts/flash.sh
```

To flash a Wi-Fi-enabled build:

```sh
WIFI_SSID="your-network" WIFI_PASSWORD="your-password" ./scripts/flash.sh
```

If `.env` exists, `./scripts/flash.sh` will use it automatically.
