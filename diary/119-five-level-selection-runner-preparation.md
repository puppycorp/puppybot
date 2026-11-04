# Preparing the fixed epoch-1 five-level selection replay (4 Nov 2026)

The fixed outbound training design calls for a comparison of its epoch-1
candidate with the parent student and exploring teacher across five levels,
32 matched scenes per level and a 300-action horizon. A fresh runner is staged
at `experiments/outbound-five-selection-runner-v1/`. These are the original
training-family scenes and seeds, so this comparison is selection evidence,
not an independent held-out evaluation. It will not promote a model.

The runner retains the strict saved-game audit and adds the independently
reconstructed inclusive final back-and-forth window, exact first pickup,
level 4 doorway numerator, denominator and censoring, longer-loop measurements,
and teacher and parent comparisons. The catalog-aware inventory is installed
in each freshly imported monitor and final-audit subprocess. The earlier v2
failed monitor and its outputs remain unchanged.

CPU-only registration is guarded by nested low-priority process deadlines,
the shared experiment lock, a 38 GiB free-space floor, source and model pins,
and clean training completion, full training audit and final-inventory checks.
The GPU launcher requires clean nested registration receipts. Existing or
failed outputs are preserved. The three CPU fixture suites passed 16 tests,
covering subprocess reloads, catalog retargeting, metric agreement, and freeze
supervisor failure boundaries; they do not test a real GPU or robot.

No selection registration or GPU replay has run. The staged code requires
independent source-pin and reload review after training, then successful
monitored execution and final inventory before its results can be interpreted.
It cannot establish new-room or physical-robot performance.
