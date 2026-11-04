# Bounded CPU overlay preparation (disabled)

This separately staged watchdog invokes the original full overlay preparation
script; it neither changes its shared lock nor its paths, no-overwrite checks,
disk guards or partial-retention behavior. Its CLI remains disabled pending
independent review and scheduling. It must run in a dedicated, single-threaded
process without existing children, because its subreaper cleans descendants.
The wrapper checks both Python and Linux task counts and the child list, and requires the monitored collection
receipt, at least 34 GiB free disk and new monitor/output paths before launch.

The 7,200-second limit includes the original collection re-audits and repeated
multi-GiB hashing. `launch.json`, `client.log`, `supervisor-result.json` and
`result.json` are retained in the separate `heading-overlays-cpu-monitor-v1`
directory. The result records the raw child exit, signal, timeout and cleanup
status. Positive child exits are forwarded when there is no interrupt or
timeout; a signal maps to 128 plus the signal, a timeout to 124, and cleanup or missing/invalid pair-ready evidence
fails the wrapper. A success remains `paired_inputs_only`, not a trained model
or qualification. The original data and all partials are preserved on failure.

CPU fixtures test exit-code forwarding, invalid/missing pair-ready evidence,
timeout cleanup of a detached SIGTERM-ignoring child, unrelated sibling
preservation, no-existing-child refusal and the disabled entrypoint. A timeout
is a failure, not a license to remove or overwrite a partial. The 34/32 GiB
checks remain point-in-time guards; a watchdog is not a disk reservation or a
host-wide lock against unrelated writers.
