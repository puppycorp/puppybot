# 42. Progress guard prototype and task-event boundary

_3 Nov 2026, state-machine tests only_

`flex/control/progress-guard.flex` is an isolated, currently unused state
machine for a fetch controller. It accepts verified task progress, sensor
health and a recovery completion acknowledgement. It requests a bounded
external recovery after an idle interval, keeps the attempt budget until a
pickup or delivery, and latches a stop and reason on invalid input, lost
sensors, exhausted attempts, an unacknowledged recovery timeout, or progress
while recovery motion has not been acknowledged stopped. A recovery result
must confirm the motion has stopped, including when it reports failure. The
caller is responsible for cancelling active motion and reporting any stop.
This prototype sends no motor commands and does not implement a recovery
maneuver or a hardware stop.

`flex/tests/visual-control-progress-guard.flex` checks threshold timing,
attempt exhaustion, real progress versus recovery completion, sensor faults,
clock regression, unexpected results, timeouts and acknowledgement races. It
compiled and passed using `build/flex/control/compiler` to a separate `/tmp`
binary; the control build script now also compiles the test. No live simulator
or robot recovery behavior has been tested.

The present chase game does not supply equivalent physical pickup events:
`flex/sim/seek.flex` uses a camera detection and simulator body/base positions
to consume and park an object. It does not perform a physical grasp; the
simulator's return event is a visual docking condition, not a verified gripper
release into a box. `vx_episode` uses those synthetic events for its carrying
cue. Wiring them into a guard would be a simulation-only experiment, not proof
that the same progress signal exists on the robot. Before deploying this
guard, implement and validate a real task-event source, a safe cancellable
recovery executor, and an actual stop/report adapter; evaluate their failures
and false triggers separately from policy delivery scores.

## Opt-in stopped-rescan integration

The experimental **simulator-only** physical client can now set
`PUPPYBOT_PHYSICAL_GUARDED_RESCAN=1`. After its navigation action budget is
exhausted without a handoff, it uses the guard to perform at most two stopped,
fresh RGB checks. Between checks it advances one zero-speed simulation tick;
it does not claim that this is a search maneuver. If a target is detected,
the existing collector may take over; detection and collector termination are
not counted as verified pickup or delivery. If both checks miss, or an
acknowledged rescan takes too many simulator ticks, the guard latches a reason
and the client requests a stop. `result.json` records the attempts, handoff,
readable stop reason and whether the simulator acknowledged that stop. The
guard does not monitor the collector after handoff; the existing collector
poll limit remains separate. Default behavior leaves this option off.

The guard now permits one observation interval after an acknowledged recovery
without treating it as task progress; if verified task progress does not occur,
the attempt budget stays consumed. Native state-machine checks and the
non-GPU `flex/tests/physical-client-rescan-stub.py` socket tests passed for
disabled mode, two missed checks, detection on the second check, simulated
tick deadline, a falsely acknowledged handoff with no tick advance, and
interrupted transport. An accepted guarded handoff must report the two stop
ticks or the client requests a stop and reports a protocol error. Existing
physical-client stub tests also passed. In the interrupted-transport case, the client exits without a
result: stop acknowledgement is unavailable. The sensor/protocol error path
still uses fail-fast process exit, not a proven physical motor stop. None of
these tests verifies rendered simulator behavior, a safe robot recovery
maneuver, a real event source or physical stop acknowledgment.

An independent silent-peer test took approximately 45 seconds to fail with
no result or stop acknowledgment. The four-tick guard deadline only advances
when the simulator replies; it does not bound a stalled stream in wall time.
The simulator-side EOF or process cleanup is not evidence that physical motors
stopped. The opt-in flag is recorded in the client input manifest and result.

A bounded rendered trial then exercised the real experimental client and
simulator on one selection scene with a brick placed behind the starting
robot. After one policy action, neither stopped RGB check saw a target. The
guard reported two attempts exhausted and received a simulated stop-command
acknowledgment. The independent audit verified response sequence
`[0, 1, 2, 1, 2, 7]`, tick increments `[10, 2, 1, 2, 0]`, fresh/still camera,
unchanged arm and zero commanded drive during both checks and final stop. The
supervisor exited successfully in 2.249 seconds without timeout or remaining
workers. Frozen source, model and input manifests, logs and trace are under
`levels-v2/pitch82/physical-guarded-no-target-v1`. This is one simulation
case: the checks are stationary, and neither physical motor stopping nor an
effective search recovery is established.
