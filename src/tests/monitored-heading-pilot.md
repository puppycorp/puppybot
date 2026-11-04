# Monitored heading pilot (disabled)

This separately staged wrapper surrounds the existing four-game heading pilot
supervisor; it does not change the pilot, catalogs or saved data. Its command
entrypoint remains disabled until independent review and scheduling. It must
run as a dedicated standalone process, not inside a process with unrelated
children, because its outer supervisor is a subreaper.

The wrapper reuses the monitored v4 smoke's telemetry and 30-second baseline:
reject fewer than 6 GiB nominal free VRAM or five successive one-second busy
samples above 10%. During the pilot, telemetry failure or nominal free VRAM
below 2 GiB aborts the worker via its pidfd. The supervisor reaps descendants,
including detached workers. Activity is recorded but is not a stop criterion
after launch. The wrapper requires at least 40 GiB free disk before its own
output directory and rechecks that threshold immediately before and after the
baseline; the original supervisor and per-stage gates remain active. Prepared
catalogs must exist and original supervisor/pilot outputs must not exist. No
output or partial is overwritten or deleted.

The outer wrapper allows 1,920 seconds, including baseline; the heading worker
is limited to 1,850 seconds after baseline. The unchanged original supervisor
sets its own 1,800-second whole-pilot limit and 600-second collection-arm
limits. The monitor saves samples, worker logs, abort reason and outer
supervisor status; a passing original pilot report remains necessary.

CPU fixtures cover disk and no-overwrite gates plus real nested cleanup after
low VRAM, telemetry loss, monitor death and pidfd-open failure; an unrelated
process survives. This wrapper has not run with the GPU. One-second samples
may miss brief peaks; nominal free VRAM and whole-device busy are not a proof
of available memory, GPU exclusivity or Kennel responsiveness. The completed
one-action visual smoke uses a different path and model and does not establish
the heading pilot's peak memory.
