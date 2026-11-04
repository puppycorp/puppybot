# Simulator dock-clearance diagnostic (CPU prototype)

This isolated source transform adds accounting to a copy of the simulator in
`dock-survey-elevation-build-v1`. It addresses the failure in the elevated
survey trial: the detector recorded stable box observations, but the planner
reported that no mapped, arm-feasible docking pose was available. The prior
36 `reason:3` records described *circular camera-viewpoint* goal checks. They
did not identify why the separate 2,304-pose release-staging search failed.
This code does not modify the archived build or current simulator source.

When the existing `PUPPYBOT_DOCK_DIAG_DIRECTORY` is set, each `dockVision`
observation gains cumulative `clearanceDiagnostic` counts. During each
release-staging enumeration they distinguish candidates too close to the
current estimate, candidates accepted by the existing `ps_nav_clear`, and
the first rejected check: confirmed RGB floor obstacle, observed-floor map,
box margin, target exclusion, or another non-discovery/oracle case. It also
counts the existing drop-clearance checks and route attempts as passed or
failed. A passed drop-clearance check includes the existing IK and 5 mm
neighbourhood tests; a failed check does not distinguish those subchecks.
The scope is the coarse enumeration and its direct checks, not every planner
or refinement call. Counters accumulate over the simulator process.

Each existing circular-viewpoint JSON record gains `clearanceDetail`, the
first failed goal-clearance check when its original planner `reason` is 3.
The goal may instead fail another existing planner branch; in that case the
detail is zero. The observed-floor check combines **unknown floor, observed
obstacles and positions outside the map**; this diagnostic does not distinguish
them. Likewise a drop-clearance failure is not proof of an IK failure.
These values are local simulated state and do not prove physical clearance,
payload/self-collision safety, or successful movement.

The transform evaluates each original predicate once and in the original
short-circuit order. With the diagnostic directory absent, it emits no new
JSON fields or counter increments. The CPU test compiles the complete copied
simulator, then executes the actual transformed staging and planner-entry
functions with mocked map, IK and route primitives. It checks all 2,304
candidate counts, first-failure categories, success and failure paths, the
guard-call counts with diagnostics off and on, real goal rejection and both
JSON formats. These are mocked branch and serialization tests, not rendered
simulator parity, measured causality, or robot hardware validation.

```
python3 -B -I experiments/dock-clearance-diagnostic-v1/test.py
```

The staged trial copies and pins the previously elevated build and applies this
transform. It uses byte-identical binaries for two controls with high survey
disabled and one candidate with it enabled. All three record diagnostics. The
existing bounded resource monitor, dedicated supervisors, disk floors and
matched-control censoring remain in force. `audit.py` validates cumulative
stage accounting and separately reports circular-viewpoint rejection detail;
it does not attribute viewpoint failures to stage candidates. Source and
binary tamper checks, symmetric configuration, subprocess routing and a
synthetic complete three-arm audit are checked with:

```
python3 -B -I experiments/dock-clearance-diagnostic-v1/trial-test.py
```

Direct CLIs remain disabled. The builder and monitored trial wrappers require
independent review before a supervised CPU build or rendered execution. No
permanent build or GPU trial has been created. The synthetic audit mocks the
manifest verifier and manipulation subprocess. Synchronous diagnostic output
can change simulator timing, and a zeroed or missing counter is not evidence
that a candidate was safe. CPU tests do not validate rendered operation.
