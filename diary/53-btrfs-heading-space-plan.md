# Btrfs space plan for the heading experiment

The heading experiment needs about 29.2 GiB in new collections, aggregates,
trainer copies and pilot overhead. Current free space was 51,845,320,704 bytes
(48.29 GiB). Completing it without reclamation would leave about 19.1 GiB,
below the existing 32 GiB safety floor. The staged experiment therefore
requires 64 GiB free before staging/collection, with further stage guards; do
not lower those thresholds to make it start.

Three existing trainer-data copies are candidates for in-place Btrfs extent
deduplication. This preserves each file, path, inode and bytes; it does not
delete training sources, model artifacts or replay data. Fresh `sha256sum` and
full `cmp -s` checks passed for each pair before this plan was written:

| Read-only source | Candidate target | Matching SHA-256 |
| --- | --- | --- |
| `search-dagger-l35-4workers/data/data.bin` | `search-dagger-l35-4workers/student-s0/data.bin` | `6ab86898f321508af3001267e96cff2d81b6ec489bd42cafd3ee17ea28ac28d3` |
| same L35 aggregate | `search-dagger-l4-matched/control-s0/data.bin` | `6ab86898f321508af3001267e96cff2d81b6ec489bd42cafd3ee17ea28ac28d3` |
| `search-dagger-l4-matched/data/data.bin` | `search-dagger-l4-matched/treatment-s0/data.bin` | `ab37d6937c4e83dbcdd05787dccc8ee55db6acc0695cd5c3ae5780a1347c1611` |

Paths above are below `build/flex/sim/levels-v2/pitch82`. Each is exactly
6,520,012,832 bytes. Btrfs reported 6.07 GiB exclusive and zero shared for
each individual file. An initial point-in-time `lsof`/process check found no
matches, but that check ran in a sandbox PID namespace and could not see the
host process tree. It is not evidence that the host files are inactive.

A scratch-only test on this Btrfs filesystem used 2,097,184-byte files,
including the same 32-byte EOF alignment as the candidates. `FIDEDUPERANGE`
shared the equal pair; a one-byte-different target returned DIFFERENT and
remained unchanged and exclusive. The three scratch paths were removed after
the test. No experiment data was changed. If all three real targets can be
shared, the upper bound is about 18.22 GiB freed, putting projected free space
after the planned work around 37.3 GiB. Extent sharing, concurrent writers,
metadata and filesystem accounting can reduce this; remeasure actual free
space rather than assuming the upper bound.

`dedupe-heading-prereq.py` is hard-coded to only these three source/target
pairs. Default/`--check` is read-only; `--execute` must not be run until
independent review and until the GPU and relevant workflows are idle. It takes
the shared experiment lock, requires effective UID 0, the host's initial PID
namespace and host systemd PID 1, checks the Btrfs filesystem, regular-file
type, size, single hard link, distinct source/target inodes and permissions,
then checks `lsof` and all visible `/proc` fd/maps state, failing on an
inaccessible surviving process. It compares every
byte and both SHA-256 hashes, rechecks file signatures, and repeats inactivity
and exact comparison immediately before each kernel dedupe. The kernel also
checks each 16 MiB range for equality. It rechecks all bytes, hashes, paths,
inodes and permissions afterward, and reports Btrfs extents and free space
before and after. A partial ioctl failure stops immediately; files are retained
and must be inspected before retrying. All activity checks are point-in-time;
the lock cannot prevent unrelated or privileged processes from starting. A
host-root process check is required immediately before any actual action;
the ordinary sandbox and an unprivileged host process are rejected before any
candidate file opens. The observed escalated host-user context could not read
`/proc/1/ns/pid`, so it is not sufficient for this guard. If host-root process
visibility cannot be obtained, the dedupe remains blocked.

The script and scratch tests are staged for independent review. **No dedupe of
experiment data has been performed.** No rollout collection or training should
start until actual post-dedupe free space is remeasured and the 64 GiB preflight
passes. No unrelated datasets or copies are in scope.
