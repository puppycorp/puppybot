# Chase game

Can the camera-to-action network learn to drive to what it sees? In the chase
game the brick reappears somewhere new after every reach, and about a fifth of
bricks jump once while the robot is still more than 0.9 m away. A memorised
opening routine cannot score; only looking can.

`run --chase` and `collect --chase` (`flex/control/chase.flex`) play one-minute
games (300 actions). The simulator's agent command 5 restores the brick at a
requested floor pose; reaching still requires a fresh camera detection within
35 cm. Placements are 60% in view (±0.45 rad, 0.6–2.2 m), 30% beside the robot
and 10% behind it, always clear of walls and the box.

The teacher picks exact seven-class actions, so its labels are exactly what the
student can output. It steers at the camera's brick detection and remembers the
last sighting through odometry for up to 25 actions. A remembered brick that
should be in view but is missing for three frames is forgotten. Without a
sighting it circles toward the side the brick was last seen. It reverses out of
contacts, and the floorplan is used only to back away from walls ahead. It never
reads the brick's true coordinates.

## Run

```sh
PUPPYBOT_PROJECT=$PWD bash datasets/visual-control/chase-v1/collect.sh build/flex/sim/chase-v1/teacher-128
build/flex/control/control train --data build/flex/sim/chase-v1/teacher-128/data/data.bin \
  --output build/flex/sim/chase-v1/train-v1 --categorical --from-scratch --mirror-augment \
  --epochs 60 --batch 2 --checkpoint-every 10 --seed 7
PUPPYBOT_PROJECT=$PWD bash datasets/visual-control/chase-v1/evaluate.sh build/flex/sim/chase-v1/eval NAME POLICY_DIR
```

All runs are headless (`SDL_VIDEODRIVER=offscreen`, display variables unset).
`evaluate.sh` also accepts `teacher` and `forward` as players, and extra run
flags such as `--blackout` or `--large-model`.

`collect.sh` runs 16 shards of 16 games and writes one PVDATA04 file to
`OUT/data/data.bin` with `aggregate.flex`. `aggregate OUTPUT WINDOW BURN
SHARD_DATA...` combines up to 64 shard files from several rounds (fitting games
first, then validation games); with window 300 and burn-in 0, training on it is
byte-identical to the older merged and packed file. Shorter windows split each
game, replaying `BURN` unsupervised frames before each later window. Both
scripts record lean games with wheel-only odometry; set `PUPPYBOT_CHASE_FULL=1`
for videos and traces. `evaluate.sh` splits its 32 games over
`PUPPYBOT_CHASE_PARTS` (8) processes without changing any game's seed or scene.

Training and inference pick a CUDA GPU when one is present, otherwise an AMD
RDNA4 (gfx1201) GPU through HIP; they never fall back to the CPU. The HIP
route loads `libamdhip64.so` (Arch package `hip-runtime-amd`, or put a copy on
`LD_LIBRARY_PATH`). Policies trained before the AMD kernels existed need
`flex/scripts/retarget-policy.sh POLICY NEW_POLICY`, which keeps the weights
and swaps in the current inference binary and kernels.

`seeds.sh ROOT NAME COUNT TRAIN_FLAGS...` trains one configuration with seeds
7, 8, ... and scores each model while the next one trains. `PUPPYBOT_EVAL_FLAGS`
passes flags such as `--fetch` to `evaluate.sh`. The script writes the mean and
standard deviation across seeds to `ROOT/score-NAME.json`. Single retrainings
vary by about 0.6 bricks per minute, so compare seed means.

## Result (28 Oct 2026)

Training: 128 teacher games on layouts 12–17 (112 fitting, 16 validation),
38,400 labelled frames, 1,530 reaches. Small categorical model (324k
parameters), from scratch, mirror augmentation; 60 epochs, then 60 more from
that checkpoint (`train-v2`, validation-selected epoch 57).

Test: 32 one-minute games on the unseen layouts 18 and 19, same seeds for every
player.

| Player | Bricks per minute | Games with a reach | Blocked steps per game |
|---|---:|---:|---:|
| Teacher | 12.8 | 32/32 | 0.5 |
| Chase student, 117 epochs (`train-v2`) | 6.2 | 32/32 | 58 |
| Chase student, 59 epochs (`train-v1`) | 2.7 | 24/32 | 21 |
| Chase student, camera blacked out | 0.22 | 6/32 | 8 |
| Previous find-and-return policy (reversal-neutral) | 0.28 | 7/32 | 147 |
| Always forward | 0.13 | 3/32 | 279 |

Replaying 16 recorded teacher test games through the students
(`probe-*.json` in the build directory): the chase student picks the
teacher's action on 92% of steps (previous policy: 20%). Its steering follows
the brick's horizontal image position (correlation +0.58, teacher +0.61;
previous policy +0.17). Erasing the brick changes 21% of its decisions on
brick-visible frames. In this replay a black screen still matches the teacher
85% of the time because drive feedback carries the teacher's previous command.
In closed loop the blind student scores 0.22, so the camera is what earns its
score.

The student leaves a gap to the teacher and gets blocked far more often (58
versus 0.5 steps per game). It has only seen the teacher's own states.

## Student-driven rounds

`collect --chase --policy DIR` lets a student drive while the teacher labels
every step (`PUPPYBOT_CHASE_POLICY` in `collect.sh`). Each round collects 128
games (256 from round 3) on layouts 12–17 with fresh seeds, then continues
training from the previous model.

| Round | Driver | Data | Test bricks/min | Games with a reach | Blocked steps |
|---|---|---|---:|---:|---:|
| 1 (`train-d1`) | `train-v2` (teacher disagreed 27%) | teacher-128 + 128 student games, 19 epochs | 9.0 | 30/32 | 12.7 |
| 2 (`train-d2`) | `train-d1` (disagreed 18%) | both student rounds, 27 epochs | 8.2 | 26/32 | 0.3 |
| 3 (`train-d3`) | `train-d2` (disagreed 12%) | 256 student games, corrected teacher, 30 epochs | 10.2 | 32/32 | 1.3 |
| 4 (`train-d4`) | `train-d3` (disagreed 10%) | 256 student games, 30 epochs | 10.6 | 32/32 | 0 |
| 4, feedback dropout (`train-d4-drop`) | same | same data, `--drop-drive-feedback-milli 500` | 10.8 | 32/32 | 2.9 |
| 5 (`train-d5-agg`) | `train-d4` (lean collection) | rounds 3–5 aggregated, 768 games, 12 epochs | 10.9 | 32/32 | 0.03 |

Round 2 stopped getting stuck, but its six empty games are one identical
drive: from the same layout-18 start, with no brick in view, it alternates
forward-left and reverse-left, which retraces the same arc. Before any
sighting the teacher chose its search direction from seed parity, which the
camera cannot reveal, so identical opening frames carried contradictory search
labels. The teacher now turns left until a sighting decides the side; mirror
augmentation supplies the right-hand version. Rounds after this change use only
data labelled by the corrected teacher. On the test games the corrected teacher
scores 12.5 bricks per minute (32/32 games, 0.03 blocked steps), against 12.8
for the seed-parity teacher.

