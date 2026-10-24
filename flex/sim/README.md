# Native Flexscript simulation

`puppybot-sim` is a standalone 3D PuppyBot environment. The compiled Flexscript
executable runs the production controller, a virtual STServo bus, URDF joint
transforms, vehicle motion, contact physics and the native renderer. It opens no
physical servo device. It is independent of Gym's experiment manager and does
not change the existing `servo-plant-v1` rollout backend.

## Build and run

From the repository root:

```sh
./flex/scripts/build-sim.sh
./build/flex/puppybot-sim
```

The build uses `build/flex/pup-compiler` when available, then `flexscript` on
PATH, then `../flexscript/build/flex`. `FLEXSCRIPT_COMPILER` selects a compiler;
`FLEXSCRIPT_ROOT` selects the shared library checkout. That checkout must contain
`libs/render.flex` and `libs/physics/physics.flex`. Native rendering needs SDL2
and OpenGL 4.5. Headless mode requires neither a display nor a GPU context.
Python 3 converts assets during the build; the executable runs without Python,
Rust, RobotDreams or a browser.

The asset pack includes all 221 URDF visuals (779,812 triangles), grouped by
their 18 independently transformed joint frames. The conversion preserves
visual origins, glTF node transforms, triangle materials and normals. The
four semantic arm joints use `models/puppybot/robotdreams.json`'s scale/offset
mapping. Passive linkage joints retain their exported reference angles.

The build writes `build/flex/sim/puppybot.bin` and a source hash receipt beside
it. Shared renderer/physics dependency hashes are in `dependencies.json`.
Assets are published by atomic replacement so rebuilding preserves active
memory mappings in open simulations. A build-only dependency mirror redirects binary64 imports and duplicate
lowering registrations to the controller's pinned IEEE implementation. It
preserves the shared contact/integration algorithms and the original checkout.
The mirror skips pair calls when both bodies have zero inverse mass, matching
the narrow phase’s existing rejection while avoiding arm self-pair overhead.
Run from the repository root, or pass an absolute asset path with `--model`.

## Blender apartment

The optional three-room world has an editable Blender source, full-height walls
and doorways, a sofa, coffee table, dining table, chairs, console and bookcase.
Export it and run the native simulator from the repository root:

```sh
blender -noaudio --background --python flex/scripts/prepare-environment.py -- \
  --blend models/environments/apartment/apartment.blend
./flex/scripts/build-sim.sh
./build/flex/puppybot-sim --environment apartment
```

The runtime requires only the packed mesh/colliders, not Blender. `--environment
FILE` loads another exported binary. `--spawn '[x,y,headingRadians]'` selects a
starting pose; positions outside the floor or intersecting the robot are
rejected. WASD drives; drag and scroll change the existing world observer;
V selects world/front/TCP, and T toggles the TCP inset. The initial world view
shows all three rooms. Below a 6 m orbit radius, the observer follows the robot.

The front and TCP sensors keep their original mounts and fields of view. Only
the world observer has cutaway walls; robot RGB sees the full-height geometry.
Tabletops and legs have separate colliders, so a high table has real clearance
underneath it. Furniture is fixed; a case's collection box remains movable.
There are 66 furniture/wall colliders and larger world capacities/bounds. Native
rendering uses the exported base colours and its existing light model. See
`models/environments/apartment/README.md` for editing/export conventions and
the decorative details omitted from collisions.

From the repository root, the source entry point builds and launches the native
simulator with the current code. It prepares missing robot/dependency exports
on first use; subsequent launches compile without re-exporting the model.

```sh
flexscript run sim.flex --case house-blocks-into-box --drift 10
flexscript run sim.flex --case house-blocks-into-box --drift 0
flexscript run sim.flex --case ball-into-bin
flexscript run sim.flex --case blocks-into-box
flexscript run sim.flex --list-cases
flexscript run sim.flex --help
```

With no task argument, `sim.flex` selects `house-blocks-into-box`, so
`flexscript run sim.flex --drift 10` also works. All other simulator arguments
are forwarded, including `--camera-panels`, `--record`, `--capture`, `--steps`
and `--bind`. `flexscript sim.flex ...` is the runner's equivalent shorthand.
The entry point also accepts its absolute path when launched from elsewhere.
The simulation itself runs as native Flexscript code, outside the runner's
short VM time and memory budgets.
The source entry point chooses an available local API port automatically;
an explicit `--bind` overrides that default.

`--drift` is the shorter house-case argument for the existing synthetic error
scale: **0** uses wheel integration without added error, **10** is the default
1% distance/0.2 degree steering bias, and **50** is the stronger 5%/1 degree
setting. It selects wheel-drift localization and rejects use with another case
or explicit oracle localization. `--odometry-drift` remains available.

The original pickup cases keep their short floor search lane. The separate
`house-blocks-into-box` case spreads six rotated bricks across the apartment,
two in each room, and searches a coverage itinerary with the front camera:

```sh
./build/flex/puppybot-sim --case house-blocks-into-box
# Retain and audit a new drift experiment (failure is a useful outcome):
python3 flex/tests/sim-odometry.py --run build/flex/sim/odometry/new-run
# Run the original six-brick oracle baseline for comparison:
python3 flex/tests/sim-house.py --output build/flex/sim/house/new-run
```

This case loads the apartment automatically. Hybrid A* plans forward/reverse
Ackermann manoeuvres through the known Blender furniture map. It executes the
production drive commands, with every move checked by the existing swept
collision guard. House collection defaults to **wheel-drift** localization:
the controller integrates wheel-speed/steering commands from a configured
starting prior, independently of true motion. This is mapped coverage rather
than SLAM or unknown-house exploration. The coverage itinerary
contains search poses, not brick targets. The initial layout is a fixed fixture.

`--localization wheel` uses ideal command integration, `wheel-drift` adds seeded
errors, and `oracle` restores the old true-pose baseline. Other cases retain
their existing localization. `--odometry-seed N` defaults to 42;
`--odometry-drift N` accepts 0–100 and defaults to 10. A value of 10 models a
1% distance overestimate (with independent uniform variation of ±0.2%) and a
0.2 degree steering bias. A value of 50 models 5% ±1% and 1 degree.
Errors accumulate only during commanded motion. These are synthetic stress
parameters, not measured PuppyBot sensor specifications.

Wheel-mode navigation, floor-ray calibration, arm targeting and grasp-offset
estimation all use the estimated pose and joint feedback. Camera calibration
is computed in separate kinematic buffers, without reading true camera pose.
Map planning does not query live obstacle bodies. Physical execution can still
stop at a collision, like a protective interlock. The overview, actual camera
rendering and outcome judge retain truth. `localization.evaluation` reports
position/heading errors for inspection; the controller never consumes them.
The map and initial pose prior are still supplied, joints and images are ideal,
and there is no visual relocalization or SLAM correction yet. Finding the box
can correct a local release target; it does not reset accumulated odometry.

```sh
./build/flex/puppybot-sim --case house-blocks-into-box --camera-panels \
    --localization wheel-drift --odometry-drift 50 --odometry-seed 42 --bind 127.0.0.1:0
python3 flex/tests/sim-odometry.py --probe
python3 flex/tests/sim-odometry.py --mode wheel --run build/flex/sim/odometry/ideal-run
python3 flex/tests/sim-odometry.py --trace build/flex/sim/odometry/new-run/trace.jsonl
```

A drift experiment is allowed to fail the mission: `sim-odometry.py` records
`completed: false` and audits the failure without treating it as an infrastructure
error. Its audit independently reconstructs every estimated motion increment
from recorded commands and the seeded error model. The native executable exits
1 for an incomplete mission. `--probe` poisons true root, TCP and world matrices
and checks that camera calibration, IK, planned paths and grasp estimates stay
unchanged in wheel mode.

