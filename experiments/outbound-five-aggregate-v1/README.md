# Five screened teacher prefixes in a copied aggregate

This staged CPU-only builder creates a new `PVDATA04` aggregate containing the
existing 928 fitting histories, the five fitting teacher episodes screened as
helpful in diary 107, and the original 96 validation histories. It retains
all 300 RGB and feedback frames in each new teacher episode and masks action
labels after the first virtual consumption. It never inserts pilot-validation
episodes. The accompanying map histories follow the same order.

`build.py` rechecks the completed pilot's resource receipt, saved-game screen,
output inventory, source chain and current preflight, then binds the baseline
aggregate and map to the pilot student's model receipt. It verifies selected
episode labels and post-action consumption, and requires the exact episode and
cutoff list. It snapshots direct source files, the mask helper, eagerly loaded
local modules and all sources pinned by the completed pilot before and after
creation. These are local consistency checks, not independent execution or
camera attestation, complete model ancestry, semantic scene independence or a
claim of teacher correctness.

The writer exclusively creates a new output directory and requires Btrfs
`FICLONE`: it never hard-links the baseline or falls back silently to a copy.
It moves validation histories backward in the clone to make room, then inserts
the five teacher records. Each write is checked against a 34 GiB active floor;
preflight reserves 36 GiB plus the **full logical output size**, even though
copy-on-write is expected to use less. The final floor is 36 GiB. The separate
`verify.py` checks every preserved data and map byte and every inserted image,
feedback, label, mask and map byte, including ordering and split boundaries.
Inputs are rehashed afterward. No deletion or overwrite is performed. Failed
work can leave partial output for inspection.

`supervise.py` holds the existing advisory `.l4-matched.lock` from before
source verification until a second bounded process completes the independent
byte/order check. Both worker processes run at low CPU/I/O priority and have
absolute deadlines. A fresh supervisor receipt is required: a data report alone
is **not** evidence that final verification passed. The builder directly checks
the free-space floor around its writes, but there is no independent continuous
disk sampler during CPU hashing or rechecks; other disk users can race those
observations. The source chain and copied bytes cannot authenticate a hostile
same-user process or prove the teacher's behavior.

No real candidate aggregate has been created by this preparation. No model has
been trained. The report explicitly sets `trainingAuthorized:false`; even a
completed dataset and verified byte preservation will need a reviewed training
plan, GPU/gradient checks and matched selection evaluation before any promotion.
The direct CLI is disabled; the importable supervisor is not an access-control
boundary and must be invoked in a dedicated process only after independent
review and resource scheduling.

CPU fixture tests:

```
python3 -B -I experiments/outbound-five-aggregate-v1/test.py
python3 -B -I experiments/outbound-five-aggregate-v1/supervise-test.py
```

The tiny fixture intentionally runs on the workspace Btrfs and removes only
its own temporary files. It checks FICLONE source isolation, preserving the
original fitting and validation data/maps, exact selected order and mask,
corruption detection, existing output and hard-link rejection, disk
reservation, pinned-source mutation, the shared lock and both supervisor
stages. The tests do not process the real aggregate or run the trainer.
