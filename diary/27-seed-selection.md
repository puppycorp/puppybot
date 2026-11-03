# 27. Seed selection

_31 Oct, `runs/19`_

`PUPPYBOT_EVAL_SELECTION=1` makes `evaluate.sh` play training layouts with
seeds 980000+ so students can be chosen without the test games. Five more
`edag2` seeds, all eight scored on selection levels 4 and 5:

| Seed | Selection L4 + L5 | Selection room reached | Test L4 + L5 | Test room reached |
|---|---:|---:|---:|---:|
| s0 | 1.47 | 13 of 35 | 0.94 | 6 of 33 |
| s1 | 1.22 | 11 of 32 | 1.34 | 23 of 36 |
| s2 | 1.38 | 9 of 32 | 0.88 | 3 of 31 |
| s3 | 1.38 | 15 of 34 | | |
| s4 | 1.59 | 19 of 34 | | |
| s5 | 1.66 | 21 of 41 | | |
| s6 | 1.84 | 25 of 41 | | |
| s7 | 1.84 | 29 of 40 | 0.91 | 6 of 34 |

Chosen `edag2-s7`, alone: standard 3.94, level 1 4.66, level 3 1.56,
level 4 0.03, level 5 0.88; as main of the mix: standard 4.72, level 4
0.06, level 5 1.03, room reached 3 of 32. Verdict: rankings on the
training two-room layouts (13, 15, 17) do not carry to test layout 19;
the doorway skill does not generalize, and which seed happens to suit
layout 19 is luck. Next: more two-room training layouts (`runs/20`).
