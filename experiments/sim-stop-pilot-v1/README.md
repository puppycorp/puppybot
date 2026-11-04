# Disabled rendered-simulator fault pilot

This is an isolated derivative of the reviewed `sim-stop-supervisor` stub
prototype. It has not been run against the rendered simulator. The launcher and
supervisor command-line entry points remain disabled. The paired plan uses one
copied client and simulator, model and scene: a no-fault control, followed by a
fault arm that kills the client process immediately after the proxy has received
and validated the reset response, before sending that response to the client.
The proxy then attempts stop sequence 2. The fault does not depend on simulator
truth or actor input.

Each arm saves length-framed binary records of requests before and after complete
socket writes and full replies after validation. The independent auditor parses
the saved bytes, checks sequencing, stop acknowledgment and zero-drive echo, and
compares the complete initial reset transactions between arms. A mismatch is
censored; a missing, incomplete or invalid transaction fails the audit. The
journal and process reports are local, same-owner evidence and cannot prove the
kernel executed a particular binary or exclude deliberate fabrication.
The records contain complete requests, completed-write markers and validated
full replies; a failed partial write does not preserve each wire fragment.

The launcher pins the copied client and source archive, compiler, simulator,
model and kernels, case, environment, asset, configuration, selected runtime and
the identified scripts before and after the pair. These hashes do not attest
all dynamically loaded libraries, drivers or device execution. Source is
reconstructed from the archive and fixed transformation, but that consistency
check does not prove the supplied binary was compiled from it. An exclusive
existing experiment lock, no-overwrite output, a 30-second GPU baseline,
36 GiB disk preflight, a 34 GiB active and final floor, ongoing GPU and disk
checks across the output, workspace and home filesystems, pidfd signaling and nested process-group/subreaper
deadlines bound the proposed run. A clean outer result and complete audit are
required; interrupted, timed-out or forcibly cleaned runs retain partial
evidence and fail closed. The absolute session limit is 60 seconds per arm;
actual rendered simulator startup and completion within that limit remain
unproven. The launcher resolves input paths before the worker changes directory.
Both command-line entry points exit without running a pilot.

CPU tests use fake simulator and policy programs and simulated telemetry. They
cover control/fault byte replay, altered or truncated stop acknowledgment,
initial-frame mismatch, signal and escaped-child cleanup, changed pinned input,
low or missing telemetry, pidfd failure, and no-overwrite. They do not establish
rendered-simulator behavior, real camera or robot operation, motor braking,
delivery, or physical safety. A simulated stop acknowledgment is not a physical
stop; a real robot requires an independent physical stop mechanism and watchdog.

Independent review reran all eight proxy, nine supervisor/audit and nine
launcher CPU test groups successfully, including the relative-path fix.
Its disposition is limited to the staged
stub diagnostic. The predeclared reset fault occurs at zero commanded drive and
does not test braking from motion.
