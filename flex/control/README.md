# Native visual control

The entire visual-control workflow runs without Python: scene construction,
simulator/process control, camera resizing, demonstration recording, dataset
packing, CNN/GRU learning, checkpoint packaging, inference, evaluation and
independent recorded-run verification are Flexscript. Shell launchers compile
or execute native binaries. No NumPy, OpenCV, PyTorch, NPZ or `.pt` dependency
remains in this workflow.

```text
TCP RGB 640×480 → native area resize → RGB 84×84 → CNN ─┐
previous controls / wheel commands / steering / contact ┼→ GRU(128) → steering, speed
previous recurrent state ──────────────────────────────┘           each in [-1,1]
```

The actor has 323,410 parameters. Training adds a 129-value auxiliary phase
head, making 323,539 trained parameters. Every CNN, GRU and head receives
gradients through full episodes. The reserved seventh feedback value is always
zero: phase labels are supervision, never actor input. No map, pose or target
coordinates enter the policy. The forward camera stays fixed after startup.

An optional categorical actor keeps the same encoder, GRU and inputs and has
324,055 actor parameters (324,184 including the training phase head). It predicts
seven joint-action logits: forward or reverse with steering -0.6, 0 or +0.6,
and stop. Inference selects the largest logit and emits that complete normalized
steering/speed pair. It never averages different actions. This is an experiment
to compare against the default continuous actor using whole episodes.

## Build

```sh
./flex/control.sh build
./flex/control.sh --help
```

Set `FLEXSCRIPT_COMPILER` to a native compiler and `FLEXSCRIPT_ROOT` to a
dependency checkout with `libs/ml/pup/gpu.flex` when necessary. The build stages
the compiler patch locally, adapts shared renderer/physics imports and generates
factories and CUDA kernels directly from Flexscript. It does not change the
dependency checkout or invoke Python generators.

The shared simulator robot asset `build/flex/sim/puppybot.bin` must already
exist. Its URDF/glTF exporter is shared simulator asset tooling, outside this
workflow. The control build reuses that geometry and never calls its exporter.
No previously generated visual-control executable, factory, kernel or dataset
is required. CUDA and a working local display/renderer are needed; hidden
rendering still requires `WAYLAND_DISPLAY` or `DISPLAY`. FFmpeg records videos
and native libpng decodes sensor PNGs during verification.

After building, `flexscript run control.flex ...` or
`build/flex/control/control` accepts the same arguments.

## Collect and train

Use new output directories whose parents exist:

```sh
./flex/control.sh collect --output build/flex/sim/control-data \
  --episodes 64 --validation 8 --seed 101000 --horizon 300 --curriculum mixed

./flex/control.sh verify-data --run build/flex/sim/control-data \
  --data build/flex/sim/control-data/data.bin --output build/flex/sim/control-data-verified

./flex/control.sh pack-data --data build/flex/sim/control-data/data.bin \
  --output build/flex/sim/control-data-packed

./flex/control.sh train --data build/flex/sim/control-data-packed/data.bin \
  --output build/flex/sim/control-policy --epochs 80 --batch 2 \
  --learning-rate-micros 700 --seed 7 --from-scratch
```

`train --mirror-augment` randomly reflects complete fitting histories. Every
camera frame in one history receives the same horizontal flip; steering
targets, previous steering and steering-servo feedback change sign, and left
and right wheel feedback swap. Speed, contact, phase and supervision masks
keep their original meaning. Burn-in observations receive the same transform;
padding stays zero. The source dataset and its native audit receipts remain
valid for the original recordings. A separate deterministic RNG chooses the
reflections without changing episode shuffling. Validation and deployed policy
inputs use the original sensor view. The policy receipt records this option.
Native tests compare GPU pixels with an independent CPU scatter, then compare
actual optimizer gradients and weights against an explicitly mirrored dataset.

A training-only oracle may use the complete reference floorplan, brick/box
coordinates and physical robot pose. It searches a 10 cm grid with obstacles
inflated by 24 cm, follows the route with bounded steering/speed, then reverses
its executed trajectory after approaching a real RGB brick detection. The native physical
collision guards still apply. The oracle cannot consume a brick or declare
success using coordinates alone: consumption requires a fresh camera detection,
its bounds to match the physical brick's projected center within 12 pixels,
and a planar robot-base-to-brick-centre distance of at most 35 cm. This
simulation-only association does not add a coordinate input to the actor. The
correction teacher aims 24 cm from the brick, leaving room for the planner's
10 cm arrival tolerance inside the acceptance radius. Fresh box views in the
stopped return pose finish the task. There is no grasp,
carrying or release. Each episode retains the privileged plan in `oracle.json`.

