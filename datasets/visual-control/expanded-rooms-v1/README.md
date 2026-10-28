# New fitting layouts and correction pilot

An initial-input audit of the later 292-history corpus found 11 exact RGB and
own-feedback inputs with conflicting supervised action classes within a split.
The 292 supervised first frames contain 143 distinct inputs. A deterministic
policy with zero initial recurrent state must misclassify at least 9 of the 209
fitting examples and 7 of the 83 validation examples under those labels.
This is a lower bound for the first-frame classification task, not an episode
success estimate or proof of the cause of the observed failures. The native
`summarize-initial-label-ambiguity.flex` audit compares actual input bytes and
records its source hash; its current result is under
`build/flex/sim/expanded-rooms-v1/large-model-v1/initial-label-ambiguity-v2/`.
The teacher navigates toward the privileged target before it is visible, so
training a search policy on those commands may require guessing unavailable
information. An exploration teacher that chooses search destinations without
using the unseen target should be evaluated against the current teacher.

The same exact-input audit now supports `--neutral-drive`, matching the five
zeroed drive-feedback fields used by the neutral-drive model while preserving
contact feedback. On the later 354-history corpus it found 205 distinct initial
inputs and 11 conflicting groups among 354 supervised initial frames; the
minimum errors remain 9 of 240 fitting and 7 of 114 validation examples, with
or without masking those fields. This is a first-frame bound, not an episode
success estimate. The audit does not alter the recordings or actor.
`summarize-prefix-label-ambiguity.flex` extends the audit to whole observation
histories, comparing every image and feedback byte at each node of a prefix
trie. For this corpus it found 324 conflicting prefixes, with minimum label
errors of 274 of 41,144 fitting frames and 113 of 20,747 validation frames.
Of those, 265 and 106 occur after the first frame. All such lower-bound errors
were in search, and neutralizing drive feedback did not change the counts.
These are exact repeated inputs in recorded histories; the lower bound neither
counts near-duplicates nor predicts autonomous episode success. The audit is
under `prefix-label-ambiguity-354-v3/` in the large-model build directory.

`audit-initial-conflict-scenes.sh` joins those groups to recorded source scenes
after checking the exact masked RGB and feedback bytes. All examples in each
of the 11 groups share the same recorded starting pose; 8 groups contain
different brick positions. All examples in 9 groups have no simulator detector
selection or detections. The simulator detector is a separate diagnostic and
its output does not establish what the neural policy sees. These associations
support testing an observation-consistent search teacher but do not prove why
the teacher commands differ or why autonomous episodes fail. The receipts are
under `initial-label-ambiguity-neutral-354-v1/` and
`initial-conflict-scenes-neutral-354-v1/` in the large-model build directory.
A further matched check, `audit-coverage-conflict-pilot.sh`, ties two retained
coverage-teacher trips to one of those conflicting input groups. Their actor
inputs and starts match, their brick placements differ, and the coverage
teacher labelled both initial inputs forward-straight. The corpus contains
forward-straight labels for both exact cases and a forward-left label for one
of them. The two teacher-assisted trips completed; this is not an autonomous
policy result. The check verifies the scene files, actor bytes, recorded label
and goal audits; the underlying goal audit still does not independently replay
the teacher. The pilot supplied a one-room layout while the corpus source supplied
a two-room layout, despite identical rendered environment and case bytes. This
changes privileged inputs to the teacher, so the two labels cannot establish
what that teacher would choose with the corpus layout. The strengthened check
is `initial-conflict-coverage-pilot-354-v2/`; it supersedes the earlier receipt
that did not check room-layout metadata.
`coverage-initial-query.flex` now queries the current coverage teacher in fresh
software-rendered native simulations, using each recording's original scene and
room layout. `check-coverage-initial-group.sh` requires the reproduced masked
actor input to match the recorded input byte-for-byte and records the teacher's
actual query response. Across the six fitting conflict groups with an empty
recorded simulator detector, the teacher produced the same forward-straight
label within each group: 33 histories, of which 25 already had that label and
8 had a different one. These are repeated initial observations, not independent
whole episodes. The teacher still uses privileged room bounds and collision
geometry; this result does not establish autonomous performance. Artifacts are
under `coverage-initial-fit-groups-354-v1/` and
`coverage-initial-group-354-v1/` in the large-model build directory.
`coverage-replay-query.flex` also replays the original commands from a recording,
checking every resulting RGB frame and feedback against both that recording and
the packed corpus before asking the coverage teacher for a label. A first
matched three-command prefix had opposing saved labels; the fresh teacher gave
both the same forward-straight label using a camera-derived goal. This is two
replays of one exact scene, not a policy improvement. Its receipt is in
`coverage-prefix-group-4-354-v1/`. Altered-pixel and altered-command preflights
were rejected; the query uses privileged teacher geometry only for labels.

The experimental coverage-and-camera teacher was checked on two placements
in that same room. With one student action and the remainder teacher-controlled,
both trips reached the brick and returned in 269 and 264 actions. The trips
passed student-action replay, physical recording checks and independent
reconstruction of all search destinations from room bounds or recorded camera
detections. The planner still has privileged collision geometry and true pose;
the goal audit does not rerun it independently. These two placements are not
independent room layouts, and the result is teacher-assisted, not a learned
policy benchmark. Artifacts are under
`build/flex/sim/expanded-rooms-v1/large-model-v1/coverage-teacher-pilot-v1/`.

