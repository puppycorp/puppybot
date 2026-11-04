# Five-prefix checkpoint: five-level selection (4 Nov 2026)

The fixed epoch-1 checkpoint from [entry 120](120-five-prefix-training-result.md)
was compared with its original student parent and the reference teacher on
the same 32 previously used training-family scenes per level, each for 300
actions (60 simulated seconds). The seeds recur across levels. This is
selection evidence, not unseen-room or physical validation. Each table cell
shows games with a virtual delivery / 32; deliveries per simulated minute;
and the inclusive 20-action back-and-forth share of 9,600 actions.

| Level | Parent | Five-prefix checkpoint | Teacher |
| --- | --- | --- | --- |
| L1 | 29/32; 6.000; 4.198% | 31/32; 6.156; 4.177% | 32/32; 7.469; 11.948% |
| L2 | 32/32; 5.219; 5.260% | 32/32; 5.156; 6.344% | 32/32; 5.219; 6.927% |
| L3 | 28/32; 2.063; 1.063% | 28/32; 1.875; 2.125% | 32/32; 2.688; 1.208% |
| L4 | 32/32; 3.000; 1.979% | 32/32; 2.781; 2.583% | 26/32; 2.344; 10.979% |
| L5 | 26/32; 1.125; 4.063% | 23/32; 0.969; 4.115% | 20/32; 0.875; 16.906% |

The checkpoint meets neither the per-level delivered-game threshold nor the
strict loop threshold across all levels. First virtual consumption on L3 was
29/32 for the checkpoint, 28/32 for the parent and 32/32 for the teacher.
On L4, opposite-side placements delivered by the horizon were 39/66 for the
checkpoint, 42/70 for the parent and 31/58 for the teacher; these denominators
include unresolved placements at the time limit. Later placements vary by
trajectory, so the denominators are not a matched set of brick positions and
do not estimate eventual success.

The independent 50-action search-loop indicator flagged 77/5,933, 50/6,046,
298/6,773, 156/6,306 and 107/7,417 search actions for the checkpoint on L1
through L5 respectively. This heuristic is distinct from the 20-action
back-and-forth measure and does not cover every longer loop. Virtual pickup
and delivery are simulator task events, not demonstrated physical grasp and
release. A teacher comparison with privileged map information is a research
reference, not a deployable onboard policy.

The five new teacher prefixes are not isolated as the cause of any difference:
the checkpoint also had an additional epoch, a lower learning rate and a
fresh optimizer state. The training loss decrease is not proof of a better
fetch policy. No checkpoint is promoted from this comparison.

All 15 arm supervisors saved results. A separate re-audit recomputed all 480
games and reproduced the complete report SHA-256
`c8e2008b5db7b088186399081edaaea17f1d7712117186bfe4d9f14b0019291a`.
The resource monitor passed, and the final inventory and outer supervisors
exited cleanly. The final inventory checker reported `final_inventory_verified`;
the completion receipt SHA-256 is
`d37c1b6569d0ff7b68f1574933c9b68e46db04824c6002963adbeea4ad6fc6cf`.
An independent full final-inventory recomputation also returned
`final_inventory_verified` and checked all ten completion-receipt hashes.
Across 1,586 GPU samples the minimum recorded free memory was 8,569,241,600
bytes; across 1,557 disk samples the minimum recorded free space was
46,354,534,400 bytes. Sampling does not prove GPU exclusivity or exclude brief
unobserved conditions. The original earlier v2 comparison's monitor failure
remains unchanged. Artifacts are under
`build/flex/sim/levels-v2/pitch82/fresh-policy-selection-v3/` and
`fresh-policy-selection-monitored-v3/`.

Five L5 seeds shared one layout and starting pose but different brick
placements. The checkpoint took the same 300 actions and delivered none on
all five; the parent delivered on four of those games where the teacher also
failed. The two students first diverged before the case detector recorded a
brick in those games. Because raw actor frames were not saved, the identical
checkpoint trajectories do not establish that the policy saw the different
bricks or that perception failed. A targeted, matched replay with saved actor
frames can investigate route coverage without treating these scenes as held
out.

An additional descriptive breakdown assigns each flagged back-and-forth
action to its saved post-action virtual phase. For the checkpoint, L1 has
250 return, 138 search and 13 delivered-state actions; L2 has 325 return,
260 search and 24 delivered-state actions; all 204 flagged L3 actions have a
search post-state. L4 has 101 return, 144 search and 3 delivered-state
actions; L5 has 174 return and 221 search. The phase totals match the
independently reconstructed inclusive metric. These post-action labels are
not an explanation of why a loop occurred; in particular, a transition action
can be attributed to the later phase. The reproducible read-only diagnostic
is `experiments/backforth-phase-audit-v1/audit.py`.
