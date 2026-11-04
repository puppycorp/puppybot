# Simulated stop after an invalid response sequence (3 Nov 2026)

An isolated simulator fault diagnostic recorded a command-3 stop after the
client received a deliberately altered response sequence while simulated
drive was nonzero. The instrumented simulator logged its zero-drive marker
after handling that command. This is simulator software-state evidence, not
an independently acknowledged stop, physical braking, an autonomous recovery
or a pickup and delivery. The deterministic client probe is not the learned
policy and does not run the full fetch episode.

Both arms used the same copied simulator, probe and previously studied scene.
In each arm the relay recorded reset command 1, two forward command-2 actions
with speed 500, and command 3 at sequence 4. The first three simulator
responses were at ticks 495, 505 and 515. Both drive responses echoed left
and right speed 30 with steering 90. The saved first validated decision and
the reset/drive requests match between arms.

In the fault arm, the relay first consumed the complete real second drive
response for sequence 3, then sent a client-facing header bearing sequence
4 instead. The probe rejected that response, sent a command-3 request at
sequence 4 and exited with code 1. Its log explicitly says the stop is
unverified and that child exit was not observed during its bounded wait. The
separately supervised simulator subsequently exited with code 0 and its
instrumented log contained exactly one `FAULT_TEST_SIM_STOP_ZERO` marker;
the control simulator also logged one marker and exited cleanly. The fault
hook's stop request had zero hold/task fields; the ordinary control stop
retained the normal hold and task fields. No separate command-3 acknowledgment
or post-stop physical motion measurement was recorded.

This particular relay drained the complete response before corrupting its
header. It does not exercise a partially written request, partial or missing
response, blocked stream, hard kill, neural policy or actual robot hardware.
The marker is written by modified simulator code after its existing stop call
and zero/inactive state check; the saved log is not an independent motor
sensor or execution attestation.

An independent saved-output re-audit verified the registered input manifest,
reconstructed the report and checked both clean arm-supervisor statuses.
The monitor passed, its outer and final-inventory supervisors exited cleanly,
all five recorded monitor-snapshot hashes and the evidence/final-status
hashes matched, and the final 16-file output inventory matched. The 38 GPU
samples recorded at least 9.144 GiB free and at most 6% busy; the minimum
sampled free disk across nine records was 44.590 GiB. Sampling does not prove
GPU exclusivity or exclude brief changes between samples.

Artifacts: `build/flex/sim/levels-v2/pitch82/sim-fault-real-peer-trial-v1/`
and `build/flex/sim/levels-v2/pitch82/sim-fault-real-peer-monitor-v1/`.
