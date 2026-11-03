# 38. More epochs

_3 Nov, `runs/30`_

The `ccont` students trained on in rounds of 8 epochs in one go on the same
`kmask` games (fused path, no hang). Training loss keeps falling (0.27 to
0.19) while validation loss stays at 0.268–0.276, and the trainer keeps the
best validation epoch, so a seed whose validation loss does not improve comes
out unchanged (`more1-s2`, `more2-s0`). Back and forth in brackets:

| student | standard | L1 | L2 | L3 | L4 | L5 | L4 room reached | L4 past door delivered |
|---|---|---|---|---|---|---|---|---|
| `ccont` | 4.66 | 6.02 (0.06) | 4.69 | 1.76 (0.01) | 2.39 (0.04) | 0.66 (0.02) | 109 of 156 | 83 of 156 |
| `more1` +8 | 4.93 | 6.75 (0.06) | 4.97 | 1.82 (0.01) | 2.47 (0.04) | 0.93 (0.05) | 121 of 163 | 90 of 163 |
| `more2` +16 | 4.80 | 6.82 (0.04) | 5.14 | 1.88 (0.01) | 2.26 (0.03) | 0.81 (0.04) | 107 of 151 | 76 of 151 |

Standard by seed: `ccont` 4.69, 4.34, 4.94; `more1` 5.00, 4.84, 4.94;
`more2` 5.00, 4.31, 5.09. L5 `more1` 1.19, 0.81, 0.78; `more2` 1.19, 0.25,
1.00. Round one gains on every level, and `more1` is the best single
students so far on the standard test (above `dart`'s 4.54). Round two is
within noise overall: `more2-s1` reaches a lower validation loss and plays
worse (L4 2.25 to 1.69, L5 0.81 to 0.25), so validation loss no longer
picks better players. Seven of `more1`'s level-5 games are mostly back and
forth against two of `ccont`'s. Stopped there; keep `more1`. Students
`levels-v2/pitch82/more{1,2}-s*`.
