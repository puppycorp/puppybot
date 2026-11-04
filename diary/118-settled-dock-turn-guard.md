# Guarding the release-arm turn after it settles (4 Nov 2026)

The stale-turn reproduction in [diary 117](117-docking-floor-and-stale-turn-audit.md)
showed that the simulator can command a retained lowering target after the
box observation expires during an already-authorized yaw turn. That command
does not itself open the gripper. The first private guard stopped immediately
on stale or changed vision, even while the turn was still in progress.

A separate opt-in source transform now places the guard **after** the
existing arm-settlement check in `ps_case_drop_turn_update`. The already
authorized yaw is allowed to finish while an observation is stale, unstable
or changed. Once settled, camera mode requires a fresh, stable observation
of an unchanged box before issuing the retained lowering target. Otherwise,
the case fails using its existing stop path. Loss of the held object still
fails immediately, even during the turn. Non-camera mode retains its
previous behavior.

The private native A/B test at
`experiments/dock-turn-settled-guard-v1/test.py` compiled both the original
and guarded copies and passed. It checks stale and changed views while the
arm is unsettled, invalid or expired, unstable and changed views after
settlement, fresh stable unchanged views, non-camera mode and lost payload.
It also verifies the existing sampling order: on a scheduled sampling tick,
the camera sample precedes the turn branch; a simulated refreshed detection
permits lowering, whereas an invalidated detection blocks it. An invalid
sample can recover at a subsequent scheduled sample while the arm is still
turning. Other ticks do not request an extra sample in this branch.

The guard's failure path calls the real modeled `pr_stop`, and the test
checks cleared modeled joint targets and speeds, stopped drive state and
no gripper-open command. The probe stubs camera sampling, arm settlement,
the gripper command and actuator application. It does not demonstrate camera
freshness, arm stopping or payload retention on physical hardware. Allowing
the existing yaw to finish also means this candidate does not claim an
immediate stop when vision is lost mid-turn. Short camera loss near
settlement can still cause a terminal failure if no fresh stable detection
is available on the relevant sampling schedule.

The guard does not wait for another camera sample after settlement: an
invalid, expired, unstable or changed observation on the first settled tick
fails immediately, even if another scheduled sample might later recover.
That is a conservative completion tradeoff. A follow-up native regression
also held the arm permanently unsettled in both original and guarded copies.
Both reached the existing drop-stage step timeout, failed the case and
called the modeled stop with no new lowering or gripper-open command. The
test uses an artificially short timeout and mocked settlement, so it does
not establish a real-time hardware deadline or physical stop.

The candidate and tests are in `experiments/dock-turn-settled-guard-v1/`.
After independent source review and a repeat of the native probe, the same
guard was applied to `flex/sim/case.flex`; the full worktree simulator
compiled to a temporary binary, and the probe passed again. Existing simulator
binaries, archived trial sources and training inputs were not replaced. The
guard still needs rendered validation; no physical validation or GPU trial of
this change has been performed.
