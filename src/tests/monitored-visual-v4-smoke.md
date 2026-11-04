# Monitored v4 smoke (disabled)

This is a staged wrapper for the separately reviewed one-action rendered smoke.
Both CLI entrypoints remain disabled. Use is limited to a dedicated standalone
supervisor process, so its subreaper does not adopt or signal unrelated children.
No GPU run has been performed with this wrapper.

The monitor pins the current GPU PCI address `0000:03:00.0` and reads the
kernel busy and nominal VRAM counters at one-second intervals. Before launch it
requires 30 seconds of valid samples, at least 6 GiB free in each sample, and
fewer than five consecutive samples above 10% busy. During the smoke it aborts
on telemetry failure, less than 2 GiB nominal free, or the worker deadline;
activity is recorded but not used to stop an active smoke. The monitor writes
JSONL samples and a failure reason, and targets its own worker using a pidfd.
The outer subreaper supervisor bounds the entire operation to 300 seconds and
cleans its descendants, including detached processes. The inner smoke retains
its own 120-second watchdog. Existing outputs and partials are preserved.

The CPU fixtures include telemetry and threshold cases and real nested-process
cleanup after abort, monitor death, and pidfd-open failure; an unrelated sibling
process remains alive. One-second samples can miss transient allocations, and
nominal free VRAM does not guarantee memory or scheduling availability. Busy
percentage is whole-device activity and cannot attribute use or service latency
to Kennel. Neither low activity nor a passing smoke proves exclusive access,
full-rollout safety, or physical robot success. A monitored smoke does not
authorize the full visual validation or heading training.
