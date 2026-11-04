# Read-only postrun selection audit

The completed v2 selection's original monitor failed before publishing its
final inventory because the generic inventory rejects directory symlinks.
The evaluation script creates scene-catalog links by design. The original
failure and all outputs remain unchanged; this verifier cannot retroactively
make that monitor pass.

The verifier first checks the registered selection inputs and original
terminal monitor outcome. It constructs exactly 160 expected catalog link
paths and targets from the frozen five-level design, rejects missing,
retargeted or extra links, and never traverses links. It hashes regular output
files with `O_NOFOLLOW` on their final path component, captures monitor-file
identities, checks the saved GPU/disk telemetry, reconstructs the full saved
comparison and then repeats all checks. Directory enumeration and hash
snapshots are local consistency checks, not an atomic filesystem snapshot or
attestation of execution. Concurrent path replacement or changes between
samples cannot be ruled out.

The output is a read-only Python result with status
`postrun_consistent_original_monitor_failed`; it does not create or modify
any receipt. No held-out, physical, actor-execution or original-monitor-pass
claim follows. Direct CLI execution is disabled pending independent review
and a separately supervised read-only invocation.

Run the seven CPU fixture checks with:

```
python3 -B -I experiments/fresh-policy-postrun-v1/test.py
```

They cover exact expected links, absent/retargeted/replaced links, unexpected
file and directory links, nonregular output nodes, changed output inventory,
and the persistence of the original failed status. They do not exercise the
full 480-game postrun audit.
