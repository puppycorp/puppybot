# Why the captured brick did not reach the box (3 Nov 2026)

The enabled arm of the censored dock-confirmation trial captured the brick,
but its subsequent box survey found no usable marker components. It then
rejected all 36 planned circular viewpoints without executing a viewpoint
move and failed while still holding the brick. This is a trace diagnosis of
one previously used simulator selection case, not an outcome attributable to
dock confirmation or evidence of physical-robot performance. See
[entry 71](71-dock-confirmation-censored-comparison.md) for the control
divergence and the complete trial boundary.

At tick 13,830, the simulator gripper captured the brick. After stowing it,
the collector planned a return to the remembered observation pose and reached
the parking/survey sequence. From ticks 15,809 through 16,201, three wrist
survey orientations produced 15 recorded dock samples. None produced a fresh
valid dock pose or any retained marker components. The displayed
`visibleCorners` value remained two from the older observation; it is not a
fresh detection count. At tick 16,210, the collector reported `viewpoint:36`
and failed with `box not reacquired from the bounded circular camera search`.
The recorded route-planning count increased from 5 to 41 in that tick, with
no intervening simulated movement. Thus the 36 viewpoints were considered by
the planner, not actually visited. The trace does not record a separate
rejection reason or expansion count for each candidate.

The archived `case.flex` aims each survey from the estimated arm origin toward
the last RGB box position, with a centre view and offsets of approximately
plus or minus 20 degrees. `dock-search.flex` centres its circular search on
that remembered RGB position and advances the viewpoint index when a navigation
plan fails. `navigation.flex` requires observed-clear floor and checks the
estimated box clearance in collector mode; unknown floor is not authorized by
the remembered position. These checks use local estimates rather than the
simulator's true object pose. The existing detector requires fresh observations
and stability before docking; neither a remembered pose nor a partial marker
hint alone authorizes release.

The saved robot localisation was very different from simulator truth, but
the remembered box and robot positions share the estimated frame. At the
final survey position, post-run truth gives a box-centre bearing of +0.398 rad
and range 1.131 m relative to the robot; the remembered RGB centre and local
robot estimate give +0.487 rad and 1.140 m. The relative difference is about
5.1 degrees and 9 mm. These are centre-to-base comparisons, not camera-frame
visibility measurements. The large absolute pose offset therefore does not
by itself explain the failed survey; we cannot identify whether field of
view, occlusion, rendering, marker detection or another factor prevented
reacquisition from the retained trace alone. Simulator truth was used only
for this after-the-fact comparison.

The next diagnostic should retain the raw wrist RGB and camera calibration at
each survey attempt and record a reason for every viewpoint-plan rejection.
That would distinguish missing or occluded markers from detector failure and
unobserved floor from other planner constraints. A future recovery may use
the remembered RGB pose as an attention or planning hint, but should preserve
fresh-image and mapped-clearance checks before approach and release; this
trace does not establish that such a recovery would succeed.

Evidence: the saved `trial/candidate-search/run/trace.jsonl` and audited
`trial/audit.json` under
`build/flex/sim/levels-v2/pitch82/physical-dock-confirm-monitored-v1/`, plus
the archived source under `physical-dock-confirm-build-v1/source/sim/`.
