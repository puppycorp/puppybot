# Fixed five-prefix warm-start training design

This is an **unlaunched exploratory** one-epoch continuation of the exact
`student-s1` used in the diverse outbound pilot. The fixed schedule is encoded
in `design.py`: seed 7120000, batch two, learning rate 100 micros, categorical
action loss, unit transition weight, memory-map auxiliary, carry cue, mirror
augmentation, and checkpoint at epoch 1. The parent trained for eight epochs
at 700 micros; its receipt confirms the same batch, action codec, carry cue,
map auxiliary, mirror and transition settings. This is a deliberate lower-rate
one-epoch continuation, not an exact replay of the parent training. The native
trainer allocates and zeroes new Adam moments and step count; it initializes
weights from the parent, not the parent's optimizer state. Five new histories
change minibatch order, the final incomplete batch and loss normalization even
when every old history is preserved byte-for-byte.

The proposed comparator is the unchanged parent, not a separately retrained
baseline. A result difference therefore cannot isolate the effect of the five
prefixes from the additional epoch, different learning rate, or optimizer
reset. A separate matched continuation would be needed for that causal claim.

The candidate aggregate must contain 1,029 300-step histories, including 933
fitting and the original 96 validation histories. Source episodes 3, 4, 5, 6,
and 8 occupy fitting slots `[928,933)`; their post-consumption action and
auxiliary output masks are suppressed while RGB, feedback and recurrent
history remain available. The data and map are required to have fixed SHA-256
hashes recorded in `design.py`, and `train.inputs()` rechecks the monitored
pilot completion, the complete source chain, exact fitting selection and
cutoffs, and an independent byte comparison of every preserved and inserted
history. Its candidate-data receipt deliberately does not itself claim model
improvement or authorize promotion.

`build.py` copies the previously pinned heading-training source and retains its
FICLONE-only dataset-copy behavior. It applies only the reviewed 1,030-episode
limit, the five-episode auxiliary mask, and a direct reference to its own copied
trainer executable. It pins literal transitive imports and source/binary hashes
and verifies a separate FICLONE scratch probe. It never replaces shared
binaries. `train.py` preregisters all candidate, source, model, simulator,
selection and runtime files before training, and prepares a read-only inference
package from **epoch-1.bin**, even when the trainer's validation-selected
`weights.bin` differs. The receipt must show the requested options, exact
parent initial weights, 467 optimizer steps and a complete fixed checkpoint.
Failed or partial new outputs are retained.

The `monitor.py` wrapper reuses the existing 30-second GPU idle baseline,
36/34/32 GiB disk floors, free-VRAM thresholds, nested process cleanup, and
separate final inventory supervisor. Its direct CLI, the build CLI and the
training CLI are disabled. The CPU-only manifest registration completed with
SHA-256 `fc20b722234564e0b352f663d144817a128122e35e1cd822c3780083efed65e0`.
Independent full plan and supervision receipt readback passed. All hashes and
process logs are local consistency
checks; they do not attest raw camera input or OS execution identity.

The proposed evaluator is deliberately **not yet wired or launched**. Its
frozen design uses the existing 160 training-family selection rows (32 per
level; their original v2 monitor failed), with fresh matched games for the
unchanged student-s1, fixed epoch-1 candidate and exploring teacher. Recompute
the final-window-inclusive `pose20-final-inclusive-v2` loop measure for each
complete game; the old legacy score is not a qualification. Also record first
pickup, complete virtual pickup-and-return, doorway outcomes, longer search
loops, deliveries/minute and all failures. The catalog-aware monitor adapter
and full evaluator must be separately implemented and reviewed before that
selection run. These scenes are disjoint from the five new training prefixes by
exact case/environment bytes, but have appeared in earlier development and
are not held-out. No checkpoint tuning or model promotion is authorized by
this design alone.

The evaluator must report per-level game completion, first pickup and
doorway denominators for the candidate, parent and teacher separately. The
design's `requireReliabilityWithoutSacrifice` field is a reminder, not a
quantitative comparator; the evaluator and its acceptance rule still need an
explicit definition and independent review before selection.

CPU checks read the archived trainer sources, parent model, selection scenes
and completed candidate's small supervisor receipt; they do not read the full
aggregate or require a GPU:

```
python3 -B -I experiments/outbound-five-trainer-v1/test.py
python3 -B -I experiments/outbound-five-trainer-v1/train-test.py
python3 -B -I experiments/outbound-five-trainer-v1/supervise-build-test.py
python3 -B -I experiments/outbound-episode-cap-v1/test.py
python3 -B -I experiments/outbound-episode-cap-v1/order-test.py
python3 -B -I experiments/outbound-aux-mask-v1/test.py
```

The native device graph, gradients, prefetch concurrency and full real
300-step training have not been tested in this candidate trainer. No actual
training, independent selection, held-out evaluation or physical robot run has
been performed by this experiment.
