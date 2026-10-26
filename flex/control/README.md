# Native visual control

The entire visual-control workflow runs without Python: scene construction,
simulator/process control, camera resizing, demonstration recording, dataset
packing, CNN/GRU learning, checkpoint packaging, inference, evaluation and
independent recorded-run verification are Flexscript. Shell launchers compile
or execute native binaries. No NumPy, OpenCV, PyTorch, NPZ or `.pt` dependency
remains in this workflow.

```text
TCP RGB 640×480 → native area resize → RGB 84×84 → CNN ─┐
previous controls / wheel commands / steering / contact ┼→ GRU(128) → steering, speed
previous recurrent state ──────────────────────────────┘           each in [-1,1]
```

The actor has 323,410 parameters. Training adds a 129-value auxiliary phase
head, making 323,539 trained parameters. Every CNN, GRU and head receives
gradients through full episodes. The reserved seventh feedback value is always
zero: phase labels are supervision, never actor input. No map, pose or target
coordinates enter the policy. The forward camera stays fixed after startup.

## Build

```sh
./flex/control.sh build
./flex/control.sh --help
```

Set `FLEXSCRIPT_COMPILER` to a native compiler and `FLEXSCRIPT_ROOT` to a
dependency checkout with `libs/ml/pup/gpu.flex` when necessary. The build stages
the compiler patch locally, adapts shared renderer/physics imports and generates
factories and CUDA kernels directly from Flexscript. It does not change the
dependency checkout or invoke Python generators.

The shared simulator robot asset `build/flex/sim/puppybot.bin` must already
exist. Its URDF/glTF exporter is shared simulator asset tooling, outside this
workflow. The control build reuses that geometry and never calls its exporter.
No previously generated visual-control executable, factory, kernel or dataset
is required. CUDA and a working local display/renderer are needed; hidden
rendering still requires `WAYLAND_DISPLAY` or `DISPLAY`. FFmpeg records videos
and native libpng decodes sensor PNGs during verification.

After building, `flexscript run control.flex ...` or
`build/flex/control/control` accepts the same arguments.

## Collect and train

Use new output directories whose parents exist:

```sh
./flex/control.sh collect --output build/flex/sim/control-data \
  --episodes 64 --validation 8 --seed 101000

./flex/control.sh train --data build/flex/sim/control-data/data.bin \
  --output build/flex/sim/control-policy --epochs 80 --batch 4 \
  --learning-rate-micros 700 --seed 7 --from-scratch
```

A training-only expert uses physical pose to drive out, then reverses its
trajectory after a real RGB brick sighting. Speed varies between 0.5 and 0.9.
The task consumes that brick and requires a fresh box view in the return pose.
It performs no grasp, carrying or release. Expert coordinates never enter the
student observation.

Collection directly writes `PVDATA01` data with 64-frame padded episodes. The
first `episodes-validation` trajectories fit the model; the remainder validate
it. All attempts retain videos, sensor frames and physical/decision traces.
If an expert fails, collection fails and retains `data.partial.bin`; it does not
discard failed episodes or publish a complete dataset. Successful collection
atomically publishes `data.bin` and a SHA256 receipt.

The native trainer owns batching, shuffling, full recurrent backpropagation,
weighted control MSE, phase BCE, gradient clipping, FP32 Adam, validation and
checkpoint selection. Best held-out demonstration loss selects `weights.bin`.
Test-episode outcomes do not select weights. Checkpoints use `PUPV0001` and
SHA256 receipts. Transfers use the execution stream and wait before host buffers
are reused. Add `--initial-policy DIRECTORY` to warm-start; Adam moments reset.
`init --output DIRECTORY --seed 7` creates a random policy without learning.
No converted or pretrained weights are required for scratch initialization.

## Evaluate and independently verify

```sh
./flex/control.sh run --policy build/flex/sim/control-policy \
  --output build/flex/sim/control-eval --episodes 8 --seed 110000

./flex/control.sh run --policy build/flex/sim/control-policy \
  --output build/flex/sim/control-blackout --episodes 8 --seed 110000 --blackout

./flex/control.sh run --policy build/flex/sim/control-policy \
  --output build/flex/sim/control-hidden --episodes 1 --seed 97001 --hidden-target

./flex/control.sh verify --run build/flex/sim/control-eval/110000 \
  --policy build/flex/sim/control-eval/policy \
  --output build/flex/sim/control-verified
```

Runs snapshot their policy executable, weights and kernels, reset memory per
episode, and retain physical collision/actuator guards. Each command advances
ten 20 ms ticks (5 Hz). There is no frontier planner, mapping worker or forced
scan. Blackout masks actor images only; task detection still reads real RGB.
Use matching seeds for paired normal/blackout comparisons.

`--scene DIRECTORY` accepts `case.json` and `environment.bin`; optional
`layout.json` supplies reference room bounds to the evaluation judge only.
The native hidden-target fixture has two rooms and a doorway. Hidden-target
success additionally requires leaving the starting room and at least 1.5 m of
search excursion.

Results include `summary.json`, per-episode `result.json`, `mission.mp4`,
`outcome.png`, sensor PNGs, raw actor images/feedback, `initial.json`,
`decisions.jsonl` and physical tick traces. All failures/time limits remain in
the totals. Startup camera positioning and action time are reported separately.

Verification decodes sensor PNGs, checks RGB/actor hashes, reproduces native
area resizing and own-state feedback, compares camera calibration in body
coordinates, checks every physical movement increment and replays all recurrent
commands from empty memory. It checks fresh frames, fixed arm, bounded commands
and zero mapping/scans/grasps. Pass `--blackout` for a blackout replay.

## Native tests and limits

```sh
build/flex/control/tests NEW_TEST_DIRECTORY
build/flex/control/gradient-tests build/flex/control/kernels NEW_GRADIENT_TEST_DIRECTORY
build/flex/control/policy-tests POLICY_DIRECTORY NEW_POLICY_TEST_DIRECTORY
build/flex/control/guard-tests build/flex/control/trainer build/flex/control/kernels NEW_GUARD_TEST_DIRECTORY
./flex/control.sh test
```

CPU contracts cover area integration, RGB/NCHW ordering, actor input isolation,
masked phase hints, blackout, policy packing, seeded scenes and file formats.
GPU tests independently perturb a high-gradient coordinate in each of the 16
parameter tensors, comparing central finite differences to full CNN/GRU
backpropagation. They also check Adam against independent scalar arithmetic.
No external autodiff framework supplies the oracle.
The full test command also collects two real RGB trajectories, trains a scratch
model for two epochs, executes a short bounded episode and independently
verifies its recording. That is an integration smoke test, not a success-rate
benchmark for such a briefly trained policy.

Historical Python scripts and their numerical tests were removed. Pre-removal
source is preserved only in the local experiment archive
`build/flex/sim/control-no-python/legacy-source/`. Other repository utilities
are outside this visual-control migration.

Simple return success is not room exploration. Keep normal, blackout and hidden
tests separate, retain failures and judge actual travel and return pose. This
policy is not trained for pickup and has not been tested on the physical robot.
