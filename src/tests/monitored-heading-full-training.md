# Monitored matched full heading training (disabled)

The existing full trainer already applies a 3,600-second watchdog to each of
two arms and checks 34 GiB at stage start and 32 GiB after each arm. It did not
have a whole-run GPU/disk monitor or monitored-completion gate. This separate
wrapper supplies those controls without altering that trainer. Its CLI stays
disabled pending independent review and scheduling; launch only from a fresh
standalone process because the outer subreaper cleans all its children.

It requires a 30-second one-second-sampled GPU baseline, 6 GiB nominal free
VRAM, no five consecutive busy samples above 10%, and at least 34 GiB free
disk. During training, telemetry loss, nominal VRAM under 2 GiB or disk below
34 GiB stops the pidfd-identified worker and its supervised descendants. The
34 GiB threshold leaves 2 GiB above the 32 GiB floor; it is headroom, not a
reservation. Actual full-scale CoW, logs and unrelated writes are not bounded
by the small pilot, and sampling can miss a sudden excursion. A final 32 GiB
check precedes publication.

The worker allows 14,400 seconds for both 3,600-second arm ceilings plus
input checks and audits; outer supervision allows 15,000 seconds. A separate
post-run evidence/hash process has a 1,800-second deadline. Outputs and partials
are never overwritten or deleted. After a clean outer result and final
telemetry, the fixed-path completion receipt binds the full training report,
inputs, both arm commands and statuses, model data/checkpoints/receipts and
kernel files, monitor logs and frozen sources. Fixed-epoch selection packaging
requires that receipt as well as its existing full training and paired-input
checks. The receipt is an ordinary saved-data consistency check; it is not OS,
GPU, actor-input or physical-robot attestation, and does not promote a model.

CPU fixtures cover baseline thresholds, disk and telemetry failures, pidfd
abort, detached descendants, unrelated-process preservation, saved command and
status mismatches, and model/telemetry tampering. No full training has run
under this wrapper. One-second device counters cannot establish GPU exclusivity
or Kennel service responsiveness.
