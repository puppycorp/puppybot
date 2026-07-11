# PuppyBot

PuppyBot is PuppyCorp's four-wheel service robot with a four-joint PuppyArm.
The active control stack is Rust and shares protocol, arm control, safety, and
STServo behavior between the bare-metal ESP32 firmware, the OS runtime, and
RobotDreams simulation.

## Repository layout

- `puppybot/core/` contains the reusable robot controller, v1 wire protocol,
  kinematics, safety logic, drive state, and STServo packet implementation.
- `puppybot/esp32/` contains the classic ESP32 bare-metal Rust firmware.
- `puppybot/runtime/` contains the OS runtime, HTTP/WebSocket API, and WGUI
  dashboard.
- `puppybot/cli/` contains the command-line client.
- `android/` contains the direct robot controller app.
- `robotdreams/`, `models/`, and `tests/robotdreams/` contain the simulation
  project, owned model assets, and integration tests.
- `python/` contains STServo discovery, configuration, and service utilities.
- `design/` contains the editable electronics sources.

The old ESP-IDF C firmware and Bun mothership server have been retired. Use Git
history when servicing those historical implementations.

## Rust runtime

From `puppybot/`:

```sh
./scripts/run-runtime.sh --sim --headless --config runtime/puppybot.json
```

The command and read API defaults to `http://127.0.0.1:8080` in this example,
with the Android-compatible WebSocket endpoint at `/ws`. The WGUI dashboard
defaults to `http://127.0.0.1:8081/`. See
[`puppybot/README.md`](puppybot/README.md) for hardware serial-bus, CLI,
simulation, calibration, and API examples.

## ESP32 Rust firmware

Install the Rust ESP32 toolchain, build, and flash from `puppybot/`:

```sh
./scripts/install.sh
WIFI_SSID="your-network" WIFI_PASSWORD="your-password" ./scripts/build.sh
./scripts/flash.sh
```

When networking is configured, the firmware serves `ws://puppybot.local/ws`
and advertises `PuppyBot._ws._tcp.local`. It executes PuppyArm and steering
commands through the STServo bus. Physical rear DC motor actuation is not yet
wired into the bare-metal Rust entry point.

The Android app's Network mode is supported. Its historical Bluetooth mode and
permissions remain in the app, but the Rust firmware does not expose a BLE
service.

## Protocol

The supported binary contract remains protocol v1 over WebSocket `/ws`, with
local discovery through `_ws._tcp`. Command and telemetry layouts are defined
in [`docs/puppybot-protocol.md`](docs/puppybot-protocol.md). Command IDs are
stable; retired IDs remain reserved and are not renumbered.

## Service tools

Use the Python tools with a USB serial adapter for STServo service work:

```sh
python3 python/servobus.py scan --port /dev/ttyUSB0
python3 python/servobus.py assign-id --port /dev/ttyUSB0 \
  --family sms_sts --old-id 1 --new-id 2
```

Install their dependency with:

```sh
python3 -m pip install -r python/STServo_Python/requirements.txt
```

## Verification

```sh
cargo fmt --manifest-path puppybot/Cargo.toml --all --check
cargo test --locked --manifest-path puppybot/Cargo.toml --workspace
cargo test --locked --manifest-path tests/robotdreams/Cargo.toml
cd android && ./gradlew testDebugUnitTest assembleDebug
```
