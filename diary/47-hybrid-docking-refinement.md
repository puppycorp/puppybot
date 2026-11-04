# 47. Hybrid docking: coarse staging and bounded refinement

_3 Nov 2026, offline diagnostic and simulator-only prototype_

The 29,980-tick trace from entry 45 reacquired the box in three stable camera
frames at step 14129. The direct release and ring-stage checks found no
approved pose, so the existing controller began a full local floor-map scan.
After that scan it reacquired the box at step 28065, again found no approved
stage, briefly searched a viewpoint, and began its second allowed map scan
at step 28301. It was still scanning at the protocol limit. The observations
explain the control flow but do not prove why each candidate was rejected.

For a closer diagnosis, a CPU-only probe reconstructed the step-12134
grasp estimate and step-28065 local pose/box estimate from the recorded trace,
with the saved RGB-derived first-scan maps (`observed-27255.bin`,
`observed-detail-27255.bin`, `safe-27255.bin`). Before this change, compiling
the current simulator source produced the same simulator SHA as the trial.
At the recorded pose, the probe found the local floor and observed footprint
clear and the box gap positive, but release IK and the ±80 mm straight-line
reach search failed. Among the 2,304 coarse ring samples, 550 were
observed-clear; two had an exact IK solution, and none passed the existing
±5 mm release-clearance check. A separate finer search around one of those
seeds found a candidate near `(0.06595, -0.26148, -0.03)` that passed the
same mapped-floor, ±5 mm clearance, route and arrival/parking checks. This
is a reconstructed-state feasibility finding, not a successful delivery.

`flex/sim/dock-search.flex` now has a simulator-only, `--agent-physical` opt-in
fallback that refines at most four exact-IK coarse seeds on a local 5 mm / 0.03
rad lattice after the ordinary search fails. It requires fresh, stable RGB at
entry and preserves the existing observed-floor, box-gap, ±5 mm IK, release
planner and arrival/parking gates. It allows at most two release-planner
calls and uses a cooperative 12-second wall deadline, including planner node
expansion. Clock failure, timeout or route-budget exhaustion clears pending
route state, latches a case failure and requests stop; callers must not start
another route or scan after the failure. The deadline cannot preempt an
individual IK or parking calculation and is not a hardware watchdog.

The CPU-only `flex/tests/sim-dock-refine-gates.py` mocks passed for opt-in and
freshness, rejected floor/IK/route/parking gates, failed and expired clocks,
planner budget, late planner results, and stopping both caller paths after a
latched failure. `flex/tests/hybrid-dock-replay.py` is prepared to replay the
actual saved state with hash checks and stale/unknown-floor negative controls.
It found a valid reconstructed stage near `(0.06727, -0.20225, -0.01636)` in
4.086 seconds and rejected stale vision and unknown floor. This is one saved
state, not a worst-case timing bound or a delivery. Physical behavior is not
established.

An independent mock exposed a transient clock-error hole inside planner
expansion: if the clock failed once and then recovered, the caller could try
another route. The planner now latches clock failure or deadline expiry while
the opt-in deadline is active, and the refinement stops immediately when the
planner returns with that fault. CPU mocks cover the transient failure,
latched expiry, and unchanged no-deadline behavior. The exact checks were:

```sh
python3 -I flex/tests/sim-dock-refine-gates.py
build/flex/control/compiler flex/sim/main.flex -o /tmp/puppybot-dock-clock-fault-review
git diff --check
```

The recorded-state replay and rendered trial described above predate this
final clock-fault fix; they do not verify the revised binary. This does not
make an individual IK or parking call preemptible, and the revised binary
still needs a supervised rendered run.

An isolated rendered candidate trial on the visible-brick selection scene
then captured the simulated brick at step 12086, released it over the box at
14690, and met the independent diagnostic settling checks at 14828. It ended
cleanly with the object still settled. The learned policy took zero actions;
the heuristic collector did the task. The trace did not record whether the
coarse stage or the new refinement produced the route, so this result cannot
be attributed to the fallback. Asynchronous map timing differed between
otherwise matching prior runs; it is one diagnostic trial, not an exact
paired comparison, held-out score or physical-robot delivery. Artifacts are
under `levels-v2/pitch82/physical-hybrid-refine-29980`.

After the transient clock-fault fix, the saved-state replay again passed,
finding the same reconstructed goal in 3.856 seconds and rejecting stale
vision and unknown floor. A fresh supervised rendered run of the revised,
instrumented binary (`physical-hybrid-refine-final-29980`) then captured
the simulated brick at step 12082, released at 14774 and met the diagnostic
settling criterion at 14900. Its trace recorded one refinement entry and one
accepted refinement plan at step 14041, no coarse-plan acceptance and no
refinement fault. The collector reached terminal and the simulated stop was
acknowledged; the supervisor reported no timeout or leftover workers.
The policy took zero actions. This establishes that refinement was exercised
in one successful hybrid simulation, not that it caused success: asynchronous
mapping differs between runs, and neither held-out nor physical-robot
delivery was demonstrated.

