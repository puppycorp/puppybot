# Matched simulator dock-survey recording

This diagnostic uses the previously studied selection case and one isolated
simulator binary in all three arms. Search fallback and dock confirmation are
enabled in every arm. The first two arms have survey recording disabled; the
third records wrist RGB, estimated camera calibration and circular-viewpoint
planner results into its own fresh directory. Neither this case nor the
instrumentation establishes physical performance or held-out reliability.
Synchronous file writes can alter timing, and the two controls themselves
diverged during the earlier dock trial. A control mismatch censors the matched
comparison. Recording a useful image is not proof of the cause of failure or
of improved pickup and delivery.

The runner reuses the existing saved protocol, actor-prefix, manipulation,
scene and process-supervisor audit. The `surveyDiagnostic` audit checks image
lengths, camera metadata, trace counters and write errors, candidate reason
records and frame/tick linkage. The saved plan counter must match the number
of unique candidate files; missing or duplicate records fail the audit. It
marks `observationEligible` false when no
survey image was recorded. It strips only its own added diagnostic counter
from the *comparison* of initial simulator state, then independently checks
the original recorded counter. The monitor inventories all output files,
including the raw images and candidate JSON, and repeats the audit before
publishing a censored or diagnostic result.

The isolated CPU build uses fresh `dock-survey-diagnostic-build-v1` and
`dock-survey-diagnostic-build-cpu-monitor-v1` paths, the shared pitch82 lock,
low CPU/I/O priority and a bounded child supervisor. The rendered trial uses
the existing GPU and disk monitor: 30-second baseline, at least 36 GiB free
before work, 34 GiB during collection/final audit, 32 GiB at completion,
separate process deadlines and final output inventory. Direct CLIs remain
disabled; execution requires independent review and a dedicated process.

After review, call `launch()` from `build-supervisor.py` in a dedicated,
low-priority process; check its `result.json` for `isolated_build_only` and
clean supervisor status. Then call `launch(output, build, case, environment,
model)` from `monitor.py` in another dedicated process. Use an absent output
directory under `build/flex/sim/levels-v2/pitch82`, the build path above, and
the `case.json`, `environment.bin` and `model` under
`physical-hybrid-hidden-v1/inputs` in that same directory. Do not use a shared
diagnostic output directory between arms. A nonzero exit, missing completion,
write error, or incomplete/mismatched input is retained as censored evidence.

CPU checks:

```
python3 -B -I experiments/dock-survey-diagnostic-v1/test.py
python3 -B -I experiments/dock-survey-trial-v1/test.py
```

The six trial tests include a real disposable simulator build, provenance and
binary-tamper checks, a supervised build-worker fixture, subprocess import
routing, diagnostic-file validation and a complete synthetic three-arm audit
with a changed actor prefix. They do not render a scene, prove GPU exclusivity,
or attest the recorded actor's execution. The diagnostic simulator build and
rendered trial have not yet run under their permanent monitored paths.
