# Connected blue support around fitted box corners (3 Nov 2026)

An offline follow-up examined whether observed markers associated with the
copied native box fit's estimated corners share a connected blue-coloured
region. The prior
blue-context experiment counted all accepted markers, including markers not
used by the fitted pose, and accepted a fabricated image of separate blue and
black patches with no box. This diagnostic exports corner-associated marker
indices from the real copied detector and tests four-connected blue pixels in Python; it
does not change the detector, planner or robot.

A region of at least 200 blue-like pixels within an 11×11 square around at
least two distinct corner-associated markers preserved all five detections in the saved
worker-barrier survey and all three additional earlier positive images. The
native fit made no detection on the other 40 of those 45 barrier frames. The
five barrier detections are repeated images from one stationary viewpoint, not
independent scenes. The threshold, colour test and selected earlier positives
are post-hoc, and occluded box views may fail this criterion.

The separate half-blue/half-black patch spoof still fooled the native fit but
was rejected by the connected-region cue: its largest connected component
near a fitted corner covered only one corner. However, a second synthetic
no-box image with blue lines joining the same marker patches fooled both the
native fit and the connected-region cue. Connectivity is not sufficient to
identify a real box or authorize release. Two observed fitted corners do not
establish a whole box boundary, and connecting colours in an image do not
establish depth, physical free space or object identity.

The CPU test compiled an instrumented first-frame native detector and replayed
all saved and synthetic frames. One test group passed; two independent audit
invocations generated identical report bytes. The local receipt verifies the
named image and camera hashes, with selected source, compiler and library
version records. It does not establish camera provenance or a complete build
chain. Only first-frame fits were examined; no temporal tracking, new rendered
episode, real pickup, release, delivery or physical robot was tested.

Artifact: `experiments/dock-rim-connectivity-v1/`. Any future use needs
independent scenes and negatives, tracking/occlusion tests, and a validated
release decision; this cue remains an offline research diagnostic.
