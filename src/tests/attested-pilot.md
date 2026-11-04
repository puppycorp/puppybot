# Original and instrumented control pilot

`python3 -I flex/tests/run-attested-pilot.py` is prepared for one future
diagnostic pair, not yet run. Run it only after other GPU work has finished
and the GPU is independently confirmed idle. It takes the shared matched
experiment lock, requires 12 GiB initially and 8 GiB before each arm, and
retains any partial output at
`build/flex/sim/levels-v2/pitch82/search-dagger-l4-matched/actor-attested-pilot`.
It refuses an existing output, including a dangling symlink.

Both controls receive the same fixed-epoch control model, Level 5 training
scene 15/1, seed 7800001, 300-action horizon and full recording options. The
instrumented binary is built from an isolated source copy; its model, scene,
source-build receipt and both binaries are hashed before use and checked
again after each arm. Each control process has a 300-second wall watchdog,
process-group termination and descendant cleanup. A model/package audit,
matched-training audit and previous training-input checksum check precede
execution. No held-out scene is involved.

The pair auditor checks both process statuses and summaries, snapshots of
the model and scene, action and feedback records, the actor journal, and
captured control argv and child exec intent. It compares the original saved
actor images with the instrumented journal where available. The original
first saved image was recorded before brick placement, so it cannot prove the
first actual actor image; full parity remains undetermined even when every
compared signal matches. After later deliveries, a saved frame can likewise
precede placement and produce a conservative image mismatch. This is a single
pair and does not prove repeatability, actual loaded libraries or GPU runtime,
camera authenticity, simulator-to-actuator application, or physical success.
The carry cue is derived from simulator task state.

Before launching, complete independent review of the scripts and confirm that
the required epoch-8 package and local runtime are present. The tests
`flex/tests/attested-pilot-runner.py` and `flex/tests/attested-pair-audit.py`
exercise CPU preflight and synthetic pair checks; they do not run the GPU
pilot or independently prove its eventual outcome.
