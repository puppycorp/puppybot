# Matched high wrist survey diagnostic (simulator only)

This staged experiment evaluates `dock-survey-elevation-v1` in the previously
studied hybrid selection case. It applies that opt-in transform to a copy of
the archived dock-survey simulator, preserving its survey image and planner
recording. All three arms use byte-identical copied client and simulator
binaries, search fallback, dock confirmation, the same case, environment,
model, 90 navigation actions and up to 1,499 collector polls. The first two
disable `PUPPYBOT_DOCK_HIGH_SURVEY`; the third enables it. All three record
survey images and planner records in separate directories so recording is
symmetric. Synchronous file writes can still change timing.

The existing saved-protocol and independent manipulation auditor checks scene
and initial state, actor and request prefixes, identical full control journals
and outcomes, and capture/release/settling. The previous control runs
diverged during collection; a control mismatch censors the comparison. This
is one known case and an early, simulator-only diagnostic, not held-out,
physical or throughput evidence. Collector terminal replies and high-pose
acceptance are not pickup or delivery. The simulator arm guard checks fixed
scene objects but does not establish carried-payload or self-collision safety.

The audit reads each arm's original diagnostic trace and files, verifies
image/metadata and viewpoint-record counts and errors, and checks that high
survey counters exist only in the enabled arm, are monotonic and consistent.
For initial-state matching it removes only opt-in diagnostic metadata; the raw
values are separately audited. `acceptedCommandAndLaterFrameObserved` records
whether a survey frame occurred on a later tick after the latest unambiguous
accepted high-pose command. `mechanismEligible` further requires an otherwise
matched comparison and a frame associated with that request after the
simulator reports the target reached and stopped: the trace must show the
same request and target ticks, the aiming and finding-box phases, strictly
ordered acceptance, settled and frame ticks, matching camera/trace timestamps,
a settled arm, held object and encoder ticks within the simulator's
eight-tick threshold. A reset, missing association or multiple attempts in one
tick is not credited. The simulator's servo-bus stopped flags are not
independently exposed by this audit. This is source-conditioned simulator
evidence, not an independent pose measurement, physical safety or proof that
the box was visible or delivered.

`build-supervisor.py` reuses the locked low-priority CPU build and writes
fresh `dock-survey-elevation-build-v1` and
`dock-survey-elevation-build-cpu-monitor-v1` paths. `monitor.py` reuses the
bounded GPU/disk monitor, per-arm supervisors and final inventory. Its disk
floors are 36 GiB at preflight, 34 GiB during work and 32 GiB at completion.
Direct CLIs are disabled. Before execution, independently review the candidate,
builder, source pins, saved audit and subprocess rebindings. Then invoke the
supervised build in a dedicated low-priority process and `monitor.launch` in a
separate dedicated process when the GPU baseline permits. Preserve failures
and never overwrite outputs.

CPU checks:

```
python3 -B -I experiments/dock-survey-elevation-v1/test.py
python3 -B -I experiments/dock-survey-elevation-trial-v1/test.py
```

These tests compile the copied full simulator, exercise the disposable
supervised build worker and tamper checks, process routing, symmetric arm
environment, high-counter and frame association, and a synthetic matched
three-arm saved audit. They do not establish real rendered operation, actor
execution, a complete delivery, physical braking or hardware behavior.