In the 292-history policy's brick-finding development episode, the learned
return gate averaged 0.30 over the 32 remaining post-consumption actions and
never exceeded 0.5. The gate is a continuous logit mixture, not a calibrated
binary switch. An exact-prefix 600-action replay still did not return. These
are observations from one case, not proof of causation; the replay artifacts
are under `student-only-return-phase-v1/` and `long-return-diagnostic-v1/`
in the large-model build directory. A separately queued balanced-phase-loss
comparison retains the same actor inputs and original validation loss.

On four matched teacher-assisted development scenes, the original coverage
teacher returned in both open rooms and neither two-room layout. A revised
ordering that first considers a forward adjacent room returned in all four;
the two-room trips took 79 and 124 actions versus two 300-action failures.
Scenes, initial actor inputs and first student actions were checked identical,
and each recording passed replay and search-goal checks. This comparison uses
one target placement per layout and privileged teacher geometry; it does not
establish learned-policy performance. Results are in
`build/flex/sim/expanded-rooms-v1/large-model-v1/coverage-teacher-v2-pair-v1/`.

The original layouts 6/7 benchmark is not independent of checkpoint selection:
21 of its 32 exact cases appear in the prior demonstration validation histories,
including all eight screen cases. The new cohort adds six more of those cases
to demonstration validation. None are fitting histories, but validation loss
can influence selection, so prior episode scores are development results, not
clean generalization evidence. The audit and hashes are under
`build/flex/sim/expanded-rooms-v1/holdout-audit-v1/`. New layouts 18/19 have 32
cases and environments distinct from the prior corpus and this cohort. They
are for subsequent development comparisons; layouts 10/11 remain reserved final
tests. Once results are used for decisions, layouts 18/19 are development data.

This experiment generates six additional fitting layouts, IDs 12–17, with
96 seeded scenes. Layouts 10/11 remain reserved final tests; existing layout 7
is used only for validation in the two-episode pilot. The scenes extend the
same strict 35 cm find-and-return task and use the existing native scene format.

The pilot lets the epoch-1 gradient-separated student drive for up to 120
actions before privileged teacher recovery, with dense oracle labels on the
student's own observations. This checkpoint was selected after development
screens, so the pilot is exploratory. The actor still receives only RGB and
its own feedback; the teacher may use simulator geometry. Both trips must
physically complete and pass the unchanged native data audit, including image,
feedback, replay, motion, approach and return checks. Failure is retained;
pilot success is not autonomous student success or dataset admission.

The 30-trip collection and its repairs passed independent data audits. The
admitted 202-history corpus has 160 fitting and 42 validation histories and
retains all previous 172 histories. Candidate camera labels were regenerated
with independent projection and pixel checks; a separate native check confirmed
every old label sequence is byte-identical at its new index. The new sidecar
contains 4,309 fitting and 1,151 validation candidate frames; these remain a
visibility heuristic rather than proven segmentation. The data
SHA256 is `ad8bf0288486b26d67b89a6baa8908e275386cbe0deaea053a605ba259038c34`.
Admission artifacts and per-worker audit receipts are under
`build/flex/sim/expanded-rooms-v1/admission-v3/`; the checked sidecar is in
`build/flex/sim/expanded-rooms-v1/labels-v3/`.

The completed continuation comparison started both arms from the same fixed
student and used 2,720 optimizer steps per arm: 40 epochs on the original
136 fitting histories and 34 epochs on the expanded 160. The sets and shuffle
orders differ, so this compares the dataset additions at matched update count,
not identical examples. Each arm selected its checkpoint by demonstration
validation loss and was measured on the same 32 layout-18/19 episodes.
Those layouts become development data once their results inform decisions;
the independent layout-10/11 final gate is still required.

All 64 episode audits passed. The original-data arm approached 2/32 bricks,
the expanded-data arm approached 0/32, and both returned 0/32. In the 16
two-room episodes, both models stopped for all 4,800 actions; those episodes
share a starting camera view and one room layout rather than representing
16 independent layouts. Neither candidate qualified for the additional
four-layout check, and the reserved final rooms were not run. See
[`matched-comparison-results.json`](matched-comparison-results.json).

`bash datasets/visual-control/expanded-rooms-v1/summarize-episode-benchmark.sh
BENCHMARK_DIR NEW_OUTPUT_DIR` summarizes a completed, audited 32-case
benchmark by open and hidden layout. It reports approach and return rates,
time to approach after camera positioning, and whole-episode time for
successful returns. It checks outcomes against recorded simulation ticks and
retains input hashes. These find-and-return episodes do not include pickup.

`diagnose-long-return-cohort.sh` can replay the five cases that approached a
brick in the student-only development benchmark with a 600-action limit. It
checks that the first 300 actions and actor inputs match the original run.
Those cases were selected after observing the results, so the extended runs
are diagnostic and do not change the standard 300-action score.

The corrected-simulator baseline and epoch-1 student each completed all 32
layout-18/19 recordings with all audits passing. Neither approached a brick
or returned. Across 9,600 actions each, both stopped 7,192 times; all 4,800
actions in the hidden-room layout were stops. The student travelled 4.50 m
per episode on average versus 2.14 m for the baseline, but its average maximum
excursion was 0.61 m versus 0.91 m. Thus more travel did not establish better
exploration. Detailed rows and recordings are under
`build/flex/sim/expanded-rooms-v1/unseen-benchmark-v2/`; motion diagnostics
are in the adjacent `baseline-motion-diagnostic-v2/` and
`student-motion-diagnostic-v1/` directories. Compact results are in
[`unseen-results.json`](unseen-results.json). All 16 hidden cases share the
same initial RGB frame, so they are variations of one layout and starting view,
not 16 independent layouts.

