# Paired trainer batch and mirror journal prototype (4 Nov 2026)

The existing trainer records only its first batch's mirror mask. Matching a
seed alone therefore would not independently prove that two full-epoch arms
used the same realized augmentation for every batch. A separate private
trainer transform now journals the episode IDs, batch start/count and actual
host mirror mask at every training batch send. It includes prefetched batches
and the final one-history batch; it leaves startup and validation paths
inactive so they do not create records or advance the mirror RNG.

Five native CPU tests pass, covering all 468 sends for 935 histories, the
seeded 935 mirror draws, prefetch, the partial final batch, inactive startup
and validation, missing footer and tampering. An independent reviewer reran
them and checked the send boundary. The comparator checks both arms' full
recorded orders and masks; it has not yet compared real training runs. This
is host-side metadata, not proof of actual GPU consumption, gradients or
policy performance. Artifact: `experiments/parent-route-mirror-journal-v1/`.

A later separately named CPU build was published and independently
recompiled. Its trainer SHA-256 is
`5e716e9caa80b97b69efdf5750afbb4c8540da757be22241803aabe699d78c1f`;
its build receipt SHA-256 is
`dc705355cad7d71675e6cd98cc7663bd8d3f1b77910723d77612079b16095d57`.
Review added and tested rejection of symlinked or hardlinked build artifacts,
and remeasurement of the reflink fixture's shared extents. No GPU training
has used this build.
