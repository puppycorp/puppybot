# Dock survey camera-aim kinematics (3 Nov 2026)

At tick 11,477 of the matched footprint trial, the box was visible toward the
left of the high-wrist image but the original four-pixel detector did not obtain
a fresh pose. A CPU-only probe reconstructed the recorded wheel-local pose and
four measured joint ticks using the actual native simulator kinematics. Its
camera calibration matches the recorded 12 camera values within 1e-6, and it
reproduced the commanded existing survey target ticks `[1459,249,3020,2975]`.
This validates the narrow reconstructed state, not arm motion or its safety.

The probe sampled 1,176 combinations of 4–16 cm radial wrist offset, 340–400 mm
height, 65–90° requested finger pitch and −40° to +20° angular offset. The
existing native IK accepted 273. Candidate targets were derived from the old
cached RGB box estimate available to the survey. For offline scoring only, the
script projected the prior three-pixel detector's fit in the matching saved
image at the expected 99 mm marker height. That fit mapped through the recorded
robot-relative transform to within 3.7 mm of the simulated box centre in this
one selected view; it can also be fooled by an image with no box and is not a
release decision. Simulator truth was used only for that subsequent error check.

| Wrist pose: radius / height / pitch / offset | Target ticks | Projected box centre | Projected depth | Max travel from recorded ticks |
| --- | --- | --- | --- | --- |
| Existing: 4 cm / 380 mm / 80° / −20° | `[1459,249,3020,2975]` | `[195.7,379.0]` px | 1.081 m | 8 ticks |
| More centred: 4 cm / 380 mm / 80° / −40° | `[1231,249,3020,2975]` | `[341.5,382.2]` px | 1.102 m | 236 ticks |
| Alternate: 10 cm / 400 mm / 80° / −20° | `[1259,596,3432,2912]` | `[324.1,365.5]` px | 1.067 m | 405 ticks |

All projections above are from predicted target ticks; real settled ticks may
differ. The first alternative improves image centring but is about 2% farther
from the fitted point; the second is about 1.3% closer than the existing
command. These small depth differences alone do not demonstrate enough pixel
coverage to pass the original four-pixel gate. Image rasterization, payload
occlusion, move guard behavior and reachable camera sightlines can change the
outcome. None of the candidates was commanded or rendered, and the probe did
not establish arm, held-brick or physical-robot collision safety.

`experiments/dock-survey-aim-kinematics-v1/` contains the probe, input hashes
and report. Two CPU runs produced identical bytes. This is one reused selection
scene with an offline fit, not a held-out test, delivery, recovery or trained
policy improvement. A matched guarded rendered test would be needed before
changing the survey behavior.