Local process streams time out after 45 seconds by default. Slow teacher
planning can opt into a longer bounded timeout with
`PUPPYBOT_LOCAL_STREAM_TIMEOUT_MS`, from 45000 to 600000 milliseconds; this
changes the wait limit, not the planner or the robot inputs.

The correction teacher tries another oriented approach after a blocked command
or an arrived search pose without a real detection. Its return goals are
50 cm from the box; an arrived pose gets up to six stationary observations for
fresh marker stability and return acceptance. `correct --return-via-home`
first routes via a waypoint 40 cm behind the original spawn, allowing a wider
approach to the box when a direct return gets trapped near a corner. The
intervention receipt records this teacher option. These remain ordinary
physical-oracle queries with the same collision guards and recorded labels;
they never force consumption or success.

`correct --approach-side 0..3` chooses the teacher's initial oriented standoff
around a brick. The receipt records it separately from student inputs.
`verify-data --audit-start N --audit-count K` checks only that episode range
without altering the data or its split. Its receipt reports the audited
`episodes`, `firstEpisode` and original `datasetEpisodes`; a subset receipt is
not evidence that the entire dataset passed.

The student receives only RGB and its existing seven own-feedback fields. Full
scene information and the route never enter that observation or dataset input.
Oracle steering/speed become supervised action labels; the training-only phase
label remains separate, and the reserved actor task-event input stays zero.

Collection defaults to alternating easy and two-room hidden-target scenes.
Easy-scene box sides use a separate RNG bit from the alternating difficulty,
so the curriculum includes both sides. Existing saved cases stay unchanged.
`--curriculum easy` or `--curriculum hidden` selects one difficulty;
`--hidden-target` also selects hidden scenes. Hidden targets vary by seed and
the box stays clear of the doorway approach. `--scene DIRECTORY` instead uses
an explicit `case.json`/`environment.bin`, with optional judge-only `layout.json`.
This small curriculum does not establish generalization to arbitrary houses.

Collection directly writes `PVDATA01` data with 300-frame padded episodes by
default (60 seconds of actions); `--horizon 1..512` changes the limit. The
first `episodes-validation` trajectories fit the model; the remainder validate
it. All attempts retain videos, sensor frames and physical/decision traces.
If an expert fails, collection fails and retains `data.partial.bin`; it does not
discard failed episodes or publish a complete dataset. Successful collection
atomically publishes `data.bin` and a SHA256 receipt.

`verify-data` independently decodes recorded sensor PNGs, checks every physical
action interval, and matches each dataset image/feedback row against its
pre-action observation and each action label against the executed command.
It also checks phase timing, masked padding, RGB consumption and physical return
acceptance. It runs entirely in Flexscript with native libpng. Failed audits
produce no success receipt.

The internal simulator bridge also supports opt-in `--oracle-labels` queries
for training interventions. The query uses full physical geometry and pose to
plan an oriented drive action, restores normal localization afterward, and
does not move the robot or advance physics. Actual execution still passes the
same motor/contact guards. The observation records oracle availability and a
query counter. Student runs disable this mode, and student replay rejects any
recording with privileged oracle access enabled. A successful teacher handoff
is never counted as an autonomous student success.

To teach recovery from states reached by the student, collect interventions:

```sh
./flex/control.sh correct --policy build/flex/sim/control-policy \
  --output build/flex/sim/control-corrections --episodes 16 --validation 4 \
  --rollin 30 --horizon 300 --seed 331000

./flex/control.sh verify-data --run build/flex/sim/control-corrections \
  --data build/flex/sim/control-corrections/data.bin \
  --output build/flex/sim/control-corrections-verified
```

Each episode starts with a seeded number of student actions from zero through
`--rollin`. Set `--rollin-min` to raise the lower bound when the student needs
practice recovering from later mistakes. The scheduled and actual handoff
lengths are recorded and audited. The full-geometry teacher then plans and executes recovery actions
until actual RGB detection and physical docking succeed. The frozen student
and per-episode handoff are recorded. `--scene-catalog DIRECTORY` uses numbered
scene directories `0`, `1`, and so on, with the final `--validation` scenes held
out of fitting. Keep these scenes separate from final evaluation cases.

Corrections use `PVDATA02`, which separates the valid-frame mask from the
supervision mask. Student actions stay in recurrent history but receive no
imitation or phase loss; expert actions receive both. Gradients from expert
steps still propagate through the earlier student images and feedback. If the
student finishes before handoff, its successful trajectory is supervised and
the receipt identifies this explicitly. The actor still receives the same
seven own-feedback values. Training also accepts existing `PVDATA01` datasets.

