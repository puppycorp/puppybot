# Bounded observation wait after a dock turn (4 Nov 2026)

The private settled-only guard in [diary 118](118-settled-dock-turn-guard.md)
fails immediately when the box is not visible at the first settled tick. A
separate private-copy candidate explores a bounded wait for the existing
detector instead. It leaves the previously authorized yaw alone until the
arm settles; it does not issue another lowering or gripper-open command while
waiting. It fails on payload loss, or on a fresh stable box estimate that
differs from the saved drop frame.

When the arm has settled without fresh stable vision, the candidate starts
one 50-simulator-tick deadline and clears the detector's stability count.
The normal scheduled camera samples must rebuild that count to at least
three, with the latest accepted observation from the wait period and an
unchanged box, before the retained lowering target can be issued. The wait
remains bounded if the arm later becomes unsettled again. A nonadvancing or
backward simulation tick fails closed. The deadline is strict: even a
qualifying sample at exactly tick 50 is too late. The pre-existing drop-phase
timeout still applies and can stop earlier. At the simulator's 20 ms per tick,
50 ticks represent one second of simulated time; this is not a wall-clock
watchdog or physical safety guarantee.

The wait state resets on a new drop-target request, on episode reset and
before a successful lowering command. Non-camera behavior is unchanged. The
normal stage-eight release checks still require fresh, stable, unchanged
vision after lowering; a stale observation cannot itself open the gripper.
The candidate uses the original detector's stability semantics. Three
consistent detections are not evidence of three independent RGB exposures:
the earlier trial retained identical image bytes for multiple detections.

`experiments/dock-turn-reacquire-v1/transform.py` applies the candidate only
to a copied simulator. `test.py` compiles both unmodified-dependency simulator
copies and compares the immediate-stop and wait variants in a native probe.
The probe covers scheduled samples, the three-count recovery, unchanged and
changed targets, no commands while waiting, loss, exact and early timeouts,
settlement flapping, clock faults, reset, non-camera mode and the subsequent
release guard. It injects synthetic pose detections into the real detector
stability update and stubs camera sampling, arm settlement and actuator
application. The real modeled failure path stops modeled joint targets and
drive, but these tests do not validate real RGB perception, independent
frames, a physical stop or payload retention. No active simulator or
training-pinned source was changed and no GPU experiment was launched.

This is a safety/liveness hypothesis for review, not evidence of a completed
delivery. It needs independent review and a controlled rendered evaluation
before drawing a conclusion about the robot's behavior.
