# One guarded short approach after failed box search (4 Nov 2026)

After the stationary retry in entry 108, all 36 circular-viewpoint goals were
rejected at the observed-floor check. Those goals were 30–46 cm from the cached
box, while the estimated base was about a metre away. A closer intermediate
goal might be on observed floor even when the final viewpoint is not.

A CPU-only native replay loaded the candidate's saved local coarse and fine
map and the last recorded estimated base and box poses. Of nine intermediate
goals 20–40 cm toward or slightly around the cached box, the existing planner
found paths to seven, including the straight 20 cm proposal. The probe also
reconstructed two earlier failed-command constraints from the adjacent saved
pose and drive-command trace rows; the same seven proposals planned in this
reconstruction. The constraints' exact in-memory insertion timing was not
independently attested. The straight proposal yielded four existing swept
primitives and a predicted endpoint `[-1.068226, 0.436902]` m, about 24 cm
from the estimated start and closer to the remembered box. This is a replay on
one saved local map, not a driven route, physical-clearance proof or estimate of
success rate.

`experiments/dock-short-waypoint-v1/` stages a default-off simulator-only
recovery that tries at most one short mapped approach after the existing
bounded stationary floor retry and exhausted viewpoints. It retains the
original planner's contact constraints, swept floor checks, arm travel pose,
protective stops and fresh-stable box/release gates. The route must make at
least 10 cm of predicted progress, have at most eight primitives and end within
50 cm of its start. An eight-second cooperative planner deadline and a
once-per-search latch bound extra work. An accepted route returns to ordinary
wrist survey, not release. Existing simulator arm/gripper checks have not
established held-brick, self-collision or physical-robot safety.

Three CPU tests passed: full copied simulator compilation and invalid-option
rejection; mocked branch, disabled, prerequisite, nonprogress, path-budget,
retry and timeout checks; and the real saved-map native planner replay with
reconstructed contact constraints. Two independent invocations of that replay
produced identical report bytes. No GPU episode, actual robot motion, pickup,
release or delivery tested this candidate. A separately reviewed supervised
matched rendered trial is required before drawing a behavioral conclusion.

Artifacts: `experiments/dock-short-waypoint-v1/` and
`experiments/dock-waypoint-diagnostic-v1/`.

A later same-binary trial scaffold preserves floor retry in all arms and varies
only the waypoint option; it uses the inherited disk/GPU supervisor, an
independent output inventory, and a new waypoint telemetry audit. Five further
CPU checks passed, including actual frozen-manifest and arm-flag checks and a
synthetic complete three-arm audit. The synthetic audit mocks the manipulation
judge and manifest validator; separate tests exercise the real manifest. The
scaffold was independently reviewed and its bounded low-priority CPU build
completed with `isolated_build_only`; the build receipt is under
`build/flex/sim/levels-v2/pitch82/dock-short-waypoint-build-cpu-monitor-v1/`.
No rendered trial has run.
