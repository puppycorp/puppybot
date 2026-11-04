# Frozen simulated visual-stop validation

`prepare-sim-visual-validation.py PILOT NEW_INPUT_DIRECTORY` prepares inputs
only. It derives nine predeclared heading/appearance variants from the
completed pilot apartment and copies three predeclared existing training-room
cases. The natural, uniform-color and striped descriptions are design
intentions; the rendered actor images and post-run trace must establish whether
any case actually covers low texture, repeating imagery, moving or stationary
behavior. The stripe panel is visual-only geometry and has no collision body.
It cannot establish clearance or physical obstruction.

The v3 frozen matrix is in
`build/flex/sim/levels-v2/pitch82/visual-stop-validation-inputs-v3`. The
previous v1 and v2 matrices remain unchanged. All twelve cases use the exact
pilot client, simulator and model, with disabled/enabled arms differing by the
visual-stop environment flag. The generation step and CPU tests do not run a
simulator or GPU. These are selection scenes, not held-out qualification.

After independent review and an idle-GPU/disk check,
`run-sim-visual-validation.py PILOT MATRIX NEW_OUTPUT` supervises each arm for
at most 300 seconds. Twelve pairs have a 120-minute total watchdog ceiling,
plus setup and auditing. It refuses existing output, pins the original
executables, model, scene assets, archived source and runtime inputs, and
retains partial results and a censored audit if an arm fails. The lock is
cooperative; it does not itself establish that the GPU is idle.

The post-run auditor labels each eligible disabled-arm window using simulation
truth: stationary if every tick stays within 1 cm and 2 degrees of the first
pose; moving if any tick reaches 5 cm or 10 degrees; ambiguous otherwise.
These thresholds are fixed before the suite. The pose is never fed to the
actor. Stationary is not a collision or obstruction claim. Windows that lack
continuous non-deadband drive or valid timing are ineligible. Initial-camera detection or zero policy actions in either arm, collector handoff,
missing runs, timeout and failed process cleanup are censored. Actor or
protocol-prefix differences and a missing or different stop-trigger image are
also censored; none contributes matched success or negative counts. The
initial simulator poses must match the pinned scene spawn and one another
within 1 cm and 1 degree. The
retrospective disabled-arm windows do not imply that every later window would
have occurred in the enabled arm after an early stop.

For each game the report separates moving visual suspicions, stationary
windows without suspicion, moving and stationary low-texture abstentions,
ambiguous windows, actual enabled stop reasons and audit failures. It preserves
all overlapping windows and also provides per-game counts: windows from one
game are correlated. A simple horizontal image-shift score documents whether
the rendered actor image shows repeating pixels; it cannot establish that
robot motion causes aliasing. Retrospective stable-pose delay is measured in
simulated ticks from available trace data, not wall-clock or contact onset.

A simulated zero-command acknowledgment is not physical motor feedback.
Transport, stale-image, timeout or acknowledgment failure leaves physical or
simulated stopping unverified. No automatic turn or reverse is performed.

## v3 room failure and v4 case plan

The v3 suite did not complete: `room-13` used the original training case's
`rgb-find-return` controller. In the archived simulator this sets the seek
flag, which conflicts with `--agent-physical`. The remaining two copied room
cases use the same incompatible controller. The partial v3 output and its
censoring are retained; they are not combined with a later run.

`visual-stop-validation-inputs-v4` is a separate, predeclared plan. Its three
room case copies use `rgb-discovery`, matching the simulator's physical-agent
mode. Every other parsed case field, all room environment bytes and all nine
apartment case/environment files are unchanged from v3. This changes the case
controller's semantics; it does not establish equivalence to the original
virtual find-return task.

A CPU-only shim compiled from the archived simulator source exercised its
actual case/environment parsers and pre-render `ps_reset`, using the pilot's
pinned robot asset. All 12 v4 conditions were accepted; a separate test that
moved the spawn into a real room partition was rejected by that reset. The
sidecar `visual-stop-validation-inputs-v4-reset-report.json` preserves those
checks. The shim never initialized graphics, started the policy or called the
case controller; rendered startup, camera observations, task results and real
hardware remain unverified. The v3 runner does not accept v4.

A separate metadata verifier checks every inherited family, heading, layout,
scene hash and other original row field against v3, verifies that the room
case changed only in its controller field, and binds the frozen CPU reset
report to its recorded sources and robot asset. This prevents a corrected
case from silently receiving the wrong scene label; it does not authenticate
an untrusted report or establish a rendered run.

## Staged v4 launch path

The separately named `sim-visual-v4-smoke.py` and
`run-sim-visual-validation-v4.py` entrypoints are **hard-disabled pending
independent review**. The proposed smoke supervises room 13 for at most one
policy action and one collector poll, with a 120-second process-group and
subreaper watchdog. It requires a fresh camera observation, one acknowledged
policy command, a matching pre-render spawn pose and a final simulated
zero-drive acknowledgment. Failure or an initial handoff leaves the smoke
unverified. It does not establish a successful search or task.

The proposed full runner revalidates the original v3 pilot and metadata,
repeats all 12 archived CPU reset checks, requires independently re-audited
and pinned smoke evidence, and retains the original 300-second-per-arm
watchdog and censoring. Its separate auditor applies the same v3 observation,
trigger-frame and eligibility checks to the v4 discovery cases. The prior v3
partial audit is not combined with this separate plan. Both scripts must stay
disabled until reviewed; an idle-GPU and fresh disk check are still required
before any authorized launch.

Independent review of the staged v4 path found no remaining blocker to a
**smoke-only** scheduling decision. The focused CPU checks passed: 9 v4
launcher/auditor tests, 4 metadata tests and 5 case/reset tests. The launcher
entrypoints remain hard-disabled until a real GPU scheduling decision. The
full 24-arm suite still requires a successful independently re-audited
rendered smoke and its own scheduling decision. Nine v4 apartment conditions
were already observed in the partial v3 run; neither they nor the three
corrected room cases constitute fresh held-out evidence. No v4 rendered smoke
or full v4 run has been performed.
