# PuppyBot

Run the Flexscript PC controller directly from the repository root:

```sh
flexscript run puppybot.flex
```

It defaults to a fake servo bus. For physical serial control and explicit
output enable, see the [Flexscript instructions](flex/README.md).
Open **http://127.0.0.1:8081/** for the Monolith robot dashboard: drive and arm
controls, targets, live feedback, temperatures, enable/disable, and stop.
The source entry point builds and executes the native controller automatically,
so a long-running session does not exhaust the source VM's instruction budget.
The default calibration is [puppybot.json](puppybot.json), beside the launcher;
it is loaded automatically when running from the repository root.

For a separate virtual serial simulator, start `flexscript run simulator.flex`
in another terminal. It prints the `/dev/pts/N` device and the exact Puppybot
connection command. See the [serial simulator](flex/simulator/README.md) for
details. This models servo motion and faults; it does not yet render a 3D world.

PuppyBot is PuppyCorp's four-wheel service robot with a four-joint PuppyArm.
The active control stack is Rust and shares protocol, arm control, safety, and
STServo behavior between the bare-metal ESP32 firmware, the OS runtime, and
RobotDreams simulation.

## Flexscript port

The `flexscript` branch adds a shared Flexscript controller, native Linux
HTTP/WebSocket and serial runtime, Monolith dashboard, CLI, classic ESP32 serial
firmware, and independently verified fake-servo executable under
[`flex/`](flex/README.md). Simulation and wireless integration remain in progress;
the Rust stack below is the reference implementation.

[`PuppyBotGym`](flex/gym/README.md) uses Monolith to manage simulation rollouts separately from
the robot-control UI. Its first backend runs the native firmware in an isolated
process against a deterministic servo plant, with seeded cases and recorded results.
Its Live camera view tests [native Pup YOLO detection](flex/vision/README.md) with
camera frames, labels and boxes, separately from firmware rollouts and robot controls.

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
./scripts/run-runtime.sh --sim --headless
```

Plain `--sim` automatically loads the simulation-only
`runtime/puppybot.sim.json` profile, independent of the launch directory. It
keeps the calibrated simulated joint limits enabled without changing the
physical runtime profile at `runtime/puppybot.json`. An explicit `--config`
overrides this simulation default.

The command and read API defaults to `http://127.0.0.1:8080` in this example,
with the Android-compatible WebSocket endpoint at `/ws`. The WGUI dashboard
defaults to `http://127.0.0.1:8081/`. See
[`puppybot/README.md`](puppybot/README.md) for hardware serial-bus, CLI,
simulation, calibration, and API examples.

For a deterministic simulation validation image without opening the UI or a
window, run a finite number of controller/RobotDreams updates and render the
settled scene through PGE's real offscreen WGPU renderer:

```sh
cargo run --manifest-path puppybot/Cargo.toml -p puppybot-runtime -- \
  --sim --screenshot workdir/screenshots/validation.png --frames 120 \
  --robotdreams-project robotdreams/project.json
```

`--screenshot` requires `--sim`; `--frames` requires `--screenshot` and must be
positive. If omitted, `--frames` defaults to 120. The process saves the PNG,
prints the controller/model TCP delta, and exits without opening a preview
window or entering the long-running runtime server loop.

Screenshot captures accept an optional orbit camera. The target uses
RobotDreams world meters; angles use degrees:

```sh
cargo run --manifest-path puppybot/Cargo.toml -p puppybot-runtime -- \
  --sim --screenshot workdir/screenshots/rear-high.png --frames 120 \
  --camera-target 0,0,0.22 --camera-radius 0.68 \
  --camera-azimuth -140 --camera-elevation 48 \
  --robotdreams-project robotdreams/project.json
```

The close validation view remains the default: target `[0, 0, 0.22]` m,
radius `0.6031221` m, azimuth `-28.78213` degrees, and elevation `31.537512`
degrees. Camera flags require `--screenshot`; the radius must be positive, all
values must be finite, and elevation must be strictly between -90 and 90
degrees. Azimuth is normalized to `[-180, 180)`.

To capture the same automatic-calibration validation scene as a finite video,
use the `record` subcommand:

```sh
cargo run --manifest-path puppybot/Cargo.toml -p puppybot-runtime -- \
  record --sim --out workdir/recordings/validation.mp4 --frames 150 \
  --robotdreams-project robotdreams/project.json
```

Recording settles the controller and RobotDreams model for 120 simulation
ticks, renders exactly the requested number of frames at 50 fps with one PGE
WGPU renderer, encodes an H.264 MP4 through `gst-launch-1.0`/OpenH264, removes
its temporary raw frames, prints the final controller/model TCP delta, and
exits without starting the runtime UI, HTTP, or WebSocket servers.

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
