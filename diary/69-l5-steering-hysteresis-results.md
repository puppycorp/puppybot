# L5 steering kick and reversal hysteresis results (3 Nov 2026)

The three-arm, training-family simulator diagnostic completed all 36 games.
The kick plus reversal hysteresis rule **never activated**, so this run does
not show whether the rule can reduce the oscillation observed in the earlier
kick screen. Both kick arms exceeded the goal's 2% back-and-forth threshold
on these cases. There was no prespecified success or promotion rule.

| Measure | Control | Kick | Kick + hysteresis |
| --- | ---: | ---: | ---: |
| Games with a virtual delivery | 7/12 | 10/12 | 10/12 |
| First virtual consumption by action 200 | 3/12 | 10/12 | 10/12 |
| Back-and-forth actions | 127/3,600 (3.53%) | 120/3,600 (3.33%) | 120/3,600 (3.33%) |
| Games over 20% back-and-forth | 0/12 | 0/12 | 0/12 |
| Longer-loop actions / search actions | 0/2,978 | 53/2,596 (2.04%) | 53/2,596 (2.04%) |

Each game had 300 actions. The kick triggered in 8/12 games. The hysteresis
activated and changed an action in 0/12; the saved proposed actions, applied
actions, feedback and actor image and recurrent-state digests match between
the two kick arms across all 300 decisions in each game. This is evidence
about the recorded paths, not proof of what would happen after activation.
For comparison, the earlier kick screen had 310/3,600 flagged actions and two
games over 20%; these are different seeds and variants, so the change cannot
be attributed to the rule or treated as a matched comparison.

The back-and-forth detector unions 20-action windows with at least four
drive reversals, less than 0.25 m net displacement and under 45 degrees net
turn. The separate longer-loop metric unions 50-action search windows that
travel at least 0.75 m and end within 0.4 m and 45 degrees of their start.
All 53 longer-loop actions in each kick arm came from seed 6800205, across
four overlapping windows; recorded truth and odometry both flagged those 53
actions. These bounded heuristics do not capture every loop.

The saved-output re-audit reconstructed all 12 three-arm pairs and matched
`report.json` exactly. It checked the registered scene and initial inputs,
policy snapshots, intended commands and environment, clean status for each
of the 36 supervisors, actor-boundary logs, simulated drive echoes, and the
hysteresis journal. The outer and final inventory supervisors recorded clean
exits; `monitor-result.json` reports `passed` and `completion.json` remains
`diagnostic_only`. Across the sampled monitor records, minimum free GPU memory
was 9.065 GiB and minimum free disk was 45.714 GiB. Sampling cannot establish
exclusive GPU use or exclude brief changes between samples.

These are known training-family layouts, not held-out evaluation. Virtual
consumption and delivery are not physical grasp or hardware evidence. The
saved records and intended commands do not independently attest execution or
neural computation. The kick and hysteresis thresholds were informed by prior
trajectories; neither intervention is promoted by this diagnostic.

Artifacts: `build/flex/sim/levels-v2/pitch82/l5-steering-hysteresis-diagnostic-v1/`
and `build/flex/sim/levels-v2/pitch82/l5-steering-hysteresis-monitored-v1/`.
