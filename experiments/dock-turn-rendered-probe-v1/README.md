# Private rendered dock-turn fault proposal

This is **preparation only**. No rendered experiment has been run. The
direct command-line entry points are disabled pending independent review;
the monitor and runner can start GPU-backed simulator processes when called
by a separately scheduled process. No physical robot is addressed.

The proposed scenario is the visible-brick hybrid case saved under
`build/flex/sim/levels-v2/pitch82/physical-hybrid-refine-final-29980/`.
Its trace entered simulated carrying at tick 14507 and placing at 14751,
released at 14774, and passed its independent settling check. The base joint
moved from 1090 to 1044 while the other arm joints stayed fixed, then they
moved: this supports a release-yaw interpretation but the old trace did not
record the internal turn flag. Box observations stayed fresh, so that run is
not evidence of a natural loss or of the new wait. The actor took zero
navigation actions. These are reused selection inputs, not held-out data.

The exact source of that old successful run predates the newly integrated
wait. The six private builds use *current* worktree source and the saved
immediate-stop baseline, with matching injected instrumentation; therefore
they can compare the wait itself but may not reach the old trajectory. A
missed turn, an unstable or changed box before injection, and missing trace or
stop evidence are censored. The asynchronous mapping worker means matched
inputs do not ensure identical trajectories.

The reference harness is `flex/tests/run-physical-hybrid-trial.py`, using:

- `physical-hybrid-visible-trial/case.json`, the apartment environment,
  `more1-s0` model and kernels, and the saved matching physical simulator
  client; hashes are in the old `supervisor-inputs.json` and the new build
  manifest. The build rejects a changed case, environment, asset, model,
  receipt, policy or client.
- `SDL_VIDEODRIVER=offscreen`, 30 navigation actions, 1,499 collector polls
  of at most 20 ticks, and a 300-second arm watchdog. The old arm used about
  58 seconds and 156 MiB, not a forecast or upper bound.

The control uses the immediate-stop source saved in
`experiments/dock-turn-reacquire-current-v1/baseline-case.flex`; the candidate
is required to equal the current integrated `flex/sim/case.flex`. For each,
the fault is 0, 10 or 60 simulated ticks. A trigger is recorded once, just
after the existing stateful settlement call. Only if the immediately prior
box estimate is fresh, stable and unchanged does the fault invalidate that
observation and suppress detections during the chosen interval. Scheduled
camera captures are still requested; this is synthetic detection loss, not a
camera fault model. The 10-tick arm can rebuild three detector observations
before the 50-tick wait deadline. The 60-tick arm should stop at the deadline.
The nonfault arms check whether both controls reach normal lowering and any
later delivery. The `turnProbe` trace fields record the pre-fault evidence,
trigger, suppressed observations, waiting state and first lowering attempt.
No fault is injected when the precondition fails.

`test.py` compiles all six complete variants, then exercises their injection,
wait and stop paths with mocked RGB, detector, settlement and actuators. It
does not establish rendered sensing, delivery, physical safety or a stopping
distance. `audit.py` locally rejects missing triggers and incomplete/unclean
outcomes and distinguishes mechanism mismatches from simulated deliveries.
Its fixture tests run with `python3 -B -I .../audit-test.py`. The local auditor
does not validate the worker, provenance manifest, GPU/disk history, frozen
assets or source identity; its output alone cannot certify a comparison.

`build.py` prepares private source and binary copies when explicitly called by
a future reviewed supervisor. It checks the current candidate against the
baseline transform, pins source, library, compiler, client, scene, asset,
model and reference receipt hashes, recompiles all six and records them in a
new exclusive output directory. It never executes a simulator.

`run.py` and `monitor.py` stage a **two-arm pilot** only: `control-10` then
`candidate-10`. A dedicated `guardian.py` process owns the shared
`.l4-matched.lock` and remains a subreaper until its coordinator and all
descendants have exited. It watches its caller with a pidfd; it preserves
the lock and kills/reaps adopted descendants after a caller or coordinator
failure. A guardian resource stream covers the entire coordinator lifetime,
including the original baseline and final inventory subprocess, and continues
through cleanup. Below 34 GiB it aborts, and below 32 GiB or on an unavailable
resource sample it escalates immediately. The guardian's 4,200-second outer
deadline does not bound an uninterruptible OS operation. These processes use
the existing worker supervision and frozen six-build source/dependency/executable
inventories, scene, model kernels, robot asset and worker snapshots. They
require a 30-second GPU baseline and 38 GiB free before the trial, a 34 GiB
active floor and a 32 GiB final floor. Per-arm processes have 300-second
deadlines; errors leave the output and any partial runs in place. The inherited
outer monitor verifies resource logs, reruns the comparison audit and checks
the complete output inventory before writing a completion receipt. Monitoring
samples do not establish GPU exclusivity or rule out a brief dip between
samples; lazy-loaded worker/runtime files and
raw-camera provenance remain limited. This is not a six-arm runner.

`runner-test.py` exercises ordering, process failures, retained partial output,
lock identity and resource-sample coverage using CPU mocks. `guardian-test.py`
uses CPU-only processes to kill a coordinator and its caller, exercise an
escaped session leader, and lower disk samples through 34 and 32 GiB during
abort. `build-test.py` builds and
recompiles all six in a temporary directory, and rejects changed generated
dependencies, source and binary. Independent review is required before any
GPU run, and the untouched 0- and 60-tick modes still need a reviewed adapter.
No result should be promoted to a held-out or physical claim. Further
camera-frame provenance is required to interpret independent RGB exposure and
detection reliability.
