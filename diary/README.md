# Fetch experiment diary (chase-v1)

One file per experiment or finding, numbered in order (`NN-name.md`), newest
last: what was tried, the result, the verdict and where the data and scripts
are. Scores are deliveries per minute on the 32 test games, mean of three
seeds unless noted; one seed varies by about 0.3, so differences below about
0.4 are noise. Full tables and method details are in
[README.md](../datasets/visual-control/chase-v1/README.md). Run scripts are in [levels/runs](../datasets/visual-control/chase-v1/levels/runs),
analysis tools in [levels](../datasets/visual-control/chase-v1/levels); data is under
`build/flex/sim/levels-v1` (`pitch82/` from [entry 9](09-camera-pitch-82.md) on).
A new finding gets the next number and a line under Entries below.

## Where things stand (1 Nov 2026, old level numbering: 4 other room, 5 doorway drill)

- Since then (new numbering, `levels-v2/pitch82`): best single students
  `more1-s*` ([entry 38](38-more-epochs.md)): standard 4.93, level 1 6.75,
  level 4 2.47, level 5 0.93, against the teacher's 7.69, 2.88 and 1.25.
  Back and forth is no longer what limits them ([entry
  36](36-teacher-back-and-forth-unlabelled.md)); the gap is speed on ordinary
  fetches.
- Best ordinary fetching: students fine-tuned from `chase-v1/train-d5-agg` on
  640 noisy sweep-teacher games (DART), camera pitch 82: standard 4.54,
  level 3 1.40 (`pitch82/dart-s*`). Played as an ensemble with `edag-s2`
  (`--ensemble-until 35`, [entry 25](25-ensemble-with-a-doorway-fallback.md)): standard 5.03, level 3 1.63.
- Best through doorways: the same plus door-early teacher games
  (`pitch82/early-s*`: doorway room reached 41 of 107, level 4 0.09) and a
  DAgger round (`pitch82/edag-s*`: 64 of 113, level 4 0.16), at a cost on the
  standard test (4.27, 3.44).
- Best overall: `run --ensemble-until 35` with `edag-s2` as main and
  `dart-s1`, `dart-s2` as members (entries 25, 29): standard 5.03 (4.81 on
  training-layout selection games, best of nine players there).
- Most promising: students of the fixed exploring teacher whose memory also
  learns its coverage map, trained without the drive-change loss weight
  (`pitch82/ftrw-s*`, [entry 34](34-fixed-teacher-and-loss-weights.md)): standard 4.41, level 3 2.00, level 4 0.25,
  level 5 1.90, doorway room reached 95 of 142, no rocking, without DAgger.
- Open problem: the doorway skill does not generalize. Which seed suits test
  layout 19 is luck ([entry 27](27-seed-selection.md)), and games on generated two-room layouts make
  it worse (entries 28, 30); level 4 stays far below the teacher (0.97 for
  the fixed exploring teacher).
- Did not help: RL by advantage-weighted regression, self-imitation, staged
  curriculum, plain doorway-drill data, DAgger fine-tuning alone, weight
  averaging, straight-driving bias, straight teacher routes, DAgger on normal
  placement, a second door-early DAgger round, seed selection on training
  layouts, generated two-room layouts, a search timer input; plain ensembles help ordinary
  fetching only ([entry 23](23-ensembles.md)).
- Level 5 alone is misleading: score it with `levels/l5cross.py` (did the
  robot reach the brick's room) and `levels/l5split.py` (same-room against
  past-doorway bricks).

## Practical notes

- Levels 4 and 5 swapped on 2 Nov 2026 so the numbers follow difficulty:
  level 4 is now the doorway drill and level 5 the other room. Entries 1–34,
  the status above and everything under `build/flex/sim/levels-v1` use the
  old numbering (4 other room, 5 doorway drill). A seed gives the same game
  under the new number, so an old level 5 score is a new level 4 score and
  the reverse. New games record `levelPlacement` in `result.json`, and
  `levels/score.sh` refuses a root whose level 4 or 5 games lack it, so new
  scores go to a new root.
