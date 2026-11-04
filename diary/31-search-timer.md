# 31. Search timer

_31 Oct, `runs/23`_

`--search-cue` (train and run) puts the search time in the carry-cue slot: 1
while carrying, otherwise minus the steps since the last pickup, delivery or
start over 200, down to -1 (`vd_search_cue`). `data-early` with the seeds of
`early-s*`, as `time-s*`: standard 4.27 (3.69, 4.56, 4.56; `early-s*` 4.27),
level 1 4.86, level 2 4.40, level 3 1.30 (1.14), level 4 0.04 (0.09), level 5
0.97 (1.08), room reached 8 of 94 (41 of 107). Validation loss as before
(0.27). Verdict: worse at the doorway; untested guess: the teacher rarely
searches long, so long-search timer values hardly occur in its games.
