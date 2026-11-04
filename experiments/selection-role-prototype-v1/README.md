# Isolated selection-role prototype

This is CPU-only preparation for a possible **development selection** family.
No actual selection scenes, held-out scenes, policies, simulators or GPUs are
run by this prototype. It does not claim that the proposed scenes are new or
geometrically independent of all model ancestry.

`transform.py` transforms a copy of the current diverse generator. It adds a
`selection` role for layout IDs 290–353 inclusive, with `fit:false` and
`selectionOnly:true` in the layout metadata. It rejects `--wide-heading`
and `--no-obstacle` for this role. The former role ranges are unchanged,
including held-out 226–289. It checks the expected source shape before
rewriting; it never edits the active generator or emits a scene.

`design.py` defines 32 games per level. Levels 1–3 use layouts 290–321;
levels 4–5 use odd layouts 291–353. Game `(level,index)` uses variant
`index % 16` and seed `1800000000 + 100*level + index`. Its optional history
comparison checks only explicitly supplied seeds and exact canonical room,
doorway and obstacle coordinates, ignoring the layout name and record order.
It does **not** identify near-equivalent geometry, alternate encodings or
unknown ancestry. No selection-role scenes should be generated until a
reviewed history inventory and explicit protected execution boundary exist.

`prepare.py` is a read-only gate for a separately supplied candidate scene
tree. It does not launch the generator or write a manifest. It checks that the
generator source is the exact private transform, records hashes of that source
and the supplied binary, pins every case, environment, layout and start pose,
and requires 32 distinct environment hashes, start poses and exact metadata
geometries per level. It requires nonempty prior case and environment hash
inventories, rejects exact overlap with them and the pinned held-out manifest,
and binds canonical digests and counts of the supplied prior hash inventories
in its result. It also checks the seed/metadata-geometry evidence supplied
by its caller, then re-reads the candidate files and source inputs. The binary
hash does not prove that it was compiled from the recorded source, and the
metadata geometry has not been proven to match the environment binary. The
supplied history can be incomplete; a registered launcher and an independent
geometry-to-environment check are required before relying on this gate.

`guard.py` is a separate fail-closed **prototype API**, not a change to the
active control, collector, trainer or any existing binary. It requires both a
SHA-256-pinned selection manifest and the pinned held-out reservation
manifest. For fitting and validation it rejects a selection/held-out marker,
reserved layout ID or matching reserved case or environment content, including
where a marker and layout ID have been changed. For selection it requires the
exact `(level,index,seed,layout)` mapping, `fit:false`, `selectionOnly:true`,
one obstacle and matching case, environment and layout hashes. It returns
file bytes captured from open descriptors: a future caller must consume those
bytes directly and bind the manifest digests in its own reviewed plan. It is
not a substitute for guarding all ingestion paths, preexisting datasets,
symlink-independent ancestry, atomic multi-file snapshots or semantic
similarity. A caller-controlled manifest digest is not proof of authenticity.
The existing native commands do not call this API and can bypass it entirely.

The prospective selection manifest uses `status:selection_not_evaluated`,
`task:virtual-fetch`, `gamesPerLevel:32`, and 160 rows with `level`, `index`,
`layoutId`, `seed`, `scene` (`generated/<layout>/<index % 16>`),
`caseSHA256`, `environmentSHA256`, `layoutSHA256` and `startPose`, plus
top-level `generatorSourceSHA256` and `generatorSHA256`. Both the preparation
gate and guard reject duplicate environment hashes or start poses within any
level. The held-out manifest
uses the existing `reserved_not_evaluated` 160-row mapping. This document does
not constitute an actual manifest, authorization to play, or a claim that
the chosen seed family is fully disjoint from unknown history.

Run `python3 -B -I experiments/selection-role-prototype-v1/test.py`. The 15
CPU tests compile the transformed generator into a private native probe,
exercise valid and invalid role boundaries, and write only synthetic metadata
in a temporary directory. They also use synthetic manifests and fake scene
bytes to check fit/validation rejection, stripped-marker/hash cases, held-out
rejection, catalog retargeting, seed mapping, duplicate environments and
poses, prior-case/environment hash reuse, changed input detection, source
pinning and exact-geometry overlap. No
actual scene was generated. The tests do not establish a complete runtime
ingestion guard or the correspondence of an old production binary to source.
