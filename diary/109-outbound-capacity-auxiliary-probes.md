# Outbound candidate capacity and auxiliary masks (4 Nov 2026)

The existing selected model's baseline aggregate has 1,024 episodes: 928
fitting and 96 validation. Five screened teacher fitting episodes would make
1,029 total and 933 fitting. The current trainer and existing prefix-mask tool
cap PVDATA04 at 1,024, so the candidate cannot be used unmodified. Its
projected data file is 6,551,848,832 bytes and map file 44,452,832 bytes,
about 6.143 GiB logical. This is below the trainer's separate 8 GiB mapped-data
limit, but dataset size alone does not prove training compatibility.

A disposable 4 MiB test on the workspace Btrfs confirmed `FICLONE` creates a
distinct inode sharing extents; after a 4 KiB clone-only write, the source hash
was unchanged and the clone showed 4 KiB exclusive. A possible one-pass layout
would clone the baseline, move its 96 validation histories after the five new
fitting histories and write the five new records in between. That would rewrite
about 0.573 GiB of validation history and add 0.030 GiB before filesystem
metadata and fragmentation. These are estimates, not measured physical usage
of the real aggregate. Budget the full 6.143 GiB plus headroom if cloning is
unavailable or behaves differently; preserve the 36/34/32 GiB disk floors.
No real dataset has been copied or modified.

An isolated dataset-source transform raises only the PVDATA04 episode limit to
1,030. Four native copied-trainer CPU tests show its real header/size gate
accepts synthetic sparse 1,029/1,030 datasets and rejects 1,031 while retaining
the legacy-format limit. A separate native host probe exercised the trainer's
actual row validation, map loader, fitting shuffle and both batch loops with
1,029 synthetic one-step histories: all 933 fitting and 96 validation records
were visited with aligned maps, and the incomplete fitting batch was masked.
The probe uses batch two, like the selected model. Source review found the
order array allocated from the episode count; the 1,024 batch-times-length
limit is separate. These tests do not cover the actual 300-step device graph,
prefetch concurrency, gradients or optimizer.

The model used a memory-map auxiliary. Its valid suffix frames would still
supervise that auxiliary even when teacher action labels are masked. A separate
copied-trainer transform now masks phase-from-valid, map, pose and target/heat
auxiliary output supervision on zero-action-mask rows in the proposed new
`[928, 933)` fitting range, preserving their images and feedback and leaving
all baseline rows untouched. Three CPU tests compile the complete transformed
trainer and exercise its actual host batch/loss path with positive baseline
controls, event and pairwise boundary checks, heat absence, and fail-closed
count/split/horizon header checks. The shape check cannot authenticate episode
ordering; a future dataset receipt must bind the exact data, maps, source and
trainer hashes to that range. GPU gradient behavior remains untested.
Adding the five episodes also changes fitting-batch composition and loss
normalization even if every baseline row is byte-identical; baseline behavior
therefore still requires a matched evaluation.

No training, candidate aggregate or new checkpoint has been produced. These
are feasibility probes, not authorization to train or evidence of robot
improvement. Artifacts: `experiments/outbound-episode-cap-v1/` and
`experiments/outbound-aux-mask-v1/`. A direct, provenance-checked one-pass
builder and independently reviewed training plan are still required. Actual
byte-for-byte preservation of the real baseline aggregate has not been tested.