Round 3 scored in every test game; the six games round 2 left empty now score
6–14 bricks. The remaining gap to the teacher is spread across games rather
than concentrated in failures.

Round 4 gains little, and dropping drive feedback on half the training sequences
changes the score by less than the game-to-game noise (per-game spread is about
3.5 bricks, so the standard error over 32 games is about 0.6). Each round now
overfits: training loss falls to 0.12 while validation loss on the round's own
32 held-out games stays near 0.8. Only the latest round's 256 games fit in one
PVDATA01 file (6.4 MB per game, 2 GB file cap), so earlier rounds are dropped
rather than aggregated. Seed 990001 is still the worst game for every student:
the brick leaves the view and circling never brings it back.

Aggregating rounds 3–5 (`aggregate.flex`, 672 fitting and 96 validation games)
stops the overfitting: validation loss falls from 0.65 to 0.44 (selected epoch
8) instead of staying near 0.8. The test score barely moves: paired over the 32
games, round 5 is +0.38 ± 0.43 bricks per minute over round 4, and the teacher
is still 1.6 ± 0.5 ahead. Seed 990001 still scores 1.

The trainer's drive-feedback dropout path copied batches with `vc_copy`, which
needs `vc_init`; the trainer only called it with auxiliary supervision, so
dropout crashed the small categorical model through a null `memcpy`. It now
uses the trainer's own `pt_memcpy`.

## Fetch game (28 Oct 2026)

`--fetch` (with `collect`, `run`, and as an extra flag to the scripts)
alternates the two targets of the real task: after each reach the robot must
stop facing the box before the next brick appears. In task 3 the simulator's
find-and-return check (stopped 0.30–0.65 m from the camera-located box, within
35°, for three frames) now counts a delivery and play continues. The chase game
places a new brick at once and so never reaches this check. The score is
deliveries per minute.

The camera points down: the box leaves the top of the 84×84 image at about
1.8 m, and the rim-marker box detector works only within about 1.1 m. Bricks
are therefore placed 0.7–1.5 m from the box, on a clear straight line from the
robot. While carrying, the teacher steers at its last camera sighting of the
box, kept for the whole game through odometry because the box never moves. It
stops 0.40–0.58 m from the box.

Three teacher fixes found on the test layouts apply only to fetch, so chase
labels are unchanged; the chase teacher still reproduces every recorded test
game exactly.

- Circling never found a brick about 2 m away, so after each full circle the
  search drives straight for 12 actions.
- Wheel-odometry drift left a wrong box memory, so a remembered box not seen
  again within 0.9 m is forgotten.
- After reversing onto a brick behind it, each contact made it reverse again,
  for 216 steps. Three or more contacts in a row now alternate forward and
  reverse.

While carrying, the last feedback slot is 1. That slot is the task-event slot,
and every other path still requires it to be zero. Training on fetch data needs
`--carry-cue`, which allows exactly 0 or 1 there. `run --hide-carry` keeps the
slot at 0 for the policy.

| Player (32 test games) | Deliveries per minute | Games with a delivery | Bricks per minute |
|---|---:|---:|---:|
| Teacher | 4.28 | 32/32 | 4.72 |
| Fetch student, 3 seeds (`fetch-t1`) | 3.81 ± 0.08 | 31/32 each | 4.22 |
| Plus one student-driven round, 3 seeds (`fetch-d1`) | 3.56 ± 0.27 | | 3.98 |
| `fetch-t1-s2` with the carrying bit hidden | 4.19 | 31/32 | 4.59 |
| Chase student `train-d5-agg` | 0 | 0/32 | 0.97 |
| Always forward | 0 | 0/32 | 0.03 |

`fetch-t1` trains 30 epochs from the round-5 chase student, with mirror
augmentation. Its data is 256 teacher games on layouts 12–17, where the teacher
makes 4.25 deliveries per minute. Validation loss falls from 10.9 at epoch 0 to
0.13. Averaged over seeds, the student is 0.47 ± 0.21 deliveries per minute
behind the teacher.

Its box leg matches the teacher's: about 32 versus 30 actions per leg. The gap
is brick search: about 34 versus 29 actions, with three times as many legs over
60 actions. All three seeds score zero on seed 990018, where the first brick
starts about 2 m away and out of view; only the teacher's straight search finds
it.

The student-driven round changes the score by less than the noise. In it the
teacher disagreed with the driving student on 22% of steps; training then used
512 aggregated games for 15 epochs.

### Search-heavy fetch data

`collect --fetch --far-bricks` places every brick 0.7–2.0 m from the box and
out of camera view: more than 1.8 m from the robot or more than 35° off its
heading. The teacher makes 3.58 deliveries per minute on such games against
4.19 on normal ones, so more of each game is search. Test games keep the
normal placement. All arms below train 30 epochs from the round-5 chase
student on AMD (3 seeds each) and are scored on the 32 test games:

| Training data | Deliveries per minute | Seed 990018 deliveries | Cycles per run |
|---|---:|---:|---:|
| 256 normal games (`fetch-t1`, AMD) | 3.95 ± 0.05 | 0, 0, 0 | 126.3 |
| 512 normal games (seed 870000 added) | 3.90 ± 0.08 | 4, 0, 0 | 124.7 |
| 256 normal + 256 far-brick games (seed 900000) | 4.33 ± 0.07 | 2, 4, 4 | 138.7 |
| Teacher | 4.28 | 4 | 137.0 |

Paired over the 32 games (seed means), far-brick data adds 0.44 ± 0.15
deliveries per minute over the same amount of normal data, which itself
changes nothing (−0.05 ± 0.17 against 256 games). The students now match the
teacher. Median brick-to-box cycles stay at 56–58 steps for every player; the
gain is fewer games where the robot never finds the next brick. Data and
models are in `build/flex/sim/fetch-v2`.

On HIP, policy inference sharing the GPU with a training run stalls past the
45 s process-stream limit (a CPU load alone does not), so `seeds.sh` evaluates
each HIP-trained model before the next training starts.

### Search levels

