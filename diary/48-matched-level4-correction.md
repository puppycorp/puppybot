# Matched level-4 correction experiment

The previous mixed L3/L5 candidate delivered 79 times against its parent's 88
across the 32 paired L4 selection games. In the x=1.7 partition group it fell
from 24 to 14 deliveries. The games reuse only three layout/start combinations,
and these are training layouts; they are not independent held-out results.
Some regressions occur on the first same-room pickup and others after an
initial delivery. The diagnosis motivates this experiment; it does not prove
what caused the regression.

Compare continued training of the same mixed `student-s0` checkpoint with
identical optimizer settings and seed. The control uses the original 1024-game
aggregate. The treatment replaces four 32-game L4 teacher shards in their
original positions with 128 fresh student-driven L4, teacher-labelled games.
All 896 other games retain their original order and fitting/validation slots.
The byte audit checks their data, all labels and weights, and maps after teacher
masking; the separate student audit checks all 384 correction games against
their original shards. This tests a **substitution**, including any effect of
the new scenes and trajectories, not a pure increase in L4 data. One training
seed is a pilot, not evidence of consistency across training seeds.
The four replacement shards each contain two validation games, so eight of
the 96 validation games change too. The trainer can select a checkpoint based
on this different validation set. Selected-checkpoint results therefore mix
the training-data substitution with checkpoint selection on different games.
The staged fixed-epoch comparison packages recorded epoch-8 checkpoints as
separate read-only policy copies and compares both at the same epoch. Original
policy directories and their training receipts remain unchanged. The copies
have derived receipts and retain byte-identical original training receipts;
their checksums and read-only modes protect against accidental changes, not
against an owner who deliberately rewrites files. The original receipts did
not separately hash `epoch-8.bin` or `last.bin`, so matching those files and
the epoch-8 training curve verifies present consistency, not independent
attestation of their origin.

After any other GPU job has stopped, from the repository root, run one stage at
a time:

```
bash datasets/visual-control/chase-v1/levels/runs/35-l4-matched.sh pilot
bash datasets/visual-control/chase-v1/levels/runs/35-l4-matched.sh collect
bash datasets/visual-control/chase-v1/levels/runs/35-l4-matched.sh prepare
bash datasets/visual-control/chase-v1/levels/runs/35-l4-matched.sh train
bash datasets/visual-control/chase-v1/levels/selection-pair-l4-matched.sh 4
bash datasets/visual-control/chase-v1/levels/selection-pair-l4-matched.sh 5
```

Once training and any other matched selection are finished, create the fixed
epoch copies and run the separate paired selections:

```
O=build/flex/sim/levels-v2/pitch82/search-dagger-l4-matched
python3 -I datasets/visual-control/chase-v1/levels/package-matched-epoch8.py create "$O/control-s0" "$O/treatment-s0" "$O/epoch8-pair"
bash datasets/visual-control/chase-v1/levels/selection-pair-l4-matched-epoch8.sh 4
bash datasets/visual-control/chase-v1/levels/selection-pair-l4-matched-epoch8.sh 5
```

The pair was created and independently verified from the completed runs; its
control and treatment checkpoint SHA-256 values begin `e7c759b24cfd` and
`1279597b3569`, respectively. The create command above refuses to overwrite
that existing pair; use the packager's `verify` mode to recheck it.

The shared lock rejects packaging while another matched stage is active; a
failed no-overwrite publication retains its partial directory for inspection.
The fixed-epoch selections have not run, and their training-layout results will
not be held-out qualification or physical-robot proof.

The pilot has one worker and two games, never enters the full dataset, and must
pass provenance, label-disagreement and aggregate-preservation checks. The
full collection uses four workers and 32 games per worker, original teacher
and student sources are audited, and both arms begin with identical initial
weights. Input, source, audit, dataset and model files are hashed. The runner
uses a clean environment, captures the key executables, kernels and scenes,
and checks the pinned previous inputs. It refuses to overwrite existing pilot,
collection, partial preparation or incomplete model data. It requires 35 GiB
free at stage start and 32 GiB before each model; it never deletes source data
or model copies. The checks are guards, not a reservation against other disk
users. On this host there was approximately 57 GiB available when staged;
recheck before use. Each model can contain a roughly 6.1 GiB data copy.
One persistent advisory lock file covers all pilot, full and selection stages;
the file itself remains after the process exits and does not indicate a stale
running job. After both models finish, the audit compares initial weights,
first/final ordering, the first recorded mirror mask and per-epoch optimizer
and aggregate mirror counts. This does not prove every intermediate shuffle
or individual later mirror decision was identical.

