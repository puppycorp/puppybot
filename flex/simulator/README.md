# Simulator with an external Puppybot controller

From the repository root, start the 3D environment:

```sh
flexscript run simulator.flex
```

Keep it running. It prints a private `/dev/pts/N` device and a ready-to-copy
connection command. In another terminal, run that printed command, for example:

```sh
flexscript run puppybot.flex --virtual-bus --servo-device /dev/pts/N --config ./puppybot.json
```

Replace `N` with the printed number. Open **http://127.0.0.1:8081/** and choose
**Enable outputs** after feedback appears. If a controller is already listening
there, stop it before starting the newly printed command, or choose another
`--bind 127.0.0.1:PORT` on Puppybot.

The simulator displays the owned URDF robot, floor, objects, contact geometry,
and world/TCP views. Arm encoder motion changes the rendered arm and TCP;
drive outputs move the vehicle through the existing swept collision guard.
The existing environment option is supported too:

```sh
# Requires the apartment asset to have been exported with Blender first:
flexscript run simulator.flex --environment apartment

# No display needed, still accepting the external controller:
flexscript run simulator.flex --headless
```

The first launch exports the local robot assets and mirrors the shared renderer
and physics libraries with `flex/scripts/build-sim.sh`. Later launches compile
current simulation sources without exporting the model again. Python is used
for build-time asset conversion; the long-running simulation is native. The
source VM's instruction/time budget does not apply to either process. Use
`FLEXSCRIPT_ROOT` for the shared-library checkout and `FLEXSCRIPT_COMPILER` for
a compiler override. Native rendering needs the renderer's SDL/OpenGL support.

## Process and control ownership

The two applications are independent processes. The simulator creates the PTY
and supplies peripheral state; Puppybot runs its normal core, serial parser,
safety gates, HTTP/WebSocket API, and Monolith dashboard. The simulator's robot
structure is a calibrated geometry/telemetry view, with **no controller tick**.
Its keyboard drive/jog and autonomous pickup/discovery/case policies are disabled.
The simulator HTTP/WebSocket robot command endpoints are also disabled, so they
cannot compete with the controller connected to its serial port.

Both applications use the same root `puppybot.json` by default. The simulator's
`--config PATH` is included in the printed connection command. Initialization
uses that profile's servo IDs, reference encoders, semantic joint angles and
wrapping limits. The simulator reads calibration and never saves it. Restart
both processes after changing the profile.

The dashboard labels this connection **Simulator**, while the controller retains
its guarded serial adapter behavior. It starts in monitor mode, requires explicit
enable and fresh position/temperature feedback, and retains thermal, limit,
stall and command-lease checks. Held-button renewals preserve stall timers and
latched faults. A dropped browser hold expires after 500 ms.

Arm traffic uses ordinary checksummed STServo ping, mode, position/wheel and
sensor packets. DC drive outputs have a different hardware interface and their
logical motor IDs overlap the arm servo IDs. The explicit `--virtual-bus` adapter
therefore sends a separate PTY-only peripheral frame: STServo envelope,
broadcast ID254, instruction160, payload `PBV1`, signed left/right percentages,
steering degrees and output-admission flag. It has no status reply. The runtime
accepts this adapter only on a verified Linux slave PTY; normal USB/physical
serial launches do not send these frames. No direct controller-memory or robot
command API connection exists between the two processes.

A 50 ms peripheral heartbeat refreshes the vehicle output. If the controller
exits unexpectedly or stops communicating for 500 ms, the simulator clears
motor commands and the vehicle stops. Arm velocity settles through the plant's
acceleration bound. Restarting Puppybot preserves world/encoder state and starts
its new controller in monitor mode again. Stopping the simulator removes the PTY
and invalidates controller feedback. A new simulator prints a new device path.

## Scene controls and faults

The mouse orbits/zooms the scene; V/T switch world/TCP views, K toggles colliders,
O/C controls the scene's auxiliary gripper, Space pauses, and R resets the world.
The gripper remains a simulator scene control; the current Puppybot runtime has
no gripper actuator interface on this serial bus.

Pause freezes the world and clears motor commands. Pause/reset also temporarily
makes temperature feedback unavailable, so the normal Puppybot interlock returns
to monitor mode. Resume and restored feedback never re-enable outputs by
themselves. Click **Enable outputs** again before starting another movement.
The local `/api/sim/state`, `/api/sim/views`, pause/resume/reset and auxiliary
gripper routes remain available on the simulator's printed observer port.
They are separate from Puppybot's dashboard/API listener.

For reproducible fault tests:

```sh
flexscript run simulator.flex --jam 0           # yaw jam; joints indexed0..3
flexscript run simulator.flex --temperature 81  # hot sensor blocks enable
```

Temperatures default to a synthetic 25 °C and voltage to a synthetic 12 V.
These are test inputs, not a measured thermal/electrical model. The robot arm
and vehicle use the existing kinematic/servo-motion model and swept collision
queries; loose objects and gripper contacts use the contact solver. This does
not add articulated motor dynamics or calibrated hardware prediction.

## Lightweight servo-only compatibility

The previous non-rendering servo plant remains available explicitly:

```sh
flexscript run simulator.flex --servo-only
flexscript run simulator.flex --servo-only --state build/flex/simulator-state.json
```

It prints a normal STServo connection command without the vehicle adapter.
It supports `--config`, `--jam 0..3`, `--temperature 0..255`, `--ticks N` and
atomic `--state` snapshots. It models four wrapping encoders, velocity with a
2,000 tick/s² acceleration bound and jams, with no world/vehicle/camera.
Position-mode writes set the encoder directly; wheel mode uses the plant.
The device is private to the current user and requires no serial-device group.

## Verification

```sh
python3 flex/tests/sim-serial.py  # builds/launches both root entry points
python3 flex/tests/simulator.py  # lightweight servo-only protocol compatibility
```

The external-world checks cover independent processes, serial sensor exchanges,
URDF/TCP and vehicle motion, arm/DC ID separation, exclusive control, release and
lease expiry, disable, pause/reset re-arming, controller restart/crash, simulator
disconnect, hot/jammed servos, and an actual offscreen 3D capture. The runtime,
Monolith dashboard and existing serial parser tests remain separate regressions.
