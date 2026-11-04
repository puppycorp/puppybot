# Matched observed-footprint trial: no delivery (3 Nov 2026)

The revised observed-floor footprint guard did not change the recorded outcome
in this one rendered simulator selection case. Both legacy-guard controls and
the revised-guard arm captured the simulated brick at tick 9,098; all three
failed at tick 11,526 with `box not reacquired from the bounded circular camera
search`. None released or delivered it. Their terminal response reported a
completed collector interaction, not a successful fetch.

All three arms used the same copied simulator and client, the same known scene
and model, high wrist survey, and experimental stereo worker barrier. The first
two selected the legacy guard and the third selected the revised guard. The
saved-output audit reports `matchedSavedPrefix:true` and
`comparisonEligible:true`: both disabled-control journals and outcomes match,
the 90 recorded navigation actor inputs and actions match across arms, and
initial saved truth matches. All three full physical-agent journals are
byte-identical. These local records do not independently attest actor execution
or camera provenance.

Each arm accepted and settled three survey requests and recorded 15 associated
frames. At failure the dock pose was not freshly valid. Each recorded 36
circular viewpoint plans rejected at the combined observed-floor clearance
check; release-stage runs and candidates remained zero. This combined check
includes unknown, occupied and outside-map conditions. These are viewpoint
plans, not release-stage rejections or evidence that 36 poses were visited.
The corrected and legacy guard call results were not instrumented, so the audit
explicitly reports `mechanismEligible:false` and
`guard_effect_not_instrumented`: identical recorded outcomes do not show
whether the revised guard was reached or affected a decision.

The worker-barrier audit checked a constant +1,280 ms clock offset and all
consecutive trace ticks. Each arm recorded 17 applied map transitions, with
identical frame and application ticks across all three. Worker elapsed wall
latency ranged from 1,004–1,058 ms, 997–1,036 ms, and 987–1,031 ms in the
baseline, second control and revised guard respectively. Barrier waiting is
excluded from simulated time; this is not a real-time performance result.

An independent saved-output re-audit reproduced `trial/audit.json` exactly.
All ten completion hashes, the 1,360-entry trial inventory, launch source pins
and resource logs verified. The resource monitor passed, and all three arm
supervisors plus outer and final supervisors exited cleanly. Across 315 GPU
samples the minimum free memory was 9.329 GiB and the maximum busy was 47%; 286
disk samples had at least 44.226 GiB free. Samples cannot establish exclusive
GPU use or exclude brief conditions between samples. This one training-family
scene is neither a held-out reliability result nor evidence of physical
pickup, braking, release or collision safety.

Evidence: `build/flex/sim/levels-v2/pitch82/observed-footprint-matched-monitored-v2/`,
including `completion.json`, `trial/audit.json`, the three manipulation traces,
and the monitored worker inventory. No historical result was replaced.