`collect`/`run --fetch --level N` places every brick relative to the robot's
pose at placement time, independent of the box: 1 in view (0.6–1.5 m, within
35° of the heading; the camera's half-angle is 37.6°), 2 just off view
(0.6–1.5 m, 40–90°), 3 out of view in the same room (1.0–2.5 m behind, or
1.8–3.0 m in any direction), 4 a doorway drill on a two-room layout (below), 5
anywhere free in the other room of a two-room layout (rooms split at the
`Wall.partition` walls). Levels 4 and 5 swapped on 2 Nov 2026 so that the
numbers follow difficulty: the results in this README and LOG entries 1–34 use
the old numbering (4 other room, 5 doorway drill), and `levels/score.sh`
refuses to add new level 4 or 5 games to a root holding old ones. A seed gives
the same game under the new number, so an old level 5 score is a new level 4
score and the reverse. A fetch robot faces the box at every placement, which
can block the whole level 1 cone, so that cone widens by 10° every 300 tries;
levels 1–2 keep a clear straight line when possible. Without `--level`
placement is unchanged (the teacher reproduces all 32 test games).
`PUPPYBOT_EVAL_TWO_ROOM=1 evaluate.sh` plays all 32 games on the two-room
layout 19, for levels 4 and 5.

Deliveries per minute on 32 test games per level (`build/flex/sim/levels-v1`):

| Level | Teacher | Far-brick students (3 seeds) | 256-game students (3 seeds) |
|---|---:|---:|---:|
| 1 in view | 4.41 | 3.51 ± 0.36 | 3.27 ± 0.30 |
| 2 just off view | 3.97 | 3.85 ± 0.21 | 3.68 ± 0.25 |
| 3 out of view, same room | 1.88 | 0.68 ± 0.30 | 0.35 ± 0.18 |
| 4 other room | 0.03 | 0 | 0 |

The teacher is the limit from level 3 on: circling plus 12 straight actions
finds bricks 2–3 m away in only 24 of 32 games, and it has no notion of
doorways, so the other room is reached by chance. Students fall further behind
it there, and also trail it at level 1, where bricks lie beside the box rather
than 0.7–1.5 m from it as in all their training data.

### Exploring teacher

`collect --fetch --explore-teacher` replaces the circling search with one that
plans through the privileged floorplan but decides only from what the robot
could know. Since the brick appeared, every 10 cm cell the camera has covered
(rays to 1.9 m within 27.5° of the true heading, stopped by walls and the box,
plus the 0.35 m reach) is marked seen; the search drives a breadth-first route,
0.30 m clear of walls, to an unseen cell that could hold a brick, scored by
route length, turning and unseen cells around it. The unseen brick position
never enters a decision; a counter of covered cells that held the brick
without a detection checks the coverage model (`coverageMisses`, 1–5 per 32
games). Coverage follows whoever drives, so labels stay valid when a student
drives. Camera sightings are steered at as before. Carrying, it routes to the
box (which never moves and the robot started beside) whenever the straight
line is blocked or the box is out of mind, and near an unseen box it faces it
and backs away until the camera finds it. Without the flag the teacher is
unchanged: all 64 level 1 and 3 test games reproduce exactly.

| Level | Teacher | Exploring teacher | Games with a delivery |
|---|---:|---:|---:|
| 1 in view | 4.41 | 8.31 | 32 |
| 2 just off view | 3.97 | 5.81 | 32 |
| 3 out of view, same room | 1.88 | 2.50 | 32 |
| 4 other room | 0.03 | 0.94 | 25 |

Most of the level 1–2 gain is the return: the old teacher circled in place
whenever it lost sight of a nearby box. Level 4 is bounded by search order:
the teacher cannot know the brick is in the other room, so it covers the
start room (about 100 steps in the large room of layout 19) before crossing.
`PUPPYBOT_CHASE_TWO_ROOM=1 collect.sh` collects on the two-room training
layouts 13, 15 and 17 only, for level 4. On the standard 32 test games the
exploring teacher makes 4.91 deliveries per minute (old teacher 4.28).

Students trained on 128 exploring-teacher games each of normal placement and
levels 1–4 (640 games, 30 epochs from the round-5 chase student, 3 seeds,
`build/flex/sim/levels-v1/mix-s*`), deliveries per minute:

| Test | Exploring teacher | Level-mix students | Far-brick students |
|---|---:|---:|---:|
| Standard | 4.91 | 3.19 ± 0.86 | 4.33 ± 0.07 |
| Level 1 | 8.31 | 5.14 ± 1.27 | 3.51 ± 0.36 |
| Level 2 | 5.81 | 3.70 ± 1.70 | 3.85 ± 0.21 |
| Level 3 | 2.50 | 0.79 ± 0.21 | 0.68 ± 0.30 |
| Level 4 | 0.94 | 0.01 | 0 |

The students copy the faster return (level 1) but not the search, and vary
widely between seeds: the teacher's search depends on which floor it has
already covered, which the student must infer from its own frames and memory,
and teacher-driven data never shows the student the states its own mistakes
lead to.

One DAgger round does not fix this. `mix-s2` (4.03 on the standard test)
drove 128 games per level while the exploring teacher labelled every step;
it delivers 3.99, 7.30, 4.88, 0.76 and 0.05 per minute on normal placement and
levels 1–4, and the teacher disagrees with 88, 65, 75, 168 and 166 of its 300
actions. Training reads at most 1024 games, so the round-1 set keeps 64
teacher and all 128 student-driven games per level (960). Three students
fine-tuned 15 epochs from `mix-s2` on it (`agg1-s*`):

| Test | Level-mix students | Round 1 students |
|---|---:|---:|
| Standard | 3.19 ± 0.86 | 2.48 ± 0.58 |
| Level 1 | 5.14 ± 1.27 | 5.23 ± 0.38 |
| Level 2 | 3.70 ± 1.70 | 3.73 ± 0.60 |
| Level 3 | 0.79 ± 0.21 | 0.59 ± 0.35 |
| Level 4 | 0.01 | 0.03 |

All three fall below their starting policy on the standard test, and their
validation loss stays at 0.53–0.59 (0.29 for `mix-s2` on teacher data): on
student-driven search states the labels follow the teacher's coverage map and
sticky goal, which the student's frames and 128-wide memory do not determine.

### Sweep teacher and the doorway drill

`--sweep-teacher` searches with decisions a student can take from its current
view and a short memory, with no coverage map: turn a full circle (forward arcs,
reversing from walls), then keep turning until the heading shows a doorway into
another room (1.5 m open) or 2 m of open floor (1.2 m after a second circle),
never back the way the last drive came; route up to 2.5 m that way and turn
again. The floorplan only plans routes and measures what is open in view.
Sightings and the routed return are those of the exploring teacher.

The doorway drill (`--level 4`, `--level 5` before the swap) is on a two-room
layout: half the bricks appear as in level 1, the other half 0.6–1.5 m past
the doorway in the other room (within 0.8 m of its centre line). Deliveries
per minute on 32 test games:

| Level | Old teacher | Coverage teacher | Sweep teacher | Sweep, doorway before the full circle |
|---|---:|---:|---:|---:|
| 1 | 4.41 | 8.31 | 5.97 | 5.06 |
| 2 | 3.97 | 5.81 | 5.19 | 4.44 |
| 3 | 1.88 | 2.50 | 2.34 | 2.28 |
| 4 | 0.03 | 0.94 | 0.66 | 0.53 |
| 5 | 0.97 | 2.00 | 1.28 | 1.56 |

Taking a doorway as soon as one is in view helps only the drill: elsewhere it
abandons bricks near the robot that are not yet in view, so the sweep teacher
keeps the full circle.

On the training layouts (128 games per level, `sweep-L*`) the sweep teacher
makes 5.02, 5.76, 5.30, 2.09, 0.14 and 1.09 deliveries per minute on normal
placement and levels 1–5. Level 4 is far below the 0.66 of test layout 19:
the robot starts facing the box, which hides the doorway, and the first
direction with 2 m of open floor after the circle leads into the large start
room. Remembering a doorway seen during the circle, and judging doorways by
line of sight anywhere in the camera's view, raised pickups only from 3 to 6
in six training games, so neither was kept.

Three students fine-tuned 30 epochs from `train-d5-agg` on the 640 sweep games
of normal placement and levels 1–4 (`data-sweep`, `swp-s*`), against the
level-mix students of the exploring teacher:

| Test | Level-mix students | Sweep students | Sweep teacher |
|---|---:|---:|---:|
| Standard | 3.19 ± 0.86 | 4.03 ± 1.28 | |
| Level 1 | 5.14 ± 1.26 | 4.26 ± 1.39 | 5.97 |
| Level 2 | 3.70 ± 1.69 | 3.89 ± 1.28 | 5.19 |
| Level 3 | 0.79 ± 0.21 | 0.81 ± 0.23 | 2.34 |
| Level 4 | 0.01 | 0.01 | 0.66 |
| Level 5 | 0.77 ± 0.02 | 0.75 ± 0.24 | 1.28 |

The map-free teacher is easier to copy on the standard test, but the students
still lose two thirds of its level-3 search and all of its level-4 search.

### Noise bursts in the teacher's games (DART)

`collect --action-noise 3` starts a burst of 2–6 random actions with 3%
probability per step while the teacher drives, about 10% of all steps; every
step keeps the teacher's own choice as its label, so the student sees how the
teacher recovers from small mistakes. The same 640 sweep games with noise
(`levels/collect.sh ROOT dart 910000 --action-noise 3`, `data-dart`) deliver
4.04, 4.75, 4.41, 1.78 and 0.18 per minute on normal placement and levels 1–4
(clean: 5.02, 5.76, 5.30, 2.09, 0.14). Students trained as the sweep students
(`dart-s*`):

| Test | Sweep students | Noisy-teacher students |
|---|---:|---:|
| Standard | 4.03 ± 1.28 | 4.55 ± 0.08 |
| Level 1 | 4.26 ± 1.39 | 5.21 ± 0.02 |
| Level 2 | 3.89 ± 1.28 | 4.83 ± 0.12 |
| Level 3 | 0.81 ± 0.23 | 0.67 ± 0.13 |
| Level 4 | 0.01 | 0 |
| Level 5 | 0.75 ± 0.24 | 0.81 ± 0.08 |

The noise makes the students both better and far more consistent between
seeds wherever they already find the brick (standard test, levels 1 and 2;
spread 0.08 instead of 1.28), but does nothing for the search itself.

### Self-imitation

`collect --policy DIR --self-imitate STEPS` lets the student drive and keeps
as labels only its own actions in quick cycles: from the brick appearing to
its delivery within STEPS steps. Every other row has weight 0. `dart-s2` drove
64 training games per level with 3% noise bursts (`levels/collect.sh ROOT self
980000 --self-imitate 200 --action-noise 3`). It kept 13,969, 13,326, 13,518,
4,891, 0 and 3,876 of 19,200 steps on normal placement and levels 1–5; on
level 4 it never delivers, so there is nothing to keep. Training stops on a
batch whose every row has weight 0, so only games with a kept cycle (239 of
384) joined the 640 noisy teacher games. Three students fine-tuned 15 epochs
from `dart-s2` on that set (`self-s*`), against the same 15 epochs on the
teacher games alone (`more-s*`):

| Test | `dart-s2` | 15 more epochs, teacher games | Plus kept cycles |
|---|---:|---:|---:|
| Standard | 4.63 | 4.52 ± 0.07 | 3.15 ± 0.15 |
| Level 1 | 5.22 | 5.27 | 4.46 |
| Level 2 | 4.75 | 4.82 | 3.61 |
| Level 3 | 0.69 | 0.97 | 0.48 |
| Level 4 | 0 | 0.09 | 0.10 |
| Level 5 | 0.78 | 0.81 | 1.02 |

The kept cycles make the student worse everywhere except the doorway drill.
They included the noise bursts themselves, so about one kept label in ten was
a random action. Noise steps are now never kept. The same games again with
them left out (`self2-*`, 12,523, 12,017, 12,125, 4,417 and 3,516 rows kept on
normal placement and levels 1, 2, 3 and 5):

| Test | 15 more epochs, teacher games | Plus kept cycles without noise steps |
|---|---:|---:|
| Standard | 4.52 ± 0.07 | 4.60 ± 0.25 |
| Level 1 | 5.27 | 4.78 |
| Level 2 | 4.82 | 4.68 |
| Level 3 | 0.97 | 0.83 |
| Level 4 | 0.09 | 0 |
| Level 5 | 0.81 | 0.79 |

Without the noise labels the damage is gone, but so is any gain: the student
can only reinforce searches it already completes, and it completes almost none
past level 2.

### Staged curriculum

Three students trained in stages from `train-d5-agg` on the noisy teacher
games: normal placement and levels 1–2 for 20 epochs, then with level 3 for 15,
then all of levels 0–5 for 10 (`staged-s*`). The same number of game-epochs
with everything mixed from the start is 30 epochs of levels 0–5 (`mixed-s*`):

| Test | Staged | Mixed |
|---|---:|---:|
| Standard | 4.36 ± 0.44 | 4.48 ± 0.11 |
| Level 1 | 4.71 | 4.85 |
| Level 2 | 4.60 | 4.56 |
| Level 3 | 0.80 ± 0.20 | 0.56 ± 0.09 |
| Level 4 | 0 | 0 |
| Level 5 | 0.76 | 0.82 |

Staging gains a little on level 3 and nothing elsewhere. Adding the level-5
drill games to training (mixed, against the level 0–4 `dart-s*`: 0.82 against
0.81) does not improve the drill either.

### Longer level-4 games

With 512-step games instead of 300 (`PUPPYBOT_CHASE_HORIZON=512`), the sweep
teacher delivers in 26 instead of 20 of the 32 level-4 test games, at the same
rate (0.68 against 0.66 per minute); `more-s1` in 8 instead of 6 (0.22 per
minute both) and `dart-s2` in none. Level 4 is limited by the search, not by
the one-minute game, so longer training games would add few successful
searches.

### Camera pitch

In the fetch game the wrist camera drives in the compact search pose: eye
0.45 m above the floor, looking 42° down with a 60° vertical field of view,
which sees the floor from about 0.15 m to 2.1 m ahead. `--camera-pitch DEG`
(collect and run; simulator `--camera-pitch`) sets the wrist pitch of that
pose, default 75. At 82 the camera looks 35° down and sees to the far walls
and doorways; 86 and above have no arm solution, and lower values look down
at the robot's own wheel.

At pitch 82 (`build/flex/sim/levels-v1/pitch82`) the sweep teacher, which
plans its search from the floorplan, changes little; 640 noisy teacher games
and three students trained as `dart-s*`, all played at pitch 82:

| Test | Teacher, 75 | Teacher, 82 | Students, 75 | Students, 82 |
|---|---:|---:|---:|---:|
| Standard | | | 4.55 ± 0.08 | 4.54 ± 0.25 |
| Level 1 | 5.97 | 6.13 | 5.21 | 4.77 |
| Level 2 | 5.19 | 5.13 | 4.83 | 4.27 |
| Level 3 | 2.34 | 2.34 | 0.67 ± 0.13 | 1.40 ± 0.52 |
| Level 4 | 0.66 | 0.44 | 0 | 0 |
| Level 5 | 1.28 | 1.59 | 0.81 | 0.95 |

The higher view doubles the students' level-3 search (every pitch-82 seed,
0.94–1.97, beats every pitch-75 seed, 0.53–0.78) and helps the doorway drill,
at a small cost on levels 1 and 2, where the brick appears smaller. It is the
first change that improves the students' search.

