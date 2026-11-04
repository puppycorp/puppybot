# Matched four-player training-family diagnostic

This is a proposed evaluation of the two fixed epoch-1 models from the
matched training run. It adds 320 virtual-fetch games: 32 games on each of
five levels for each new model, 300 actions per game. It compares them with
the original parent and exploring teacher's **previously saved** games from
the successfully monitored v3 selection. Those reference games ran earlier,
under separate resource telemetry; they were not run simultaneously with
the proposed new games. The auditor matches the frozen scene bytes, initial
placements, seeds, horizon, simulator/control/evaluator binaries and HIP
runtime link chain before comparing. It re-audits the full previous inventory
and saved games, and the completed paired-training model packages.

All scenes are reused training-family data; two L5 cases were subsequently
added to fitting. This is a diagnostic of possible regressions, not an
independent selection, held-out or physical robot evaluation. No candidate
is automatically chosen or promoted. Virtual pickup/delivery is not a
verified physical grasp and release. The fixed legacy simulator score format
is checked explicitly; the final-window-inclusive 20-action back-and-forth
metric is reconstructed separately, as are the L3 first-consumption, L4
doorway denominator/censoring, longer-search-loop heuristic, per-level
teacher rate and matched wins/losses against parent and teacher.

Fresh paths are `fresh-policy-selection-plan-v4.json`,
`fresh-policy-selection-v4/` and `fresh-policy-selection-monitored-v4/`
under `build/flex/sim/levels-v2/pitch82/`; v3 and all previous runs are
preserved. Direct command-line execution is disabled. Registration and launch
must be run in separate reviewed dedicated processes after all CPU tests and
independent review pass. Registration checks the exact old selection and
training evidence before freezing. A lock-owning subreaper guardian covers
the 30-second idle GPU baseline, all 10 serial model/level supervisors, the
separate final review and descendant cleanup. It checks 38 GiB through
baseline, 34 GiB during active work, and escalates cleanup under 32 GiB; each
arm additionally records a 34 GiB precheck. Failures retain their partial
output and are censored. The last launcher recheck is read-only and disk
bracketed after the guardian exits; it is not continuously sampled or locked.

The prior v3 directory sizes suggest approximately 1.05 GiB for two new
student arms, but that is an estimate, not a guarantee. The actual bytes,
filesystem occupancy, concurrent workloads and sampled resource minima must
be checked live. The checks establish local saved-output consistency, not
raw-camera provenance, an atomic snapshot, OS execution attestation, or
complete model ancestry. They do not repair or relabel earlier experiments.

CPU fixtures (no GPU is launched):

```
python3 -B -I experiments/matched-four-arm-diagnostic-v1/audit-fixture-test.py
python3 -B -I experiments/matched-four-arm-diagnostic-v1/guardian-fixture-test.py
```
