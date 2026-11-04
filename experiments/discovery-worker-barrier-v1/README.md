# Experimental simulator worker barrier

This isolated, default-off transformation is an investigation aid, not a
promoted simulator or hardware control change. It leaves the archived sources
untouched. It is restricted to non-realtime virtual physical-agent mode and is
rejected with an external serial interface. A caller must explicitly transform
and compile an isolated copy, then set `PUPPYBOT_SIM_WORKER_BARRIER=1`.

The asynchronous stereo worker is polled from inside a simulated tick. Once a
stereo job starts, the barrier keeps that tick fixed until the process and both
output streams finish. It requires zero commanded drive and a settled simulated
arm; failure invokes the existing discovery stop/failure path. The actual worker
output still goes through the existing validation. No output is synthesized.
Trace field `workerBarrier` records completed waits, the last submitted frame,
`lastWorkerCompleteTick`, its elapsed host wall time from spawn, and barrier
failures. Worker completion precedes result validation and does not imply that
a map was accepted.

The 15-second wall deadline is **cooperative, not a hard deadline**. The host
worker pump can spend unbounded time handling interrupted or continuously
flowing output, and process cleanup can block; host allocation/output assertions
can terminate the simulator before the normal discovery failure path runs.
Each pump call also consumes host arena memory. An external supervisor with a
hard process-group deadline, explicit episode censoring, and resource controls
is required before experimental use. A crash, timeout, lost response, or missing
trace must be recorded as censored/failed, never replaced with a successful
episode. The transform alone does not provide that supervisor.

Worker latency is excluded from simulated time while the barrier waits. That
changes simulator-time scoring relative to existing unbarriered experiments;
compare only fresh runs with the same simulator, flag, sources, and protocol,
and report wall-clock latency separately. This mechanism gives no guarantee
about physical stopping, real-time operation, other nondeterministic inputs, or
end-to-end determinism. It has not yet been tested on a complete episode, GPU,
or physical robot.

A separate CPU-only diagnostic uses an older, complete first stereo scan from
`reverse-frontier-v20/west-tight`, not the dock-control scene. Two fresh worker
output directories received the same pinned request, RGB inputs, worker source
and transformed driver; the second worker had a deliberate one-second host
delay. The native harness initialized simulated tick 370, and the actual
simulator result validator accepted map frame 369 at that tick in both cases,
with identical map and mask hashes. Recorded worker elapsed
times were 996 and 1,991 ms. OpenCL was explicitly disabled, CPU threading was
limited, and the existing external subreaper supervisor reported clean exits.
This directly exercises one real worker result and does not run a simulated
search or full episode. Evidence and an input manifest are in
`build/flex/sim/barrier-real-worker-cpu-v1/`; runtime libraries were not fully
pinned or attested.

Run the CPU-only checks with:

```
python3 -B -I experiments/discovery-worker-barrier-v1/test.py
```

The checks compile the transformed full archived simulator in a temporary
directory, exercise option rejection, test mocked failure paths and different
worker latencies, and run two actual child processes at different durations
through the archived host worker pump. A malformed real-child result is also
fed through the transformed simulator's discovery update and must fail without
applying a map. These checks do not execute the robot policy.
