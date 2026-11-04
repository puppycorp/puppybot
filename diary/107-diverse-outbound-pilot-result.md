# Diverse-room outbound teacher pilot result (4 Nov 2026)

The matched virtual-fetch pilot passed its preregistered **feasibility screen**:
five fitting games across two layouts and one pilot-validation game had a
qualifying teacher outbound prefix; none met the screen's definition of the
teacher doing worse. This is not model training, a model improvement, a
held-out result or a physical pickup and delivery. The output explicitly says
`trainingAuthorized:false`.

Both arms ran 12 matched cases for 300 actions each. The fixed `student-s1`
policy consumed no brick in any of the 12 games and delivered none. The
exploring teacher consumed a brick in 9/12 games and delivered in 7/12 games,
with 11 total virtual deliveries. These are simulated task events, not a
physical grasp or release. The teacher had 3,058 disagreements among the
student-driven arm's 3,600 saved action labels; that is a label count, not a
quality or policy-gain measure. The audit checked all 3,600 labels in each arm.

| Seed | Layout / variant | Split | Teacher first consumption | Teacher deliveries | Flagged teacher outbound actions | Helpful by screen |
| --- | --- | --- | ---: | ---: | ---: | --- |
| 6910000 | 27 / 8 | Fit | 291 | 0 | 0 | No |
| 6910001 | 27 / 9 | Fit | None | 0 | 0 | No |
| 6910002 | 27 / 10 | Fit | None | 0 | 0 | No |
| 6910003 | 29 / 8 | Fit | 162 | 1 | 0 | Yes |
| 6910004 | 29 / 9 | Fit | 107 | 2 | 0 | Yes |
| 6910005 | 29 / 10 | Fit | 171 | 1 | 0 | Yes |
| 6910006 | 31 / 8 | Fit | 43 | 3 | 0 | Yes |
| 6910007 | 31 / 9 | Fit | None | 0 | 83 | No |
| 6910008 | 31 / 10 | Fit | 38 | 2 | 0 | Yes |
| 6910009 | 33 / 11 | Pilot validation | 260 | 0 | 20 | No |
| 6910010 | 35 / 11 | Pilot validation | 161 | 1 | 0 | Yes |
| 6910011 | 37 / 11 | Pilot validation | 157 | 1 | 26 | No |

The screen calls a case helpful when the teacher's first virtual consumption
is by action 200, the student either consumes at least 30 actions later or
does not consume within 300 actions, and the teacher has zero flagged actions
in the strictly pre-consumption prefix. With the student
missing in all 12 games, this screen's zero `teacherWorse` does not establish
that the teacher always outperforms the student on other scenes. The threshold
was at least three helpful fitting cases across two layouts, one helpful
pilot-validation case, and at most three teacher-worse cases. Its
`pose20-prefix-bounded-final-inclusive-v1` action-union heuristic includes the
window ending at the prefix boundary and cannot mark earlier actions solely
because of later post-pickup reversals. It does not detect every loop.

The three variants within each fitting layout share one environment and spawn;
the six geometries were also used in older training-family data. Exact scene
bytes were checked against the current five-level selection, but this does not
establish semantic novelty or complete model ancestry. The 12 cases are not 12
independent room layouts, and their selection was motivated by earlier work.
The independent replay and monitor establish local record consistency, not OS
execution attestation, raw-camera provenance, model gain or physical safety.

An independent saved-game re-audit reproduced `report.json` exactly. It
verified the scene copies, starts, 300-action clock, simulated transitions,
labels and the prefix screen. All eight completion hashes and all 249 output
inventory entries matched; current preflight agreed with the launch and frozen
inputs. The resource logs verified, the monitor passed, and both arm plus outer
and final-inventory supervisors exited cleanly. The student and teacher arms
took 141.7 and 130.3 seconds of wall time. Across 313 GPU samples, minimum free
VRAM was 9.157 GiB and maximum busy was 20%; 284 disk samples had at least
44.134 GiB free. Sampling cannot establish exclusive GPU access or exclude
brief conditions between samples.

Evidence: `build/flex/sim/levels-v2/pitch82/outbound-diverse-prefix-pilot-v1/`
contains the catalog, paired shards, 24 game records and screen report;
`build/flex/sim/levels-v2/pitch82/outbound-diverse-prefix-pilot-monitored-v1/`
contains monitor, frozen-input, inventory and completion receipts. Output is
approximately 216 MiB plus a 728 KiB monitor directory. A training candidate
would still require separately reviewed prefix selection, dataset provenance,
a fixed independent selection boundary, model training and full reliability
and loop evaluation before held-out use.
