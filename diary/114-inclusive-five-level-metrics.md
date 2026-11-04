# Inclusive five-level selection metrics (4 Nov 2026)

A standalone helper now reconstructs the goal's 20-action back-and-forth
measure with the final post-action window included, first virtual consumption,
and the separate 50-action odometry search-loop indicator for **all three**
selection arms, including the teacher. It also reports delivery-game counts,
deliveries per minute, parent and teacher comparisons, and level-4 doorway
placements with unresolved and zero-time cases retained in the denominator.
Rate, reliability and doorway counts remain separate; no combined promotion
decision is produced.

Two low-priority read-only replays on the saved five-level v2 selection each
reconstructed 480 games and produced identical report bytes. The helper
reproduced all legacy per-game back-and-forth counts and all previously saved
per-arm delivery totals before computing the inclusive metric. On L3, exact
first virtual consumption was 28/32 for the older student, 31/32 for the
older heading model and 32/32 for the teacher. This is consumption from
recorded simulator state, not a physical pickup. Inclusive back-and-forth
counts agree with entry 96; the teacher's separate long-search flagged actions
per search action were L1 315/5,409, L2 0/6,104, L3 105/5,645,
L4 509/6,824 and L5 780/7,078. The heuristic can miss other loops.

A separate read-only check matched first consumption, odometry and truth loop
counts and window counts for each of the 480 saved games. An independent
existing audit also matched the legacy and inclusive back-and-forth totals for
all 15 level-and-arm combinations.

The historic `treatment` arm in this replay is the older heading model, **not**
the five-prefix checkpoint. The original v2 resource monitor remains failed,
and this metric replay does not repair that receipt or independently verify
execution, raw camera provenance, the complete scene/model inputs, or data
stability during reading. It is development evidence, not a new selection,
held-out pass or robot delivery.

Six CPU tests cover exact first consumption even without a saved return-phase
row, the final 20-action window, duplicate/incomplete records, separate long
loops, doorway censoring at the horizon, and rate versus reliability
comparisons. The saved output SHA-256 is
`d0ecf9afac0dd227c3b06075b390f5346fc77c4e7dcabc5fb8542920e6997254`.
Artifact: `experiments/outbound-five-selection-metrics-v1/`.

A fresh runner still needs to freeze the fixed checkpoint and shared scenes,
re-run all three arms, invoke the strict scene/model/transition auditor,
reconstruct these metrics, and reinstall the catalog-aware inventory adapter
in every monitor and final-check subprocess. It must pin the full source chain,
retain failed runs, and use the supervised GPU/disk limits. Only then can this
helper inform a comparison; held-out testing and physical validation remain
separate requirements.
