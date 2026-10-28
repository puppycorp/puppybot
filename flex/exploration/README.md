# Neural exploration experiments

The navigation curriculum in `seek_train.py` and `seek_native.py` tests a
smaller complete task: explore without a supplied map, consume the first brick
seen in TCP RGB, then return and stop facing the freshly observed collection
box. There is no grasp, carry, release, or arm-reach requirement. The camera
still moves with the wrist to scan the room.

Launch the native task with the heuristic:

```sh
flexscript run sim.flex --case find-return-house
```

Train and run the small navigation network:

```sh
OPENBLAS_NUM_THREADS=1 python3 flex/exploration/seek_train.py \
  --output build/flex/sim/seek-training
PUPPYBOT_SEEK_POLICY=mlp \
PUPPYBOT_SEEK_WEIGHTS="$PWD/build/flex/sim/seek-training/checkpoint.npz" \
  flexscript run sim.flex --case find-return-house
```

`--teacher heuristic` bootstraps from heuristic navigation demonstrations;
`--teacher oracle` instead uses offline shortest paths through the reference
layout. Both use privileged geometry for safety labels during training only.
The actor is a **32 → 64 → 32 → 2** tanh MLP with 4,258 parameters, scoring
goal utility and risk. Inputs contain 24 partial-map features plus task phase,
remembered RGB box geometry and candidate standoff/orientation. It chooses
goals during both search and return. Persistent map/box memory, RGB detection,
stereo mapping, Hybrid A*, and collision guards are classical components; this
first curriculum has no recurrent network and no YOLO encoder.

Training uses generated rooms, idealized full-circle 1.3 m ray observations,
exact odometry and legal grid paths with endpoint orientation. It is supervised
imitation, not reinforcement learning or native RGB training. One hidden brick
is retained per training episode. Native scenes can contain several bricks;
only the first sighting counts, and only one object is consumed.

The native `rgb-find-return` controller uses actual TCP RGB. Its simulator-only
consumption hook matches an image detection to a physical prop, hides it, and
parks its inert collider below the world. That hook does not provide object
coordinates to navigation. Actor requests contain only RGB/calibration, robot
geometry, estimated pose, phase, and a box landmark measured from RGB. Return
success requires three stationary observations at **0.30–0.65 m** from the box,
facing it within **35°**, with stable current box detections. This is a coarse
navigation staging pose, not a claim that the gripper can release a payload.

Compare frozen policies on whole native episodes:

```sh
python3 flex/exploration/freeze.py --output build/flex/sim/seek-frozen \
  --synchronous-mapping
python3 flex/exploration/seek_native.py --frozen build/flex/sim/seek-frozen \
  --weights build/flex/sim/seek-training/checkpoint.npz \
  --output build/flex/sim/seek-comparison --seeds 96001 96002 --hidden-brick
```

The runner retains every success, failure and timeout, videos, source/checkpoint
hashes, and an independent audit of physical base increments, RGB consumption
pixels, zero grasps/releases, unsupplied maps, camera inputs and true final box
distance/orientation. `--audit-run DIRECTORY --frozen DIRECTORY` rechecks a
saved episode. Simulation action time excludes stationary mapping worker waits;
wall time includes rendering, mapping and inference.

The default `--hidden-brick` task is an actual search example; `--nearby-bricks`
opts into the older smoke test. It keeps one reachable brick in another room, at least 4.3 m
from the initial base pose. The extra exploration criterion requires leaving
the start room and a search excursion of at least 1.5 m, before returning.
The closer observer camera follows the robot and does not change its TCP
sensor images. Audits report search distance, maximum excursion, rooms visited,
and moving/stationary simulation time; path length alone can hide local loops.

The first curriculum artifacts are under `build/flex/sim/find-return-v1/`.
The oracle-label pilot (`training/`) completed only 3/20 idealized test layouts,
against 17/20 for the heuristic. The imitation run (`training-imitation/`)
trained on 48 layouts, selected on 8 separate layouts and completed 20/20 fresh
idealized test layouts, against 18/20 for the heuristic. These are small grid
results; the separately recorded native comparison determines RGB performance.

The final native comparison (`comparison-verified/`) completed 2/2 episodes
for each method, with success exit codes, zero grasps/releases and independent
audits of 32,060 motion increments and 176 mapping RGB frames. Mean simulated
completion was 161.38 seconds for the model and 159.26 for the heuristic: no
native speed advantage. These two scenes have nearby first sightings, so this
does not establish deep multi-room search. `report.md`, `verification.json` and
the 20-second `find-return-8x.mp4` retain the result and recording.

