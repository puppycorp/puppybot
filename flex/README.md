# Puppybot Flexscript port

This branch contains the shared controller, a native Linux HTTP/WebSocket and
serial runtime, and a protocol v1 command-line client in Flexscript. The Rust
stack remains the reference for the migration. A [classic ESP32 serial firmware](firmware/README.md)
now builds the controller for the real chip. A Monolith dashboard controls the
PC runtime. Android app, wireless firmware integration, and RobotDreams integration
remain separate work.

[PuppyBotGym](gym/README.md) now provides a separate Monolith experiment interface and
headless rollout runner. It launches the native firmware target in its own
process, supplies virtual STServo hardware, and records seeded arm/fault cases.
It also manages native camera/contact scenes, including unknown-map house
discovery and pickup, with pause/resume/stop, videos, maps, and saved results.
Its servo plant has no contact physics; native arms use kinematic collision
checks and loose objects use contact dynamics. Robot controls connect
independently to each bot's endpoint.

[Native 3D simulation](sim/README.md) runs the full PuppyBot model with the
Flexscript controller, keyboard/API controls, URDF joint poses and shared
rigid-body ball contacts. Build it separately with `./flex/scripts/build-sim.sh`.
The simulator includes a [case catalog](sim/cases/catalog.json) for ball-to-bin and grouped-blocks-to-box tasks.
Robot motion is kinematic; gravity-loaded articulated dynamics remain future work.

[Native Pup vision](vision/README.md) adds YOLO26n inference and Gym's Live camera
test view. Models and checkpoints are separate from the observation/detection
contract; Python/ONNX are preparation tools, tinygrad is a validation reference,
and inference uses shared native Flexscript CPU/SASS/CUDA/HIP kernels without Torch.

## Build and run

Run the root entry point directly from source, without a manual build step:

```sh
flexscript run puppybot.flex
```

With no arguments and no serial-device environment setting it starts a fake
servo bus on localhost:8081. If the compiler is not on PATH, use
`../flexscript/build/flex run puppybot.flex`. The original
`flex/runtime/main.flex` remains the native compiler entry point.
The root launcher compiles it to `build/flex/puppybot-runtime` and replaces
itself with that executable. The long-running controller therefore executes
natively, outside the source VM's finite instruction/deadline/memory budgets.
Every launch rebuilds from current source and atomically publishes the result;
a failed compile never starts an older binary. `FLEXSCRIPT_COMPILER` selects
the compiler, otherwise the launcher searches PATH and the sibling checkout.
The default calibration is `puppybot.json`, beside `puppybot.flex`; run from
the repository root to load it automatically. Both the PC runtime and ESP32
build use this file. `--config PATH` or `PUPPYBOT_RUNTIME_CONFIG` selects another
PC profile, and `PUPPYBOT_ESP32_CONFIG` overrides it for firmware builds.

To connect the normal controller to a separate simulated serial bus, run
`flexscript run simulator.flex` in another terminal and copy its printed
Puppybot connection command. The [standalone simulator](simulator/README.md)
creates a private `/dev/pts/N` device, uses the same calibration, and supplies
STServo encoder/temperature replies. Controller enable, freshness, limits and
command leases remain active. It reuses Gym's servo-motion model; articulated
3D physics is not implemented.

## Robot dashboard

After starting `flexscript run puppybot.flex`, open **http://127.0.0.1:8081/**
(or `http://localhost:8081/`). The same listener serves the dashboard, HTTP API,
and `/ws` protocol endpoint. `/health` retains the JSON runtime health response.
The dashboard is separate from Gym's experiment and camera interface on port 8090.

The Monolith view includes live bus/output status, joint angles/ticks/targets,
faults, limits, temperatures, calibration status, and the last command. Controls
cover drive directions, joint and base/tool TCP jogging, speed, hold/stop,
fault clearing, joint targets/default pose, coordinate targets, and calibration
save. Fake mode also offers limit and reference editors. Hardware calibration
and limit edits remain locked: update the reviewed `puppybot.json` and restart.
Coordinate targets use the existing API's robot-base convention; TCP readout
and base-frame jogging use the arm base.

