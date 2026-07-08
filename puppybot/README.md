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
`ws://puppybot.local/ws`. The Rust firmware currently accepts command frames
and replies to protocol pings; motor/arm command execution still needs the
Rust hardware control layer.

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

Scenario brain-process harnesses live in `scenarios/`. For example, the
ball-to-bin scripted flow starts RobotDreams, connects the Rust runtime to the
virtual STServo bus, and drives the arm through the same WebSocket API as the
real robot:

```sh
python3 scenarios/place_ball_to_bin.py
```

The ball-to-bin task definition lives next to the harness as
`scenarios/place_ball_to_bin.robotdreams.json`. The harness loads it through the
first-class `robotdreams scenario` CLI before starting task progress checks.
To write machine-readable proof artifacts for a run:

```sh
python3 scenarios/place_ball_to_bin.py --recording-dir workdir/recordings/place-ball-to-bin-001
```

This writes `run.json`, `progress.jsonl`, `robot_commands.jsonl`, `sensor.jsonl`,
`completion.json`, and `validation.json`.

By default, the scenario asks RobotDreams to export the virtual bin pressure
sensor. For a real external bin pressure sensor, have the sensor writer update a
file with `true`, `1`, or JSON like `{"pressed": true}` / `{"pressure": 0.82}`:

```sh
python3 scenarios/place_ball_to_bin.py --bin-pressure-file /tmp/bin-pressure.json
```

The scenario also posts task observations to RobotDreams and queries semantic
progress telemetry after each major action so the run log can show whether the
task is seeking, grasped, carrying, pressure-detected, or complete.

## Flash

```sh
./scripts/flash.sh
```

To flash a Wi-Fi-enabled build:

```sh
WIFI_SSID="your-network" WIFI_PASSWORD="your-password" ./scripts/flash.sh
```

If `.env` exists, `./scripts/flash.sh` will use it automatically.
