# 46. Level-5 first-room diagnosis and L3/L5 DAgger plan

_3 Nov 2026; planned experiment, not yet run_

On entry 44's paired level-5 selection games, every initial brick starts on
the opposite side of a partition. `levels/l5-first-room.py` checks the first
search leg from recorded simulator positions. The `more1-s0` baseline enters
the target room in 19/32 games, picks up in 14 and delivers in 12. The
level-3 DAgger `student-s0` enters in 13/32 and picks up and delivers in all
13; in its other 19 games it neither enters nor comes within 1 m of the brick.
This supports prioritizing room entry and search over further pickup or return
tuning, for this selection set. These are virtual pickups, not physical grasps.

| Partition x / selection layout | Baseline room entries | L3 DAgger room entries |
|---|---:|---:|
| 1.6 m / 13 | 11/11 | 2/11 |
| 1.7 m / 15 | 4/11 | 1/11 |
| 1.8 m / 17 | 4/10 | 10/10 |

Layout is confounded with initial pose, heading and placement; this table
does not identify which caused the change. For context, in the existing noisy
L5 teacher-driven training games the teacher entered the target room in
111/128, first picked up in 97/128 and delivered in 74/128. That is not a
guarantee that its labels will recover student-visited states.

## Candidate training mix

`runs/34-level35-dagger.sh` stages a new isolated experiment: the current
`student-s0` drives 128 new level-5 games while the same exploring teacher
labels the visited states and records coverage maps. Continue each of the
three previous `student-s*` models for eight epochs on the following exact
1024-game mix:

| Source | Games |
|---|---:|
| Teacher levels 0, 1, 2, 3 | 96 each, 384 total |
| Teacher level 4 | 256 |
| Teacher level 5 | 128 |
| Previous L3 DAgger, driven by `more1-s0` | 128 |
| New L5 DAgger, driven by previous `student-s0` | 128 |

The aggregate orders 928 fitting and 96 validation games; exact source
scene/start identities are checked for cross-split overlap. Teacher-driven
back-and-forth labels are masked as before; student-driven teacher corrections
must remain intact. `audit-multi-shards.py` checks each driving policy's
frozen receipt, binary, kernels and weights, per-game level, source checksums,
counts and selection-seed separation. `audit-student-labels.py` checks
student-driven labels and disagreement counts; `audit-mixed-students.py`
compares every student image, original feedback/label row and coverage map to
the aggregate after masking. These checks do not validate teacher correctness
or establish old simulator binary or full model-ancestry identity.

The 1024-game cap requires removing 128 L0–L3 teacher games (32 per level)
relative to entry 44. That is a **confound**: a change cannot be attributed
solely to adding L5 DAgger data. The validation mix also changes from 920/104
to 928/96 fitting/validation games, and all new states come from only
`student-s0`. Selection against the previous students can show whether this
combination helps; a matched control arm is required to isolate the cause.

## Sequence and decision boundary

1. With the GPU idle, run `bash datasets/visual-control/chase-v1/levels/runs/34-level35-pilot.sh`.
   This collects two L5 games in a separate directory and checks their labels
   and preservation alongside 48 old games; it does not train a model.
2. Only after the pilot passes, run `PUPPYBOT_DAGGER_STAGE=collect bash
   datasets/visual-control/chase-v1/levels/runs/34-level35-dagger.sh`, then
   separately run the same command with `PUPPYBOT_DAGGER_STAGE=train`.
   Failed or partial outputs are retained and refused on retry until inspected.
3. After training, use `PUPPYBOT_PROJECT=$PWD LD_LIBRARY_PATH=$PWD/build/flex/rocm-runtime
   bash datasets/visual-control/chase-v1/levels/selection-pair-l35.sh LEVEL SEED`
   one pair at a time. Compare all three pairs on L5 and L3, and check L1 and
   L4 for regressions. Inspect first-room entry, first pickup, delivery and
   back-and-forth, not loss alone. L2 and standard-fetch checks are still
   required before promotion; this wrapper does not yet run those cases.
4. These are reused training-layout selection scenes. Freeze and audit a new
   genuinely independent held-out scene and seed set before any final test.
   The legacy level-4 test seed range overlaps old teacher collection seeds,
   even though its layouts differ. Never call these selection games held-out.

