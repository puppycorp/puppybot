# First strict-task training and autonomous test

On 2026-10-27, two native Flexscript/Pup CUDA CNN/GRU training runs completed
20 epochs each on the 96 fitting histories. The 32 validation histories came
from layout instances 6 and 7, excluded from fitting. A further eight frozen
scenes from new instances 8 and 9 were excluded from fitting and checkpoint
selection. All instances belong to the same two room-generator families.

Training improved some approaches, but **no evaluated model completed the
whole strict approach-and-return task**. The retained policy was not replaced.

## Training and selection

Both runs used batch 2, seed 73, full 201-frame recurrent histories with valid
frame masking, and 324,184 parameters including the auxiliary training head.
The warm run started from retained checkpoint
`1a7033fd0607ddbf2137fb082d5cf9a56b2e9d0fe485fc51bdb77725f91ce7f2`
at learning rate 0.0001. The cold run randomized all parameters at learning
rate 0.0003. Actual initial weights were checked, and both runs used identical
first and final episode ordering. These are two training recipes, not an
isolated comparison of initialization with a matched learning rate.

The fixed optimizer snapshots at epochs 5 and 20 were packaged separately
from each trainer's automatic minimum-validation-loss output. All four exports
matched training-graph logits and recurrent state exactly in native forward
checks. Each completed the same eight-scene autonomous validation screen:

| Checkpoint | Approached within 35 cm | Returned and docked |
| --- | ---: | ---: |
| Warm, epoch 5 | 1/8 | 0/8 |
| Warm, epoch 20 | 1/8 | 0/8 |
| Cold, epoch 5 | 1/8 | 0/8 |
| Cold, epoch 20 | 1/8 | 0/8 |

The declared ranking used physical episode completions, then mean whole
simulation time, then earlier epoch and warm initialization. All four tied
on completion and time, so warm epoch 5 was selected by the tie-break. This
selection does not establish that it is better than the other checkpoints.
The selected trained checkpoint SHA256 is
`8aeffe83f433ebf53d03974a99058caa65f78a2f592b128214df7857befceaf5`.

## Complete-episode results

Approach means actual RGB detection with physical base-to-brick distance
at most 0.35 m. Completion additionally requires stopping 0.30–0.65 m from
the box, facing within 35 degrees, fresh rim-marker observations and three
stable return observations. There is no grasp/carry/drop procedure in this
benchmark. Physical completion is taken from the final case state; the older
summary's additional hidden-room exploration flag is retained separately.

| Evaluation | Policy | Approached | Returned and docked |
| --- | --- | ---: | ---: |
| Full validation, 32 scenes | Retained | 0/32 | 0/32 |
| Full validation, 32 scenes | Warm epoch 5 | 4/32 | 0/32 |
| Fresh final, 8 scenes | Retained | 0/8 | 0/8 |
| Fresh final, 8 scenes | Warm epoch 5 | 3/8 | 0/8 |
| Same fresh final, 8 scenes | Warm epoch 5, network RGB blacked out | 0/8 | 0/8 |

Every episode reached the 60-second driving limit, plus 5.9 seconds of initial
camera positioning: 65.9 simulated seconds per episode. No improvement in
whole-episode speed or success has been demonstrated. The small blackout
comparison gives approach-level evidence only; all full-task outcomes were
failures. Final scenes were not used to revise the selected checkpoint.

## Observed failures and next experiment

In validation, all four approaches occurred in the open layout. None of the
16 two-room runs left the starting room. On the fresh two-room layout the
selected model entered the second room in all four trials and reached one
brick, but still did not dock. Behavior is sensitive to layout changes.

Inspected open-room approaches were followed by repeated reversing into a
wall. For example, validation layout 6 / scene 0 spent 201 of 300 action
samples blocked and never chose zero speed; its final physical distance from
the box exceeded the docking range. The rendered outcome confirms wall
contact. The failure includes return navigation, rather than just a missing
final stop command.

A useful next experiment is longer on-policy collection on **fitting layouts**,
with oracle recovery labels during approach, return and persistent contact.
The current dataset's student prefixes end after 8–32 actions (1.6–6.4 s),
while these failures persist much later. This is a proposed remedy, not a
verified explanation or improvement. Preserve separate fresh test layouts
for the next training experiment.

## Evidence and local artifacts

All 112 unique autonomous recordings passed native independent verification:
33,600 network commands replayed with zero error, 368,928 physical motion
increments checked, ten valid RGB/proximity consumption events, current
sensor PNGs matching actor inputs, and no task-event hints. The training
oracle was disabled during autonomous evaluation. Runtime, scene and
experiment binary fingerprints remained unchanged. Training, inference and
verification used native Flexscript/Pup CUDA; no Python was invoked.

The packed dataset SHA256 remained
`e45f28097f8f58b00b915b026c921b9013334c3795be205aca0dce2c13c3a148`.

Local experiment files are under `build/flex/sim/approach35-train-v1/`:

- [Protocol](../../../build/flex/sim/approach35-train-v1/protocol.json) and [results](../../../build/flex/sim/approach35-train-v1/result.json).
- [Independent audit totals](../../../build/flex/sim/approach35-train-v1/audit-summary.json).
- `learn.sh`, `benchmark.sh`, `evaluate.sh`, `publish.flex`: exact executed recipe.
- `warm/`, `cold/`: curves, initial weights, optimizer snapshots and ordering.
- `policy-warm5/`: selected experimental checkpoint; other fixed exports are adjacent.
- `validation-*/`, `screen-*/`, `final-*/`: per-scene videos, PNGs, commands and verification.
- [Fresh-scene example video](../../../build/flex/sim/approach35-train-v1/final-warm5/1/8910001/mission.mp4): valid approach followed by failed return, with live TCP camera inset.

The large build artifacts are local and ignored by Git. This experiment does
not demonstrate arbitrary-floorplan generalization or physical robot pickup.
