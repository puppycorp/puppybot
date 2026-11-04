# Simulator-only stop-on-failure prototype

This isolated experiment copies an archived client source and adapts the copy to
use a supervisor-owned socket. The supervisor owns the client and simulator as
separate processes. The command-line entry point is disabled; nothing here is
integrated into the normal robot client. The copied source and build artifacts
are created under a new output directory and existing artifacts are preserved.

The proxy forwards complete simulator protocol transactions. After a validated
reset or response, if the client disappears, sends a malformed request, times
out or is interrupted while the peer is idle, the proxy can request a simulated
stop at the next sequence number. It reports `stopAcknowledged` only after the
complete peer response has passed the sequence, owner, stop-acknowledgment,
zero-drive echo, tick and frame checks. An ack 6 is a peer-reported failure
and zero-drive echo; it is not a stop acknowledgment. If any request bytes
may have reached the peer but the corresponding response is incomplete,
invalid or late, the sequence is ambiguous: the proxy closes and reports the
stop as unverified without guessing another command. A partial client request
which has not been forwarded leaves the previously completed boundary intact.

The outer watchdog uses a process group and subreaper to bound execution and
clean escaped descendants. Because that supervisor can reap any child of its
caller, the launcher requires a dedicated single-threaded process with no
existing children before creating output. If forced cleanup is needed, the
outer launch fails closed and retains its evidence. Signals are recorded using
non-raising handlers during worker cleanup. A missing session or outer report
is not success. The environment is restricted to the diagnostic whitelist;
the launch record is intended invocation evidence, not OS attestation.

CPU-only local-socket fixtures cover normal copied-client/direct-client byte
parity for one stub case, failure after reset, partial or malformed streams,
wrong, missing, duplicate-key and nonfinite stop responses, in-flight timeouts,
repeated signals, an escaped signal-ignoring child, and the dedicated-process
guard. These tests use a fake simulator and policy. They do not establish
behavior of a rendered simulator, real camera, robot, learned policy or motor.
No simulated acknowledgment, process exit or peer-reported drive value proves a
physical stop or delivery. Power loss, forced termination of the supervisor,
socket failure and malicious or fabricated peers remain outside the guarantee;
a real robot would require an independent physical stop mechanism and watchdog.

Independent review reran all eight proxy and seven supervisor CPU test groups
successfully. The tests were run with local Unix socket access enabled; no GPU
or rendered simulator was used. The review applies only to this stub-based
diagnostic and its stated boundaries.
