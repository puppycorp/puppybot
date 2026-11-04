# Parent-route companion boundary audit

`audit.py` checks one saved instrumented collector episode assigned to the
private shard's validation partition. It accepts only seeds 7820011 and
7820026, episode 1 of a two-episode dataset with one fitting episode and a
300-action horizon. These are **companion-only** histories: the proposed
later aggregate must not insert them into either its fitting or validation
data. A companion is not rejected merely for failing to deliver or for the
teacher and parent choosing identical labels.

The callable interface is `audit(data_path, map_path, actor_path,
boundary_path, seed, episode, rows, result)`. `rows` is the complete parsed
post-step decision journal, and `result` is the parsed collector result for
the same episode. It validates result seed, model, mode and delivery count;
data/map split, sizes and journal headers; every image, feedback, carry cue,
teacher action, map byte, validity weight, executed action and recurrent
state; actor/map boundary ordering and terminal footers. It checks the
teacher-disagreement count and task-state delivery transitions. The return
value reports first delivery and label differences if they occur, without
requiring either one.

This is a same-process saved-buffer consistency check. A separate outer
auditor must bind the frozen scene, simulator, policy, runtime and selection
records, independently audit the saved game and task-event journal, and
prove episode 1 belongs to the intended shard. The map-byte comparison does
not validate map geometry, and recorded actor buffers do not establish
independent camera provenance or actor execution. No GPU or real collection
is launched by this module.

Run `python3 -B -I experiments/parent-route-companion-audit-v1/test.py` for
the CPU native-boundary fixtures. They include no delivery, no label
differences, a successful companion, split and seed errors, changed sensor or
map data, changed actions and cues, task-state errors and missing footers.
