# Disabled three-action L5 steering diagnostic

This simulator-only draft tests whether a bounded steering perturbation changes
long first-search paths. The observed selection association is confounded by
layout: all 17 treatment games with late virtual consumption but no delivery
started with three `(-0.6, -1.0)` actions, whereas 10 of 12 delivered games
began `(0.6, -1.0)`; those 10 were on one layout. This does not establish that
steering direction caused the difference. The earlier small logit-bias pilot
changed no actions and is not reused.

Both arms use the **same isolated instrumented control binary**. The control
uses `--steer-probe-control`; the intervention uses
`--steer-probe-enabled`. At action one, the fixed trigger is proposed steering
<= -0.5 and speed <= -0.8, with no carry cue. If triggered and enabled, flip
each nonzero proposed steering sign for at most actions 1–3 while preserving
its speed; run policy inference at every step. The intervention permanently
cancels as soon as the existing carry cue appears. The cue comes from virtual
simulator task state, not an independently sensed physical gripper. There is
no runtime teacher or target-coordinate input. This is not a hardware control
or safety proposal.

The isolated hook records each pre-inference image and recurrent-state digest,
raw seven-float32 actor feedback, proposed and applied action float32 bits,
post-action previous-action bits, quantized command, and motor echo. The
saved-data auditor verifies the fixed rule, feedback and recurrent continuity,
command/echo against the simulated trace, paired actor-boundary equality before
first divergence, scene/start bytes and the existing virtual-fetch metrics. The
input and hidden hashes are local journal evidence; they do not authenticate
OS execution, actor computation, camera-to-input conversion, real actuator
motion, or physical braking. Contact input is not independently authenticated.
Both arms retain no-op games in the denominator.

`plan.py` gives 12 fixed draft rows, four scene variants each for layouts 13,
15 and 17, seeds 6800100–6800111, and the prespecified exploratory screen:
at least six intervention activations, at least three more games with first
virtual consumption by action 200, no fewer games with virtual delivery, and
no increase in mostly back-and-forth games. Missing games are censored; the
screen is not promotion. Report the complete per-game data, first-consumption
latency (misses capped at 301), search path, room entry, delivery, contacts,
back-and-forth and cue-triggered cancellation. These are previously used
training-family scene variants; seeds are fixed but not yet proven absent from
recorded historical inventories. Unknown pretrained ancestry remains a limit.
No held-out catalog is used.

`transform.py` only transforms explicitly supplied source text. `prepare.py`
would build a fresh isolated source snapshot and native CPU probe under the
shared pitch82 lock; its CLI is disabled. `test.py` builds a temporary copy of
the control and runs a native CPU hook/logger probe, plus synthetic saved-data
and screen negatives. Six CPU groups passed independent review. No real
build/output, GPU episode or registered plan has been created.

`register.py` and its separate 3,600-second CPU watchdog stage a no-overwrite
frozen plan and seed inventory over explicitly named known training/selection
roots. The scan skips held-out-labelled and symlinked directories and cannot
establish unrecorded history or pretraining ancestry. `runner.py` stages the
fixed 24 arms with 600-second per-arm bounds, full saved-pair re-audits, and
no-op games included. `monitor.py` stages a 19,800-second monitored phase with
an 18,000-second worker bound, followed by a separately supervised 900-second
final re-audit and inventory. The worker budget covers 24 × 600-second arm limits plus 3,600 seconds
for setup, per-arm checks and audits; the monitored phase adds 1,800 seconds
for baseline, registration checks and final saved-data checks. Exceeding any
bound still censors the run. The monitor samples output,
workspace and home disk space, and GPU memory and activity; it cannot prove
exclusive device use or rule out between-sample events. All entrypoints remain
disabled pending review and scheduling.
Even a passed exploratory screen needs L1–L4 checks and a future independent
held-out protocol, which remains disabled.
