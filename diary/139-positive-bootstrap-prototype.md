# Positive-allowlist snapshot bootstrap (4 Nov 2026)

An isolated native executable now tests the first step of a reservation
bootstrap: it embeds a synthetic positive-allowlist digest and can only
snapshot approved scene triplets. It validates the pinned bytes, role and
seed, copies them to new private output and reads them back. Collection,
training, correction, evaluation, packed-data commands and unknown or
reserved inputs fail before output. The build records the compiler, imported
source tree, policy and builder hashes and recompiles the private executable.

Eight synthetic CPU tests and an independent review passed, including source
changes, unsupported commands, output and artifact aliases, existing-output
preservation and reproducible build. This executable is snapshot-only: it
does not launch or protect a collector, replace active binaries, protect
opaque existing datasets, establish complete ancestry or enforce an OS-level
boundary against unrestricted same-user execution. No real reserved scene or
GPU work was used. It is a prototype at `experiments/positive-bootstrap-v1/`,
not a completed held-out reservation or ingestion guard.