### Reinforcement learning

`collect --sample-actions` (fetch collect with `--policy`, no noise or
self-imitation) lets the student play by sampling each action from its own
output and stores the discounted return (γ 0.99) in each row's weight. A pickup
earns 0.5, a delivery 1, and the first entry into the brick's room 0.3 when the
brick is in the other room. Each iteration the policy plays 288 games at pitch
82 (32 on each of levels 0–2, 64 on each of levels 3–5), the advantage of each
row is its return less the mean of rows with the same level, carrying state
and 50-step slice of the game, divided by that group's spread (at least 0.25),
and a row is kept with probability exp(min(z, 2) − 2), since training takes
only 0/1 weights. Two epochs at 2e-4 from the previous policy on the kept rows
plus the 640 pitch-82 noisy teacher games (an anchor) give the next policy.
Starting from `dart-s2` (`build/flex/sim/levels-v1/rl`), scored at pitch 82:

| Policy | Standard | Level 3 | Level 4 | Level 5 |
|---|---:|---:|---:|---:|
| `p0` (`dart-s2`) | 4.81 | 1.97 | 0 | 1.09 |
| `p1` | 4.56 | 1.63 | 0 | 0.69 |
| `p2` | 4.31 | 1.28 | 0.03 | 0.81 |
| `p3` | 3.88 | 1.16 | 0 | 0.69 |
| `p4` | 3.75 | 1.41 | 0.03 | 0.69 |
| `p5` | 3.56 | 1.22 | 0 | 0.63 |
| `p6` | 3.63 | 1.31 | 0 | 0.72 |