One original fitting trip reached the 35 cm range but triggered on a color
component whose bounds missed the brick's projected center, so its independent
audit rejected it. The simulator now checks the association before removing a
prop. On the same scene and seed, a corrected run retained the first 120
student frames and actions exactly, skipped that detection, and consumed the
brick on the next action; both corrected pilot trips passed physical and replay
audits. The pilot wrapper's integrity check ran from the wrong directory and
exited nonzero; a separate acceptance check reran its integrity, scene, prefix
and physical-audit checks, preserving the original failed status. A same-scene
five-history repair has also passed its full audit. Two other histories from a
worker that exceeded the original stream timeout needed the same scene-preserving
repair; its five selected histories subsequently passed a full audit as well.
The corrected benchmark
uses the revised simulator for both policies, so its results should not be
compared as if the simulator were unchanged from older recordings.

An action survey of the original 172-history corpus found 10,250 supervised
search-phase fitting frames and no stop targets in that phase. All 419 stop
targets occur in return. Under the existing stop/transition loss multipliers,
those 419 frames account for 6,855 of 55,297 fitting action-weight units.
The survey calls the same weighting function as the trainer and is a diagnostic, not
evidence that a loss weight causes the policy's stopped behavior. Early
layout-18 baseline recordings show repeated stopping or reversing even before
seeing a brick; compare complete, audited suites before drawing conclusions.

On four audited search-only recordings, a read-only replay of the GRU phase
head predicted return above 0.5 for most frames. For the hidden-room baseline
and student samples, that threshold was crossed on actions 1 and 2 respectively,
while both issued stop for all 300 actions. The replay reproduced every command.
The phase readout does not control the actor directly, and its probabilities
are not calibrated; the result suggests a memory-state problem but does not
prove that the readout caused the stops. The reproducible probe is
`phase-diagnostic.sh` and its recordings remain under the build directory.

As a separate, raw-pixel diagnostic, the hidden-room starting image's nearest
search frame in the original fitting data has mean absolute RGB difference
0.051 and different own-feedback values. In the expanded fitting data, the
nearest search frame has difference 0.022 and identical own feedback; its
student stopped while the oracle labelled forward-right. This compares one
image and does not measure semantic similarity, recurrent state or task
performance. `nearest-rgb.flex` excludes validation frames and records the
source hashes and nearest examples.

An exploratory continuation on six selected fitting histories and two
validation histories was run after examining these development failures. On
the stalled hidden-room starting frame, its epoch-20 first command changed
from stop to forward-left; the similar fitting frame's teacher label was
forward-right. The epoch was fixed before an eight-case rollout. Both the
initial and fine-tuned policies had 0/8 approaches and 0/8 returns, with all
audits passing. The fine-tuned policy stopped less (824 versus 1,798 of 2,400
actions) but recorded more blocked-contact actions (742 versus 4); none of
the four hidden cases left the starting room. These small, adaptively selected
results are diagnostic and do not qualify a policy for promotion. See
[`correction-probe-results.json`](correction-probe-results.json) for the frame,
audit and episode summaries.

The next two audited teacher-recovery pilots used this exploratory policy for
120 and 150 actions respectively before teacher recovery. Across the two
120-action histories, 67 student decisions followed blocked contact: the
student repeated its previous command 65 times and the oracle reversed the
drive direction all 67 times. Neither 150-action history encountered a
blocked-contact decision. These counts characterize training examples, not
autonomous success. In one additional audited 300-command recording,
`contact-intervention.flex` replayed the recorded state and switched off only
the contact feedback for every tenth contact frame. One of 19 sampled actions
changed, although all 19 sets of action logits changed. This is a one-step
intervention on a single history, not a counterfactual episode.

The contact cohort fixes the exploratory policy and selects twelve
unused fitting cases across layouts 12–17 and four validation cases in two
new layouts 24/25. Its catalog checks case hashes against existing data and
both pilots, and checks cases and environments against the development and
generalization scenes. The validation environments also differ from existing
training and pilot environments. Layouts 10/11 remain reserved. Each worker
records student roll-in observations and privileged teacher labels, then
requires completed teacher trips and independent replay/data audits. A failed
worker retains its recordings; collection alone does not admit data or prove an
improvement. The selection recipe and worker diagnostic are
`catalog-contact-cohort.sh` and `diagnose-contact-cohort-worker.sh`.
The frozen first collection wrapper has a shell error-propagation weakness:
its worker status alone is insufficient to establish success. The separate
admission procedure rechecks every source data hash, full native audit, scene,
teacher completion and student checkpoint before merging. The source wrapper
has been corrected for future runs. A native byte-comparison check also verifies
that the 202 existing histories are unchanged by the merge; it passed on the
previous 172-to-202 expansion and rejected a deliberately altered history.
All 16 collection trips passed their full audits and were admitted alongside
the four audited pilot histories. The resulting corpus contains 222 histories
(174 fitting and 48 validation); its SHA256 is
`30a382877b404dcb7daa711a77e77afda2f794b8e2d3ee48bfd20157bccdbe66`.
Across the 16 cohort trips, 271 student decisions followed blocked contact,
with prior commands repeated 266 times and oracle drive direction reversed
271 times. These are correlated frames from seven trips, not independent tests.
An exact case-file identity check found 115 distinct fitting cases among the
174 fitting histories and 33 distinct validation cases among 48 validation
histories, with zero exact case hashes shared across the splits. Histories of
the same case may contain different trajectories. The validation split has
four distinct environment-file hashes, none shared with fitting. Different
files can still encode similar layouts; `analyze-case-identity.sh` reproduces
these exact-file checks.