The selection games repeat the existing 32 training-layout scenes and seeds.
They are intended to assess the L4 tradeoff and L5 retention, not to qualify a
model. The exact-argv/actor-input attestation and independent held-out evaluator
remain unvalidated and disabled. Previous collection declarations and hashes
cannot establish old executable identity or pretrained ancestry, nor prove
physical pickup and return. Never use the result as a physical-robot success
claim. Synthetic CPU fixtures, lock contention, and shell syntax were checked
before launch. The two-game pilot then passed the source, teacher-label and
mixed-data preservation audits (66 source games and 34 student-driven games
checked). Full collection then completed all 128 games without logged stream
timeouts. The prepared dataset passed the byte-level audit: 896 unchanged
game slots and maps, 128 replaced slots, and all 384 student-driven games'
images, feedback, labels and maps preserved. The two sequential training
runs completed. The recorded initial weights, first/final ordering, first
mirror mask and aggregate per-epoch mirror counts matched; this does not prove
every later individual random draw matched. Both selected weights differ from
their respective epoch-8 checkpoints. Selection comparisons are in progress;
the changed validation games make a fixed-epoch comparison necessary as well.

The validation-selected L4 pair passed its selection audit. Control and
treatment each had a delivery in 26/32 games; they delivered 30/55 and 28/55
past-doorway bricks, respectively. Room entry was 39/55 versus 38/55;
deliveries/min were 2.50 versus 2.625 and back-and-forth share was 2.69%
versus 3.86%. This single model pair does not establish a treatment benefit,
and the selected checkpoints were chosen against different validation games.
The pair is retained under `search-dagger-l4-matched/selection-L4`.

Separate read-only epoch-8 control and treatment packages were created and
verified after both source-model and package checks passed. Original model
directories and receipts were preserved. Their fixed-epoch L4 selection
comparison was started. Because the original training receipts did not hash
the epoch-8 snapshots separately, matching the current epoch and final files
establishes present consistency, not independent proof of their production.

The fixed-epoch L4 selection pair passed its audit. Control versus treatment
delivered 34/58 versus 35/62 past-doorway bricks, entered 47/58 versus 43/62
and scored 2.531 versus 2.563 deliveries/min. Games with a delivery were
28/32 versus 26/32; back-and-forth shares were 3.98% versus 3.07%. These
results do not establish a treatment benefit. They are one model pair on
reused selection scenes; eight validation games differed during training,
but this comparison uses the same final epoch for both arms. The artifacts
are under `search-dagger-l4-matched/selection-epoch8-L4`.

The fixed-epoch L5 pair also passed its audit. Both arms delivered in 20/32
games, at 0.750 versus 0.781 deliveries/min; back-and-forth shares were
6.72% and 6.00%. The treatment entered the brick's room in 21/32 games
versus 32/32 for control, with first pickups 20 versus 26. In the repeated
x=1.7 environment group, entries fell from 11/11 to 0/11; these cases share
an environment and starting view, so they are not independent layouts. The
substitution does not show a clear overall benefit and may harm this search
behavior. Artifacts are in `selection-epoch8-L5`; further seeds and independent
scenes would be required for generalization.

An offline trace diagnostic of the treatment's repeated x=1.7 cases found
mobile search rather than stationary rocking: the median search visited 65
distinct 0.25 m cells, and about 19% of cell transitions re-entered a
previously visited cell. One representative traveled 17.99 m but ended
0.62 m from its start without reaching the other room. This is not a clean
causal comparison with control: its search windows end at different pickup
times, and the cases share a starting view and environment. A stationary-image
guard alone would not address this route failure.