- Watch rocking in place next to deliveries: every game's `result.json` has
  `pingPongSteps` (actions inside runs of at least six that flip drive
  direction every action and add up to at most one action's turn;
  three-point turns do not count) and score files `meanPingPongShare` and
  `gamesMostlyPingPong` (above 20%); `levels/pingpong.py` counts it for older
  games from `decisions.jsonl`. Ping-pong misses slower loops (three actions
  each way), so also watch `backForthSteps` (actions in 20-action stretches
  that end under 0.25 m and 45° from where they began with at least four
  drive reversals; score files `meanBackForthShare`, `gamesMostlyBackForth`;
  `levels/backforth.py` for older games). It is the one to quote.

- One GPU job at a time; never score while collecting on the CPU (the policy
  stream times out).
- `control train` copies its whole dataset into the model folder as
  `data.bin`; nothing reads it afterwards. `flex/scripts/drop-data-copies.py`
  deletes copies that match an existing dataset byte for byte.
- `sweep-L4/aggregate` takes at most 64 shard files (`PVDATA01`), not the
  merged per-level `data/data.bin` (`PVDATA04`); training takes at most 1024
  games and only 0/1 row weights.
- Keep to about 8 policy processes at once: with 12 or 24 (ensembles of
  three over 4 or 8 parts) some starve and time out after a few steps,
  while a lone ensemble game runs at full speed. Ensembles score with
  `PUPPYBOT_CHASE_PARTS=2`.
- A sampled game is about 12 s (40 ms a step, simulator, controller and
  policy in turn); four games at once leave half the CPUs idle.

## Entries

