# Matched diverse-room outbound teacher feasibility pilot

This pilot compares the fixed `student-s1` policy driving while the exploring
teacher labels with the same teacher driving on the same 12 scenes and seeds.
Each arm collects complete 300-action level-5 virtual-fetch games, nine fitting
and three pilot-validation episodes. The explicit rows and motivation are in
diary 99. All six layouts appeared in earlier training-family collections;
this is not an unseen-room, held-out, physical, or model-improvement test. A
successful screen cannot authorize training.

`plan.py` adapts the earlier outbound pilot plan to the different diverse
scene tree. It checks exact case/environment overlap with the saved current
five-level selection and hashes all 160 selection scene pairs. It also uses
the old named-history seed and model/runtime checks. Exact hashes do not
establish semantic independence, the named history skips symlink directories,
and model ancestry is incomplete. Source scene file, model, existing control,
simulator, runtime, Python and pilot source hashes are included in the frozen
preflight and rechecked. The existing compiled control binary is deliberately
used for both arms; current source is not silently substituted. Its legacy
back-and-forth metric is audited as such, not compared to a different metric
version without reconstruction.

The worker creates a new shared catalog, freezes its input hashes and commands
before play, and runs each arm with a 3,600-second per-arm process supervisor.
The old saved-game auditor verifies the actual 12-game shards, matched starting
states, actions, labels and scene bytes; the screen scores every case, including
misses. The outbound reversal score counts complete 20-action windows strictly
before the consumption action, including a window ending at that boundary;
post-pickup actions cannot mark earlier prefix actions. When pickup is missed,
the complete 300-action horizon is the prefix. The plan and report name this
`pose20-prefix-bounded-final-inclusive-v1`; this differs from the old pilot's
full-episode mark-and-clip score. A failed arm leaves a censored partial directory.
Neither intended command records nor files alone prove OS execution, camera
provenance, teacher correctness or physical safety. Model training and held-out
evaluation remain outside this pilot.

The monitor reuses the earlier nested process cleanup, 30-second GPU baseline,
36 GiB preflight / 34 GiB active / 32 GiB final disk floors, 6 GiB baseline /
2 GiB active free-VRAM floors, sampled telemetry verification, and an independent
final output inventory. The worker is bounded to 7,500 seconds and the outer
monitor to 7,900 seconds. All outputs use fresh fixed paths; existing data are
never overwritten. Baseline and sampled telemetry cannot prove exclusive GPU
use between samples. Start only under a separately scheduled low-priority
dedicated process, after independent review, and preserve all partial outputs.
The direct worker and monitor CLIs are disabled; their importable entrypoints
are not access-control boundaries and must only be called within the monitor.

CPU checks:

```
python3 -B -I experiments/outbound-diverse-prefix-pilot-v1/test.py
python3 -B -I experiments/outbound-teacher-prefix-pilot-v1/test.py
python3 -B -I experiments/l5-teacher-rollin-pilot-v1/monitor-test.py
```

These tests use real read-only preflight inputs and synthetic process/output
fixtures; they do not run the rendered simulator, train a policy, or establish
actual capture/release. A passing pilot must still be independently audited
and evaluated on separate selection scenes before any model change.
