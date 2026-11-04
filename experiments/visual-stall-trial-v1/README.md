# Matched visual-stall simulator diagnostic (staged)

This diagnostic revisits the two selected training-family cases in diary
entries 70 and 75. For each, four arms use the same isolated controller,
model, simulator, scene, seed and 300-action horizon:

| Pair | Visual stop disabled | Visual stop enabled |
| --- | --- | --- |
| Normal simulator feedback | `disabled` | `enabled` |
| Synthetic contact-zero ablation | `zero-contact-disabled` | `zero-contact-enabled` |

The ablation validates the simulator contact bit, then forces the controller
and policy contact feedback to zero. Simulator truth and `blocked` remain
unchanged. This artificial input intervention does not establish parity with
physical sensing. Because suppressing a policy input may change a trajectory,
the ablated pair is compared to itself and need not reproduce the prior stall.
The normal disabled arm must reproduce the prior hysteresis trace; each
enabled arm must match its own disabled arm's recorded prefix through its
trigger. No held-out or physical result follows.

The visual stop compares resized camera bytes, without using simulator contact
or truth. Five equal timestamp-valid images across four nonzero wheel-command
intervals request zero drive. The report records the trigger image digest,
timestamp, frame ID and wheel-command echoes before zero. The saved audit
reconstructs the first trigger, checks the matched image and verifies the
subsequent zero action and echo. An interrupted game is marked incomplete and
failed at the original horizon. The zero action advances one additional
simulator action; when triggered at the horizon it is outside the 300 scored
actions. A zero echo is not an independent stop acknowledgement or physical
braking. A trigger at the final observation is censored because there is no
independent matching baseline image digest for it. An enabled game that does
not stop has no saved post-horizon image, so the audit reconstructs its 300
pre-action images only.

Both cases and the threshold were selected after seeing a failure. Exact
equality can miss noisy stalls or falsely flag a frozen camera or repeating
view while moving. Timestamps alone do not prove camera freshness. This
diagnostic cannot estimate field false-stop rates or justify promotion. The
separate stale-response failure-stop prototype is not integrated; error-path
stopping, physical sensing and actual recovery are not tested.

`build-supervisor.py` stages a fresh CPU build under the shared pitch82 lock,
low CPU/I/O priority, bounded worker and disk floors. `trial.py` freezes a new
plan and reuses the GPU/disk monitor, arm supervisors and final inventory with
fresh paths. Direct CLI entry points are disabled. Review the source and tests
before build or execution, use dedicated processes, and run only when the GPU
baseline is available.

CPU checks:

```
python3 -B -I experiments/visual-exact-stall-v1/test.py
python3 -B -I experiments/visual-stall-trial-v1/audit-test.py
python3 -B -I experiments/visual-stall-trial-v1/test.py
python3 -B -I experiments/visual-stall-trial-v1/protocol-test.py
```

The last test needs local socket access, which a restricted sandbox may deny.
It uses the real `ve_receive` path with a synthetic peer reporting contact=1,
checking that the normal arm retains contact and the ablated arm zeros it
without changing wheel feedback. The other tests use a disposable full build,
saved-trace fixtures and a mocked outer launch. They do not run a rendered
simulator, neural policy, full episode or physical robot.
