# Dock survey: small rasterized rim patches (3 Nov 2026)

The saved first elevated-survey view with a valid box and the later
clearance trial's first failed view contain nearly the same projected rim
patches. The latter missed them at the detector's minimum-component-size
gate. This identifies a concrete perception sensitivity, but the two runs
were censored comparisons and the recorded images do not establish why
their rasterizations differ or prove what would happen in a new run.

Both first requests targeted ticks `[1644,249,3020,2975]`; settled measured
ticks were `[1637,257,3027,2967]` and `[1637,257,3028,2967]`. Their true
base poses were approximately `[-0.758899,0.064604,-0.620239]` and
`[-0.759671,0.064413,-0.619128]`; estimated camera eyes were
`[-0.960,0.667,0.456]` and `[-0.960,0.668,0.456]` metres. The camera
metadata is the recorded estimated calibration, not an independent
measurement of the rendering camera. The frames differ in pixels; the
similarity of pose and calibration alone does not explain that difference.

At first successful frame 15,745, rim-colour components at image centroids
`(29.25,347.25)`, `(82.67,353.17)`, `(88.70,370.90)` and
`(93.75,385.75)` contain 4, 6, 5 and 4 pixels respectively. The first
clearance frame, 15,725, has the corresponding patches at approximately
`(29.50,346.50)`, `(82.50,352.50)`, `(88.50,370.50)` and
`(93.00,385.50)`, containing 3, 3, 3 and 2 pixels. The detector discards
components smaller than four pixels; its only surviving current marker
is `(48.75,380.75)`, with four pixels. It reports no fresh box pose.
The trace's `visibleCorners:5` and box position
`[-1.273321,-0.439698]` are from old frame 11,141; they are not a fresh
five-marker detection. The first successful updated position is
`[-1.354793,-0.415220]` in the estimated local frame.

At the clearance trial's second view, the saved frame has no matching
rim-colour pixels. At its third view (frame 16,077), a larger portion of the
box appears in the raw image around x=140–245, but all eight detected
rim-colour components contain only two or three pixels. Six have three
pixels and two have two; therefore none passes the current size gate.
The box remains off-centre and partially obscured in some views, but changing
wrist direction alone is not a demonstrated fix for the raster gate.

Reproduce the colour mask and four-connected component counts, without GPU
or changing an image, with `experiments/dock-rim-raster-audit-v1/audit.py`;
`recorded-components.json` records SHA-256 hashes and results for the three
first successful frames and all 15 failed clearance survey frames. This
audit only screens colour, connectedness and image boundaries: component
counts at an alternative threshold are not a valid box pose, and it does
not reproduce ray, geometry, tracking, temporal stability, or release
checks. The three successful frames have identical component measurements;
so do the five frames at each separate clearance viewpoint. These repeated
views are not independent scene samples.

An isolated source transform in `experiments/dock-rim-raster-audit-v1/`
adds `PUPPYBOT_DOCK_SMALL_COMPONENTS=1`; the default remains the original
four-pixel minimum, and an invalid value is rejected. The experiment keeps
the existing geometric fitting, stability, clearance and release code, but
the flag changes the component gate throughout the candidate simulator,
not just the high-wrist survey. No frozen source or normal simulator was
changed. The six CPU-only tests compile the copied Flex source and call its
actual detector on these saved frames, plus synthetic controls. Disabled
and unset settings match the original detector's results on all 18 saved
frames. The enabled version fits the first clearance frame using five
components, at `[-1.354198,-0.413767]` metres, and the third using six,
at `[-1.354006,-0.415246]`. It also fits the earlier successful view; the
second clearance view remains undetected. These are offline pose fits on
recorded RGB and estimated calibration, not a new simulated trajectory.

The test calls the detector three times on each identical saved image to
exercise repeat behavior. Its reported stability of three is synthetic and
is **not** evidence of three independent observations or camera captures.
Blank, two-patch and six-collinear-patch synthetic inputs do not fit a pose.
However, a deliberately constructed black frame with no box and only six
horizontal magenta three-pixel patches at `(140,369)`, `(227,369)`,
`(156,385)`, `(235,385)`, `(205,398)` and `(242,398)` does fit when enabled;
the original four-pixel gate rejects that input. Extending each patch to
four pixels also fools the original gate. This is an adversarial synthetic
false positive, not an estimate of the natural false-positive rate; it shows
that marker geometry and repeated identical images do not establish a real
box. The three-pixel candidate must not be promoted for release
authorization on this evidence. Independent held-out negative scenes and a
stronger identification strategy remain necessary. No actuator command,
GPU rendering, physical grasp or physical robot test was performed.