### Stock-model perception baseline

The target is to run the controller from sensor observations. Oracle poses,
object identities and map truth can remain in the simulator for independent
scoring and future training labels. The current house collector still has a
supplied map, spawn prior and task-judge feedback; it does not meet that target.

Before training a custom model, survey the installed, unchanged YOLO26n COCO
checkpoint on both existing cameras:

```sh
python3 flex/scripts/survey-stock-vision.py --output build/flex/sim/stock-vision/new-survey
```

This saves clean 640x480 front/TCP RGB at the house coverage poses and several
furniture-facing poses, all raw class predictions, annotated review images,
commands, model/asset hashes and `contact-sheet.png`. A settled-ball positive
control checks inference. Only RGB reaches the native Pup detector; fixture
poses, calibration sidecars and object IDs stay in the test harness. The model,
its 0.25 threshold and the robot's camera mounts remain unchanged. This is a
stationary perception survey with the initial arm configuration, not a
navigation test or a measurement of detection accuracy. Duplicate coverage
poses are retained as defined by the case. The collector is not modified by it.

The first survey with a settled positive control saw predictions in 10 of 44
house images: four `chair`, six `airplane` and one `toilet`. Visual inspection
showed chair detections, robot-arm false positives labelled `airplane`, and a
plant pot labelled `toilet`. The ball control scored 82%. These observations
are specific to this checkpoint, scene and mounts. COCO has no LEGO or
storage-box class. Stock detections would need temporal and geometric checks
before becoming landmarks; a class label alone does not identify a unique
chair or give its distance. The RGB-component collector and floor-feature
breadcrumbs below remain separate experiments.

For other reproducible camera/model experiments, the native simulator accepts
`--sensor-capture NEW_PREFIX` with rendering and a finite `--steps` budget.
It writes `NEW_PREFIX.front.png`, `NEW_PREFIX.tcp.png` and calibration sidecars
at the final simulation frame. Dedicated framebuffers keep all UI, detector
markings and cutaway overview geometry out of the images, even with live
panels enabled. Existing calibration sidecars include true camera extrinsics
for independent evaluation; they are not sensor inputs to the detector.

### Moving stock-landmark experiment

```sh
flexscript run sim.flex --stock-landmarks
# Save and independently audit a new complete attempt:
python3 flex/tests/sim-landmarks.py --run build/flex/sim/landmarks/new-run
python3 flex/tests/sim-landmarks.py --probe build/flex/sim/landmarks/new-probe
```

This separate controller starts in a prepared clear corridor. It learns a
static furniture prediction from three consecutive front-camera observations,
drives 0.8 m using wheel-command integration, then reverses until the saved
view matches in three fresh observations. The return decision requires the
same stock class, confidence at least 0.4, bounding-box overlap at least 0.88,
and a 16x16 grayscale crop difference at most 14/255. Ambiguous matches and
stale frames cannot finish the return. Missing/old observations stop driving;
a timeout or exhausted command-distance search window fails the attempt.
These are explicit policy gates, not model training or changed model scores.

The controller reads RGB, YOLO predictions and drive commands. It reads no
world pose, map, object IDs, depth or task judge. Initial spawn and the
collision guard belong to the simulator/test setup. True pose remains in the
trace for independent evaluation only. This demonstrates a fixed-heading
straight teach/return; it does not solve unknown-house exploration, turns,
obstacle avoidance, drift, or collecting LEGO. Similar chairs can still alias.

The front pane shows the actual stock YOLO boxes/confidences on the exact
inference frame, including all class predictions. The TCP pane continues its
existing RGB component stream, labelled `FILL`/`RIM`; these are not model
confidence. No new cameras are added. `R` or `P` restarts; manual driving
cancels the experiment. The window remains open after matching or failing.

The first moving run failed to learn the chair at the old live JPEG quality
80. On the same saved view, native stock YOLO scored the chair at 66% for PNG,
26% at JPEG quality 90, and 54% at quality 95. The experiment defaults to 95;
`--landmark-jpeg-quality 80` reproduces the lower-quality condition. Detailed
frames slightly exceeded the old 48 KB live-message bound, so this experiment
requests a bounded 128 KiB worker input. Existing ball/Gym streams keep their
48 KB bounds and JPEG settings. Weights and the model's 0.25 threshold stay
unchanged. The first completed run drove 0.8 m out and visually stopped 6.8 cm
from its start, confirmed by the independent judge; it did not precisely
relocalize the robot.

`--landmark-output NEW_DIRECTORY` saves each active observation's original
camera PNG/calibration, the exact transmitted JPEG and raw YOLO JSON, plus
`observations.jsonl` with decisions. Recording stops after a terminal decision
while the live panes continue. Restarts create episode subdirectories. The
audit checks model hashes, source-frame provenance, continuous physical motion
and confirmation freshness. The native probe poisons truth/map pointers and
checks ambiguity, wrong appearance, unsupported classes and stale-frame guards.

### Pickup, stock-landmark return and placement

```sh
flexscript run sim.flex --stock-pickup --landmark-confidence 25
# Equivalent catalog entry:
flexscript run sim.flex --case stock-landmark-pickup --landmark-confidence 25
python3 flex/tests/sim-stock-pickup.py --run build/flex/sim/stock-pickup/new-run --confidence 25
```

This one-brick corridor fixture runs the complete handoff: learn the box from
TCP RGB, fold the arm, learn a stock furniture view, search for the floor brick
with front RGB, refine/grasp through TCP RGB, lift/stow, retrace the driven
route and confirm home with the stock landmark, reacquire the box through TCP RGB, place, release and judge settling.
The furniture return bypasses A* home planning. Its coarse stopping point can
hide some rim markers, so the box search reverses slowly through a bounded
wheel-command window and waits for three fresh valid RGB box observations.
Release still requires a same-step camera observation. If the observed slot
is outside the arm workspace, docking searches up to 8 cm forward/backward for
a reachable approach with a 5 mm neighbourhood of valid poses, then creeps
toward it with fresh box observations, bounded to the staging window. This
margin handles the few-millimetre changes seen between RGB box fits. After
release, the empty arm withdraws to its calibrated upright pose; it does not
reuse the compensated held-object target at a different wrist pitch. Camera-guided release poses can rise to 260 mm when a
near-side slot and grasp offset need more height; joint limits still apply.

The scene includes a movable physical box and a rotated brick. Outbound search
and grasp approach still use the known Blender collision map and configured
starting prior with wheel integration. Stock YOLO supplies the return landmark;
the existing colour-component/rim detectors supply brick and box observations.
The current COCO checkpoint has neither a LEGO nor a storage-box class. The
existing contact/grasp constraint and physical task judge remain. This is not
an oracle-free house navigator, and it has no general obstacle-avoidance
policy. Its return controller follows the recorded journey without reading
the house map; wheel slip and newly moved obstacles remain limitations.

Adding the brick/box suppressed the stock chair prediction enough that the
original 0.40 landmark gate failed before pickup. The explicit
`--landmark-confidence 25` variant accepts predictions down to the checkpoint's
normal 0.25 cutoff, retaining temporal, appearance and ambiguity checks. Model
weights and the detector threshold are unchanged. This is a separate weak-
landmark experiment; the default gate remains 0.40. The lower gate is not
evidence of robust chair recognition in arbitrary rooms.

The first audited complete run passed 1/1: two-finger capture at step 1994,
fresh-camera release at 3835, and physical settling confirmed at 4099. It drove
1.71 m with no drive/arm blockage or physics fault. The stock match stopped
7.3 cm from the taught view; the subsequent RGB box search supplied the final
placement observation. The earlier 0.25 run without that box search returned
with the brick but timed out without releasing. The default 0.40 variant
failed to learn its landmark before pickup. All three outcomes are retained
under `build/flex/sim/stock-pickup/` for comparison.

