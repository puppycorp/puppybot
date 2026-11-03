# 22. Longer training

_30 Oct, `runs/14`_

Entry 20's data for 60 epochs instead of 30: standard 3.84 (4.22, 2.97, 4.34),
level 4 0.17, level 5 1.22, room reached 55 of 110; seed 2's best epoch is 20,
so it is the same model as `edag-s2`. Verdict: no change. The collapsed seeds
lose whole standard games rocking between forward and reverse arcs (straight
on 1–3% of steps, reverse on 22–47%).