Every iteration loses ground on every level; sampled play on level 4 delivers
0.16 per minute with `p0` and 0.02–0.05 after. About 20% of rows are kept,
most of them the policy's own sampled choices, so training mostly imitates
sampling noise, which blurs the student. Level 4 gives about two deliveries in
64 games, too little to learn from.

Level 5 scores hide the doorway: split by where each brick appeared (a brick
still out when the game ends counts as missed), nearly all of its deliveries
are the level-1 half.

| Level-5 bricks delivered | In the robot's room | Past the doorway |
|---|---:|---:|
| Sweep teacher, test | 33 of 41 | 18 of 42 |
| `dart-s0`–`s2`, test | 85 of 92 | 6 of 95 |
| `p1`–`p6`, test | 132 of 150 | 3 of 177 |
| Sampled play by `p0` | 67 of 77 | 19 of 73 |
| Sampled play by `p1`–`p5` | 253 of 291 | 21 of 303 |

The students almost never fetch a brick from past the doorway, even 0.6–1.5 m
beyond it, and RL lowers that further. An earlier run without the spread floor
gave a few rows weights above 1000 and was stopped after one iteration.

Adding 256 noisy sweep-teacher doorway-drill games (the teacher reaches 99 of
315 past-doorway bricks on the training layouts) to the 640 pitch-82 games
does not help: three students (`door-s*`) score 4.15 on the standard test
(3.50, 4.56, 4.38), 1.23 on level 3, 0 on level 4 and fetch 2 of 89
past-doorway bricks. Once in the brick's room students deliver about as often
as the teacher; getting there is what fails:

| Past-doorway bricks, test | Robot reaches the brick's room | Delivered |
|---|---:|---:|
| Sweep teacher | 27 of 42 | 18 |
| `dart-s*` and `door-s*` | 15 of 184 | 8 |

Nor does one round of DAgger: `dart-s2` drives 288 pitch-82 games (32 on each
of levels 0–2, 64 on each of levels 3–5) while the sweep teacher labels every
step (it disagrees on 40 of 300 steps on levels 0–2 and 104–166 on levels 3–5),
and three seeds fine-tune `dart-s2` on them for 10 epochs (`dag-s*`). They
score 4.02 on the standard test (4.22, 3.75, 4.09), 3.74 on level 1, 1.45 on
level 3, 0.02 on level 4, and reach the brick's room for 13 of 89 past-doorway
bricks.

On level 5 the students drive straight on 6–12% of steps, the teacher on 32%.
`--straight-bias HUNDREDTHS` (chase collect and run with `--policy`) raises
the straight-ahead class before the most likely class is taken, and
`--straight-after STEPS` applies it only once a search without the brick has
lasted that long since the last delivery. On `dart-s2` (bias 1 reproduces its
plain scores):

| Straight bias | Standard | Level 1 | Level 3 | Level 4 | Level 5 | Past-doorway bricks: room reached |
|---|---:|---:|---:|---:|---:|---:|
| None | 4.81 | 4.97 | 1.97 | 0 | 1.09 | 8 of 35 |
| 0.5 | 4.66 | | 1.84 | 0 | 1.00 | 7 of 36 |
| 1 | 4.53 | | 1.88 | 0 | 0.81 | 5 of 33 |
| 2 | 3.22 | | 1.09 | 0.16 | 0.84 | 20 of 34 |
| 2 after 40 steps | 4.84 | 4.91 | 2.03 | 0 | 1.06 | 8 of 34 |
| 2 after 80 steps | 4.84 | 5.03 | 1.97 | 0 | 1.03 | 7 of 34 |
| 3 after 80 steps | 4.84 | 5.03 | 2.00 | 0 | 0.97 | 7 of 33 |