`--landmark-output NEW_DIRECTORY` also records periodic native world/front/TCP
captures for this sequence, with each pane's own capture metadata. Logging
continues through release and the physical outcome. `R` or `P` reruns the full
sequence. The case needs a prepared fresh launch; cycling/API case selection
does not relocate an existing rover into the fixture. `sim-stock-pickup.py`
checks model/frame provenance, grasp contacts, continuous motion, landmark
confirmation before release, fresh box observations and complete brick bounds
inside the settled movable bin independently of the simulator's inside flag.

### Scattered room challenge

```sh
flexscript run sim.flex --case stock-landmark-room --landmark-confidence 25
python3 flex/tests/sim-stock-pickup.py --case stock-landmark-room --confidence 25 \
  --run build/flex/sim/stock-room/new-run
python3 flex/scripts/render-stock-run.py build/flex/sim/stock-room/new-run
```

The harder fixture keeps the same model, 0.25 landmark gate, initial staging
area and movable box. Six rotated bricks span 2.08 by 2.15 m of the dining-room
floor, beside the table, chairs and plant. Their initial cuboids do not overlap
the exported furniture colliders. This is a fixed comparison fixture rather
than a randomized layout. Coverage poses describe a scan itinerary; brick
targets still come from front/TCP RGB observations.

The return controller now records each executed movement command with its
estimated pose before and after the step, including turns and reverse pickup
approaches. It retraces those entries in reverse order with heading/lateral
steering feedback. The supplied map is not consulted on return. An exhausted
route does not authorize arrival: three fresh stock-YOLO/appearance matches of
the taught furniture view still confirm home, followed by fresh TCP RGB box
observations for release. Route progress replaces accumulated signed travel
as the home-match gate; the bounded docking search uses staging displacement.
Docking movements are retained in the route for the next trip. Reset clears
all route history. Stale model frames stop movement without consuming route
entries, and excessive tracking error or collision stops the return.

Outbound planning also remembers loose bricks seen through front RGB. Three
separate observations confirm an estimated floor point; the planner then
keeps the rover footprint clear of it and replans when a new point is
confirmed. The active grasp target is handled by its approach planner, and
pickup removes the corresponding camera-estimated point. If a coverage goal
lies on an observed brick, planning chooses a nearby observing pose facing
that goal instead of driving onto it. No loose-body ID or
true brick position supplies this memory. Confirmed detections beyond the near pickup lane can now trigger an approach
plan up to 1.2 m ahead. The planner tries calibrated grasp/hover poses from
several headings rather than discarding a visible brick outside the current
straight approach. Pickup still waits for fresh wrist-camera refinement and
physical finger contact. The coarse-to-wrist association radius scales from
5 to 12 cm with observation distance and requires compatible RGB colour;
red/orange components are compatible under lighting changes. After a fresh
wrist target is acquired, the gate returns to 5 cm. This handles side-face
ray bias from distant detections without authorizing a blind grasp.
These are local odometry coordinates,
so drift or a moved brick can leave stale points; this is not global SLAM.
`rememberedRgbObstacles` counts stored candidate points, including candidates
that have not yet reached the three-observation gate.

The trace's `stockLandmarks.route` reports the recorded count, reverse cursor
and tracking errors. This is command integration, not wheel encoder feedback
or visual odometry. It cannot measure slip. Outbound coverage still uses the
supplied map and wheel integration. Both existing camera panes remain live.
The audit accepts failed task outcomes, retains the reason and grasp/release
history, and independently checks any completed collection. Native frame
recordings can be rendered into a replay and highlights with the command above.
`python3 flex/tests/sim-route.py` checks turn/reverse replay, a second trip with
dock movement, a tracking disturbance, visual arrival requirements, stale
camera stops, reset, and poisoned world/map inputs.
`python3 flex/tests/sim-placement.py` reproduces two recorded reach failures
using only estimated base poses, servo feedback and camera brick/box targets;
it checks the higher release and bounded base correction without world/map
access. Moving/occluded-box integration checks remain in `sim-dock.py`.
`sim-floor-memory.py` checks independent-frame confirmation, the recorded
rear-wheel collision pose, grasp removal and poisoned world/map inputs.
`sim-approach.py` reproduces the purple brick observed beyond the former near
pickup gate and checks a reachable drive plan without live world geometry.
`sim-refinement.py` reproduces the orange brick's far-ray mismatch and checks
colour-compatible wrist association, including a closer wrong-colour distractor.
`sim-stock-pickup.py --drift 10` also runs the synthetic-drift variant.

The current controller passed both recorded full-room trials at the same
0.25 landmark gate, stock checkpoint and fixed six-block layout:

| Mode | Placed and settled | Steps | Driven | Maximum pose error (judge only) |
| --- | --- | --- | --- | --- |
| Wheel | 6/6 | 22232 | 29.25 m | 0.0 cm |
| Wheel + drift 10 | 6/6 | 27940 | 28.40 m | 15.2 cm |

Both runs have six bilateral-contact captures, six same-step RGB box releases,
all six full brick bounds inside the settled physical box, and no physics
faults. Every home return has fresh stock-view confirmations and no A* home
replan. `route-trial9/` contains the ideal-mode replay and highlights;
`route-room-drift10-trial9/` contains the drift run's trace and raw frames.
`improvement-comparison.json` retains the failed baselines, exact input hashes,
model/frame audits and interrupted-run receipts. These are two prepared-scene
trials, not a general navigation success rate. The drift run's final pose
error was 4.8 mm, evaluated from truth; the controller still has no visual
odometry correction and cannot observe wheel slip.

The first recorded challenge placed 1/6, with two bilateral grasps and one
fresh-camera release. The first return matched 4.4 cm from the taught view.
The second pickup left the rover facing 97.3 degrees away from the taught
heading; straight reversing never recovered that view, and return timed out
at step 9056 with the second brick still held. In 298 second-return RGB samples,
stock YOLO reported other classes but no chair. This is a failed navigation
experiment, not evidence of full-room collection. The source trace, raw model
frames, partial-containment audit and replay remain under
`build/flex/sim/stock-room/baseline/`. This retained baseline used the former
straight-reverse controller. The recorded-route controller is evaluated
separately; intermediate route images do not yet correct odometry drift.

The first recorded-route trial reached home on all four attempted returns,
including approaches at 97 and -136 degrees, and placed 3/6. It then exposed a
release-workspace limit: the fourth slot needed a 240 mm TCP pose, beyond the
former 220 mm search ceiling. A drift-10 room trial placed 2/6 before a far slot
needed a small base correction. These failed trials are retained under
`route-trial1/` and `route-room-drift10/`; they motivated the wider camera-guided
release search and local docking approach. Superseded runs carry an
`interrupted.json` receipt and are not counted as completed task outcomes.
A later drift trial exposed a few-millimetre box-fit change at the arm's reach
boundary, motivating the 5 mm docking margin. An ideal-odometry trial placed
3/6 before a rear wheel met a loose yellow brick during outbound coverage.
That brick appeared in earlier camera observations; RGB floor memory now
feeds those observations into outbound obstacle avoidance. These outcomes are
retained in `route-room-drift10-trial3/` and `route-trial3/`.
The next drift run released a fourth brick into the box, then failed its
empty-arm withdrawal; the compensated drop target was unreachable at the old
retreat pitch. Calibrated withdrawal fixes that case. Both subsequent runs
placed 5/6, but never selected the purple brick despite seeing it beyond the
near pickup lane. Those outcomes (`route-trial7/` and
`route-room-drift10-trial7/`) motivated the confirmed far-detection approach.

### Visual breadcrumb experiment

