# 37. Brick heat map as an auxiliary target

_2 Nov, `runs/29`_

Long level-1 fetches mostly start with the brick at the edge of view after a
delivery (bearing over 35 degrees in 81% of `mtrw`'s legs over 40 steps, 19%
of short ones), so the students may not be picking out bricks they can see.
`levels/heat-labels.py` labels the brick's image position from the teacher's
own camera detection, when it saw exactly one brick and a brick-coloured pixel
lies within 2 pixels of it in the training image: 26% of the `kmask` frames.
`control train --target-heatmap` trains a heat head on those positions next to
the critic (the actor's inputs are unchanged). The heat head disables the
fused training path, so an epoch takes 180 s against 27 s, and its GPU work
hangs about 11 to 12 minutes in (trainer waiting in libhsa, GPU 100% busy, no
kernel error; reproduced twice, cause not found). So both arms continue
`mtrw-s0..2` for 8 epochs as four 2-epoch chunks through `--policy`, with a
chunk killed and retried after 20 minutes (needed twice): `hmap` with the heat
target, `ccont` without it, and `cont` the same 8 epochs in one go. Back and
forth in brackets:

| student | standard | L1 | L2 | L3 | L4 | L5 | L4 room reached | L4 past door delivered |
|---|---|---|---|---|---|---|---|---|
| `mtrw` | 4.43 | 6.28 (0.05) | 4.86 | 1.97 (0.02) | 2.00 (0.03) | 0.66 (0.03) | 112 of 154 | 70 of 154 |
| `cont` | 4.62 | 5.78 (0.05) | 5.02 | 1.78 (0.01) | 2.15 (0.03) | 0.60 (0.03) | 113 of 146 | 65 of 146 |
| `ccont` chunked | 4.66 | 6.02 (0.06) | 4.69 | 1.76 (0.01) | 2.39 (0.04) | 0.66 (0.02) | 109 of 156 | 83 of 156 |
| `hmap` heat map | 4.69 | 6.77 (0.07) | 4.78 | 1.98 (0.01) | 2.28 (0.03) | 0.72 (0.01) | 107 of 161 | 81 of 161 |

Seeds, `hmap` against `ccont`: L1 7.53 / 5.88, 6.97 / 5.34, 5.81 / 6.84;
L4 2.72 / 2.62, 1.56 / 1.88, 2.56 / 2.66; L5 1.00 / 0.75, 0.19 / 0.44,
0.97 / 0.78. Level-1 fetch legs over 40 steps fall from 82 of 672 to 69
of 745 (by seed 30 / 18, 35 / 29, 17 / 22), but those that remain still
start off to the side (80%), so the head does not make edge bricks easier
to find. Two seeds gain 1.6 on level 1 and the third loses 1.0, and
nothing else moves beyond noise: not proven with three seeds, and too
slow and fragile to keep training with while the hang is open. Data
`levels-v2/pitch82/data-kmask/heat`, students
`levels-v2/pitch82/{cont,ccont,hmap}-s*`.
