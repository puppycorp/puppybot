# 44. Level-3 DAgger: selection pairs

_3 Nov 2026, training-layout selection, ongoing_

`runs/33` mixed 128 student-driven level-3 games labelled by the exploring
teacher with 896 teacher-driven games. Teacher loops were unlabelled only in
teacher-driven games, retaining the teacher's correction labels in the
student-driven games. All 1,024 source games passed `levels/audit-shards.py`;
three `more1` students were continued for eight epochs each. Input hashes and
source audit are under `levels-v2/pitch82/search-dagger-4workers` (entry 41).

`levels/selection-pair.sh 3 0`, `3 1` and `3 2` compared each student with its starting
model, with 32 matched 60-second games per pair on training-layout selection
scenes and seeds 7800000–7800031. It captured input hashes before play and
audited policy snapshots, paired scenes and starts, complete game counts,
timeout logs and scores afterward. These seeds are disjoint from the mixed
source shards; the pretrained model's full ancestry has not been audited.

| Player | Deliveries/min | First pickups | Games with delivery | Back-and-forth share | Mostly back-and-forth games |
|---|---:|---:|---:|---:|---:|
| `more1-s0` | 2.125 | 27/32 | 27/32 | 3.51% | 2 |
| `student-s0` | 2.344 | 31/32 | 31/32 | 0% | 0 |
| `more1-s1` | 2.031 | 27/32 | 27/32 | 1.22% | 1 |
| `student-s1` | 2.219 | 29/32 | 29/32 | 1.22% | 1 |
| `more1-s2` | 2.094 | 28/32 | 27/32 | 0.23% | 0 |
| `student-s2` | 2.375 | 29/32 | 29/32 | 0.57% | 0 |

Promising on all three pairs, but not a held-out result and not evidence of a
physical grasp: the chase task uses virtual pickup and visual docking (entry
43). Do not promote on these pairs. Check
other levels and ordinary fetching for regressions before any held-out test.
The pair manifest, games and audit are in
`search-dagger-4workers/selection-L3`.

An ordinary-fetch regression check (`selection-pair.sh 1 0`) also passed its
paired audit. Both `more1-s0` and `student-s0` scored 6.8125 deliveries/min;
games with a delivery were 31/32 and 32/32, respectively. Back-and-forth
shares were 4.19% and 4.57%, above the proposed 2% target, with zero and one
mostly-back-and-forth games. This single selection pair does not establish
the other seeds' or levels' behavior; files are under `selection-L1`.

The first doorway regression check (`selection-pair.sh 4 0`) also passed.
`more1-s0` scored 2.25 deliveries/min and delivered 26 of 51 past-doorway
bricks; `student-s0` scored 2.75 and delivered 33 of 51. Their back-and-forth
shares were 3.24% and 1.45%, respectively. Both saw 51 past-doorway cases;
room entry was 43 and 40, so the result is not evidence of better room entry.
This is one selection pair, not the held-out 80% goal. Files are in
`selection-L4`.

The second doorway pair (`selection-pair.sh 4 1`) delivered 36/59
past-doorway bricks for `more1-s1` and 38/64 for `student-s1`, with room
entry 48/59 and 50/64. Deliveries/min were 2.94 and 3.09; back-and-forth
shares were 2.99% and 3.24%. The doorway fractions are similar and below the
goal, so the first pair's improvement is not yet consistent evidence.

The third doorway pair (`selection-pair.sh 4 2`) regressed: `more1-s2`
delivered 30/54 past-doorway bricks at 2.47 deliveries/min; `student-s2`
delivered 23/48 at 1.84/min. Their back-and-forth shares were 1.73% and
3.13%. First pickups rose from 24/32 to 32/32, but delivery rate fell. This
rules out treating the three-seed level-3 improvement as a general promotion.

The first other-room pair (`selection-pair.sh 5 0`) passed its audit but both
players struggled: `more1-s0` delivered in 12/32 games at 0.469/min;
`student-s0` delivered in 13/32 at 0.406/min. First pickups were 14 and 13.
Back-and-forth share fell from 8.93% (5 mostly back-and-forth games) to
0.68% (none). Fewer loops did not establish reliable delivery. Files are in
`selection-L5`.
