# Disabled simulated nonzero-command stop prototype

This isolated v3 extends the v2 simulator-only proxy. It does not modify v1,
v2 or the physical client used by other experiments. Its command-line launch
entry points are disabled. No rendered v3 experiment has been run.

A no-fault control must finish cleanly and contain at least one fully validated
drive response with nonzero left or right command echo. Its complete protocol,
session, outer status and recorded actor files are hashed at the control gate
and checked again before and after the fault and by the standalone auditor.
Without such a control the outcome is censored and no fault arm starts.

In the fault arm, the supervisor kills the client immediately after recording
the first complete validated nonzero drive response, using a pidfd and waiting
for exit. It then sends the stop command at the next sequence number. The
auditor independently replays both protocols, requires every request and full
response through the triggering drive to match, compares saved actor input and
action files through that point, and validates the simulated stop ACK, zero
drive echo and unchanged tick. Prefix or actor mismatch is censored. Invalid,
missing, partial or late peer responses cannot be credited as a stop, and no
new stop is guessed while a peer transaction is ambiguous. Commands of either
sign qualify; steering alone does not.

The planned protocol permits ten navigation actions and one collector poll,
with a 25-second first-request deadline, five-second subsequent I/O deadline,
60-second arm wall limit, resource monitoring and no-overwrite output. The
case, model and simulator are caller-supplied and pinned before the pair. A
previous hidden-selection case and model produced nonzero reverse commands,
but that historical result does not guarantee this prototype will encounter
one; an initial RGB detector miss does not prove geometric invisibility.

The files and peer acknowledgments are local evidence. Even a matched result
does not independently authenticate camera-to-actor processing, policy
execution or actual simulator displacement. A nonzero command echo followed
by a simulated zero-drive ACK is not evidence of physical braking, a physical
stop, recovery or delivery. An independent physical stop mechanism and
watchdog would be needed on hardware. CPU fixtures use fake simulator and
policy peers and make no GPU, rendered-scene or hardware claim.

Independent source review found no material blocker within this scope. Both
reviewers reran the 14 proxy and 14 launcher CPU groups at low priority; the
author's 11 copied-client/auditor groups also passed. The independent review
did not repeat the copied-client builds during the active selection.
