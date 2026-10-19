# PuppyBotGym

PuppyBotGym manages simulation experiments. The bot runs in a separate native
firmware process; its robot-control API is independent of the Gym interface.
This first milestone implements reproducible servo cases, rollout lifecycle,
recording, inspection, and a persistent run catalog.

The management UI is a **Monolith app**: declarative Flexscript `view` definitions
render the page and compile its keyed DOM patches. Monolith handles form actions,
action tokens, and SSE updates through its bundled browser adapter. The Gym has
no handwritten browser JavaScript or JSON polling loop. FlexDB remains the run
catalog; the firmware process and robot-control endpoint stay separate.

## Build and start

From the repository root:

```sh
./flex/scripts/build.sh
./build/flex/puppybotgym serve
```

Open **http://127.0.0.1:8090**. Choose a case and seed, then launch a rollout.
The interface shows its outcome, encoder trace, actuator commands, firmware
fault, and separate robot endpoint. Pause freezes simulation time; resume
continues the same processes. Stop finalizes a cancelled rollout after the
firmware's zero-speed cycle. Completed results can be reopened after restarting
Gym. The preview samples up to 32 observations; full recordings remain on disk.

The manager defaults to `build/flex/gym-runs`, with a FlexDB catalog at `gym.db`.
Use `--data DIRECTORY`, `--bind 127.0.0.1:PORT`, and `--firmware PATH`
to change its configuration. Port zero selects an ephemeral port. The interface,
browser adapter, and stylesheet are embedded in the native executable. Gym binds
to loopback, following Monolith's host/origin and action-token checks.
One manager owns a data directory, enforced with a file lock. At most eight
workers run concurrently; the interface lists the latest 50 runs.

The build needs Python 3 and the sibling Flexscript libraries for FlexDB and Monolith.
`scripts/prepare-gym.py` creates a build-only import adapter so FlexDB uses the
controller's pinned IEEE comparison functions without duplicate declarations.
All other database modules remain upstream; source hashes are recorded under
`build/flex/gym-dependencies.json`. The scoped syntax wrapper in `syntax.flex`
runs Monolith's view compiler on `views.flex` and Monolith's server module,
skipping unrelated firmware/database sources to stay within the extension VM's
budget. It retains upstream rendering and patch generation. The native listener
hands UI requests to Monolith's dispatcher and retains `/api/gym/` for tools.
Neither Python nor the sibling source tree is needed by a built Gym executable
at runtime.

All connected tabs share Monolith's selected rollout and experiment state;
input drafts and focus stay local to each browser. Worker progress invalidates
the view at most five times per second and updates clients over SSE.

## Run without the interface

```sh
./build/flex/puppybotgym cases
./build/flex/puppybotgym run --case arm-reach --seed 42 \
    --output build/flex/reach-42
./build/flex/puppybotgym run --case joint-stall --seed 42 \
    --output build/flex/stall-42
./build/flex/puppybotgym show build/flex/reach-42
./build/flex/puppybotgym replay build/flex/reach-42
```

Output directories must be new, with an existing parent. Prior recordings are
never overwritten. `replay` streams saved observations as JSONL; it does not
rerun the simulation. `--steps N` bounds an episode (default 500, maximum
10,000); exhausted episodes fail. Exit codes are 0 for accepted cases, 1 for
failed/error cases, 2 for invalid startup, and 130 for cancellation.

For an inspectable, paused bot:

```sh
./build/flex/puppybotgym run --case arm-reach --seed 42 --realtime --paused \
    --output build/flex/interactive-42
# Another terminal:
./build/flex/puppybotgym resume build/flex/interactive-42
./build/flex/puppybotgym pause build/flex/interactive-42
./build/flex/puppybotgym stop build/flex/interactive-42
```

