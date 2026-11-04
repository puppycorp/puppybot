# Matched visual-search transfer diagnostic (staged)

This simulator-only experiment tests `visual-search-recovery-v1` on the
previously used physical-hybrid selection case. It runs one copied client and
one unchanged search simulator in all three arms. Search fallback is enabled
in every arm; the first two disable visual transfer and the third enables it.
The two controls help reveal nondeterministic collector behavior. No
held-out scene or physical robot is used.

Each arm uses the same model, initial case, 90-action navigation ceiling,
1,499-poll collector ceiling and 300-second watchdog. Early visual transfer
can shorten navigation and therefore does not provide an equal fixed-duration
throughput comparison. The audit reports each complete, unfinished or failed
simulated manipulation outcome independently; an ACK, handoff, trigger or
terminal collector reply is never counted as a delivery. A poll-limited arm
is unfinished, not a successful recovery. Missing or unclean arms and
mismatching initial states, full control journals/outcomes, or actor/protocol
prefixes censor comparison. A target handoff at transfer remains unverified.

The candidate must additionally pass the individual visual protocol audit,
which reconstructs the first five identical resized image buffers, fresh
ticks and nonzero simulated drive echoes from the saved actor and trigger
images, and checks that the search request follows the trigger immediately.
The final trigger image is separately compared byte-for-byte with the input
at the same observation sequence in both disabled controls; a mismatch or
missing control image prevents a valid matched comparison.
`mechanismEligible` means an early trigger was recorded in a matched
comparison; it does not mean the brick was found, grasped or delivered. The
simulator-truth manipulation audit independently checks capture, release and
settling after collector ownership. The image records and intended commands
do not independently attest raw camera freshness or actor execution, and
simulated stop echoes do not prove physical braking. The collector itself
uses simulated grasp and containment state. Exact image repetition can falsely
trigger on a frozen camera or fail to trigger with sensor noise.

The previously saved search-fallback trace on this scene has a reconstructed
first repeated-image trigger after action 49, sequence 50, tick 985. This is
retrospective, based on one reused training-family trajectory. Runtime timing
or changed client behavior can produce a different trajectory, so a no-trigger
candidate is censored for mechanism assessment rather than silently omitted.
The existing fallback control experiment already showed collector divergence,
so reproducibility is not assumed.

`build.py` copies the archived fallback source, applies only the reviewed
visual client transform and detector, compiles a fresh client and copies the
same archived simulator. The two baseline binaries are byte-identical copies
of the candidate binaries. Build verification checks the archive, transformed
source, compiler, copied library and all four binaries. `build-supervisor.py`
reuses the locked, low-priority bounded CPU build supervisor. `monitor.py`
reuses the GPU/disk monitor, three per-arm process supervisors, independent
final audit and output inventory. Direct command-line entry points are
disabled. Independent review is required before execution; all output paths
must be fresh and the GPU baseline must pass. Disk gates remain 36 GiB before
work, 34 GiB during collection/final audit and 32 GiB at completion.

The fresh CPU build paths are `visual-search-matched-build-v1` and
`visual-search-matched-build-cpu-monitor-v1` under
`build/flex/sim/levels-v2/pitch82/`. Following independently reviewed build,
call `monitor.launch(output, build, case, environment, model)` in a separate
dedicated process using an absent monitored output directory and the case,
environment and model in `physical-hybrid-hidden-v1/inputs`. These inputs are
checked against the recorded selection reference and copied into the trial.
Incomplete runs are retained, not overwritten.

CPU checks:

```
python3 -B -I experiments/visual-search-matched-v1/test.py
```

The tests compile the complete copied client and test the supervised build
worker, source/binary tampering, fresh-process monitor routing, three-arm
synthetic early-transfer audit, altered trigger image and mismatched actor
prefix. They do not run the real rendered simulator or actual neural policy.
No permanent build or rendered trial has been launched by this staging work.
