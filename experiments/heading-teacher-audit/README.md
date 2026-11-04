# Saved teacher/student selection audit

This CPU-only library audits already saved **training-layout simulated fetch**
outputs. It does not run or schedule a teacher, student, simulator or GPU.
Callers must separately freeze the teacher and student inputs before play,
verify monitored execution and enforce the shared experiment lock. The
recorded camera, runtime, actor input and physical robot behavior are not
authenticated by this audit.

`audit_task(name, teacher_root, student_root, models)` expects one task such
as `L2`; `teacher_root` contains `teacher/0` through `teacher/3` and
`score-teacher.json`, `student_root` contains the matching `control` and
`treatment` outputs and scores, and `models` maps those arm names to their
fixed model paths. Both student arms go through the existing strict saved-game
checks. The teacher side checks four eight-game shard reports, data headers,
sizes and hashes, all 32 games, 300 action records, score files, event/state
consistency and exact per-seed initial scene, robot and brick parity with both
students. A simulated delivery can add one protocol sequence number for the
next placement, so sequence checks account for that event. Later placements
may differ because the policies follow different trajectories.

A complete task returns `complete_diagnostic` and rates for 32 one-minute
games per arm. Missing, incomplete, mismatched or malformed evidence returns
`censored` with no rates. Each arm reports total deliveries per simulated
minute, the fraction of games with a delivery and the 29-of-32 reliability
observation. `firstReturnGamesProxy` is a virtual return-phase indicator,
not a proven physical pickup. For L4, unresolved doorway placements are
right-censored at the horizon, including placements created at action 300;
the delivered-by-horizon fraction explicitly includes those placements.

`audit_pool(reports)` accepts the completed task reports keyed `L1` through
`L5`. It requires all five and pools 160 simulated minutes per arm. If the
teacher delivers zero, student/teacher ratios are `null`; absolute rates and
reliability observations remain separate. A missing task censors the pooled
result. This library makes no automatic promotion decision or held-out claim.

Run `python3 -I experiments/heading-teacher-audit/test.py` for synthetic CPU
fixtures. They test complete and incomplete tasks, score and start mismatch,
event/state consistency, zero teacher rates and doorway censoring. They use
sparse mock datasets and mock only the dataset digest and student saved-game
loader; they are not an end-to-end simulation or evidence of actual results.
An independent review reran the seven synthetic groups and checked the
transition logic against one previously recorded game. That bounded review
does not establish a new teacher result or qualify the planned experiment.
