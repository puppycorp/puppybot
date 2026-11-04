# Monitored matched trainer pilot (disabled)

This wrapper surrounds the existing one-epoch stock-versus-reflink trainer
pilot and does not alter its two training commands. Its entrypoint remains
disabled pending review and scheduling. It must run in a dedicated standalone
process: the outer subreaper cleans all descendants of its caller.

The monitor reuses the visual smoke's 30-second, one-sample-per-second GPU
baseline. It rejects five consecutive busy samples above 10%, any baseline
nominal free VRAM below 6 GiB, and missing telemetry. During training it aborts
its exact worker by pidfd on telemetry failure or nominal free VRAM below
2 GiB; outer supervision cleans adopted descendants. Activity is logged but is
not a stop condition once training starts. The wrapper requires 40 GiB free
disk before output creation and before and after baseline; the trainer's own
per-stage and 32 GiB final checks remain in force. Output directories and
partials are retained and never overwritten.

The original trainer retains its 1,800-second watchdog for **each** of two
arms. The monitored worker allows 4,100 seconds after baseline for both arms
and their checks; the whole outer wrapper allows 4,200 seconds. On success the
wrapper re-runs `verify_small_pilot`, including clean per-arm supervisor status,
dataset and model checks, and matching outputs. It then writes a distinct
`completion.json` binding the comparison, telemetry, monitor result, outer
supervisor result and monitor script hashes. The default downstream trainer
verification requires this receipt and clean outer status; failure after a
passing model comparison therefore cannot qualify the pilot. The fixed output
is `heading-trainer-pilot-monitored-v1`. It does not launch or authorize full
training.

CPU tests cover no-overwrite/input and disk checks, the exact worker command,
missing/failed result rejection, plus real detached-child cleanup and
unrelated-process preservation on telemetry loss, low VRAM, monitor death and
pidfd-open failure. No GPU test of this wrapper has run. One-second samples may
miss short peaks; nominal free VRAM and whole-device busy do not prove device
exclusivity, availability, or Kennel service responsiveness. The prior short
roll-in's memory use does not establish this training workload's peak.
