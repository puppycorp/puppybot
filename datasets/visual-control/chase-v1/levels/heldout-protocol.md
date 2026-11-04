# Prospective virtual-fetch held-out protocol

This is a **reservation protocol**, not a completed benchmark. It evaluates
the current virtual-pickup / visual-docking game and cannot establish a
physical grasp, release, or delivery. The earlier `10/11` reserved final set
belongs to a different find-return workflow and is not consumed here. Legacy
`18/19` results informed selection and are development evidence.

The diverse scene generator reserves IDs **226–289** for `held-out`; these
cannot be generated under the fitting, validation or development roles. For
each level, use 32 games of 300 actions (60 simulated seconds), camera pitch
82 and wheel odometry. Levels 1–3 use layouts 226–257, alternating open and
two-room environments; levels 4–5 use the 32 two-room layouts 227–289. Each
level has 32 distinct recorded start poses and environment files. Game `i`
for level `L` has seed `1700000000 + 100*L + i`, scene variant `i % 16`;
the selected single policy and the exploring teacher use exactly the same
seed, scene and initial placement. A seed is not itself evidence of
independence.

`prepare-heldout.py GENERATOR NEW_OUTPUT PRIOR_ROOT ...` generates and freezes
the catalog without running a policy. Supply every known relevant fitting,
validation and selection root, including model-ancestry data, to its exact
scene-file and seed overlap check. Missing roots fail. The manifest records
the searched roots and their record counts, source/binary/template hashes,
all scene hashes and start poses. It cannot prove that the supplied roots
cover the model's entire ancestry, that similar geometry is absent, or that
the generator binary corresponds to the recorded source. Review those gaps
before relying on the reservation. The role restriction protects generation,
not ingestion: existing collection and control commands accept arbitrary
scene catalogs and do not reject `reservedHeldOut:true`. A fail-closed
training/selection ingestion guard is still needed. Until it exists, do not
create or use this catalog for an active training workflow. Do not inspect
policy performance on these games or use them to choose a checkpoint.
`preflight-training-scenes.py RESERVED_MANIFEST SCENE_OR_CATALOG ...` is a
staged check for this future integration: it rejects the reserved role and
exact reserved case/environment hashes even if role metadata was stripped.
It checks only explicitly passed inputs and is **not wired into native
control, collection, training or selection**; the caller must also pin the
reserved manifest itself. Repackaged semantically equivalent scenes can evade
an exact-hash check. The helper alone does not protect a holdout.

The intended gate compares one candidate fixed **before any held-out play**
with the same teacher on the same games, without teacher recovery in candidate
games. Record all binaries, model receipt/weights/policy/kernels, runtime,
scenes, script versions and selection evidence before the first game, and
verify hashes after each player. Retain failed games and logs; reject missing,
duplicate, timed-out, wrong-scene, wrong-start, wrong-model or incomplete
games. The goal metrics, reported separately by level, are:

- At least 29/32 games with one completed virtual pickup and return on each
  level; at least 29/32 first pickups on level 3.
- At least 80% of the level-4 **past-doorway placements** delivered. Multiple
  placements in one game are correlated; report the denominator and per-game
  outcomes rather than treating them as independent samples.
- Back-and-forth action share below 2%, plus the separately reported
  100-action search-return-to-pose indicator. The latter includes stationary
  cases and misses other loops; it is not a complete loop detector.
- Candidate deliveries/minute at least teacher deliveries/minute on each
  level, without sacrificing the reliability criteria above.

`audit-heldout.py` provides a provisional virtual-only comparison for the
planned output layout and insists on frozen input, policy snapshot, complete
trace and scene checks. It does **not** establish exhaustive ancestry,
pre-registration timing, robot-start provenance outside the recorded scene,
physical manipulation or the overall goal. A threshold result is not a
promotion. `evaluate-heldout.sh` is deliberately **disabled**: its proposed
selection receipt is self-asserted, and an independent verifier linking all
selection artifacts, including level 2 and standard-fetch checks, is still
needed. Do not remove that guard until the verifier and the evaluator have
been independently tested against incomplete, substituted and stale evidence.

