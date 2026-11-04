# L5 three-action steering diagnostic results (3 Nov 2026)

The fixed training-family simulator screen did not pass. The intervention
improved first virtual consumption and completed virtual deliveries in these
12 matched games, but increased games with more than 20% back-and-forth steps
from zero to two. This was the fixed screen's failing condition; it is not a
model promotion, independent held-out result, or physical-robot evaluation.

The screen included all 12 games, including the four in which the intervention
was a no-op. First consumption by action 200 improved from 4/12 to 9/12;
games with a completed delivery improved from 5/12 to 11/12; and the
intervention changed actions in 8/12 games. The prespecified requirements were
at least six triggered games, at least three additional early consumptions,
no fewer delivered games and no increase in mostly back-and-forth games. The
first three conditions held; the last did not.

| Seed | Layout / variant | Changed actions | First consumption, control / intervention | Games delivered, control / intervention | Back-and-forth steps, control / intervention |
| --- | --- | ---: | --- | --- | --- |
| 6800100 | 13 / 0 | 3 | 248 / 144 | yes / yes | 0 / 0 |
| 6800101 | 13 / 1 | 3 | not observed / 262 | no / yes | 0 / 23 |
| 6800102 | 13 / 2 | 3 | not observed / not observed | no / no | 0 / 70 |
| 6800103 | 13 / 3 | 3 | 241 / 116 | no / yes | 0 / 0 |
| 6800104 | 15 / 0 | 3 | not observed / 174 | no / yes | 29 / 44 |
| 6800105 | 15 / 1 | 3 | 259 / 99 | no / yes | 0 / 41 |
| 6800106 | 15 / 2 | 3 | not observed / 101 | no / yes | 0 / 0 |
| 6800107 | 15 / 3 | 3 | 268 / 233 | no / yes | 0 / 108 |
| 6800108 | 17 / 0 | 0 | 96 / 96 | yes / yes | 0 / 0 |
| 6800109 | 17 / 1 | 0 | 107 / 107 | yes / yes | 0 / 0 |
| 6800110 | 17 / 2 | 0 | 126 / 126 | yes / yes | 0 / 0 |
| 6800111 | 17 / 3 | 0 | 105 / 105 | yes / yes | 24 / 24 |

Each game had 300 actions. A missing first consumption means none was observed
within that horizon; it is not an estimate of a later time. The pooled
back-and-forth total was 53/3,600 actions (1.47%) in control versus 310/3,600
(8.61%) under intervention. The screen labels a game mostly back-and-forth
when this count exceeds 60/300. The saved-trace detector marks 20-action
windows with at least four drive-direction reversals, less than 0.25 m net
movement and under 45 degrees net turn; it is a bounded heuristic rather than
a count of all possible search loops.

In seed 6800102 the intervention had 70 flagged actions (23.3%) versus zero
in control; neither arm consumed or delivered. In 6800107 the intervention
had 108 flagged actions (36.0%) versus zero; it consumed at action 233 and
delivered once, while control consumed at 268 and did not deliver. An
independent reconstruction found qualifying windows well after the first three
changed actions, including very little displacement with repeated reversals.
For both cases, the first recorded common proposal `[-0.6, -1.0]` was applied
as `[+0.6, -1.0]` in the intervention, with simulator command echo changing
from `[-60, -60, 63]` to `[-60, -60, 117]`. The subsequent actor inputs and
recurrent states diverged. These traces show bouncing in the changed
trajectories, but do not establish its underlying mechanical cause.

A read-only saved-game re-audit independently reproduced all 12 pair objects
and the exact failed screen. It checked initial saved scene and start/brick
matching, actor-boundary proposed/applied action and feedback records, the
recorded carry state and 300 decision rows, and reconstructed the
back-and-forth count. All 24 saved commands and environments matched the
registered single-game plan, and all 24 arm supervisors recorded clean exits.
The resource monitor and its outer and final-inventory supervisors were clean,
and `completion.json` reports `diagnostic_only`. The 31-sample baseline spanned
30 seconds; minimum sampled free GPU memory was 9.593 GiB and minimum sampled
free disk was 45.787 GiB. Sampling does not prove GPU exclusivity or exclude
brief conditions between samples.

The runs share a simulator, model and initial conditions within each pair, but
their later observations and trajectories can diverge. The intervention is an
isolated controller experiment on known training-family scenes using the
existing carry cue. The saved records and intended commands do not independently
attest OS execution or neural computation. Virtual consumption and delivery
are not evidence of physical grasp or hardware performance.

Artifacts: `build/flex/sim/levels-v2/pitch82/l5-steering-kick-diagnostic-v1/`
and `build/flex/sim/levels-v2/pitch82/l5-steering-kick-monitored-v1/`.
