# Paired trainer one-update GPU smoke (4 Nov 2026)

The two candidate datasets from [entry 135](135-paired-parent-route-aggregates.md)
were each used for one monitored optimizer update from the same original
parent weights with a fresh Adam optimizer. Both arms used seed 7120260, the
same first fitting batch `[203, 934]` and mirror mask 3. Both ran initial and
post-update validation, reported the HIP backend and exited cleanly. This is
a smoke test, not a full epoch or a policy evaluation.

The saved checkpoints and gradient tensors were finite; the actor7 bias
gradient vectors differed in five of seven entries, one by approximately
9.3e-10. The first-gradient
SHA-256 values were
`cda60e39a6169b5c171e479b284452e3beca1d2dd79f8c33b38030618f532d80`
for teacher-label control and
`d7cc831d1c321dbe390d4a7fd87d85bb129bc3dea16e54746827da0bc3a4b8a4`
for parent-label treatment. The one-step outputs also differed. This is
evidence that the GPU path responded differently on this batch; it is not a
numerical gradient proof, full-epoch mask proof or evidence that either
policy performs better.

The guarded final check and an independent saved-evidence audit checked 154
registered input/source pins, all 88 inventory entries, data-copy evidence,
both arm audits and finite checkpoint tensors, plus supervisor and guardian
receipts. The independent audit did not repeat the complete older ancestry
traversal, which the guarded final and post-run checks performed. Across
1,426 guardian samples, minimum free disk was 45,749,735,424 bytes and minimum
free GPU memory was 9,372,073,984 bytes; samples do not prove GPU exclusivity.
The completion receipt SHA-256 is
`09441ef844cd1450937e14bc73fb6bf19a71b457a555995df1ada117dd8c0481`;
the final-result SHA-256 is
`e9fb2be021d6639e62429860599f444ee2c3224c6bf5b6c47c4a5b7b7b39c839`.

The retained diagnostic is at
`build/flex/sim/levels-v2/pitch82/parent-route-paired-smoke-v1/`. A full
matched epoch requires its separately reviewed complete batch/mirror journal,
and a genuinely new selection family and held-out ingestion protection remain
unresolved. Neither smoke checkpoint is promoted.
