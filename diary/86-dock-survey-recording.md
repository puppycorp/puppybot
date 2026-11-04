# Dock survey recording: camera view and rejected viewpoints (3 Nov 2026)

The rendered simulator recorded the previously studied return-to-box case
with dock confirmation enabled in all three arms and survey recording in the
third. All three arms captured the red block in simulated gripper state, but
none released or delivered it. Each collector ended in failure with `box not
reacquired from the bounded circular camera search`. This is one known
selection scene, not a held-out result or a physical grasp or delivery.

The matched comparison was **censored**: the two recording-disabled controls
first differed at saved journal sequence 117, tick 1,897, in joint encoder
ticks `[1035,375,3120,2652]` versus `[1035,374,3119,2653]`. All 90 actor
RGB, feedback, hidden-state and action files match across the three arms, but
the later control divergence prevents attributing an outcome to recording.
The saved records do not independently attest actor execution or raw-camera
provenance.

The recording arm produced 15 complete 640×480 RGB survey frames and camera
metadata at ticks 15,849–15,889, 15,997–16,037 and 16,201–16,241. Direct
inspection of representative frames at 15,849, 15,997 and 16,201 showed
floor and the held red block/gripper, with no apparent box or rim. The saved
local calibration reported camera forward z = -0.913845, about 66° downward.
Using that locally estimated, rounded calibration and the stale RGB-derived
box centre `(-1.276619, -0.439259)` in the same estimated frame, projecting
the centre at an assumed 0.10 m rim height gives approximate image rows 691,
656 and 687, respectively, below the 480-pixel image. At an assumed 0 m height
the corresponding rows are 617, 582 and 613. These are estimates of the
centre, not independently measured true camera geometry or proof that every
rim marker was outside view. Using the configured 0.0985 m rim height and
four corner offsets, the same local estimate projects corner row ranges of
652–722, 607–695 and 639–724 in those three frames. These are predictions
from the same estimated pose and configured geometry, not independent
observations of the physical box. The survey code aims horizontally toward the
remembered position and considers wrist sweeps around that direction; the
recorded steep optical angle suggests camera elevation is a candidate cause,
not a proven fix.

The search attempted 36 circular-viewpoint plans and recorded all 36 as
reason 3, a combined goal-configuration clearance rejection. The diagnostic
does not distinguish unknown floor, an observed obstacle or the box-margin
check within that category. It recorded zero diagnostic write errors. No
viewpoint move or fresh box reacquisition was established by these records.

An independent full saved-output re-audit matched `trial/audit.json`,
including 15 image/metadata pairs and all 36 candidate records. All ten
recorded completion hashes matched, the resource monitor passed, and outer
and final-inventory supervisors exited cleanly. Across 277 GPU samples,
minimum free GPU memory was 8.826 GiB and maximum busy was 7%; across 248 disk
samples minimum free space was 44.549 GiB. Sampling cannot prove exclusivity
or exclude brief conditions between samples. A simulated stop response and
software state do not establish physical braking.

Evidence: `build/flex/sim/levels-v2/pitch82/dock-survey-diagnostic-monitored-v1/`,
especially `trial/audit.json`, the candidate's `diagnostic/survey-*.rgb` and
metadata, its `search-*-candidate-*.json`, and each arm's saved traces.
