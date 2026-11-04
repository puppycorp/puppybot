# Fixed outbound-prefix training preparation (4 Nov 2026)

The five teacher fitting prefixes selected by the monitored pilot in entry 107
are now available in the independently verified candidate aggregate from the
preceding data-build work. This entry records a **training preparation**, not a
trained model, policy gain, held-out pass or physical result.

The planned parent is the exact `student-s1` used by that pilot, with weight
SHA-256 `9c586f40ad6fc1a13a17f325cd3b33da5aca07e4790ee0922fd59049cd89f0d1`.
A single schedule was fixed before training: seed 7120000; one epoch; batch 2;
learning rate 100 micros; categorical action loss; memory-map auxiliary; carry
cue; mirror augmentation; unit speed-transition weight; checkpoint every epoch.
The candidate is the **fixed epoch-1 checkpoint**, never whichever checkpoint
had the best validation loss. The parent's receipt records eight epochs at 700
micros, the same batch, codec, map auxiliary, carry cue, mirror augmentation and
transition weight. This is a lower-rate continuation from the parent's weights,
not a replay: the trainer creates zeroed Adam moments and resets its optimizer
step counter. Five new examples also alter training order, the final partial
batch and loss normalization. An unchanged-parent comparison cannot isolate
the prefix labels from those other changes.

A fresh private CPU build copies the previously pinned heading-training source,
keeps its FICLONE-only dataset-copy path, raises the PVDATA04 limit to 1,030,
and applies the reviewed auxiliary-loss mask only to unsupervised rows in
fitting slots `[928,933)`. The private control invokes its own trainer binary;
shared control/trainer binaries are untouched. It compiled under the existing
low-priority, shared-lock CPU supervisor. Its clone fixture preserved byte
identity and verified shared extents; the supervisor completed cleanly with
`isolated_build_only`. Independent review checked its 601 launch source pins,
compiler, binaries, receipt and CPU/I/O priorities. The private build receipt
SHA-256 is `48f04e3cf747268189ba58143e5a7076f16d2ebf92beef92f3e2737d6fd56c57`.

The real training-input preflight rechecked the supervised data-build receipt,
the pilot's monitored completion, and every preserved or inserted episode byte
and map byte. It reports 1,024 preserved histories, five selected teacher
histories, 1,029 total, 933 fitting and 300 steps. Candidate data SHA-256 is
`765f160e1e07fbc2b9598f57b0f6ea14e2a4782c7b4bf383c20c9ea16b10b272`;
map SHA-256 is
`fc8d693afb2acafc1e3b9e86d30a81c1f43099af21fbdb2f5b3d839148ed4896`.
The resulting preflight inventory binds 141 source/runtime/model files and the
four private-build supervision artifacts. Local hashes and byte comparisons
establish consistency with these files, not raw-camera or OS execution identity.

The proposed evaluation design fixes 32 games on each of five previously used
selection levels, comparing unchanged parent, fixed epoch-1 candidate and
exploring teacher. It requires separate game-completion, first-pickup, doorway,
long-loop and delivery-rate results, and independent reconstruction of the
final-window-inclusive back-and-forth metric. Those scenes are disjoint from
the selected teacher cases by exact source bytes but are training-family data;
the original selection monitor failed. Fresh selection execution and its
catalog-aware resource monitor are not yet integrated or run. The design's
reliability boolean is not itself a quantitative comparator: the future audit
must report parent, candidate and teacher numerators and denominators explicitly.

The build, model-package, schedule and supervisor fixtures passed CPU tests,
including HIP-backend and fit/validation-order rejection. GPU graph/backprop,
actual training and the full 300-step execution remain untested. The training
plan was registered by nested low-priority CPU supervisors, with a 2,400-second
outer deadline and the shared experiment lock. The process exited cleanly
with `plan_registered_only`; its SHA-256 is
`fc20b722234564e0b352f663d144817a128122e35e1cd822c3780083efed65e0`.
The inner and outer completion receipts are retained under
`outbound-five-freeze-cpu-monitor-v1/` and
`outbound-five-freeze-outer-monitor-v1/`. Independent full plan and supervision
receipt readback passed; the canonical input inventory SHA-256 is
`9305df9b1c4d8991a2334a15845fb576aaa678a996fce3f46bcaec3728b100eb`.
Training has not been launched, and a clean build is not a trained policy or
permission to promote one. Artifacts are under
`experiments/outbound-five-trainer-v1/` and
`build/flex/sim/levels-v2/pitch82/outbound-five-trainer-build-v1/`.
