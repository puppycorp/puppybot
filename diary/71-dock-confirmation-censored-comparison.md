# Simulated dock confirmation: censored comparison (3 Nov 2026)

The three-arm rendered simulator trial completed, but its saved comparison was
**censored**: the two confirmation-disabled controls diverged during
collector search. The enabled arm recorded dock confirmation and a simulated
capture, but no release or delivery. The control divergence prevents an
attribution of the later outcome to confirmation. This is one previously used
selection case, not a held-out or physical-robot test.

All three arms used the same candidate simulator binary and search fallback.
The first two disabled confirmation; the third enabled it. Each recorded 90
navigation actions without an ordinary target handoff, followed by a
search-only ACK 8 at tick 1,397. Their saved actor RGB, feedback, recurrent
state and action files matched across all 90 actions. The journal prefix
through navigation also matched; these local records do not independently
attest actor execution or raw-camera provenance.

The two disabled controls shared the same saved journal through sequence 116.
At sequence 117, tick 1,897, their first journal difference was the simulated
joint ticks: `[1035, 375, 3120, 2652]` versus `[1035, 374, 3119, 2653]`.
The trace shows the next scan arm target issued at tick 1,895 in the second
control versus tick 1,896 in the first; this is an observed timing difference,
not a confirmed underlying cause. It arose before the enabled arm's recorded
confirmation. The audit requires the two disabled-control journals and their
manipulation outcomes to match, and both conditions failed. Its
`comparisonEligible` and `mechanismEligible` are false with reason
`saved_prefix_or_initial_truth_mismatch`.

| Arm | Box learned | Simulated capture | Final observation |
| --- | --- | --- | --- |
| First disabled control | tick 25,089 | tick 26,719 | Collector failed at tick 29,354: box not reacquired during bounded circular camera search; object still held |
| Second disabled control | not recorded | none | Poll limit at tick 31,377; search still active |
| Confirmation enabled | tick 11,143 | tick 13,830 | Collector failed at tick 16,210: box not reacquired during bounded circular camera search; object still held |

In the enabled trace, one confirmation run began at tick 11,141. Fresh valid
dock-frame IDs 11,141, 11,142 and 11,143 were recorded; the latter set
`boxLearned` and the run ended with confirmation reason 4. The first frame
was the travel observation that initiated the zero-drive command; the other
two followed it. Saved commanded wheel speeds were zero while the confirmation
state was active. These values demonstrate the recorded simulator state only:
zero commands are not evidence of physical braking or independent image
measurements.

The independent manipulation audit found no release or settled delivery in
any arm. Both arms that captured ended with the simulator gripper holding the
object; neither completed the task. The disabled arm that reached its
1,499-poll limit reported `collectorTerminal:false`, followed by simulated
stop ACK 7. Terminal ACKs in the other two arms represented collector failure,
not delivery success.

All three arm supervisors and the outer and final-inventory supervisors
recorded clean exits. The resource monitor passed, and `completion.json`
retains the censored comparison status. Its recorded audit, telemetry, disk
and supervisor-status hashes were rechecked. Minimum sampled free GPU memory
was 9.096 GiB and minimum sampled free disk was 45.622 GiB; sampling cannot
exclude brief conditions between samples or prove exclusive GPU use.

Evidence: `build/flex/sim/levels-v2/pitch82/physical-dock-confirm-monitored-v1/`,
especially `trial/audit.json`, each arm's `physical-agent.jsonl` and
`trace.jsonl`, and `completion.json`.
