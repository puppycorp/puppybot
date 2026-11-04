# Paired parent-route candidate aggregates

This is CPU-only preparation for the label-substitution comparison in
`diary/128-parent-retention-feasibility.md`. No real aggregate or trained
model has been created by these scripts. The fitting episodes use previously
inspected L5 scenes and are not independent selection or held-out evidence.

The baseline is the 1,029-episode, 933-fitting five-prefix aggregate. The
two verified fit episodes from `parent-route-instrumented-collector-v1`
(seeds 7820010 and 7820025; first delivery at actions 163 and 189) are inserted
before the original 96 validation episodes. Both outputs contain 1,031
episodes with 935 fitting. The two companion episodes are not inserted.

Control retains teacher labels on each added first-delivery prefix; treatment
uses the recorded executed parent actions on those same rows. After each
cutoff, both variants have zero action-label bytes and zero supervision
weight, with valid frames, feedback, maps and recorded executed actions
retained. All other bytes must match between arms, and every original episode
must match its source. The verifier requires exactly 35 and 31 prefix label
differences in the real source. This compares action-label substitution, not
the isolated effect of earlier teacher prefixes or proof of generalization.

The zero-weight suffixes still contribute to some existing trainer auxiliary
losses unless explicitly masked. Before training, a separately reviewed
trainer must support exactly 1,031/935/300 and mask auxiliary loss seeds for
zero-weight rows in the half-open fitting episode range `[928, 935)`; it must
also preserve normal baseline and validation supervision. Dataset byte
verification does not establish that trainer behavior. The result stays
`trainingAuthorized:false` until a separate trainer plan and audit.

`plan.py` checks the baseline data, maps, full byte/order reconstruction,
its supervised CPU receipt, the completed instrumented collector and
guardian chain, its complete local inventory and saved-game/boundary audit.
It fixes every source path, seed, cutoff, source hash, tool and eager local
module hash before creation; frozen inputs are rechecked afterward. These
are local consistency checks, not independent proof of raw camera data,
world-map truth, actor execution or complete model ancestry.

The writer requires Btrfs `FICLONE` into exclusive new single-link inodes;
there is no hard-link or copy fallback. It creates the control output first,
then rechecks the full worst-case *unshared* logical size of one output plus
the 34 GiB active floor, and at least 38 GiB, before creating treatment. If
the second reservation fails, the completed first arm is retained and the
second is not created. A lock-owning subreaper samples disk and GPU during
the serial worker, final audit and cleanup; it holds the shared experiment
lock until descendants are reaped and escalates on the 32 GiB emergency floor.
Samples cannot exclude brief unobserved changes or hostile same-user races.

The separately supervised final process runs the independent byte verifier
after worker cleanup and checks input pins, fixed sources, output hashes and
the exact output inventory. After guardian cleanup, an additional read-only
output/source recheck is bracketed by disk-floor checks but is not continuously
sampled or lock-protected. Failure leaves all partial evidence intact. Direct
CLIs are disabled; separate review, registration and supervised scheduling
are required before invoking the importable functions.

CPU checks:

```
python3 -B -I experiments/parent-route-paired-aggregate-v1/test.py
python3 -B -I experiments/parent-route-paired-aggregate-v1/verify-test.py
python3 -B -I experiments/parent-route-paired-aggregate-v1/supervise-test.py
```

The small integration fixture uses the real workspace Btrfs reflink writer
and independent verifier with synthetic actor/map-boundary records. Separate
read-only source checks have validated all 300 real recorded rows per selected
fit episode; neither check establishes model or physical performance.