On this host before the run, `df` showed about 66 GiB available. The previous
equivalent 128-game collection occupied 1.88 GiB exclusive on Btrfs, its
1024-game aggregate 6.11 GiB, and each retained training model including its
copied data 6.08 GiB. Three models plus collection and aggregate could thus
consume roughly 26.2 GiB, before pilot, selection games and logs. The scripts
require 35 GiB free before each stage and 32 GiB before each model, retain all
partial files, and never delete old data. Concurrent disk growth or an
unexpected artifact size can still interrupt a run; recheck free space and
process state rather than assuming this estimate is current.

## Pilot

The two-game L5 pilot completed with seeds 5300000 and 5300001, each for 300
actions. The driving student delivered once in the first game and not in the
second; these two games are not a performance estimate. Teacher and student
actions differed on 101 and 200 steps. The 50-game mixed-source audit passed
with 45 fitting and 5 validation games; after teacher-only masking, the
preservation audit confirmed the images, original feedback and teacher-label
rows, and maps of all 34 student-driven games were unchanged. Teacher-only
masking unlabelled 228 teacher rows. The pilot's audit output and manifests
are under `levels-v2/pitch82/search-dagger-l35-pilot`.

## Full collection

The four-worker level-5 collection completed 128 games with no logged stream
timeouts. The mixed-source audit passed for 1,024 games: 768 teacher-driven,
128 level-3 student-driven and 128 level-5 student-driven. The separate label
audit passed on all 128 new games and counted 20,105 teacher/student action
disagreements; it checks saved-data consistency, not whether teacher actions
are correct. The post-aggregation audit confirmed preservation of all 256
student-driven games' images, feedback, labels and maps. Three eight-epoch
training runs completed; selection comparisons remain in progress. Outputs
are under `levels-v2/pitch82/search-dagger-l35-4workers`.

## First level-5 selection pair

`selection-pair-l35.sh 5 0` passed its paired audit on 32 reused
training-layout selection games. Against its starting L3-DAgger student, the
new candidate entered the brick's room in 32/32 games rather than 13/32,
and made a first pickup in 24/32 rather than 13/32. Games with a delivery
rose from 13/32 to 19/32, and deliveries/min from 0.406 to 0.656. However,
back-and-forth share rose from 0.68% to 6.84% (one mostly looping game),
and no delivery occurred in the 11 games with partition x=1.7. Layout and
initial placement are confounded, so the partition grouping is diagnostic
only. The result is below the reliability and loop targets and is neither a
held-out result nor evidence of physical grasp. The removed teacher games
also confound attribution to the added L5 data. Full pair artifacts are in
`search-dagger-l35-4workers/selection-L5`.

The first L4 regression pair showed a material doorway tradeoff: the mixed
candidate delivered 27/51 past-doorway bricks versus 33/51 for its starting
model. Both entered the brick's room in 40/51 cases, with median entry 81
versus 63 actions. Deliveries/min fell from 2.75 to 2.47 and back-and-forth
rose from 1.45% to 2.98%. These are training-layout selection games; do not
promote the model on its L5 gains alone. Artifacts are in `selection-L4`.

On this L4 pair, total deliveries fell 88→79; ten net deliveries were lost
within the x=1.7 group, while the other groups changed by +3 and −2. Two
initially same-room cases took 220–239 actions to first pickup for the mixed
student instead of 20–24. Another case had the same first delivery but fell
from six deliveries to one, so both first-fetch and repeat-fetch behavior
matter. These are repeated selection layouts and virtual task events; the
evidence does not identify which training change caused the regression.

The second L4 pair did not repeat the first pair's past-doorway delivery
regression: `student-s1` delivered 41/65 versus its starting model's 38/64.
Room entry was 53/65 versus 50/64, with median 73 versus 61 actions;
deliveries/min were 3.03 versus 3.09 and back-and-forth 2.92% versus 3.24%.
Neither result meets the proposed 80% doorway goal, and the two pairs have
different case counts because later brick spawns depend on the player's run.

