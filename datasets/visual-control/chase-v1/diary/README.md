# Fetch experiment diary

One file per experiment or finding, numbered in order (`NN-name.md`), newest
last: what was tried, the result, the verdict and where the data and scripts
are. Scores are deliveries per minute on the 32 test games, mean of three
seeds unless noted; one seed varies by about 0.3, so differences below about
0.4 are noise. Full tables and method details are in
[README.md](../README.md). Run scripts are in [levels/runs](../levels/runs),
analysis tools in [levels](../levels); data is under
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
