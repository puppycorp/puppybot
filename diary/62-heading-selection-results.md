# 62. Matched fixed-epoch heading selection (3 Nov 2026)

The two fixed epoch-8 models from the matched heading-distribution experiment
were evaluated on the registered training-layout selection plan. Each row is
32 matched games per arm, seeds 7800000–7800031, under the saved standard or
L1–L5 conditions. These are virtual-fetch selection results, not held-out or
physical-robot evidence. Control and treatment were trained from the same
parent and matched validation data, with the roll-in heading distribution as
the intended difference; prior source ancestry is not fully authenticated.

| Task | Control deliveries/min | Treatment deliveries/min | Control games delivered | Treatment games delivered | Control back-and-forth | Treatment back-and-forth |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Standard | 4.906 | 4.688 | 32/32 | 32/32 | 1.95% | 2.00% |
| L1 | 7.156 | 6.531 | 32/32 | 31/32 | 5.53% | 5.23% |
| L2 | 5.719 | 5.219 | 32/32 | 32/32 | 4.64% | 2.03% |
| L3 | 2.531 | 2.469 | 29/32 | 31/32 | 2.78% | 1.20% |
| L4 | 2.719 | 2.156 | 27/32 | 29/32 | 3.79% | 1.57% |
| L5 | 0.563 | 0.438 | 15/32 | 12/32 | 11.10% | 2.28% |

Back-and-forth shares are fractions of recorded actions. Mostly
back-and-forth games for control/treatment were standard 0/0, L1 1/2,
L2 1/0, L3 1/0, L4 0/0 and L5 0/1. These are separate statistics: a low
mean does not establish absence of difficult search loops. No teacher arm was
run and there was no preregistered overall winner or promotion rule.

For L4 doorway placements, control delivered 33 of 60 and treatment 28 of
54 by the horizon; 27 and 26 placements respectively were unresolved and
right-censored, including one treatment placement at action 300 with no time
to deliver. The fractions use all placements as their denominators and are
not eventual-success probabilities. Placement counts can differ because later
placements follow each policy's trajectory.

L5 treatment recorded first virtual consumption in 29/32 games, versus
15/32 for control, but completed a virtual delivery in only 12/32 versus
15/32. Of the 17 treatment games with consumption but no delivery, every
first consumption occurred at action 238–299, leaving 1–62 actions before
the 300-action horizon; 10 had fewer than 30 actions remaining. At the final
recorded action all 17 were still in the return phase with the same target
marked consumed, with no recorded reset or loss. For successful first
returns, elapsed actions from consumption to delivery were 30–114 (median 54)
for treatment and 30–117 (median 57) for control. This supports late search
as a substantial horizon constraint; it does not prove those incomplete
returns would succeed if extended.

The 17 late treatment searches travelled a median 16.37 m by recorded
simulator truth before consumption (range 14.15–17.81 m), with median net
displacement 3.10 m. In the four matched games delivered only by control,
control/treatment first-search paths were 7.56/14.57 m (seed 7800003),
13.91/16.01 m (7800015), 6.96/16.37 m (7800018), and 7.08/14.15 m
(7800030). L5 delivered in both arms for 11 seeds, control alone for 4,
treatment alone for 1, and neither for 16. Search-loop flags are limited
heuristics and a zero count does not rule out a long or closed route; this
comparison does not prove the cause of those paths.

The six pair audit logs and individual arm audit logs match the completed
selection summary. All 30 saved arm and audit supervisor records show clean
exit, no timeout, no signal and no remaining workers terminated. The monitored
completion receipt reports passed. Its 31 baseline GPU samples cover 30.0 s,
with minimum free VRAM 7.565 GiB and maximum busy 3%; during selection the
minimum sampled free VRAM was 6.132 GiB and disk was 46.330 GiB. The enclosing
supervisor recorded 2,684.8 seconds. Samples cannot exclude transient resource
contention between observations or prove no impact on another service.

Audit scope is matching of recorded scene/start/placement and saved scores;
actual OS invocation and camera/actor input execution are not independently
attested. `firstReturnGames` is a return-phase proxy and virtual consumption
is not a physical pickup. No independent teacher comparison, held-out test,
physical-grasp success or policy promotion follows from these results.

Artifacts: `build/flex/sim/levels-v2/pitch82/search-dagger-heading/selection-epoch8/`
and `build/flex/sim/levels-v2/pitch82/heading-selection-monitored-v1/`.
This write-up reads the saved results and logs; it does not rerun the audits
or rehash the large inputs.