`qualify-selection.py INDEX CHOICE_JSON NEW_RECEIPT` is a staged, deliberately
disabled verifier for the L3/L5 experiment. Existing lean result files do not
record exact control argv or the actor's carry-cue input: `--search-cue` can
change that input without leaving a result flag. Pinned script/library files
also do not prove which argv or runtime library the process actually used.
Qualification receipt creation therefore fails even if all selection pairs
exist, until an independent live execution and actor-input attestation is
implemented and tested. The intended verifier requires six 32-game paired selections: ordinary
fetching and levels 1–5, and re-audits their scenes, starts, model snapshots,
result traces, scores, training sources and preserved student labels. The
choice JSON must name schema `puppybot.selection-choice.v1`, a nonempty
`rationale`, `selectedWeightsSHA256`, `candidateReceiptSHA256`,
`trainingManifestSHA256`, and `selectionAuditSHA256` mapping each of
`standard`, `L1`, `L2`, `L3`, `L4`, `L5` to the corresponding paired-audit
file hash. It records the chosen candidate and selection observations; it
does not require the candidate to meet the held-out thresholds on training
layouts or automatically choose a candidate. `selection-pair-extra.sh`
stages the missing `standard` and level-2 pair formats, but has not been run
or proven end to end. Current selection evidence is incomplete, so the
verifier cannot yet issue a receipt. Even a valid receipt cannot prove when
the choice was made, that prior held-out data was unused, or that all model
ancestry and semantic overlap are known. The held-out runner remains disabled.

### Missing selection attestation

The current paired selection outputs are `--lean`. They do not record the
exact control argv, the actual loaded HIP library, or the actor input at the
instant of inference. `decisions.jsonl` is written after the action step:
its `proprio` values are not proof of the preceding actor input. In
particular, `--search-cue` modifies the carry-cue input without a result flag.
The staged qualifier rejects recorded intervention fields, but deliberately
refuses to create *any* receipt until those hidden cases can be excluded.

For a future instrumented selection run, the supervisor should capture and
bind the actual control argv, sanitized relevant environment, process
identities, executable hashes and loaded GPU-runtime files for every part;
pin the supervisor and runtime before play; and retain exit and timeout data.
The actor boundary should separately journal the resized image bytes, seven
feedback floats **after all cue modification**, pre-inference recurrent
memory, returned policy output and final applied action for every step. Each
record needs an unambiguous game seed, simulator frame and sequence number.
An independent verifier must check completeness, reconstruct actor input
bytes using the pinned normalization, rule out search-cue/action bias,
sampling, ensembles and teacher intervention, and link the model output to
the applied action. Replaying or checking policy outputs is a separate test;
a decision journal alone does not prove the model produced them.

`flex/control/actor-attestation.flex` and `audit-actor-attestation.py` are an
isolated writer/verifier prototype, **not wired into the active control
path**. The writer saves the resized image, exact float input buffer, raw
single-policy response and applied action before the environment advances;
the verifier checks normalization, frame/sequence alignment, standard carry
cue, previous-action feedback and recurrent-memory continuity; wheel and
steering feedback are checked against the recorded controller state. The
aggregated contact bit is only cross-checked against the prior journal, since
the saved state does not independently authenticate the protocol header.
A complete footer is required. It cannot prove that its buffers came from the actual
runtime, that the image came from the camera, that a model produced the
recorded response or what argv/libraries were used. It also depends on the
proposed integration placing the hook after final policy action selection and
before `ve_step`, which is not implemented or tested in a real policy run.
At 84×84 pixels and 128 memory values it writes about 107 kB per action, or
about 12.3 GB for six baseline/candidate pairs of 32 games with 300 actions,
before videos and other logs. Space limits and cleanup must be planned; do
not delete the recordings merely because a model trained successfully.

Source and supervisor changes require separate builds and tests; they must not
alter the binaries or manifests of any active experiment. Process/file hashes
and unsigned journals prove consistency within a recorded run, not trusted
wall-clock time, exhaustive model ancestry or absence of adversarial
fabrication. Do not enable the holdout runner solely because an attestation
file contains self-asserted flags.
