# Saved simulator terminal-failure report audit

This read-only diagnostic checks the final collector failure and stop in one
saved simulator-protocol run. It requires `physical-agent.jsonl`,
`search-requests.jsonl`, `trace.jsonl`, and `result.json` inside the run
directory. The first two must have consecutive, aligned sequence numbers.
The final collector response must be ACK 5, owner 2, zero drive and a bounded
nonempty `collectorFailure`; its matching command intent must be a collector
poll. The immediately following final response must be ACK 7, owner 2 and
zero drive, with a matching stop intent and the same tick and time. The saved
result must acknowledge that stop and preserve the same failure while keeping
its outcome unverified. The terminal-step trace must be the trace endpoint,
state that the simulator case failed, and have the same reason and time.
All four evidence files are hashed before and after the check, and the result
lists their digests. Duplicate JSON fields, non-finite JSON constants and
contradictory or missing final evidence are rejected.

```
python3 -B -I experiments/physical-terminal-real-audit-v1/audit.py RUN_DIRECTORY
python3 -B -I experiments/physical-terminal-real-audit-v1/test.py
```

The intent journal requirement deliberately limits this diagnostic to runs
that record command intents, such as the search-fallback client. It does not
check every preceding request or response, the binary or model identities,
resources, process execution, or the origin of the local files. Use it in
addition to a separately reviewed trial audit, resource monitor, pinned input
manifest and process supervisor. Even a pass only states that these saved
local records agree about a simulated failure and stop acknowledgment; it does
not establish motor braking, a hardware stop or a delivery. The seven CPU test
groups use synthetic saved files and cover altered, missing and contradictory
terminal reports, stop acknowledgments, intents, results, trace fields and
in-flight evidence changes. No rendered simulator or robot is run.

Older trial outputs without `collectorFailure` should fail this new audit;
they are retained unchanged and are not retroactively upgraded.
