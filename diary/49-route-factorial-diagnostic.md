# Paired search-route diagnostic

The matched epoch-8 L5 selection showed treatment entering the other room in
21/32 games versus 32/32 for control. All eleven missing entries were in the
x=1.7 partition group, whose initial robot pose was the same in all cases:
`[-0.04, -0.04, 0.42]`. Treatment's first 240 actions were identical across
those eleven seeds. For each pair, the policies first diverged at action 71,
near `[-1.46, 0.50]`, before crossing. In seed 7800001 control crossed at
244 and picked up at 283; treatment never crossed in 300 actions. Treatment
travelled about 18 m and had zero reported back-and-forth steps. It visited
65 distinct 0.25 m cells and re-entered previously visited cells on about
19% of cell transitions, ending 0.62 m from its start. It is a route failure,
not evidence the robot stood still. Since those eleven games share a start
and environment, their outcomes are not eleven independent layout trials.

`route-coverage.py` scores saved virtual-game search trajectories from the
start through first pickup, or all 300 actions without a pickup. It reports
path length, net displacement, unique world-grid cells and re-entry share,
as well as first room entry, pickup and deliveries. Cells are not a free-space
map, and search windows can have different lengths if pickup times differ.
The metric reads simulator truth offline; it supplies no policy input.

The proposed selection-only diagnostic uses 27 conditions: training layouts
13, 15 and 17 crossed with starting yaw 0.35, 0.42 and 0.49 radians and
seeds 7800001, 7800004 and 7800007. The starting position is fixed at
`[-0.04, -0.04]`; each condition runs both fixed-epoch-8 policies. Input
preparation changes only the 24 spawn-pose bytes in the corresponding PBENV
file; collider records and the rendered meshes remain byte-identical to their
source layout. Each policy pair must actually start at the expected pose with
the same scene and brick placement. The runner checks that brick placement is
the same across headings within a layout and seed and fails if not.

This matrix tests heading changes within each layout and whether the paired
policy difference changes with heading or layout. It does **not** isolate a
single doorway parameter: these layouts also differ in room dimensions,
partition location and width, wall opening, visual appearance and case data;
initial target placements can vary across layouts. Three seeds do not make
independent layouts or establish generalization. Each game gets a fresh
policy process rather than sharing the multi-episode process used in the
previous selection run, so this is not a bit-identical replay of that run.

When the GPU is otherwise idle, and after independent review, prepare inputs
and launch the diagnostic with:

```
O=build/flex/sim/levels-v2/pitch82/search-dagger-l4-matched
python3 -I datasets/visual-control/chase-v1/levels/prepare-route-factorial.py "$O/route-factorial-scenes"
python3 -I datasets/visual-control/chase-v1/levels/run-route-factorial.py
```

The generator and runner refuse existing outputs; failed or partial output is
retained. The runner uses the same nonblocking experiment lock as matched
training and selection, a clean process environment, a per-game watchdog and
source, scene and fixed-epoch package checks. It requires 12 GiB free before
starting and 8 GiB before each condition; the lock does not detect unrelated
GPU jobs. It checks recorded model snapshots and trace declarations, but it
does not attest every actor input or every process. Its carry cue is derived
from simulator task state; it is not an independently sensed physical-robot
input. The retained held-out qualification gate remains disabled.

The scene-preparation and route-analysis tests are CPU-only. The 54-game
paired rollout then completed and passed its start, placement and input
checks. Across the 27 conditions, control entered the target room in 17
games and treatment in 24; they made 17 and 32 deliveries respectively.
Heading mattered within layouts: on layout 15 treatment entered in 3/3,
0/3 and 3/3 games at yaw 0.35, 0.42 and 0.49; control entered in 2/3,
3/3 and 3/3. On layout 13, control entered in 2/3, 0/3 and 2/3 while
treatment entered in 3/3 at all three headings. On layout 17, control
entered in 3/3, 0/3 and 2/3 and treatment in 3/3 at each heading. These
small groups contain three seeds sharing each environment and start pose,
not three independent layouts. Other geometry and appearance vary between
layouts, so these results isolate neither doorway geometry nor a general
policy improvement. They are virtual-fetch training-layout diagnostics, not
held-out or physical-robot evidence. The full manifest, games and report are
under `search-dagger-l4-matched/selection-route-factorial`.
