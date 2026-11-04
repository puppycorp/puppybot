# Matched observed-footprint evaluation preparation (3 Nov 2026)

The revised coarse-cell footprint guard from entry 95 has not yet been tested
in a rendered episode. A separate copied simulator now contains both the exact
archived legacy guard and the current revised guard, selected by an explicit
environment flag. Baseline and duplicate control use the legacy guard; the
candidate uses the revised guard. The same simulator and client binaries,
selection scene, high-wrist survey, stereo-worker barrier and diagnostic
recording are planned for all three arms. This is a previously used selection
case, not an independent held-out test.

The CPU build completed with the existing low-priority bounded supervisor and
an `isolated_build_only` receipt. The copied simulator compiled, and eight CPU
checks passed, including actual frozen-input manifest construction, arm flag
identity, a native missed-overlap probe, a synthetic three-arm audit, and the
corrected constant-clock-offset parser. The synthetic saved-audit test mocks
manifest verification and manipulation subprocess; separate checks exercise
the real manifest code and provenance. No GPU trial, physical movement, robot
recovery or delivery has been observed from this build.

Independent review found that the offset-auditor's transitive import of the
earlier barrier monitor was missing from source pins. The trial manifest and
outer monitor now pin it, and all eight checks passed again. A fresh v2 CPU
build and receipt were produced after that change; the v1 output is preserved
but its build-supervisor receipt pins the earlier runner and is not the build
to use for this trial. The v2 build verification and supervisor receipt pass.

The trial monitor and independent saved-output audit are prepared but have not
been independently reviewed or run. The audit explicitly censors the mechanism
claim: there is no per-call record establishing whether the changed guard was
reached or which decision it changed. The coarse-clear/fine-unknown limitation
from entry 95 still applies. The barrier does not account for worker latency in
simulated time, and all simulation evidence is distinct from physical safety.

Artifact: `experiments/observed-footprint-matched-v1/`. The build and receipt
are `build/flex/sim/levels-v2/pitch82/observed-footprint-matched-build-v2/`
and `.../observed-footprint-matched-build-cpu-monitor-v2/result.json`.
