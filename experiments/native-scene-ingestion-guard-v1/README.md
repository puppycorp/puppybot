# Isolated native scene-ingestion guard

This is a CPU-only prototype of an integration point for protected
fit/validation collection. It does not modify the active control source or
binary, open held-out scenes, generate real scenes, or run a simulator or
GPU. The private transformed binary accepts only `collect --fetch` with an
explicit numbered scene catalog, a scene-guard policy and its SHA-256; it
refuses ordinary collection, run, correct, train and pack-data. In particular,
it cannot train a model: existing PVDATA lacks a guarded scene-lineage
binding, so admitting it would defeat this experiment's fail-closed scope.

`policy.py` prepares a canonical policy by invoking the separately reviewed
selection-role `SceneGuard` against the pinned selection and held-out
reservation manifests. It binds the split, starting seed, each numbered
scene's case/environment/layout digests, both manifest digests and their
reserved case/environment hash unions. The native binary reads both manifest
files, checks their digests and 160-entry index/seed/layout mappings, and
requires every case/environment digest in each to appear in the policy deny
lists. Both the preparer and native guard also reject a collection seed range
that intersects either reservation, including a range that crosses into one.
A reviewed higher-level plan must pin the policy and the intended
reservation manifest identities: a caller-supplied digest is self-asserted.
No actual reserved manifests are created here.

The private transform invokes `vg_prepare` after creating the output
directory, but before allocating the training dataset or starting the policy.
It validates every episode's policy index, seed, role, scene metadata and
three content hashes, rejects reserved layout ranges/markers and deny-listed
case/environment bytes, and copies all three files into per-episode snapshot
directories. Each source is copied to private memory before hashing, and
the layout role is checked on that same buffer before writing; the transformed `vx_scene` passes the
snapshots to the existing `ve_open` and `ve_reference` paths. A failed guard
can leave a partial output directory but no dataset or launched policy.
The split check requires fitting scenes to carry `fit:true` and validation
scenes `fit:false`. The current parent-route replay uses `fit:true` metadata
for both fitting and companion scenes; this guarded build intentionally
rejects that legacy convention and is not a drop-in replacement for it.

The policy digest, reservation sets and captured files do not establish
complete model ancestry, semantic similarity or independence; same-user
mutation of the snapshot after validation and non-atomic reads across files
remain possible. No guarantee extends to older unguarded binaries, dataset
files, or other ingestion paths. A production design needs a reviewed guard
for every entry point, a binding from collected data to the policy and scene
snapshots, and a fail-closed training-data lineage check. The existing
prospective held-out protocol remains disabled.

Run `python3 -B -I experiments/native-scene-ingestion-guard-v1/test.py`.
The tests compile the full privately transformed control binary and a native
guard probe, using only synthetic manifests and tiny files. They check split
and hash-bound snapshot behavior, content with stripped markers, role and ID
rejections, missing or incomplete deny lists, manifest drift, and fail-closed native command
dispatch. They include an actual protected collector invocation that rejects
a changed catalog before dataset or policy creation, and a compiled probe
that mutates the original catalog after snapshot and checks that `vx_scene`
still resolves the saved snapshots. They do not run a valid
simulator episode or prove that ordinary, uninstrumented binaries enforce
this policy.
