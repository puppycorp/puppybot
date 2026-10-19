# Puppybot Flexscript port

This branch has the first migration milestone: the shared controller runs as
native Flexscript against a byte-level fake STServo bus. The Rust runtime,
firmware, CLI, Android app, and RobotDreams integration remain available as the
reference stack. They have not been replaced by this milestone.

## Build and run

From the repository root:

```sh
./flex/scripts/build.sh
./build/flex/controller-demo
./build/flex/controller-demo 1000
```

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

There is no Rust, Python, interpreter, or C math dependency at demo runtime.
Rust and Python are used by the independent verification tools.

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
  and validated controller initialization. JSON loading/saving belongs to the
  forthcoming host runtime.
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
No device has been opened or flashed.

Next milestones are Linux serial/network adapters and CLI, the Monolith
control dashboard, integrated classic ESP32 firmware, then native simulation
and autonomy workflows. RobotDreams/PGE remain the simulation reference;
Flexscript physics currently lacks articulated joints. Existing model assets
and Android protocol v1 are retained.

An existing calibration discrepancy remains visible: `runtime/puppybot.sim.json`
sets the wrist minimum to 300, while its Rust tests and documentation expect
2400. This milestone preserves the input profiles; resolve that mismatch when
validating runtime configuration rather than silently choosing a calibration.
