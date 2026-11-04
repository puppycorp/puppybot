# Visual-stall search transfer: censored simulator comparison (3 Nov 2026)

The visual-stall candidate transferred to the simulated search controller
after 49 policy actions. The collector later captured the brick but failed
to reacquire the box and ended while still holding it; no arm released or
delivered the brick. The two disabled controls diverged during collection,
so the matched comparison is **censored** and cannot attribute the candidate
outcome to the transfer. This is one reused training-family scene, not a
held-out test or physical-robot result.

The three arms used the same copied client and simulator, scene, model and
navigation/poll ceilings. The controls disabled the visual transfer; the
candidate enabled it. Their saved navigation journals matched through
observation sequence 50, and their first 49 actor RGB, feedback, recurrent
state and action files matched. The candidate's separately recorded trigger
image also byte-matched each control's actor image at sequence 50.

In the candidate, observation sequences 46–50 at ticks 945–985 had identical
resized-image bytes and nonzero drive echoes `[-60, -60, 63]`. The detector
triggered after action 49. Command 8 at sequence 51 received ACK 8 at tick
987, with zero drive echo and search ownership. Post-run simulator truth
recorded an unchanged pose and `blocked:true` at the five trigger ticks;
the tick-987 response recorded zero/inactive drive. The image records and
timestamps do not independently establish raw-camera freshness or actor
execution. ACK 8 means a simulated ownership transfer, not pickup, delivery
or physical braking.

The disabled-control journals first differed at sequence 117, tick 1,897:
their recorded joint ticks were `[1035,375,3120,2652]` and
`[1035,359,3104,2668]`. The baseline exhausted all 1,499 collector polls at
tick 31,377 without capture and reported `collectorTerminal:false`. The
other disabled control failed after 1,213 polls at tick 25,638 with `collision
guard stopped home parking`, without capture. The candidate captured the
red block at tick 26,865, then failed after 1,410 polls at tick 29,186 with
`box not reacquired from the bounded circular camera search`; it was still
holding the block. An independent simulator-truth manipulation audit recorded
no release or settled delivery in any arm. Terminal ACKs in the two failed
arms are not delivery success.

The audit reports `matchedTriggerFrame:true`, but `comparisonEligible:false`
and `mechanismEligible:false` because of the control divergence. The early
transfer also changes total episode duration relative to the controls; these
records are not an equal-time delivery-rate comparison. The five-frame
threshold was chosen after inspecting a prior failure. Frozen or repeating
camera imagery can trigger while moving, and image noise can hide a stall.
The collector itself uses simulated grasp and containment state.

An independent saved-output re-audit reproduced `trial/audit.json`. The
three arm supervisors and outer and final-inventory supervisors exited
cleanly, the resource monitor passed, all ten completion hashes matched and
the 999-file worker inventory verified. Across 455 GPU samples, minimum free
memory was 9.559 GiB and maximum busy was 8%; across 426 disk samples,
minimum free space was 44.450 GiB. Sampling cannot prove exclusive GPU use
or exclude brief conditions between samples.

Evidence: `build/flex/sim/levels-v2/pitch82/visual-search-matched-monitored-v1/`,
especially `trial/audit.json`, the three protocol journals, actor and trigger
images, manipulation traces and `completion.json`.
