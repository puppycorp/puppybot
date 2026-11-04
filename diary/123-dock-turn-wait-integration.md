# Simulator dock-turn observation wait integrated (4 Nov 2026)

The bounded wait from [entry 122](122-dock-turn-reacquisition.md) is now
integrated into the current simulator source. When an already-authorized arm
yaw settles without a fresh, stable box observation, the simulator waits up
to 50 simulated ticks while the existing detector samples the box. It issues
no new lowering or gripper-open command during the wait. A lost payload,
confirmed changed box, nonadvancing or backward tick, or expired deadline
fails the case and requests the existing simulated stop. The existing phase
timeout can stop earlier. The wait state is reset for each new drop target,
on case reset, and before a successful lowering command.

The exact current-source baseline and integrated source both compile as full
private simulator copies. The native A/B state-machine probe in
`experiments/dock-turn-reacquire-current-v1/test.py` passes; it exercises
reacquisition, timeouts, changed box, payload loss, settlement flapping, clock
faults, reset and later release checks. An independent review repeated the
test and checked the simulator's once-per-tick update schedule. The probe
uses sensor and actuator stubs. A camera capture failure can leave the
detector stability count intact, and repeated identical frames can also
increase it: three accepted detections do not prove three consecutive or
independent sensor exposures.

This source integration does not replace the shared simulator binary used by
the selection run. It does not establish a successful rendered delivery,
physical stop, payload retention or safe hardware operation. The original
authorized yaw continues until settlement; this wait is not a wall-clock
watchdog. Controlled rendered and physical tests remain necessary.
