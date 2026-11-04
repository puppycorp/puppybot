# Matched teacher comparison on training-layout selection (3 Nov 2026)

The exploring teacher and the two fixed epoch-8 heading models were compared
on the previously registered training-layout selection conditions, 32 matched
300-action games per arm per task. These are virtual-fetch results, not
held-out or physical-robot evidence. Standard is reported separately and is
not included in the pooled L1–L5 figures.

| Task | Teacher deliveries/min | Control deliveries/min | Treatment deliveries/min | Teacher games delivered | Control games delivered | Treatment games delivered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Standard | 5.094 | 4.906 | 4.688 | 32/32 | 32/32 | 32/32 |
| L1 | 7.406 | 7.156 | 6.531 | 32/32 | 32/32 | 31/32 |
| L2 | 5.406 | 5.719 | 5.219 | 32/32 | 32/32 | 32/32 |
| L3 | 2.812 | 2.531 | 2.469 | 31/32 | 29/32 | 31/32 |
| L4 | 2.688 | 2.719 | 2.156 | 26/32 | 27/32 | 29/32 |
| L5 | 0.750 | 0.563 | 0.438 | 19/32 | 15/32 | 12/32 |

For the pooled L1–L5 denominator, each arm has 160 one-simulated-minute
games. Teacher made 610 deliveries (3.8125/min), control 598 (3.7375/min,
98.03% of teacher's rate), and treatment 538 (3.3625/min, 88.20%). Teacher
had at least one delivery in 140/160 games; both control and treatment did so
in 135/160. These rates alone do not establish the separate per-game,
oscillation, held-out, or physical goal criteria.

Back-and-forth action shares for teacher/control/treatment respectively were:
standard 4.32%/1.95%/2.00%, L1 10.28%/5.53%/5.23%, L2
6.20%/4.64%/2.03%, L3 0.27%/2.78%/1.20%, L4 11.84%/3.79%/1.57%,
and L5 15.98%/11.10%/2.28%. These are action shares on this set; neither the
mean nor a loop heuristic proves absence of long search routes.

For L4, opposite-side placement deliveries by the horizon were 28/53 for the
teacher, 33/60 for control and 28/54 for treatment. Respectively 25, 27 and
26 placements were unresolved and right-censored at the horizon, including one
treatment placement created at action 300. The fractions include unresolved
placements and are not eventual-success probabilities; later placement counts
can differ because the agents' trajectories and delivery timing differ.

The saved task reports compare matching seed, scene, recorded start and initial
placement. Subsequent trajectories and placements can differ. The teacher uses
camera detections and recorded wall geometry for its search, while the student
uses a learned policy; this is a useful reference comparison, not a claim that
their observation or control interfaces are identical. Return-phase counts are
proxies, and simulated virtual consumption is not a physical grasp. The saved
records do not independently attest OS invocation, raw camera-to-actor inputs,
policy execution, semantic scene independence or unrecorded model ancestry.

The six task audit outputs match the nested task entries in the teacher summary;
the pooled audit matches its summary entry. All 13 saved task-run, task-audit
and pool-audit supervisors report clean exit, no timeout, no signal and no
remaining workers terminated. The outer worker also finished cleanly and its
monitor result passed. The baseline had 31 GPU samples spanning 30.0 seconds,
with minimum 6.439 GiB free and maximum 3% busy; minimum sampled free VRAM
during the run was 5.861 GiB and minimum sampled free disk was 45.867 GiB.
The outer worker took 2,019.939 seconds. These samples cannot exclude brief
interference between observations or prove exclusive GPU use.

The final completion receipt records `complete_diagnostic` after the bounded
snapshot and source-pin checks, with 45.844 GiB free before receipt publication.
Its scope is the saved teacher comparison.

Artifacts: `build/flex/sim/levels-v2/pitch82/search-dagger-heading/teacher-selection-v1/`
and `build/flex/sim/levels-v2/pitch82/heading-teacher-selection-monitored-v1/`.
This entry summarizes saved outputs without re-running audits or rehashing large
datasets.
