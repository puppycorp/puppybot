# 23. Ensembles

_30 Oct, `runs/15`_

`run --ensemble DIR` (repeatable) plays the policy with others, each keeping
its own memory, taking the most likely class of their mean probabilities
(scored with 2 parts):

| Test | `dart` | `early` | `edag` |
|---|---:|---:|---:|
| Standard | 4.72 (4.54) | 4.56 (4.27) | 4.44 (3.44) |
| Level 1 | 5.09 (4.77) | 5.78 (5.06) | 5.16 (4.21) |
| Level 3 | 1.34 (1.40) | 1.25 (1.14) | 1.25 (0.95) |
| Level 4 | 0 (0) | 0.03 (0.09) | 0.09 (0.16) |
| Level 5 | 0.88 (0.95) | 0.84 (1.08) | 0.97 (1.23) |
| Room reached | 3 of 32 | 2 of 30 | 9 of 34 (64 of 113) |

Seed means in brackets. Verdict: the mean fixes collapsed seeds and lifts
ordinary fetching, but setting off for the doorway is a minority choice
and the vote returns to circling.
