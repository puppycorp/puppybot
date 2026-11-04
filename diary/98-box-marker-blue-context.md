# Blue context and small box markers: offline replay (3 Nov 2026)

A research-only copy of the dock detector now requires nearby blue-like
pixels when its separate three-pixel marker option is enabled. At least two
accepted components must also have a mix of blue and nonblue pixels nearby, a
crude boundary proxy counted across all accepted components, including those
not used by the fit. On retained images this rejects both magenta-on-black and
magenta-on-solid-blue marker spoofs while retaining the known small-marker
views. It is **not reliable box identification**: a synthetic image with the
same magenta components on half-blue, half-black patches, but no box, still
passes the full geometric fit. Neither the new gate nor the older
three-pixel option should authorize release. The colour and pixel thresholds
were selected after seeing the saved views, and have not been tested on
independent scenes or physical camera images.

The saved worker-barrier trial had 15 survey frames per arm. The two controls
produced no offline box fits in their 30 frames; in the elevated candidate,
frames 60–64 at ticks 11,477, 11,487, 11,497, 11,507 and 11,517 all fit, while
the preceding ten do not. The ungated three-pixel detector produced the same
fits and marker counts on these 45 frames: the blue and boundary gates improved rejection
of two synthetic spoofs, not these actual-view results. The original four-pixel
detector saw no fresh box pose in this trial (diary 93). The original trial
remains censored, and this offline replay does not change its completion status.

A single native detector instance replayed the five saved candidate frames in
order using their recorded tick spacing. It produced stability counts 1, 2, 3,
4 and 5 and identical estimated local XY `[-1.366620, -0.401332]` metres.
The simulator trace records a settled arm and identical joint ticks
`[1467,257,3027,2967]` at those five ticks; saved estimated camera calibrations
also match. The RGB images alternate between only two hashes, so these are
repeated observations of one stationary viewpoint, not independent examples.
The estimate depends on recorded estimated calibration and is not independent
physical pose, sensor freshness or box truth. No release-stage planner or
actuator was executed in this replay.

Nine CPU tests compile copied native detector code and exercise all 45 saved
barrier frames, previously retained positive and occluded images, disabled-path
parity, black, solid-blue and half-blue synthetic marker spoofs, and the five-frame sequential
state. The receipt locally hashes saved images, camera metadata and the candidate trace; this does
not independently attest their provenance. No new GPU run, real robot motion,
pickup, release or delivery was performed. Continued work needs stronger box
identification and negative-scene evidence, followed by a controlled rendered
trial; the marker-colour check alone is not a safe release criterion.

Artifact: `experiments/dock-marker-blue-support-v1/`.
