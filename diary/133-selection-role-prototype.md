# Selection-role preparation prototype (4 Nov 2026)

An isolated generator transform and manifest-preparation guard propose a
selection-only range of layout IDs 290–353 while retaining the separate
held-out range 226–289. No real scenes have been generated. The proposed
160-game seed and layout design is recorded in
`experiments/selection-role-prototype-v1/`; it is not evidence that the
scenes or all model ancestors are independent.

The CPU-only preparation checks a supplied pinned generator source and
binary, per-scene metadata and exact case/environment hashes, per-level
uniqueness of environments, start poses and canonical metadata geometry, and
exact overlap with supplied prior seed, case, environment and geometry
inventories. It records digests and counts of those supplied inventories.
An independent review found two gaps—duplicate per-level scenes and missing
prior case/environment overlap checks—which were fixed and re-reviewed. All
15 synthetic CPU tests passed.

These checks cannot prove the supplied ancestry is complete, that the binary
corresponds to the source, that metadata describes the binary world's geometry,
or that near-equivalent scenes are absent. The role guard remains an opt-in
prototype, not wired into the native collector or trainer; existing binaries
can bypass it. Multi-file snapshots are not atomic. A real selection catalog
requires those remaining provenance and ingestion boundaries to be resolved,
and the reserved held-out catalog must remain unused in this workflow.
