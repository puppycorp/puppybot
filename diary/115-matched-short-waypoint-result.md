# Matched short-waypoint trial: fresh box view, no delivery (4 Nov 2026)

The guarded short-waypoint candidate moved closer to the box and subsequently
recorded a fresh stable box detection in one known simulator selection case.
It did **not** release or deliver the brick. Both disabled controls also
captured the simulated brick but made no delivery. The candidate was still
mapping while holding the brick when the 1,499-poll collector limit was
reached; its client recorded `collectorTerminal:false` and a simulated stop
acknowledgment. This is an incomplete episode, not a demonstrated docking
success or a physical braking result.

All three arms used the same copied simulator and client, model and scene,
with high wrist survey, the corrected coarse-footprint guard, stationary
floor retry and experimental stereo-worker barrier enabled. The waypoint
was disabled for two controls and enabled for the candidate. The saved audit
reports matching control journals, matching first 90 actor inputs and actions
across arms, and `comparisonEligible:true`. The saved records do not
independently attest camera provenance or actor execution; the audit keeps
`mechanismEligible:false` because the swept waypoint route was not
independently attested.

The candidate accepted one waypoint plan at tick 22,054 after the two normal
36-viewpoint sweeps. Its recorded path had four primitives. By tick 22,288,
the estimated local pose changed from `[-1.022739, 0.672069]` to
`[-1.068294, 0.434194]` m, a 0.242 m displacement; simulator truth shows a
0.240 m displacement. The simulated gripper still reported the brick held.
This establishes recorded movement in this simulated case, not physical
payload or collision safety.

The copied simulator retained the original four-pixel marker-component
gate. After the move, the trace recorded a valid box view at tick 22,845,
then fresh frames at 22,855 and 22,865 with stability counts 1, 2 and 3.
At the first frame the associated arm was recorded settled at its requested
high-survey pose; the third coincided with entering docking-floor mapping.
The three saved RGB frames have identical SHA-256 bytes, so they are repeated
views and do not independently prove image freshness or three independent
observations. The first saved frame's marker-colour mask contains components
of 7, 7, 7, 6 and 6 pixels at the five recorded marker centres. The original
detector can also be fooled by constructed no-box imagery; this observation
is not proof of robust box identification.

The candidate subsequently recorded 15 release-staging enumerations with
34,560 candidate poses. Every candidate failed the combined observed-floor
check, which conflates unknown floor, observed obstacles and out-of-map
coordinates. No candidate reached drop-clearance or route checks. Each
control recorded zero staging runs and eventually failed box reacquisition.
The candidate recorded 47 stereo-worker map applications versus 33 in each
control. These counters do not establish increased physical clearance or
prove what would happen if given more time; the poll horizon ended during
the candidate's mapping pass.

A separate saved-output re-audit reproduced `trial/audit.json` exactly. All ten
completion hashes, 50 launch source pins and 1,584 inventory entries matched;
all three arm supervisors and the outer and final supervisors exited
cleanly. Resource logs independently verified. Across 644 GPU samples the
minimum free memory was 9.122 GiB and maximum busy was 9%; across 615 disk
samples the minimum free space was 43.752 GiB. Sampling cannot establish GPU
exclusivity or exclude brief unobserved conditions. Worker-barrier waiting is
not charged to simulated time, so this is not a real-time performance result.

Evidence: `build/flex/sim/levels-v2/pitch82/dock-short-waypoint-monitored-v1/`,
including the completion receipt, three traces, saved RGB, manipulation audit
and monitored inventory. This is one reused selection scene, not a held-out
reliability result or a physical pickup, collision-safety, release or delivery
test. No earlier evidence was replaced.
