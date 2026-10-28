# Targeted forward-contact data

The accepted dataset is
`build/flex/sim/forward-contact-v2/artifacts/data142/data.bin`: 142 complete
histories, split into 112 fitting and 30 validation histories, with a padded
sequence length of 354. All 132 previously accepted histories and their roles
are retained. The file is 1,066,888,064 bytes and has SHA256
`852a80123d19dc45e6ec78587c5ea19c30388d9381c7d634faebb22501f349f9`.

Ten added trajectories passed independent native RGB, feedback, oracle-label,
student-replay, motion, 35 cm approach and docking audits. The frozen student
executes either 60 or 8 actions before oracle takeover, yielding 340 exactly
replayed commands. The fitting student windows supply 232 forward-contact
examples, exceeding the required 200. Independent recording-journal counts
match the native dataset counter. Including the first teacher handoff frames,
the full fitting corpus now has 337 search-phase forward-contact frames,
compared with 97 in the previous corpus. Every such target reverses direction.

The eight new fitting scenes use fitting layout 5 at initial pose
`[0, 0.04, 0.14]`; walls and objects remain byte-identical to their fitting
sources. The two validation scenes retain their original roles and environment
bytes in layouts 6 and 7. Reserved final layouts 10 and 11 are excluded.
The failed zero-coverage V1 cohort was not admitted. Acceptance and source
hashes are recorded in `artifacts/coverage.json`; collection, finalization and
dataset exit statuses are all zero.

Two native Flexscript/Pup CUDA training arms completed 20 epochs each. The
control uses the previous 132 histories; the treatment uses all 142. Both start
from identical checkpoint weights, use the unchanged 324,184-parameter CNN/GRU,
batch size 2, learning rate 0.0001 and seed 131. Corpus sizes produce different
episode orders and optimizer step counts. No augmentation or architectural
change is part of this comparison.

Fixed epoch-10 and epoch-20 checkpoints are evaluated with exact native forward
parity and the canonical eight-case autonomous screen. A return in both open
and hidden rooms triggers paired full-32 validation. Promotion still requires
24/32 returns, at least 8/16 in each room type, and subsequent reserved final
tests. Teacher completion and lower offline loss do not establish autonomous
improvement. The retained policy is unchanged.

Training and evaluation recipes are frozen under `models/recipes/`, with
runtime and recipe hash manifests. Actor inputs remain actual TCP RGB, own
feedback and recurrent memory; the reserved event input is zero. No Python is
required. All four fixed snapshots scored 1/8 audited screen returns, with
0/4 returns in hidden rooms. All 32 episode audits and all four exact forward
parity checks passed. Treatment epoch 20 clears the initial box and reaches
over 3.5 m into the hidden rooms, but does not approach the brick within the
episode horizon. This local behavior change did not improve whole-episode
success. No checkpoint qualified for full-32 validation or reserved final tests.
Training and evaluation terminated successfully; see [results.json](results.json).
