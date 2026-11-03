# 39. Ensemble of the more1 students

_3 Nov 2026, `runs/31`_

The three `more1` students ([entry 38](38-more-epochs.md)) play together with
`--ensemble` (mean of their action probabilities, each keeping its own
memory, as in [entry 23](23-ensembles.md)), `more1-s0` as main. One ensemble,
so one set of 32 games per test against the three-seed mean. Back and forth
in brackets:

| player | standard | L1 | L2 | L3 | L4 | L5 | L4 room reached | L4 past door delivered |
|---|---|---|---|---|---|---|---|---|
| `more1` seed mean | 4.93 | 6.75 (0.06) | 4.97 | 1.82 (0.01) | 2.47 (0.04) | 0.93 (0.05) | 74% | 55% |
| `more1` ensemble | 4.91 | 7.34 (0.05) | 5.09 | 1.84 (0.00) | 2.66 (0.03) | 1.00 (0.02) | 49 of 59 | 34 of 59 |
| teacher `explore-kturn` | | 7.69 (0.07) | 5.50 | 2.81 (0.00) | 2.88 (0.07) | 1.25 (0.09) | 41 of 59 | 32 of 59 |

The standard test does not move, but every level gains a little, level 1 the
most (+0.6, now 0.35 below the teacher). Level-5 back and forth falls to a
third, with 1 game mostly back and forth against 7 of 96 for the seeds. Past
the doorway the ensemble reaches the brick's room more often than the teacher
(83% against 69%) and delivers as often (58% / 54%). The vote fixes a seed's
bad moments rather than adding a new skill, at three times the compute per
step. Verdict: the best player so far on levels 1–5; keep it as the reference
to beat, and look for the remaining level-1 and level-3 gap (2.81 against
1.84 on bricks out of view in the same room) in the students' search. Games
`levels-v2/pitch82/ensemble`.
