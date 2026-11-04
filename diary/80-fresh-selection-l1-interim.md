# Fresh policy comparison: five-level interim audits (3 Nov 2026)

The fresh training-family comparison finished its level-1 through level-5
arms, and independent read-only audits reconstructed all 32 matched games
per arm for each level and the pooled saved results. **The run is censored:**
the outer monitor later failed while inventorying the output tree, so no
successful completion or final-inventory receipt exists. These are saved
selection diagnostics, not a held-out or physical-robot result.

Each game had 300 policy actions and 60 simulated seconds; the denominator
for the back-and-forth share is 32 × 300 = 9,600 actions per arm. The
teacher uses reference wall geometry in addition to camera detections.

| Arm | Games with virtual delivery | Deliveries | Deliveries / simulated minute | Back-and-forth actions |
| --- | ---: | ---: | ---: | ---: |
| Older student, `control` | 29/32 | 192 | 6.00000 | 402/9,600 (4.1875%) |
| Heading model, `treatment` | 32/32 | 219 | 6.84375 | 456/9,600 (4.7500%) |
| Exploring teacher | 32/32 | 239 | 7.46875 | 1,145/9,600 (11.9271%) |

The separate 50-action longer-search-loop heuristic flagged 101 of 6,032
search actions (1.6744%) for the older student, and 0 of 5,606 search
actions for the heading model. It is a bounded odometry-based diagnostic;
zero flagged actions does not establish an absence of longer loops. First
virtual consumption was recorded in 29/32 and 32/32 games respectively.
The teacher's longer-loop metric was not computed in this interim check.

The same read-only audit was run after all three level-2 arms completed:

| Level 2 arm | Games with virtual delivery | Deliveries | Deliveries / simulated minute | Back-and-forth actions |
| --- | ---: | ---: | ---: | ---: |
| Older student, `control` | 32/32 | 167 | 5.21875 | 505/9,600 (5.2604%) |
| Heading model, `treatment` | 32/32 | 164 | 5.12500 | 347/9,600 (3.6146%) |
| Exploring teacher | 32/32 | 167 | 5.21875 | 665/9,600 (6.9271%) |

Both student arms recorded first virtual consumption in 32/32 level-2 games.
The longer-search-loop heuristic flagged 51 of 6,035 search actions (0.8451%)
for the older student and 50 of 5,982 (0.8358%) for the heading model. The
teacher's longer-loop metric was not computed. These are per-level results,
not a pooled score, and all three back-and-forth shares exceed 2%.

The level-3 saved audit completed after all three arm supervisors exited:

| Level 3 arm | First virtual consumption | Games with virtual delivery | Deliveries / simulated minute | Back-and-forth actions |
| --- | ---: | ---: | ---: | ---: |
| Older student, `control` | 28/32 | 28/32 | 2.06250 | 102/9,600 (1.0625%) |
| Heading model, `treatment` | 31/32 | 30/32 | 2.21875 | 390/9,600 (4.0625%) |
| Exploring teacher | 32/32 | 32/32 | 2.68750 | 116/9,600 (1.2083%) |

First consumption is read directly from saved `consumedIndex` state, not the
separately reported return-phase proxy. The longer-search-loop heuristic
flagged 216 of 6,589 search actions (3.2782%) for the older student and 489
of 6,316 (7.7422%) for the heading model; teacher longer loops were not
calculated. The old student's first-consumption and delivery counts are below
90%, while the heading model exceeds 2% back-and-forth. These selection
results do not qualify either model for held-out evaluation by themselves.

Level 4 also completed all three arms and passed the saved-game audit:

| Level 4 arm | Games with virtual delivery | Deliveries / simulated minute | Back-and-forth actions | Doorway placements delivered by horizon |
| --- | ---: | ---: | ---: | ---: |
| Older student, `control` | 32/32 | 3.00000 | 190/9,600 (1.9792%) | 42/70 (60.00%) |
| Heading model, `treatment` | 29/32 | 2.25000 | 345/9,600 (3.5938%) | 31/59 (52.54%) |
| Exploring teacher | 26/32 | 2.34375 | 1,046/9,600 (10.8958%) | 31/58 (53.45%) |

