# 34. Fixed teacher and loss weights

_1 Nov, `runs/25`, one seed_

The `runs/24` games again with the same seeds and the fixed teacher
(`data-exfix`, rocking 0.02 on level 4, under 0.005 elsewhere), then the
`emap` student four ways. Deliveries per minute, rocking share in brackets;
`emap` is the mean of its three seeds from [entry
32](32-coverage-map-in-memory.md), whose rocking was 0.26–0.45 on level 3,
0.38–0.79 on level 4 and 0.28–0.62 on level 5:

| student | standard | L1 | L2 | L3 | L4 | L5 | L5 past door delivered |
|---|---|---|---|---|---|---|---|
| `emap` (old data) | 4.45 | 6.82 | 4.66 | 1.36 | 0.14 | 1.49 | 36 of 121 |
| `fmap` as before | 4.81 (0.04) | 6.91 | 4.84 | 1.28 (0.37) | 0.13 (0.60) | 0.94 (0.55) | 3 of 33 |
| `fdrop` feedback hidden 25% | 4.38 (0.04) | 6.50 | 5.06 | 1.31 (0.22) | 0.13 (0.65) | 1.31 (0.43) | 14 of 43 |
| `frev` reversal penalty | 4.63 (0.01) | 6.31 | 5.09 | 1.66 (0.04) | 0.34 (0.14) | 1.81 (0.08) | 23 of 52 |
| `ftrw` no ×8 drive-change weight | 4.53 (0.00) | 6.75 | 5.19 | 2.31 (0.00) | 0.47 (0.12) | 2.66 (0.05) | 34 of 60 |
| fixed teacher | | 8.06 | 5.53 | 2.56 | 0.97 (0.02) | 2.59 | 31 of 56 |

A clean teacher alone does not stop students rocking (`fmap`); the
eightfold loss weight on drive changes was the main cause, since it
rewards guessing a change. Without it (`--transition-weight-one`) the
student hardly rocks, matches the teacher on level 3 and level 5 (it
reaches the brick's room for 51 of 60 past-doorway bricks) and triples
the best level-4 score so far. The reversal penalty helps for the same
reason but less. Hiding the feedback does little.

Seeds 1 and 2 (`runs/26`): `ftrw-s1` standard 3.91, L3 1.78, L4 0.03,
L5 1.19 (past door 10 of 38); `ftrw-s2` 4.78, 1.91, 0.25, 1.84 (20 of
44); rocking at most 0.03 on every level for both. Mean of three `ftrw`
seeds against `emap`: standard 4.41 / 4.45, L1 6.84 / 6.82, L2 4.94 /
4.66, L3 2.00 / 1.36, L4 0.25 / 0.14, L5 1.90 / 1.49, room reached 95
of 142 / 62 of 121, past-doorway delivered 64 of 142 / 36 of 121. Seed
0 was the lucky one, but level 3 and level 5 gain beyond noise, level 4
a little, and the rocking is gone for every seed. `ftrv-s0` (both the
weight off and the reversal penalty) is no better: 3.72, 1.94, 0.31,
1.88. Verdict: train chase-v1 students with `--transition-weight-one`
from now on; level 4 (teacher 0.97) is still the gap. Data
`pitch82/data-exfix`, students `pitch82/f*-s*`.