A strong bias from the first step reaches the other room nearly as often as
the teacher (27 of 42) but wrecks ordinary fetching; driving straight only
after a failed circle does not find the doorway. Teacher labels against the
student's own actions in the DAgger games show where the student departs:

| Level 5, `dart-s2` driving | Student agrees |
|---|---:|
| Teacher turns forward the circling way | 91% |
| Teacher drives straight | 60% (25% turns the circling way) |
| Teacher turns forward the other way | 5% (71% turns the circling way) |

The other-way turns and most straight steps come from the sweep teacher's
routes (grid routes on the reference floorplan to open floor straight ahead);
the student keeps circling instead of following them.

Driving those routes straight while the floor ahead is free makes the teacher
miss the doorway (level 4 0.03, level 5 0.97; 12 of 36 past-doorway bricks
reach the other room). `--door-pass` (sweep teacher, levels 4 and 5) instead
steers, once the heading shows a doorway, at a point 0.45 m short of its
centre and then at one 0.6 m past it with the brick-approach steering law
(arc when more than 0.2 rad off, otherwise straight), then turns a fresh
circle. The teacher keeps its doorway (level 4 0.47, level 5 1.44, 27 of 42
past-doorway bricks reach the other room). 128 level-4 and 256 level-5
door-pass games on the seeds of `dart-L4`/`dart-L5`, with `dart-L0`–`L3`,
train `pass-s*`, against `door-s*` (the same games with grid-route doorways):

| Test | `door-s*` | `pass-s*` |
|---|---:|---:|
| Standard | 4.15 | 4.35 (4.22, 4.50, 4.34) |
| Level 1 | 4.32 | 5.03 |
| Level 2 | 4.30 | 4.27 |
| Level 3 | 1.23 | 1.30 |
| Level 4 | 0 | 0.03 |
| Level 5 | 0.75 | 0.79 |
| Past-doorway bricks: room reached | 3 of 89 | 14 of 95 |
| Past-doorway bricks delivered | 2 | 5 |

The students still rarely set off for the doorway: the teacher only does so
after a full circle, which they must count in memory. `--door-early` (with
`--door-pass`) also takes a doorway in view during the first circle. The
teacher gains on level 4 (0.66; level 5 1.38, 36 of 41 past-doorway bricks
reach the other room) and keeps 29 of 35 same-room level-5 bricks (31 of 36
without). The same 384 games played that way train `early-s*`:

| Test | `dart-s*` | `pass-s*` | `early-s*` |
|---|---:|---:|---:|
| Standard | 4.54 | 4.35 | 4.27 (4.13, 4.41, 4.28) |
| Level 1 | 4.77 | 5.03 | 5.06 |
| Level 2 | 4.27 | 4.27 | 4.56 |
| Level 3 | 1.40 | 1.30 | 1.14 |
| Level 4 | 0 | 0.03 | 0.09 (0.03, 0.06, 0.19) |
| Level 5 | 0.95 | 0.79 | 1.08 |
| Past-doorway bricks: room reached | 12 of 95 | 14 of 95 | 41 of 107 |
| Past-doorway bricks delivered | 6 | 5 | 19 |

Every `early-s*` seed delivers on level 4, the first students to do so.

A DAgger round with that teacher (`early-s2` drives 64 level-4 and 64 level-5
games, the door-early teacher labels every step and disagrees on 158–185 of
300) added to the 896 games trains `edag-s*`: standard 3.44 (2.44, 3.53,
4.34), level 1 4.21, level 3 0.95, level 4 0.16 (0.06, 0.09, 0.31), level 5
1.23, and 64 of 113 past-doorway bricks reach the other room (27 delivered),
near the teacher's rate. Validation loss rises from 0.26 to 0.37–0.41: labels
on the student's own detours depend on the teacher's search state, which the
camera does not show, and the standard test suffers.

Rebalancing toward normal placement (64 more noisy teacher games there, half
the level-5 door-early games dropped, 960 games, `edagb-s*`) restores the
standard test, 4.32 (4.47, 3.94, 4.56), but loses the doorway: level 4 0.07,
level 5 0.88, 22 of 99 past-doorway bricks reach the other room. The doorway
skill follows the number of door-early level-5 games, and so far it has come
at the expense of ordinary fetching.

Playing three seeds together (`run --ensemble DIR`, repeatable: each member
keeps its own memory and the most likely class of their mean probabilities is
driven; `levels/runs/15-ensemble.sh`, two parts so that no more than about 8
policy processes share the GPU) helps ordinary fetching and rescues collapsed
seeds, but drops the doorway (seed means in brackets):

| Test | `dart-s*` | `early-s*` | `edag-s*` |
|---|---:|---:|---:|
| Standard | 4.72 (4.54) | 4.56 (4.27) | 4.44 (3.44) |
| Level 1 | 5.09 (4.77) | 5.78 (5.06) | 5.16 (4.21) |
| Level 2 | 4.50 (4.27) | 4.69 (4.56) | 4.84 (3.65) |
| Level 3 | 1.34 (1.40) | 1.25 (1.14) | 1.25 (0.95) |
| Level 4 | 0 (0) | 0.03 (0.09) | 0.09 (0.16) |
| Level 5 | 0.88 (0.95) | 0.84 (1.08) | 0.97 (1.23) |
| Past-doorway bricks: room reached | 3 of 32 | 2 of 30 | 9 of 34 |

Setting off for the doorway is a minority choice among the members, and the
mean returns to circling.

DAgger on normal placement does not steady the seeds either: `edag-s0` and
`edag-s1` each drive 64 level-0 games while the teacher labels every step, in
place of half the `dart-L0` and `dart-L1` games (`levels/runs/16-standard-dagger.sh`,
`sdag-s*`): standard 3.66 (3.53, 4.38, 3.06), level 1 4.32, level 2 3.81,
level 3 1.03, level 4 0.05, level 5 0.97, 38 of 105 past-doorway bricks reach
the other room.

`run --ensemble-until STEPS` lets the members vote only until STEPS steps pass
without carrying or a delivery; then the main policy drives alone (the
members still run, keeping their memory). With the doorway student `edag-s2`
as main and `dart-s1`, `dart-s2` as members (`levels/runs/17-ensemble-until.sh`):

| STEPS | Standard | Level 1 | Level 2 | Level 3 | Level 4 | Level 5 | Past-doorway: room reached |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 20 | 4.84 | 4.94 | 4.75 | 1.50 | 0.13 | 1.00 | 9 of 36 |
| 35 | **5.03** | 5.34 | 5.06 | 1.63 | 0.06 | 0.97 | 9 of 35 |
| 60 | 4.84 | 5.28 | 5.06 | 1.69 | 0.16 | 0.91 | 19 of 33 |

`PUPPYBOT_EVAL_SELECTION=1` makes `evaluate.sh` play the same 32-game format on
the training layouts with seeds 980000+, for choosing players without the test
games. On normal placement it ranks the STEPS-35 mix first of nine (4.81, the
`dart-s*` students 4.53–4.69, the plain `dart` ensemble 4.72), so its gain is
not test tuning (`levels/runs/21-selection-standard.sh`).

