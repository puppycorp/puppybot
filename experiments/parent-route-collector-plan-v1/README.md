# Parent-route retention collector plan

This is a CPU-only plan and independent local lineage audit for the matched
label-substitution proposal in diary 128. It does not prepare a catalog,
launch a collector or authorize training. It deliberately reuses known
selection scenes, which become fitting-family data; it does not create an
independent selection family or touch reserved held-out IDs 226–289.

Two separately supervised two-episode shards are proposed, in this order:

| Shard | Episode | Role | Seed | Scene | Prior first delivery |
| --- | --- | --- | --- | --- | --- |
| 0 | 0 | fit | 7820010 | 15/10 | 163 |
| 0 | 1 | companion only | 7820011 | 17/11 | 223 |
| 1 | 0 | fit | 7820025 | 15/9 | 189 |
| 1 | 1 | companion only | 7820026 | 17/10 | 175 |

The two fitting histories share a layout and start and are correlated. The
two second episodes satisfy the collector's positive validation split; the
proposed aggregate uses the original 96 validation histories and must never
insert either companion into fitting or validation. A new later selection
requires a separate ancestry and scene-role audit; the held-out ingestion
guard is not wired into the active training or selection path.

Both commands use the same fixed parent policy, two episodes, 300 actions,
level 5, camera pitch 82, wheel odometry, exploring teacher and map recording.
No `--self-imitate`, sampling, action noise or intervention is included. In
mode 3 the parent drives, but the PVDATA01 label is the teacher action. At
row `i`, RGB and feedback are captured before the parent action; the same
row's teacher label is written before `ve_step`. `decisions[i].action` is the
action actually executed, while that journal's state and proprioception are
post-step. This source-level interpretation is pinned and tested; the
current source files have not been proven to correspond to the pinned
prebuilt binary.

Before any collection, a separate reviewed runner must safely stage the two
one-shard catalogs, hold the shared experiment lock, pin source/binary/model,
scene and runtime before and after, enforce disk and GPU limits continuously,
clean process descendants, and retain failed output. It must verify that the
actual actor input includes the carry cue. Each game must match its fixed
selection seed, initial placement and executed actions/events; any mismatch
is a failure rather than evidence of an equivalent trajectory. For each fit
episode, audit the complete 300-step action-to-row alignment, every feedback
and carry-cue transition, RGB/frame association, scene and map history,
finite joint-seven teacher and executed actions, row masks and exact first
delivery boundary. Include only the first successful cycle, and screen the
bounded-prefix-inclusive back-and-forth actions. Require nonzero actual
teacher-versus-executed label differences. These are proposed future audits,
not claims about data not yet collected.

The current model receipt's data and map hashes are checked against the
complete retained parent aggregate. Its selection evidence links both model
and the four original games to a clean monitored comparison. These checks do
not establish complete model ancestry, pre-inference actor execution,
raw-camera provenance, teacher quality or semantic scene independence.

Run `python3 -I experiments/parent-route-collector-plan-v1/plan.py` to print
the current input snapshot; hash and preserve that output as the proposed
frozen plan. Run `python3 -I experiments/parent-route-collector-plan-v1/audit.py
PLAN_JSON` for a separately implemented independent lineage check. Both read
the entire parent data and map to confirm their hashes; they can take time and
are CPU-only. `python3 -I experiments/parent-route-collector-plan-v1/test.py`
checks split, command and source-order regressions with small fixtures.
