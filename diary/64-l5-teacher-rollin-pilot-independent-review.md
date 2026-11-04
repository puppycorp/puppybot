# Independent review of the L5 teacher roll-in pilot

The completed monitored pilot compared the exploring teacher driving against
the fixed heading-treatment student driving while the teacher supplied labels.
Both arms used two previously used training-pilot games, not held-out scenes.
The saved initial state bytes and start robot/brick events matched for each
pair. Recorded commands and source hashes are local evidence; they do not
independently establish which binaries executed or that labels are correct.

| Seed | Student first virtual consumption | Teacher first virtual consumption | Student / teacher virtual deliveries |
| --- | ---: | ---: | ---: |
| 6700000 | Action 241 | Action 259 | 1 / 1 |
| 6700001 | Action 255 | Not observed within 300 actions | 0 / 0 |

The teacher was not earlier in either observed horizon. Its second game is
right-censored at 300 actions; the result does not say what would happen with
more time. Directly streaming the four saved 300-action decision logs confirmed
the consumption and delivery transitions. Independent decoding of 600 label
rows per arm found finite, in-range actions and unit supervision weights.
The teacher labels matched its recorded actions on all 600 rows; 328 student
actions differed from their teacher labels, split 149 and 179 by game. These
comparisons do not validate the teacher or establish a training gain.

The saved outer, student, teacher and final-inventory supervisors reported clean
exits without timeout, signal or descendant cleanup. The saved evidence and
report agree, and the completion hashes for the small evidence, telemetry,
disk and final-status files match. A read-only rerun of the telemetry verifier
found 31 baseline, 57 active and one final GPU sample, with a maximum gap of
1.003 seconds, minimum reported free VRAM of 6.24 GiB and minimum reported
free disk of 46.352 GiB. Sampled telemetry cannot exclude interference between
samples. This review did not rehash the large data files, use the GPU or
modify the pilot outputs.

The result does not demonstrate a faster teacher route on these two games and
does not justify expanding this teacher-driven route experiment on its own.
Virtual consumption is not a physical grasp; two reused training-pilot cases
cannot establish generalization, a held-out result or physical robot success.
