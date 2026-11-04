# Native scene-ingestion guard prototype (4 Nov 2026)

An isolated native fetch-collector variant explores enforcing scene-role
reservations before data collection. It validates pinned synthetic selection
and held-out reservation manifests and denial coverage, rejects reserved seed
overlap even when scene metadata is stripped, snapshots the permitted case,
environment and layout files before dataset allocation, and routes the
collector's scene lookup to those private snapshots. Unsupported collection
and data-ingestion commands fail closed in the private binary.

Twelve CPU tests pass. An independent reviewer reproduced two fail-open
cases—incomplete denial policy and reserved-seed overlap—and verified the
fixes. One test changes the original catalog after snapshotting and exercises
the transformed native scene lookup against the retained copy. These are
synthetic fixtures, not a rendered `ve_open` or GPU collection result.

The real selection and held-out reservation manifests do not yet exist, so
there is a bootstrap problem before this can protect an actual reservation.
The prototype is not wired into active binaries and deliberately rejects the
current fitting-role companion convention. Ordinary collector/trainer
binaries and opaque existing datasets remain unprotected. It also cannot
prove complete ancestry, raw-world semantic equivalence or independent
camera provenance. No real scenes were generated. Artifact:
`experiments/native-scene-ingestion-guard-v1/`.
