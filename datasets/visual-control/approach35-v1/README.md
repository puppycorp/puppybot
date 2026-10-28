# Approach within 35 cm, then return

This corpus expands the four strict-task smoke examples to **128 audited
histories**: 96 fitting trips from six layout instances and 32 validation trips
from two entirely held-out layouts. It contains 11,822 supervised action frames
and 1,263 student-prefix commands replayed with zero error. The packed file is
546,051,104 bytes (about 521 MiB), with sequence length 201 and zero padding.

The generator varies room dimensions,
doorways, spawn pose, brick position/color/size/yaw, box side in open rooms,
and floor color. These remain two families: open rooms and partitioned rooms.

```sh
bash datasets/visual-control/approach35-v1/collect.sh
```

The script builds and freezes the native control/simulator binaries and retained student,
generates and fingerprints scenes, audits a 16-trip layout pilot, then collects
four workers. Half the histories are full teacher trips; half start with 8-32
retained-student commands before teacher recovery. Every valid frame receives
an oracle target, with executed commands stored separately in PVDATA03.
The privileged teacher can read geometry, true pose and target coordinates.
The student receives only camera pixels, its own feedback and recurrent state.

Consumption requires real RGB detection within 0.35 m of the physical robot
base. Box docking and the 300-action episode limit remain enforced. Every
source scene must complete, with failed attempts retained if collection stops.
The aggregate is usable only after the independent RGB/feedback/action/physics/
proximity/docking audit passes. This command does not train a neural network.
It creates its restricted native-tool PATH locally, without depending on a
pre-existing temporary directory. Existing runs are never overwritten.
It requires the shared simulator model and the retained student checkpoint
listed in `protocol.json`, plus a local rendering session. Existing desktop
environment variables are honored.

Generated local artifacts live here under `artifacts/` and are ignored by Git:

- `data128/data.bin`: packed training/validation histories, after completion.
- `verified/result.json`: acceptance receipt covering every selected history.
- `manifest.json`: counts, split, source hashes and episode audit provenance.
- `scenes/`, `catalog.json`: exact geometry, case identities and split roles.
- `runs/{0..3}/expert-*`: sensor PNGs, raw actor inputs, videos and journals.
- `pilot/`: infrastructure checks only; not added as extra fitting histories.
- `dataset.exit`: zero for the completed, verified corpus.

Three primary histories failed physically and five further histories failed
the unchanged RGB projection check. All eight were replaced by audited trips
of exactly the same original scenes. No scene was dropped or moved between
fitting and validation. Failed attempts remain alongside successful sources;
`collection.exit` preserves the original collector's failure status.

`assemble.flex` checks the exact source SHA256 and episode index of each native
audit receipt before copying that history. The original 123 passing histories
retain their individual audits; the five replacement camera views have new
audits. Their coverage includes all 128 final histories and 155,852 physics
increments. A complete native packing check also passed byte for byte.

`artifacts/audited-selection.jsonl` is the final scene-to-source selection.
`finalize.sh` checks all 128 receipts, preserves the 96/32 roles, validates the
packed master, and publishes locally only after those checks pass. Re-running
it on the completed corpus verifies the checksum without changing the data.
The exact original collection recipe is retained in `artifacts/recipe-used/`;
the source collector subsequently received portability and publication fixes.

SHA256: `e45f28097f8f58b00b915b026c921b9013334c3795be205aca0dce2c13c3a148`.

Do not mix older sighting-only demonstrations into this stricter corpus.
Teacher-assisted completions are collection evidence, not student performance.
These are still two room families, mostly forward/right-side targets and
modest spawn-heading changes; arbitrary-house or full360-degree exploration
generalization has not been demonstrated. The first two training runs and
autonomous comparisons are recorded in [training-v1.md](training-v1.md): the
selected checkpoint approached 4/32 validation bricks and 3/8 fresh-test
bricks, but completed no returns. The retained policy remains unchanged.

See [assessment.md](assessment.md) for failures, repairs and verification details.
The recipe refuses to overwrite existing runs; preserve partial attempts and
repair/retry the same scene identities if an attempt fails.