The doorway skill does not generalize. A second door-early DAgger round
(`edag2-s*`, `levels/runs/18-doorway-specialist.sh`) gives seeds that reach
the other room for 3 to 23 of about 33 past-doorway bricks on test layout 19,
and their ranking on the training two-room layouts does not predict it
(`levels/runs/19-seed-selection.sh`: the best of eight there, `edag2-s7`,
reaches 6 of 34 on the test). 128 door-early games on 16 two-room layouts from
`generate-diverse` (IDs 27–57, `collect.sh` with `PUPPYBOT_CHASE_SCENES` and
`PUPPYBOT_CHASE_LAYOUTS`), added to the `early` set, make it worse, with the
obstacle (`div-s*`: 4 of 91) or without (`--no-obstacle`, `dno-s*`: 1 of 87),
and lower every other level too (`levels/runs/20-diverse-layouts.sh`,
`22-diverse-no-obstacle.sh`).

A sampled game takes about 12 s (40 ms a step): the simulator, controller and
policy work in turn, none fully busy. Four games at once leave the 12 CPUs 58%
idle with the GPU 57% busy on four single-frame policies; an iteration is 16
minutes of play, 1 of training and 4.5 of scoring.

### Model size

Small (128 memory values, 324k parameters) and large (256 memory values, wider
encoder, about 3M parameters) students from scratch on the 640 exploring-teacher
games, 40 epochs, three seeds each (`levels/size.sh`). The large model only
learns at a 2e-4 learning rate (at 7e-4 it stays at the action prior); the
small model is no better at 2e-4 than at its usual 7e-4:

| Test | Small, 7e-4 | Small, 2e-4 | Large, 2e-4 |
|---|---:|---:|---:|
| Standard | 0.38 ± 0.28 | 0.34 ± 0.17 | 1.55 ± 0.30 |
| Level 1 | 0.98 | 0.19 | 1.18 |
| Level 2 | 0.44 | 0.24 | 1.31 |
| Level 3 | 0.07 | 0.05 | 0.28 |
| Level 4 | 0 | 0 | 0 |

The large model is four times better from scratch, but both stay far below the
small model fine-tuned from the chase student `train-d5-agg` on the same games
(3.19): the starting point matters more than the size. A large model has no
such starting point yet. Large-model training keeps the RX 9070 98% busy at
about 38 s per epoch.

### What the student's memory holds

`run --record-memory` writes, at every step, the 128 (or 256) memory values
with 16 true facts of the game (`memory.bin`). A linear probe fitted on even
games and scored on odd ones (96 games on normal placement and levels 3 and 4)
shows what can be read out of the memory; an untrained network's memory is the
control:

| Fact | Level-mix `mix-s2` | Sweep `swp-s2` | Untrained |
|---|---:|---:|---:|
| Carrying (balanced accuracy) | 0.92 | 0.97 | – |
| Brick in view now | 0.86 | 0.91 | 0.50 |
| Brick seen in the last 10 steps | 0.80 | 0.87 | 0.50 |
| Turned a full circle since the brick appeared | 0.84 | 0.95 | – |
| Steps since the brick appeared (R²) | 0.47 | 0.76 | 0.09 |
| Box distance (R²) | 0.20 | 0.75 | < 0 |
| Box bearing, left (R²) | 0.23 | 0.61 | – |
| Where a brick seen earlier now is (R²) | < 0 | < 0 | – |
| Which room (balanced accuracy) | 0.50 | – | – |

The memory holds what the sweep teacher's decisions need: whether it carries,
how long since it saw the brick, how far it has turned and where the box is
(path integration from its own controls). It does not hold where a brick it
lost sight of is, nor which room it is in; the large from-scratch model (256
values) is no better on these (R² < 0). Neither teacher returns to a lost
brick by memory, so nothing in the training labels asks for it.

### Checkpoint by validation loss or by driving

Every model keeps the checkpoint with the lowest validation loss. Its score,
and the scores of the epoch 10, 20 and 30 checkpoints, on the 32 test games:

| Model | Kept epoch | Kept | Epoch 10 | Epoch 20 | Epoch 30 |
|---|---:|---:|---:|---:|---:|
| `mix-s0` | 21 | 3.22 | 3.03 | 2.94 | 2.06 |
| `mix-s1` | 30 | 2.31 | 2.88 | 2.03 | 2.31 |
| `mix-s2` | 26 | 4.03 | 4.56 | 2.50 | 3.44 |
| `swp-s0` | 30 | 2.56 | 3.94 | 4.41 | 2.56 |
| `swp-s1` | 17 | 4.66 | 4.59 | 4.50 | 4.28 |
| `swp-s2` | 19 | 4.88 | 4.16 | 4.28 | 4.47 |

Scores swing by up to 2 per minute between checkpoints a few epochs apart, at
almost the same validation loss, so validation loss is a weak guide to driving.
Epoch 10 is on average as good as the kept checkpoint (3.49 against 3.19 for
the level mix, 4.23 against 4.03 for the sweep). Choosing by driving would need
its own set of games: picking the best on the 32 test games would overstate it.

### Reproducing the level experiments

`PUPPYBOT_PROJECT=$PWD bash datasets/visual-control/chase-v1/levels/run.sh
[ROOT]` runs every step above in order (default root
`build/flex/sim/levels-v1`), skipping steps whose outputs exist: baseline and
exploring-teacher scores (`levels/score.sh`), the 640 teacher games
(`levels/collect.sh ROOT data 910000`, 8 shards of 16), the level-mix students,
the student-driven games (`levels/collect.sh ROOT dagger 960000`, 4 shards of
32, driven by `mix-s2`), and the round 1 students. It ends by writing
`ROOT/manifest.json` with the SHA-256 of every dataset and model;
`levels/manifest.json` holds the original run's values. In the root,
`data-L0`…`data-L4` and `dagger-L0`…`dagger-L4` hold the shards (each with a
merged `data/data.bin`), `data-mix` and `data-agg1` the training sets, `mix-s*`
and `agg1-s*` the models and `eval-L1`…`eval-L4` and `eval` every game's
result. The run takes about 2.5 hours and 70 GB, 29 GB of which are the
training-set copies inside each model directory.

