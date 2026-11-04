# Replaying the two steering failures with hysteresis (3 Nov 2026)

The hysteresis intervention changed both previously oscillating kick
trajectories, but **did not preserve delivery and is not a candidate for
promotion**. On seed 6800107, kick delivered once while kick plus hysteresis
never consumed the target and spent much of the remaining game blocked.
These two cases were deliberately chosen because the earlier kick experiment
failed on them; this is a post-hoc debugging replay, not a held-out test or a
general estimate of performance.

All six games used the same newly instrumented controller binary and matched
model, simulator, scene, seed and 300-action horizon within each case. The
new kick arm reproduced the saved prior kick actor records for all 300
actions in each game, with matching initial and start bytes. This comparison
concerns recorded actor inputs, actions and digests; it does not independently
attest the computation that produced them.

| Seed | Arm | Back-and-forth actions | First virtual consumption | Virtual delivery | Contact-feedback actions |
| --- | --- | ---: | ---: | --- | ---: |
| 6800102 | control | 0 | not observed | no | 0 |
| 6800102 | kick | 70 | not observed | no | 0 |
| 6800102 | kick + hysteresis | 64 | not observed | no | 0 |
| 6800107 | control | 0 | 268 | no | 0 |
| 6800107 | kick | 108 | 233 | yes | 2 |
| 6800107 | kick + hysteresis | 43 | not observed | no | 158 |

The hysteresis activated and first changed an action at 174 and 129,
respectively. Thus the lower reversal counts do not demonstrate a successful
recovery: for 6800107 the changed trajectory missed a previously completed
delivery. The recorded simulator `blocked` flag was true for 159 actions in
that arm versus two under kick. Two of those blocked actions preceded the
intervention; the flag was then true continuously from action 144 through
300. Contact feedback was recorded at actions 82 and 85 in both kick arms,
and again from action 145 through 300 in the hysteresis arm. This is a
conditional observation about the saved simulator trajectory, not proof of a
physical collision or a diagnosis of its mechanical cause.

Wheel-command odometry is especially misleading during this failure. From
the post-action state at 129 to the post-action state at 300, simulated truth
moved 0.239 m, while recorded odometry moved 9.742 m; their final positions
differed by 10.238 m. The guard does not provide a reliable stop or report
when recovery fails, and its odometry is not independent proof of movement.

The separate longer-loop diagnostic uses 50-action search windows with at
least 0.75 m traveled, less than 0.4 m endpoint displacement and less than
45 degrees of heading change; overlapping windows are unioned. On 6800107,
kick had 142 odometry-flagged actions and 144 truth-flagged actions; kick plus
hysteresis had 57 and 103 respectively, including 46 truth-only actions.
Neither detector flagged a long loop on 6800102. These bounded metrics miss
other forms of stagnation and do not by themselves establish recovery safety.

An independent saved-output re-audit reconstructed both three-arm pairs and
matched the report. It checked matched input and actor records, policy
snapshots, simulated drive echoes, hysteresis journals, all six intended
commands and clean supervisor statuses. The final output inventory, monitor
logs and completion hashes matched; both outer and final-inventory supervisors
exited cleanly, and completion remains `diagnostic_only`. The minimum sampled
free GPU memory was 9.098 GiB and free disk 45.685 GiB. Sampling cannot prove
exclusive GPU use or exclude brief changes between samples.

Virtual consumption and delivery do not establish a physical grasp or a
hardware stop. The replay used two known training-family cases selected after
inspecting their failures; neither the kick nor this one-shot hysteresis rule
meets the robot's held-out reliability or recovery requirements.

Artifacts: `build/flex/sim/levels-v2/pitch82/l5-steering-hysteresis-debug-v1/`
and `build/flex/sim/levels-v2/pitch82/l5-steering-hysteresis-debug-monitored-v1/`.