- [1. Sweep teacher students](01-sweep-teacher-students.md) (29 Oct)
- [2. Model size](02-model-size.md) (29 Oct)
- [3. Memory probe](03-memory-probe.md) (29 Oct)
- [4. Checkpoint choice](04-checkpoint-choice.md) (29 Oct)
- [5. DART noise](05-dart-noise.md) (29 Oct)
- [6. Self-imitation](06-self-imitation.md) (29–30 Oct)
- [7. Staged curriculum](07-staged-curriculum.md) (30 Oct)
- [8. 512-step level-4 games](08-512-step-level-4-games.md) (30 Oct)
- [9. Camera pitch 82](09-camera-pitch-82.md) (30 Oct)
- [10. RL, advantage-weighted regression](10-rl-advantage-weighted-regression.md) (30 Oct)
- [11. Level-5 split](11-level-5-split.md) (30 Oct)
- [12. Doorway-drill data](12-doorway-drill-data.md) (30 Oct)
- [13. DAgger, fine-tune only](13-dagger-fine-tune-only.md) (30 Oct)
- [14. Weight averaging](14-weight-averaging.md) (30 Oct)
- [15. Straight-driving bias](15-straight-driving-bias.md) (30 Oct)
- [16. Where students depart from the teacher](16-where-students-depart-from-the-teacher.md) (30 Oct)
- [17. Straight teacher routes](17-straight-teacher-routes.md) (30 Oct)
- [18. Door-pass teacher](18-door-pass-teacher.md) (30 Oct)
- [19. Door-early teacher](19-door-early-teacher.md) (30 Oct)
- [20. Door-early DAgger](20-door-early-dagger.md) (30 Oct)
- [21. Rebalanced set](21-rebalanced-set.md) (30 Oct)
- [22. Longer training](22-longer-training.md) (30 Oct)
- [23. Ensembles](23-ensembles.md) (30 Oct)
- [24. DAgger on normal placement](24-dagger-on-normal-placement.md) (30 Oct)
- [25. Ensemble with a doorway fallback](25-ensemble-with-a-doorway-fallback.md) (30 Oct)
- [26. Doorway specialist](26-doorway-specialist.md) (30 Oct)
- [27. Seed selection](27-seed-selection.md) (31 Oct)
- [28. Diverse two-room layouts](28-diverse-two-room-layouts.md) (31 Oct)
- [29. Selection games on normal placement](29-selection-games-on-normal-placement.md) (31 Oct)
- [30. Diverse layouts without the obstacle](30-diverse-layouts-without-the-obstacle.md) (31 Oct)
- [31. Search timer](31-search-timer.md) (31 Oct)
- [32. Coverage map in memory](32-coverage-map-in-memory.md) (31 Oct)
- [33. Rocking in place](33-rocking-in-place.md) (1 Nov)
- [34. Fixed teacher and loss weights](34-fixed-teacher-and-loss-weights.md) (1 Nov)
- [35. Teacher loop fixes and new students](35-teacher-loop-fixes-and-new-students.md) (2 Nov)
- [36. Teacher back and forth unlabelled](36-teacher-back-and-forth-unlabelled.md) (2 Nov)
- [37. Brick heat map as an auxiliary target](37-brick-heat-map-as-an-auxiliary.md) (2 Nov)
- [38. More epochs](38-more-epochs.md) (3 Nov)
- [39. Ensemble of the more1 students](39-more1-ensemble.md) (3 Nov)
- [40. First-search failures and a heat-map ensemble](40-first-search-and-heat-ensemble.md) (3 Nov)
- [41. Goal baseline and search-loop diagnostics](41-goal-baseline-and-search-loops.md) (3 Nov)
- [42. Progress guard prototype and task-event boundary](42-progress-guard.md) (3 Nov)
- [43. From virtual fetch to a physical-grasp experiment](43-physical-fetch-bridge.md) (3 Nov)
- [44. Level-3 DAgger: first selection pair](44-level3-dagger-selection.md) (3 Nov)
- [45. Opt-in hybrid physical simulator protocol](45-physical-agent-prototype.md) (3 Nov)
- [46. Level-5 first-room diagnosis and L3/L5 DAgger plan](46-level35-dagger-plan.md) (3 Nov)
- [47. Hybrid docking: coarse staging and bounded refinement](47-hybrid-docking-refinement.md) (3 Nov)
- [48. Matched level-4 correction](48-matched-level4-correction.md) (3 Nov)
- [49. Paired search-route diagnostic](49-route-factorial-diagnostic.md) (3 Nov)
- [50. Bounded search bias](50-bounded-search-bias.md) (3 Nov)
- [51. Actor-input instrumentation pilot](51-actor-input-pilot.md) (3 Nov)
- [52. Matched heading-distribution roll-in experiment](52-heading-rollin-experiment.md) (3 Nov)
- [53. Btrfs space plan for the heading experiment](53-btrfs-heading-space-plan.md) (3 Nov)
- [54. Simulated visual-stop validation stopped early](54-visual-stop-validation-aborted.md) (3 Nov)
- [55. Monitored visual-stop startup smoke](55-monitored-visual-v4-smoke.md) (3 Nov)
- [56. Monitored heading roll-in pilot](56-monitored-heading-rollin-pilot.md) (3 Nov)
- [57. Monitored heading trainer pilot](57-monitored-heading-trainer-pilot.md) (3 Nov)
- [58. Full heading collection and overlays](58-full-heading-collection-overlays.md) (3 Nov)
- [59. Full heading training](59-full-heading-training.md) (3 Nov)
- [60. Heading fixed-epoch package](60-heading-fixed-epoch-package.md) (3 Nov)
- [61. Hybrid navigation-to-grasp audit](61-hybrid-navigation-grasp-audit.md) (3 Nov)
- [62. Matched heading selection results](62-heading-selection-results.md) (3 Nov)
- [63. Simulated stop after a nonzero drive command](63-simulated-command-stop.md) (3 Nov)
- [64. L5 teacher roll-in pilot review](64-l5-teacher-rollin-pilot-independent-review.md) (3 Nov)
- [65. L5 three-action steering diagnostic](65-l5-steering-kick-diagnostic.md) (3 Nov)
- [66. Matched teacher comparison on selection layouts](66-teacher-selection-results.md) (3 Nov)
- [67. L5 three-action steering diagnostic results](67-l5-steering-kick-results.md) (3 Nov)
- [68. Search fallback independent review](68-search-fallback-independent-review.md) (3 Nov)
- [69. L5 steering kick and reversal hysteresis results](69-l5-steering-hysteresis-results.md) (3 Nov)
- [70. Replaying the two steering failures with hysteresis](70-steering-hysteresis-failure-replay.md) (3 Nov)
- [71. Simulated dock confirmation: censored comparison](71-dock-confirmation-censored-comparison.md) (3 Nov)
- [72. Why the captured brick did not reach the box](72-dock-reacquisition-trace-review.md) (3 Nov)
- [73. Simulated sustained-contact stop: matched trial](73-simulated-contact-stop-trial.md) (3 Nov)
- [74. Simulator failure-stop prototype and deadline review](74-simulator-failure-stop-prototype.md) (3 Nov)
- [75. Retrospective exact-image stall screen](75-retrospective-exact-image-stall-screen.md) (3 Nov)
- [76. Simulator diagnostics prepared while GPU busy](76-simulator-diagnostics-staged.md) (3 Nov)
- [77. Outbound teacher paths on an L5 failure cluster](77-outbound-teacher-failure-cluster.md) (3 Nov)
- [78. Simulator hybrid visual-stall search recovery](78-visual-search-recovery-prototype.md) (3 Nov)
- [79. Outbound-only teacher label preparation](79-outbound-prefix-label-masking.md) (3 Nov)
- [80. Fresh policy comparison: five-level interim audits](80-fresh-selection-l1-interim.md) (3 Nov)
- [81. Outbound mask: native trainer host-loss probe](81-outbound-mask-host-loss-probe.md) (3 Nov)
- [82. Outbound teacher episode selection: non-authorizing preview](82-qualified-outbound-selection-preview.md) (3 Nov)
- [83. Fresh five-level selection: post-run audit with failed monitor](83-fresh-policy-selection-postrun.md) (3 Nov)
- [84. Simulated stop after an invalid response sequence](84-real-peer-fault-stop-diagnostic.md) (3 Nov)
- [85. Teacher outbound on the fresh L5 selection cases](85-fresh-l5-outbound-comparison.md) (3 Nov)
- [86. Dock survey recording: camera view and rejected viewpoints](86-dock-survey-recording.md) (3 Nov)
- [87. Simulated visual-stall stop with contact ablation](87-simulated-visual-stall-stop.md) (3 Nov)
- [88. Visual-stall search transfer: censored simulator comparison](88-visual-search-transfer-censored-trial.md) (3 Nov)
- [89. Elevated dock survey: censored simulator comparison](89-elevated-dock-survey-censored.md) (3 Nov)
- [90. Stereo worker scheduling and experimental barrier](90-stereo-worker-timing-barrier.md) (3 Nov)
- [91. Dock-clearance diagnostic: staging not reached](91-dock-clearance-unreached-stage.md) (3 Nov)
- [92. Dock rim raster threshold](92-dock-rim-raster-threshold.md) (3 Nov)
- [93. Rendered worker barrier: saved-trace re-audit](93-rendered-worker-barrier-postrun.md) (3 Nov)
- [94. Visual trigger evidence failure: simulated stop path](94-visual-trigger-evidence-stop.md) (3 Nov)
- [95. Observed-floor footprint: missed coarse cells](95-observed-floor-footprint.md) (3 Nov)
- [96. Final back-and-forth window in the saved selection](96-backforth-final-window.md) (3 Nov)
- [97. Saved floor-map resolution comparison](97-saved-floor-resolution.md) (3 Nov)
- [98. Blue context and small box markers: offline replay](98-box-marker-blue-context.md) (3 Nov)
- [99. Diverse teacher level convention and pilot scenes](99-diverse-teacher-level-convention.md) (3 Nov)
- [100. Matched observed-footprint evaluation preparation](100-footprint-matched-evaluation-preparation.md) (3 Nov)
- [101. Fitted box markers and connected blue support](101-fitted-corner-connected-blue.md) (3 Nov)
- [102. Matched observed-footprint trial: no delivery](102-matched-observed-footprint-result.md) (3 Nov)
- [103. Simulator collector failure reporting](103-sim-collector-failure-report.md) (3 Nov)
- [104. Bounded dock floor refresh prototype](104-dock-floor-refresh-prototype.md) (3 Nov)
- [105. Diverse outbound pilot executor](105-diverse-outbound-pilot-executor.md) (3 Nov)
- [106. Dock survey aim kinematics](106-dock-survey-aim-kinematics.md) (3 Nov)
- [107. Diverse-room outbound teacher pilot result](107-diverse-outbound-pilot-result.md) (4 Nov)
- [108. Matched dock-floor refresh: no delivery](108-dock-floor-refresh-result.md) (4 Nov)
- [109. Outbound trainer capacity and auxiliary probes](109-outbound-capacity-auxiliary-probes.md) (4 Nov)
- [110. Saved simulator terminal-failure audit](110-sim-terminal-failure-audit.md) (4 Nov)
- [111. Five teacher-prefix aggregate preparation](111-five-prefix-aggregate-preparation.md) (4 Nov)
- [112. One guarded short approach after failed box search](112-dock-short-waypoint.md) (4 Nov)
- [113. Five teacher-prefix aggregate: verified candidate data](113-five-prefix-aggregate-result.md) (4 Nov)
- [114. Inclusive five-level selection metrics](114-inclusive-five-level-metrics.md) (4 Nov)
- [115. Matched short-waypoint trial: fresh box view, no delivery](115-matched-short-waypoint-result.md) (4 Nov)
- [116. Fixed outbound-prefix training preparation](116-fixed-outbound-training-preparation.md) (4 Nov)
- [117. Missing docking-floor evidence and stale arm turn](117-docking-floor-and-stale-turn-audit.md) (4 Nov)
- [118. Guarding the release-arm turn after it settles](118-settled-dock-turn-guard.md) (4 Nov)
- [120. Five-prefix training: fixed epoch 1](120-five-prefix-training-result.md) (4 Nov)
- [121. Where docking-floor evidence is missing](121-dock-floor-coverage-audit.md) (4 Nov)
- [122. Bounded observation wait after a dock turn](122-dock-turn-reacquisition.md) (4 Nov)
- [123. Simulator dock-turn observation wait integrated](123-dock-turn-wait-integration.md) (4 Nov)
- [124. Five-prefix checkpoint: five-level selection](124-five-prefix-selection.md) (4 Nov)
- [125. Prepared rendered dock-turn fault probe](125-dock-turn-fault-preparation.md) (4 Nov)
- [126. L5 camera-frame replay attempts](126-l5-frame-replay-attempts.md) (4 Nov)
- [127. L5 actor-frame comparison after recording-aware replay](127-l5-camera-frame-comparison.md) (4 Nov)
- [128. Parent-route retention: matched data feasibility](128-parent-retention-feasibility.md) (4 Nov)
- [129. Rendered short dock-observation dropout pilot](129-dock-turn-fault-pilot-result.md) (4 Nov)
- [130. Parent-route collection plan and lineage audit](130-parent-route-collection-plan.md) (4 Nov)
- [131. Parent collector actor-boundary prototype](131-parent-actor-boundary-prototype.md) (4 Nov)
- [132. Instrumented parent-route collection](132-parent-route-collection.md) (4 Nov)
- [133. Selection-role preparation prototype](133-selection-role-prototype.md) (4 Nov)
- [134. Paired trainer capacity and mask prototype](134-paired-trainer-prototype.md) (4 Nov)
- [135. Paired parent-route dataset candidates](135-paired-parent-route-aggregates.md) (4 Nov)
- [136. Paired trainer batch and mirror journal prototype](136-paired-mirror-journal.md) (4 Nov)
- [137. Paired trainer one-update GPU smoke](137-paired-one-update-smoke.md) (4 Nov)
- [138. Native scene-ingestion guard prototype](138-native-scene-ingestion-guard-prototype.md) (4 Nov)
- [139. Positive-allowlist snapshot bootstrap](139-positive-bootstrap-prototype.md) (4 Nov)
- [140. Matched teacher-label and parent-label training](140-matched-parent-label-training.md) (4 Nov)
- [141. Fresh four-arm selection design](141-fresh-selection-design.md) (4 Nov)