`endpoint.json` contains that bot's loopback WebSocket URL. The existing
`puppybot --url URL ping` and `arm state` commands connect directly to it.
Gym's management API contains only experiment operations at `/api/gym/`;
it has no drive, joint-jog, or calibration controls.

## Firmware and virtual hardware

`firmware/sim.flex` compiles the production Flexscript controller, scheduler,
packet parser, and protocol into a native Linux executable. It shares the
HTTP/WebSocket adapter with the runtime. This target is not an ESP32 emulator
or a claim that a complete flashable ESP32 application is finished.

The worker supplies a configuration and explicit clock through a bounded local
`SOCK_SEQPACKET` channel. Firmware sends STServo packets across that channel and
receives serialized status replies, fragmented into bytes before parsing.
The scripted case sends normal v1 command frames. Gym judges independent
encoder state and public telemetry; it does not inspect firmware memory.
During a pause, the firmware endpoint remains responsive while its simulation
clock is frozen. External control clients can alter a rollout; exact seeded
reproducibility assumes no external interventions.

The initial backend, **`servo-plant-v1`**, models encoder position, wheel
velocity, a 2,000 tick/s² acceleration bound, and a jammed joint. It advances
in fixed 20 ms steps. All cases use a dedicated simulation calibration,
separate steering ID 5, and a 64-step startup interval to cover feedback
initialization and the controller's one-second wheel-mode retry window.

- **arm-reach:** seed-derived targets for all four joints. Acceptance requires
  every encoder within 8 ticks, zero velocity, and stopped commands for 25
  consecutive steps.
- **joint-stall:** jam the yaw actuator while requesting a distant target.
  Acceptance requires the firmware's `stall` fault and stopped wheel outputs.

Both policies are scripted. There is no articulated dynamics, link contact,
gravity-loaded arm, camera renderer, or learned policy in this backend.
The existing RobotDreams scenarios remain reference fixtures for those stages.

## Recorded evidence and lifecycle

Each run retains:

- `manifest.json`: versioned case/policy, seed, targets, limits and plant settings.
- `config.json`: initial simulation calibration.
- `firmware.elf` and `gym.elf`: exact firmware and case/policy executable snapshots.
- `commands.jsonl`: protocol commands issued by the scripted case.
- `serial.jsonl`: actual request/status packet bytes.
- `observations.jsonl`: simulation time, plant state, and v1 firmware telemetry.
- `endpoint.json`, `progress.json`, and final `result.json`.
- `firmware.log`: child diagnostics.

Artifacts use private permissions. Summaries and controls use atomic writes;
journals are fsynced before publishing the final result. The parent reaps its
firmware process. Manager shutdown requests worker stops; parent-death signals
terminate workers and firmware after a manager crash. On restart, unfinished
catalog entries become `interrupted` unless a final result exists. A process
crash can leave a partial recording; it does not imply success or exact resume.

## Verification and next stages

`./flex/scripts/test.sh` includes independent Gym checks for seed variation,
identical repeated recordings, packet checksums and mode acknowledgements,
settled-target scoring, fault detection, cancellation, separate bot access,
FlexDB restart, locking, manager crash cleanup, and graceful shutdown.

An optional browser check against a running manager is available with Playwright
and Chromium installed:

```sh
node flex/tests/gym-browser.cjs
```

Set `PLAYWRIGHT_MODULE`, `CHROMIUM`, or `GYM_URL` if needed. It launches a real
rollout through Monolith actions, pauses/resumes it, reopens results, and saves
desktop/mobile screenshots under `build/flex/`. It checks SSE updates between
two tabs, preserved input drafts/focus across reconnects, and absence of JSON
polling or application browser scripts.

Next stages are articulated simulation and camera observations, dataset export,
then real training/evaluation workers with checkpoint lineage. Training jobs,
model promotion, full world replay, and mid-episode checkpoint resume are not
implemented in this milestone. Simulator truth should remain available to
judges and offline labeling; learned policies should use the bot's observation
and command interfaces.
