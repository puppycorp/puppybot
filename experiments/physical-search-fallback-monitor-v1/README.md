# Monitored search fallback trial (staged)

This is a separate, disabled outer monitor for the three-arm simulated search
fallback diagnostic. It does not start the simulator from its CLI. Before any
execution, schedule the entire baseline and trial outside all other GPU work;
the inner trial lock alone does not protect the resource baseline.

The monitor checks at least 36 GiB free before output creation and throughout
the GPU baseline, 34 GiB in active samples and before the final audit, and the
32 GiB floor before completion. It checks the workspace, home and output
filesystems separately. GPU sampling requires a 30-second baseline with at
least 6 GiB free, no five consecutive samples above 10% busy, and at least
2 GiB free during the trial. Missing, malformed or overly sparse samples fail
closed. Samples are observations, not a guarantee of exclusive GPU access.

A dedicated-process outer subreaper has a 3,000-second limit, and the worker has
2,700 seconds for setup, three 300-second arms, audit and possible partial
audit. The later CPU-only final check has its own 900-second subreaper limit.
Failure, timeout, low or lost telemetry, or required descendant cleanup leaves
the evidence in place without a completion receipt. The final check re-audits
the saved output and compares a streaming inventory of all trial files before
and after the check. A complete diagnostic can still be censored; the receipt
retains the actual comparison eligibility and censor reason.

The worker flag, locally recorded invocation and checksums are evidence of the
saved workflow, not an operating-system attestation. The simulator search ACK
does not independently authenticate the private no-target frame and does not
prove physical stopping, pickup, delivery or safety. No rendered run has been
performed by this monitor.

CPU-only fixtures:

```
python3 -B -I experiments/physical-search-fallback-monitor-v1/test.py
```

The fixtures include real nested processes, escaped SIGTERM-ignoring children,
repeated signals, an unrelated sibling, low/lost telemetry, timeout and pidfd
failure. They do not use a GPU or validate rendered behavior.
