# Real simulator peer fault diagnostic (staged)

This opt-in simulator-only experiment tests the failure-stop code in
`contact-stop-io-failsafe-v1` against a real rendered simulator peer. It uses
one previously examined training-family scene and a deterministic client
probe, not a neural policy or a held-out case. Both arms use the same copied
probe, simulator, scene and commands. The control sends two nonzero drive
actions and then its normal command 3. In the fault arm a relay consumes the
complete second simulator response, changes only the sequence in the header
presented to the probe, and forwards the failure-stop command 3 produced by
the real `ve_receive`/`vc_require` failure path. It does not inject a fault
inside the simulator and does not test a missing or partial response.

The isolated simulator source emits `FAULT_TEST_SIM_STOP_ZERO` to its own log
only after reading command 3, calling its existing `pb_drive_stop`, and finding
zero left/right drive and inactive status. A matched result requires that
marker, a validated nonzero first drive response, a matching recorded control
prefix and clean simulator exit. It also requires the client to report an
invalid response and an unverified failure-stop request. The simulator marker
is local instrumented evidence of a software state transition, not an
independent motor sensor, physical braking, a stop acknowledgment, or proof of
future stationarity. The separate Python supervisor owns the simulator child;
the probe does not test the production controller's parent-death behavior.

The relay records only selected response fields and the first valid decision;
it does not independently attest OS execution or camera-to-policy computation.
An unmatched prefix, missing marker, nonzero final drive, process failure,
timeout or monitor failure censors the experiment. The probe never calls the
complete `vx_episode` loop, and this experiment makes no claim about delivery,
policy quality, recovery, or error paths outside the injected bad sequence.

`build-supervisor.py` stages a fresh copied build under the existing shared
lock, low CPU/I/O priority and disk floors. `experiment.py` freezes a separate
input manifest and reuses the existing GPU baseline, live disk/VRAM monitor,
outer process-tree supervisor, per-arm watchdog and final inventory. Its
direct CLI is disabled. The supervised CPU build completed with an
`isolated_build_only` receipt and clean child exit. A fresh dedicated process
must call `experiment.freeze`, then another dedicated process must call
`experiment.launch`, only after independent review and GPU scheduling. The
experiment plan has not been frozen, and the rendered trial has not been
launched. The 32 GiB final disk floor and 36/34 GiB preflight/active floors
are preserved.

CPU checks:

```
python3 -B -I experiments/sim-fault-real-peer-v1/test.py
```

The test compiles the copied simulator and the real-environment probe, then
uses a synthetic socket simulator to exercise both relay arms, prefix audit,
and missing-marker rejection. It does not run the real simulator or GPU and
requires local socket access outside a network-restricted sandbox.