Press and hold a jog button with the pointer/touch, or focus it and hold Space
or Enter. Release, pointer cancellation, blur, hidden page, or a failed live
connection ends the hold. Escape stops all motion. Each hold has an owner and
a 500 ms server-side lease, renewed only by the browser while held, including
in fake mode. An expired/released lease cannot be renewed; reconnecting never
resumes motion. Hardware still starts in monitor mode and requires explicit
enable with fresh feedback; thermal shutdown and existing joint guards apply.

Monolith owns server rendering, form actions, keyed patches, SSE, and input
draft/focus preservation. The small browser bridge adds the press/hold lifecycle.
Dashboard requests retain Monolith's localhost Host/Origin and action-token
checks. Use a localhost URL even if binding the API to another interface.
All dashboard responses and SSE patches use the runtime's bounded nonblocking
queues; slow tabs cannot block the servo loop. Assets are embedded in the
native executable, with no browser framework, Python, or separate UI server
needed at runtime. After editing `flex/runtime/ui.css` or `controls.js`, run
`python3 flex/scripts/prepare-dashboard.py` to refresh the checked-in assets.

Verification:

```sh
python3 flex/tests/dashboard.py
# Optional, with Playwright installed (also accepts PLAYWRIGHT_MODULE/CHROMIUM):
node flex/tests/dashboard-browser.cjs
```

From the repository root:

```sh
./flex/scripts/build.sh
./build/flex/controller-demo
./build/flex/controller-demo 1000
```

The script also builds `build/flex/puppybot-runtime`, `build/flex/puppybot`,
`build/flex/puppybot-firmware-sim`, and `build/flex/puppybotgym` for Linux x86-64.
To try the runtime with a fake bus, start it in one terminal:

```sh
./build/flex/puppybot-runtime --fake --config build/flex/fake.json
```

Then use the CLI from another terminal:

```sh
./build/flex/puppybot ping
./build/flex/puppybot --json config get
./build/flex/puppybot --json arm state
./build/flex/puppybot drive steer --throttle 35 --steering 0
./build/flex/puppybot drive stop
./build/flex/puppybot arm jog --joint 0 --direction 1 --duration-ms 150
```

The fake runtime defaults to `127.0.0.1:8081`; the CLI defaults to
`ws://127.0.0.1:8081/ws`. Use `--bind IPv4:PORT` on the runtime and `--url`
on the CLI to change these. A bind port of zero selects an ephemeral port,
reported at startup. CLI hostnames use the system IPv4 resolver through libc;
numeric IPv4 addresses need no resolver. Transport deadlines begin after name
resolution. TLS and IPv6 are not implemented.

For a physical serial adapter, select its stable path and an existing calibration:

```sh
./build/flex/puppybot-runtime --servo-device /dev/serial/by-id/YOUR-ADAPTER
```

The current user needs read/write access to the selected device. Startup errors
name the path, failed operation, and Linux error number. For `permission denied`,
check the adapter target with `ls -l /dev/serial/by-id/` and its device ownership;
the serial group is commonly `uucp` on Arch or `dialout` on other distributions.
Adding a user to that group takes effect in a new login session and grants
access to all serial devices owned by the group.

The adapter uses Linux termios2, raw 8N1, and a default baud rate of 1,000,000.

The same hardware connection can run directly from source:

```sh
flexscript run puppybot.flex --servo-device /dev/serial/by-id/YOUR-ADAPTER
```

Physical mode requires an existing calibration file and starts with feedback
reads only. Inspect `GET /api/state`, then explicitly enable outputs. Disable
finishes a stop cycle before returning to monitor mode:

```sh
curl -X POST http://127.0.0.1:8081/api/control/enable
curl -X POST http://127.0.0.1:8081/api/control/disable
```

