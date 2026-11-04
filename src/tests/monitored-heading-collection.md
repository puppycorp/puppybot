# Monitored full heading collection (disabled)

This separately staged wrapper calls the original full heading collector, with
four shards per arm collected sequentially. It does not alter the collector,
catalog generator, completed-pilot inputs or source data. Its CLI stays
disabled pending review and scheduling. Launch only in a dedicated standalone
process: the outer subreaper cleans all children of its caller.

The monitor uses the same 30-second baseline as the small pilots: 6 GiB
minimum nominal free VRAM, no five consecutive one-second busy samples above
10%, and valid telemetry throughout. While collection runs it stops its worker
via pidfd on telemetry failure or nominal free VRAM below 2 GiB. The existing
per-shard 3,600-second watchdogs remain. The worker allows 32,400 seconds
after baseline, enough for all eight maximum shard times plus 3,600 seconds
for collector checks; outer supervision allows 33,000 seconds. A separate
post-run receipt hashing subprocess is capped at 600 seconds. It requires
40 GiB free disk before staging and before and after the baseline; the
collector's own later 34/32 GiB checks remain. Partials are retained.

Only after a clean collection, final telemetry, clean outer supervision and
receipt snapshot does the wrapper write its fixed-path `completion.json`.
It binds the catalog, collection report and inputs, eight shard data/maps and
reports, eight arm-supervisor statuses, monitor/outer statuses, telemetry and
both wrapper/verifier scripts. It also binds each of 256 games' result,
decision, chase and scene files, each shard's policy snapshot and kernel
inventory, and the presence or absence of audit-relevant logs. Overlay creation, standalone pair receipt
publication and the full training entrypoint require the verified receipt.
Before launching it also records hashes of the wrapper, telemetry module,
receipt verifier, collector and supervisor/cleanup source files; the final
snapshot must still match those hashes. These disk checks are not proof of
which bytes actually ran or of an executable identity throughout the run.
The original collector is unchanged, and a failed or unmonitored run cannot
qualify through those entrypoints. Hashes check current consistency, not
independent runtime attestation.

CPU tests cover completion tampering, all three downstream gates, thresholds,
the exact collector command, receipt-audit timeout, telemetry failure, and
cleanup of detached workers while an unrelated process survives. No full
collection has run under this wrapper. One-second sampling can miss brief
peaks; nominal free VRAM does not guarantee availability, and device-wide
busy does not establish Kennel service health or exclusive GPU access.