The third L4 pair delivered 37/59 past-doorway bricks for the candidate
versus 23/48 for its starting model, with room entry 49/59 versus 40/48 and
median entry 34 versus 64 actions. Deliveries/min rose from 1.84 to 2.81;
back-and-forth fell from 3.13% to 2.07%. Case denominators differ as later
spawns depend on play. Across the three model pairs the doorway results are
mixed, and no pair establishes the held-out 80% target.

The first paired L3 regression check passed its audit. The mixed candidate
made a first pickup and delivered in 29/32 games versus 31/32 for its
starting L3-DAgger model; deliveries/min were 2.219 versus 2.344 and
back-and-forth share 1.57% versus 0%. This is a small selection-set
regression for one model, not a held-out estimate. Artifacts are in
`search-dagger-l35-4workers/selection-L3`.

The second L3 pair also declined on selection games: the candidate delivered
in 27/32 versus 29/32 games, with first pickups 28 versus 29 and deliveries
per minute 2.031 versus 2.219. Back-and-forth shares were 0.94% and 1.22%.
This is not independent held-out evidence, but it reinforces the need to
check retention when training on level-5 correction data.

The third L3 pair improved from 29/32 to 30/32 delivery games, with first
pickups 29 versus 30; delivery rates were 2.375 and 2.344 per minute.
Back-and-forth rose from 0.57% to 2.21%. Across the three candidate seeds,
L3 delivery-game counts changed 31→29, 29→27 and 29→30 on these reused
selection games, so the result is mixed and not a held-out assessment.

The third paired L5 comparison passed its audit: delivery games increased
from 11/32 to 18/32, first pickups from 20/32 to 22/32 and deliveries/min
from 0.375 to 0.656. Back-and-forth share rose from 0% to 1.57%. Across
the three candidate pairs, all selection delivery counts improved, but the
best reached 24/32; none met the 90% game-reliability target on these games.
Other levels, ordinary fetching and independent held-out tests remain open.

Trace inspection of the 11 partition-x=1.7 games gives a more specific
failure: the candidate entered the other room in all 11, but at decision
250 in ten games and 262 in one. It picked up five bricks at decisions
265–291, leaving 9–35 actions for return, and delivered none. Six had no
pickup. The 11 games share the same recorded action and pose prefix through
decision 222, so they are not independent layout replicates; this does not
prove that return control was the sole cause. A 27-action back-and-forth
segment at decisions 217–243 is shared by ten of the 11; the remaining game
diverges earlier. All 11 use one identical environment file. These are
simulator-truth diagnostics of virtual pickup, not physical grasp evidence.

The second paired L5 comparison also passed its audit: the candidate entered
the target room in 32/32, picked up in 25/32 and delivered in 24/32, versus
16 first pickups and 10 delivery games for its starting model. Rates were
0.906 versus 0.313 deliveries/min; back-and-forth share was 2.42% versus
3.17%. The candidate delivered in 5/11, 10/11 and 9/10 games in the x=1.6,
1.7 and 1.8 partition groups respectively; those groups confound environment
and starting view. This remains selection evidence, with fewer than 90% of
games delivered and loop share above 2%. Pair artifacts are in
`search-dagger-l35-4workers/selection-L5`.

An ordinary-fetch selection pair for model seed 1 passed its audit. The
mixed model delivered in 32/32 games versus 31/32 for its starting model,
at 5.25 versus 4.9375 deliveries/min. Back-and-forth was 2.10% versus
2.73%. The difference is on reused training-layout selection games and does
not establish held-out performance. Artifacts are in `selection-standard`.

The model-seed-1 L2 pair also passed its audit. Both models made a first
pickup and delivery in 32/32 games, at 5.219 versus 5.281 deliveries/min;
back-and-forth increased from 3.92% to 5.22% for the mixed model. This is a
selection comparison, not a held-out measurement. Artifacts are in
`selection-L2`.

The model-seed-1 L1 pair found a speed regression: the mixed model delivered
in 31/32 games versus 32/32 for its starting model, at 6.4375 versus 7.75
deliveries/min. Back-and-forth fell from 4.58% to 3.59%, but both shares
remain above 2%. This training-layout selection result is not a held-out
score and rules out promoting on L5 gains alone. Artifacts are in
`selection-L1`.
