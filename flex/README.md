# Puppybot Flexscript port

This branch contains the shared controller, a native Linux HTTP/WebSocket and
serial runtime, and a protocol v1 command-line client in Flexscript. The Rust
stack remains the reference for the migration. The dashboard, ESP32 firmware,
Android app, and RobotDreams integration have not been replaced.

[PuppyBotGym](gym/README.md) now provides a separate Monolith experiment interface and
headless rollout runner. It launches the native firmware target in its own
process, supplies virtual STServo hardware, and records seeded arm/fault cases.
Its initial servo plant has no articulated/contact physics. Gym manages runs;
robot controls connect independently to each bot's endpoint.

## Build and run

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

The fake runtime defaults to `127.0.0.1:8080`; the CLI defaults to
`ws://127.0.0.1:8080/ws`. Use `--bind IPv4:PORT` on the runtime and `--url`
on the CLI to change these. A bind port of zero selects an ephemeral port,
reported at startup. CLI hostnames use the system IPv4 resolver through libc;
numeric IPv4 addresses need no resolver. Transport deadlines begin after name
resolution. TLS and IPv6 are not implemented.

For a physical serial adapter, select its stable path and an existing calibration:

```sh
./build/flex/puppybot-runtime --servo-device /dev/serial/by-id/YOUR-ADAPTER \
    --config puppybot/runtime/puppybot.json --bind 127.0.0.1:8080
```

The adapter uses Linux termios2, raw 8N1, and a default baud rate of 1,000,000.
`--baud` overrides it. The runtime also accepts `PUPPYBOT_RUNTIME_CONFIG`,
`PUPPYBOT_RUNTIME_ADDR`, `PUPPYBOT_STSERVO_PORT`, and `PUPPYBOT_STSERVO_BAUD`;
command-line options take precedence. A missing configuration loads controller
defaults. Only a new fake profile substitutes steering ID 5 to keep it separate
from arm yaw ID 1; loaded profiles are preserved. There is no automatic device
scan or mDNS discovery in this milestone.

The build selects `flexscript` on PATH, then the sibling
`../flexscript/build/flex`. Set `FLEXSCRIPT_COMPILER` to an absolute executable
path to select another verified compiler. No compiler or library is installed
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
curl http://127.0.0.1:8080/api/state
curl -H 'Content-Type: application/json' -d '{"speed":220}' \
    http://127.0.0.1:8080/api/arm/speed
curl -H 'Content-Type: application/json' -d '{}' \
    http://127.0.0.1:8080/api/calibration/save
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
operations return an explicit error. The root endpoint reports runtime metadata;
the separate robot-control dashboard and full simulation/autonomy workflows remain future work.
These services retain the existing unauthenticated local-network control model;
choose the bind address accordingly. Hardware mode defaults to `0.0.0.0:8080`.

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

`pb_system_queue` holds at most 16 events and reports `-11` on overflow.
`pb_system_frame` checks room for a whole decoded event group before enqueueing;
its protocol/config state is decoded immediately. Callers must handle overflow.
Telemetry output requires at least 256 bytes. `pb_arm_mode_words` exports the
complete tagged mode into 128 bytes. Optional fields use explicit presence words.

The production temperature sampling and physical rear DC motor backend were
not wired in the original ESP32 entry point. Exposing their controller state
here does not add those hardware integrations.

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

The complete controller path cross-compiles to `esp32-xip-elf`, including the
pinned classic-chip cache initializer. Its portable numerical code exceeds the
128 KiB all-RAM code target, so firmware must use flash code. The test output
`build/flex/esp32-smoke.elf` is an unlinked cross-compilation fixture, not a
flashable Puppybot release. Device execution, control-loop timing, Wi-Fi load,
UART2 at 1 Mbaud, WebSocket/mDNS, and restoration/flashing remain unverified.
No physical device has been opened or flashed. Linux serial timing and behavior
have been checked with PTYs; physical-bus waveforms and robot motion remain
unverified.

Next milestones are articulated Gym simulation, datasets and training workers,
the separate robot-control interface and discovery, and integrated classic
ESP32 firmware.
RobotDreams/PGE remain the simulation reference;
Flexscript physics currently lacks articulated joints. Existing model assets
and Android protocol v1 are retained.

An existing calibration discrepancy remains visible: `runtime/puppybot.sim.json`
sets the wrist minimum to 300, while its Rust tests and documentation expect
2400. This milestone preserves the input profiles; resolve that mismatch when
validating runtime configuration rather than silently choosing a calibration.
