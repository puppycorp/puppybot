# Teacher outbound on the fresh L5 selection cases (3 Nov 2026)

The fresh 32-case L5 selection supports a **conditional**, not general,
teacher-outbound hypothesis. The older student did not virtually consume the
brick in five games; in each of those, the teacher did consume and deliver it
within 300 actions. Conversely, the teacher did not consume in ten other
games where the older student did. These are post-hoc training-family
selection observations, not independent held-out or physical results. The
original full-run monitor failed during output inventory; the later local
post-run consistency check did not turn that failure into a monitor pass.
See [entry 83](83-fresh-policy-selection-postrun.md).

For all 32 cases, matched saved scene bytes and initial robot/brick placements,
teacher shards and game transitions were checked using the existing L5
three-arm auditor. First consumption is the first **post-action** state with
the virtual consumed index set. The counts partition all 32 cases: teacher
alone consumed in 5, student alone in 10, both missed in 0, teacher consumed
earlier in 9, student earlier in 6, and both tied in 2. Among the 17 where
both consumed, the teacher was at least ten actions earlier once; the
student was never ten or more actions earlier. These timing categories do not
measure the quality of every intermediate action or future learning.

| Student-miss seed | Layout / variant | Teacher first consumption | Teacher deliveries | Teacher back-and-forth before consumption / full episode |
| --- | --- | ---: | ---: | ---: |
| 7820005 | 17 / 5 | 129 | 1 | 0 / 0 |
| 7820006 | 13 / 6 | 130 | 1 | 0 / 36 |
| 7820013 | 15 / 13 | 43 | 1 | 20 / 114 |
| 7820015 | 13 / 15 | 153 | 1 | 0 / 22 |
| 7820021 | 13 / 5 | 124 | 1 | 0 / 56 |

The before-consumption column reconstructs the existing 20-action reversal
heuristic using only actions strictly before consumption. A zero count does
not establish a safe or optimal route. The existing helper omits a window
ending exactly at the prefix boundary; an independent check including that
window gave the same five counts. One of the five helpful teacher
episodes had 20 flagged pre-consumption actions, and three others had flags
later in the episode. Blindly retaining every teacher trajectory or its full
return labels would not address those differences.

The cases are strongly correlated. Three of the five student misses use
layout 13; their recorded student action-and-pose trajectories match for all
300 actions, and their teacher prefixes match for the first 100. All ten
teacher-miss games use layout 15, and their recorded teacher actions and
poses match for all 300 actions. Each seed has a different saved placement,
but seed counts are not independent route evidence, and layout/variant and
initial appearance can be confounded. The teacher uses reference wall
geometry in addition to camera detections.

The read-only audit `python3 -B -I
experiments/fresh-l5-outbound-audit-v1/audit.py` verifies the current frozen
selection inputs, re-runs the existing L5 matched saved-game audit and checks
its result against the saved full report, requires clean L5 arm supervisor
receipts, and reconstructs these categories and reversal counts. Its two
small CPU tests cover missing/tie timing categories and common-prefix
boundaries. Recorded files and hashes are local evidence, not OS execution,
raw camera or neural-policy attestation. No new data was collected and no
model was trained. A future pilot must use separately verified fitting data,
select useful labels rather than every teacher episode, and evaluate against
appropriately independent scenes and the full reliability and loop gates.