`train --phase-from-valid` supervises the training-only search/return auxiliary
head on every valid frame, including failed student burn-in. It keeps control
loss masked on those actions. Phase loss has its own valid-frame normalization;
padding and inactive batch slots contribute neither loss nor gradients. This
lets failed roll-ins teach whether a brick has actually been seen without
imitating their unsuccessful commands. The default uses only action-supervised
frames for both losses. The policy receipt records the choice; neither mode
adds phase or task-event input to the deployed actor.

For interventions, `verify-data` replays every student command from its frozen
policy and checks every expert command against the simulator's recorded oracle
label. It verifies both masks and all pre-action inputs. The dataset audit may
therefore load a student policy; ordinary teacher demonstrations need none.
Pack and warm-start training with `--initial-policy` as above. A completed
intervention remains teacher-assisted evidence; evaluate the resulting student
separately with `run`, where privileged queries are disabled.

For student roll-ins with `--label-rollin`, `correct --allow-incomplete`
can retain densely labeled prefixes that end at the horizon or when the oracle
cannot provide another action. It also permits a roll-in as long as the horizon,
so the student controls the whole recorded episode. With `--return-rollin`, the
teacher first searches and the student must execute at least one return action;
a return window truncated by the horizon can also be retained. `verify-data` requires its
own `--allow-incomplete` opt-in, checks every recorded label and student action,
and reports unsuccessful episodes separately. The audit does not independently
prove why the oracle became unavailable. The original recording horizon is kept
in the intervention receipt so a shorter prefix remains checkable after it is
padded into a longer dataset. These prefixes are training data, not successful
task episodes; default collection and verification remain strict.

`correct --label-rollin --coverage-teacher` selects an experimental search
teacher. In multi-room layouts it first considers a point in a forward room,
then sweeps deterministic waypoints; it may pursue a fresh
full-resolution camera detection; its search destinations do not use the
unseen brick position. The teacher's room bounds, true pose and collision-safe
oracle are privileged training information, and the planner can use physical
geometry that includes objects. None are actor inputs. The resulting
`teacher-search.jsonl` can be checked with
`datasets/visual-control/expanded-rooms-v1/audit-coverage-teacher-v2.sh`, in
addition to `verify-data`. This reconstructs search goals from the recorded
room bounds and camera observations and checks the recorded oracle labels; it
does not independently rerun the oracle planner. Teacher-assisted completion
is not a student success. With `--return-rollin`, the coverage teacher searches
first and the student takes control after consumption with its recurrent
history intact; the teacher may then recover if the student does not return.
The first experimental teacher version has a separate
`audit-coverage-teacher.sh` checker for its earlier room ordering. Its legacy
`actorInputsUnchanged` field is a declaration, not an independent input check;
use the separate `verify-data` receipt for actor-input and command replay.

Add `--label-rollin` to query the oracle at every student-visited state as well.
This writes `PVDATA03`: the supervision target and the actually executed action
are separate. Every real frame is supervised against the oracle's recommendation,
while the recurrent history and own feedback follow the student's actual drive.
The audit replays the student's executed commands and independently matches each
target to its recorded oracle query. Executed-command metadata never enters the
actor or substitutes for oracle targets during training. Querying still occurs
only during training; autonomous evaluation always disables it.

To inspect the balance of a `PVDATA03` dataset, run
`build/flex/control/summarize-demonstrations DATA`. It reports valid and
supervised frames, histories, action classes and oracle/executed action
disagreements separately for fitting and validation search/return phases.
Disagreements alone do not identify student-controlled actions; use the
intervention receipts for those windows.

`correct --label-rollin --return-rollin --rollin-min 90 --rollin 150`
starts the student window immediately after a real RGB/proximity consumption.
The teacher drives the approach, the student attempts the return for 90–150
actions, and the teacher then recovers and docks. The network processes every
teacher approach frame with its actual executed-command feedback, so its
memory at handoff includes the complete trip. All frames retain separate
oracle targets and executed commands in `PVDATA03`. A positive minimum window
and dense labels are required. Allow enough horizon for approach and recovery.

The intervention receipt records `studentStartAction` and
`studentBeginsAfterConsumption`. `verify-data` checks that handoff is exactly
the first post-consumption input, advances the frozen student's memory over
the complete teacher warm-up, and checks every command in the student window.
It also retains the RGB/proximity, docking, oracle-label and physical-motion
checks. Existing initial-prefix receipts remain supported. Teacher-assisted
return windows are training data; they do not count as autonomous completions.

