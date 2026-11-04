# Simulated sustained-contact stop: matched trial (3 Nov 2026)

The opt-in contact stop requested zero drive in the previously observed
blocked simulator trajectory and recorded the episode as incomplete and
failed. In the other selected case it did not activate. Neither case
delivered the brick in any arm. These two training-family cases were selected
after inspecting their failures, so this is a debugging result, not a
held-out reliability measurement or a physical-robot test.

All four arms used the same isolated controller binary, model, simulator,
scene and seed within each case, with a 300-action policy horizon. Each
case compared the contact stop disabled and enabled, on top of the same
experimental steering kick and hysteresis. The disabled arms reproduced the
previously saved hysteresis trajectories. In seed 6800102 both arms ran all
300 actions, with no stop and no virtual delivery. Their saved decisions,
steering and hysteresis records matched throughout. In seed 6800107 the
enabled arm matched the disabled arm through 146 policy actions, then
requested zero; neither arm delivered.

For seed 6800107 the simulator reported contact on the responses to policy
actions 144, 145 and 146, at ticks 1,935, 1,945 and 1,955. Those actions
each commanded forward speed with wheel echo +60/+60; the recorded simulator
truth pose remained unchanged from action 143 onward. The guard latched
`sustained_contact` after the third response and sent action 147 as `[0, 0]`.
The response at tick 1,965 echoed zero for both wheels and centered steering.
The report records `triggerAfterActions:146`, `observedActions:147`, one
zero action, `zeroCommandEchoObserved:true` and
`stopCommandAcknowledged:false`. The zero action advances ten simulated
ticks; the pose also remained unchanged in that response.

The stopped game's result records `countAsFailedGame:true` and
`fullHorizonCompleted:false`; its run summary records `complete:false` and
one stopped episode. The enabled 6800102 summary records zero stopped
episodes and `complete:true`. The disabled summaries do not include
contact-stop fields. A partial episode remains a failed game when evaluated
against the original horizon; these results are not a comparison of delivery
rates or a measurement of physical braking.

An independent saved-output re-audit matched the recorded two-pair report,
checked the archived and current initial states and scene inputs, the complete
disabled runs, enabled action prefixes and zero echo, all four intended
commands and clean supervisor receipts. The monitor passed; the outer and
final-inventory supervisors exited cleanly, the final inventory was verified,
and all seven recorded completion hashes matched. Minimum sampled free GPU
memory was 9.065 GiB and free disk was 45.598 GiB. Sampling cannot prove GPU
exclusivity or exclude brief changes between samples; the logs do not
independently attest execution or neural computation.

The echo confirms a simulated command response, not an independently
acknowledged stop or physical braking. The prototype performs no recovery
motion. Malformed or stale driving responses can exit before it requests zero,
and the experimental physical client currently forces contact feedback to
zero. Thus stop-and-report on actual hardware, error-path stopping and recovery
remain unproven.

Artifacts: `build/flex/sim/levels-v2/pitch82/contact-stop-trial-v2/`,
`build/flex/sim/levels-v2/pitch82/contact-stop-monitored-v2/` and
`experiments/contact-stop-trial-v1/`.
