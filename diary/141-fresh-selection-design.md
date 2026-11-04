# Fresh four-arm selection design (4 Nov 2026)

A prospective selection design compares the original parent, the matched
teacher-label and parent-label epoch-1 checkpoints, and the teacher on the
same 160 games: 32 per level, 640 arm-games in total. It defines per-level
delivery reliability and rate, first L3 virtual pickup, doorway outcomes
including unresolved placements at the horizon, inclusive 20-action
back-and-forth, and a separate 100-action search-return loop measure. It also
reports matched treatment wins/losses and reliability against both student
references. These are simulator task metrics, not physical grasp evidence.

The design checks model, scene, initial placement and score-version identity
across arms. Its CPU tests cover the metric thresholds and first/final loop
windows, scene/placement mismatches, teacher-rate comparisons for all three
student arms, and float32 collider geometry comparisons. Independent review
found and verified fixes for an omitted first long-loop window, score-version
confusion, mismatched identities, float32-versus-float64 geometry and a
missing parent-versus-teacher rate field. The current design does not itself
bind every game to a registered scene; an outer run auditor must do so.

A read-only ancestry inventory reconstructed 48 named parent-training shards
and 1,024 games. It is not complete pretraining ancestry, proof of rendered
geometry or exclusion of near-equivalent environments. The design also
depends on trusted reservation manifests and protected ingestion that do not
yet exist. No real fresh-selection or held-out scenes have been generated,
no selection plan registered, and no GPU evaluation run. Artifact:
`experiments/fresh-selection-design-v1/`.