Before emitting a training label, the teacher validates the first 20-tick
motion primitive with the physical execution guard at every physics tick and
one-millimetre swept intervals. Coarse lattice endpoints alone can miss a
collection-box corner between samples. Later search edges remain speculative;
the first executable edge is checked again on every oracle query. This check
applies to the privileged teacher, with the runtime collision guard preserved.
The label bridge also preserves a primitive's remaining ten ticks after its
first ten ticks were executed unchanged. It requires the matching physical
midpoint and goal, no contact, and a fresh swept check of the remaining path.
A different student command, changed goal, blocked movement or stale interval
causes a new plan. This avoids forward/reverse limit cycles caused by repeatedly
executing only half of a 20-tick lattice primitive. Student actions remain at
five hertz, and the continuation is available only to the training oracle.
The planned route also survives completion of a primitive. Each next primitive
gets a fresh swept check before its label is emitted; a newly blocked edge
triggers replanning. This prevents a fresh short-horizon plan from undoing a
completed escape and cycling near the collection box.

`pack-data` keeps every valid step and the complete recurrent history, but
removes padding after the longest real episode. It checks finite values, input
isolation, action bounds and contiguous masks before writing a new dataset and
source/output hashes. It never overwrites the source. `verify-data` accepts the
packed dataset against the same recordings. Packing reduces unrolled training
work without shortening any demonstration.

The native trainer owns batching, shuffling, full recurrent backpropagation,
weighted control MSE, phase BCE, gradient clipping, FP32 Adam, validation and
checkpoint selection. Best held-out demonstration loss selects `weights.bin`.
The initial checkpoint participates in selection, so a warm-start continuation
retains its starting weights if no epoch improves validation. `last.bin` and
periodic snapshots still contain the actual optimizer state even when the
selected `weights.bin` remains unchanged.
Control loss weights steering by eight and stopped targets by five. Targets
whose speed differs from the previous command by more than 0.2 receive another
factor of eight, emphasizing starts, search-to-return reversals and docking
stops. These weights use training labels and existing own feedback; they add no
actor input. The checkpoint receipt records the weights.
`train --stop-weight-one` is an experimental alternative that removes the
fivefold stopped-target multiplier while keeping the eightfold speed-transition
multiplier. It changes training only; compare complete episodes before deciding
whether it helps.
`train --focus-history INDEX --focus-copies COUNT` optionally repeats one
zero-based fitting history `COUNT` times per epoch. It randomly omits other
fitting histories to keep the number of optimizer updates unchanged; validation
histories are never resampled. This is an experimental training choice, not an
actor input, and can overfit a single trajectory.
`train --max-optimizer-steps COUNT` optionally caps optimizer updates for
comparisons with equal training budgets. A partially completed epoch is still
evaluated against the full validation split before checkpoint selection. The
epoch limit remains an independent upper bound.
`train --reversal-penalty-milli WEIGHT` is an experimental categorical-action
loss that discourages opposite drive directions on consecutive supervised
frames where the teacher commands the same nonzero direction in the same
phase. Teacher stops, reversals, phase changes and masked frames are excluded.
The weight is in thousandths. Validation and checkpoint selection use the
unmodified loss, and its effect must be measured in autonomous episodes.
Sequences retain memory for the full episode. Training accepts up to 512 frames
and at most 1,024 frames per batch (`batch * sequenceLength`); the default batch
is two. Legacy demonstration files may be up to 2 GiB, with at most 256
episodes. Dense merges that exceed either limit use `PVDATA04`, which supports
up to 1,024 episodes and 8 GiB. Training and `verify-data` support that format;
`pack-data` still accepts only the legacy size and episode limits. A padded
64-episode, 300-frame dataset uses about 407 MB before videos and traces. The
file is mapped on the host; GPU batch and sequence limits remain unchanged.

Categorical policies without auxiliary heads (no phase gate, event, pose,
target or heat supervision) train through a fused graph. The input projection
and the action and critic heads run once over all frames, and the recurrence is
one launch: a single thread block steps the GRU with a barrier per step and
saves each step's gates. With 128 units and at most two rows,
`recurrence-registers.ptx` keeps every thread's recurrent weights in registers;
otherwise `recurrence.ptx` reads them from memory. States match the unrolled
graph and exported inference exactly. The backward pass is one reverse scan
over the saved gates (`recurrence-registers-backward.ptx` or
`recurrence-backward.ptx`, kept apart from `gradients.ptx` because register use
limits block size), then batched recurrent weight and bias reductions. Other
configurations keep the per-step graph.

Training also selects `convolution-train.ptx` (eight output channels per work
item) and `binary-train.ptx` (direct indexing for same-shape, scalar and bias
operands); both keep the generic kernels' summation order and results.
Convolution input gradients are blocked over eight input channels. Weight
gradients sum fixed batch slices in eight-channel blocks, with enough slices
for about 200k work items, and then add the slices in a fixed order, so
gradients stay deterministic. Matrix input gradients read a transposed weight
copy. On the host, rows are validated once at startup, batch images are staged
in pinned memory, and the next batch is filled while the backward pass runs.

