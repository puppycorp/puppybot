# 32. Coverage map in memory

_31 Oct, `runs/24`_

Exploring teacher (`--explore-teacher`, which drives to floor its camera has
not covered) at pitch 82 with 3% noise, in the `data-early` level mix (128
games on each of levels 0–4, 256 on level 5; `data-expl`). `--record-map`
stores its coverage map around the robot each step; `emap-s*` also learn it
from their memory (`--memory-map`, training only), `expl-s*` do not. Same
settings and seeds as `early-s*`. Teacher on the test games: level 1 8.50,
level 2 5.75, level 3 2.53, level 4 0.81, level 5 2.31.

| Students | Standard | L1 | L2 | L3 | L4 | L5 | Room reached |
|---|---:|---:|---:|---:|---:|---:|---:|
| `expl-s*` | 3.63 (4.34, 4.09, 2.44) | 6.10 | 3.77 | 0.81 | 0 | 1.00 | 21 of 97 |
| `emap-s*` | 4.45 (4.63, 4.44, 4.28) | 6.82 | 4.66 | 1.36 | 0.14 | 1.49 | 62 of 121 |
| `early-s*` | 4.27 | 5.06 | 4.56 | 1.14 | 0.09 | 1.08 | 41 of 107 |
| `dart-s*` | 4.54 | 4.77 | 4.27 | 1.40 | 0 | 0.95 | |

Validation loss 0.30–0.32 for both (earlier exploring-teacher students
0.53–0.59 on their own states); map loss 0.21 (0.69 is guessing). Room
reached by seed: 30 of 48, 3 of 32, 29 of 41. Verdict: the map helps on
every level, no seed collapses, and level 1 and level 5 are the best of
any single student; level 4 stays far below the teacher. The map head
first ran on the per-step training path, which hung at random epochs on
the RX 9070 (no kernel log entry); it now runs on the fused path,
about five times faster with the same losses.
