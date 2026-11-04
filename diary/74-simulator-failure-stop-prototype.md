# Simulator failure-stop prototype and deadline review (3 Nov 2026)

The contact stop tested in [entry 73](73-simulated-contact-stop-trial.md)
receives only valid simulator observations. A stale, malformed or missing
driving response can instead terminate or stall the client before the contact
guard requests zero. This entry records an isolated CPU prototype for that
gap, not a rendered simulator or physical-robot result.

With the separate `--contact-stop-failsafe` flag, a fatal controller validation
or stream failure after simulator registration attempts one nonblocking
virtual command-3 stop before reporting the error. If all 64 bytes are accepted
by the local socket, it waits up to 300 ms for the simulator child; the
standard-error message calls both request and outcome unverified. The virtual
protocol does not acknowledge command 3, and a child exit does not prove the
command was processed. The existing simulator child also has parent-death
termination, which is not physical braking evidence. The normal close path
disarms the extra hook before its ordinary command-3 write; a failed normal
close write is not retried.

After a validated reset, each simulator-stream I/O call has an exploratory
five-second monotonic deadline. An independent review found the first draft
checked its deadline only after `EAGAIN`, permitting repeated interrupted or
partial I/O to pass the limit. The revised enabled path checks time on every
iteration and treats clock failure as a fatal error. This is a cooperative
per-call bound, not a whole-action or hard real-time guarantee: separate write,
header, JSON and image calls can add their times, and scheduling or a stuck
operation outside the checked loop can delay failure handling.

Four CPU test groups passed with local socket access outside the restricted
sandbox. They compile the full copied control entry point and exercise real
environment protocol functions against a synthetic socket peer. The peer
recorded a command-3 request following stale data, a bad response header and a
missing response; the missing-response test observed the five-second timeout.
The disabled control did not send the extra request. Additional compiled
probes injected clock failure, repeated `EINTR` and repeated partial progress,
and tested the bounded child wait and one-attempt latch. No test established
that a real simulator consumed the emergency request.

An in-flight request or response may be partial; the single nonblocking stop
write may itself be partial, unavailable or queued behind other bytes. The
hook does not resynchronize, cannot guarantee a durable failure report, does
not handle hard kills or all hangs, and makes no hardware-stop claim. The
prototype does not perform recovery motion. A supervised fault test with a
real simulator peer, and separately validated hardware feedback and stopping,
remain necessary.

Artifact: `experiments/contact-stop-io-failsafe-v1/`.
