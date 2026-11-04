# Fresh training-family policy and teacher comparison

This draft compares the existing L3/L5 DAgger `student-s1`, the fixed heading
treatment, and the exploring teacher on levels 1–5. Each arm receives the same
32 training-family scenes and seeds 7820000–7820031 per level, 300 actions,
camera pitch 82 and four eight-game parts. Seeds are shared across levels, so
the 160 games per arm are not independent replications. These are selection
layouts, not the reserved held-out layouts. This is not a promotion rule.

The saved historical comparisons show 566 virtual deliveries in 160 games
for student-s1 and 610 for the teacher, with 146 versus 140 games delivered.
These were separate historical runs with matching saved scene and initial
placement and recorded control/simulator hashes, but full old runtime and
asset identity was not recorded. They cannot establish the new comparison.

`selection.py` stages a frozen manifest, reuses `evaluate.sh`, the existing
teacher/student saved-game auditor and the existing GPU/disk monitor. The
auditor's seed constants are explicitly changed only within each new process.
It reports longer-search loops separately for both students, doorway counts,
virtual pickup and delivery, game reliability and teacher rate. Its seed
inventory checks the named prior roots and fixed prospective held-out seed
formula, not unknown earlier ancestry, semantic scene similarity or other
unrecorded history. Layout metadata must mark each scene as fitting and not
reserved. Reserved catalog content is never read.

The last comparable five-level, three-arm run used about 2.5 GiB for saved
outputs and roughly 65 minutes when extrapolated from earlier six-level runs;
both are only planning estimates. The monitor requires 38 GiB before launch,
34 GiB throughout collection and final audit, and 32 GiB at completion, with
no overwrite, shared lock, per-arm watchdog, 30-second GPU baseline and
outer subreaper. Unrelated writers can still consume disk between samples.
The absolute worker deadline is 27,000 seconds; any timeout retains partial
outputs as censored. No GPU job is started by the direct CLI.

Before execution, independently review the entire adapter and its CPU tests,
especially the seed and history boundaries, observer subprocesses, per-game
audits and failure handling. Run `python3 -B -I
experiments/fresh-policy-comparison-v1/test.py`. A dedicated single-thread
process can explicitly call `selection.freeze()` before any play and a second
dedicated, resource-monitored process can call `selection.launch()` after
review. The saved records do not independently attest actor computation,
physical pickup or robot safety.
