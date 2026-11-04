# Private paired-data trainer extension

This is CPU-only preparation. It copies the previously verified
`outbound-five-trainer-build-v1` source into a new private build; it does not
modify the shared control/trainer, either candidate aggregate, or any model.
No GPU graph, optimizer update or training is launched by these scripts.

The private transform raises only the PVDATA04 capacity from 1,030 to 1,031,
requires exactly 1,031 episodes, 935 fitting and 300 steps, and extends the
existing zero-weight auxiliary-mask range from `[928, 933)` to `[928, 935)`.
The corresponding data file is 6,564,583,232 bytes and the map file is
44,539,232 bytes; the data file is below the existing 8 GiB mapping limit.
At batch size two, one full fitting epoch contains 468 optimizer batches,
including a final one-history batch. These are calculated shapes, not an
observed training run.
Thus the five earlier teacher prefixes and the two new parent-driven
histories retain valid suffix frames as recurrent context while zero-weight
suffix rows do not seed the selected auxiliary losses. Baseline episodes
before 928 and validation episodes from 935 onward retain their prior
behavior. Reversal and phase-consistency pairs crossing a masked suffix must
also be checked by the CPU host-loss probe.

The trainer's native row guard now runs before GPU initialization. On fitting
slots 928–932, it requires the existing first-consumption cutoffs
162/107/171/43/38, valid frames, binary prefix masks, joint-seven actions and
teacher labels identical to recorded executed actions. On slots 933–934 it
requires first-delivery cutoffs 163/189, the same valid/prefix/codec checks,
and zero action-label bytes after the cutoff. Control and treatment may have
different valid prefix labels; dataset provenance and the paired aggregate
verifier must bind which labels belong to which arm. These structural checks
cannot authenticate data, maps, model or training order.

`build.py` verifies the previously pinned trainer build, copies its source,
applies only the declared dataset/trainer/workflow changes, redirects the
copied control to its own trainer, and compiles both binaries and the
unchanged reflink probe. A small Btrfs fixture checks separate single-link
inodes, matching bytes and shared extents. The receipt pins source trees,
literal imports, compiler, previous build and binaries; verification
recompiles the same source and requires matching binary hashes. Its direct
CLI is disabled, and it refuses an existing output or less than 38 GiB free.

CPU checks:

```
python3 -B -I experiments/parent-route-paired-trainer-v1/build-test.py
python3 -B -I experiments/parent-route-paired-trainer-v1/probe-test.py
```

The tests use copied source and synthetic data, not actual GPU gradients,
prefetch concurrency, the optimizer, real datasets or a trained policy.
Before either training run, independently review and bind both verified
aggregate hashes to a fixed matched training plan, validate actual device
gradients and the complete mask/order behavior, and use fresh selection
families with a separate ancestry audit. This preparation is not a training
authorization, held-out pass or physical robot result.
