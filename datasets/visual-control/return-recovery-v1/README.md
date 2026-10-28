# Late student recovery dataset

The accepted corpus is now `artifacts-primitive/data96/data.bin`: **96 histories,
72 fitting /24 validation**, 12,992 supervised frames and sequence length354.
The file is721,276,448 bytes. SHA256:
`a4dd1b61727f82e7ed044ebaf89268509cf47631a1392f7caa8249d826f3d6f8`.

The original32-trip attempt completed30 physically. Two start-room recoveries
oscillated, and a further history failed the unchanged RGB projection audit
because the gripper hid most of the brick. All three were replaced by audited
histories of exactly the same scenes. The original `collection.exit` remains1;
`finalize-selected.exit` and `dataset.exit` are0. Nothing was dropped or moved
between fitting and validation. Exact source hashes and episode coverage are
checked by `assemble-selected.flex`, followed by native merging and an identical
native repack. Negative checks rejected a duplicate scene, substituted scene
and wrong-episode audit receipt. See `artifacts-primitive/coverage.json` and
`manifest.json` for complete provenance.

The fitting split now contains1,341 contact frames and2,626 cases where the
oracle target differs from the executed action, among9,693 supervised frames.
The earlier128-history fitting split had only4 contacts among8,917 frames.
This is improved recovery-state coverage. Both matched80-epoch training runs
and their32-scene autonomous validation runs have now completed under
`build/flex/sim/approach35-v2/recovery-primitive-models/`.

## Autonomous results (2026-10-27)

Both models used72 fitting histories and24 validation histories, batch2,
learning rate0.0001, seed89 and the same initialization and episode order.
The fixed epoch80 snapshots produced:

| Model | Audited brick approaches | Completed approach and return | Open layout | Hidden-brick layout | Rejected audits |
| --- | --- | --- | --- | --- | --- |
| Direct action | 5/32 | 3/32 | 3/16 | 0/16 | 1 |
| Learned phase gate + camera-event auxiliary | 5/32 | 3/32 | 3/16 | 0/16 | 0 |

The direct-action rejection was scene14 in layout6: the reported consumption
bbox did not contain the actual brick projection. Its recording and failed
audit are retained, and it counts as a failed episode. The original evaluator
stopped there; a separate continuation completed the remaining cases without
relaxing acceptance. All32 recordings in each arm completed. Training/export
logits and recurrent state matched exactly for both models.

The earlier retained baseline completed0/32 on the same scene bytes and seeds;
its32 native audit receipts were rechecked. The new models remain unreliable,
particularly in hidden-brick rooms, and neither passes the promotion gates.
The retained policy is unchanged and final layouts10/11 remain unused.

All three successful direct-action cases failed when their actor RGB inputs
were zeroed. This is a visual-dependence diagnostic on selected positive cases,
not an aggregate performance estimate. A successful normal recording is
`build/flex/sim/approach35-v2/screen-primitive-flat80/0/8900000/mission.mp4`
(22 seconds, including initial camera setup). Full results, hashes, timings
and audit counts are in [results-primitive.json](results-primitive.json).

The current collection uses the corrected primitive timing consistently:

```sh
bash datasets/visual-control/return-recovery-v1/collect-primitive.sh
bash datasets/visual-control/return-recovery-v1/train-primitive.sh
```

These write `artifacts-primitive/` and
`build/flex/sim/approach35-v2/recovery-primitive-models/`. The independent local
evaluator is `build/flex/sim/approach35-v2/evaluate-primitive.sh`. The initial
collection under `artifacts/` is retained as an earlier attempt; it exposed
two teacher failures and must not be published as the accepted aggregate.
The 12 pilot/regression histories passed audit with 1,474 student commands
replayed exactly. All32 scene identities and split roles remain unchanged.

This experiment targets failures from the first strict-task model: incomplete
returns, repeated reversing into walls and failure to depart through a doorway.
The 35 cm brick approach, physical docking conditions and student input boundary
remain unchanged. Collection success is teacher-assisted evidence.

