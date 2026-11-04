# Synthetic positive-allowlist bootstrap

This isolated **snapshot-only** native executable explores the first step of
the bootstrap described in `experiments/reservation-bootstrap-v1/`. It does
not invoke a simulator, collector, policy, trainer or any child process. It
does not generate, open or inspect real selection or held-out scenes. The
prototype accepts only an allowlist marked `synthetic_only` and is not an
authorization to materialize the prospective reservation.

The private builder embeds the exact SHA-256 of a synthetic allowlist in the
compiled binary. Its only command is `snapshot ALLOWLIST CATALOG OUTPUT`;
the caller cannot provide a replacement digest. The native executable checks
the embedded digest, fixed row/index/seed/split, exact case/environment/layout
content hashes, valid layout role, reserved layout and seed ranges, and
duplicate case/environment digests. Unknown or changed inputs fail before
the output directory is created. All approved source bytes are copied into
process-owned buffers and validated before the executable writes the same
buffers into a new snapshot tree. It copies the allowlist into the output for
later lineage inspection and hashes each written file on readback. An existing
output is never intentionally reused.

This provides a narrow positive boundary for **this snapshot executable only**.
It does not authorize or enforce collection, training, packed-data ingestion,
correction, policy evaluation, or any ordinary PuppyBot binary. Those commands,
direct-scene forms, opaque dataset paths and extra options are rejected by
the private executable before output. There is no process-execution API in
its main path, so it starts no children. An unrestricted same-user shell can
still run older binaries or build a different executable; a higher-level
workflow would have to independently review and pin both the executable and
its allowlist. The builder itself does not decide whether supplied scene or
model ancestry is complete or semantically disjoint.

Hashing and copying each source buffer do not make the *set* of files an
atomic snapshot. Same-user mutation of written snapshots, unnoticed equivalent
geometry, compromised compiler/runtime, and unknown ancestry are outside the
guarantee. The builder hashes the compiler, all project `.flex` source files,
generated source, executable and allowlist before/after the build and
recompiles the private source to the same binary. It does not prove a trusted
compiler or impose OS-level confinement. Future data or reservation materialization must not be enabled
until separately reviewed ingestion/execution boundaries, lineage checks and
failure tests exist. `synthetic_only` is a scope marker, not a magic proof
that a caller supplied synthetic content.

Run the CPU-only tests with:

```
python3 -B -I experiments/positive-bootstrap-v1/test.py
```

They compile private binaries in temporary directories and exercise actual
native command dispatch, the baked allowlist identity, approved snapshots,
changed/missing/unknown bytes, reserved roles and seeds, duplicate scene
content, fail-closed unsupported commands, build artifact aliases and
existing-output preservation. No GPU or real scene is used.
