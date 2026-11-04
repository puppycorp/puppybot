# Elevated dock survey: censored simulator comparison (3 Nov 2026)

The opt-in elevated wrist survey recorded fresh box detections in one known
simulator selection case, but did **not** complete a delivery. The two
disabled controls diverged during collector search, so both the matched
comparison and mechanism comparison are censored. These are within-arm
records, not proof that the elevated pose caused the detections, a held-out
reliability result, or a physical-robot test.

All three arms used the same simulator binary and dock confirmation; the
first two disabled the elevated survey and the third enabled it. Each saved
90 navigation actions followed by search-only ownership transfer. Their 90
actor RGB, feedback, hidden-state and action files match across arms. The
two disabled controls first differed in their journal at sequence 117, tick
1,897, in joint ticks `[1035,374,3119,2653]` versus
`[1035,367,3112,2660]`. This later difference prevents a matched causal
comparison even though the recorded navigation inputs match. Saved records
are local evidence, not independent actor execution or camera attestation.

In the enabled arm the first elevated request was accepted at tick 15,534,
targeting `[1644,249,3020,2975]`, and its recorded settlement was at 15,744.
At ticks 15,745, 15,755 and 15,765, distinct saved frames had valid box
observations with four retained marker components and stability counts 1,
2 and 3. The first two explicitly retained request 1, settled tick 15,744
and `armStillMatching:true`. The third frame coincided with a transition to
observing docking floor: the high-survey request metadata was cleared and
arm mode changed, although the recorded joint ticks and estimated camera
metadata still matched the prior frames. The records support this sequence,
not an independent guarantee that the arm or payload was collision-free.

The enabled arm later accepted request 2 at tick 29,658, targeting
`[1594,249,3020,2975]`, and recorded settlement at 30,128. Frames 30,129,
30,139 and 30,149 had valid observations with five components and stability
1, 2 and 3. The first two explicitly retained request 2 and matching arm
state; the third cleared that metadata on transition to failure. The held
object remained recorded in the simulated gripper. Direct inspection of
representative enabled RGB frames shows a blue box rim with small markers,
partly clipped or occluded by the held block/gripper. Representative disabled
survey frames show floor and the held object but no apparent box rim.
Camera metadata gives the enabled frames an approximately 37° downward
forward direction, compared with approximately 66° for control frames;
these are simulator-local estimated camera poses, not independent
physical-camera calibration.

All three arms recorded one simulated capture and no release or settled
delivery. Both controls ended with `box not reacquired from the bounded
circular camera search`. The enabled arm ended at tick 30,149 with `box
observed but no mapped arm-feasible docking pose found`, after two recorded
refinement entries and no refinement solution. Its diagnostic recorded 36
reason-3 failures for **circular camera-viewpoint plans**. That reason is a
combined clearance category, and these 36 records are not the separate
release-staging candidate reasons. They do not distinguish unknown floor,
obstacles or box-margin constraints, or establish why release planning failed.

An independent saved-output re-audit reconstructed and matched the complete
`trial/audit.json`, including six enabled RGB/metadata pairs and their
camera-viewpoint plan records. All ten completion hashes matched. The
resource monitor passed; all three arm supervisors and the outer and final
inventory supervisors exited cleanly. Across 370 GPU samples the minimum
free memory was 9.532 GiB and maximum busy was 8%; across 341 disk samples
the minimum free disk was 44.384 GiB. Sampling cannot prove exclusivity or
exclude brief conditions between samples. The simulator's arm/gripper guard
is not proof of held-brick or self-collision safety, and a zero command or
simulated stop acknowledgment does not establish physical braking.

Artifacts: `build/flex/sim/levels-v2/pitch82/dock-survey-elevation-monitored-v1/`,
especially `trial/audit.json`, each arm's `run/trace.jsonl`, and the saved
`diagnostic/survey-*.rgb` and camera-viewpoint plan records.