For future trials the physical recording now includes `boxSearch.stageDiagnostic`
counters for coarse success, refinement entries, refinement success, no solution,
timeout, clock fault and route-budget fault. Its `last` values are 0 = none,
1 = coarse success, 2 = entered refinement, 3 = refinement success,
4 = no solution, 5 = timeout, 6 = clock fault, 7 = route budget fault. Because
search runs synchronously within one tick, the counters retain completed events
even when an intermediate `last` value cannot appear in a recorded frame. These
diagnostics are restricted to opt-in physical recordings; the physical actor
uses a separate response that does not contain them. CPU-only gate tests cover
the counters and the recording guard. They do not retrospectively identify the
path taken in the completed trial.

`last` identifies the last tracked event, not necessarily the result of the
most recent stage-search invocation. For example, a later coarse search can
fail with refinement ineligible and leave an earlier coarse-success value
unchanged. Success counters record plan acceptance before subsequent travel,
parking or delivery; compare counter changes with recorded state transitions
rather than interpreting a nonzero value as proof of the completed task.

`flex/tests/run-physical-hybrid-trial.py` accepts a separate candidate binary,
checks it against a fresh build of the current source, preserves the original
29,980-tick baseline, and freezes the case, model, executable and source
archive with hashes. It records the compiler hash, checks policy kernels and
491 observed worker/runtime files against the recorded baseline, uses a
300-second process watchdog and descendant cleanup, and independently audits
the retained trace with the archived audit source.
The shared robot asset is checked before and after rather than copied; worker
files loaded lazily and scheduling are not fully pinned. Preflight passed for
candidate simulator SHA `87634763a41fd54a8b61d75262dc87907e176be59b56e59388ad5b1ed2bfb6e5`;
the preserved original is SHA
`baac590d3ff2a5eeb476bc25ce940deaa232fd36ad8ce0d8a79af76621d12a17`.
The supervisor rejects the original as a candidate. Earlier same-input trials
had different map completion and capture steps, so even matching these inputs
does not make the resulting trajectory an exact replay or a controlled measure
of improvement. The trial command was:

```sh
python3 -I flex/tests/run-physical-hybrid-trial.py --collector-ticks 29980 \
  --candidate-simulator /tmp/puppybot-dock-refine-candidate \
  build/flex/sim/levels-v2/pitch82/physical-hybrid-refine-29980
```

## Unconfirmed RGB handoff hint prototype

A separately generated simulator build can opt in to retaining one fresh RGB
sighting at the stopped physical-agent handoff. The hint is held separately
from the collector's target memory. It is only used if the first later fresh
collector observation, within 500 simulated ticks, contains a same-color
estimate within 6 cm. That later frame becomes the second distinct sighting;
a third distinct frame is still needed. An empty, stale, different or too-late
first observation discards the hint. The hint neither establishes identity
of a physical object nor marks unknown floor free, bypasses home/box
localization, or changes the existing pickup IK, routing or clearance gates.
The 500-tick (10 simulated second) limit is an unvalidated diagnostic choice.

`flex/tests/prepare-physical-handoff-hint.py` snapshots source and builds the
baseline and candidate into a new output; it does not change active simulator
sources or binaries. The feature is enabled only by
`PUPPYBOT_PHYSICAL_HANDOFF_HINT=1` on the separate physical-agent protocol.
Four CPU test groups compile the real candidate, exercise the hint's freshness,
ownership, wheel-localization, distinct-tick and unknown-map gates, and run the
actual handoff and collector-observation dispatch with test-only sensor mocks.
Independent CPU review passed; the mocks do not prove rendered behavior,
clearance, target identity, a pickup, delivery or hardware safety.

A future matched diagnostic should compare the original simulator with the
candidate disabled, then compare that same candidate disabled and enabled.
It must retain all outcomes, independently audit captured/released body and
settling, and report whether the hint was actually used before attributing any
change. The prior visible scene used zero learned policy actions; this would
measure collector handoff behavior, not solve learned navigation. No GPU trial
of the handoff hint has run.

## Staged matched handoff-hint experiment

The isolated handoff hint has received an independent CPU source and protocol review. Its tests cover the real handoff/collector dispatch with sensor mocks and the distinct-frame, age, distance, owner, camera and no-map-write gates. This is not a rendered pickup result or evidence of physical safety.