```sh
flexscript run sim.flex --case house-blocks-into-box --drift 10 --breadcrumbs
python3 flex/tests/sim-odometry.py --breadcrumbs --run build/flex/sim/breadcrumbs/new-run
python3 flex/tests/sim-breadcrumbs.py --trace build/flex/sim/breadcrumbs/new-run/trace.jsonl
python3 flex/tests/sim-breadcrumbs.py --output build/flex/sim/breadcrumbs/new-pairs
```

This opt-in experiment uses **the existing front RGB mount**, with its own
framebuffer and feature buffers. It does not add cameras or change the brick
and box detector's observations. Stock native YOLO returned no detections on
the three retained front-camera samples; this version uses image features,
not furniture labels or learned place recognition.

A Harris-style corner score finds image details. A 64-bit metric patch
descriptor, bilinear image samples, and rigid RANSAC fit ground-plane matches.
The fixed calibrated front-camera height and a flat floor provide metric scale.
Known map colliders, body identities, true root pose and true camera extrinsics
never enter registration. Reference images carry **estimated** poses. Truth
remains in rendering, collision guards and independent error/outcome scoring.

During travel, consecutive image matches correct small odometry errors. Rich
images become route checkpoints at about 18 cm or 10 degree intervals, with
at least 60 features and 12 temporal inliers. Return visits those checkpoints
in reverse order, preserving their recorded viewing direction. This often
means driving backward along the known map; it does not supply a rear camera.
Each checkpoint requires a current visual match before advancing. The final
release still requires fresh TCP rim observations.

At least ten geometrically consistent matches, 5 cm landmark spread in each
floor axis, and a bounded correction are required. Translation corrections are
limited to 6.5 cm and heading corrections to 0.2 rad around the current estimate.
This is local tracking with remembered routes, **not global relocalization**.
The repeating floor grid can be ambiguous, sparse or occluded views can fail,
and errors on a long featureless stretch can exceed the search bound. The
controller stops when a return checkpoint cannot be recognized.

On the fixed apartment with seed 42 and drift 10, direct return placed 0/6,
reverse checkpoints with pose corrections disabled placed 1/6, and the filtered
visual-route experiment placed 6/6. The successful run reached 166 checkpoints
in reverse order and made 1,373 RGB pose corrections. Its global position error
still peaked at 21.1 cm and ended at about 10 cm: repeated floor patterns can
produce a wrong grid-cell match. Fresh local TCP box observations allowed the
releases. This result demonstrates improved route completion on that fixture;
it does not establish accurate global localization in a general room.

`--breadcrumb-output NEW_DIRECTORY` retains checkpoint images with true camera
metadata for independent inspection and `events-EPISODE.jsonl` with estimated
poses and registration results. Trace `breadcrumbs` fields report images,
features, inliers, checkpoint index, correction counts and per-step pose deltas.
`--no-breadcrumb-corrections` keeps the same route/matching logic but suppresses
pose updates, for comparison. A native image-pair test checks a known physical
camera displacement, deliberately corrupts true world pose, and rejects an
unrelated view and a black image. These checks do not feed judge poses into the
policy.

The robot first learns the box rim from its TCP RGB camera and avoids that
observed footprint during navigation. Every brick target then comes from a
front RGB observation, refined through the TCP camera before contact. The
controller generalizes grasp approaches to the robot's current heading. It
filters smaller overlapping colour components and can plan a short sideways
reposition if wrist refinement moves the target off its current driving line.
After
lifting, it folds the arm, drives home, parks using real steering manoeuvres,
and reacquires the box through the same wrist camera. Fresh stable rim-marker
observations authorize release; a remembered home pose alone does not. Physical
contacts supply object identity only after grasping, for the independent judge.

The house case also fits five visible corner/midpoint rim patches when the
gripper hides a complete corner row. This fallback is confined to the house
controller; the original lane cases retain their existing detector behavior.
`case.navigation` reports the route, planner, localization source and progress.
The gray-brick negative control checks that removing the brick colours prevents
hidden-pose pickup. Furniture remains static and navigation does not infer
unseen obstacles from a depth camera; there are still only front/TCP RGB sensors.

```sh
python3 flex/tests/sim-house.py --trace build/flex/sim/house/new-run/trace.jsonl
python3 flex/tests/sim-house.py --probe
python3 flex/scripts/run-cases.py --case house-blocks-into-box --render --record
```

The original `sim-house.py` audit runs the explicit oracle baseline and checks
all six bilateral captures, fresh visual release frames,
settled physical containment, travel across all three rooms, and every pose
increment against the actual previous wheel/steering command. Native helper
checks cover overlapping orange detections, planner priority updates, and the
partial rim fit with rotation and missing landmarks. The general catalog runner
omits long missions unless selected explicitly or with `--include-long`.

```sh
python3 flex/tests/sim-environment.py --render
```

This checks both doorways, travel beyond the old arena bounds, wall/sofa/leg
collisions, under-table clearance, low tabletop and door-frame stops, reverse
escape, malformed assets and spawn rejection. `--render` also captures the
native overview/front/TCP and checks the original camera mounts. Logs and
captures are retained in `build/flex/sim/environments/checks/`.

## Controls

| Input | Action |
| --- | --- |
| W / S | Drive forward / backward |
| A / D | Steer left / right while driving |
| 1–4 | Select yaw, shoulder, elbow or wrist |
| Q / E | Jog the selected joint |
| Space | Pause / resume simulation time |
| N | Advance one 20 ms step while paused |
| R | Reset robot pose, controller, ball and physics |
| P | Reset and run the selected case or ball pickup |
| G | Generate the next seeded random floor layout and run it |
| O / C | Open / close the gripper |
| V | Cycle world / rover / TCP camera |
| T | Show / hide the live TCP inset |
| L | Show / hide the live front and TCP pair |
| B | Toggle YOLO boxes and confidence in the camera inset |
| K | Show / hide robot collision outlines |
| Tab | Show / hide the case catalog |
| [ / ] | Select previous / next case |
| Mouse drag / wheel | Orbit / zoom the camera |
| Escape | Stop and close |

The title reports pause state and selected joint. Releasing drive/jog keys or
losing focus stops keyboard motion. Existing controller limits, faults and
watchdogs still apply. The camera follows the chassis. The cyan dot marks the
gripper grasp centre while empty; red/green ground lines show world +X/+Y. The green pad
is a destination marker, not a grasp or task acceptance condition.

## TCP view

The house collection case shows two small live views on the right: **front**
above **TCP**, refreshed about every 100 ms throughout searching, driving,
grasping and returning. Press **L** to hide/show the pair. Use
`--camera-panels` to enable them for any rendered case, including hidden
captures, or `--no-camera-panels` to disable them.

Green boxes mark RGB colour/shape candidates; yellow boxes mark magenta box-rim
patches. **FILL** and **RIM** percentages describe component fill, not learned
detector confidence. These display-only detections have their own images and
buffers and do not update controller targets or box-observation freshness.
`GET /api/sim/views` reports each pane's capture step/time and detection count.
Captures with the pair enabled also save `.front.png`, `.tcp.png`, their
`.camera.json` sidecars, and `.views.json`. Both views use the existing mounts.

Other visible windows show a live **TCP POV** inset at the top right. The main view
stays available while the inset follows the wrist through approach, grasp and
lift. Press **T** to hide/show it, or **V** to cycle the main view through world,
rover and TCP. Both views pause and reset with the same simulation.

The virtual camera has a fixed mount relative to the gripper: eye
`(0, 65, -65)` mm, looking toward `(0, 0, 65)` mm, with local `-Y` as up.
Local X is jaw travel and local Z points along the fingers. It uses the current
wrist pose, without following the ball position. This is a simulated wrist camera;
it does not imply a physical camera has been mounted there.