The first four-trip worker passed its independent replay audit, including 480
exact student commands. Its fitting and validation trips respectively contain
102 and 26 post-contact decisions; the student repeated the blocked command and
the teacher labelled a reversal in each case. These 128 observations come from
only two trips and are not independent trials. The paired continuation is queued
after the existing comparison and the full collection audits: both arms start
from the same exploratory policy and use 1,920 versus 1,914 optimizer steps on
the 202- versus 222-history datasets. The training and validation sets and
shuffle orders differ. The initial checkpoint and both continuations will each
be evaluated on the same 32 development episodes; separate held-out rooms remain
necessary before promotion. See `train-contact-comparison.sh`.
`contact-weight-survey.flex` also found 1,607 supervised contact frames in
the earlier 160-history fitting split and 1,879 in the expanded 174-history
split. The oracle labels reverse the previous speed on 1,606 and 1,878 of those
frames respectively. Raw action weights are normalized per batch during
training, so aggregate weight counts are diagnostic rather than a causal measure.

An additional small exploratory continuation combined the previously selected
eight histories with the audited first 120-action pilot and first four-trip
worker. All 14 histories passed replay audit, including 1,645 exact student
commands; existing data and target labels were byte-preserved. The selected
checkpoint and its starting policy were then compared on the same eight
development episodes. All audits passed: the continuation approached 1/8
bricks compared with 0/8 for its starting policy, but both returned 0/8 and
neither left the starting room in the four two-room cases. The continued policy
stopped 228 versus 824 times and recorded 1,008 versus 742 blocked actions,
out of 2,400 commands per policy. This is an adaptive small screen, not a
generalization result. See `contact-quick-v1/comparison.json` under the build
directory and `diagnose-screen-pair.sh`.

In that screen's single brick-approach episode, the robot issued 241 more
actions without obtaining a valid box view or returning. Its closest recorded
robot-center distance to the box afterward was 1.04 m, calculated from
simulator positions only after the run; the policy did not receive those
positions. `diagnose-quick-return.sh` records this observation. A separate
two-case pilot uses the existing dense `--return-rollin` workflow: the teacher
approaches first, the student then attempts return with its full recurrent
history, and privileged oracle labels supervise the recorded observations.
Teacher-assisted trajectories are not autonomous whole-episode scores.
Both return pilot trips passed replay audit: each contained a 90-action student
return window, with 87 actions differing from the oracle's recommendation and
no valid box view. A 16-history continuation including these two trips passed
full audit, but validation selected its unchanged initial checkpoint; the same
eight-case screen repeated 1/8 approaches and 0/8 returns. Its final epoch is
screened separately after this selection outcome was known, so that screen is
post-hoc and cannot establish generalization. All eight audits passed; it
also approached 1/8 bricks and returned 0/8, with 1,256 blocked actions versus
1,008 for the starting policy. It did not leave the start room in any of the
four two-room cases. These results do not qualify either checkpoint for promotion.
The subsequent return cohort selects six new fitting cases in layouts 12–17
and six new validation cases in layouts 24/25. Each trip gives the student up
to 90 return actions after a teacher-driven approach, retaining the full image
and feedback history. A successful collection is followed by per-trip physical,
label and replay audits, a distinct-scene check, and a merge that preserves all
222 admitted histories. The queued 222-versus-236-history comparison starts
both arms from the same screened policy and uses 1,914 versus 1,911 optimizer
steps; training and validation sets differ. The initial policy and both
continuations must each complete the same 32 development episodes before the
separate held-out gates are considered. A teacher-assisted return window is not
an autonomous episode or a policy-promotion result.
All 12 return windows passed their audits. In one, the student completed the
return after a teacher-driven approach; the other 11 needed teacher recovery.
Across 1,050 student return actions, 793 differed from the teacher's label.
The successful student window lasted 60 actions and its commands replayed exactly.
This demonstrates a partial-task return on one case, not autonomous search,
approach and return. Its recording is under
`build/flex/sim/expanded-rooms-v1/return-cohort-v1/runs/4/expert-0/mission.mp4`.
The 12 cohort histories and two pilot histories were admitted into a
236-history corpus after the scene and replay checks, retaining every prior
history byte for byte. Its data SHA256 is
`74ed59242a4b7df9f9f5732458c23d743cf79f2e56a10b4394703845e9f1f833`.
There are 181 fitting histories with 122 distinct case-file hashes and 55
validation histories with 40 distinct case-file hashes; neither exact case
nor environment file hashes overlap between splits. The label preparation and
paired training comparison remain separate from dataset admission. Target-label
preparation passed its projection, split and byte-preservation checks, producing
4,785 fitting and 1,451 validation camera-target candidates. The 222-versus-236
paired training comparison is running; performance is not yet known.
Once both paired comparisons finish, `select-trained-candidates.sh` checks
all six starting and trained checkpoints against the same qualification gate.
`select-episode-candidate.sh` recomputes counts from the 32 per-case rows,
checks their seeds, layouts, policy hashes, individual replay receipts and
recorded final states, and
requires at least 24 returns with at least eight per room type. A qualifying
candidate still requires the four-layout and reserved-final evaluations. The
gate passed boundary fixtures and rejected inconsistent counts, wrong seeds and
altered episode rows, failed replay receipts and missing input-boundary fields;
`test-selection-gate.sh` reproduces these checks. The stronger
`trained-selection-v2` run supersedes the
earlier summary-only `trained-selection-v1` run.