On the 324k-parameter chase policy (batch 2, 300 steps, 256 games) an epoch went
from 36 s to 2.4 s. Gradient, guard and forward-equality tests pass. Every
change except the slice counts left final weights byte-identical; slice counts
change only gradient rounding (about 1e-6 relative).
An experimental 128x128 path uses a separate `PVDAT128` format and inference
handshake. Its low-level trainer accepts files up to 8 GiB, and `run`/`verify`
accept `--image-128`. The 128x128 dataset converter and independent verifier
are in `datasets/visual-control/expanded-rooms-v1/`; they preserve the original
camera field and training-only labels. This path is under evaluation and does
not yet establish improved task performance.
An experimental `--large-model` option trains and runs the 84x84 categorical
heatmap actor with a 256-value GRU and about 3.06 million parameters, including
training-only heads. Use it with `train --categorical --target-heatmap DIR
--heat-actor`, and with `run`, `verify`, `correct`, or `verify-data` for the resulting checkpoint. Its
weights and inference handshake differ from the 128-value policy; the option
cannot be combined with `--image-128`. This architecture is under evaluation,
and its size alone does not establish better episode performance.
The large phase-gated heat actor with the training-only event head has
3,065,425 parameters in its checkpoint. The event head accounts for 257, so
3,065,168 parameters are used by the driving graph. The experimental
neutral-drive checkpoint additionally holds 3,840 drive-feedback weights at
zero; those weights are still included in the graph's parameter count. The
other 3,061,585 checkpoint parameters can receive training updates.
`train --memory-pose DIRECTORY` adds a training-only four-value readout of GRU
memory: initial-frame-relative forward/sideways displacement divided by eight
metres and sine/cosine of heading change. It applies mean squared error to valid
frames; the exported actor still takes RGB, own feedback and recurrent memory
only. The directory must contain `targets.bin` and a physical-verification
receipt bound by SHA256 to the exact demonstration data, roles and dimensions.
The trainer copies both into its output for reproducibility. Pose supervision
can accompany `--event-aux` and `--mirror-augment`, including with the
256-value large model; reflection flips sideways displacement and heading sine
for the whole sequence.

`build/flex/control/prepare-memory-pose DATA MERGED_RUN NEW_OUTPUT` creates
that sidecar from recorded simulator poses. It checks command intervals and
physical motion, matches each pre-action pose against the trace, checks executed
actions against the dataset, and records source hashes. It rejects trajectories
whose relative displacement exceeds the eight-metre normalization range. These
simulator poses are training labels only and do not enter the actor at inference.
`train --target-position DIRECTORY` adds a separate training-only readout of
the current CNN features. It learns normalized image coordinates on frames
marked by an offline visibility heuristic; ambiguous and other frames are
masked. The directory contains target data and a SHA256-bound receipt tied to
the exact dataset and split. The output copies those files for reproducibility.
The actor still uses only camera pixels, own feedback and recurrent memory;
no target coordinates enter inference. This supervision can accompany the
event and motion heads, and horizontal mirroring negates its x coordinate.
For a source dataset with no qualifying target candidates in one or both
splits, `prepare-targets --allow-empty-splits` can produce a masked sidecar for
those frames. It is accepted as a merge input only; standalone training and
the final merged sidecar still require candidates in both fitting and validation
splits. No target is invented for an unobserved frame.
`--target-heatmap DIRECTORY` is an alternative training-only head on the first
convolution's 20x20 feature map. For each candidate it supervises the nearest
cell and 16 separated negative cells; masked frames contribute no heatmap loss.
The coordinates use the same checked sidecar as `--target-position`, and the
two options are mutually exclusive. The heatmap is not an inference input or
an additional deployed output.
With `--heat-actor --target-heatmap DIRECTORY`, the learned 20x20 visual
features are also projected into the recurrent policy. The new projection is
zero-initialized when extending an existing policy, preserving its initial
behavior, and is trained together with the actor. The heatmap comes from the
camera itself at inference; target coordinates and simulator state remain
training-only. Continuing such a policy requires the same explicit options.
`verify-data` selects each recorded student's memory width from its receipt,
so it can audit collections containing both 128- and 256-value policies.
`--heat-stop-gradient` optionally blocks the driving loss from updating the
heatmap through this connection; the heatmap labels still train its head and
the driving loss still trains the policy and shared camera encoder. This is a
training choice and does not change inference.
`--heat-absence` additionally trains sampled heatmap cells as negative on
valid frames after the brick has disappeared. It excludes the first
consumption-labelled frame, because that camera image can still contain the
brick. This supervision uses the recorded phase only for training; the actor
still receives no event hint.
Test-episode outcomes do not select weights. Checkpoints use `PUPV0001` and
SHA256 receipts. Loss predictions and gradient seeds use separate host buffers
for each time step, batching transfers on the execution stream and waiting
before CPU reads or buffer reuse. Add `--initial-policy DIRECTORY` to warm-start;
Adam moments reset.
For a recorded one-brick episode, `build/flex/control/measure-brick-distance
EPISODE_DIR OUTPUT_DIR` reports the closest planar base-to-brick distance at
the recorded decision frames. It reads reference positions offline for scoring
only; it does not supply them to the actor. A distance within 35 cm alone is
not success: the simulator also requires a matched camera detection and the
subsequent docked return.
`init --output DIRECTORY --seed 7` creates a random policy without learning.
No converted or pretrained weights are required for scratch initialization.

