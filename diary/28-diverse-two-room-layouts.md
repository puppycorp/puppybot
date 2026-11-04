# 28. Diverse two-room layouts

_31 Oct, `runs/20`_

32 new fitting layouts from `generate-diverse` (IDs 26–57,
`levels-v1/diverse-scenes`; the 16 odd ones are two-room with varied bounds,
doorway, start pose, floor colour and an obstacle); `collect.sh` takes
`PUPPYBOT_CHASE_SCENES` and `PUPPYBOT_CHASE_LAYOUTS`. Door-early teacher 64
level-4 and 64 level-5 games there (teacher level 4 about 0.5), added to
`data-early` for `div-s*` (seeds of `early-s*`). Teacher there: level 4 0.52,
level 5 1.78, room reached 69 of 93. Students: standard 4.11 (4.63, 3.41,
4.31), level 1 4.44, level 2 3.70, level 3 0.77, level 4 0.02, level 5 0.75,
room reached 4 of 91 (`early-s*` 41 of 107). Verdict: worse everywhere, not a
seed effect; validation loss is normal (0.31). Untested guess: the grey
obstacle in every diverse room resembles the delivery box.
