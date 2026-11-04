# 24. DAgger on normal placement

_30 Oct, `runs/16`_

The collapsed seeds `edag-s0` and `edag-s1` each drive 64 level-0 games while
the teacher labels (they follow 95% of its straight steps but about half of
its reverse ones); these replace half of the `dart-L0` and `dart-L1` games in
`data-edag` (1024): standard 3.66 (3.53, 4.38, 3.06), level 1 4.32, level 3
1.03, level 4 0.05, level 5 0.97, room reached 38 of 105. Verdict: no gain;
the two seeds that drove recover and the third collapses instead.
