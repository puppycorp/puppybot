# 26. Doorway specialist

_30 Oct, `runs/18`_

Second door-early DAgger round: `edag-s2` drives 64 level-4 and 64 level-5
games (room reached 27 of 69), in place of half the `dart-L1`/`dart-L2` games
(`data-edag2`, 1024): standard 4.17 (4.38, 4.13, 4.00), level 1 4.88, level 3
1.25, level 4 0.10 (0.03, 0.22, 0.06), level 5 0.95, room reached 6/33, 23/36,
3/31. The seed matters more than the data. `edag2-s1` (best on the test levels
4+5, so optimistic) as main of the `--ensemble-until 35` mix: standard 4.66,
level 1 5.19, level 2 4.72, level 3 1.50, level 4 0.28, level 5 1.72 (teacher
1.59), room reached 27 of 44, delivered 15.
