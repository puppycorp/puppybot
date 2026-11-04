# 65. L5 three-action steering diagnostic (staged, 3 Nov 2026)

This simulator-only draft tests whether a one-shot early steering intervention
changes long searches. In the completed heading selection, all 17 treatment
games that consumed a target but did not deliver began with three reverse
`(-0.6, -1.0)` actions. Ten of 12 delivered games began with the opposite
steering sign, but those ten were on one layout; this association is
confounded by layout and does not establish causation. Earlier heading
factorial results motivate an intervention test; the separate small
straight-logit bias changed no actions and is not reused.

A fresh isolated control build provides control and intervention flags in the
same binary. If the first proposed steering is <= -0.5 and speed <= -0.8,
the intervention flips nonzero steering signs for at most the first three
0.2-second actions while preserving each proposed speed. Policy inference
continues at every action; the existing simulator carry cue latches
cancellation. This cue is virtual task state, not a physical sensor. The hook
records proposed and applied float32 action bits, pre-action feedback,
recurrent-state and image digests, quantized commands and simulated motor echo.
The saved-data audit checks the rule, state-derived carry transitions,
previous-action and own-drive feedback, recurrent digest continuity, scene
and start matching, and the recorded virtual-fetch metrics. Local digests and
intent do not independently authenticate OS execution, actor computation,
camera-to-input conversion, physical motion, braking or hardware safety.

The draft plan contains 12 paired games: four variants each on previously used
training-family layouts 13, 15 and 17, with fixed seeds 6800100–6800111. Its
exploratory screen includes all games, including no-ops: at least six
activations, at least three additional games consuming by action 200, no
fewer games with a virtual delivery and no increase in mostly back-and-forth
games. Missing or unverified games censor the comparison. Report first room
entry, consumption time with misses capped at 301, virtual delivery, contacts,
back-and-forth, and search path. The saved path metric uses post-action search
poses and excludes the start-to-first-action and final consumption transition.
This is not a winner rule, held-out qualification, or learned policy promotion.

Registration inventories `result.json` and `report.json` seed metadata under
explicit known training/selection roots, including the known 60 source-shard
reports, while skipping held-out-labelled and symlinked directories. The scan
cannot prove absence from unrecorded history or pretrained ancestry. The 12
scene files, their canonical symlink spellings, roles, room bounds, partition
and spawn, isolated binary, model, source, runtime and relevant tools are pinned
before play. Inventory or identity mismatch fails closed; no alternative seeds
are selected automatically. A later independent held-out protocol remains
disabled.

The source transform, real native CPU probe and saved-pair tests passed six CPU
groups. The paired runner/inventory tests passed nine groups, and the execution
monitor passed 13 independent CPU groups. Separate CPU registration and build
watchdogs each passed four independently reviewed groups. No actual isolated
build, frozen plan, steering game, GPU
job or production data hash has been run for this experiment. All direct
entrypoints remain disabled. Existing benchmark sources and evidence were not
modified.

After the active teacher benchmark has fully finished, with the independent
build-watchdog and registration/runner reviews passed, the intended
stages are separate dedicated processes from the project root. These commands
are documented for scheduling, not executed by this entry:

```sh
python3 -I -c 'import importlib.util,sys; s=importlib.util.spec_from_file_location("m",sys.argv[1]); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); sys.exit(m.launch())' experiments/l5-steering-kick-v1/build-supervisor.py
python3 -I -c 'import importlib.util,sys; s=importlib.util.spec_from_file_location("m",sys.argv[1]); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); sys.exit(m.launch())' experiments/l5-steering-kick-v1/register-supervisor.py
python3 -I -c 'import importlib.util,sys; s=importlib.util.spec_from_file_location("m",sys.argv[1]); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); m.launch()' experiments/l5-steering-kick-v1/monitor.py
```

Each prior stage must finish with a clean supervisor and its expected receipt
before the next is considered. All output paths are fixed and refuse overwrite;
failures retain partial evidence. The first two stages are bounded CPU work;
the build watchdog checks output/workspace/home have 36 GiB free at startup,
and the build checks 32 GiB on the output filesystem before its receipt. It
does not continuously monitor disk during the build.
The third is the separately monitored GPU experiment. The execution monitor
uses a 30-second baseline, 36/34/32 GiB disk thresholds on output/workspace/home,
6/2 GiB VRAM thresholds, a 19,800-second monitored phase and separate
900-second final inventory. Its 18,000-second worker ceiling covers all
24 × 600-second arm limits plus 3,600 seconds of setup and audit allowance;
the monitored phase adds 1,800 seconds for baseline and other checks.
Exceeding a bound still censors the run. Sampled
telemetry does not prove exclusive GPU use or absence of transient interference.
