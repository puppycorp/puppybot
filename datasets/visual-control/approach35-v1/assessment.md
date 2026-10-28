# Completed strict-task dataset expansion

The final corpus contains 128 original scene identities exactly once, with
96 fitting histories from layouts0-5 and 32 validation histories from layouts6-7.
All require actual TCP RGB detection within 35 cm of the physical robot base,
followed by fresh, stopped box docking under the existing acceptance rules.
No legacy distant-sighting data was added.

There are 64 teacher-only histories and 64 histories with retained-student
prefixes followed by teacher recovery. Every valid frame has a privileged
oracle label, separately stored from the executed command in PVDATA03.
Student inputs remain RGB84x84, own-feedback7 and recurrent state128.

Final native-verified evidence:

- 128 histories; 96 fitting / 32 validation; eight distinct layout instances.
- 11,822 supervised actions and 155,852 independently checked physics increments.
- 1,263 student commands replayed with zero error.
- All camera/actor pixels, own feedback, oracle labels, command intervals,
  detection projections, 35cm proximity, fresh docking and padding accepted.
- Sequence length201, 546,051,104 bytes; native repacking was byte-identical.
- SHA256 e45f28097f8f58b00b915b026c921b9013334c3795be205aca0dce2c13c3a148.

The simulator and reference-policy fingerprints, all scene hashes and the
exact collection recipe passed integrity checks. The dataset lives locally
under artifacts/data128 and is ignored by Git. No model training, commit or
push was performed for this expansion.

## Collection failures and repairs

A pilot first exposed the teacher's 30cm goal plus10cm arrival tolerance.
That could stop outside the task's35cm limit. The teacher now aims24cm away;
the exact failed pilot is preserved in artifacts-pilot-arrival30. All16
repaired pilot trips passed before full collection.

The primary128-scene run produced125 physical completions and three failures.
Successful retries retained every failed scene's identity and original role:

| Final index | Layout / scene | Original rejection |
| --- | --- | --- |
| 14 | 0 / 14 | Return stuck near box |
| 19 | 1 / 3 | Approach and return recovery |
| 84 | 5 / 4 | Arrived search pose without RGB consumption |
| 27 | 1 / 11 | RGB consumption projection |
| 29 | 1 / 13 | RGB consumption projection |
| 41 | 2 / 9 | RGB consumption projection |
| 107 | 6 / 11 | RGB consumption projection; validation role preserved |
| 122 | 7 / 10 | RGB consumption projection; validation role preserved |

The last five rejections were found by the independent image audit after
physical completion. Its12pixel projection check was not relaxed. Alternate
approaches and shorter allowed student prefixes produced new passing records
of those same scenes. All original and unsuccessful repair traces remain.

Teacher-only changes include alternate oriented approaches after contact or
an unproductive stop, a50cm box target, and optional routing behind the
original spawn. The integrated return-via-home option reproduced the passing
prototype's entire two-episode dataset byte for byte. Exploratory departure
and steering-centering fallbacks that did not fix the case were not retained
in the public teacher implementation.

## Audit coverage and safeguards

Native range audits checked every original episode individually. They found
123 passing histories and the five image rejections. Each final selected
history has an episode-specific native receipt; assembly verifies its source
file SHA256, original source index, command count, student replay count and
all boundary-check flags. This reuses already verified source histories
without claiming a fresh serial audit of the new aggregate.

The complete aggregate was independently repacked by the native reader and
compared byte for byte. All128 scene identities and96/32 layout-disjoint roles
are checked before publication. Negative checks rejected duplicate/order
changes, substituted physical scenes and an audit receipt for the wrong
episode without publishing a dataset.

The new audit-range option preserved the default32-episode audit's existing
result fields exactly. Native observation/action/oracle/proximity contracts,
scene regeneration determinism, shell syntax and whitespace checks passed.
The neural gradient suite was not rerun because no neural training logic changed.

## Limits

The eight layouts come from open-room and two-room-with-doorway families.
Room sizes, doorways, spawn pose, brick color/size/yaw/position and box side
vary, but targets remain directionally biased. This is data-quality evidence,
not a student success-rate or arbitrary-floorplan generalization result.