PC hardware mode and ESP32 share the same admission checks: fresh position and
temperature feedback from all four servos, no temperature above 80°C, and a
250 ms maximum sample age. A hot/failed/stale temperature cancels pending output
and disables movement; cooling and serial reconnect never auto-enable it.
PC `/api/state` reports `control.state`, temperatures, freshness and the thermal
interlock reason. Its hardware jog command lease is 500 ms. Retained HTTP state
does not renew an abandoned hardware command; callers send new requests while
jogging. Fake/Gym retain their existing simulation behavior.

Hardware calibration/ID/limit mutations are rejected through both APIs; edit
the configuration and restart. Every enable requires fresh wheel-mode
acknowledgements before speed output. The server binds localhost by default;
select another interface explicitly with `--bind`.

`--baud` overrides the serial rate. The runtime also accepts `PUPPYBOT_RUNTIME_CONFIG`,
`PUPPYBOT_RUNTIME_ADDR`, `PUPPYBOT_STSERVO_PORT`, and `PUPPYBOT_STSERVO_BAUD`;
command-line options take precedence. A missing fake configuration loads controller
defaults. Only a new fake profile substitutes steering ID 5 to keep it separate
from arm yaw ID 1; loaded profiles are preserved. There is no automatic device
scan or mDNS discovery in this milestone.

The build selects `flexscript` on PATH, then the sibling
`../flexscript/build/flex`. Set `FLEXSCRIPT_COMPILER` to an absolute executable
path to select another verified compiler. Set `FLEXSCRIPT_ROOT` to a dependency
checkout containing `libs/ml/pup/gpu.flex` (currently Flexscript branch
`codex/gpu-inference-lowering`, commit `4777273`). Shape specialization, graph
fusion, tiling and operation kernels come from that repository. No compiler or library is installed
or changed by these scripts.

The finite demo connects no hardware and models no robot physics. It runs real
controller cycles through serialized requests and fragmented status replies,
advances illustrative fake feedback, exercises the drive timeout, and releases
motion after 50 ticks. The default run prints:

```json
{"ticks":120,"serialPackets":130,"traceChecksum":2052069402,"armMode":0,"driveActive":0}
```

The demo and native runtime require no Rust, Python, interpreter, or C math
library. Rust and Python are used by the independent verification tools.

## Linux runtime and CLI

One nonblocking event loop shares a controller between the HTTP command API and
Android-compatible protocol v1 at `/ws`. Supported host operations include drive,
joint jog/stop, hold, joint and Cartesian targets, TCP jog, feedback/state,
calibration edits, and explicit calibration save. `GET /api/state`,
`GET /api/config.json`, and `GET /api/autonomy/state` expose observations.
For example:

```sh
curl http://127.0.0.1:8081/api/state
curl -H 'Content-Type: application/json' -d '{"speed":220}' \
    http://127.0.0.1:8081/api/arm/speed
curl -H 'Content-Type: application/json' -d '{}' \
    http://127.0.0.1:8081/api/calibration/save
```

Calibration saves use a private temporary file, file fsync, atomic rename, and
parent-directory fsync. Runtime changes remain in memory until explicitly saved.
JSON numbers use exact decimal-to-binary64 conversion and round-trip formatting;
JSON strings validate UTF-8 and Unicode surrogate pairs. To bound the reference
controller's repeated angle wrapping, host joint/reference angles and tool pitch
are limited to 100 turns in either direction. Oversized angles are rejected.

HTTP button-style jog/drive commands stay held until stopped and refresh every
200 ms. Wire commands retain the shared controller's deadmen and drive timeout;
a long CLI `--duration-ms` does not refresh a jog's deadman. Timed CLI jogs send
a stop at the end or on SIGINT/SIGTERM. A protocol ping barrier confirms that the
runtime processed preceding command frames before the CLI exits; the protocol
does not report whether each controller command was accepted.

Serial writes and RX draining have 20 ms bounds; response deadlines start after
a complete write and last 50 ms. Fragmented status replies are supported.
After a transport disconnect, motion is stopped and held commands are cleared.
The runtime retries the same selected path once per second, resets feedback and
mode acknowledgements, and does not resume old commands after reconnect. An
initial failure to open the selected device exits with an error. SIGINT/SIGTERM
attempt a final zero-speed cycle, with a one-second shutdown deadline.

