# One bounded floor refresh after failed box viewpoints (3 Nov 2026)

The matched trial in entry 102 failed all 36 circular camera-viewpoint plans
while the box was not freshly detected. The existing collector then failed
immediately. It already has a stationary wrist-stereo mapping routine for the
held-payload return, but that routine was only initiated when a box pose was
fresh and stable. The saved trial does not establish whether an extra scan
would reveal more floor or enable a route.

An opt-in simulator-source transform now tries the existing mapper once after
all 36 viewpoint plans fail with no fresh stable box, provided the simulator's
physical-agent mode and collection are enabled, the simulated gripper holds an
object and a box was previously observed. The old visual estimate is used only
to orient the stationary scan. On acceptance the viewpoint index resets for a
new bounded search. A second failed sweep or an unavailable mapping start
retains the existing failure path; the mapper's own job, scan and two-map
limits still apply. An accepted retry increments the diagnostic sweep ID to
preserve the first sweep's viewpoint files. No base movement is added by the
retry itself.

While this extra mapping is active, its map-result callback requires a fresh,
three-frame-stable box before invoking release-stage planning. Ending the scan
returns to the existing wrist survey; later movement and release continue to use
their existing floor, arm and fresh-box gates. The option is disabled by
default. This is a research copy and does not establish arm/held-object safety,
physical braking or a successful delivery.

Four CPU tests passed. They compiled the copied full simulator and checked
invalid configuration; a native branch probe checked disabled behavior, the
single retry, stale and unstable observations, fresh/stable staging, reset,
missing prerequisites and setup failure. A second native probe exercised the
real copied map-begin/end code, including fresh unknown-map setup, reuse of an
existing local map, return to survey and search-clock accounting. A third probe
used the real diagnostic writer and verified two sweeps preserve separate
files. The probes stub the motor, camera/worker and some planning functions.
No RGB images, actual stereo worker, map coverage,
rendered episode or physical robot were exercised; a matched, resource-bounded
rendered test and independent review are still needed.

Artifact: `experiments/dock-floor-refresh-v1/`. The existing simulator source,
archived build, prior trial outputs and model were not modified.

## Matched trial preparation (4 Nov 2026)

A same-binary three-arm trial scaffold now selects this retry only for the
candidate; both controls leave it disabled. All arms use the corrected
footprint, high-wrist survey and simulator worker barrier. Its separately
pinned barrier auditor accepts a map-frame reset only on a recorded transition
into the retry's fresh local map, and accepts a later restore only to the saved
transit-map frame. Existing local maps are reused without a reset. Eight CPU
checks passed, including a synthetic full audit with a reset, unchanged prior
control trace, forged transition rejection, real input-manifest and arm-flag
checks. The full synthetic audit mocks manifest and manipulation execution;
separate checks exercise the actual manifest and invocation validation.

Independent review found a missing eager audit import in the trial and outer
monitor pins. The source pin was added and the CPU suite passed again. A fresh
low-priority, bounded v2 build and receipt completed with
`isolated_build_only`; the prior v1 build is retained. The result is
`build/flex/sim/levels-v2/pitch82/dock-floor-refresh-build-cpu-monitor-v2/result.json`.
No rendered retry trial has yet been run, and this build by itself does not
prove the scan sees additional floor, permits a route, or completes delivery.