Layouts 20–23 supply four additional non-fitting room geometries, with 16
preselected cases distinct from the prior corpus and layouts 18/19. A paired
check is queued only if a matched candidate meets the existing 32-case
qualification. Layouts 10/11 remain separately reserved final tests; they are
generated only after qualification and the four-layout audit. The final protocol
compares the selected policy, baseline and selected-policy camera blackout on
the same 16 cases. It requires at least 12 returns, including at least four in
each room type, and all episode audits to pass. It does not automatically
overwrite the retained policy.

The 236-history overlap audit now rechecks all training cases and environments
against the 16 four-layout cases, as well as the earlier development and
16-history exploratory cases. It excludes exact matching file hashes; it does
not rule out similar room geometries. `evaluate-qualified.sh` rechecks the
per-episode qualification evidence before running the four-layout comparison.
It generates the reserved scenes only after a candidate qualifies and every
four-layout episode passes its replay audit. A negative gate test and a
synthetic qualified-candidate walkthrough exercise the control flow without
generating real reserved scenes. The final report separately records whether
returns improved over the baseline or mean successful time decreased at the same return count and whether
blackout reduced returns; neither result causes automatic promotion.

For the larger 256-memory policies, `prepare-large-selection.sh` converts a
completed 32-case development benchmark to the same gate only after checking
each replay, scene, policy hash and recorded return. The generalized
`audit-generalization-corpus.sh OUTPUT CORPUS COVERAGE` checks the exact scene
hashes for an audited PVDATA04 corpus, including the 264-history dataset. It
still cannot exclude similar geometry. To use that audit in a qualified run,
provide `PUPPYBOT_QUALIFIED_CORPUS_DIR` and `PUPPYBOT_QUALIFIED_COVERAGE` and
include the audit as `corpus-audit.sh` in the frozen resources hash manifest.
The selected policy's dataset hash must match the audit. The frozen benchmark
scripts and control runtimes must also support `--large-model`; an incompatible
runtime fails before held-out episodes start. Synthetic tests cover this
qualification wiring without generating real reserved scenes.

Some earlier frozen scripts used a negated command with `set -e`, which did
not reliably stop on a duplicate hash. Do not reuse those frozen audit or
evaluation scripts: create a new resource snapshot from the corrected source.
The 280-history corpus was independently rechecked against development and
generalization scenes with the corrected audits. These checks compare exact
files and do not exclude geometrically similar rooms.

The 128x128 experiment uses the same camera field of view with a 12x12,
stride-six first convolution and resolution-specific heatmap label placement.
Its streamed data format supports up to 8 GiB, allowing the full 236 histories
to be prepared and independently rechecked. The queued 16-history experiment
is a development screen rather than a held-out comparison. A separate matched
236-history experiment reduces the stopped-target loss multiplier from five to
one while retaining the speed-transition multiplier; it starts from the same
weights and uses the same optimizer step count as the existing 236-history arm.
These experiments have not yet established improved episode performance.

`summarize-trajectory-diversity.sh BENCHMARK NEW_OUTPUT` checks an audited
32-case development benchmark for exact repetitions of the initial resized
actor image and feedback, followed by ordered actions and resulting actor
observations. It also counts initial poses and reports
room exits and travel. Exact repetitions are correlated evidence; different
hashes do not prove that two episodes are independent. These development cases
vary brick placement but reuse the initial pose within each layout, so their
episode count alone does not establish generalization across starting poses.
`summarize-blocked-feedback.sh PROBE EPISODE NEW_OUTPUT` summarizes the
offline neutral-drive-feedback probe on blocked search frames. Each contact
input comes from the observation preceding the recorded action; the first
action is excluded. These alternate actions are counterfactual predictions,
not a closed-loop simulation result.
`summarize-coverage-contact.sh` likewise pairs each student action and teacher
label with contact feedback from the preceding recorded observation. Earlier
summaries made from the post-action row overcounted or misclassified some
contact examples; this correction changes the analysis, not the dataset.

`train-longer-316.sh` compares ten epochs on the audited 316-history corpus
against its existing 98-update policy. It checks identical initial parameters,
sampling and first optimizer update, then evaluates the validation-selected
checkpoint on the same four development cases. `benchmark-longer-316.sh`
compares that checkpoint on the same 32 audited cases. The longer run may select
a different checkpoint by validation loss; neither screen proves performance on
new starting poses or automatically promotes the policy.

`generate-diverse.flex` supplies additional seeded rooms with varied bounds,
doorway, start pose, floor color and an obstacle. It reserves IDs 26–125 for
fitting, 126–179 and 188–217 for validation, 180–187 for development, and
218–225 for wide-heading development,
leaving the existing generalization and final layouts out of those ranges.
After `flex/control.sh build`, use `build/flex/control/diverse-generator OUTPUT
FIRST END fit`, `... validation`, `... development`, or `... wide-development
--wide-heading`; the end ID is exclusive. `--wide-heading` samples the initial
heading across approximately −180° to 180°; the default narrow-heading
generation remains byte-identical. Geometry and determinism tests
cover the physical simulator records, scene links and disjoint role ranges.
Two teacher episodes in one open room and two in one two-room layout passed
independent trace and camera audits; these repeated-scene smoke tests do not
establish generalization or learned-policy performance.

