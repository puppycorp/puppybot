# Simulator diagnostics prepared while GPU busy (3 Nov 2026)

Three isolated simulator diagnostics were built after their CPU tests and
independent review. None has run against a rendered simulator, and none
establishes physical robot behavior or held-out performance. GPU utilization
remained above the existing 10% baseline gate during preparation; the earlier
fresh-policy run stopped in its baseline before any games. Disk headroom was
approximately 44 GiB, so the existing disk floors remain in force.

The dock-survey build records wrist RGB, local camera calibration and
per-candidate route-plan outcomes for the search failure in entry 72. Review
found that missing candidate files could go unnoticed, so the trace now
records the number of planned candidates and the audit checks the count,
unique identities, write errors and consistency of outcomes. Both diagnostic
and trial CPU suites passed six tests each. The clearance rejection category
still combines several possible causes, and synchronous recording can alter
the simulated trajectory.

The real-peer fault probe uses the existing failure-stop client functions and
a relay to inject an invalid response sequence after nonzero simulated drive.
Its copied simulator logs a marker only after its command-3 handler requests
zero drive. Review found that the saved audit did not independently verify
the nonzero drive and full request sequence; the audit now checks these and
rejects altered or missing evidence. Two CPU socket tests passed. A future
marker would demonstrate an instrumented simulator software state, not a
hardware stop or physical braking.

The visual-stall controller compares validated resized image bytes and
requests zero after five equal images across four nonzero drive intervals.
The threshold is retrospective: entry 75 found the repeated image only in
one known blocked trajectory and its replay, among 70 correlated saved game
streams. Review required blackout to be rejected and a complete expected
stream inventory. Its staged episode test compares enabled and disabled
arms in two selected cases, with separate synthetic zero-contact pairs; this
ablation can change the policy trajectory and is not physical sensor parity.
The audit reconstructs the complete disabled baseline's action, feedback
and hysteresis history, and compares each enabled prefix against it. A
trigger at the final horizon is censored when no independent baseline image
digest exists. Six prototype tests, six saved-audit tests, three build and
launch tests, and one synthetic socket ablation test passed. Exact image
equality can miss noisy stalls or stop on a frozen or repeating camera view.

The supervised CPU builds reported `isolated_build_only` and clean child
exit in `dock-survey-diagnostic-build-cpu-monitor-v1`,
`sim-fault-real-peer-build-monitor-v1`, and
`visual-stall-build-cpu-monitor-v1` under
`build/flex/sim/levels-v2/pitch82/`. These builds do not establish the
behavior of their planned real-peer or full-episode trials. Each rendered
trial still requires its own fixed inputs, resource monitor and saved-output
audit when the GPU is available.
