# Reproduce prior steering failures (draft)

This fixed **post-hoc debugging plan** reuses exactly the two training-family
cases whose kick trajectories had more than 20% back-and-forth actions:
6800102 on layout 13 variant 2, and 6800107 on layout 15 variant 3. It does
not contain held-out cases and cannot support a generalization or promotion
claim. The three arms (control, kick, kick plus hysteresis) would each use the
same isolated hysteresis-build binary, model, scene, seed and 300-action horizon.
Their trajectories may diverge after an applied action differs.

The previous kick run used a different instrumented controller binary. Its
failure may therefore not reproduce with the new binary; explicitly compare
the matched new kick outcome and actor prefix with the old saved trace before
interpreting any apparent guard effect. A case that does not reproduce is
inconclusive, not evidence that the guard fixed it. Report both cases including
no-op and failed deliveries, guard activation, changed actions, back-and-forth
actions, first virtual consumption, and completed virtual deliveries. There is
no success or promotion threshold for this deliberately selected pair.

`plan.py` supplies a fixed six-arm command design and a read-only preflight
that checks the selected recorded failures, scene bytes, selected model and
simulator hashes, and the candidate controller binary. It does not freeze a
plan, launch a simulator, or attest runtime execution. The runtime symlink chain,
remaining model/kernel inputs and full source pins must also be reverified in a
new registration. A separate reviewed runner and bounded disk/GPU monitor are
required; the existing 12-case runner and its registered outputs must not be
repurposed. Preserve its 32 GiB disk floor and abort or censor unclean arms.
These simulated virtual outcomes do not establish a physical pickup or stop.
