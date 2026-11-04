# 41. Goal baseline and search-loop diagnostics

_3 Nov 2026, analysis of saved games_

`levels/goal-report.py` checks the matched 32 games per level, their 300-action
(60-second) horizon, scene hashes, start events and completed delivery events.
On the entry-39 ensemble, the share of games with a delivery is 100%, 100%,
75%, 100%, 75% on levels 1–5. On level 3 the first pickup is 24/32; on level
4, 34 of 59 past-doorway bricks are delivered (58%). Back-and-forth action
share is 4.76%, 4.86%, 0%, 3.08%, 1.51%. The teacher's deliveries per
minute exceed the ensemble's on all five levels. Thus several proposed goal
thresholds are unmet. The report is diagnostic: old records do not prove
simulator-binary identity or a fresh, untouched benchmark. It does not certify
an overall pass. Output `levels-v2/pitch82/ensemble/goal-report-historical.json`.
The legacy level-4 test seed range 990000–990031 also overlaps the kturn
level-4 teacher-training seed range, even though those runs use different
layouts. A future held-out benchmark needs independently frozen, disjoint
seeds as well as audited scenes and starts.

The report also measures return near the same pose after 100 search actions;
this includes stationary periods and misses other loops. Separately,
`levels/search-loops-odometry.py` measures 50-action loops on wheel odometry
and compares simulator truth. On entry 40's selection baseline it flagged
239 search actions in 4 games, with 237 also flagged using true poses; on the
mixed ensemble, 318 in 6 games, of which 205 overlapped. The selection games
are not independent of training (entry 40). Two odometry-only detections
occurred in games that each completed two deliveries; wheel drift can be
substantial. These signals are experimental diagnostics, not a validated
intervention trigger. A recovery action needs phase information available at
runtime, localization confidence and controlled tests before deployment.

The first `runs/33` level-3 DAgger collection was stopped after three of
eight student-policy streams timed out. Its partial files remain in
`levels-v2/pitch82/search-dagger`, and must not be used as a completed
dataset. The two-game single-worker pilot confirmed that mixed aggregation
retains student-driven teacher labels and maps, but did not establish safe
eight-worker throughput. A separate four-worker pilot tests concurrency
before the full collection is retried into a new directory. That pilot
completed eight 300-action games, with no reported timeouts or blackouts;
its data is in `levels-v2/pitch82/search-dagger-four-pilot` and is not part
of the training set. Full collection was then started with four workers in
`levels-v2/pitch82/search-dagger-4workers`.

The full four-worker collection completed all 128 level-3 games. The
subsequent `levels/audit-shards.py` check passed for all 1,024 mixed source
games (896 teacher-driven and 128 student-driven), including checksums,
complete 300-action traces, timeout logs and frozen student-policy files.
The source records do not establish model receipt or kernel identity before
collection; snapshots match the current model. Selection seeds 7800000–31
are disjoint from these source shards, but the pretrained model's complete
ancestry was not audited, and selection scenes remain training layouts.
The mixed dataset was assembled with teacher-only masking; three eight-epoch
student training runs were started sequentially after recording the current
training inputs in `training-inputs.sha256`. Training loss is not task
success; candidates still require completed selection and held-out games.
