# Fresh five-level selection: post-run audit with failed monitor (3 Nov 2026)

All 480 games in the fresh training-family comparison produced a saved report,
but the original resource monitor **failed** while inventorying the output.
Its status remains failed and there is no original completion or final
inventory receipt. A separately reviewed read-only post-run verifier found the
retained files and reconstructed report locally consistent; this is not a
retroactive monitor pass, held-out result, execution attestation or physical
robot test. Entry 80 records the interim audits and original failure.

Each arm used 32 games per level, seeds 7820000–7820031, a 300-action horizon
and 60 simulated seconds per game. Seeds recur across levels, so the pool is
not 160 independent seed draws. The older student is `control`, the heading
model is `treatment`, and the teacher uses reference wall geometry. Each cell
below is games with a virtual delivery / 32, deliveries per simulated minute,
and back-and-forth share of 9,600 actions, in that order.

| Level | Older student | Heading model | Teacher |
| --- | --- | --- | --- |
| L1 | 29/32; 6.00000; 4.1875% | 32/32; 6.84375; 4.7500% | 32/32; 7.46875; 11.9271% |
| L2 | 32/32; 5.21875; 5.2604% | 32/32; 5.12500; 3.6146% | 32/32; 5.21875; 6.9271% |
| L3 | 28/32; 2.06250; 1.0625% | 30/32; 2.21875; 4.0625% | 32/32; 2.68750; 1.2083% |
| L4 | 32/32; 3.00000; 1.9792% | 29/32; 2.25000; 3.5938% | 26/32; 2.34375; 10.8958% |
| L5 | 26/32; 1.12500; 4.0625% | 16/32; 0.65625; 1.3958% | 20/32; 0.87500; 16.7604% |

Level-3 first virtual consumption was 28/32, 31/32 and 32/32 respectively,
read directly from saved consumption state. Level-4 opposite-side placements
delivered by the horizon were 42/70 (60.00%), 31/59 (52.54%) and 31/58
(53.45%), respectively. The denominators include 28, 28 and 27 unresolved
placements, including one teacher placement at action 300 with zero time.
Later placements differ with the trajectory; these are not equal matched
placement sets or eventual-success probabilities.

The separate 50-action longer-search-loop heuristic produced the following
flagged actions / total search actions for the older and heading models:
L1 101/6,032 and 0/5,606; L2 51/6,035 and 50/5,982; L3 216/6,589 and
489/6,316; L4 52/6,482 and 159/7,285; L5 104/7,197 and 0/7,840. This
odometry-based heuristic is separate from the 20-action back-and-forth
metric, and a zero count does not prove absence of longer loops. Teacher
longer-loop totals were not calculated.

Across the five levels, the older student made 557 virtual deliveries in
160 simulated minutes (3.48125/min), the heading model 547 (3.41875/min),
and the teacher 595 (3.71875/min). Games with a virtual delivery were
147/160, 139/160 and 142/160. The student rates were 93.61% and 91.93% of
the teacher rate. These pooled figures do not replace per-level reliability,
doorway or loop gates; neither student meets all of them on this selection.
Virtual consumption is not physical pickup, and a virtual delivery is not a
verified grasp, release and settled object in a physical box.

All 15 arm supervisor receipts report exit 0, no timeout or signal and no
remaining workers terminated. The original outer monitor exited 1 with
`unsafe or vanished output directory`; its generic inventory rejected
directory symlinks. In the retained tree, the 160 catalog links were present,
unbroken and matched the frozen scene paths; this explains the present
rejection but cannot prove no concurrent disappearance at failure time. Saved
telemetry checks passed: 31 baseline samples over 30.00 s, maximum baseline
GPU busy 8%, minimum sampled free GPU memory 7.669 GiB and disk 44.552 GiB.
Sampling does not prove GPU exclusivity or rule out changes between samples.

The separately supervised read-only verifier reported
`postrun_consistent_original_monitor_failed`, 4,762 regular files and 160
catalog links, with output inventory SHA-256
`4fb5838dd2a0d3df6fa1eb6339a625f3613fdb2cdb7cb9899cfa805079a58773`,
monitor snapshot SHA-256
`346c52a43faeb9a92dff4946d970ee66917a47485b39e41a65718e68c75f24af`, and
verifier SHA-256
`4d91a21d8e1fdcc1f21ef9e0916d6a63e9846b6de8cb410a970d7756b36d9c3e`.
It checked the frozen inputs and prior baseline failure, verified catalog
targets without traversing links, re-audited the complete saved report, and
compared inventories before and after. These are later local consistency
checks, not an atomic snapshot or independent proof of actor computation,
raw-camera provenance or OS execution. The original monitor remains failed.

Artifacts: `build/flex/sim/levels-v2/pitch82/fresh-policy-selection-v2/`,
`fresh-policy-selection-monitored-v2/`, and
`experiments/fresh-policy-postrun-v1/`.
