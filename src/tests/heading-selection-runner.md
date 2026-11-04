# Fixed-epoch heading selection runner

`run-heading-selection-v1.py` is staged with its CLI hard-disabled. It requires
independent review and an independent overall deadline, subreaper, and GPU
resource monitor before any execution. The existing monitor used by the
heading collection cannot simply be assumed to cover this new workload.

The registered plan fixes standard and levels 1–5, 32 training-layout games
per arm, the scene and seed for each game, and the epoch-8 model packages. The
runner takes the shared pitch82 lock, verifies the plan and saved training
evidence, records its intended argv and sanitized environment, and runs both
arms in order. Each arm has a 3,600-second supervisor; each of the two arm
audits and the paired audit has a 600-second supervisor. Twelve arms and 18
audits therefore permit 15 hours before input verification and cleanup. Free
space is checked by the inner runner at 12 GiB before launch and 8 GiB before
each arm and final publication. The separately staged monitor adds a 33 GiB
preflight and sampled runtime guard, with a 32 GiB floor before its completion
receipt. Sampling and the 1 GiB headroom do not guarantee protection from
rapid concurrent writes.

A failure stops subsequent work. Any created output is retained, with a
partial censor report when it can be written. A missing final summary means
the run is incomplete, including if filesystem failure prevents the partial
report itself. The completed inventory records file hashes and symlink targets
before the summary is written. No existing output is overwritten.

The audits compare recorded scenes, starts, placements, traces and scores.
Recorded commands and hashes are evidence of intended invocation, not an
independent attestation of the operating-system execution, actor inputs or
training ancestry. The plan does not preregister a winner or promotion rule;
these training-layout games are neither held-out qualification nor evidence
of physical robot performance.
