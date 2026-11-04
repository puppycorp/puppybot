# Missing docking-floor evidence and stale arm turn (4 Nov 2026)

The 34,560 staging rejections in [diary 115](115-matched-short-waypoint-result.md)
were not shown to be a box-geometry failure. All 15 staging enumerations
rejected all 2,304 sampled poses at the observed-floor check, before box
margin, drop clearance or route planning. The saved worker metadata and
trace report zero mapped occupied cells in each corresponding floor map.
Every sampled pose and its rotated rover footprint lies well inside the map,
so the out-of-map branch cannot account for these rejections. Under the
retained mapper's thresholds, the remaining reason is missing mapped-floor
evidence. This classification does not prove the physical floor is empty.

For the last map, frame 31,037, the retained `evidence.npz` independently
reconstructs the reported zero occupied cells and both exact coarse and fine
observed-floor masks. Earlier per-frame occupied counts are worker metadata;
their full underlying evidence arrays were not retained. The saved map
directory is outside the original trial inventory, so its provenance is
weaker than the supervised trial outputs. The read-only
`experiments/dock-stage-cause-v1/audit.py` records the local file hashes and
checks the 15 traces, map masks and geometry. Its `report.json` preserves
the resulting input identities. There was no delivery in this episode.

One additional mapped approach is worth testing. An offline native planner
replay at tick 31,038 used the post-waypoint map, the saved estimated pose
and two failed-command constraints reconstructed from adjacent trace rows.
It found six routes among nine 20–40 cm sampled goals; all three 40 cm goals
failed clearance. The existing short-waypoint selection returned a two-
primitive route to estimated `[-1.191948, 0.229853]` m, about 0.239 m from
the current estimated pose. Its requested 20 cm sample was
`[-1.130601, 0.244147]` m; the sampled goal and actual planner endpoint are
not the same. This is an offline plan, not a commanded or completed drive;
the exact original in-memory contact insertion timing was not retained.
`experiments/dock-stage-cause-v1/waypoint-replay.py` and
`waypoint-report.json` contain the replay and local input hashes.

An opt-in private-copy prototype in `experiments/dock-second-waypoint-v1/`
allows at most one additional short waypoint after the first waypoint really
finishes, a subsequent complete floor-mapping sweep finishes, and a new map
from that sweep is applied. It reuses the existing route, swept-footprint,
remembered contact, payload, distance, progress and deadline checks. The
original survey and fresh stable RGB gates still govern the next release.
Unknown floor remains blocked. An episode-wide counter survives search reset
and caps accepted waypoints at two. CPU tests compile the copied simulator and
exercise accepted, blocked, missing-map, timeout, reset and disabled branches
with planner and actuator stubs. This prototype has not been independently
reviewed or rendered. The saved geometry does not establish that the new
view will reveal usable floor, that a release pose exists, or that any route
can be executed safely.

The 1,499-poll collector limit censored the existing candidate after 15 of
the post-waypoint staging enumerations, before a full mapping sweep finished.
The additional-waypoint trigger therefore may not be reached at that
horizon. A longer comparison would need the same prespecified poll and wall
limits for every arm, plus a reviewed corresponding physical-agent tick
limit, and cannot be compared as though it used the earlier short horizon.

The review also found a separate stale-observation arm-control issue. A
successful old stage estimate ends mapping and enters survey; that survey may
move the arm but does not itself open the gripper. A fresh stable observation
is required again before the usual final release. However, when a previously
authorized release-arm yaw turn is still in progress, the turn update runs
before the stage 7/8 freshness guards and can command the retained lowering
target after the box observation becomes invalid or expires. It does not
itself issue the gripper-open command.

An isolated native CPU A/B probe in `experiments/dock-turn-freshness-v1/`
reproduces that stale lowering command and tests a conservative private-copy
guard that fails the case when vision is stale, unstable or the observed box
has changed. The guarded path calls the existing real stop routine, clears
four modeled joint targets and speeds and the drive state, retains the
simulated held flag, and issues no gripper-open command. Fresh, stable,
unchanged evidence continues through the old turn path. The test also checks
expiration before the arm is settled. It stubs sensors, settlement and
actuator application; it does not prove a physical stop or secure grip. The
guard has not been applied to the active simulator and can reduce completion
on transient visual loss. Independent review is required before adoption.

Both diagnostics ran on the CPU only. No original trial data, pinned
simulator source or training inputs were modified, and no new GPU trial was
launched.