The network server has 32 fixed connection slots, 12 KiB request buffers,
8 KiB HTTP bodies, 2 KiB WebSocket messages, and 32 KiB output queues per client.
HTTP input and queued output have two-second deadlines. It handles masked client
frames, fragmentation, ping/pong, close, and per-client telemetry subscriptions.
HTTP uses one request per connection; transfer encoding is unsupported.
An incomplete client request or missing servo response does not block socket I/O.
Controller commands are dispatched between complete serial cycles.

`--fake` advances illustrative servo feedback through the real packet codec;
it has no articulated physics, scene oracle, cameras, or captures. Simulation
operations return an explicit error. The PC runtime root serves the dashboard;
`/health` reports runtime metadata. Full simulation/autonomy workflows remain future work.
These services retain the existing unauthenticated local-network control model;
choose the bind address accordingly. Both modes default to `127.0.0.1:8081`.

## Shared implementation

- `core/words.flex`: integer/wire helpers, binary32 conversion, portable binary64
  math, and explicit native CPU lowering bindings.
- `core/layout.flex`: joint and arm storage fields.
- `core/drive.flex`: motor/steering commands and the 500 ms drive watchdog.
- `core/kinematics.flex`: calibrated FK, all four IK branches, tool pitch,
  frame transforms, wrist backoff, and the arm chain.
- `core/safety.flex`: wrapped limits, recovery direction, target approach,
  slew limits, stale/missing feedback, temperature/stall faults, and deadmen.
- `core/arm.flex`: joint commands, calibration, target/hold/jog modes,
  branch continuity, Cartesian target lead/boundary handling, and wheel-mode
  acknowledgement/recovery.
- `core/protocol.flex`: v1 command decoding, typed events, responses, and arm
  telemetry including the target extension.
- `core/config.flex`: default calibration, complete v1 configuration validation,
  and validated controller initialization.
- `core/stservo.flex`: packet construction and bounded incremental status parsing.
- `core/system.flex`: cooperative feedback, queued intents, steering, mode
  setup, and wheel writes in the same order as `Puppybot::run_once`.

Core modules perform no device I/O, sleeps, or per-tick allocation. The caller
owns buffers and supplies time, transport progress, and errors. Linux uses
binary64 CPU instructions; portable builds retain the same numerical bodies.
The vendored math and flash-code adapter are pinned by content hashes in
`vendor/manifest.json`, with upstream notices preserved.

## Storage and transport contract

Allocate disjoint buffers: 8192 bytes for a robot, 448 for configuration, and
2048 for a serial system. Call `pb_config_default`, `pb_robot_configure`, and
`pb_system_init`. A configuration buffer must not overlap the robot it initializes.
Joint records occupy 256 bytes each; named field indexes are in `layout.flex`.
The arm header also retains wheel acknowledgements, mode payloads, and scratch.
Coordinates are millimetres and angles are binary64 radian words.

Call `pb_system_begin(system, now_ms)` to start an idle cycle. Take pending
bytes with `pb_system_take_tx` and `pb_system_packet`. After a bounded platform
write completes, call `pb_system_written`; feed received bytes through
`pb_system_receive`. Keep calling `pb_system_poll` with monotonic time and
report transport errors through `pb_system_error`. Never start a second active
cycle. A status timeout is 50 ms. Another servo's status requests retransmission
without extending that response deadline. Platform write timeouts and draining
old RX bytes before each request remain platform responsibilities.

The ESP32 firmware and PC hardware runtime call `pb_system_temperature_enable(system)` after init to
read position and temperature together from registers 56..63. Successful exact
eight-byte replies update `pb_arm_temperature` and per-joint receipt times in
system words 12..15; failed replies invalidate that joint's temperature. Fake/Gym
retain the default two-byte position read. `pb_system_cancel` cancels queued
events/transport while preserving this mode and the sensor receipt times.
Both physical adapters enforce the shared policy in `core/interlock.flex`;
see [the firmware contract](firmware/README.md).

