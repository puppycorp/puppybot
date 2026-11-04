# Monitored v4 rendered startup smoke

3 November 2026: the independently audited `room-13` smoke observed a fresh
rendered simulated startup, **one policy action out of the one permitted**, and
an acknowledged simulated stop. There was no handoff, and the outcome remains
`unverified`; this is not a completed search, pickup, delivery or physical
robot test. Visual stopping and stopped rescan were disabled. The existing
`sim-visual-v4-smoke.py` auditor was rerun against the pinned
`physical-visual-stop-pair-v1` pilot and `visual-stop-validation-inputs-v4`
matrix and returned `simulated_rendered_startup_observed`.

The outer supervisor exited 0 in 49.142 s; the inner smoke supervisor exited 0
in 7.789 s. Neither reported a timeout, signal or residual-worker cleanup. The
monitor recorded 51 samples: 31 baseline samples over 30.000 s, 19 while the
smoke worker ran, and one after it exited. Baseline GPU busy was 3% in 31/31
samples; smoke samples ranged 3–6% in 19/19. Baseline minimum nominal free VRAM
was 9,291,796,480 bytes (8.654 GiB); minimum during smoke was 8,935,596,032
bytes (8.322 GiB). No telemetry error was recorded. Sampling can miss short
peaks and device-wide utilization does not measure Kennel service latency or
identify which process used the GPU.

After the smoke, host `fuser` reported the unrelated `kennel` PID 2499981 still
holding `/dev/kfd`; this confirms its process and open device, not its health,
responsiveness or lack of interference. The saved outputs are under
`build/flex/sim/levels-v2/pitch82/physical-visual-v4-monitored-smoke-v1`.
This is one room and one action, not evidence for the other eleven v4
conditions, full rollout VRAM peaks, held-out performance, camera authenticity,
or actual GPU runtime identity. The heading pilot has a different collection
path and model, so its resource use needs separate monitoring.
