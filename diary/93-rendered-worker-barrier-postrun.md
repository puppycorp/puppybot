# Rendered worker barrier: saved-trace re-audit (3 Nov 2026)

One rendered selection case ran with the experimental stereo-worker barrier:
two identical disabled-survey controls and one elevated-survey candidate used
the same simulator and client. All three captured the simulated brick at tick
9,098, and none released or delivered it. The high-survey candidate accepted
and settled three arm requests, but still ended with `box not reacquired from
the bounded circular camera search`. This is not a held-out, physical, or
real-time result.

The original `completion.json` and saved trial audit remain censored with
`control_barrier_trace_censored`. Their barrier parser assumed `timeMs` was
exactly `20 * totalSteps`; these traces instead have a constant 1,280 ms clock
offset. The original parser also labels an error on the first row `empty_trace`.
Neither the completion receipt nor the pinned trial output was changed.

A separate read-only postrun audit checks the clock offset on every trace row,
requires consecutive ticks and monotonically increasing simulated time, and
then reuses the original audit with only the barrier parser substituted. It
reproduced the original saved audit and the completed trial inventory before
and after the re-audit. Two separate runs of the corrected analysis produced
identical bytes. The corrected analysis reports that both controls' recorded
journals and outcomes matched, their actor-recorded first 90 actions matched
the candidate, and the two controls applied the same 17 stereo map frames on
the same ticks. The first map frame was 1,621 at tick 1,622, and the last was
7,453 at tick 7,454. Each of the three traces recorded 17 valid map transitions.
Worker submission-to-completion elapsed times were 986–1,035 ms, 984–1,033 ms,
and 976–1,029 ms for baseline, second control, and candidate respectively.
The corrected audit considers this saved comparison eligible for this one
diagnostic, but this postrun conclusion does not replace the original censor or
independently attest actor execution, raw camera-to-actor transformation, or
physical behavior.

Each control recorded 15 survey frames with no fresh rim-patch attention. The
candidate recorded fresh attention in 10 of its 15 frames, each with two
marker components. None of the 45 frames had a valid box pose, and release
staging was never entered. The `visibleCorners` field retained the value 5
from an earlier frame, so it must not be mistaken for a current detection.
All arms rejected 36 circular viewpoints on a combined observed-floor check;
this does not identify a release-staging failure. The previously tested
three-pixel marker relaxation remains unsafe because a synthetic image with no
box fools it (diary 92).

All 36 source hashes in the launch receipt and all ten completion hashes were
verified. All three arm supervisors, the outer supervisor and the final
supervisor exited cleanly. The resource monitor reported passed: its 297 GPU
samples had a minimum 9.431 GiB free and maximum 12% busy; 268 disk samples had
at least 44.265 GiB free. These samples do not establish exclusive GPU use or
exclude transient conditions between samples. Five CPU tests for the corrected
clock parser pass. The barrier intentionally removes worker latency from
simulated time and remains an experimental simulator-only diagnostic; its
cooperative worker deadline still requires external supervision.

Evidence: the untouched run is
`build/flex/sim/levels-v2/pitch82/dock-barrier-rendered-monitored-v1/`;
the separate postrun script and stable saved report are under
`experiments/dock-barrier-postrun-v1/`. The next useful test is to improve
box-view acquisition or marker identification and replay against both the
saved positive images and no-box false-positive controls, then evaluate it
with fresh matched rendered controls before attempting a release.