The doorway denominators count all opposite-side placements, including
unresolved cases at the horizon: 28 for control, 28 for treatment and 27
for teacher. One unresolved teacher placement occurred at action 300 with no
time to deliver. The counts differ across arms because later placements
depend on each trajectory, so they are not equal paired cases or eventual
success rates. The 50-action longer-search-loop heuristic flagged 52/6,482
search actions (0.8022%) for control and 159/7,285 (2.1826%) for treatment;
teacher longer loops were not calculated. First virtual consumption was
32/32, 30/32 and 27/32, respectively. None of these placement fractions
reaches the 80% goal in this selection set.

Level 5 completed all three arms and passed the saved-game audit:

| Level 5 arm | First virtual consumption | Games with virtual delivery | Deliveries / simulated minute | Back-and-forth actions |
| --- | ---: | ---: | ---: | ---: |
| Older student, `control` | 27/32 | 26/32 | 1.12500 | 390/9,600 (4.0625%) |
| Heading model, `treatment` | 29/32 | 16/32 | 0.65625 | 134/9,600 (1.3958%) |
| Exploring teacher | 22/32 | 20/32 | 0.87500 | 1,609/9,600 (16.7604%) |

The longer-search-loop heuristic flagged 104/7,197 search actions (1.4450%)
for control and 0/7,840 for treatment; teacher longer loops were not
calculated. Neither model reached 90% delivered games on this level.

Across the five levels, each arm has 160 one-simulated-minute games; the same
32 seeds recur across levels, so these are not 160 independent seed draws.
The independently reconstructed pool is:

| Arm | Games with virtual delivery | Deliveries | Deliveries / simulated minute | Rate / teacher |
| --- | ---: | ---: | ---: | ---: |
| Older student, `control` | 147/160 | 557 | 3.48125 | 93.61% |
| Heading model, `treatment` | 139/160 | 547 | 3.41875 | 91.93% |
| Exploring teacher | 142/160 | 595 | 3.71875 | 100% |

The pooled rates do not replace the per-level game, doorway, loop or reliability
requirements. The older student's pooled game count is higher than the
teacher's, but its delivery rate is lower. This is selection evidence, not
held-out qualification or physical delivery.

The following read-only command loaded the experiment's seed configuration
(`7820000`–`7820031`) and existing saved-game auditor. It checked each
arm's saved scores, scenes and initial placements across arms, decision and
delivery state transitions, and the teacher shard data hashes:

```sh
python3 -B -I -c 'import importlib.util,json; s=importlib.util.spec_from_file_location("selection","experiments/fresh-policy-comparison-v1/selection.py"); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); r=m.P/"fresh-policy-selection-v2/L1"; print(json.dumps(m.auditor.audit_task("L1",r,r,m.MODELS),sort_keys=True))'
```

The independent longer-loop calculation used the same module's
`qualification.strict_games` and `metrics.summarize` on each student arm.
All fifteen saved level-1 through level-5 arm supervisor receipts report exit 0, no timeout or
signal, and no remaining workers terminated. The outer monitor then exited 1
with `unsafe or vanished output directory` while applying an inventory rule
that rejects directory symlinks. The current output contains 160 catalog
directory symlinks deliberately created by `evaluate.sh`; each link target
matches the corresponding frozen scene path and none is broken. The first
current-tree path rejected by the inventory rule is
`L1/catalogs/4-0-selection/0`. This explains the present rejection but does
not prove that no directory vanished at the time of failure. The saved GPU
and disk logs pass the existing log checks, but that does not make the failed
monitor pass. These receipts and saved inputs
are local records, not independent proof of OS execution or actor computation.
Virtual consumption and delivery do not establish a physical grasp or return.
For levels 2–5 the command above was repeated with `L1` replaced by `L2`,
`L3`, `L4` or `L5` in both the output directory and `audit_task` argument; the separate
longer-loop calculation used the corresponding level number.

Artifacts: `build/flex/sim/levels-v2/pitch82/fresh-policy-selection-v2/L1/`,
`fresh-policy-selection-v2/L2/`, `fresh-policy-selection-v2/L3/`,
`fresh-policy-selection-v2/L4/`, `fresh-policy-selection-v2/L5/` and their respective `supervisors/` entries.
The failed monitor evidence is under `fresh-policy-selection-monitored-v2/`;
there is no final completion receipt.
