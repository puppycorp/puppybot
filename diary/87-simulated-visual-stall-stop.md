# Simulated visual-stall stop with contact ablation (3 Nov 2026)

The opt-in visual stop requested zero drive in both versions of one known
blocked simulator case, including a version where contact feedback to the
controller and policy was forced to zero. It did not trigger in the other
selected case. No arm delivered the brick. These are two post-hoc selected
training-family cases, not a false-stop-rate estimate, held-out reliability
test or physical-robot result.

All eight arms used the same copied controller binary, simulator, model,
scene, seed and 300-action policy horizon within each case. Each case paired
visual stop disabled and enabled under normal feedback and separately paired
the same modes with synthetic contact suppression. The normal disabled arms
reproduced their previously recorded hysteresis trajectories. The ablated
pair is compared only to itself: changing feedback can change the policy's
actions and is not proof of physical sensor parity.

| Seed | Feedback pair | Disabled | Enabled |
| --- | --- | --- | --- |
| 6800102 | Normal | 300 actions, no delivery | 300 actions, no stop or delivery |
| 6800102 | Contact forced to zero | 300 actions, no delivery | 300 actions, no stop or delivery |
| 6800107 | Normal | 300 actions, no delivery | stop after action 147, no delivery |
| 6800107 | Contact forced to zero | 300 actions, no delivery | stop after action 85, no delivery |

For 6800107 with normal feedback, the enabled arm matched its disabled
partner through 147 policy actions. Four saved actor-image digests followed
by the reported triggering image were identical. The trigger observation was
at tick 1,965 and echoed +60/+60 wheel command; action 148 requested zero and
the response at tick 1,975 echoed 0/0. Recorded simulator truth pose remained
unchanged across the repeated-image and zero-command observations.

In the synthetic zero-contact pair, the enabled arm matched its own disabled
partner through action 85. Its repeated-image trigger was at tick 1,345 with
+60/+60 echoed, and action 86 requested zero with a 0/0 echo at tick 1,355.
The simulated truth pose was unchanged across that repeated-image interval,
and the simulator's `blocked` state was true even though the suppressed
policy feedback was zero. This trajectory differed from the normal-feedback
pair; the earlier stop cannot be attributed solely to removing contact
feedback. Both enabled stopped-game results explicitly count the episode as
failed and incomplete. The separate closing stop command was not independently
acknowledged; a simulated command echo is not evidence of physical braking.

The independent saved-output re-audit reconstructed both normal and ablated
pairs, their policy prefixes, image digests, command echoes, summaries and
all eight clean arm-supervisor statuses. The monitor passed; the outer and
final-inventory supervisors exited cleanly. All seven completion hashes and
the 348-file final inventory matched. Among 123 GPU samples, minimum free
memory was 9.061 GiB and maximum busy was 12%; among 94 disk samples, minimum
free space was 44.536 GiB. Sampling cannot prove exclusivity or rule out
brief unobserved conditions.

The five-image threshold was chosen after inspecting a prior failure. A noisy
camera can hide a stall, and frozen or repeating images can look stationary
while the robot moves. The saved resized-image digests do not independently
attest raw camera freshness or policy execution. The prototype stops rather
than attempting recovery; stale or malformed input can still fail before a
confirmed stop or report, and no physical-robot test was performed.

Artifacts: `build/flex/sim/levels-v2/pitch82/visual-stall-trial-v1/` and
`build/flex/sim/levels-v2/pitch82/visual-stall-monitored-v1/`.