`prepare-diverse-development.sh` allocates layouts 180–187 to an eight-case
development screen, with four open layouts, four two-room layouts and eight
distinct starting poses. It checks case and environment file hashes against the
316-history corpus and existing development rooms; similar geometry remains
possible. These IDs are now development cases and must not be used as held-out
validation or fitting data in later experiments. The separate
`benchmark-diverse-development.sh` verifies the recorded initial pose, scene,
distance receipt and physical replay for each policy episode. It does not
automatically promote a policy or replace the reserved final evaluation.
`compare-longer-diverse-development.sh` pairs the 316-history baseline with
the longer-trained checkpoint on these same eight cases, while checking the
training comparison and scene identities.
For policies trained on another corpus, `audit-diverse-corpus.sh` first checks
the eight scenes against every case and environment file in that audited corpus.
The diverse benchmark requires the matching audit and rechecks its hashes.
`compare-reversal-diverse-development.sh` uses this for the 310-history
reversal-penalty experiment and its same-data baseline.

`prepare-coverage-scale-catalog.sh` prepares 32 additional layouts for teacher
data, with 16 fitting and 16 validation layouts; each split contains eight open
and eight two-room layouts. It checks generated geometry and exact scene-file
overlap against both current corpora and the development layouts.
`collect-coverage-scale.sh` records one student action followed by privileged
teacher control and independently checks the teacher goals and replay. Partial
teacher trips remain partial, and collection does not automatically add data
to the training corpus or establish autonomous success.
`admit-coverage-scale.sh` separately rechecks the collection, preserves the
existing 316 histories and target labels, and audits the 16 new histories in
each split before creating a 348-history corpus. `train-coverage-scale.sh`
compares 98 optimizer updates with the 316-history baseline and checks that
new fitting examples were sampled. The datasets, validation splits and
potentially the shuffled samples differ, which limits causal interpretation.
`benchmark-coverage-scale.sh` and `compare-scale-diverse-development.sh`
evaluate the resulting checkpoint on the 32-case and distinct-start development
sets; neither automatically promotes it or replaces final evaluation.

`prepare-wide-heading-development.sh` reserves eight additional rooms with
wide headings and checks their generated geometry and exact file disjointness.
`smoke-wide-heading-development.sh` separately tests actual simulator spawns,
camera frames and one-step replay. Passing that smoke test does not measure a
complete exploration or return episode. Set `PUPPYBOT_DIVERSE_SCENE_SET` to
`wide-heading` when running `benchmark-diverse-development.sh` to evaluate
complete episodes on these rooms. This is a development benchmark; the final
held-out layouts are still required for an independent evaluation.

An exploratory 348-history model used 32 additional teacher demonstrations
(27 complete and 5 partial) and 98 optimizer updates. On eight distinct-start
development rooms it approached the brick in 2 episodes, compared with 1 for
the 316-history baseline; neither returned to the box. On the eight separate
wide-heading rooms both policies approached the brick 0 times, returned 0
times and exited the start room in 1 of 4 two-room episodes. The training
datasets, shuffle orders and validation sets differed, so these small results
do not isolate the effect of the additional demonstrations. They are not a
final held-out evaluation. On a separate matched 32-case development check
using two layouts, both policies had 0 approaches and 0 returns.

`prepare-wide-student-catalog.sh` prepares four fitting and four validation
layouts with varied headings, checking geometry and exact file overlap with
the admitted corpus and development cases. `collect-wide-student-rollouts.sh`
then records up to 300 student-controlled actions per layout and training-only
oracle labels for those states. It audits the recorded inputs, commands,
starting poses and teacher search goals; incomplete trajectories remain
incomplete. `audit-wide-student-control.sh` separately checks that every
recorded action was controlled by the student. `admit-wide-student-rollouts.sh` checks and merges those histories
without changing existing data or targets. `train-wide-student.sh` and
`compare-wide-student.sh` provide an equal-update exploratory comparison on
the standard and wide-heading development sets. These steps do not promote a
model automatically or replace the independent final evaluation.

The eight student-driven wide-heading trips all ended without finding the
brick. After an equal-update retraining run used all four new fitting histories,
the candidate reached the brick in 0 of 8 standard varied-start development
episodes versus 2 for its 348-history baseline; both returned 0 times. On the
wide-heading development set both had 0 approaches, 0 returns and 1 of 4
two-room exits. Training order and validation composition differed, and these
development sets are too small to establish a general effect.

`admit-return-reuse.sh` separately adds two previously collected return
histories to the 348-history corpus. In those trips the teacher searched first,
the student controlled 60 return actions per trip, and the teacher then
recovered; the student did not complete either return window. The 350-history
dataset, `train-return-reuse.sh`, and `compare-return-reuse.sh` provide a
matched exploratory comparison. The source audit is checked against its
original frozen script after a source-path change; its goals are also
reconstructed again. These teacher-assisted trips do not establish autonomous
episode success.

The 350-history return-reuse model matched the 348-history baseline on the
same eight standard varied-start rooms: both approached in two and returned in
none. It exited the starting room in three of four two-room cases versus two
for the baseline. On the eight wide-heading rooms both had zero approaches and
returns and one two-room exit. The validation set and shuffle order differ;
the results do not isolate the added return data.

