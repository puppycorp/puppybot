# Fresh policy comparison: retry after a busy GPU

The first selection attempt stopped in its GPU baseline before launching a
worker or recording any games. Five consecutive baseline samples reported
41–42% GPU busy, exceeding the existing 10% threshold. Its frozen plan,
monitor receipt, logs and telemetry remain in the v1 paths.

This adapter reuses the unchanged selection design and code with fresh v2
manifest, output and monitor paths. It permits the same cases only after
checking the v1 terminal failure, all five baseline samples, absence of v1
worker and game outputs, the saved plan, and its recorded input hashes. It
also requires the runtime symlink chain and validated scene-link identities
to match v1. It pins the v1 evidence and this adapter in the new plan and reloads v2 bindings
in every spawned monitor, runner and final-audit process. The GPU baseline,
disk thresholds, supervisor, failure censoring, and teacher/student scoring
are unchanged. The saved records establish local consistency, not execution
attestation or proof of GPU exclusivity.

No retry has been registered or run by this adapter. Its direct CLI is
disabled. After independent review, use a dedicated process to call `freeze()`
and a separate dedicated monitored process to call `launch()`, only when the
GPU is available; the existing monitor still evaluates a fresh baseline.
The v1 artifacts must remain intact. An incomplete, stopped or already-run v1
attempt must not be retried using the same seeds.

Run CPU-only checks with:

```
python3 -B -I experiments/fresh-policy-comparison-v2/test.py
```
