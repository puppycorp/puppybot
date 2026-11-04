# 35. Teacher loop fixes and new students

_2 Nov, `runs/27`, new level
numbering from here on: 4 doorway drill, 5 other room_

Back and forth
(`backForthSteps`) showed the fixed teacher still stuck in slower loops
than rocking: 0.19 of drill time and 0.23 of other-room time. Two
causes. A brick seen through the doorway was driven at straight, so the
teacher bumped the partition and backed off forever; it now routes to
such a brick like unseen floor when walls or the box are in the line
(`vx_brick_route`). And at a wall corner the reverse turned toward the
aim, which swaps sides there, undoing the forward turn each time; right
after a forward turn the reverse now keeps turning the same way, as in a
three-point turn. Teacher on the test games (`explore-kturn`, back and
forth in brackets) against `explore-commit`: L1 7.69 (0.07) / 8.06
(0.06), L2 5.50 / 5.53, L3 2.81 (0.00) / 2.56 (0.10), L4 2.88 (0.07) /
2.59 (0.19), L5 1.25 (0.09) / 0.97 (0.23). In its noisy training games
(`kturn`, same seeds and sizes as `exfix`) back and forth drops less:
drill 0.11 / 0.15, other room 0.11 / 0.21, and level 1 rises to 0.16 /
0.12 (reversing near the box). Then `ftrw` again on that data
(`rtrw-s0..2`), against `ftrw` renumbered:

| student | standard | L1 | L2 | L3 | L4 | L5 | L4 room reached | L4 past door delivered |
|---|---|---|---|---|---|---|---|---|
| `ftrw` (`exfix` data) | 4.41 | 6.84 | 4.94 | 2.00 | 1.90 (0.07) | 0.25 (0.13) | 95 of 142 | 64 of 142 |
| `rtrw` (`kturn` data) | 4.40 | 6.43 | 5.00 | 1.84 | 2.20 (0.07) | 0.44 (0.06) | 96 of 149 | 68 of 149 |

Seeds: `rtrw` L4 1.81, 2.31, 2.47; L5 0.03, 0.72, 0.56 (`ftrw` 0.47,
0.03, 0.25). The other room gains a little and its back and forth halves,
but drill back and forth stays at 0.04–0.09 and the past-doorway rate is
unchanged; L1 loses 0.4. Cleaner teacher games are not enough: the
students' remaining loops come from states the teacher never shows, so
the next step is DAgger with the fixed teacher labelling the student's
stuck states. Data `levels-v2/pitch82/data-kturn`, students
`levels-v2/pitch82/rtrw-s*`.
