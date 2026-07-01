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
The dashboard includes drive controls, arm jog controls, arm hold/stop, and
fault clearing; these send commands to the same runtime robot instance used by
the WebSocket endpoint.
To bind different addresses:

```sh
PUPPYBOT_RUNTIME_ADDR=127.0.0.1:8082 ./scripts/run-runtime.sh
./scripts/run-runtime.sh --ui-bind 127.0.0.1:9090
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