`pb_system_queue` holds at most 16 events and reports `-11` on overflow.
`pb_system_frame` checks room for a whole decoded event group before enqueueing;
its protocol/config state is decoded immediately. Callers must handle overflow.
Telemetry output requires at least 256 bytes. `pb_arm_mode_words` exports the
complete tagged mode into 128 bytes. Optional fields use explicit presence words.

The original Rust ESP32 entry point does not poll servo temperatures or wire
physical rear DC motor outputs. The new Flexscript ESP32 target polls
temperatures and applies its thermal interlock; rear DC output integration
remains unfinished.

## Verification

```sh
./flex/scripts/test.sh
```

The script runs the original Rust core's 172 tests through an isolated manifest,
without resolving the runtime's PGE/RobotDreams dependencies. It then compares
Rust and Flexscript with hardware lowering and portable math separately. The
seeded corpus currently contains 38,229 operations and 1,744,958 output words
per mode. Responses, decoded events, telemetry, full modes, numerical results,
controller state, and fake-bus packet order match bit for bit in that corpus.
This is differential evidence for the tested inputs, not exhaustive equivalence.

The reference imports the actual production Rust core. It does not reimplement
that controller. Reports under `build/flex/differential-{hardware,reference}.json`
record source/compiler hashes and both output hashes. `tests/contracts.flex`
separately checks parser memory bounds, malformed commands, queue bounds,
retransmission deadlines, timeout progress, and finite completion after bus errors.
It also checks unsigned drive timeouts through `u64::MAX`.

Host checks independently verify decimal rounding and IEEE round trips,
Unicode/JSON parsing, real loopback HTTP/WebSocket sessions, calibration restart,
slow/malformed clients, telemetry isolation, every CLI command's wire bytes,
and interrupted timed jogs. Private Linux PTYs emulate fragmented STServo replies,
mode acknowledgements, timeouts, disconnect/reconnect, and shutdown stops through
the actual serial adapter. The suite opens no physical device and sends no
multicast discovery traffic. It requires permission to create loopback sockets
and PTYs in restricted environments.

Both isolated Cargo manifests have checked-in lockfiles. On a machine without
cached dependencies, fetch them once before the offline test script:

```sh
cargo fetch --locked --manifest-path flex/tests/oracle/Cargo.toml
cargo fetch --locked --manifest-path flex/tests/core-reference/Cargo.toml
```

Malformed inputs have two intentional guards beyond the reference: nonfinite
joint-angle targets are rejected, and `i16::MIN` speed is rejected before its
absolute value can overflow. The Rust reference can panic on infinite angles
and that speed. These guards have separate contract tests; reference cases
that panic are not counted as matching comparisons.

## ESP32 and remaining migration

The [classic ESP32 target](firmware/README.md) builds a fully linked ROM image
with cached flash code, UART2 at 1 Mbaud, embedded physical calibration, bounded
serial commands/telemetry and a 500 ms continuous-command lease. It starts with
feedback reads only; explicit enable requires fresh feedback. The exact image
boots and runs the real Xtensa controller against an independent servo peer in
Espressif QEMU. `build/flex/esp32-smoke.elf` remains the older unlinked compilation
fixture; use `./flex/scripts/build-esp32.sh` for the actual firmware image.
No physical device has been opened or flashed. Real bus waveforms, robot motion,
control timing, and Wi-Fi/BLE/WebSocket/mDNS integration remain unverified.

Next milestones are articulated dynamics, Gym dataset export and training workers,
robot discovery, and wireless ESP32 firmware.
RobotDreams/PGE remain the simulation reference;
Flexscript physics currently lacks articulated joints. Existing model assets
and Android protocol v1 are retained.

An existing calibration discrepancy remains visible: `runtime/puppybot.sim.json`
sets the wrist minimum to 300, while its Rust tests and documentation expect
2400. This milestone preserves the input profiles; resolve that mismatch when
validating runtime configuration rather than silently choosing a calibration.
