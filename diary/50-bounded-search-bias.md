# Bounded search-bias experiment (staged)

The factorial diagnostic found that a small change in initial heading can
change room entry sharply for either policy. The same treatment model entered
layout 15 in 3/3, 0/3, 3/3 recorded games at yaw 0.35, 0.42, 0.49; the
three cases in each cell share a layout and start. The first action difference
between the earlier control and treatment in the yaw-0.42 case appeared at
action 71, well before room entry. These observations motivate, but do not
establish, a targeted intervention.

The proposed experiment uses the **same treatment epoch-8 policy** in both
arms and an isolated rebuilt control binary. Both arms request raw logits.
The treatment adds 0.5 to the straight-ahead class for at most 30 actions,
starting after 70 search actions since the latest brick placement; carrying
suppresses it and a delivery starts a new search interval. The control uses
the same 0.5 bias but a threshold of 1,000, beyond the fixed 300-action
horizon. This directly tests one preselected timing and strength. It does not
train the policy, detect loops, or establish the correct maneuver. Previous
experiments with a 2.0 straight bias on an older model showed no doorway gain
(diary 15); a small bounded bias on this model is an unproven hypothesis.

The isolated source transformation fails if the original source does not
match the expected function. It records the number of bias-eligible steps
and the number on which the bias changed the chosen action class. A staged
CPU-only native probe checks the window boundaries and carrying gate before
the binary is used. The paired auditor requires equal initial pose, target,
scene and policy, and identical first 70 actions. It rejects a recorded action
change without a paired divergence, or a paired divergence with zero recorded
changes. Eligible steps are recomputed from recorded pickup and delivery
transitions. Without raw logit recordings, the exact changed-action count is
not independently reconstructed; its relationship to paired divergence does
not prove the source of every later difference. These checks and hashes do
not independently attest actor execution.

The pilot is the single previously problematic training-layout condition
layout 15, heading 0.42, seed 7800001. It must finish both 300-action games,
match the first 70 actions and produce at least one changed action before
expansion. A zero-change pilot means the hypothesis failed to activate for
that case; it does not justify searching many thresholds on that case.

If the pilot activates, `select` tests all 27 existing layout/heading/seed
conditions for each of levels 1, 3, 4 and 5; `validate` uses the same layouts
and headings with the preselected seeds 7810101, 7810104 and 7810107. Those
seeds are checked against the 60 recorded source-shard seed ranges, but
unrecorded earlier uses and pretrained ancestry are not established. Both
sets are training-layout selection, not held-out benchmark data. The scripts
record deliveries, pickup and room-entry action, per-episode back-and-forth
(recomputed from the action/pose trace), search route coverage, and the bias
counters. Report results by level and heading; do not promote an L5 gain
without looking at L1/L3/L4 and back-and-forth regressions. The actor's carry
cue comes from simulator task state and is not a physical sensor.
For L1/L3/L4, target placement may depend on starting heading. Control and
treatment placements are matched within each condition, but comparisons
across headings cannot isolate the heading effect from target placement. L5
also checks that the same layout and seed produce the same initial placement
across headings; layout differences still bundle other scene changes.

When the GPU is otherwise idle, **after independent source review**, the
intended sequence is:

```
python3 -I datasets/visual-control/chase-v1/levels/prepare-bounded-bias.py
python3 -I datasets/visual-control/chase-v1/levels/prepare-bias-validation.py
python3 -I datasets/visual-control/chase-v1/levels/run-bounded-bias.py pilot
python3 -I datasets/visual-control/chase-v1/levels/run-bounded-bias.py select 5
python3 -I datasets/visual-control/chase-v1/levels/run-bounded-bias.py validate 5
python3 -I datasets/visual-control/chase-v1/levels/run-bounded-bias.py select 1
python3 -I datasets/visual-control/chase-v1/levels/run-bounded-bias.py select 3
python3 -I datasets/visual-control/chase-v1/levels/run-bounded-bias.py select 4
python3 -I datasets/visual-control/chase-v1/levels/run-bounded-bias.py validate 1
python3 -I datasets/visual-control/chase-v1/levels/run-bounded-bias.py validate 3
python3 -I datasets/visual-control/chase-v1/levels/run-bounded-bias.py validate 4
```

Each stage uses the nonblocking shared experiment lock, retains all existing
and partial output, verifies pinned inputs and the model, supervises each
process for at most 180 seconds, and requires 12 GiB initially and 8 GiB
before each condition. The lock does not detect other GPU jobs. At most 434
one-minute simulated games are specified by the full sequence, so the pilot
should be assessed before launching the longer stages. No files under the
held-out reservation or evaluator are used. The isolated build and native
CPU probe passed; the rebuilt control SHA-256 is
`e78d6031cfa137c6345829fee818926d0f6a867a77553cd35048dc22ac9c9c02`.
The original control binary was not replaced. The build command above now
refuses to overwrite the existing build; its manifest can be rechecked with
`prepare-bounded-bias.py`'s `verify` function. Physical testing and model
promotion require separate evidence.

The two-game L5 pilot has since run and passed its paired audit. The bias was
eligible for 30 actions but reported zero changed action classes; the two
decision journals had the same SHA-256. Neither arm entered the target room,
picked up or delivered; both traveled 17.99 m and ended 0.62 m from the
start. This one scene shows no effect, not that no possible bias would work.
The expansion gate correctly rejects a pilot with no changed action. Do not
launch the larger comparison based on this result. Artifacts are in
`search-dagger-l4-matched/bounded-bias-pilot-L5`.
