# Saved simulator terminal-failure audit (4 Nov 2026)

The newly added simulated collector-failure report from entry 103 needs an
independent check against the actual peer response and trace. An isolated
read-only audit now checks a recorded failed terminal ACK 5 and its bounded
failure reason, verifies that the same tick is the end of the simulator trace
with `case.phase` failed and the same reason, then requires the next and final
response to be ACK 7 at the same tick with zero wheel commands. It also checks
matching collector-poll and stop request-intent records and requires the final
client result to preserve the reason, acknowledge the simulated stop and keep
its outcome `unverified`.

The audit hashes the protocol journal, request-intent journal, simulator trace
and result before and after reading; duplicate JSON fields, missing evidence,
contradictory states and changed files are rejected. Seven CPU test groups
cover synthetic consistent data and mutated terminal fields, stop responses,
request intents, result data, trace states, duplicate keys and mid-audit input
changes. The previous saved matched-footprint run is rejected because it
predates `collectorFailure`; its contents and completion receipt remain
unchanged.

This audit checks the final failure and stop, not every preceding command or
response. It deliberately requires an intent journal, so it is suitable for the
instrumented search-fallback client rather than every client variant. It must
supplement a separately reviewed trial audit, source and binary registration,
resource monitor and process supervisor. File consistency and simulated drive
state do not attest execution, a physical stop, motor braking or a successful
delivery. No real simulator, GPU or robot was run for this audit.

Artifact: `experiments/physical-terminal-real-audit-v1/`. A future real-peer
trial must use a fresh copy of the simulator and client with the entry-103
changes and must not replace the earlier saved trial.
