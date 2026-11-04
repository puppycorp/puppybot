# L5 route and actor-frame diagnostic

`python3 experiments/l5-route-frame-diagnostic-v2/diagnose.py` reads the
registered v3 selection and its saved games; it does not launch a simulator or
write to the selection. It checks the registered plan, the named simulator,
robot, control and model files against their recorded hashes, the two selected
scene copies, game metadata, 300 recorded actions, initial states and the
first action difference. Its JSON includes hashes of the retained decisions,
events and results. It does not validate every file in the full selection or
replace that run's monitor audit.

The diagnostic checks selected original records and the selection report
against the completed selection's sealed evidence inventory, and checks the
frozen GPU runtime symlink/hash chain. The selected games are L5 indices 10
and 25, seeds 7820010 and 7820025, from
training-family layout 15, variants 10 and 9. Original student and candidate
first choose different actions at zero-based index 68 on both games. Their
initial robot poses and environment bytes match; the two bricks have different
initial locations. Original student completes one delivery in each game;
candidate completes none. Case-component detections are saved in state logs;
they are neither saved actor images nor proof of what the policy could see.
The lean runs did not retain their actor frames.

## Proposed capture, not launched

`capture.py` contains a disabled standalone launcher for this plan. Its
`launch()` entry point requires a dedicated process and independent review;
executing the file directly intentionally exits without launching. A shared
nonblocking GPU-experiment lock covers the capture, an outer monitor samples
disk and GPU through capture and CPU audits, and a separate subreaper wraps
each serial game. The CPU-only `test_capture.py` exercises tampering, lock
contention and process-tree cleanup; it does not replace review or a monitored
end-to-end capture.

Use the two selected scenes with both frozen policies: four single-episode
reruns, serially, retaining actor frames. This is an investigation of known
selection cases, not held-out validation. Do not train on these results while
claiming this selection set is independent; reserve different untouched scene
families and seeds for selection and final qualification.

Before any launch, re-run `diagnose.py`, verify the original full selection
completion and resource-monitor receipts, pin a capture plan and the present
execution environment, and independently review a watchdog with descendant
cleanup. With disk at approximately 43 GiB free, begin only above 38 GiB,
stop gracefully below 34 GiB, and use 32 GiB as emergency termination. Check
GPU capacity and monitor the whole process tree and GPU throughout; avoid
concurrent GPU experiments. Record all thresholds, samples, exit statuses and
reasons, keep partial output on failure, and do not call an incomplete capture
successful. The Btrfs free-space margin, runtime and output size must be
checked live; do not assume captured video and sensor files are small.

Create new isolated output and one-entry catalog directories. Each catalog's
entry `0` must resolve to the corresponding registered scene after verifying
its case, environment and layout hashes. Run this argument structure once per
seed and arm with the original frozen policy directory and no `--lean`:

```
build/flex/control/control run --chase --policy MODEL \
  --scene-catalog CATALOG --output NEW_OUTPUT --episodes 1 --horizon 300 \
  --seed SEED --wheel-odometry --fetch --level 5 --camera-pitch 82
```

Use the recorded `SDL_VIDEODRIVER=offscreen`, runtime-library path and cleared
`DISPLAY`/`WAYLAND_DISPLAY`; run from the project root. The control binary,
simulator, robot asset, policy/weights/kernels and scene must match the
selection's frozen pins. Crucially, `PUPPYBOT_CHASE_FULL=1` in `evaluate.sh`
also drops `--wheel-odometry`; simply turning it on would not reproduce the
original setting. The direct command above retains wheel-only odometry while
removing only lean recording. The four intended `(SEED, MODEL)` combinations
are the two seeds above crossed with `control` and `treatment` model paths in
the diagnostic JSON. The simulator carries virtual task state and the
student receives its ordinary carry cue; no teacher, supplied map or oracle is
introduced.

For each capture, require exact equality of the initial JSON state and each
recorded action, proprioception, step, sequence, state, task event and final
result against its corresponding lean record, alongside matching scene and
model hashes. There are no state normalizations. Fail and preserve the capture
if any reproduction check differs. The launcher records initial observation
hashes and inventories the captured files; the original lean run has no saved
initial actor observation to compare against.
Compare the saved `actor-*.rgb` and `.feedback` across matched captures at
corresponding pre-action states. The initial actor frame is associated with
the initial state; a decision row records the image after its action, so use
the preceding observation when reasoning about the input to an action. The
raw image hashes in non-lean rows are post-action, too. Where the same actor
input history is available, an offline recurrent replay must maintain separate
hidden histories for both models; compare action logits without inventing a
shared hidden state. A capture or counterfactual replay is a local diagnostic,
not a measure of generalization or real-world behavior.
