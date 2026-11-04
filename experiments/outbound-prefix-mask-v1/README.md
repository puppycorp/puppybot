# Teacher first-acquisition label masking

This standalone CPU tool derives a **new** `PVDATA04` whole-episode
aggregate from an existing `map-aggregate` output and the exact ordered source
shards. Explicit `teacher-prefix` shards must be recorded as teacher-driven
exploring-fetch data. `preserve` shards remain unchanged. It never modifies
the input files and refuses an existing output path.

For each selected teacher game, the tool reads all 300 saved post-action
decision states. It keeps existing supervised labels through the action whose
response first reports virtual consumption and sets later supervision weights
to zero. If no consumption is recorded within the horizon, it excludes the
whole teacher game rather than making an all-zero-label episode that could
produce an empty training batch. It does not turn an existing zero mask back
on. All other games remain byte-identical. It preserves each retained game's
entire 300-frame image and feedback history, including frames after the
masked labels, and preserves PVDATA04's independent valid-frame field at
offset 44. If supplied, the matching aggregate map file is filtered and
reordered with the same retained episodes. The fitting/validation partition
is recomputed and an invalid or empty split is rejected.
At least one fitting teacher-prefix game with a retained action label is
required, so a validation-only or all-miss teacher shard cannot silently
produce an unchanged preserve-only training aggregate.

Before writing, it validates the aggregate's ordered image and row bytes
against the source PVDATA01 shard files, source checksums and reports, game
seeds, initial unconsumed state, saved decision actions, and virtual task
transitions. Episode directories and evidence files may not be symlinks or
resolve outside their declared source shard. When a map is supplied, it also matches each aggregate map
episode to its source shard map in fit-first order, verifies recorded map
checksums, and requires all-unknown map bytes for shards with no map. It
snapshots and rechecks the inputs, refuses output overwrite or an output
inside an input tree (including through a symlinked parent),
reserves the estimated output size plus 32 GiB of free space on the output
filesystem, checks the floor around each episode write and before publishing,
and verifies the output data and map bytes before writing its hash receipt.
The per-episode checks cannot prevent another process consuming space between
observations. The check supports only full 300-action, zero-burn-in aggregate
windows; it does not infer arbitrary window-to-episode mappings. A failed
write can leave an incomplete output directory for inspection; lack of
`report.json` means it was not successfully published.

This is **candidate data preparation**, not an approval to train. Source
provenance, selection/held-out exclusion, episode-quality criteria and a
matched training plan must be established separately. In particular, this
tool does not reject every poor outbound path or independently attest that
the teacher labels are correct. The teacher uses reference wall geometry.
Historical selection cases must not be fed back into training merely because
this tool can read them.

For a future screened pilot, the Python `create` API can accept an optional
`teacher_selection` mapping. Each explicitly named teacher shard must bind
its `data.bin` and `report.json` SHA-256 and a list of exact `(episode, seed)`
identities, each with hashes for its result, initial state, start/events and
decisions. It rejects duplicates, altered hashes, non-fitting teacher
episodes and selected games without virtual consumption; all other teacher
episodes are excluded. In particular, pilot-validation teacher games are
not inserted into fitting data. Non-teacher shards retain their original
fit/validation split and require separate provenance and leakage checks. The
selection is caller-provided and is **not** evidence that the episodes passed
a quality gate; the direct CLI intentionally has no selection option.

The separate `pilot-selection.py` module provides a read-only preview only
after invoking the actual saved-game pilot auditor and rechecking the pilot
preflight and evidence hashes, including policy files, catalog, map data and
presence or absence of optional audit logs. It records its own source hashes
and binds the already-frozen current selection manifest before and after the
audit. It extracts only screen-helpful fitting
identities and excludes all pilot-validation teacher episodes. As an additional
post-hoc guard, it excludes helpful fitting episodes whose exact
`(layout, variant)` appears in the current selection design and reports each
such exclusion, along with other non-helpful or pilot-validation exclusions;
it does not change the pilot's preregistered feasibility gate. Separately, the
preview refuses to return a selection unless the remaining helpful fitting
episodes still meet the pilot's minimum count and layout-family count. This
additional filter was chosen after the pilot was designed and is not a
predeclared training or promotion gate.
The pilot and current selection nevertheless reuse the same layout families
and underlying geometry, so this filter does not establish scene independence.
The pilot has
not run, its screen explicitly does not authorize training, and its auditor
does not yet verify an outer resource-monitor receipt. Therefore the preview
always says `outerMonitorVerified: false` and `usableForTraining: false`;
it does not write an aggregate or offer a training path. Future qualification
must separately verify the monitor, preserved shards, selection and held-out
boundaries, and stable filesystem identities, including reauditing full pilot
evidence across output creation. The generic selection API does not verify
quality or detect preserved shards that alias teacher data. The pilot-validation cases have
already influenced its feasibility screen and are not independent evaluation.

The current `train.flex` path reads PVDATA04 valid frames separately from
the action-supervision mask and copies all image and feedback rows into the
batch; its row checker allows a zero-supervision suffix. Its default phase
loss uses the supervision mask too. However, `--phase-from-valid` and enabled
auxiliary losses can still supervise valid masked suffix frames. Configure and
audit these separately. `pack-data` has stricter supervision-order checks and
must not be assumed compatible with this output. No real trainer, gradient or
GPU behavior was tested here.

Example only, after separately preparing and auditing fresh training inputs:

```
python3 -B -I experiments/outbound-prefix-mask-v1/mask.py \
  --aggregate NEW_AGGREGATE/data.bin --map NEW_AGGREGATE/map.bin \
  --output NEW_DERIVED_DIRECTORY \
  --shard teacher-prefix NEW_TEACHER_SHARD \
  --shard preserve NEW_STUDENT_SHARD
```

The shard order must match the original `map-aggregate` command, not the
aggregate's resulting fit-first order. Omit `--map` only if no map will be
used by training. A separate output with fresh paths is required.

Run CPU fixture tests with:

```
python3 -B -I experiments/outbound-prefix-mask-v1/test.py
python3 -B -I experiments/outbound-prefix-mask-v1/pilot-selection-test.py
```

The fixture tests, including native-format 300-action cases, cover cutoff
indexing, excluded misses, fitting/validation and map alignment, unchanged
frames and feedback, prior masks, overwrite and bad-source rejection,
transition validation, a shuffled-map rejection, detached episode paths,
simulated disk depletion and output readback. A separate disposable `/tmp`
compatibility check used the existing native `map-aggregate` with the two
archived teacher and two archived student pilot games: it retained the
teacher's 259-action prefix, excluded the teacher miss, and kept three games
(two fitting, one validation). That was a format check only; the prior pilot
failed its expansion gate, and those files were not used for training. No
large dataset was copied persistently and no GPU was used.