Add `--categorical` to `train` or `init` to use the seven-action head. When
switching from a continuous checkpoint, the encoder, GRU and phase head load
their existing weights and the new action head initializes from the seed.
Categorical initialization and episode shuffling use separate seeded streams.
Warm-starting from a categorical checkpoint preserves its action codec.
Supervised targets must exactly match the seven oracle commands; unsupported
continuous targets are rejected instead of quantized. Weighted joint-action
cross entropy replaces control MSE, with the same stop and speed-transition
weights. The receipt records the codec, loss and action table. Collection,
camera inputs, memory reset and physical guards are shared by both actors.

`--phase-gated` uses separate seven-action search and return heads. A sigmoid
of the GRU's learned phase logit mixes their logits before action selection.
The phase comes from the same camera history and own feedback; the simulator's
phase label remains loss supervision only. No event flag is supplied at
inference. This model has 325,087 parameters, including the phase head now used
by the actor. When starting from a seven-action checkpoint, both heads clone
its action weights and bias, preserving the initial controller before learning.
Phase BCE and action cross entropy train the gate and heads together. Warm starts
preserve this architecture automatically.

The 84x84 large heatmap actor also supports `--phase-gated`. Its 256-value GRU
predicts the mixing gate internally from camera history and own feedback, and
its search and return heads start as copies of the original seven-action head.
The simulator phase is used only as a training label. This combination remains
experimental and requires autonomous evaluation.

`train --phase-consistency-milli WEIGHT` is an optional training-only loss for
a phase-gated policy. It penalizes changes in the predicted gate probability
between adjacent supervised frames with the same phase label. Masked frames and
the actual search-to-return boundary are excluded. The weight is expressed in
thousandths and defaults to zero; validation and checkpoint selection use the
ordinary losses. The label is never an inference input. This is an experiment:
a smoother gate could still switch too early or fail to switch at all, so it
must be evaluated on complete episodes.

`train --balanced-phase` is another experimental option for a phase-gated
policy. When a training batch contains both supervised search and return
frames, each phase contributes half of the phase BCE; a batch containing one
phase retains the original normalization. Masked frames contribute nothing.
Validation and checkpoint selection still use the original unbalanced loss,
and the simulator phase remains a training label, never an actor input. This
option changes the training objective; measured episode performance is needed
to determine whether it helps.

`train --return-weight-milli 2000` is a separate experimental option that
doubles the control-loss weight of supervised return-phase actions during
training. Search actions retain their existing weights, and the weighted
control loss is normalized over the batch. Validation uses the original
control loss; phase remains a training label rather than an actor input. This
does not imply improved returns without an episode benchmark.

`train --contact-weight-milli 2000` doubles the supervised action weight on
frames where the robot's existing drive-contact feedback is active. The weight
is normalized over the batch and applies only during training; validation
uses the ordinary loss. The option checks that contact feedback is binary and
does not add any inputs to the policy. Its effect on recovery and whole-episode
success must be measured separately.

`train --drop-drive-feedback-milli 250` randomly neutralizes the previous
commands and drive speeds for 25% of fitting sequences. The same mask is used
for every frame in a sequence; contact feedback is preserved. This is a
training-only robustness experiment, so masked inputs are hypothetical.
Validation and inference use the recorded feedback, and action-loss weights
still use the original feedback. The dataset and actor interface are unchanged.

