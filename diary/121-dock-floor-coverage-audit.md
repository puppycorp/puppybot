# Where docking-floor evidence is missing (4 Nov 2026)

In the saved short-waypoint run from [diary 115](115-matched-short-waypoint-result.md),
the candidate acquired more mapped floor near the estimated box but still
had little coverage across the area relevant to release staging. Using the
recorded local RGB box estimate `[-1.372582, -0.404959]` m, the staging
centres span radii 0.28–0.40 m. The rover footprint extends up to 0.193 m
from a centre, so an 0.08–0.60 m annulus gives a convenient approximate
area summary. Its 2 cm cell centres number 2,777.

The first retained staging map, frame 21,179, marks 60 of those cells
effectively clear; the last, frame 31,037, marks 430, or 15.5%. A cell is
counted clear when its containing 10 cm coarse map cell is clear or its
2 cm detail cell is clear, following the navigation check's coarse/fine
fallback. Of the final 430 cells, 339 are northeast and 91 northwest of the
estimated box; none are south. This is a descriptive cell-centre statistic,
not a per-pose footprint or swept-route check. It includes no evidence that
unmapped cells are unsafe or safe. Map and box coordinates are local
estimates, not ground-truth box location.

The data support the earlier finding that all 34,560 sampled staging poses
were rejected at observed-floor checking before box-margin, arm/drop or
route checks. The last saved mapper evidence independently reproduces the
coarse and fine masks and has zero confirmed mapped occupied cells. Earlier
occupancy counts come from the retained worker metadata. The worker-output
directory is outside the original supervised trial inventory; the new
read-only `experiments/dock-floor-coverage-v1/audit.py` pins the local map
file hashes to the preceding saved-map audit and reproduces these statistics
in `report.json`.

One point-level camera replay helps explain why more pictures do not
automatically clear this area. For the estimated ground point at
`[-1.372582, -0.004959, 0]` m, 0.40 m north of the estimated box, the
recorded camera geometry places it within both images in four saved stereo
pairs. Replaying the original worker found its robot self-mask covers that
projected point in frames 23,385 and 23,791. In frames 25,461 and 25,865,
it is not self-masked but does not pass the worker's local texture gate;
metric stereo is invalid in the former and valid in the latter. These are
specific projected pixels, not an explanation of every missing cell or proof
of physical occlusion. The final 2 cm detail cell is unknown, while its
containing 10 cm coarse cell is marked free, so this point alone does not
prove any particular staging footprint is blocked. The checks reject
untextured and robot-masked areas for a reason; this analysis does not relax
those checks. The read-only `experiments/dock-floor-coverage-v1/camera-audit.py`
checks the worker source hash and runtime versions against the retained trial
pins, instruments that source in memory, and hashes the saved requests and
RGB before and after replay. Its saved report was independently reproduced
byte-for-byte. These checks do not attest the original worker's execution.

A bounded camera experiment could add one intermediate estimated yaw near
−132° in this run's local frame, between the saved −109° and −154° views,
aimed toward the near-side patch. A general implementation should derive
the bearing from current estimates rather than hard-code that angle. It
should accept both stereo endpoints only through the existing IK,
requested-yaw and arm/payload collision checks, and retain the existing
height, pitch search, stereo consistency, texture and self-mask gates. This
is a hypothesis, not evidence of a clear view: the −154° views already
avoid the self-mask at the sampled point but fail its texture test. The
extra view may do the same, be unreachable, or fail to add useful floor.

A concrete planning candidate is one additional short route on an updated
map after the first waypoint completes and the subsequent floor-mapping
sweep ends. The preserved native planner replay from
`experiments/dock-stage-cause-v1/waypoint-report.json` used map frame 31,037
and two approximately reconstructed historical failed-command constraints.
It planned two primitives to `[-1.191948, 0.229853]` m: estimated box
distance falls from 0.893 to 0.660 m and the endpoint is 0.239 m from the
current pose. The sampled destination differs from the actual endpoint.
This is offline planning only; the pose was not driven, retained-contact
timing is not fully attested, and moving closer does not prove an unobstructed
or useful camera view, a reachable eventual stage or a safe physical path.
The private second-waypoint prototype retains unknown-as-blocked, the
existing planner and collision checks, and fresh stable vision for release;
it remains subject to independent review.

The retained trial was censored during the same scan. It recorded 15 stage
checks, ending at sector 7, tilt 0, and stopped at tick 31,377 without a
recorded sector 7, tilt 1 check. Consequently the full-sweep-triggered second
waypoint was not evaluated. The client permits at most 1,500 collection
polls of 20 simulated ticks each and the simulator separately caps the
physical-agent phase at 30,000 ticks. A future longer comparison needs
reviewed copies of both limits, identical prespecified poll, tick and wall
budgets for controls and candidate, and its own separate audit. It cannot be
reported as a direct equal-horizon comparison with the earlier 1,499-poll
run. No GPU test was launched for this audit.
