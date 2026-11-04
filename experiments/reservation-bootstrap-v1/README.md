# Reservation bootstrap: scoped execution boundary

This is a design for closing the bootstrap gap in the prospective virtual
fetch protocol. It is not an executable guard or permission to generate,
inspect, ingest or evaluate real held-out scenes. No reservation material
has been generated for this design.

The existing private native guard requires both complete, hash-pinned
160-row reservation manifests and checks that its denial policy includes
every listed case and environment hash. Before those scenes exist, their
hashes are unknown. A declaration containing only layout IDs and seeds is
not a substitute: scene metadata can be removed or changed while scene
bytes remain, and placeholders would falsely imply that exact-content denial
is enforced. The current held-out protocol remains disabled until its
ingestion boundary is demonstrably in place.

## Proposed sequence

1. Freeze a schema-distinct **declaration**, not a reservation manifest.
   It names the fixed held-out and prospective selection layout/seed mappings,
   the reviewed generator recipe and source, its reproducibly built binary,
   and all known dataset and model ancestry. It contains no invented scene
   digests. Its status permits neither reserved generation nor policy play.
   Missing ancestry stays explicitly unknown rather than becoming a claim of
   independence.
2. Before materializing reserved content, demonstrate a scoped protected
   execution boundary using synthetic scenes and manifests. It must permit
   only explicitly pinned protected executables and exact command forms,
   provide only individually pinned approved scene triplets and datasets,
   snapshot the bytes actually consumed, and reject every unsupported input
   path before creating a dataset or starting a policy. A caller-provided
   policy or manifest hash is not the trust anchor: the reviewed plan must
   bind the exact identities independently. Deny training from any opaque
   dataset until a recursively checked lineage binds its scenes, source
   records, transformations, split and digests. An allowlist can deny all
   other content before the future reserved hashes exist; it cannot prove
   that approved ancestry is complete or semantically disjoint.
3. Only after that boundary and its failure tests pass, use a separately
   supervised offline generation process without model or simulator access
   to materialize the predeclared scenes into a protected vault. Check the
   reproducible generator build, exact layout/seed mapping, binary-world
   geometry against metadata, uniqueness, and overlap against the complete
   known ancestry. Freeze the resulting actual scene hashes and manifest
   identity; the native denial policy can then bind real hashes. Do not run
   a model or use held-out results to choose a candidate in this phase.
4. Keep policy evaluation disabled until a candidate and the complete
   selection evidence are fixed under the prospective protocol. The final
   evaluator must separately bind the candidate, teacher, exact scenes,
   runtime and execution/actor records. The declaration and bootstrap tests
   alone are not a qualification receipt.

## Required bypass tests and scope

Before treating step 2 as complete, test the *actual* execution boundary,
not only a helper: legacy executable invocation; `collect` with direct scene,
catalog or a reserved seed range; default/non-chase collection; `correct`;
`run`; `train --data`; `pack-data`; missing, forged or changed data lineage;
same reserved scene bytes with markers removed; catalog retargeting; source
or policy changes between check and consumption; and child processes escaping
the intended executable/data restrictions. Each unauthorized attempt must
fail before policy startup or dataset creation, with failure and cleanup
recorded. A production proof also needs complete known-ancestry inventory,
identity checks on the protected binaries and data, and independent tests of
the actual consumed bytes. Synthetic success is not a rendered rollout.

The active control executable has several independent scene and dataset
ingestion routes; guarding only `vx_scene` does not cover direct scene,
correction, default collection, packing or training from `--data`. Existing
historical binaries can also be invoked outside a private wrapper. A scoped
boundary can reject evidence produced outside it, but cannot prevent an
unrestricted same-user shell from running those binaries. Claiming global
no-bypass enforcement would require integrating the checks into all active
ingestion paths and constraining execution and data access at an appropriate
OS boundary. Exact hashes and metadata cannot rule out equivalent repackaged
geometry or forgotten model ancestry.
