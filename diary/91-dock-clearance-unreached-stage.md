# Dock-clearance diagnostic: staging not reached (3 Nov 2026)

The rendered clearance diagnostic did not reach the release-staging
enumeration. In all three simulated arms, the collector captured the brick
and ended without releasing or delivering it. The candidate's final reason
was `box not reacquired from the bounded circular camera search`. Both
matched and mechanism comparisons are censored because the two controls
diverged during collector search. This was one previously used selection
scene, not a held-out or physical-robot result.

All arms used the same instrumented simulator binary; the first two disabled
the elevated survey and the third enabled it. Their 90 recorded actor RGB,
feedback, hidden-state and action files match across arms. The first saved
journal difference between the controls was sequence 117, tick 1,897, in
joint ticks `[1035,372,3118,2654]` versus `[1035,359,3104,2668]`. Thus the
saved comparison does not establish a causal effect of the elevation flag.
Recorded inputs and hashes are not independent proof of actor execution or
raw-camera provenance.

The enabled arm accepted three elevated survey requests and recorded them
settled at ticks 15,724, 15,872 and 16,076. It recorded five survey frames
after each settlement. Across all 15 frames the dock detector reported no
fresh valid pose and a stability count of zero. The first five retained one
current marker each; the other ten retained none. Its cached frame ID 11,141
was an earlier discovery observation, not a fresh survey detection: the
trace had recorded seven stable observations at 11,141, then marked the pose
invalid at 11,151, before capture at 13,745. Direct inspection of the first
survey RGB shows the held red brick/gripper and a clipped blue box edge; it
does not establish that a complete rim was visible or why detection failed.

At tick 16,126 the enabled collector attempted all 36 **circular camera
viewpoint** plans in one tick and then failed; it did not visit those 36
viewpoints. Their planner records all had reason 3, with detail 2 indicating
that the existing observed-floor clearance check rejected the proposed goal.
That check combines unknown floor, observed obstacles and positions outside
the map; this diagnostic cannot separate those causes. The two disabled
controls likewise recorded 36 viewpoint plans rejected by the same first
check, but the censored comparison does not attribute their outcomes to the
candidate or its diagnostic writes.

The separate **release-staging** counters in all three arms remained at
`stageRuns:0` and `stageCandidates:0`, with zero drop-clearance and route
checks. At the enabled arm's failure, fresh dock validity was false and
stability was zero; the existing staging path requires a fresh stable dock
observation. The zero counts therefore mean staging was not entered. They do
not mean that all release poses passed, that none were rejected, or that the
36 viewpoint rejections explain a release-staging failure in the earlier
elevated-survey run.

An independent full saved-output re-audit matched `trial/audit.json`,
including the diagnostic image, viewpoint and clearance-counter checks.
All ten completion hashes matched; the resource monitor passed, and all
three arm supervisors plus the outer and final-inventory supervisors exited
cleanly. Across 319 GPU samples minimum free memory was 9.488 GiB and
maximum busy was 9%; across 290 disk samples minimum free disk was 44.337
GiB. Sampling cannot prove exclusivity or exclude brief conditions between
samples. Simulated capture and command acknowledgment do not establish a
physical grasp, release, delivery or braking guarantee.

Evidence: `build/flex/sim/levels-v2/pitch82/dock-clearance-monitored-v1/`,
especially `trial/audit.json`, each arm's `run/trace.jsonl`, and the
`diagnostic/survey-*.rgb` and `search-*-candidate-*.json` records.
