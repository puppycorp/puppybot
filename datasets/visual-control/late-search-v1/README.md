# Longer on-policy search corrections

The latest forward-contact model clears the initial box but fails later in
search. A two-scene pilot lets that model execute 120 actions, labels its actual
observations with the privileged oracle, then hands control to the oracle to
finish the trip. Both physical trips completed and passed the unchanged native
audit: 434 total commands, 4,928 motion increments and 240 student commands
replayed with zero error. The packed pilot SHA256 is
`40c6c8a925353912d2361ddada56ec9410cdc878210ec38095c7bd1374c6a555`.

In the fitting trip's second 60-action window, the model disagrees with the
oracle on 56/60 actions. It reverses on 33 frames where the oracle chooses
forward. The native diagnostic reads separate oracle and executed actions from
the audited PVDATA03 file. This is useful correction coverage; teacher takeover
does not establish autonomous success. Pilot artifacts are under
`build/flex/sim/late-search-v1/`.

The predeclared collection contains 24 fitting scenes, four from each of
layouts 0–5, plus six validation scenes in layouts 6/7. Each fitting layout has
two original starts and two starts at `[0, 0.04, 0.14]`; all walls and objects
retain their source bytes. Validation environments retain their original bytes
and roles. Reserved final layouts 10/11 are excluded. The catalog is
`catalogs-v2/`; the earlier `catalogs/` directory retains an unsuccessful
preparation attempt that used a nonexistent source path and contains no trips.

Collection uses 120 student actions followed by oracle recovery, a maximum
512-action horizon and three simultaneous native simulators. Every declared
scene must complete physically and pass independent RGB, own-feedback, label,
student-replay, motion, 35 cm proximity and docking audits before admission.
Failures remain recorded. Fitting-only coverage must include at least 300
oracle disagreements after action 60, spanning at least eight fitting histories
with 20 such disagreements each.

The intended aggregate retains all 142 accepted histories and adds all 30 new
histories, preserving 136 fitting / 36 validation roles. It is not admitted
until `artifacts-v2/dataset.exit=0` and `coverage.json.passed=true`. Native merges,
exact repacking, role/source guards and frozen artifact hash checks enforce
that boundary. No dataset or autonomous performance claim follows from this
collection plan alone.

The original first three workers physically completed all 15 trips, but the
camera audit rejected worker 2's validation scene (layout 6, scene 4). Its
reported detection covered a purple robot part rather than the actual brick
projection. The original recordings, rejected audit and failure statuses remain
under `artifacts/`; no training started from that attempt.

The four fitting histories from that worker passed a separate native audit
covering 812 commands and 480 exact student replays. They were retained without
re-recording. A new teacher approach (side 0) re-recorded the same validation
scene, seed 9622004 and 120-action student window. It completed in 210 actions
and passed the original strict audit. The two-episode collector also recorded
a duplicate fitting partner, which is retained as a diagnostic and excluded
from admission. `replace-validation.flex` selects only the repaired validation
history and all four original fitting histories. The resulting five-history
batch passed its complete native audit: 1,022 commands, 11,690 physical motion
increments and 600 student commands with zero replay error. Its packed SHA256
is `8c2ce988c58e5ad3340aef76c579ca06551cc27953ef5117d644d02548a67172`.

The resumed collection and subsequent admission use `artifacts-v2/`. Separate
frozen recipes and terminal-status files preserve the rejected attempt. Neither
the RGB audit nor the approach/docking thresholds were changed. The final three
workers retain the original scene catalog, seeds and teacher settings.

All 30 declared trips are now accepted. The new cohort passed checks covering
6,391 commands, 72,730 physical motion increments and 3,567 exact student
replays. Fitting-only later coverage is 1,230 oracle disagreements, with at
least 20 in 23 of 24 fitting histories. Native merges retained all previous
142 histories; exact native repacking and negative source/role guards passed.
The admitted `artifacts-v2/data172/data.bin` has 172 histories, split into
136 fitting / 36 validation, sequence length 354 and 1,292,286,944 bytes. SHA256:
`05032e0eb2a4a98a7f0146db66195792b2c22fe3bda3138039e9c721bc69b284`.
Collection, finalization, dataset admission and the resumed watcher all exited
successfully. The original rejected statuses remain unchanged.

The native file reader now permits up to 2 GiB so aggregation can preserve full
histories. Episode, sequence and GPU batch limits are unchanged. The native
size test maps, packs and forwards a valid 1,081,914,656-byte sparse dataset,
preserving all 144 histories and roles. Both workflow and trainer reject files
above 2 GiB; malformed-data guards still pass. Old and rebuilt trainers produce
byte-identical initial weights, gradients, first optimizer update and final
weights on the audited pilot. Losses also match exactly. These reader checks
do not measure robot performance.

The paired comparison is training under `models/`, using the same current model as initialization,
unchanged CNN/GRU architecture and fixed epoch-10/20 snapshots. It compares
continued learning on the previous 142 histories with the accepted 172-history
aggregate. Canonical autonomous screens, paired full-32 validation and reserved
final gates remain unchanged. The actor receives TCP RGB, own feedback and
recurrent memory; maps, poses, targets and event hints remain outside its inputs.

Both fixed epoch-10 checkpoints scored 0/8 complete returns and 1/8 approaches.
At epoch 20, the control remained 0/8; the expanded model scored 1/8 returns and
3/8 approaches, including its first hidden return. All 32 fixed-snapshot audits
and four exact native forward checks passed. Standard loss-selected outputs
(control epoch 8 and expanded epoch 1) each scored 1/8 returns and 1/8 approaches;
all 16 additional audits and both forward checks passed.

The broader [full-32 transfer check](../transfer-v1/README.md) found 2/32 returns
for the expanded model versus 3/32 for the previous policy, despite reaching
9 bricks versus 6. No overall completion improvement is demonstrated. Training
and these evaluations are complete; the production policy remains unchanged.

`phase-probe.flex` reads the auxiliary phase head on an exactly replayed,
already audited autonomous hidden-room failure. Across all 300 search frames,
the original model predicts return probability above 0.5 on 189 frames and
above 0.9 on 138. However, its first reverse occurs at action 34 with return
probability only 0.0144. This diagnostic shows poor later phase calibration;
it does not establish that the phase estimate causes the reverse behavior.
The flat actor does not directly consume this readout. Native results remain
in `phase-hidden-before/result.json`; no actor inputs or weights are changed.

The complete-history consistency diagnostic hashes each actual RGB/feedback
prefix, then checks whether identical histories receive different oracle
classes. The accepted corpus has 19,475 fitting and 5,164 validation supervised
frames. Exact fitting conflicts affect 559 frames across 167 history groups;
choosing each group's most common label still incurs 213 errors (1.09%). The
validation lower bound is 82 errors (1.59%). These are conservative bounds for
exact duplicates, not a measurement of all perceptual ambiguity or task
failure. Reports are `prefix-labels.jsonl` and `prefix-ambiguity.json` in the
build directory. This check does not justify attributing the whole performance
gap to contradictory labels.
