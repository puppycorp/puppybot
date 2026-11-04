# Simulator collector failure reporting (3 Nov 2026)

The physical-agent simulator used terminal acknowledgment 5 both when a
collector case passed and when it failed. In the matched trial from entry 102,
the client therefore reported only `collectorTerminal:true` and `outcome:
unverified`; the reason was visible in the simulator trace, but not in the
client result.

The current simulator now includes its case failure reason as an optional
`collectorFailure` field in a failed terminal acknowledgment. The client
copies valid bounded failure text before reading the next response and reports
it only after the existing stop command receives its validated simulator
acknowledgment. Older peers that omit the field retain the old result shape;
older clients ignore the additional JSON field. Invalid, empty, oversized or
embedded-NUL failure detail is marked invalid and still follows the stop path.
The overall outcome stays `unverified`: the collector's own failure report is
not independent proof of delivery or physical braking, and exit code zero is
not a successful-fetch signal.

The worktree client and simulator both compiled into temporary binaries. Fifteen
CPU/native and local Unix-socket tests passed, including the actual worktree
client against a synthetic peer, the copied simulator's actual field-writing
helper, legacy-peer compatibility, malformed detail, worst-case escaped text,
and a missing stop response. The latter writes no normal result. Independent
review reran the preceding 14-test prototype suite. No rendered simulator or
physical robot was exercised by this protocol change; peer disconnects, journal
failures and other errors may still prevent a confirmed stop or report.

Artifact: `experiments/physical-terminal-failure-v1/`. Existing trial binaries
and saved results were not replaced.
