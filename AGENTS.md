when making changes always try to match coding style of surrounding code.

If you make changes to android folder run the build.

In rust code functions inside the file should be sorted by the dependency graph for example main goes to bottom and above it comes things it calls etc...

The maintained robot implementation is under `src/`, organized by component.
Use `src/` paths for new code and documentation; `flex` is only a compatibility
symlink for historical experiments. Rust under `tests/reference/rust-core/` is
a test oracle, not a second production stack. Keep existing experiment output
paths and frozen provenance records unchanged during source reorganizations.

## Experiment storage

Treat disk as a limited experiment resource. `build/flex/sim` contains research
datasets and replay evidence, not just disposable compiler output. These rules
apply to generated outputs anywhere in this checkout and to outputs placed
elsewhere by its experiments. Do not move outputs to `/tmp` to evade a budget.

### Budgets and launch checks

- Initial local generated-output budget: 500 GiB total, including datasets,
  checkpoints, recordings, logs and compiler caches. This is a retention target
  for the existing backlog and a ceiling for new experiments. While above it,
  do read-only analysis and cleanup planning; do not launch data-producing runs.
- Reserve at least 100 GiB free on each filesystem used by a new experiment,
  after accounting for its estimated peak additional writes and other running
  jobs' remaining allocations. Include temporary aggregates, copies and final
  checkpoint writes in the estimate. Unknown output growth is not a valid plan.
- Default peak additional allocation per experiment is 25 GiB. Start with a
  small pilot to measure bytes per episode before expanding. Record a justified
  larger allocation in the run plan before launch; it must still fit the total
  budget and free-space reserve.
- New or revised runners must check space before allocation and between shards
  or epochs, with a runtime monitor for long writes. Stop writers cleanly if
  free space falls below 75 GiB or the run exceeds its allocation, and record
  the incomplete status. Never silently lower limits or start another run after
  a storage stop. Existing runners with smaller floors need updating before reuse.
- Record planned peak bytes, measured output size, dependencies, retention class
  and review date in the run plan/result. Account for all concurrent jobs together.
  Use allocated `du` sizes as a conservative budget measurement; on Btrfs also
  inspect shared/exclusive extents for cleanup candidates. Do not claim apparent
  file size as reclaimed space: verify actual filesystem free space afterward.

### What to retain

- Keep a small result record for every experiment: hypothesis, exact commands,
  configuration and seeds, source/binary/input hashes, metrics, conclusion and
  artifact locations. Hashes alone do not preserve an input or prove replayability.
- Explicitly pin the current baseline, selected candidate and inputs/evidence
  needed by active or planned runs, including transitive dependencies. Pins need
  a reason and review date; review them when an experiment finishes. Protected
  data still counts toward the budget. If it does not fit, reduce the experiment
  scope or verify an external archive before removing its local copy.
- For new runs, retain the selected checkpoint and latest resumable checkpoint,
  plus any checkpoint required by a comparison or dependency. Avoid retaining
  every epoch or embedding a full dataset in every model package. Share immutable
  inputs by reference or verified reflink where the existing verifier permits it.
- Keep full recordings only when required for the experiment's replay/audit.
  Otherwise default to metrics and at most three representative success and
  three failure recordings per run; bounded diagnostic logs should not grow forever.
- Scratch files and derived aggregates become cleanup candidates after their
  consumer finishes and verification succeeds. Failed or superseded runs get a
  retention review within seven days. Age and poor scores alone do not authorize
  deletion, and neither does a path being ignored by Git.

### Closing a run and cleaning the backlog

- Closing an experiment includes a storage review: retained bytes, pinned paths,
  disposable paths, next review date and any loss of replay capability. Do not
  keep adding new experiment generations without retiring old bulk outputs.
- Before deleting existing research artifacts, prepare an exact path list with
  reclaimable-space estimates and consequences, check live writers/readers and
  dependency references, and obtain explicit deletion authorization unless that
  exact scope is already authorized. Preserve unrelated work and result records.
- Call an aggregate reproducible only after a byte-identical reconstruction was
  verified from retained inputs and tools. Otherwise explicitly record that
  deleting it loses exact replay, even if a generation script survives.
- Prefer retiring verified duplicate copies and unnecessary recordings before
  unique datasets. Verify an archive's manifest/checksums and restore before
  treating it as a replacement. Never delete a whole `levels-v*` tree by age.
- These are repository workflow rules, not an installed disk quota or automatic
  cleanup service. Keep historical frozen plans/receipts unchanged; apply runtime
  enforcement in a new runner version rather than rewriting past evidence.