```sh
./build/flex/puppybot-sim --vision-pickup
./build/flex/puppybot-sim --camera tcp
./build/flex/puppybot-sim --hidden --steps 1150 --pickup --tcp-view \
    --capture build/flex/sim/tcp-held.png
```

`--no-tcp-view` starts a visible window without the inset. Hidden batch runs
keep a single view unless `--tcp-view` is supplied. Inset captures include a
`.tcp.camera.json` sidecar describing the inset's camera; the normal
`.camera.json` describes the main view. The separate 640 × 480 rover framebuffer
used for YOLO never contains an inset or its caption.

## Detector markings

Visible `--vision-pickup` runs enable the marked camera inset automatically.
Press **B** to switch between the smooth camera view and the latest analyzed
frame, or use `--detector-view` / `--no-detector-view`. The inset is captioned
**YOLO TCP**, or **YOLO ROVER** when the main camera is the rover view.

A resident native detector worker samples the camera about five times per
second without blocking interactive simulation steps. Green rectangles and
labels such as `SPORTS BALL 82%` come from that frame's actual YOLO output.
The inset holds the exact analyzed image until its replacement is ready, so
boxes never float over a newer pose. Empty results replace the old box with
`NO DETECTION`; failures clear the image and show `YOLO ERROR`. Reset clears
previous results and ignores pending replies from the old episode.

The orange sphere may be classified as `orange` in the close wrist view. The
inset preserves that class and its measured confidence. Display annotations
accept `sports ball` and `orange`; pickup planning continues to require
`sports ball` from its separate, unmarked rover observation. Display results
never supply motion targets or use simulator ball positions.

```sh
./build/flex/puppybot-sim --vision-pickup --detector-view
./build/flex/puppybot-sim --hidden --steps 1150 --vision-pickup --detector-view \
    --capture build/flex/sim/marked-held.png
```

Marked captures also export `.yolo.jpg` (the actual detector input),
`.yolo.json` (its raw model result) and `.yolo.png` (the annotated observation).
The TCP calibration sidecar describes the sampled inset pose/time when a
marked frame is displayed. `vision.live` in `/api/sim/state` reports the live
worker state, source view, frame ID/time, class, confidence and box independently
of the pickup's initial detection. Native JPEG encoding requires libturbojpeg.

## Case catalog

The native catalog currently includes:

| Case ID | Task | Success condition |
| --- | --- | --- |
| `ball-into-bin` | Pick up one ball, carry it to the bin and release | Ball fully inside the bin and settled |
| `blocks-into-box` | Collect three Lego-like blocks from a group | All three released and settled inside the box |
| `random-blocks-into-box` | Collect six scattered, rotated blocks from a wider floor area | All six released and settled inside the movable box |
| `search-blocks-into-box` | Find scattered bricks and the return box through RGB cameras | Six physical grasps and releases; all bricks settled in the visually located box |
| `stress-distractors` | Coloured non-target cuboids among the bricks | Experimental level 3 challenge; failures are retained |
| `stress-touching` | Two same-colour bricks touching, with four other scattered bricks | Experimental level 3 challenge; failures are retained |
| `stress-occlusion` | A solid grey divider hides a brick from the initial front view | Experimental level 3 challenge; failures are retained |

Press **Tab** to show/hide the catalog, **[ / ]** to select a case, and **P**
to run it. Selection loads the scene at rest; **P** resets and runs it again.
The panel shows the active case, phase and placement count. Existing **R**,
**Space**, manual controls and TCP views remain available. Manual motion or
opening/closing the gripper cancels an active case.

```sh
./build/flex/puppybot-sim --list-cases
./build/flex/puppybot-sim --case ball-into-bin
./build/flex/puppybot-sim --case blocks-into-box
./build/flex/puppybot-sim --case random-blocks-into-box --seed 42
./build/flex/puppybot-sim --case search-blocks-into-box --seed 42
python3 flex/scripts/run-cases.py --output build/flex/sim/my-case-run
python3 flex/scripts/run-cases.py --render --record --output build/flex/sim/my-visual-run
```

The batch runner defaults to the four ordinary benchmark cases. `--case ID` selects individual cases
and can be repeated. Each run saves a report, definition hashes, logs and final
state; `--record` adds JSONL observations and `--render` adds native PNGs.
Result directories must be new. A finite native `--case` run exits nonzero
if it has not passed by `--steps` (use 24000 for camera search and TCP return).
Camera cases automatically use hidden rendering in the batch runner, even
without `--render`; they need a working display/OpenGL context.

[Catalog entries](cases/catalog.json) point to editable JSON definitions of
objects, masses, colors, initial poses, a physical open container with five colliding surfaces,
gripper dimensions and settling criteria. New entries with the supported
ball/block shapes need no compiler changes. Case definitions are checked
before replacing the current scene. The block case uses 80 mm fingers and
65 mm grasp offset; ball cases use the original 60 mm / 45 mm gripper.
Block studs are visual details on box colliders, without interlocking physics.

The first three catalog policies use **scene state** for object positions.
The existing YOLO ball pickup and live detector remain separate; the current
COCO model is not a Lego detector. The policy selects an unplaced object,
chooses the nearest piece with a collision-free, reachable chassis/grasp approach, closes until both fingers contact it,
lifts, transfers above the rim, carries it to the container, opens and waits for gravity/contact
settling. It accounts for the held object's offset from the TCP when choosing
a drop pose. No object is teleported into the container.

`search-blocks-into-box` instead patrols a bounded straight floor lane and
samples a clean 640 × 480 rover RGB camera every ten simulation ticks. It
segments six saturated colour families, groups connected pixels, rejects
components with implausible size/shape, and projects the bright top-face
centroid onto the known 24 mm brick-top plane. Its initial approach target
comes from these pixels and camera calibration. Near the floor it reacquires
the brick through the downward wrist camera, corrects the grasp, and
repositions the rover if the corrected target exceeds the arm's joint limits.
Missing detections never fall back to simulator object coordinates.

This is a simple **colour/shape detector, not YOLO or a trained Lego model**.
It assumes the simulated brick colours/height, a flat floor, calibrated camera
pose and the positive-Y collection lane. A general real-camera Lego detector
needs training and more robust depth/pose estimates. Collision guards still
use simulated geometry. This case does not implement SLAM or navigation over
the whole room; camera calibration uses the simulated rover pose as odometry.

The return box has 6 mm magenta patches at its rim corners and side midpoints.
Box recognition uses the **existing TCP camera**, with its original fixed
mount and field of view. The arm moves to a reachable survey pose and the rover
searches along its lane; no third camera is added. Connected RGB components locate
the patches; calibrated rays intersect the known rim-height plane, and three
or four corners initialize a fit to the known rectangular dimensions. The fit estimates
box XY and yaw, including after a physical push. Container positions from the
case definition and physics engine do not enter visual homing or drop targets.
This is marker recognition with known dimensions and an upright box on a flat
floor. During the close placement view, at least two currently visible patches
can update translation and yaw by matching the box previously observed from
RGB. A remembered pose or a single patch cannot authorize release.

After lifting a brick, the controller keeps the grasp closed and stows the arm
above the rover, then aims the wrist camera toward the box side. It then searches
for the box, drives to a standoff relative to the observed placement slot, and
checks the camera throughout placement. Release requires three consistent pose
observations and another successful observation on that exact simulation step.
Lost patches keep the brick held; a moved box or sustained arm occlusion causes
stowing and visual homing again. Reset clears visual estimates and restores
the configured patches. Set `container.visionMarkers` to `false` to exercise
the unrecognizable-box path; the physical box remains in the scene.

