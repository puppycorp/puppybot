# Fixed full-epoch matched pair, staged only

This isolated scaffold is **not registered or launched**. It refuses to
register until the separate paired one-update smoke has completed with its
guardian, both arm supervisors, final inventory and full saved-output audit
verified. It also re-verifies the paired aggregate lineage and the independent
journal-trainer CPU build. A smoke failure, missing completion or changed input
must stop registration; partial outputs are retained.

The proposed two arms both start from the same original student weights and
fresh Adam state, with 1,031 histories, 935 fitting and 96 validation, batch
two, seed 7120000, learning rate 100 micros, categorical actions, carry cue,
map auxiliary, mirror augmentation, transition weight one, and one epoch.
The fixed checkpoint for each is `epoch-1.bin`, not the validation-selected
`weights.bin`. The control's two added fitting histories use teacher labels;
the treatment uses the parent actions. The verified aggregate says 35 and 31
supervised labels differ. These are previously used development scenes.

The private journal trainer records every actual host batch-send episode ID
and mirror mask, including prefetched and final partial batches. The audit
requires exactly 468 optimizer steps, finite reported losses/gradient norm,
finite nonzero first gradients, changed weights, matching fixed epoch/last
checkpoints, and exact full first/final split/order plus all 468 seeded mirror
masks across arms. It also checks parent initialization, HIP marker, data,
model/kernel hashes and distinct same-device data-copy inodes. Btrfs extent
totals are supplementary and do not prove pairwise extent identity.

The staged guardian uses the shared lock across serial arms and cleanup, a
30-second idle-GPU baseline before each arm, a 38 GiB startup floor, 34 GiB
active floor and 32 GiB emergency escalation. Before each arm it reserves
space for a full unshared training-data copy above the active floor plus
128 MiB. The trainer's audited dataset path requires FICLONE and does not fall
back to copying. The guardian's 7,500-second deadline covers both arms and
the final checker together; each arm's subprocess limit is 7,200 seconds.
Any failed arm or check stops the experiment and preserves partial output.
The final post-guardian read-only audit is disk-bracketed but is not sampled
continuously and does not retain the shared lock.

CPU fixtures: `python3 -B -I experiments/parent-route-full-pair-v1/test.py`.
They use synthetic receipts and files. They do not execute a real trainer,
device graph, optimizer, camera or robot. The smoke receipt, real paired data,
journal build and all plan/source/runtime hashes must be independently
reviewed at registration; the prospective held-out ingestion guard remains
unwired. This work is a training diagnostic and cannot by itself establish
independent-scene reliability, held-out success, physical operation or model
promotion.

The registration performs one deep smoke reconstruction and checks the current
paired data hashes again at the registration boundary. Each intermediate
verification hashes the real control and treatment aggregate datasets and maps
once, and rechecks the exact HIP symlink chain, private build, source pins,
lineage receipts and all small smoke files. It checks smoke data-copy names,
sizes and inode safety there, but defers their full bytes to the deep smoke
reconstruction at registration and the guarded final checker. At the end of
registration, the guarded final checker, and post-guardian verification, both
smoke data copies are rehashed against the sealed smoke final inventory. The
guarded checker repeats the deep smoke audit and verifies all final training
outputs; the independent post-guardian audit rechecks training outputs. The 7,500-second
shared cap is controlling, so two 7,200-second arm limits are not cumulative
guarantees; the final checker also has a 2,400-second subprocess cap. Actual
wall-clock feasibility remains unmeasured until the completed smoke is available.