The later experiments each have a script in `levels/runs` (numbered as in
[diary](../../../diary/README.md), one dated file per experiment and its verdict), using
the tools beside them: `rl.sh` and `awr.py` (RL), `keep.py` (self-imitation
shards), `probe.py` (memory probes), `soup.py` (weight averaging),
`l5split.py` and `l5cross.py` (doorway drill by brick room), `confusion.py`
(teacher labels against the student's actions in student-driven games),
`pingpong.py` (rocking in place, for games recorded before `pingPongSteps`),
`backforth.py` (slower back and forth too, for games recorded before
`backForthSteps`), `mask-stuck.py` (unlabel the teacher's back and forth
in aggregated training data) and `heat-labels.py` (brick image positions from
the teacher's detections, for `control train --target-heatmap`).


Hiding the carrying bit does not hurt the student: +0.31 ± 0.19, paired over 32
games. The student keeps track of the leg itself, because the brick vanishes at
the reach, so this game does not need the bit.

## Speed

Round 4 took 90 minutes: collection 31, two trainings of 20, two evaluations of
10. Profiling the simulator showed visual odometry (5.8 s of a 15.7 s game),
contacts (2.5 s), brick detection (1.5 s) and drive (1.1 s) dominating;
rendering was 0.7 s. Video encoding, traces and sensor PNGs cost a further 35%.

| Stage | Before | After |
|---|---:|---:|
| Collect 256 games | 31 min, 22 GB | 7.5 min, 3.8 GB |
| Evaluate 32 games | 10 min | 64 s |
| Train 30 epochs on 256 games | 20 min | 1.2 min |

Lean evaluation reproduces the recorded per-game scores of `train-d4` and of
the teacher exactly.

Training runs at about 30 GFLOP/s (about 16 MFLOP per training frame, 1,800
frames/s), well under 1% of the RTX 2070's peak; it is launch-bound with
batch 2 and 300-step recurrent sequences. Larger batches are limited by the Pup
runtime's 16,777,216-element tensor cap: a batch's image tensor holds 21,168
values per frame, so about 790 frames fit.

Training was then profiled kernel by kernel with CUDA events. One batch took
about 363 ms, mostly convolution weight and bias reductions running in a few
thousand threads (157 ms) and 23,000 tiny per-step recurrent kernels. Splitting
the reductions, fusing the recurrence into one kernel per pass, batching the
input projection and heads, and unrolling dot products brought a batch to about
47 ms and an epoch from 36 s to 6.9 s (see `flex/control/README.md`).
Retraining round 5 (768 games, 12 epochs) took 278 s instead of 1,300 s and
scored 11.3 bricks per minute (32/32 games, validation loss 0.41), +0.34 ± 0.71
over the slower run. Saving gates in the forward scan, register-resident scans,
channel-blocked convolution kernels, direct elementwise indexing, transposed
matrix gradients and host prefetching then brought a batch to about 15 ms of GPU
time and an epoch to 2.4 s; the same retraining took 110 s and scored 10.1
(32/32, validation loss 0.45). The three retrainings differ only in rounding
(first-step gradients agree to about 1e-6) and scored 10.9, 11.3 and 10.1, so a
single retraining varies by roughly ±0.6 bricks per minute. Before
those changes, epoch time fit about 226 µs per frame (convolution forward and backward) plus
about 470 µs per recurrent step (sequential over the 300-step unroll), roughly
half each for 256 games. The GPU reports 87% busy at about 100 W, so the kernels
are slow rather than idle: one thread per output, 64-bit index arithmetic, no
shared-memory tiling, and weight-gradient reductions that loop over the whole
batch in a few thousand threads. Training on 100-step windows with batch 7 cut an
epoch from 35 s to 23 s, but without burn-in the windows start with empty memory
and validation loss rose from 0.78 to 1.09.

## AMD RX 9070 (29 Oct 2026)

The kernels are also built for the direct RDNA backend (`--target
rdna-gfx1201`, `.hip` files). That encoder has no correctly rounded FP32
divide or square root, so the build stages copies of the kernels:
`flex/ml/kernels/rdna-exact.flex` corrects an SFU estimate with integer
arithmetic (identical to the f64 reference on 4 million random divides and
square roots, including subnormal results). `flex/compiler/rdna.patch` adds
the encoder's 32-bit shared-memory loads and stores. One recurrent weight per
register needs more than RDNA's 256 VGPRs, so the RDNA register-resident
recurrences (`recurrence-registers-rdna.flex`,
`recurrence-registers-backward-rdna.flex`) keep two per 64-bit local.

| Check on the RX 9070 | Result | CUDA (RTX 2070) |
|---|---:|---:|
| Gradient tests (dense and categorical) | pass | pass |
| Fetch student `fetch-t1-s2`, deliveries per minute | 3.875 | 3.875 |
| Chase student `train-d5-agg`, bricks per minute | 10.91 | 10.94 |
| Retraining `fetch-t1-s2` (seed 9), deliveries per minute | 4.00 | 3.875 |
| 30 fetch epochs on 256 games | 1.7 min | 1.45 min |

Inference is not bit-identical across vendors: the sigmoid uses each GPU's
approximate exp2 and reciprocal, so 10 of 32 fetch games diverge at some
step (none before step 16), with the same mean. The retrained model differs by
+0.12 ± 0.31 deliveries per minute, paired over 32 games. Epoch 0 losses agree
to seven digits.

A training step first took about 170 ms of GPU time instead of about 15 ms,
an epoch 24 s. The encoder has no integer/float conversion, so the generic
index quotient emulated them in f64 software; the RDNA build now builds the
FP32 estimate from integer bits for indices below 2^24 (the quotient's own
bound) and keeps the exact integer correction. The encoder also copies every
operand through scratch registers and waits for each load at its first use, so
the remaining changes cut loads and index arithmetic per multiply-add:
dot products step pointers instead of multiplying 64-bit indices; loads issue
together before their first use; the register-resident recurrences return;
the elementwise backward skips the broadcast walk for same-shaped operands;
and two RDNA-only training kernels share loads, `matmul-train` across two
adjacent columns (one 64-bit weight load) and `convolution-pairs` across two
consecutive frames. A step now takes about 24 ms and an epoch 3.4 s, against
2.9 s on the RTX 2070:

| Kernel (one batch, 300 steps) | Before | After |
|---|---:|---:|
| Recurrence forward | 31.8 ms | 2.5 ms |
| Recurrence backward | 39.4 ms | 3.7 ms |
| Convolutions forward | 14.5 ms | 3.7 ms |
| Input projection forward | 2.9 ms | 0.6 ms |
| Elementwise backward (ReLU) | 42 ms | 0.8 ms |
| Whole step | 175 ms | 24 ms |

Every change keeps each sum's order. Retraining `fetch-t1-s2` for 30 epochs
reproduces the first AMD retraining's weights hash exactly; the gradient,
convolution and augmentation tests give their earlier results, the paired
convolution matches the unpaired one byte for byte on odd and even frame
counts, and the 32 fetch games give byte-identical outputs. The convolution
gradients (about 7.5 ms) are most of what remains.

Playing chase, the fetch student scores 8.75 bricks per minute, 2.16 ± 0.73
below the chase student it started from (paired). It goes within 0.7 m of the
box between bricks in 18% of chase legs, against 9% for the chase student, so
fetch training partly overwrites chase.
