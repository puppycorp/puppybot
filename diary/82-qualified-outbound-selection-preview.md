# Outbound teacher episode selection: non-authorizing preview (3 Nov 2026)

The pilot described in entry 77 has not run, and its feasibility screen does
not authorize training. The outbound-prefix tool in entry 79 now supports a
caller-supplied per-episode filter for candidate-data preparation. It requires
the exact teacher shard data and report hashes and each selected fitting
episode's index, seed, result, initial state, event and decision hashes. It
excludes unselected teacher episodes, including all teacher-validation
episodes, while retaining other shards' existing split, recurrent frames and
aligned maps. It rejects changed evidence, duplicate shards, wrong seeds and
selected teacher episodes with no virtual consumption. Its report explicitly
sets `selectionQualityVerified:false` and `trainingAuthorized:false`.

A separate read-only pilot preview invokes the actual saved pilot audit and
its unchanged preregistered screen; it does not accept caller-supplied helpful
flags, write an aggregate or authorize training. It snapshots the pilot
evidence before and after audit, including catalog, maps, policy files and
presence of optional logs, and binds the already-frozen current selection
manifest and the local selector sources. It extracts only individually
helpful fitting games, with their evidence hashes. The pilot auditor does not
yet verify an outer resource-monitor receipt, so preview explicitly reports
that the monitor is unverified and the output is unusable for training.

The proposed pilot and the current five-level selection reuse layout families
13, 15 and 17. Across the current frozen comparison, six of nine pilot fitting
cases and all three pilot-validation cases have the same `(layout, variant)`
as a selection case. A separate, **post-hoc** preview filter excludes exact
matching fitting cases and records those exclusions; it does not change the
pilot's original feasibility screen. The preview also refuses a selection
unless the remaining fitting examples still meet the original minimum count
and layout-family count. Only three fitting cases remain after the exact-match
filter, so all three would need to be individually helpful. Distinct variants
still reuse layout geometry: this filter does not establish scene independence,
does not check every historical selection, and is not a predeclared
promotion gate.

Sixteen CPU mask tests and nine preview tests passed, including native-format
split and map preservation, changed episode evidence, validation exclusion,
duplicate and wrong identity checks, a changed frozen selection manifest,
and a screen that passes before filtering but has too few examples afterward.
Independent review repeated the tests. No pilot collection, real derived
aggregate, model training, held-out evaluation or GPU trial was performed.
Before any data use, a separately reviewed integration must verify the outer
monitor, preserved-shard provenance and aliasing, stable evidence across
output creation, and a genuinely independent evaluation boundary.

Artifacts: `experiments/outbound-prefix-mask-v1/mask.py` and
`experiments/outbound-prefix-mask-v1/pilot-selection.py`.
