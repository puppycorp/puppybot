# 25. Ensemble with a doorway fallback

_30 Oct, `runs/17`_


`--ensemble-until STEPS`: `edag-s2` votes with `dart-s1` and `dart-s2` and
drives alone after STEPS steps without the brick. The first runs had a bug:
members overwrite the shared policy output, so after STEPS `dart-s2` drove
instead (kept as `ensemble/eval*/mix*-dart2`). That variant is the best
ordinary fetcher so far: STEPS 60 standard 4.88, level 1 5.19, level 2 5.06,
level 3 1.72, level 4 0, level 5 0.81 (room reached 2 of 30); STEPS 20 4.50
(level 3 1.75), 35 4.72, 120 4.84. Fixed, `edag-s2` driving after STEPS:

| STEPS | Standard | L1 | L2 | L3 | L4 | L5 | Room reached |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 20 | 4.84 | 4.94 | 4.75 | 1.50 | 0.13 | 1.00 | 9 of 36 |
| 35 | 5.03 | 5.34 | 5.06 | 1.63 | 0.06 | 0.97 | 9 of 35 |
| 60 | 4.84 | 5.28 | 5.06 | 1.69 | 0.16 | 0.91 | 19 of 33 |

Verdict: best ordinary fetching so far (first standard above 5); the
doorway stays below `edag-s2` alone. Next: a stronger doorway specialist
as the main policy (`runs/18`).
