# Outbound teacher paths on an L5 failure cluster (3 Nov 2026)

An offline audit of the saved 32-game L5 selection suggests a targeted
training hypothesis: improve the older `student-s1` policy's outbound search
on one observed failure family, while retaining examples from the other
levels and return phase. This is a post-hoc analysis of reused training-family
selection cases. It is not a trained improvement, a held-out result, or a
physical pickup.

The older student made a first virtual consumption in 25/32 games and at
least one virtual delivery in 24/32. The fixed heading-treatment model
consumed in 29/32 and delivered in 12/32; the exploring teacher consumed in
21/32 and delivered in 19/32. These complete-set counts matter: the teacher
was not uniformly better, and the heading model often consumed too late to
return within the 300-action horizon.

Six of the older student's seven no-consumption games were in the recorded
partition-x=1.6 group. For the six seeds below, the old student never
consumed or delivered. The heading model consumed in five, but only at actions
245–299; it delivered in none. The teacher consumed earlier in all six and
delivered in four:

| Seed | Teacher first virtual consumption | Teacher deliveries | Teacher back-and-forth actions, full 300 |
| --- | ---: | ---: | ---: |
| 7800000 | 150 | 1 | 24 |
| 7800003 | 127 | 1 | 112 |
| 7800006 | 136 | 0 | 145 |
| 7800009 | 158 | 1 | 0 |
| 7800021 | 140 | 0 | 132 |
| 7800024 | 153 | 1 | 60 |

The existing 20-action reversal detector flagged no teacher actions before
first consumption in these six recorded games. It flagged substantial later
oscillation in several, and the teacher failed to deliver in two. A zero
detector count does not prove an optimal or physically feasible outbound
route, and blindly copying whole teacher episodes could teach return loops.
The six cases are correlated: their saved action-and-pose prefix is identical
for the first 98 actions for the old student and 101 for the teacher. The
partition, initial appearance and placements are confounded; six games are not
six independent layouts. Entry 64 also found a different two-game cluster in
which the teacher was not earlier than the heading model.

The read-only script `experiments/outbound-teacher-audit-v1/audit.py`
reconstructs the complete set of 32 games for all three arms. It checks
policy snapshots and saved scores, teacher shard headers and data hashes,
task-event transitions, and matching scene bytes and initial robot/brick
events. It checks the recorded plan chain, current old-student and heading
model files, and the shared recorded control, simulator and selection-auditor
hashes. The historical old-student manifest does not pin the complete
runtime and simulator asset chain, and recorded commands and hashes do not
attest execution or all earlier model ancestry. The teacher's saved receipt
states that it uses camera detections and reference wall geometry; its labels
are not independently established as correct or physically safe.

A useful next experiment would collect **new fitting seeds and training
variants**, rather than training on these six selection cases. Compare a
carefully audited mix that adds useful teacher outbound prefixes and
student-state corrective labels to a matched baseline that preserves the
existing L1–L4 and return data. Retain and inspect label masks and the full
dataset provenance; avoid presenting the teacher's return loops as successful
demonstrations. The pilot should first show that new teacher paths reach the
target earlier under matched starts and that labels are usable. A full
candidate must then be assessed on separately predeclared selection games
against the old student and teacher, including all games and timeouts: per
level at least 29/32 games delivered, L3 at least 29/32 first virtual
consumptions, L4 at least 80% of doorway placements delivered by the horizon,
less than 2% recorded back-and-forth at each level, and pooled delivery rate
at least the teacher's with no reliability loss. Longer-search loops must be
reported separately. These selection gates are prerequisites for considering
the reserved held-out evaluation, not a substitute for it.

Run `python3 -B -I experiments/outbound-teacher-audit-v1/test.py` for the
three CPU checks, and `python3 -B -I
experiments/outbound-teacher-audit-v1/audit.py` to reconstruct the saved-data
report. No simulator or GPU work is performed by either command.