`datasets/visual-control/expanded-rooms-v1/large-phase-probe.flex` replays an
audited large gated-policy trajectory and reads the gate from its saved weights
and replayed recurrent state. It checks every recorded action, rejects policies
without the gated architecture, and uses simulator phase only to label the
offline analysis. `analyze-large-phase-gate.sh` aggregates replayed episodes;
gate values above 0.5 indicate that the return head has the larger mixing
weight, not a discrete policy switch. These readouts diagnose behavior but do
not establish causal effects or whole-episode performance.

`datasets/visual-control/expanded-rooms-v1/large-phase-head-probe.flex`
reconstructs the search and return logits on the same replayed recurrent
states and reports the action that full return-head weight would select.
This is an offline counterfactual: it does not drive the simulator, and it
does not establish what would happen after the trajectory changes.

`datasets/visual-control/expanded-rooms-v1/large-feedback-probe.flex`
compares the recorded action with a hypothetical input that neutralizes the
five previous drive values while preserving contact and recurrent state. It
replays the unmodified input again to check that the policy server is stateless.
These hypothetical inputs are not used for driving or evaluation.

`summarize-search-interventions` checks the receipt for an independently
replayed initial student roll-in, then counts teacher/student action
disagreements separately for fitting and validation histories and for search
and return frames. The oracle commands and simulator phase are used only in
the offline report; they are not actor inputs. A large disagreement count
indicates candidate correction data, not improved autonomous performance.

`--event-aux` adds a training-only camera head before the GRU and own-feedback
join. It predicts the first RGB consumption frame from that frame's CNN
features. Targets come from the first pre-action return-labelled image in each
recorded history, with positive weight 50 and weighted BCE normalized separately
from the control loss. A masked current or preceding phase label excludes event
supervision, so unknown burn-in labels cannot affect it. The head adds 129
trainable parameters; inference still uses the same actor and 128-value memory.
Its label and prediction are never added to the robot's inputs. Warm starts
retain this auxiliary head automatically, and the receipt records its presence.
This is an experimental training objective; whole-episode autonomous results
determine whether it helps.

The reference oracle checks true physical collision geometry and excludes
contact memories expressed in estimated coordinates. Consecutive label queries
reuse a plan result only when the goal, true pose, arm/gripper configuration,
and complete collision geometry match byte for byte. Moving props, steering or
sub-cell pose changes invalidate reuse; an oversized key disables it. Each
request still receives a separately logged label and query number. For direct
simulator diagnostics, `--oracle-cache-check` recomputes every reused label and
requires it to match; this option requires the opt-in `--oracle-labels` bridge.
The oracle remains unavailable during autonomous student runs.

`train --checkpoint-every 10` retains `epoch-10.bin`, `epoch-20.bin`, and so on
in addition to the validation-loss-selected `weights.bin` and final `last.bin`.
These snapshots contain model weights, not resumable Adam state. Evaluate
complete autonomous episodes when choosing a policy: a lower imitation loss
does not establish better discovery or docking. Taking snapshots does not
change training order, gradients or optimizer updates.

## Evaluate and independently verify

```sh
./flex/control.sh run --policy build/flex/sim/control-policy \
  --output build/flex/sim/control-eval --episodes 8 --seed 110000

./flex/control.sh run --policy build/flex/sim/control-policy \
  --output build/flex/sim/control-blackout --episodes 8 --seed 110000 --blackout

./flex/control.sh run --policy build/flex/sim/control-policy \
  --output build/flex/sim/control-hidden --episodes 1 --seed 97001 --hidden-target

./flex/control.sh verify --run build/flex/sim/control-eval/110000 \
  --policy build/flex/sim/control-eval/policy \
  --output build/flex/sim/control-verified
```

Runs snapshot their policy executable, weights and kernels, reset memory per
episode, and retain physical collision/actuator guards. Each command advances
ten 20 ms ticks (5 Hz). There is no frontier planner, mapping worker or forced
scan. Blackout masks actor images only; task detection still reads real RGB.
Use matching seeds for paired normal/blackout comparisons.

`--scene DIRECTORY` accepts `case.json` and `environment.bin`; optional
`layout.json` supplies reference room bounds to the evaluation judge only.
The native hidden-target fixture has two rooms and a doorway. Hidden-target
success additionally requires leaving the starting room and at least 1.5 m of
search excursion.

Every episode now requires approaching the camera-detected brick within
35 cm before it can be consumed. The simulator uses physical positions for
this acceptance check; those positions are not actor inputs. The independent
recording audit recomputes this distance. Reports include
`maximumBrickDistanceM: 0.35`. Earlier sighting-only scores and demonstration
data use a weaker task: rerun evaluations and regenerate training data before
claiming results under this stricter rule.

