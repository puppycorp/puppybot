# L5 actor-frame comparison after recording-aware replay (4 Nov 2026)

Four supervised replays completed on the two reused L5 scenes from
[entry 126](126-l5-frame-replay-attempts.md): parent and five-prefix model on
seeds 7820010 and 7820025. Each ran 300 actions, and the parent delivered
once in each scene while the checkpoint delivered none. The replay auditor
matched the original actions, feedback, task events, results and saved
action-boundary states, accounting only for the expected recording filename
and independently reconstructed evaluation-only localization maxima. The
lean originals did not retain actor frames or intermediate-tick states, so
the comparison cannot establish identical original pixels or full trajectories.

In both replays the first different action was zero-based action 68: the
parent chose `[0, 1]` and the checkpoint chose approximately `[0.6, 1]`.
The 68 saved actor RGB buffers and feedback vectors corresponding to
pre-action observations 1 through 68 were byte-identical between the two
arms of each scene. The initial saved buffers also matched, but they were
saved before initial brick placement, which refreshes the observation at the
same tick; they are not proven to be the input to action 0. The first saved
image and feedback differences appeared
at pre-action index 69, after the different steering commands. The shared
action-68 actor image SHA-256 was
`c10770053a149ce72e6dd1ee8341a2cc728bb3f04778d1c8480d6db52e9b85ce`.
The case detector reported no brick component in that pre-action state;
that separate detector does not establish what either policy recognized.

This demonstrates different model outputs at action 68 following the same
saved actions and matching recorded inputs for actions 1–68. The input to
action 0 was not independently recorded, and the models can have different
recurrent hidden states. The evidence does not identify whether a single turn
caused the later delivery difference. These two selected scenes remain
diagnostics, not held-out cases or a measured recovery rate.

The next different action was action 81; actions 69–80 matched again. By
action 120, simulated truth poses were about 1.46 m apart for seed 7820010
and 1.87 m apart for seed 7820025. The parent first virtually consumed the
brick at action indices 117 and 126 and delivered at event steps 163 and 189;
the checkpoint did neither within 300 actions. A read-only reproduction of
the frame and route comparisons, which also checks the used files against the
sealed inventory, is `experiments/l5-route-frame-diagnostic-v4/analysis.py`.

The compared prefix is before virtual consumption and its saved carry cue is
zero. The recorder saves feedback after a step, before the next loop may set
the carry cue; those files should not be treated as complete next-action
training inputs in later carrying phases without reconstructing the cue.

An independent re-audit reproduced all four game checks and the full output
inventory. All four game supervisors and both outer supervisors exited
cleanly; all eight completion hashes matched. Completion SHA-256 is
`2e1b3f065235cb2d2dee2c3c8a86be8933b875965c50d1188d499d879f8c0635`,
and inventory SHA-256 is
`4d0b0f7a38394173ccedec2edeaea859eadf0ef708cab3e2665ff8cad9123b0b`.
The sampled minimum free disk was 42.983 GiB and minimum free GPU memory was
8.900 GiB; sampling does not prove exclusivity. Artifacts are under
`build/flex/sim/levels-v2/pitch82/l5-actor-frame-capture-v4/`. The earlier
failed V1–V3 attempts remain failed and retained.
