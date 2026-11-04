# Opt-in simulator search-only handoff prototype

This isolated source transformation and CPU build do not change the normal
client, simulator or existing experiment snapshots. The builder creates a new
output directory and does not run the simulator or use the GPU.

With `PUPPYBOT_PHYSICAL_SEARCH_FALLBACK=1` on both the copied client and its
child simulator, a client that reaches its navigation-action limit without a
target handoff may request command 8. The simulator requires physical-agent
mode, wheel localization, the discovery collector, and no training oracle.
It performs the existing simulated zero-command/two-tick stillness check and
requires a fresh still driving-camera frame. If the new frame has no target,
it starts the existing bounded search controller without supplying target
coordinates, body identity, free floor or map evidence; owner 1/ACK 8 means
search ownership only. If a target appears in that frame, owner 0/ACK 2 leaves
the ordinary RGB-gated command 6 responsible for any target handoff. The
client checks the two-tick advancement and stopped echo before polling.

The option is off by default and is mutually exclusive with the existing
guarded-rescan option. The default result and input receipt retain their
previous shape. When enabled, the input receipt records
`searchFallbackEnabled`; the result records `searchFallbackStarted`
separately from the existing detection `handoff` field. Neither means pickup
or delivery. A search-enabled client also writes `search-requests.jsonl`
before sends: this is client intent, not evidence that the peer received or
executed a request. ACK 2 has command-dependent meaning; a future auditor must
correlate each intent with its own valid reply and censor missing, partial or
ambiguous exchanges. The older hybrid auditor does not support search-only
ownership and must not be reused unchanged. An ACK 8 reports the simulator's
private no-target detection, but the collector-owned reply intentionally blanks
the camera and detection fields. The journal alone cannot independently prove
that no-target observation; that would require separately retained camera and
detector evidence.

The collector continues to use its existing fresh RGB, stereo observed-floor,
route, clearance and IK gates. CPU sensor mocks and source checks do not show
that it can navigate from the learned policy's final position, reacquire a
target or return it. Localization can drift against a wall, and the collector
still uses simulated grasp/held and containment state internally. An invalid
reply, EOF, timeout or failed request-journal write exits without a result;
the client does not independently verify a new stop or clean up all children on
that failure. A separately supervised watchdog is needed even for simulation.
No simulated ACK demonstrates physical braking, physical stop or hardware
safety. A separately reviewed matched simulator trial and search-aware auditor
are required before making any rendered-behavior claim.

Independent review reran 14 CPU test groups: two simulator dispatch/collector
start probes with mocked hardware, four archive corruption/copy-race checks and
eight copied-client/socket groups. The client timeout test uses a test-only
250 ms deadline to exercise the ordinary timeout path; it does not show a
physical stop or child cleanup. No rendered simulator or GPU run was performed.