Reviewing the actual trajectory showed that those four episodes are only
visibility-and-return smoke tests: none left the start room. The linked learned
episode detected its brick after approximately 5 cm of driving, stayed within
60 cm of home and spent 153.54 of 162.06 simulation seconds stationary. Its
2/2 result must not be used as evidence that the network can explore rooms.

The unchanged checkpoint then failed the stricter seed-96001 pilot within its
240-second wall budget: 5.40 m path, 2.86 m maximum excursion, starting room
only, no brick found. Of 651.06 simulated seconds, 627.46 were stationary.
The trace, closer video and true-floorplan trajectory are retained under
`build/flex/sim/find-return-hidden-run-v1/`. This exposes the current explorer's
stop-and-scan cost and does not establish whether learned ranking or the shared
mapper/planner is responsible; no harder-scene heuristic run was measured.

These experiments train a small frontier-scoring network. Its inputs are the
robot's partial map, estimated pose, scan visits, and reachable candidate costs.
It changes candidate scores only. The RGB mapper, traversability masks, native
route planner, collision guards, and physics remain unchanged. The production
explorer continues to use its existing heuristic.

`bootstrap.py` is the first idealized 2D experiment. Its synthetic validation
improved, but six short native RGB trials did not demonstrate better exploration.
The retained assessment is under
`build/flex/sim/neural-exploration-n1v_6ig8/assessment.json`.

The second experiment uses actual recorded wrist-camera mapping inputs:

1. `freeze.py --output NEW_DIRECTORY` retains a private simulator, robot asset,
   mapper, policy hook, and source manifest. The hook never receives reference
   geometry or actual poses.
2. `native_data.py --workspace DIRECTORY/workspace --inputs INPUTS.json
   --output DIRECTORY/data` replays saved stereo pairs. It checks raw RGB against
   saved PNGs and byte-matches every observed/safe map before extracting examples.
   The input JSON lists `run`, `environment`, `scene`, `split`, and optional
   sampling `stride`. Scene identities must be disjoint across train/validation.
3. `native_train.py --data DIRECTORY/data --output DIRECTORY/training` trains
   three model seeds. Minibatches balance decision states. Model/heuristic mixing
   is selected by equal-scene validation regret, then saved in `runtime.json`.
4. Freeze the checkpoint and runtime configuration before native held-out tests.
   `native.py --artifacts DIRECTORY --seeds 71001 71002 --scans 8
   --steps 70000 --repeats 2` compares heuristic, gain, and learned policies.
   Alternate repeats reverse policy order. Every trial retains RGB, trace,
   actual-motion/camera audits, offline floorplan scores, and source hashes.

Use `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1` for reproducible CPU training and
`WAYLAND_DISPLAY`/`DISPLAY` from a working graphics session for native trials.
Camera simulations need rendering even when their windows are hidden.

The second dataset has real RGB-derived **actor inputs**. Its offline labels
still approximate future 360-degree visibility within 1.3 m, divide gain by
estimated route cost, and penalize unsafe endpoints using reference geometry.
They are not executed counterfactual actions or future camera images. Reference
geometry and actual poses enter only those labels and the external evaluator.

The completed second pilot is retained under
`build/flex/sim/neural-native-data-v2/assessment.json`. It used 25,315 training
examples from four layouts, two separate validation layouts, and three model
seeds trained for 120 epochs each. The selected model was tested against both
baselines on two unseen layouts, twice per policy, with eight scans per run.

| Policy | Mean correct free-floor coverage | Mean free-space precision |
| --- | ---: | ---: |
| Existing heuristic | 4.88% | 97.21% |
| Gain baseline | 4.57% | 96.63% |
| Native-data neural model | 4.31% | 97.02% |

All twelve native trials passed their motion, camera, source, and actor-input
audits. The neural model improved the first layout but underperformed on the
second. Its improved offline validation score did not establish better native
exploration. These are partial exploration episodes, without pickup or room
completion. `reproduce.sh NEW_DIRECTORY` in that artifact directory reruns the
frozen comparison without overwriting the original measurements.

Native trials, rather than training loss, determine whether a model helps.
Report scene-level results, repeats, actual travel, map precision, protective
stops, and incomplete episodes as well as coverage. A short successful trial
does not establish room completion, six-brick collection, hardware performance,
or generalization to other layout generators.

Focused checks:

```sh
OPENBLAS_NUM_THREADS=1 python3 flex/tests/sim-exploration-learning.py
OPENBLAS_NUM_THREADS=1 python3 flex/tests/sim-exploration-native.py
OPENBLAS_NUM_THREADS=1 python3 flex/tests/sim-exploration-native.py \
    --artifacts build/flex/sim/neural-native-data-v2
```

## YOLO visual-memory experiment

