# Five teacher-prefix aggregate preparation (4 Nov 2026)

A new CPU-only builder has been staged for the five helpful fitting episodes
from the independently audited pilot in entry 107. It would preserve all 928
existing fitting histories and 96 validation histories, insert teacher
indices 3, 4, 5, 6 and 8 at aggregate indices 928–932, and keep labels through
first virtual consumption at actions 162, 107, 171, 43 and 38 respectively.
It retains subsequent image/feedback history but masks subsequent action
labels. Pilot-validation examples are excluded.

The builder re-audits the complete pilot and its monitor receipt, binds the
original 1,024-episode data and map hashes to the selected student model
receipt, and rechecks source identities after writing. It clones baseline
files with Btrfs FICLONE, shifts validation episodes backward to their new
positions and inserts the five records. A separate byte verifier checks all
preserved data and map bytes and the selected images, feedback, actions,
weights and maps. The supervisor holds the shared experiment lock, requires
36 GiB free plus the full candidate size before starting, checks a 34 GiB
floor around writes, and runs the writer and independent final verifier in
separately bounded low-priority processes. It requires a fresh completion
receipt and never overwrites existing outputs. It does not independently
sample disk during long read-only hashing, and file hashes do not attest
execution or protect against an adversarial same-user process.

Ten small Btrfs fixture tests and three supervisor tests passed. They cover
clone isolation, fit/validation preservation, selected masks and map order,
corruption and aliased input rejection, disk reservation, source-pin changes,
lock contention and both supervision stages. A separate read-only preflight
re-audited the actual pilot and selected the expected five identities; no real
aggregate has been built. The prototypes and tests are in
`experiments/outbound-five-aggregate-v1/` and still require independent review
before any actual dataset creation. No GPU training, model evaluation or
physical robot test has occurred, and the staged data does not authorize
training by itself.
