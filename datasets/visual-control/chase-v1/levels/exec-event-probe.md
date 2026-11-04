# Exec-event feasibility probe

`probe-exec-events.py` is an isolated Linux CPU experiment. It traces only a
new child and fork/vfork/clone descendants with `PTRACE_EVENT_EXEC`, reads
their `/proc/PID/cmdline` while stopped, and emits each argv element as base64
to preserve empty and non-UTF8 arguments. It applies a five-second deadline,
limits tracked processes and exec events to 128, and kills tracked children on
failure. It rejects clone/thread events; it is intended for isolated standalone
use from the main thread. Usage:

```
python3 -I datasets/visual-control/chase-v1/levels/probe-exec-events.py /bin/true
python3 -I flex/tests/exec-event-probe.py
```

On this host, the default sandbox denies the child's ptrace setup and the
probe returns failure rather than claiming successful observation. A separate
host-visible run succeeded; seven CPU fixtures passed, including twelve rapid
fork/exec events with empty and non-UTF8 arguments, simulated ptrace denial,
timeout, repeated signals during cleanup, real SIGTRAP delivery, unrelated
child preservation, and rejection of threaded execution. This is not evidence
that a different sandbox or process can be traced. Tests need ptrace permission.

Review found an unresolved cleanup race: a child can be attached by the
kernel before its parent's fork event has been consumed. If interruption
occurs then, the child is not yet on the tracked-PID cleanup list. Do not
use this probe until isolated-worker cleanup has been implemented and reviewed.
Its public trace function and command now fail closed, and the seven positive
fixtures are disabled until that fix. The observations above remain feasibility
evidence from the earlier version.

This is diagnostic only: procfs command-line bytes are an observation at the
exec stop, not proof of executable bytes, loaded libraries, GPU execution,
camera data, actor inputs, or trustworthy child behavior. It does not record
environment or file identities, protect output from modification, attach to
pre-existing processes, or establish complete coverage of every Linux exec,
thread, namespace or signal scenario. It has no independent watchdog against
the tracer itself hanging or being terminated. Do not use it as an experiment
supervisor, qualification, or held-out attestation. No experiment runner or
held-out gate imports it.
