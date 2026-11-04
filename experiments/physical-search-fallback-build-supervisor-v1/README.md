# Supervised search-fallback CPU build (disabled)

This stages a dedicated CPU-only build of the opt-in simulator prototype in
`physical-search-fallback-build-v1`, with a separate
`physical-search-fallback-build-cpu-monitor-v1` receipt directory. Both paths
must be absent; failed attempts are retained and require new versioned paths.
The CLI is disabled pending review and scheduling. It does not run the
simulator or use the GPU.

The dedicated supervisor and its build child verify nice >=15 and idle-class
I/O scheduling. Before output creation the supervisor checks at least 36 GiB
free on workspace, home and output filesystems, takes the existing shared
pitch82 lock nonblocking, and repeats the checks. It holds the lock through
build and receipt publication. A busy lock prevents the build, even though the
source archives are read-only, to avoid contention with the active benchmark.

The builder compiles two native programs from copies in the new output; the
existing compiler and archived input files are read and checked before/after.
The child validates source transformation and binary/receipt consistency, and
is supervised as a process tree with a 900-second deadline. The supervisor
requires clean persisted status, stable input hashes, matching binary receipts
and at least 32 GiB free on all three filesystems before reporting completion.
Disk is checked at the start and end, not continuously. The supervisor's own
input hashing and small receipt checks are low-priority but occur outside the
900-second child deadline; a separately bounded caller is needed for a strict
whole-wrapper deadline. The process-tree cleanup handles timeouts and caught
signals; it does not guarantee cleanup if the supervisor itself is killed with
SIGKILL or the machine fails.

Checksums and saved invocation/priority records are local consistency evidence,
not proof of operating-system execution identity. The build is not a rendered
simulator trial or evidence of physical stopping, pickup or delivery.

CPU-only tests, using disposable paths and a mock build:

```
python3 -B -I experiments/physical-search-fallback-build-supervisor-v1/test.py
```
