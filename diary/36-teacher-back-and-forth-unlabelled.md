# 36. Teacher back and forth unlabelled

_2 Nov, `runs/28`_

The `rtrw` students again on the same `kturn` games, with the labels switched
off (frames kept as input) on the teacher's back-and-forth actions, except
within 0.6 m of the box or of the brick while not carrying it, where reversing
lines up a delivery or pickup (`levels/mask-stuck.py`). That unlabels 6.6% of
rows: 10% on level 5, 8% on level 4, 6% on level 1 (16% flagged there, mostly
beside the box). Back and forth in brackets:

| student | standard | L1 | L2 | L3 | L4 | L5 | L4 room reached | L4 past door delivered |
|---|---|---|---|---|---|---|---|---|
| `rtrw` | 4.40 | 6.43 (0.05) | 5.00 | 1.84 (0.01) | 2.20 (0.07) | 0.44 (0.06) | 96 of 149 | 68 of 149 |
| `mtrw` unlabelled | 4.43 | 6.28 (0.05) | 4.86 | 1.97 (0.02) | 2.00 (0.03) | 0.66 (0.03) | 112 of 154 | 70 of 154 |
| teacher `explore-kturn` | | 7.69 (0.07) | 5.50 | 2.81 (0.00) | 2.88 (0.07) | 1.25 (0.09) | 41 of 59 | 32 of 59 |

Seeds: `mtrw` L4 2.47, 1.38, 2.16; L5 1.03, 0.19, 0.75. Back and forth
halves on both search levels, to below the teacher's, so most of the
students' loops were copied after all. Deliveries move within noise, so
being stuck is no longer what limits them. Past the doorway the students
now nearly match the teacher (room reached 73% / 69%, delivered 45% /
54%); the level-4 gap is mostly speed on same-room bricks (teacher 65
per 32 games, students 45), as on level 1. Verdict: keep the mask; the
next gains need a faster student on ordinary fetching or a better
searching teacher, not more anti-loop work. Data
`levels-v2/pitch82/data-kmask`, students `levels-v2/pitch82/mtrw-s*`.