`prepare_encoder.py` builds an independent native Pup encoder from the pinned
YOLO26n checkpoint. It stops at `model.6` (128 channels, stride 16), omits the
detection head, and defaults to a 320-pixel letterboxed input. The existing
detector binary and production mapper are unchanged. The backbone is frozen.

The experiment defaults to CUDA and retains generic kernels with the encoder.
One native worker stays resident across an episode's mapping requests; model
startup and all inference still count in wall time. The initial 320-pixel
generic SASS path produced inconsistent features on some wrist images and is
excluded from the scored experiment. CUDA features must pass independent
ONNX/tinygrad checks, including repeated inputs after a different frame.

`visual.py` projects its image features onto only valid measured stereo points
using estimated camera calibration. The local visual memory retains features
and their observation age. Each frontier receives its own surrounding feature
summary: 128 channels, observed fraction and age, appended to the original 24
map/navigation features. `visual_policy.py` trains a 154→64→32→2 fusion head.
It does not obtain reference poses or geometry. Its offline training labels
remain approximate geometric visibility, rather than pickup rewards.

Prepare separate, new artifact directories, then run:

```sh
python3 flex/exploration/prepare_encoder.py --output EXPERIMENT/encoder
python3 flex/exploration/freeze.py --visual --synchronous-mapping \
    --output EXPERIMENT/frozen
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 flex/exploration/native_data.py \
    --workspace EXPERIMENT/frozen/workspace --inputs INPUTS.json \
    --encoder EXPERIMENT/encoder --output EXPERIMENT/data
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 flex/exploration/native_train.py \
    --visual --data EXPERIMENT/data --output EXPERIMENT/training
python3 flex/exploration/episodes.py --artifacts EXPERIMENT/comparison \
    --frozen EXPERIMENT/frozen --encoder EXPERIMENT/encoder \
    --training EXPERIMENT/training --seeds 81001 81002 --rooms 2 3
```

The comparison evaluates complete six-brick episodes against the unchanged
heuristic, with the same robot, scenes, sensing, collision guards and budget.
The primary outcomes are complete mission success, correct settled deliveries
and time. Failed episodes remain in the denominators; capped completion time
and budget-normalized throughput charge early failures the full action budget.
Map quality and ranking logs are diagnostic, not the task score.

For both policies the private synchronous scheduler pauses the simulation
clock while stationary mapping workers execute. `actionSeconds` measures
simulated action time, `mappingWaitSeconds` measures worker wall time, and
`wallSeconds` includes the entire unpaced episode, including rendering and
inference. `actionPlusMappingSeconds` adds the first two; it is not a measured
hardware execution time. Episodes execute sequentially with a new inference
cache each time. Checkpoints and source/asset hashes are fixed before testing.

Focused checks are `flex/tests/sim-yolo-encoder.py` and
`flex/tests/sim-pickup-episodes.py`. The encoder test also accepts `--encoder
DIRECTORY --reference --output NEW_DIRECTORY` to compare against independent
tinygrad execution of the original ONNX backbone; that optional test needs
ONNX and tinygrad as well as the discovery Python dependencies.

The completed pilot is retained under `build/flex/sim/yolo-episode-v1/`.
The 320-pixel frozen backbone feeds a 12,066-parameter head. Three seeds were
trained for 120 epochs on 25,315 examples, with 4,388 separate validation
examples. Validation selected seed 19 with network weight 1.0 before testing.
All 758 replayed stereo pairs byte-matched their baseline map masks; the
original 24 features and labels also remained byte-identical.

The comparison used two unseen layouts, one episode per method and layout,
350,000 action steps and a 40-minute wall limit per episode:

| Layout | Heuristic settled deliveries | YOLO-assisted settled deliveries | Full missions completed |
| --- | ---: | ---: | --- |
| 81001, two rooms | 3/6 | 1/6 | Neither |
| 81002, three rooms | 0/6 | 0/6 | Neither |

All four physical audits passed. The heuristic timed out in the first layout;
the other three episodes failed because the box was visible but no mapped,
arm-feasible docking pose was found. The learned variant delivered fewer
bricks overall. Its shorter first-episode runtime reflects early failure and
does not demonstrate faster task completion. The production heuristic remains
unchanged. This small pilot establishes no pickup improvement or broad
generalization for the learned method. Training still used visibility proxy
labels rather than episode delivery rewards.

`comparison/report.md`, `comparison/summary.json`, and
`comparison/comparison.png` retain the episode results. `data-audit.json`,
`training-audit.json`, the three `cuda-repeat-audit-*` directories and the
per-episode audits retain the input, optimization and native execution checks.
`python3 flex/tests/sim-pickup-episodes.py --artifacts COMPARISON_DIRECTORY`
rechecks the full trial matrix, source hashes and independent endpoint
containment, explicitly excluding any still-held payload from deliveries.
