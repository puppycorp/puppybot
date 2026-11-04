# Paired one-update GPU smoke prototype

This unregistered prototype runs the reviewed private trainer sequentially on
the two independently audited paired aggregates, once each, from the same
original parent. It uses seed 7120260, batch two, learning rate 100 micros,
mirror augmentation, carry cue, map auxiliary and `--max-optimizer-steps 1`.
The seed's expected first shuffled batch is `[203, 934]`, so the actual batch
includes one added parent-route history with 31 supervised label differences.
The saved full order and first mirror mask must agree with this expectation in
both arms. This is a diagnostic smoke seed; the proposed full-epoch pair uses
seed 7120000 and needs a separate reviewed batch-journaling trainer.

`plan.py` proposes a separately frozen manifest binding data, model, private
build, upstream provenance, commands and runtime sources. `monitor.py` uses the
reviewed subreaper/lock guardian, a 30-second idle-GPU baseline per arm and
38/34/32 GiB startup/active/emergency thresholds. The guardian's 7500-second
overall deadline bounds both arms and the final audit together (each arm also
has a 7200-second subprocess deadline). It requires one complete
unshared data-copy reservation plus 128 MiB before each arm. Any failure stops
the pair and preserves prior outputs; an independent guarded final checker audits
both arms and inventories their files. A supplementary post-guardian inventory
and input recheck is read-only and checks the disk floor before and after; it is not
continuously sampled and does not hold the GPU lock.

`audit.py` requires the HIP marker, original parent initialization, exact data
and runtime hashes, the expected order and seeded mirror mask of 3, one optimizer step,
finite losses and map losses, finite nonzero gradients and a changed checkpoint.
The actual training data copies must have the expected bytes and size, distinct
single-link inodes on the source filesystem, with Btrfs totals recorded as
supplementary evidence. Those totals do not prove pairwise extent identity.
Map loss and the CPU-tested row masks are evidence of this path only: they do
not independently reconstruct every GPU auxiliary gradient or prove real-world
performance. Equal seven-element actor-bias gradients fail the diagnostic as
inconclusive; a difference alone does not prove the label change caused it. The one-step
output must not be used as a full-epoch model.

Run the CPU fixtures with:

```
python3 -B -I experiments/parent-route-paired-smoke-v1/audit-test.py
python3 -B -I experiments/parent-route-paired-smoke-v1/monitor-test.py
```

Direct command-line execution is disabled. Registration and execution require
independent review and a separate monitored scheduling decision; the presence
of this code does not authorize or attest a GPU run. Local hashes and process
receipts do not prove OS execution identity, raw camera/map truth, independent
held-out performance, or physical robot success. IDs 226–289 remain reserved.