The marked inset holds the exact most recent front or TCP RGB observation.
The score in API observations is component fill ratio, not neural confidence.
`case.perception` publishes boxes, pixel centroids, calibration and estimated
targets. Object IDs become known only after bilateral finger contact, for
placement accounting. Ground-truth object poses remain available to the
independent physical judge and the general simulation API. `case.dockVision`
publishes the box estimate, marker pixels, camera calibration, freshness,
consistent-observation count and the camera frame used for the last release.

Use `--search-output NEW_DIRECTORY` to retain each clean sensor PNG and camera
sidecar, together with `--record NEW_JSONL` for detections. A main-view capture
adds `.sensor.camera.json` for the held observation in the inset. **G** reshuffles
the camera case and **P** replays the current seed.

### Repeatable clutter challenges

The three `stress-*` entries use the existing RGB controller, front camera and
TCP camera, including their original mounts and fields of view. They add physical
scene clutter without changing the detector thresholds or supplying object poses
to perception. The return box still has its rim patches. These are experiments
that can fail; the ordinary catalog regression runner excludes them unless a
stress ID or `--include-stress` is supplied explicitly.
The catalog entries are fixed level-3 snapshots of seed 42; **P** replays them.
Use the sweep runner below to generate other seeds or difficulty levels.

Run a progressive sweep, including an unobstructed six-brick control for each seed:

```sh
python3 flex/scripts/stress-cases.py
python3 flex/scripts/stress-cases.py --challenge touching --seed 42 --level 3
python3 flex/tests/sim-stress.py
```

The default sweep runs seeds 42 and 43 through levels 1, 2 and 3:

| Challenge | Level 1 | Level 2 | Level 3 |
| --- | --- | --- | --- |
| Distractors | Oversized red slab | Near-camera brick-sized red decoy, also testing cropping/blind spots | Three coloured decoys, including a red one fully in the front view |
| Touching | Same-colour pair, 15 mm gap | Same pair, 3 mm gap | Same pair, touching |
| Occlusion | Divider covers about a quarter of one brick's initial front projection | About half | Full initial coverage |

Coverage is nominal: the robot can move and obtain a different view. The pair's
anchor is shared across gap levels within each seed. The other four bricks retain
the original seeded layout. Fixtures reject initial intersections between scenery
and targets. All six target bricks must still be physically collected and settled
inside the box. The controls freeze the existing floor generator's seeded poses
into explicit positions and `yawDegrees`, preserving their original orientations.

Each run retains its exact scene and challenge settings, full JSONL observations,
clean camera PNGs with calibration, an initial world view, and an outcome view.
`--until-done` stops and captures on a terminal case result, with `--steps` as an
upper bound. The report separates controller failures from execution errors, and
records non-target detections/selections through an independent offline ray/OBB
judge. Boxes covering multiple target centres flag possible merged detections;
they do not prove instance segmentation or count misses behind an occluder.
Diagnostic SVG overlays are offline reviews, never detector input.

The generated `index.html` and `report.json` show outcomes by difficulty and seed.
Every run includes `replay.sh`; invoke it to open that saved scene, or append
`--hidden --steps 24000 --until-done` for a finite replay. The executable and model
are copied into the result directory, with hashes in the report. Sensor images
and traces can occupy substantial space in a long sweep. A stress failure is a
measurement, so the runner returns zero when experiments finish successfully;
an execution error or failed unobstructed control returns nonzero.

Case definitions may include up to eight `scenery` records, each with a unique
`id`, `position`, `halfSize` and `color`. They are fixed cuboids rendered in every
camera and included in chassis, tyre, arm and finger collision guards. Their
geometry appears in the general case observation for judging, separately from
camera detections. They are never counted as target bricks. These first challenges
do not add lighting variation, image noise, wheel slip or friction-only grasping.

### Visual test highlights

Build a self-contained webpage from a retained, combined stress report:

```sh
python3 flex/scripts/build-sim-report.py
python3 flex/tests/sim-report.py
```

The output is `build/flex/sim/stress/highlights-site/dist/index.html`. It embeds
all 20 outcomes, 60 screenshots, case definitions and result data. The page includes
finding highlights, a comparison of both layouts, result filters and an inspector
with initial/outcome/sensor views. Detection boxes are offline overlays on actual
RGB frames. Downloads and copied replay commands work without an external asset
server. Replay commands open the retained scene on the original PuppyBot machine.
Use `--report PATH` and `--output PATH` to select a different retained report or file.

The six-brick random case generates XY positions and yaw rotations in Flexscript before
creating the dynamic bodies. Its default floor region is X `0.30–0.78 m`,
Y `0.015–0.20 m`, within the existing picker's reachable working area. It is
not navigation over the whole 4 m floor. Rotated brick corners stay inside
that region; circumscribed circles leave at least 25 mm between bricks and
keep them clear of the robot, obstacles and container. Bricks start 1 mm above
their resting height, then settle through the same gravity/contact solver.

The default seed is **42**. **G** increments the seed and runs a new layout;
**R** and **P** replay the current seed. `--seed N` accepts integers from `0`
through `4294967295`. The title and `case.seed` report the active seed, and
objects expose `initialPosition` and `initialYawRad` alongside their live pose.
Fixed cases report a null seed. The editable `randomFloor` definition controls
bounds, clearance and yaw range. Invalid or unfillable layouts are rejected
without relaxing clearances. Approach planning searches for a collision-free
base position, rounds it to the base's 0.1 mm movement increments, and checks
a small reach margin before selecting it. The rover folds the arm upright
between pickups so that longer drives do not sweep the wrist through obstacles.

`POST /api/sim/cases/random-blocks-into-box` accepts an optional JSON body such
as `{"seed":1234}`. `POST /api/sim/shuffle` advances the selected random case
by one seed. Both reset and start the task; the existing pause state is kept.
The batch runner also accepts `--seed N` and records the seed in its report.

The box is now a **single dynamic rigid body with five box shapes**, rather
than five fixed bodies. Its floor and walls share one pose and cannot separate.
Mass and inertia use the wall/floor volumes and the parallel-axis theorem; the
default mass is 0.30 kg. This is a prototype parameter, not a measured physical
box. The shared solver supplies gravity, friction (0.7) and restitution (0.2).
A firm shove can slide or rotate it; after contact stops, floor friction brings
it to rest. Bricks inside interact with the moving floor and walls normally.

The random case uses a larger 220 × 200 × 90 mm interior. Container definitions
accept `mass` in kilograms and optional `fixed: true` for an anchored fixture.
Reset returns the box to its definition pose and clears its velocity. The live
`case.container` reports its body, mass, floor-origin position, quaternion,
linear/angular velocity, settled state and five surface centres. All surfaces
reference the same body ID. Pick/drop targets and complete object bounds use
this live container frame; success also requires the box to stop sliding and
tipping. If a low release violates a wrist limit, the policy chooses a reachable
pose above the opening and lets gravity complete the placement.

A case passes only after every required object's complete physical bounds
fit inside the container, its speed is below the configured threshold, and the
gripper has released it. The final placement must remain settled for 100
simulation steps (2 seconds). The bounds allow 2 mm horizontal and 3 mm floor
contact tolerance. Earlier placements are checked again before success.

`GET /api/sim/cases` returns the catalog. `POST /api/sim/cases/ID` loads and runs
one case. `/api/sim/state` includes the case phase, reason, pass state, counts
and every object's pose, velocity and containment result. Existing
`POST /api/sim/reset` leaves the selected case idle; legacy `/pickup` and
`/vision-pickup` routes switch back to the original single-ball scene.

## Pick up the ball

```sh
./build/flex/puppybot-sim --pickup
```

