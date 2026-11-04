# Staged monitored teacher comparison

The freeze, runner and monitor command-line entrypoints are hard-disabled.
The plan is to register a separate, no-overwrite teacher plan only after the
student selection and its monitored completion receipt pass, and before any
teacher game. Registration and execution hold the common pitch82 lock. The
plan binds the student plan/receipt, teacher commands and environment, audit
sources, interpreter and evaluator utilities. Direct function calls bypass
the disabled command-line entrypoints and are for CPU fixtures only until
independent review and scheduling are complete.

Six fixed tasks each have a 3,600-second supervised teacher run and a
600-second saved-output audit; a 600-second pooled audit follows. The monitor
provides a 32,000-second worker deadline and 32,600-second outer subreaper
deadline. Read-only plan verification and the later completion snapshot each
have their own 1,800-second subreaper deadline. A standalone plan-registration
attempt also needs an external absolute watchdog; its function does not supply
one. A censored or failed task stops later work, and existing artifacts remain.
Missing `teacher-summary.json` or monitored completion means incomplete even
if a filesystem failure prevents writing a partial report.

The fixed collector datasets total 1,221,811,968 bytes; old 32-game shards
suggest about 1.76 GB for six tasks including prior trace overhead. Launch
requires 38 GiB free, runtime sampling aborts below 34 GiB, and completion
requires 32 GiB. These are conservative scheduling thresholds, not a guarantee
against rapid concurrent writes or larger traces. The GPU guard samples a
30-second baseline and aborts on lost telemetry or low memory; it cannot prove
that another GPU user's latency is unaffected.

Audits compare completed saved teacher games with both saved policy arms,
including matched initial scene and placement. The teacher has scene wall
geometry, later placements may diverge, and virtual consumption is not a
physical grasp. Reports are training-layout diagnostics, not independent
held-out qualification, proof of actual OS execution, or evidence of safe
physical behavior.
