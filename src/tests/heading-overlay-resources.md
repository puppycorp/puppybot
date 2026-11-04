# Full heading overlay resource evidence

The full overlay orchestrator captures the source aggregate's physical maps
before and after each arm, and checks them again before pair-ready publication.
It records each arm's free bytes before and after creation, plus source and
destination Btrfs total, exclusive and set-shared bytes. Per-arm resource JSON
and the overlay directories are retained on failure; existing paths are never
overwritten. Publication requires unchanged source maps, at least 32 GiB free
after each arm, valid extent data, and some reported shared target data.

The two resource files are included by value and SHA-256 in pair-ready. The
standalone pair verifier, full-training path and selection package verifier
recheck their contents and the current source maps. Exclusive/shared values
are observations at creation, not immutable properties: later reflinks can
legitimately change sharing. Nonzero shared bytes establish only some sharing;
they do not establish that most data is shared, reserve disk space, or predict
full-scale savings. The existing 34 GiB per-arm check and 32 GiB floor with
512 MiB per-game headroom remain point-in-time guards against disk use.

Scratch tests exercise a real small Btrfs reflink, unchanged source maps,
recorded extents, missing sharing, disk-floor failure, source-map changes and
missing/tampered evidence. They do not establish production-scale allocation.
