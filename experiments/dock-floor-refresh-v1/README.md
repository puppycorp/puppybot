# Experimental dock-floor refresh after exhausted viewpoints

This is an opt-in transform for a **copied simulator**, based on the verified
`observed-footprint-matched-build-v2` source. It does not change the active
simulator, its binaries or earlier experiment artifacts. Set
`PUPPYBOT_SIM_DOCK_FLOOR_RETRY=1` on a suitably built copy; the default is off
and other values are rejected.

The existing collector immediately fails when the 36 circular-viewpoint plans
all fail and the remembered box is not freshly stable. This transform allows
one extra stationary wrist-stereo floor-map attempt in that situation, only
in physical-agent simulator mode with collection enabled, a held object and
a previously observed box. The remembered box estimate is used by the
existing mapper to orient its scan; it does not authorize driving or release.
The existing map-job, two-map and scan/arm deadlines still apply. After an
accepted map start the 36-viewpoint search index resets. If the next sweep also
fails, or the map cannot start, the ordinary failure path remains in force.
An accepted retry starts a new diagnostic sweep number, preserving the first
sweep's per-viewpoint files.

During this extra scan, release-stage planning is only attempted with a fresh,
three-frame-stable box estimate. The existing planner's observed-floor,
arm-clearance and later release checks remain unchanged. On map completion,
the existing path requests a new wrist survey before search resumes. A map
setup failure remains terminal. The scanner retains the existing simulator's
arm and gripper motion checks; those checks have not established held-payload
or physical-robot collision safety.

`python3 -B -I experiments/dock-floor-refresh-v1/test.py` verifies the archived
build identity, compiles the whole transformed simulator, and tests invalid
option handling. Native state-machine probes exercise the actual transformed
search and map-finish branches using mocked sensor/actuator dependencies. A
second probe retains the real map-begin and map-end code, checks creation of a
fresh unknown local map when none exists, reuse of an existing local map,
mapping phase, retry index and return-to-survey timing,
while stubbing the motor command, camera/worker and planner. A third native
probe verifies that the actual diagnostic writer preserves both sweep files.
These are CPU-only
checks; they do not measure new floor coverage, verify a safe route, render a
scene, perform a pickup or prove that recovery completes a delivery. A fresh,
independently reviewed, supervised matched rendered trial is required.

## Staged matched rendered test

The isolated `build.py` creates one simulator containing both disabled and
candidate behavior. `run.py` sets retry off for two controls and on for the
candidate, with high survey, the worker barrier and the revised footprint guard
on in all three. `monitor.py` adapts the prior external watchdog and resource
monitor; `audit.py` and `barrier.py` inspect saved protocol and trace data. The
barrier parser accepts a map-frame reset only when the trace shows the retry
starting its fresh local map, and accepts a later return only to the recorded
transit-map frame. A malformed, missing or unexplained transition is censored.
The retry mechanism remains marked unverified: its trace counter alone does not
establish observed-floor gain, a safe route or a successful recovery.

Eight CPU tests in `trial-test.py` cover copied build/option dispatch, real
manifest construction and flag rejection, synthetic reset/restore traces and
forgeries, the saved previous baseline trace, and a complete synthetic
three-arm audit. The end-to-end fixture mocks actual manifest and manipulation
verification; separate tests exercise the real manifest checks. After review
found a missing transitive audit-source pin, the bounded CPU supervisor wrote
a fresh `build/flex/sim/levels-v2/pitch82/dock-floor-refresh-build-v2/` and
`.../dock-floor-refresh-build-cpu-monitor-v2/result.json` with status
`isolated_build_only`; the earlier v1 build and receipt are preserved. No
rendered run has been launched. Direct CLIs remain
disabled; independently review the full source, pinned dependency chain,
resource monitors and saved-run auditor before scheduling any GPU test.