The robot waits for the ball to settle, drives 18 cm toward it, moves above it,
lowers the open gripper, closes, lifts and holds. All arm movements go through
the production controller's inverse kinematics, encoder feedback, joint limits
and serialized servo bus. The sequence uses the default scene and calibration;
it is a scripted demonstration, not a general object-search/navigation policy.
Press **O** to drop the held ball, or **P** to reset and repeat. **Space** freezes
the sequence and preserves its pending arm targets. Manual keyboard motion
cancels the sequence. Losing window focus stops manual control; the autonomous
sequence continues.

The procedural gripper has one palm and two sliding fingers. Its opening is
0–90 mm, with 60 mm long fingers, 10 mm finger thickness and 30 mm pad depth.
The fingers move symmetrically at 50 mm/s of opening width. A right-angle wrist
mount points them downward at controller tool pitch zero. The 60 mm length lets
the fingers reach around the 70 mm ball while keeping the palm clear.

Grasping uses **`bilateral-contact-weld-v1`**: closing must generate actual ball
contacts with both finger colliders, with the ball within 20 mm of the grasp
centre. Only then does the rigid-body solver capture the current ball/palm
relative pose with a weld constraint. The ball stays dynamic, with its mass,
pose and velocity retained. Opening disables that constraint, and gravity and
contact physics move the ball. This is an assisted grasp model; it does not
establish that fingertip friction or a real actuator can support the load.

The recorded `gripper` object includes opening, contact masks, held/constraint
state, grasp/release counts, capture height and maximum held height. `pickup`
reports each phase, its outcome and a specific failure reason. Success requires
the ball centre above 100 mm and a one-second hold; the default checked run
lifts its centre from about 35 mm to 134 mm. For a finite hold or release check:

```sh
./build/flex/puppybot-sim --headless --pickup --steps 1150 \
    --record build/flex/sim/pickup.jsonl
./build/flex/puppybot-sim --headless --pickup-release --steps 1300
```

An incomplete pickup or failed release check returns a nonzero exit status.
`--demo` cannot be combined with either pickup mode.

## YOLO-guided pickup

With the existing native detector and checkpoint prepared:

```sh
./build/flex/puppybot-sim --vision-pickup
```

This mode renders a **640 × 480 RGB camera mounted on the rover**, passes that
PNG through the existing `puppybot-vision` executable, selects YOLO's `sports ball`
class, and guides the pickup from its image box. The native Pup model, weights,
preprocessing and SASS/CUDA/HIP/CPU inference path remain unchanged. The checked
RTX 2070 run used SASS and recognized the plain orange ball at about 82% confidence.
The wide spectator image instead missed the ball and mislabeled the robot as
an airplane; the rover view gives a closer observation.

The camera sits 90 mm forward of the chassis origin and 240 mm above the floor,
looking forward/down. Its offscreen render target is independent of the visible
window size. The camera image contains no object IDs or oracle annotations.
Native PNG encoding uses libpng; Python is not part of the camera or inference
path. Each observation pauses simulation stepping briefly while a separate
native detector process runs, with a 15-second bound.

**YOLO provides a 2D box, not depth.** The planner intersects the calibrated ray
through the box centre with the known ball-centre plane, 35 mm above the floor
for the configured 70 mm ball. Camera extrinsics use chassis pose. It assumes
the ball is resting on that floor; it does not estimate arbitrary object depth
or track the ball after the initial observation. The pickup planner does not
read the ball's simulator position in this mode. Physics contacts and outcome
judging still use simulator state. The assisted grasp constraint is unchanged.

A missing sports-ball detection (confidence below 0.25), wrong image dimensions,
invalid box/ray, missing model or failed detector stops the attempt with its
reason. There is no fallback to simulator ball coordinates. The original
`--pickup` mode remains explicitly labeled `simulator-truth`; the vision mode
reports `pickup.source: yolo-floor-plane-v1`.

Each attempt retains a new `build/flex/sim/vision/run-PID-EPISODE/` directory:

- `camera.png` and `camera.png.camera.json`: the actual detector image and its
  intrinsics, world camera basis, dimensions and capture step/time.
- `detections.json`: native YOLO's unmodified labels, confidence, source-pixel
  boxes, backend, and graph/checkpoint hashes.
- `detected.png`: the same camera frame with the selected box drawn in green.
- `detector.log`: the detector's diagnostic output, including model load errors.

`vision` in the observation records the estimated target, selected confidence,
capture frame ID, attempt directory and status/reason. The file detector's own
frame ID is zero; the attempt directory associates it with the actual camera
capture. **P** repeats the selected mode; **O** releases. Press **V** to inspect
the live rover view. `POST /api/sim/vision-pickup` resets and starts this mode;
`POST /api/sim/pickup` explicitly selects the original simulator-truth mode.

```sh
./build/flex/puppybot-sim --hidden --vision-pickup --steps 1150 \
    --capture build/flex/sim/vision-held.png
./build/flex/puppybot-sim --hidden --vision-pickup-release --steps 1300
```

`--vision-backend auto|sass|cuda|hip|cpu`, `--detector-model FILE`,
`--vision-binary FILE`, and `--vision-kernel DIRECTORY` select the detector.
`--vision-output DIRECTORY` selects the parent for new attempt directories.
`--headless` cannot perform vision pickup because it does not create a renderer;
use `--hidden` for a finite camera/inference batch without a visible window.

For an automatic finite demonstration and a new image file:

```sh
./build/flex/puppybot-sim --demo --steps 250 \
    --capture build/flex/sim/demo.ppm
```

`--hidden` runs the same renderer without showing its window. Captures use PNG
when the filename ends in `.png`, otherwise PPM, and never overwrite existing
files. Each capture also writes a new `.camera.json` sidecar. `--capture` and `--hidden` require a finite
step count. Normal interactive execution advances at 50 Hz. Hidden/headless
execution runs as fast as possible unless `--realtime` is specified.

## Robot API and observations

The existing HTTP and protocol v1 WebSocket controller interfaces are available
at `127.0.0.1:8082` and `ws://127.0.0.1:8082/ws`. `--bind IPv4:PORT` changes
the listener; port zero chooses an ephemeral port printed at startup.

```sh
curl http://127.0.0.1:8082/api/sim/state
curl -H 'Content-Type: application/json' \
    -d '{"throttle":30,"steering":0}' http://127.0.0.1:8082/api/drive
curl -H 'Content-Type: application/json' -d '{}' \
    http://127.0.0.1:8082/api/drive/stop
./build/flex/puppybot --url ws://127.0.0.1:8082/ws arm state
```

`GET /api/sim/state` returns chassis pose, URDF TCP, ball position, physical
encoder ticks, semantic joint angles, contacts, physics faults and controller
telemetry. `POST /api/sim/pause`, `/api/sim/resume` and `/api/sim/reset` operate
the environment and return its state. `POST /api/sim/pickup` resets and starts
the default pickup demonstration; `/api/sim/gripper/open` and
`/api/sim/gripper/close` operate the gripper and cancel any active sequence.
The controller's `/api/state` retains its
existing fake-bus contract; its `sim` field describes the legacy RobotDreams
adapter. Use `/api/sim/state` for this environment's world observations.
World/controller fields remain simulator truth. The `vision` target and
confidence come from rendered-camera inference; its RGB and raw detector result
are retained separately in the attempt directory described above. A standalone
rover observation can be exported with `--camera rover --capture FILE.png`.

```sh
./build/flex/puppybot-sim --headless --demo --steps 250 \
    --record build/flex/sim/rollout.jsonl
```

Records use `puppybot.sim.v1`, one observation per completed 20 ms step. World
coordinates use metres, Z up, and radians. Embedded controller coordinates keep
their existing millimetre/degree units. A 64-cycle controller feedback and
wheel-mode warmup precedes each episode, so its first observation is at 1300 ms.
Reset increments `episode`; `step` and `timeMs` restart, while `totalSteps`
continues. `--steps` limits total executed steps even across resets. Recording
paths must be new. The final observation also prints to stdout. Repeated demo
runs are deterministic on the checked native backend; external controls change
the trajectory. The recording contains observations, not command or firmware
snapshots, and is not an exact-resume format.

