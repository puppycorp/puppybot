# Matched rendered evaluation of the observed-floor guard

This simulator-only diagnostic compares the archived barrier simulator's
legacy coarse-footprint guard with the current revised guard. A copied build
contains both functions and selects the revised one only when
`PUPPYBOT_SIM_OBSERVED_FOOTPRINT_V2=1`. The default is legacy and invalid
values are rejected. The client and simulator bytes are identical across all
three arms; baseline and duplicate control set the flag to 0, and the
candidate sets it to 1. All three enable the same high-wrist survey, dock
confirmation, recording and stereo-worker barrier. They use one previously
examined selection scene, not a held-out case.

The copied source is verified against the archived barrier build, the current
navigation source, compiler and build script before and after compilation.
The receipt pins the copied source and libraries, builder, client, simulator
and the full current navigation source. The build requires fresh paths and
preserves earlier inputs. Changing a pinned source after the build causes the
build verification to refuse it. The separate CPU build was run under the
existing low-priority bounded supervisor on 3 November 2026 and completed with
`isolated_build_only`. It does not establish rendered behavior.

A fresh trial must run only after independent review and resource scheduling.
The wrapper reuses the prior three-arm supervision and resource monitors:
36 GiB free preflight, 34 GiB active, 32 GiB final floor, 30-second GPU idle
baseline, 6 GiB baseline and 2 GiB active free VRAM, and a 300-second arm
wall limit. Original camera, simulator, model, environment, launch,
monitoring and trace provenance checks still apply. No direct CLI is enabled.

The trial's separate audit uses the offset-aware barrier parser from
`dock-barrier-postrun-v1`; it does not change the old censored receipt. It
validates identical control behavior and compares saved actor/action prefixes,
records manipulation events independently, verifies the high-survey and floor
clearance diagnostics for all three arms, and checks both control map
application sequences. A failed monitor, unmatched controls, missing inputs,
invalid trace or unsuccessful arm censors the result. The auditor deliberately
sets `mechanismEligible:false` because there is no per-call guard instrumentation:
this trial cannot establish that the changed guard was reached or identify a
particular guard decision. A simulated capture, command acknowledgment or
stopped state is not physical grasp, release, braking or collision safety. The
barrier removes worker latency from simulated time and is not a real-time test.

Eight CPU tests compile the full selectable simulator and a native dispatch
probe, check the known missed overlap, invalid option, source tampering,
no-overwrite, actual frozen-input manifest and flag mismatch, monitor pins,
clock offset handling, and an end-to-end synthetic saved-audit path. The
synthetic audit mocks manipulation and manifest verification; it is not a
rendered execution or a proof of OS-level execution identity.

```
python3 -B -I experiments/observed-footprint-matched-v1/test.py
```

The completed CPU build is
`build/flex/sim/levels-v2/pitch82/observed-footprint-matched-build-v2` and its
supervisor receipt is
`build/flex/sim/levels-v2/pitch82/observed-footprint-matched-build-cpu-monitor-v2/result.json`.
Only after independent review, an idle-GPU baseline and unchanged input checks,
a separately supervised Python process can call `monitor.launch` with a new
output directory under `build/flex/sim/levels-v2/pitch82/`, that build,
`physical-hybrid-hidden-v1/inputs/case.json`, its `environment.bin`, and its
`model` directory. No rendered trial has yet been launched.