`prepare-wide-return-catalog.sh` prepares two fitting and two validation
rooms for additional teacher-search/student-return collection, including wide
starting headings. `collect-wide-return-cohort.sh` records paired trips: the
teacher searches, the student controls up to 60 return actions, and the teacher
may recover afterward. The simulator, student command replays, teacher goals
and physical starting poses are checked. Failed pairs retain their partial
recordings and are never automatically merged; a student return in this
curriculum is not a fully autonomous find-and-return episode.

The resulting 352-history candidate approached the brick in 0 of 8 standard
varied-start episodes versus 2 for its 350-history baseline; both returned 0
times. Both had 0 approaches and returns and one two-room exit on the eight
wide-heading episodes. The 354-history retained-window candidate subsequently
approached in 1 of 8 standard cases versus 0 for its immediate baseline, but
still returned 0 times; the earlier 348- and 350-history policies approached in
2 of those cases. These are small development sets, with different validation
sets and training orders, not isolated causal measurements.

The first wide-return worker reached the horizon during a student return.
`admit-incomplete-return.sh` admits a separately verified copy of that retained
pair, with the unsuccessful trip explicitly marked incomplete. It verifies the
original data and recorded commands, reconstructs the teacher's goals and
checks the merged fitting and validation histories. The original partial
recording is left intact. `train-incomplete-return.sh` and
`compare-incomplete-return.sh` compare its effect against the model trained on
the previously admitted return pair. The comparison remains exploratory.
On the eight wide-heading development cases, the retained-window model
approached in one case versus zero for its immediate baseline; both returned
zero times. The approach occurred late in the episode, with 55 recorded
post-detection decisions remaining. Initial camera images and own-feedback
inputs matched between the compared policies.

The drive-feedback ablation is an inference-only diagnostic of that model.
It zeros the five recurrent input rows for previous drive commands, wheel
speeds and steering, while preserving the camera, contact feedback and all
other weights. The GPU forward probe checks one frame against the parent model
with those inputs neutralized. `compare-drive-feedback-ablation.sh` compares
full episodes on the same development scenes; the ablation is not retraining
and does not automatically promote a model.

On the standard varied-start set, the inference-only ablation matched its
parent at one approach and zero returns; it exited all four two-room starts
versus three for the parent. In their shared approach case, it reversed less
often but spent more decisions blocked and stayed farther from the box. On
the wide-heading set it reached the brick zero times versus one for the parent;
neither returned. These are development results, not evidence that removing
feedback improves the full task.

`train-neutral-drive.sh` tests a separate retraining approach: its initial
checkpoint has those five rows zeroed and every training sequence masks those
inputs, while contact feedback remains available. It checks that the same
dataset, validation data, sample order, mirror mask and optimizer-update count
are used as the baseline and verifies the feedback rows remain zero. The
candidate was evaluated in closed loop: it approached in 3 of 8 standard
varied-start cases versus 1 for its baseline, with no returns for either.
On 8 wide-heading cases it approached in 0 versus 1 for the baseline, again
with no returns. It exited 4 versus 3 of the standard two-room starts, and 1
versus 1 of the wide-heading starts. The initial camera and feedback inputs
were independently matched. These small development sets do not establish
improved end-to-end performance.

In the 354-history dataset, 16,505 fitting frames supervise the return phase;
10,192 of those labels command reverse and 5,621 command forward. The mix
varies by source: the original approach data contains 1,761 reverse and 128
forward return labels, while return-recovery data contains 787 reverse and
2,329 forward labels. `summarize-demonstrations-by-episode.flex` provides the
per-history counts; grouping by the resolved recording paths is a data audit,
not an input to the policy. The differing strategies are a hypothesis about
training difficulty, not a proven cause of failure.

In the neutral-drive policy's three standard cases that reached a brick, the
recorded simulator box detector had no valid observation or fresh box attention
afterwards. In one case the policy drove forward for all 248 remaining
decisions; in the others it mixed forward and reverse. Retained marker counts
can be stale and are not evidence of current visibility. The simulator
detector is an evaluation diagnostic; these observations do not establish what
the actor recognized from its own pixels.

`build-forward-return-teacher.sh` builds isolated simulator snapshots for an
experiment that raises the oracle's reverse cost from 1.5 to 4 only during
return. Reverse remains possible, and neither the student nor the search
teacher uses the changed cost. Its oracle cache includes the task phase.
`compare-forward-return-teacher.sh` verifies matched search prefixes and replays
the one student action per teacher-assisted episode; it does not merge data.
On two wide-heading pilot scenes, both teachers found both bricks and completed
one return. The original produced 0 forward and 78 reverse return labels; the
modified teacher produced 108 forward and 4 reverse labels. The successful
original run took 25.3 simulated seconds versus 32.3 for the modified run.
This shows a different demonstration style, not improved student performance.
On two additional routes that had previously succeeded under teacher control,
both teachers again completed both returns. The modified teacher produced 136
forward and 8 reverse return labels versus 0 and 92 for the original. It took
26.7 and 34.9 simulated seconds versus 21.9 and 29.3 for the original. These
are reused training scenes and do not measure generalization. A separate
`summarize-return-box-visibility.sh` audit counts fresh simulator box-detector
observations and ignores stale marker counts; it cannot measure what the actor
recognized in its pixels.

