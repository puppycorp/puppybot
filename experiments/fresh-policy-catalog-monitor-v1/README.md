# Catalog-aware inventory for future selection runs

This is an adapter for a **future**, separately reviewed selection runner. It
does not modify, resume, or convert the failed v2 monitor to a pass. It does
not supply a new seed, frozen plan, data qualification, executor or GPU entry
point. Future seed/history and held-out boundaries must be established before
any collection.

Before a future registration, the runner must call `require_fresh()` for
distinct output, monitor and manifest paths. Production paths must be direct
children of `build/flex/sim/levels-v2/pitch82` with matching versioned names:
`fresh-policy-selection-vN`, `fresh-policy-selection-monitored-vN` and
`fresh-policy-selection-plan-vN.json`, where N is at least 3. It rejects
existing paths, symlinked parent components, other directory names and
overlap with the existing v1/v2 selection paths. Both `require_fresh()` and
`install()` default to the production `pitch82` root; a production runner
must use that default. The `base_dir` override exists for disposable tests and
must not be controlled by a runtime or untrusted input.

The future frozen manifest must include the hashes of this adapter, the
separately reviewed postrun inventory helper, and **all transitive modules
loaded by those implementations**. The postrun helper currently imports the
v2 retry module, which imports the original selection module and its helpers,
even though the adapter uses only the postrun inventory functions. Pinning
the two files explicitly checked by `install()` is therefore necessary but
not sufficient. The future caller must enumerate and revalidate those
transitive sources, as well as the full selection input/runtime/history
inventory, before and after the run.

The runner must set the monitor paths and call `install()` in **every fresh
monitor and final-audit subprocess**. The adapter checks its source pins and
frozen plan, then replaces only the monitor's inventory callback. The callback
checks the plan before and after a no-follow traversal and accepts exactly the
160 catalog link names and targets derived from that frozen plan. Missing,
retargeted, replaced and extra links fail closed; regular output files are
hashed and all other node types are rejected. These checks are local
consistency evidence, not an atomic snapshot, OS execution attestation or a
guarantee against concurrent adversarial retargeting. The runner must keep
the existing saved-game audit, GPU/disk limits, process supervision and final
failure handling.

CPU test:

```
python3 -B -I experiments/fresh-policy-catalog-monitor-v1/test.py
```

The fixture runs the existing monitor's `_worker` and `final_check` in two
fresh Python subprocesses, each reloading the adapter, against a third fixture
process creating all 160 expected links and two metadata files. GPU telemetry,
resource sampling and registration are mocked. It confirms that a retargeted
or unexpected link fails the final inventory. Other tests reject old,
existing, mismatched-version or nested paths, symlinked parents and missing
source pins.
This is not a GPU run or an end-to-end selection evaluation.
