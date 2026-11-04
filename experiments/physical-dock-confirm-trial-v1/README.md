# Matched simulated dock confirmation diagnostic

This stages one previously used selection case, with the same client, simulator,
case, environment, model, 90-action navigation limit and 1,499 collector polls
in every arm. The first two arms repeat search with dock confirmation disabled;
the third enables it. This is a diagnostic of the known search-box observation
failure, not held-out evaluation or a test of the physical robot. An ordinary
target handoff instead of search, a mismatched saved prefix, or incomplete arms
censors the comparison. Even with matched inputs and prefixes, the records do
not prove runtime attestation or physical causality.

The wrapper reuses the search-fallback runner, protocol and manipulation
auditors, resource monitor and process-tree supervisor. Its additional audit
requires enabled confirmation trace fields and their absence in disabled arms;
it reports runs, recorded active ticks and frame IDs, commanded-drive checks,
reasons, and whether the box was learned. `comparisonEligible` describes the
matched saved comparison. `mechanismEligible` is a separate flag requiring an
observed active confirmation, and does not mean the intervention worked. A
zero motor command is not an independent stop acknowledgement; captured frame
IDs and simulator truth do not establish hardware behavior. Completed grasp,
release and settled delivery require the separately reported manipulation
audit. Poll-limit exhaustion is censored for eventual outcomes.

Run CPU-only checks with:

```
python3 -B -I experiments/physical-dock-confirm-v1/test.py
python3 -B -I experiments/physical-dock-confirm-trial-v1/test.py
```

Before any GPU execution, independently review the wrappers and schedule the
entire baseline and run outside other GPU work. The inherited monitor checks a
30-second GPU baseline, disk and VRAM floors, bounded process cleanup, a final
independent audit and an output inventory. It retains incomplete outputs and
never overwrites them. The control flags and source hashes record local launch
intent and consistency; they are not operating-system attestations.

A separately supervised, low-priority CPU build is staged in
`build-supervisor.py`. It uses fresh paths `physical-dock-confirm-build-v1` and
`physical-dock-confirm-build-cpu-monitor-v1`, takes the pitch82 lock, and checks
disk headroom and input receipts before creating a source and library copy.
Its worker validates the resulting build and the parent rechecks the receipt.
The resulting `build.json` is checked again by the trial. Neither build nor
trial monitor CLI starts work directly. A dedicated Python process may call
`build-supervisor.py`'s `launch` once it has been independently reviewed and
scheduled; it must treat a nonzero return or a missing or unsuccessful
`result.json` as failure. A successful result has status `isolated_build_only`.
Once reviewed, call the trial monitor's `launch`
from a dedicated single-thread Python process with five absolute path arguments:

1. a new monitored output directory under `build/flex/sim/levels-v2/pitch82`;
2. the new dock build directory;
3. `physical-hybrid-hidden-v1/inputs/case.json` under the same pitch82 directory;
4. its `inputs/environment.bin`;
5. its `inputs/model` directory.

The inherited runner takes the shared pitch82 lock for its entire trial and
requires at least 36 GiB free before output creation, 34 GiB during the trial
and final audit, and 32 GiB at completion. Inputs are copied and checked against
the existing reference receipt. This is one deliberately selected case and
cannot establish reliability or rule out adverse effects elsewhere.
