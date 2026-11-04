# Monitored fixed-epoch heading selection (disabled)

This staged wrapper invokes the reviewed fixed-plan selection runner in a
separate process; neither CLI is enabled. It must be started as a dedicated
standalone process because the outer subreaper cleans all children of its
caller. The runner retains its shared lock, no-overwrite behavior, six tasks,
two sequential arms per task and per-arm/per-audit watchdogs.

The monitor uses the same GPU controls as the other staged monitors: a
30-second baseline of valid one-second samples, at least 33 GiB free disk,
6 GiB nominal free VRAM, and no five consecutive busy samples above 10%.
While the runner is active, GPU/disk telemetry failure, less than 2 GiB nominal
free VRAM or less than 33 GiB free disk stops only the pidfd-identified worker; the outer subreaper cleans
its descendants. Activity is logged but is not a stop criterion after
launch. The runner's existing 12 GiB initial and 8 GiB per-arm disk checks
remain unchanged. The extra 1 GiB above the 32 GiB floor is headroom based on
four earlier 32-game arm directories using 110,469,120–111,616,000 allocated
bytes each. It is a conservative estimate, not a reservation or a guarantee
against concurrent writes. The wrapper rechecks the 32 GiB floor before
publishing completion. All partials are retained.

Twelve 3,600-second arms and eighteen 600-second audits permit 15 hours before
setup or cleanup. The worker allows 64,800 seconds (18 hours) after baseline,
outer supervision allows 65,400 seconds, and a separate final inventory/hash
subprocess is limited to 1,800 seconds. Long execution remains possible; these
are limits rather than expected run times. No selection is launched by staging.

After a clean outer result and final telemetry, a separate completion receipt
binds the selection summary, plan, complete saved-file inventory, all 30 arm
and audit supervisor statuses, monitor and disk logs, checked saved command
intent and audit outputs, and pre/post source hashes. The
standalone selection audit requires that receipt before reporting a result;
the runner's intermediate audit functions remain usable for its own work.
No completed receipt is emitted on failure, timeout, telemetry loss or a
changed inventory. Files and hashes are consistency checks, not an independent
attestation of execution, actor inputs, camera authenticity or GPU runtime.
One-second telemetry may miss short spikes and cannot establish Kennel
service responsiveness. These are training-layout comparisons, not held-out
qualification, physical robot evidence, or a promotion decision.
