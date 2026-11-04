# Fresh-seed outbound teacher feasibility pilot (draft)

This stages a possible next learning experiment prompted by diary entry 77.
It does **not** run collection, qualify data for training, or establish a
model improvement. The earlier two-game heading-model pilot in entry 64 did
not justify expansion; this is a different candidate (`student-s1`) and must
independently pass its own screen.

The fixed design uses twelve L5 games per arm with seeds 6910000–6910011:
nine fitting games and three pilot-validation games, with each subset spanning
layouts 13, 15 and 17. Source scenes and variants are previously used
training-family scenes, so new seeds are not evidence of unseen geometry or
independent routes. They are not reserved held-out cases. The same copied
catalog, seed, 300-action horizon, initial state and simulator are intended
for the student-driven teacher-label arm and the teacher-driven arm. The
teacher uses recorded wall reference geometry; its labels are not proven
correct or physically safe.

`plan.preflight()` is read-only. It checks fixed selection seeds including the
active 7820000–7820031 comparison, legacy and current held-out seed formulas,
known validation seeds, named historical result/report roots, source scene
metadata and symlink boundaries, model files, runtime links and source hashes.
The latest local check found 3,935 historical records and skipped 2,254
symlinked directories. Those figures will change with local state; the check
does not establish unrecorded runs, semantic novelty, or model ancestry.
Do not stage or freeze while another process owns the common pitch82 lock.

`plan.prepare_catalog()` can stage a fresh shared catalog under that lock;
`plan.freeze()` then records the exact per-arm commands and environment before
play, provided no arm or monitor output exists. Neither function starts the
simulator. Any partial output is preserved. A separately reviewed executor
must invoke the planned commands under bounded per-arm and outer process
supervisors with GPU/disk telemetry; the paths and monitor receipts required
by `audit.audit()` are `student`, `teacher`, `monitor-student` and
`monitor-teacher` under the pilot output. The intended environment and
3600-second per-arm bounds are recorded by the frozen plan. GPU scheduling
must respect the existing baseline and disk floors. There is no executable
launcher or permanent catalog in this draft.

The saved-game auditor validates both complete shards, source scene and
catalog bytes including `layout.json`, matching initial state and start,
recorded teacher/actor declarations, action and label rows, task transitions,
back-and-forth counts, exact intended invocation and clean arm-supervisor
receipts. Local files and intended commands do not attest OS execution,
raw-camera provenance or teacher quality. A separately reviewed outer monitor
and its receipt must also be checked before interpreting a collected run.

The preregistered feasibility screen counts **all twelve** matched games,
including misses. A teacher pair is provisionally helpful only when it first
virtually consumes by action 200, at least 30 actions earlier than a student
pickup (or while the student remains unconsumed through action 300), and has
zero actions flagged by the existing outbound reversal heuristic. It requires
at least three helpful fitting games across two layouts, one helpful pilot
validation game and at most three games where the teacher is slower or misses
when the student succeeds. The thresholds are exploratory, chosen before this
pilot, and neither their satisfaction nor this small correlated sample proves
training benefit. A missing or malformed record censors the screen.

**A passing screen does not authorize training.** It only reports the indices
that met the rule. The present outbound-prefix mask tool retains all teacher
episodes that consume, not only qualifying pairs, so a separately reviewed
per-episode selection mechanism is still needed before using these data. A
matched baseline must preserve the existing L1–L4 and return examples. The
three validation games influence only this pilot feasibility screen and must
not be presented as independent model evaluation. Train/validation data and
fresh selection cases for a later model need separate planning and provenance;
the held-out catalog remains reserved. Auxiliary losses and
`--phase-from-valid` require the caveats in diary entry 79.

Run CPU checks with:

```
python3 -B -I experiments/outbound-teacher-prefix-pilot-v1/test.py
```

The test includes a read-only compatibility audit of the existing two-game
pilot when available; it does not perform the new collection or use the GPU.
Direct command-line execution of the plan, screen and audit modules is
disabled pending independent review and a monitored executor.