The [approach35-v1 dataset recipe](../../datasets/visual-control/approach35-v1/README.md)
expands the strict task with 128 fresh histories and a layout-disjoint 96/32
fitting/validation split. Run its native collection script to generate scenes,
retain teacher and student-prefix recordings, and independently audit the
packed corpus. Large files stay in that dataset's Git-ignored `artifacts/`
directory. Collection does not start model training.

Results include `summary.json`, per-episode `result.json`, `mission.mp4`,
`outcome.png`, sensor PNGs, raw actor images/feedback, `initial.json`,
`decisions.jsonl` and physical tick traces. All failures/time limits remain in
the totals. Startup camera positioning and action time are reported separately.

Verification decodes sensor PNGs, checks RGB/actor hashes, reproduces native
area resizing and own-state feedback, compares camera calibration in body
coordinates, checks every physical movement increment and replays all recurrent
commands from empty memory. It checks fresh frames, fixed arm, bounded commands
and zero mapping/scans/grasps. Pass `--blackout` for a blackout replay.

## Chase game

`collect --chase` and `run --chase` play one-minute games in which the brick
reappears somewhere new after every reach, and some bricks jump once while the
robot is on its way. A memorised routine cannot score, so the game tests whether
the network drives to what it sees. Scenes come from `--scene-catalog`
directories (`0`, `1`, ... each holding `case.json` and `environment.bin`).

```sh
build/flex/control/control collect --chase --scene-catalog CATALOG --output DIR \
  --episodes 32 --validation 4 --horizon 300 [--policy STUDENT_DIR]
build/flex/control/control run --chase --scene-catalog CATALOG --output DIR \
  --episodes 16 --horizon 300 (--policy DIR [--blackout] | --chase-forward)
```

The simulator's agent command 5 restores the brick at a requested floor pose in
task 3. Reaching still requires a fresh camera detection within 35 cm. The
teacher outputs exact seven-class actions from the camera detection and its
odometry memory of the last sighting; it uses the floorplan only to back away
from walls, never the brick's coordinates. With `--policy`, collection lets that
policy drive while the teacher labels every step. Results report reaches per
minute, blocked steps and teacher disagreements; `chase.jsonl` logs every
placement. See `datasets/visual-control/chase-v1/` for the recipe and results.

`--lean` (collect and run) keeps only `decisions.jsonl`, `initial.json` and the
results: no video, trace, sensor PNGs, actor files or frame digests, which
`verify` and the viewer need. `--wheel-odometry` (chase only) starts the
simulator with `--no-visual-odometry`, skipping per-step visual feature
matching. Together they make a game about 2.4 times faster for one process, with
byte-identical training data and identical test scores in the chase game.

## Native tests and limits

```sh
build/flex/control/tests NEW_TEST_DIRECTORY
build/flex/control/gradient-tests build/flex/control/kernels NEW_GRADIENT_TEST_DIRECTORY
build/flex/control/policy-tests POLICY_DIRECTORY NEW_POLICY_TEST_DIRECTORY
build/flex/control/guard-tests build/flex/control/trainer build/flex/control/kernels NEW_GUARD_TEST_DIRECTORY
./flex/control.sh test
```

CPU contracts cover area integration, RGB/NCHW ordering, actor input isolation,
masked phase hints, blackout, policy packing, seeded scenes and file formats.
GPU tests independently perturb a high-gradient coordinate in every parameter
tensor: 16 for the continuous and seven-action models, 18 for the phase gate,
and 20 with the camera auxiliary. They compare central finite differences to
full CNN/GRU backpropagation and check Adam against independent scalar arithmetic.
No external autodiff framework supplies the oracle.
CPU oracle tests check collision-input invalidation, exact key comparisons,
episode reset, key overflow, reference-pose contact isolation and retention of
physical-world bounds. Cache-check mode is rejected outside the training bridge.
Forward tests compare the batched training graph with exported recurrent
inference across complete recorded histories, including hidden state. Raw
logits must respond to camera pixels, and resets must be bit-identical.
The data tests check that changing masked student labels leaves gradients and
optimizer updates unchanged, while changing student images changes later
supervised gradients. They independently reject tampered oracle targets and
executed-command metadata. The full test command collects, packs and audits both
ordinary demonstrations and student-to-teacher interventions, trains scratch
and warm-start policies, executes a short bounded episode and independently
verifies its recording. That is an integration smoke test, not a success-rate
benchmark for such a briefly trained policy.

Historical Python scripts and their numerical tests were removed. Pre-removal
source is preserved only in the local experiment archive
`build/flex/sim/control-no-python/legacy-source/`. Other repository utilities
are outside this visual-control migration.

Simple return success is not room exploration. Keep normal, blackout and hidden
tests separate, retain failures and judge actual travel and return pose. This
policy is not trained for pickup and has not been tested on the physical robot.
