# 40. First-search failures and a heat-map ensemble

_3 Nov 2026, `runs/32`_

On the 32 level-3 test games from entry 39, compare the `more1` ensemble
with `explore-kturn` using `levels/search-latency.py`. It checks matching
seeds, initial positions, scene files, level and horizon, and counts the
first transition into the return phase. Each game lasts 300 actions;
unfinished first searches are capped at 300, so the capped mean is not the
mean of completed searches.

| Player | First returns | Capped first-search mean / median (actions) | Search actions per game | Deliveries |
|---|---:|---:|---:|---:|
| Teacher | 32 of 32 | 53.75 / 38.5 | 171.16 | 90 |
| `more1` ensemble | 24 of 32 | 119.75 / 50.5 | 221.34 | 59 |

In all eight games where the ensemble never entered return, the teacher did.
The ensemble's closest recorded robot-to-brick distance during those first
searches was 1.01–2.08 m, calculated from simulator positions. This points
to missed search coverage, not a demonstrated cause of it; distance is not a
camera-visibility measure. The old game files do not record simulator binary
hashes, so matching scenes and starts do not establish identical simulator
executables across these historical runs.

As a small candidate, replace `more1-s2` with `hmap-s0` (entry 37) in the
ensemble. `runs/32` compares both players on the same 32 level-3
**training-layout selection** games (seeds 980000–980031), not the unseen
test games. Scores are deliveries per minute; back-and-forth is the fraction
of actions in the pose-based loops described in the index.

Subsequent audit: 16 of those seeds also occur in the `kturn-L3` teacher
collection; seed 980000 also has identical recorded scene files and start
event. The other 15 share the start event but have different scene files.
These games are therefore not an independent selection set, and the table
cannot establish generalization. Use disjoint seeds and audit scenes and
starts for future candidate selection.

| Player | Deliveries/min | First returns | Capped first-search mean | Back-and-forth share | Mostly back-and-forth games |
|---|---:|---:|---:|---:|---:|
| `more1` ensemble | 2.0625 | 30 of 32 | 81.00 | 0.0099 | 1 |
| `more1-s0`, `more1-s1`, `hmap-s0` | 2.09375 | 28 of 32 | 94.06 | 0.0176 | 0 |

The one-delivery difference is inconclusive, and the mixed ensemble misses
more first pickups. Do not promote it. The selection games and logs are in
`levels-v2/pitch82/search-mix-selection`; `inputs.sha256` records the
control and simulator binaries and all four model weights and policy
executables and was checked after both runs. The next candidate should target
first-search coverage and be selected on training-layout games before testing
on unseen layouts.