`admit-forward-return-pilot.sh` assembles four of the modified teacher's
recordings into an experimental 358-history corpus. It keeps each reused scene
in its existing fitting or validation split, retains one timed-out run as
incomplete, checks the physical and student-action replays, and preserves the
prior data and targets. Its 242 fitting histories have 41,602 supervised
frames, and its 116 validation histories have 21,024 supervised frames. The
packed file is 2,689,760,000 bytes including padding; these are histories,
not 358 independent successful robot runs. Exact file hashing finds 280
different case files and 172 different environment files, with no exact case
or environment file shared between fitting and validation. Similar geometry
can still occur across files. `train-forward-return-pilot.sh` compares policies at
equal optimizer updates with the same initialization and seed, checking that
both added fitting histories are sampled. The training and validation sets and
their resulting shuffle order differ, so its comparison cannot isolate the
teacher change by itself. `compare-forward-return-pilot.sh` evaluates the two
policies on matching development scenes and checks their initial inputs.
In the initial four-case screen, both the baseline and the pilot-trained policy
had zero approaches and zero returns. Both new fitting histories were sampled;
the broader matched development comparisons are separate from that screen.
On eight standard varied-start development scenes, the pilot-trained policy
approached in one case versus zero for its seed-203 baseline; both returned
zero times and exited three of four two-room starts. Initial camera and own
feedback matched. The small sample and changed dataset, validation set and
shuffle order do not isolate a causal effect. On eight wide-heading scenes,
both policies had zero approaches, zero returns and one two-room exit.

`train-longer-neutral.sh` tests three complete passes over the same 354-history
fitting set used by the seed-203 neutral-drive baseline. It requires identical
initial parameters, the first sample order, feedback and mirror masks, gradients
and first optimizer update before comparing the validation-selected checkpoint.
`compare-longer-neutral.sh` checks matched development scenes and initial
camera and feedback inputs. More updates and validation checkpoint selection
are the intended differences; neither script promotes a model automatically.
On eight standard development scenes, the baseline and longer-trained policy
each had zero approaches and zero returns; they exited three and two of the
four two-room starts, respectively. On eight wider-heading cases, neither
approached or returned; each exited one of four two-room starts. These small
matched comparisons are not a final benchmark.

The pilot-trained policy's one standard brick approach was followed by 134
forward/reverse direction changes in 248 actions. Its closest physical distance
to the box after that transition was 2.22 m, and none of those actions was
blocked. This is one recorded episode, not a general failure rate.
`train-reversal-neutral.sh` tests the existing training-only reversal loss on
the same 358-history corpus and initialization; it first requires a combined GPU
check of the loss with masked drive feedback. `compare-reversal-neutral.sh`
compares complete episodes and checks their initial camera and feedback. The
loss preserves teacher-requested reversals and does not add a runtime heuristic.

`prepare-memory-pose-354.sh` prepares an auxiliary training target from the
recorded simulator trajectory, expressed relative to each episode's start.
It checks the physical trace, pre-action images and feedback and the inverse
transform. The preparer reports verified histories as it runs, and the 354-case
driver requires a preflight tied to the exact executable before beginning the
long pass. `train-neutral-pose.sh` tests that target with the neutral-drive
model; the position target is used only for training, and the actor does not
receive position or a map at inference. The added pose loss also changes the
validation objective, so it can change checkpoint selection. The matching
comparison scripts keep their results exploratory and do not promote a model.
The first 354-history preparation used an older frozen executable and was
rejected because its receipt lacked the newer image-alignment and inverse
checks. Its artifacts are retained for inspection; the corrected preparation
uses the separately preflighted executable. The resulting memory-supervised
policy and its same-data baseline each had zero approaches and zero returns
on the initial four-case screen. On eight standard varied-start scenes both
approached in the same three cases, returned zero times and exited all four
two-room starts; their initial camera and feedback matched. In those three
approach cases, the memory-supervised policy's closest recorded box distances
were 1.63, 1.70 and 1.83 m versus 1.44, 1.69 and 1.37 m for the baseline.
The trajectories differ and this small result does not isolate causation. The
additional pose loss also changes the checkpoint selection objective.
On eight wider-heading development scenes, neither approached or returned;
the pose-supervised policy exited two of four two-room starts, and its baseline
exited one.
`analyze-memory-pose.sh` replays audited autonomous episodes through the exact
policy and compares its training-only pose readout with physical pose labels.
It checks every recorded action, image and feedback before reporting position
error against a zero-displacement baseline. Reference poses are used only in
offline analysis; the result does not establish that pose estimates cause the
actor's actions. A synthetic test verifies alignment and rejects changed actions
and images. The real-episode replay is queued after the existing GPU experiments.

The current compact driving pose was measured at approximately 42 degrees
below the horizon, leaving an unobstructed flat-floor view of only about 2.1 m
at the top of the frame. Isolated arm-pose experiments are recorded separately;
changing camera pose changes the input distribution and requires fresh data and
whole-episode evaluation. `build-camera-pose-probe.sh` builds the simulated
kinematic survey without modifying the regular simulator. Its results do not
establish real-hardware reachability or collision clearance.

The first attempt failed before a trip because its copied runtime lacked the
simulator; the separate corrected `pilot-v2` used the audited route runtime.
Both teacher-recovery trips completed in 251 and 226 actions. The independent
audit passed 477 commands, 5,358 physical motion increments and 240 exact
student replays. On the new fitting layout, the student stopped for all 120
roll-in actions while the oracle chose forward-left throughout. The pilot
records are under `build/flex/sim/expanded-rooms-v1/pilot-v2/`; they are not
yet included in the admitted training dataset.
