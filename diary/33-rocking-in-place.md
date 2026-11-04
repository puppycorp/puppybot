# 33. Rocking in place

_1 Nov, measured on existing games_

The videos show robots stuck driving forward one action and back the next.
Share of actions in runs of at least six that flip drive direction every
action and add up to at most one action's turn (right steering turns right
going forward and left in reverse, so a three-point turn keeps turning one way
and does not count): `levels/pingpong.py`, now also `pingPongSteps` in every
result. Over 896 test games it matches the true poses (no net move of 0.15 m
or turn of 20 degrees in 10 actions while flipping): correlation 0.999. Games
above 20% in brackets.

| Player | L1 | L3 | L4 | L5 |
|---|---:|---:|---:|---:|
| exploring teacher | 0 | 0.02 (2) | 0.18 (15) | 0.16 (9) |
| `emap-s0` | 0.06 (2) | 0.26 (14) | 0.62 (28) | 0.28 (14) |
| `emap-s1` | 0.14 (8) | 0.45 (23) | 0.79 (32) | 0.62 (27) |
| `emap-s2` | 0.06 (4) | 0.16 (10) | 0.38 (21) | 0.33 (20) |
| `expl-s0` | 0.28 (14) | 0.34 (19) | 0.48 (32) | 0.46 (28) |
| `dart-s0`, `-s1` | 0.04, 0.08 | 0.11, 0.09 | 0, 0 | 0.04, 0.03 |
| `dart-s2` | 0.05 | 0.12 | 0.54 (32) | 0.34 (20) |
| `early-s0` | 0.06 | 0.28 | 0.46 (30) | 0.26 |
| `edag-s2` | 0.05 | 0.18 | 0.43 (26) | 0.20 |

Teacher training games (`data-expl`): 0.002 on levels 0–2, 0.01 on
level 3, 0.07 on level 4, 0.05 on level 5, mostly while carrying the
brick home. The teacher's cause: with a wall within 0.3 m ahead
`vx_route` reverses one action turning toward its route point; the next
action sees open floor and drives forward again, undoing it (one level-5
test game spends 200 of 300 actions this way). Students copy it and do
it far more, and on level 4 while searching, where the teacher hardly
does. The input shows the loop plainly: five of the seven feedback
values (last action, wheel speeds, steering angle) flip every action,
and in a two-action loop the camera image two actions apart is nearly
identical (mean change 0.6 against 6 per action), so the same input
comes back and gets the same answer; inside the teacher's loop the
label is just the reverse of the last action.

Teacher fix: `vx_route` now reverses three actions (`vx_escape=2`, as
contact recovery does) when the wall check fires. Exploring teacher on
the test games (`explore-commit`): level 4 rocking 0.18 → 0.02 (games
above 20%: 15 → 1), deliveries 0.81 → 0.97 (games with one 22 → 24);
level 5 rocking 0.16 → 0.004, deliveries 2.31 → 2.59, past-doorway
bricks delivered 28 of 52 → 31 of 56. Levels 1–3: 8.50, 5.75, 2.53 →
8.06, 5.53, 2.56, no rocking. The sweep teacher (which shares
`vx_route`) not yet scored.

Training makes it worse: `pt_control_weight` multiplies the loss by 8
when the label's drive differs from the previous action's (and by 5 for
stops). In `data-expl` drive changes are 15–20% of rows but 43–64% of
the loss weight, and rocking rows 6.5% of level-4 rows but 20% of its
loss weight (level 5: 4.8% and 14.5%). Nothing in imitation penalises
standing still. Not yet tried in chase-v1: `--drop-drive-feedback-milli`,
`--reversal-penalty-milli`, `--stop-weight-one`; the eightfold change
weight has no switch.
