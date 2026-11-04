# Rendered short dock-observation dropout pilot (4 Nov 2026)

In one reused visible-brick simulator case, both arms reached an eligible
settled release yaw and a deliberately injected 10-tick box-detection dropout.
The immediate-stop control stopped on its trigger at tick 14,560 without
lowering or releasing. The bounded-wait candidate triggered at tick 14,860,
then recorded valid detector stability counts 1, 2 and 3 at frame IDs
14,870, 14,880 and 14,890 and issued its retained lowering command at 14,890.
The control and candidate did not have identical timing; asynchronous
mapping can change their trajectories.

An independent simulator-truth manipulation audit found the candidate
released the red block over the box at tick 15,007 and it had settled there
by tick 15,135. The control had no release or settled delivery. This is a
meaningful local liveness result for the injected short dropout, not a
physical grasp, braking, sensor-freshness or safety result. Both clients
recorded zero learned navigation actions, and their client outcome remains
`unverified`. Distinct frame IDs do not establish independent RGB exposures.
The nonfault and 60-tick dropout arms were not run in this pilot; this one
selection case is neither a reliability estimate nor held-out qualification.

The guardian held the shared GPU lock through the monitored run, final audit
and descendant cleanup. Its 219 samples recorded minimum free disk
46,073,925,632 bytes and minimum free GPU memory 9,464,012,800 bytes;
sampling cannot prove exclusivity or rule out short unobserved dips. The
comparison and guardian completed cleanly. An independent post-run review
verified all five top-level and ten coordinator receipt hashes, resource logs,
four supervisor statuses and the 74-file trial inventory; it reran each arm's
mechanism and manipulation checks, and rebuilt all six private simulator
variants byte-identically. The pair-audit entry point requires a live guardian
and was not rerun after exit; the separate arm audits were rerun instead.

The top-level completion SHA-256 is
`3400e61f5d9653b9d39eca637639cd9b6d9e06eb410d54c8d5193e64789e2d57`.
The retained trial is under
`build/flex/sim/levels-v2/pitch82/dock-turn-fault-pilot-monitored-v1/`.
