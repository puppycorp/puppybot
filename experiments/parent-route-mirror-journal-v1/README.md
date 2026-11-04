# Paired trainer batch and mirror journal

This CPU-only prototype transforms a **private copy** of the already reviewed
1,031-history trainer. It adds an exclusive `batch-schedule.bin` journal for
the fixed one-epoch paired experiment. It does not edit the reviewed trainer,
launch GPU code, run training or select a model. `build.py` provides a
separate, directly disabled entry point for a future reviewed private build;
its CPU tests build only temporary copies.

At each actual training `pt_batch_send`, before device upload, the journal
records a sequential batch index, fitting-order offset, active count, host
mirror mask, and the episode IDs saved when the batch was filled. This covers
prefetched batches and the final one-history batch. The writer requires the
fixed 1,031/935 split, seed 7120000, one epoch, batch two,
mirror augmentation, no focus copies, no feedback dropout and no maximum-step
cutoff. It rejects a repeated send, a gap, or a mask that differs from the
last filled batch. The footer is written only after 935 fitting histories in
468 batches have been sent. An interrupted training run retains an incomplete
journal without a valid footer. The underlying reviewed trainer separately
requires the 300-step horizon.

`audit.py` checks both complete journals against each arm's separately saved
first and final 1,031-entry orders. It requires the exact fitting permutation,
unchanged validation order, separate files, both arms' orders and all 468
journal records to match, and the mask sequence to match the fixed seeded
augmentation generator. It explicitly checks the final active count is one.
The audit needs source/plan/output hashes and independent monitor receipts
from a future training runner; matching saved host metadata does not attest
GPU consumption, full execution, gradient values, optimizer state, model
quality or physical robot behavior.

`python3 -B -I experiments/parent-route-mirror-journal-v1/test.py` compiles the
full transformed private trainer and a CPU probe. The probe executes the real
`pt_batch_fill` and `pt_prefetch` paths for all 468 batches, with a test-only
early return after the journal hook to avoid a device upload. Tests check the
prefetched IDs/masks, seeded sequence, partial batch, missing footer, corrupted
rows, mismatched first/final orders, aliasing and invalid send sequences. The
probe also exercises inactive fill/send before journal creation and after
completion, as in initial evaluation and validation. It does not execute an
actual GPU graph, backward pass, or optimizer.

`build-test.py` also creates a temporary private control, trainer and reflink
probe on Btrfs, checks that recompilation reproduces their hashes, and rejects
changed source, binaries, receipts, fixture bytes and low disk space. It also
rejects linked private outputs or source paths and rechecks that the fixture's
two separate single-link files retain their recorded shared extents. This does
not establish sharing or safety for future real training outputs.

Before use, independently review the transform, test its interaction with the
paired trainer's mask/row checks, build and bind a **new** private binary, and
freeze an explicit paired training plan with serial GPU/disk supervision. The
two actual datasets, initialized parent weights, fresh optimizer moments,
full order/mask journals and fixed epoch-1 checkpoints must all be checked.
The reserved held-out scenes remain protected by convention only; the guard
is not wired into native training or selection.
