# 63. Simulated stop after a nonzero drive command (3 Nov 2026)

The separately reviewed v3 stop pilot completed one matched pair in the
rendered simulator, using the saved hidden-selection case, model and simulator.
It is a diagnostic of the simulated command protocol, not a physical robot
test. The no-fault arm ran ten policy actions and issued its own final stop;
the fault arm deliberately killed the client after the first fully validated
nonzero drive response. Both arms used the same pinned inputs and their raw
protocol and saved actor-file prefixes matched through that response.

Independent replay of the saved protocol reproduces `audit.json`. The common
reset was sequence 1 at simulator tick 495. Drive sequence 2 requested steering
-600 and speed -1000 for ten ticks; its response at tick 505 echoed drive
`[-60, -60, 63]`. The fault journal records the deliberate client kill, then a
supervisor stop request at sequence 3. The peer replied with owner 2, ACK 7 and
`[0, 0, 90]` at the same tick 505. The no-fault client later stopped at
sequence 12, tick 595. The fault client's `-9` exit was the predeclared kill;
the simulator exited zero. This is a simulated acknowledgment, not proof of a
physical motor stop.

As a separate post-run check, the saved simulator-truth traces in both arms
have consecutive finite poses for ticks 495–505. Those poses show approximately
0.060 m travelled and 0.05993 m net horizontal displacement during the
commanded interval. This truth was not supplied to the actor or supervisor.
The fault trace ends at tick 505, the stop-ACK tick, so it contains no later
simulation ticks with which to assess coasting, braking distance or continued
stationarity. The actor files and command echoes are local saved evidence; they
do not independently authenticate the camera-to-actor transformation, policy
execution, OS-loaded code, or physical behavior.

The outer and both per-arm supervisor records report clean exits, no timeout or
signal and no remaining workers terminated. Their wall times were 38.374 s
outer, 3.432 s control and 2.148 s fault. Thirty-one GPU baseline samples span
30.000 s, with minimum free VRAM 7.362 GiB and maximum sampled busy 3%; the
minimum during the two arms was 6.999 GiB and the final sample was 7.348 GiB
free. Samples do not exclude transient activity between observations or prove
exclusive GPU ownership.

The launcher checks free disk on output, workspace and home filesystems against
36 GiB at preflight and 34 GiB during and after the pair. Individual disk
readings were not written to this pilot's artifacts, so exact free space at
those checks cannot be independently reconstructed from the saved logs. The
launch and input manifests list the same 1,194 pins, and the four small v3
proxy/launcher/auditor source files still match their recorded hashes; this
write-up does not rehash the large inputs or establish independent runtime
attestation.

Artifacts: `build/flex/sim/levels-v2/pitch82/sim-stop-fault-pilot-v3/`.
The v1 failed-control pair and separately reviewed v2 correction remain
preserved. This one matched scene does not establish general stop reliability,
automatic recovery, delivery or hardware safety.
