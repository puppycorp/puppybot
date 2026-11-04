# Bounded contact-recovery contract (not integrated)

This CPU-only state-machine experiment explores an interface to the existing
`progress-guard.flex`; it does not implement or execute a robot recovery. A
caller must first detect a stall, request zero, and provide a fresh zero-command
echo. The gate then permits at most one short policy-proposed action in the
opposite direction, only if an independent sensor supplies fresh, explicitly
direction-specific clearance. It requests another zero immediately after the
action, cancels and reports on contact, stale input, unsafe or missing
clearance, invalid echo or deadline, and keeps its recovery budget until a
separately verified task event. The command magnitude and timing thresholds
are exploratory, not validated safe limits.

**The present policy interface cannot provide that clearance evidence.** It
has forward RGB, prior controls and simulated contact; the experimental
physical client forces contact to zero. The physical policy path supplies no
validated rear-clearance sensor or classifier, while the simulator
collector's floor map is not an onboard policy input. Forward camera images
alone do not establish a clear reverse path. Thus no existing controller should
assert `clear_fresh` or `clear_safe` from these inputs, and this contract
cannot presently authorize a real or simulated corrective action. The existing
physical progress events are also unavailable: virtual consumption and
delivery counters are not verified gripper pickup or release.

The state machine does not send motor commands, implement sensing, stop a
process, produce a durable report, or establish a physical stopping guarantee.
A caller would have to provide and validate all of those, and the caller's
clock must advance on missing responses for timeouts to work. A zero-command
echo does not independently establish that motion ceased. Do not integrate
this into a moving controller until an appropriate sensor, cancellation path
and task-event source are available and validated. When clearance is unknown,
the intended behavior remains the existing stop/report path.

Run the CPU state-machine test with:

```
python3 -B -I experiments/bounded-contact-recovery-v1/test.py
```

The test checks command limits, missing and stale clearance, wrong direction,
contact, stale or nonzero stop echoes, attempt budgets, verified progress and
timeouts. It does not prove sensor accuracy, maneuver safety, enabled/disabled
controller parity, simulator recovery, pickup, delivery or hardware behavior.
