# 2. Model size

_29 Oct, `runs/01`, `levels/size.sh`_

From scratch: small 0.38 (7e-4) / 0.34 (2e-4), large 1.55 (needs 2e-4); the
small model fine-tuned from `train-d5-agg` on the same games gets 3.19.
Verdict: the starting point matters more than size; no larger model tried.
