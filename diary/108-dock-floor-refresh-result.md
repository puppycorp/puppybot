# Matched dock-floor refresh: no delivery (4 Nov 2026)

The opt-in stationary floor refresh ran after the first 36 box-viewpoint plans
failed, but it did **not** lead to a delivery in this one known simulator
selection case. Both disabled controls and the enabled candidate captured the
simulated brick at tick 9,098. Neither control released it; the candidate also
ended without a release or settled delivery, reporting `box not reacquired from
the bounded circular camera search` at tick 22,054. The old client reports the
collector interaction as terminal and its outcome as `unverified`; that is
not a successful fetch or the newer failure-reporting protocol.

All three arms used identical copied simulator and client binaries, the same
scene, model and 90-action navigation prefix, high-wrist survey, revised
coarse-footprint guard and experimental stereo worker barrier. The controls
left floor retry disabled; the candidate enabled it. Their saved 90 actor
inputs and actions matched, and both control physical-agent journals were
byte-identical. The saved audit reports `comparisonEligible:true` for this
one simulated comparison. It does not independently attest actor execution,
raw camera provenance or physical behavior.

In the candidate, the first sweep rejected 36 viewpoint plans at tick 11,526,
then the retry started stationary dock-floor mapping. The trace recorded a
switch from transit map frame 7,453 to a fresh local map with zero free or safe
coarse cells. The scan completed at tick 21,180, with local map frame 21,179,
81 free and 44 safe coarse cells. This is a separate local map: those counts
cannot establish a gain over the earlier transit map or prove free physical
floor. The candidate recorded 33 worker-map applications overall, versus 17
in each control; 16 occurred after the retry's local-map switch. Worker
waiting is excluded from simulator time, so this is not a real-time result.

After another wrist survey, the box was still not freshly valid. A second
sweep rejected 36 more viewpoint plans at tick 22,054, all on the same combined
observed-floor check. The two sweeps retained separate diagnostic files;
unknown floor, obstacles and outside-map conditions remain combined in that
check. No release-staging run or candidate was recorded in any arm. The audit
intentionally leaves `mechanismEligible:false`: its recorded counters and map
transitions do not independently establish floor coverage, the route planner's
full decision, or why the box was not reacquired.

An independent read-only re-audit reproduced the saved audit. All ten
completion hashes, 1,426 trial-inventory entries and launch source pins
matched; all three arm supervisors and outer and final supervisors exited
cleanly. The resource monitor passed. Across 389 GPU samples minimum free
memory was 9.124 GiB and maximum busy 10%; across 360 disk samples minimum
free space was 44.069 GiB. Sampling cannot prove exclusivity or exclude brief
unobserved events. The trace's constant simulated clock offset was +1,280 ms;
the controls each had 17 validated map applications and the candidate had 33,
with worker wall-latency ranges of 987–1,030 ms, 982–1,024 ms and
979–1,043 ms respectively.

Evidence: `build/flex/sim/levels-v2/pitch82/dock-floor-refresh-monitored-v2/`,
including `completion.json`, `trial/audit.json`, three manipulation traces,
per-sweep diagnostic records and monitored inventory. This is not a held-out
reliability result, a physical pickup, release, braking or collision-safety
test. No prior output was replaced.
