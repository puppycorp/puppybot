# Parent-route collection plan and lineage audit (4 Nov 2026)

The proposed paired-label experiment in [entry 128](128-parent-retention-feasibility.md)
now has a frozen CPU-only collector plan and a separately implemented
lineage audit. It fixes two parent-driven L5 fitting histories, seeds
7820010 and 7820025, with their next consecutive seeds as separate validation
companions. The fitting scenes were already inspected as selection examples;
they are not independent evaluation. The two fitting prefixes through the
first recorded delivery contain no marked inclusive 20-action back-and-forth
windows; seed 7820025 has flagged actions later in its full game.

The audit verified the parent receipt against its actual baseline dataset and
map hashes, the model, kernels, simulator/control binaries, runtime chain,
four scene copies and original selection records against the sealed prior
inventory. A separate review reran the actual lineage audit and four CPU
fixtures and checked the collector's mode, split and action-label semantics
against source. The pinned prebuilt control binary is not independently
proven to correspond to that source. None of these checks attests execution,
reconstructs actor inputs for new rows or supplies a new selection family.

The fixed plan SHA-256 is
`54acceb5e71859e1b6eb010dca66528733a317b8cbb100e5318cf95ec368604d`;
the published lineage-audit receipt SHA-256 is
`ea9261d0c488ecfe4e5cc0fa1430cb903685f9d8b4be5cd88d99e1b7b979af21`.
They are retained under
`build/flex/sim/levels-v2/pitch82/parent-route-collector-plan-v1/`.
A monitored collection runner and complete row/action/map alignment audit
remain necessary. No collector, training job or reserved held-out run has
been launched for this plan.
