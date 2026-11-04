# PuppyBot

PuppyBot's controller, Linux runtime, simulator, visual-control training and
classic ESP32 serial firmware are implemented in Flexscript. The maintained
source is in [`src/`](src/README.md), organized by purpose.

## Run

From the repository root:

```sh
flexscript run puppybot.flex
```

Open **http://127.0.0.1:8081/** for the robot dashboard. The default is a fake
servo bus. The launcher compiles and executes the native runtime; configuration
comes from [`puppybot.json`](puppybot.json). See the
[controller instructions](src/README.md) for physical serial control and output enable.

Run a separate 3D simulator with `flexscript run simulator.flex`. It prints the
private serial device and the controller connection command. For the lightweight
servo model use `flexscript run simulator.flex --servo-only`.

For autonomous simulation and visual-control experiments:

```sh
flexscript run sim.flex --list-cases
flexscript run sim.flex --case house-blocks-into-box --drift 10
./src/control.sh build
```

See [simulation](src/sim/README.md), [visual control](src/control/README.md),
[Gym](src/gym/README.md) and [exploration](src/exploration/README.md).
Python remains in experiment orchestration, data preparation and independent
verification; the repository is not exclusively Flexscript.

## Build and verify

Install Flexscript and keep the sibling `../flexscript` Git checkout available.
The native build snapshots a pinned compiler/library revision from that checkout
into `build/native-toolchain`; it never changes the sibling checkout. Set
`FLEXSCRIPT_SOURCE` to use another checkout containing that revision. To supply
an already verified matching toolchain instead, set `FLEXSCRIPT_COMPILER` and
`FLEXSCRIPT_ROOT` (and `FLEXSCRIPT_SOURCE` for firmware link tooling).

```sh
./src/scripts/build-runtime.sh
./src/scripts/test-runtime.sh
```

These commands build and test the native controller, HTTP/WebSocket runtime,
CLI, serial simulator and simulated firmware without the GPU training toolchain.
The tests use loopback sockets and private PTYs, not a physical robot.

The broader `./src/scripts/build.sh` and `./src/scripts/test.sh` include Gym,
vision, controller differential tests and additional tooling. They require a
compatible Flexscript source checkout and GPU libraries; set `FLEXSCRIPT_ROOT`
and follow [the detailed build instructions](src/README.md).

For classic ESP32 serial firmware:

```sh
python3 src/scripts/prepare-esp32-tools.py
./src/scripts/build-esp32.sh
```

See [firmware wiring, verification and flashing](src/firmware/README.md).
The Flexscript target is serial-only: Wi-Fi/WebSocket/mDNS, Android wireless
control, persistent calibration and physical hardware qualification are still
separate work. Replacing the source layout does not establish those capabilities.

## Repository layout

| Path | Purpose |
| --- | --- |
| `src/core/`, `src/transport/` | Shared controller, kinematics, safety and protocol |
| `src/runtime/`, `src/host/`, `src/cli/` | Linux service, dashboard, serial adapter and CLI |
| `src/firmware/`, `src/platform/` | ESP32 and simulated firmware adapters |
| `src/sim/`, `src/simulator/`, `src/gym/` | 3D simulation, serial plant and rollout UI |
| `src/control/`, `src/ml/`, `src/vision/`, `src/exploration/` | Learning, inference and navigation |
| `src/scripts/`, `src/tests/` | Build tools and verification |
| `tests/reference/rust-core/` | Original Rust controller used only as a test oracle |
| `datasets/`, `experiments/`, `diary/` | Dataset recipes, experiment programs and research notes |
| `build/flex/sim/` | Local generated datasets and experiment artifacts |
| `models/`, `robotdreams/` | Owned assets and retained historical scene/calibration evidence |
| `android/`, `python/`, `design/` | Android client, servo service utilities and electronics |

The Rust runtime, CLI, ESP32 firmware and collision tools are retired from the
maintained source tree; earlier versions remain in Git history. The native
build workflow packages Flexscript runtime binaries and the Flexscript ESP32
ROM image. The Android client remains a separate application.

`flex` is a compatibility symlink to `src`; `puppybot/core` points to the Rust
test reference. New development uses the canonical paths. Existing experiments,
receipts and `build/flex` output paths are not renamed by this migration.
Source changes still require fresh provenance checks before an old run can be
repeated; a compatibility path does not guarantee identical source hashes.

## Dataset storage

Actual data lives primarily under `build/flex/sim/`; `datasets/` contains recipes
and documentation. Follow [the storage rules](AGENTS.md#experiment-storage):
budget every run, preserve required evidence, review retention when it finishes,
and verify physical space recovered after cleanup. Git-ignored data is not
necessarily disposable.
