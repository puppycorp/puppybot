# Exploratory kick plus reversal hysteresis (diagnostic only)

This separately versioned simulator-only diagnostic compares three arms using
the same isolated candidate binary: control, the existing three-action kick,
and kick plus one bounded hysteresis attempt. All 12 games in each arm,
including no-op cases, remain in the denominator. The candidate, draft plan,
registration, runner and monitor CLIs are disabled. No plan, build, GPU run or
result is created by invoking those CLIs directly. A separately supervised
three-arm run has been completed; the rule never activated and the kick arms
each recorded 3.33% back-and-forth actions. See
[the results](../../diary/69-l5-steering-hysteresis-results.md). This does not
establish recovery efficacy or promote the intervention.

The rule was frozen before the selection cases: after a kick has
triggered, inspect the previous eight *applied float32 speed actions*. All
must be nonzero, with at least six adjacent sign reversals; post-action local
wheel-odometry displacement must be strictly below 0.15 m and wrapped heading
change strictly below 45 degrees. The rule requires no current contact and no
previous or current carry cue. At most once per episode, keep the last prior
speed sign for at most the next two policy decisions, while preserving each
newly proposed steering value and speed magnitude. A proposed zero stays zero;
the policy runs at every step and receives the actual applied previous action.
Carry permanently disables the attempt, and contact cancels an active attempt.
The sign hold actively commands the held direction; it is not braking or a
safety stop. A tiny nonzero action counts even if motor quantization/deadband
produces zero drive.

The thresholds are a post-hoc hypothesis selected after looking at two prior
training-family trajectories. Both prior qualifying windows have all eight
speeds nonzero and six reversals, but this retrospective match does not show
that changing commands helps or preserves either delivery gain. The new draft
uses layouts 13, 15 and 17, variants 4–7, and seeds 6800200–6800211; those
roles and historical seed non-overlap were checked in the recorded
registration. These are training-family scenes, not held-out.

The gate uses recorded local wheel-drift odometry, applied action history, and
the existing simulated carry/contact feedback, not truth pose, target position
or scene identity. The carry cue is simulator task state, not proof of physical
sensing. The existing client checks response sequence, camera freshness and
drive echoes. Invalid or stale data fail the client and censor the run. The odometry object has no independent
sample timestamp: a replayed pose inside an otherwise fresh simulator response
is not independently detected. An exit does not guarantee a newly acknowledged stop or child cleanup without
the outer supervisor; no hardware stopping guarantee is implied.

The saved-output audit reconstructs the gate and action bits, validates the
actor input/feedback and recurrent-state records, compares the matched kick
and hysteresis actor prefix, and reports per-arm simulator outcomes and no-op
counts. Simulator truth is used only after the run for outcome diagnostics.
Logged source, commands and actor digests are local evidence, not OS/runtime
attestation. The bounded outer monitor has a 27,000-second worker budget
(36 arms × 600 seconds plus 5,400 seconds for checks and audit), a
28,800-second monitored phase and a separate 1,800-second final audit; finite
budgets may censor slow runs. It monitors GPU and disk but cannot prove
exclusive device use.

Before any build, registration or execution, independently review the final
source and CPU tests, verify the historical/scene inventory, and schedule a
fresh dedicated resource-monitored process. In particular, the one-action
fake-peer dispatch parity test uses an explicit test-only horizon relaxation;
it does not establish 300-action, rendered simulator or physical parity.
