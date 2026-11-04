# Fused overlay hash proof of concept

This isolated CPU-only prototype hashes each base and output aggregate as it
reads every header and game for the exact unchanged/replaced-slot comparison.
It compares those complete SHA-256 digests with caller-provided pins and then
independently rereads both complete aggregates for the post-pass SHA-256.
Every source shard still has its own full pre- and post-pass digest. Regular
no-follow descriptors, complete size and header checks, and pre/post file and
path identity checks are required. Production widths are specified, while the
fixtures use tiny synthetic files. The code is not connected to any training,
selection, registration, simulator or GPU workflow; its CLI is disabled.

On the current paired overlays, merging the preliminary aggregate hash into
an already-required semantic read could avoid four full 6.07 GiB reads per
paired check, while retaining the complete post-pass. The pre-hash decision
moves to the end of the semantic pass. For stable files this checks the same
full bytes, labels and mapping, and corruption still fails closed. It is not
literally equivalent under every concurrent mutation schedule: a change that
is made and restored between the legacy pre-hash and this fused stream could
be observed by the legacy check but missed here. File identity and timestamp
checks catch ordinary observed mutations and path swaps, not all hostile-owner
or filesystem corruption scenarios. Do not integrate until the desired
concurrency semantics and an immutable-input strategy are independently
specified; the independent later full hash is intentionally retained.

Run synthetic tests without production inputs:

```
python3 -B -I experiments/overlay-fused-audit-v1/test.py
```
