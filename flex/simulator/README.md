# Standalone serial simulator

Run from the repository root:

```sh
flexscript run simulator.flex
```

Keep this terminal running. The simulator creates a private Linux PTY, prints
its `/dev/pts/N` path, and prints a ready-to-copy connection command. In another
terminal, use that command, for example:

```sh
flexscript run puppybot.flex --servo-device /dev/pts/N --config ./puppybot.json
```

Replace `N` with the printed number. Open **http://127.0.0.1:8081/** and choose
**Enable outputs** after feedback appears. The simulator and Puppybot are
independent native processes; each source launcher builds and atomically execs
its native executable, so neither daemon runs inside the bounded source VM.
The simulator opens only `/dev/ptmx` and its own PTY. Its device is owned by the
current user and requires no USB adapter or serial-device group membership.

Both processes default to the same root `puppybot.json`, including servo IDs,
reference encoders and wrapping limits. A custom `--config PATH` on the simulator
is included in its printed Puppybot command. The configuration must already
exist and be valid. The simulator does not edit calibration. If you change the
profile, restart both processes with that same profile.

Puppybot uses its normal serial driver, STServo byte parser, HTTP/WebSocket API,
and Monolith dashboard. It deliberately reports the serial/hardware adapter mode:
virtual feedback still passes through the physical monitor/enable, temperature,
freshness, limit and command-lease gates. No `--fake` flag or controller-specific
simulation branch is needed. Dashboard hold renewals preserve the stall timer
and latched faults, and expire after 500 ms without a renewal.

## Model and faults

This backend reuses Gym's `servo-plant-v1`: four wrapping encoders, wheel-mode
velocity, a 2,000 tick/s² acceleration bound, and optional jammed joint. Steps are
20 ms on a real-time clock with bounded catch-up. The STServo endpoint supports
ping, mode reads/writes, position/wheel writes, encoder reads and combined
position/velocity/voltage/temperature reads. Writes receive normal status ACKs.
Temperature defaults to a synthetic 25 °C, and voltage to a synthetic 12 V.
These values are test inputs, not a measured thermal or electrical model.
Position-mode writes set the encoder directly; wheel-mode motion uses the plant.

Optional arguments:

```sh
# Record a current snapshot, atomically updated about ten times per second:
flexscript run simulator.flex --state build/flex/simulator-state.json

# Jam yaw (indices: yaw=0, shoulder=1, elbow=2, wrist=3):
flexscript run simulator.flex --jam 0

# Start with hot sensors to test enable rejection:
flexscript run simulator.flex --temperature 81
```

`--temperature` accepts integers 0–255. `--ticks N` exits after approximately
`N * 20` ms of modeled motion. `--state` cannot overwrite the calibration file.
State snapshots identify the model, virtual device, serial packet counts,
encoder ticks, velocity, commanded speed, wheel mode and synthetic temperature.

The simulator exposes one bus for one controller at a time. Stop Puppybot before
starting another controller on that port. Gracefully restarting Puppybot leaves
the simulator and encoder state intact; the new controller starts in monitor
mode again. Stopping the simulator removes the PTY and invalidates controller
feedback. A new simulator receives a new PTY path, so reconnect using the newly
printed command. Simulator process termination discards its state.

There is no 3D renderer, articulated/contact dynamics, gravity, vehicle movement,
or camera in this backend. The drive controls affect servo registers but do not
move a simulated vehicle through a world. Gym's seeded experiment manager stays
separate; this command provides an interactive serial device for the normal
controller.

## Verification

```sh
python3 flex/tests/simulator.py
```

The checks cover exact source launches, native lifetime beyond VM limits,
independent STServo checksums/registers/fragmentation/resynchronization, the
normal dashboard through a separate controller, encoder motion and settling,
release/lease expiry, controller reconnect, simulator disconnect, hot sensors,
stall detection and fault latching, configuration validation and failed builds.