An initial, hard-disabled three-arm simulator scaffold compares the original simulator, the candidate with the hint disabled, and the same candidate with the hint enabled. The same visible-brick selection case, client, model, environment and asset are planned for each arm. The purpose is to measure simulated handoff-to-capture and eventual delivery while checking the original against the disabled candidate. The known visible case begins with a detection and does not test learned navigation. A single case cannot establish a general improvement or prove that the hint caused an outcome. Runs with no hint use, no eligible handoff, an incomplete arm or mismatched baseline are not positive comparisons.

The isolated v3 build preserves previous snapshots and pins the generated dependency import file as well as source, compiler, libraries and binaries. It changes only three reviewed simulator source files in its archived candidate. The runner plans a 300-second wall limit per arm, at most 29,980 simulated collector ticks, a 12 GiB initial and 8 GiB per-arm free-space floor, input checks and supervised worker cleanup. Historical comparable runs occupied roughly 156–292 MiB each; actual GPU memory and runtime are not established. GPU idleness and free space must be checked again when scheduling. No GPU run has been launched for this experiment.

Five CPU hint/build groups and five trial checks passed. The latter exercise the preserved prior protocol, stalled handoff and unexpected drive rejection, zero-action artifact checks, trace counter/fault checks, disabled launch CLI, and an actual auditor call on synthetic completed, mismatched and missing arms with a mocked manipulation audit. They do not yet exercise a complete three-arm run or prove the audit end to end. The comparison requires matching initial protocol metadata and simulator-truth poses across all three arms; no initial camera pixels are saved or compared. Failed or missing arms are censored; supervisor failure attempts a bounded partial audit and preserves its log. A counter first observed after handoff can include both capture and use in the same saved sample, so their separate event ordering is not independently established by those counters. The CLI remains hard-disabled.

An independent recheck reran the five trial CPU groups, confirmed the reference trace records truth at the initial observation tick, and gave a conditional go for a scheduled simulator diagnostic. Initial camera pixels, later trajectory parity and causality remain unproven; this is not a hardware claim. The launch CLI remains disabled pending scheduling.

The separately staged `flex/tests/supervise-physical-handoff-hint.py` wraps the diagnostic in the existing sampled process/HIP-mapping monitor and a subreaper watchdog. Its 1,800-second ceiling includes three 300-second arm limits, two 300-second audit allowances and 300 seconds for setup/cleanup. A separate `flex/tests/monitored-physical-handoff-hint.py` adds the existing GPU resource monitor and a 1,950-second outer subreaper: 30 seconds of baseline samples require at least 6 GiB nominal free VRAM and fewer than five consecutive samples above 10% busy; it aborts on telemetry loss or less than 2 GiB nominal free. The launchers pin inputs, refuse existing outputs or less than 12 GiB disk free, and preserve evidence on failure. Independent review conditionally approved the diagnostic, and both CLIs remain hard-disabled pending scheduling.

Four process-supervisor CPU tests and four GPU-wrapper CPU tests passed, including synthetic success, changed audit rejection, fixed-command checks and real nested cleanup on low telemetry, monitor death or pidfd failure while preserving an unrelated process. No GPU test ran. The visible case may hand off before any policy action, so the sampled monitor may not see a policy or HIP mapping; that fails its check without deleting simulation data. Seeing one policy does not prove observation of all three. One-second device samples, nominal VRAM and whole-device busy cannot prove GPU exclusivity or Kennel responsiveness. Sampling, a file mapping, and simulated stop acknowledgements do not prove GPU execution or physical safety.

The subsequently scheduled `physical-handoff-hint-monitored-v1` trial failed during its original arm; the monitor terminated the client and no three-arm comparison was completed. Its preserved telemetry shows the expected HIP inode `31550564` on stat device `0:56` but the policy's `/proc` mapping on device `0:29`. A separate CPU-only mmap of that same opened file reproduced the discrepancy; the Btrfs subvolume's stat device and the backing mapping device are different. This is evidence of a monitor identity mismatch, not a successful pickup or a proven policy failure.

A separately versioned `flex/tests/supervise-handoff-process.py` now derives the expected mapping identity from an mmap of the opened file and checks the mapped path's own stat identity as well, protecting against same-inode collisions across subvolumes. It rejects changed, different or deleted files. The handoff supervisor points at this new monitor; the earlier monitor and the failed run remain unchanged. Independent review reproduced the device discrepancy and passed nine CPU process-monitor tests, four supervisor tests and four resource-wrapper tests, including an mmap of the installed HIP file and inherited signal/cleanup cases. The reviewer conditionally approved a future scheduled diagnostic; no GPU retry has run.

