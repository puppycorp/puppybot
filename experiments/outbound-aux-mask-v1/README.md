# Copied-trainer auxiliary mask for the five new fitting histories

A valid frame with a zero action-supervision mask still reaches the existing
trainer's map, pose, target/heat and `--phase-from-valid` losses. Consequently
masking action labels after teacher pickup alone does not suppress auxiliary
training on the teacher's return suffix.

`transform.py` stages a change in a **copied** trainer. For the explicitly
provided half-open episode range, it masks those auxiliary losses on rows whose
action-supervision mask is zero. The intended candidate range is `[928, 933)`:
928 preserved fitting histories precede the five selected teacher histories,
and 96 preserved validation histories follow them. The transformed trainer
requires PVDATA04 with 1,029 total, 933 fitting and 300 time steps before it
can proceed. Shape alone does not authenticate episode ordering: a separately
verified dataset receipt and exact source/binary hashes must bind the range.
The transform never edits dataset images, feedback, action labels, map files,
or any preserved history. Those inputs remain available for recurrent state
and existing baseline supervision. The output-seed masking does not itself
prove that the physical trajectory is safe or that the model improves.
Adding episodes changes batch composition and loss normalization even if the
original rows are byte-identical; that effect needs matched evaluation.

The full copied trainer compiles together with the staged 1,030 capacity. Its
host-only batch/loss probe verifies positive supervision on the selected prefix,
zero phase, pose, map, target and event output seeds on selected masked suffixes,
and continued baseline suffix supervision under the same options. It also
checks reversal and phase-consistency pairs at the boundary and heat-absence
mask override. Images and proprioception are retained. Sparse synthetic header
probes reject changed count, split and horizon before GPU initialization.

No CNN/GRU graph, actual dataset, device gradient, optimizer or real training
is tested; shared recurrent parameters and any added loss head still need
independent review. This transform is a prototype, not an active trainer or a
training authorization. Run:

```
python3 -B -I experiments/outbound-aux-mask-v1/test.py
```
