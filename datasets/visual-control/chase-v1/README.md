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
SHARD_DATA...` combines up to 32 shard files from several rounds (fitting games
first, then validation games); with window 300 and burn-in 0, training on it is
byte-identical to the older merged and packed file. Shorter windows split each
game, replaying `BURN` unsupervised frames before each later window. Both
scripts record lean games with wheel-only odometry; set `PUPPYBOT_CHASE_FULL=1`
for videos and traces. `evaluate.sh` splits its 32 games over
`PUPPYBOT_CHASE_PARTS` (8) processes without changing any game's seed or scene.

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
