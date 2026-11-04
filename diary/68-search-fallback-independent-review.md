# Simulator search fallback: independent trace review

The single matched simulator trial reached the search-only fallback, but did not
capture or deliver the block. This was a previously used selection case, not a
held-out or physical-robot evaluation. The saved comparison reports matching
prefixes across the baseline, disabled candidate and search candidate; each
completed 90 learned navigation actions without an ordinary target handoff.

The enabled candidate requested search-only transfer and received simulator
ACK 8 at tick 1,397, after two stopped ticks. It then received 1,499 collector
poll responses with ACK 4, each advancing 20 ticks. At the configured poll
limit the collector had not returned a terminal ACK: the client issued its
stop request and received ACK 7 at tick 31,377. Thus `collectorTerminal:false`
records poll-limit exhaustion, not a reported collector failure or a completed
pickup. The 29,980 collector ticks represent 599.6 simulated seconds. The
candidate arm supervisor reported a clean 120.401 seconds of wall time; the
outer and final-inventory supervisors also reported clean completion.

At the final recorded tick, discovery remained in phase 3 with reason
`scanning unknown space`. It recorded five scans, 102 images, one remembered
target, one failed frontier and one protective stop; the box was not learned,
no target was selected and pickup was not busy. The first recorded nonzero
remembered-target count was at tick 2,492. A remembered target is not evidence
of capture or of a usable pickup route. The saved manipulation audit reports
no captures, releases or settled deliveries.

Across all 29,981 transfer-and-collector trace rows, `boxLearned` remained
false and `case.selected` remained -1. Recorded dock stability never exceeded
two; dock `valid` was true in 40 tick rows, which are not necessarily distinct
observations. In the archived simulator source, `boxLearned` represents the
home-ready flag, the observation path requires a dock detection with at least
three stable observations to set it, and the collector selection function
returns while it is false. Given the saved trace and source, this home gate
therefore prevented the collector selection path during the recorded search.
This does not show that satisfying it would produce a pickup: the count of
remembered targets does not establish three confirmed sightings, and the
route, mapped floor and arm-feasibility checks would still apply.

The trace narrows the confirmation gap: four distinct dock frame IDs at ticks
11,131, 11,141, 11,151 and 11,161 were recorded during travel with both
wheel commands at +30. Consecutive estimated box positions changed by 2.346,
3.757 and 1.043 mm; the stability count went 1, 2, 1, 2. The archived dock
matcher requires the position change to be strictly below 3 mm, consistent
with the reset at the third frame. Its travel observation caller ignores the
collector's request to hold for confirmation, while the stationary discovery
scan honors that return. This is a source-and-trace explanation of the observed
reset, not proof of why the RGB estimates differed or what a different run
would do.

For post-run context only, the simulator truth pose moved from approximately
(-0.762, 0.029) m at transfer to (-0.429, 0.280) m at the end. Summing adjacent
recorded truth positions after transfer gives approximately 2.358 m of path;
this is not a localization input to the controller or a physical measurement.
The recorded wheel commands were nonzero on 534 of the 29,981 transfer-and-
collector trace rows; zero-command rows include scanning and arm motion.

The search-only acknowledgement does not independently expose the invalidated
handoff camera frame. Recorded action and resized-image evidence does not
attest actor execution or raw-camera provenance. ACK 7 reports a simulated
stop command acknowledgement, not a physical stop or braking guarantee. The
trace and command journal do not establish why the remembered target was not
collected, and this result does not establish that a longer run would succeed.

Evidence: `build/flex/sim/levels-v2/pitch82/physical-search-fallback-monitored-v1/`,
including `trial/audit.json`, `trial/candidate-search/run/result.json`,
`physical-agent.jsonl`, `search-requests.jsonl`, `trace.jsonl` and the saved
supervisor statuses. This review read the existing trace and journals; it did
not rerun the simulator or hash the large trace.
