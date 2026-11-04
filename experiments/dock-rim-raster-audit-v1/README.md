# Rim raster audit and CPU replay

`audit.py` accepts raw 640 by 480 RGB frames and reproduces the detector's
colour mask and four-connected component sizes. `recorded-components.json`
contains its results and input SHA-256 digests for the 18 named saved
frames, including single-pixel components. It does not fit box poses or
apply the detector's ray and size gates.

Run `python3 experiments/dock-rim-raster-audit-v1/test.py -v` from the
repository root. It needs the archived clearance build, compiler and saved
frames under `build/flex/` from this experiment history. It copies the
archived simulator into a temporary directory, compiles the actual detector,
and replays saved RGB and their estimated camera calibrations on the CPU.
It also tests synthetic inputs and disabled/default parity with the original
detector. It does not initialize rendering or command a robot.
The tests verify each RGB and camera file against the recorded receipts and
check the archived source, library and compiler against the pinned build
report. Hashes establish consistency with these receipts, not independent
proof of camera provenance or completeness of the captured data.

`transform.py` stages a research candidate only on a copied source tree. The
default is unchanged and `PUPPYBOT_DOCK_SMALL_COMPONENTS=1` opts in to
three-pixel components throughout that candidate simulator. The source
transform deliberately preserves the existing geometric and release gates;
the synthetic false-positive tests show those gates do not establish that a
real box exists. Repeating the same frame in the probe exercises stability
logic but is not independent capture or validation. Do not promote this
candidate for release authorization on the basis of this experiment.

See `diary/92-dock-rim-raster-threshold.md` for the frame-by-frame evidence,
synthetic spoof construction and limits of the censored comparisons.