## Physics scope

The backend identifies itself as `flexscript-kinematic-contact-v1` and reports
`articulatedDynamics: false`:

- The real controller exchanges checksummed servo packets and fragmented status
  replies with the existing acceleration-limited encoder plant.
- Arm link poses follow the URDF tree. Drive uses a bicycle model with prototype
  0.18 m wheelbase and 0.5 m/s maximum speed. Wheel spin uses the 0.0325 m visual tyre radius. Positive
  steering follows the controller API's right-turn convention.
- Four kinematic cylinder colliders follow the actual URDF wheel joints and
  steering. Their radii, widths and axial offsets are derived from the owned
  visual meshes during packing, rather than measured hardware dimensions.
- Drive checks the chassis and tyres against static obstacles and loose bricks
  with a sampled narrow-phase guard (at most 1 mm between samples). Forward,
  reverse and turning use the same checks. Planned approaches also avoid the
  container, while actual contact with a dynamic container is handled by the
  rigid-body solver, allowing the rover to push it.
- Thirty-two kinematic arm proxies follow individual visual parts. The palm,
  fingers, tyres, chassis, arm parts and compound box participate in physical
  contacts with dynamic objects. Fixed obstacles still block prescribed arm
  motion through explicit swept queries. Fixed/kinematic and self contacts
  are not full articulated dynamics.
- The shared solver advances gravity, friction, restitution and contacts in
  ten 2 ms substeps per controller tick. A movable container can translate,
  rotate and support cargo. Its five surfaces share one mass, inertia and
  transform, with the top left open. The detailed meshes remain visual
  geometry; primitive proxies approximate their contact bounds.

The chassis collider retains 30 mm ground clearance; a 24 mm block between
wheel tracks may legitimately fit underneath, while the same block in a tyre
track stops driving. The rover remains kinematic, without wheel traction, vehicle inertia, suspension
or the ability to climb over a block. The container and loose objects are dynamic;
contact with the prescribed rover motion supplies the impulses that move them.
`vehicle` observations expose the blocking body, blocking part (`0` chassis,
`1`–`4` wheels, `5`–`7` palm/fingers, `8` and above arm visual proxies,
`-1` none), query fault and actual wheel centres/axes/dimensions. `collision`
reports an arm stop and the obstacle body and arm/gripper part that caused it
(`0`–`2` palm/fingers, `3` and above arm visual proxies).
Press **K** or start with `--colliders` to inspect cyan collision outlines;
the blocking part turns red. Outlines appear only in the world view and never
in TCP/rover sensor images or YOLO input.

The chassis/root placement (32 mm above the floor), primitive colliders, ball
mass and motor parameters are prototype values. This version has no arm torque
dynamics, self contact, full mesh contacts, suspension/tyre model, force-controlled fingers,
continuous visual tracking or a learned control policy. It provides a controllable 3D world and
repeatable controller/contact experiments; hardware prediction needs measured
parameters and articulated dynamics.

## Verification

```sh
python3 flex/tests/sim.py
python3 flex/tests/sim.py --render
python3 flex/tests/sim-driving.py
python3 flex/tests/sim-box.py
python3 flex/tests/sim-container.py
python3 flex/tests/sim-random.py
python3 flex/tests/sim-vision.py
python3 flex/tests/sim-views.py
python3 flex/tests/sim-markings.py
python3 flex/tests/sim-cases.py --render
```

The checks compare runtime TCP positions against an independent traversal of
the original URDF, compare repeated recordings byte for byte, test falling-ball
settling and collision-aware ball avoidance, drive into an obstacle, exercise live robot
commands and pause/reset, and preserve existing artifacts. Pickup checks require
bilateral capture, a stable lift/hold, repeatability, a gravity-driven release,
and rejection of an empty grasp. Pause/resume preserves autonomous arm targets.
The render option also captures two distinct poses and the held ball through the native GPU renderer. Local
loopback socket access is required for both modes.

`sim-driving.py` drives the production executable through its HTTP API into
wheel-height bricks in forward, reverse and steering motion at maximum speed,
a narrow brick and a taller chassis obstacle. It checks stopping without
pushing the obstacle through the scene, reversing away, tyre dimensions and
floor alignment, genuine under-belly clearance, and absence of query faults.

`sim-container.py` compares gentle and hard rover pushes, checks longer
frictional coasting after a harder impact, tests rotation from a glancing hit,
verifies that all five surfaces retain the same rigid transform, checks loose
cargo stays inside a sliding box, and verifies reset. It uses physical contacts
through the production robot API; no box velocity or position is injected.

`sim-box.py` deliberately drives forward/backward into a fixed container,
commands a finger through a wall, and rotates an arm link into a taller box.
The checks require blocked motion, stable encoder positions and the ability to
reverse away. Catalog tests also require successful placement through the open
top with the collision guards enabled.

`sim-vision.py` additionally requires the prepared YOLO checkpoint/kernels,
native detector, a supported rendering/inference device, and Pillow for image
inspection. It runs real RGB inference and pickup, independently checks the
camera ray estimate, compares native PNG/PPM orientation, and exercises missing
target, wrong-class, invalid-ray and missing-model rejection without oracle
fallback. The recorded target is checked against simulator truth only by this
test's judge. Negative detector fixtures are used only for rejection tests.

`sim-views.py` checks the wrist camera against an independent URDF TCP, verifies
that joint and chassis motion move the view, compares every pixel outside the
inset with a single-view render, and checks the caption and held ball. It needs
the native renderer and Pillow. The YOLO test runs with the inset enabled to
verify that presentation does not contaminate inference images.

`sim-markings.py` replays each saved wrist/rover input through the real native
detector and compares the displayed class, score and box. It checks border
pixels at the returned coordinates and the label pixels, tests empty results,
and verifies API responsiveness, reset invalidation and worker cleanup. Only
the empty-result path uses a fixture.

`sim-cases.py` executes the catalog cases, independently computes containment
from observed quaternions and definition dimensions, checks bilateral captures
and real releases for every object, requires sustained physical success,
compares repeated outcomes, tests case-switch/reset/pause APIs and rejects
invalid definitions. `--render` also verifies the same outcomes through the GPU
renderer and native catalog display.

`sim-search.py` checks full six-brick camera collection, independently projects
published pixels, verifies contact-only object identity and capture continuity,
and judges physical containment. A far-brick fixture must drive before pickup;
a grey-brick fixture must keep searching without a blind grasp, even though
the simulator knows the brick's location. It requires native rendering.

`sim-dock.py` physically pushes/rotates the box while a brick is held, and
hides its patches during placement while moving it again. It verifies marker
rays independently, compares estimated poses with physics solely as a test
oracle, checks that missing/stale observations cannot open the gripper, and
requires successful reacquisition and physical containment. `--output NEW_DIR`
retains camera images and complete traces.

The simulation-only `POST /api/sim/container/push` accepts an `impulse` vector
in N s and optional `pointOffset` from the centre of mass in metres, both in
world axes. Component limits are ±0.5 N s and ±0.15 m. It applies a physics
impulse without cancelling the task. `POST /api/sim/container/markers` with
`{"enabled":false}` hides the patches for an occlusion probe; `true` restores
them. Neither endpoint updates the controller's visual estimate directly.

`sim-random.py` independently checks rotated floor bounds, obstacle/robot/bin
clearance and separation across 37 seeds, then verifies seed replay, API reset
and shuffle, unchanged fixed cases, and rejection of invalid seeds or impossible
regions. Catalog checks also run and render the seeded random pickup case.
