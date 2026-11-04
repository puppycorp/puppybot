# Fixed-selection virtual-fetch metrics

This helper is a metric layer for an eventual five-level training-family
selection. It is **not** a runnable selection evaluator and does not verify
scene provenance, model identity, actor execution, monitor completion, or
saved score integrity beyond its own arithmetic checks. A future runner must
first freeze the candidate checkpoint, scene/model/runtime/source chain and
run commands, then independently run the existing strict saved-game auditor and
the catalog-aware resource monitor. It must pin this helper and its transitive
imports, install the catalog adapter in every fresh monitor/final subprocess,
and bracket both strict and metric audits with a no-follow output inventory.
Neither this helper nor a selection result authorizes held-out use or physical
promotion.

For each of the three arms and 32 complete games per level, it verifies the
legacy saved 20-action back-and-forth count, independently reconstructs the
final-window-inclusive union, extracts first virtual consumption, and computes
the existing 50-action odometry search-loop indicator. It reports completion,
rate and candidate-vs-parent/teacher game counts separately; a better rate
cannot erase a reliability drop. Doorway placements are counted separately
per arm, with horizon-censored and zero-time placements in the denominator;
placement sets may differ across trajectories. A virtual task event is not a
physical grasp or delivery and a zero loop count does not prove no loops.

Run the six synthetic tests:

```
python3 -B -I experiments/outbound-five-selection-metrics-v1/test.py
```

The read-only archived replay accepts only the saved v2 selection root and
requires its original failed monitor status. The saved output at
`archived-v2-report.json` was reconstructed twice with identical results:

```
nice -n 19 ionice -c 3 python3 -B -I \
  experiments/outbound-five-selection-metrics-v1/metrics.py \
  build/flex/sim/levels-v2/pitch82/fresh-policy-selection-v2 > /tmp/five-selection-metrics.json
cmp /tmp/five-selection-metrics.json experiments/outbound-five-selection-metrics-v1/archived-v2-report.json
```

The archived treatment arm is the older heading experiment, **not** the new
five-prefix candidate. The v2 monitor remains failed; this later metric replay
cannot repair it, prove all input files remained unchanged during reading, or
independently attest execution. See diary 114.