```sh
bash datasets/visual-control/return-recovery-v1/collect.sh
```

The collector requires the existing audited `approach35-v1` corpus, the
experimental `approach35-train-v1/policy-warm5` checkpoint and the completed
native recovery pilot under `build/flex/sim/approach35-v2/`. It builds native
binaries, runs the control/action/oracle/swept-motion/proximity contracts and
freezes the runtime and student. Its private tool PATH contains no Python.
A local rendering session is required; the simulator windows remain hidden.
Existing output directories are refused before installing an exit-status trap.

Four workers each collect eight histories, with six fitting and two validation
scenes. All fitting layouts remain 0–5; validation uses 6 and 7. Layouts 8–11
never enter this dataset. Source case and environment bytes are preserved.

- Two workers let the student drive the initial 90–150 actions (18–30 s).
- Two workers first use the oracle to approach and consume the brick, then let
  the student attempt the return for 90–150 actions. The network processes the
  complete teacher approach so its recurrent history contains actual RGB and
  executed-command feedback throughout.
- The teacher then recovers and docks. Every real input has an oracle target
  separate from the actual executed action. The reserved event input stays zero.
- The teacher routes return trips through a waypoint behind the original spawn.
  Its first planned primitive receives the same one-millimetre swept collision
  checks as physical execution, including intermediate physics ticks.

Every new history must complete physically and pass native camera/input,
label, frozen-student replay, motion, proximity and docking audits. Failed
attempts stop publication and remain available for repair of the same scene.
No scene may be silently dropped or reassigned between fitting and validation.

After collection, native tools combine the 32 new histories (24 fitting / eight
validation) with 64 unchanged base histories (48 /16). The base sample takes
scene indices 0–7 in each of the eight original layouts, preserving their roles.
The 96-history result contains 72 fitting and 24 validation histories. The full
original 128-history corpus remains intact. Native merges preserve all valid
steps and recurrent history; no expert or student sequence is truncated.

The base sample reuses exact-SHA native source audits. New source audits cover
each packed correction batch. `coverage.jq` follows actual merge receipts and
checks source hashes and episode indices through the final dataset. A separate
native repack must match the aggregate byte for byte. `artifacts/data96/` is
published locally only after all gates and runtime/scene/recipe checks pass.
Large recordings, data and checkpoints stay ignored by Git.

```sh
bash datasets/visual-control/return-recovery-v1/train.sh
```

The training launcher freezes its native trainer, kernels, policy binaries,
graphs and initial checkpoint. It can start while collection is running: it
waits for an accepted dataset and stops if collection exits without one. It
then trains flat and learned-phase/event variants for 80 epochs with matched
data, initialization, learning rate and episode ordering. Each arm writes
fixed epoch-20 and epoch-80 snapshots. The local experiment's independent
rollout evaluator is `build/flex/sim/approach35-v2/evaluate-recovery.sh`; loss
alone does not select or promote a policy.

The pilot accepted eight histories with 1,054 student commands replayed
exactly. An original doorway recovery exhausted its horizon; replay of the
same physical scene exposed a box-corner collision missed by coarse planner
endpoints. The swept first-primitive fix completed both affected pilot scenes,
which then passed the unchanged data audit. Native tests also reject forged
early/late return handoffs and retain compatibility with old prefix receipts.

The initial architecture-only trial (learned search/return heads plus a
camera-event training auxiliary on the original corpus) completed 80 epochs,
but achieved 0/8 returns on its fixed validation screen. A one-fitting-scene
learnability diagnostic completed in 13 driving seconds; that is deliberately
not held-out evidence. The recovery-corpus results above establish a few
autonomous completions, but no reliable improvement across both room types.

See `protocol.json` for the fixed scenes, split rules, training recipes and
held-out selection gates. Further results and artifacts are recorded under
`build/flex/sim/approach35-v2/`; final layouts 10 and 11 remain reserved.
