# Simulator-only failure-stop experiment

This isolated source transform extends the opt-in `--contact-stop` prototype
with a separate `--contact-stop-failsafe` flag. It copies source; it does not
change the normal controller, the simulated robot protocol or hardware code.
The flag is rejected unless `--contact-stop` is also enabled.

After the virtual simulator is spawned, a fatal `vc_require` failure attempts
one nonblocking 64-byte command-3 stop on that simulator's stream, then waits
up to 300 ms for the simulator child to exit before the existing failure exit.
The request is sent before writing its diagnostic to standard error. A guard
prevents multiple attempts. The output explicitly says the stop is unverified:
the virtual protocol does not acknowledge command 3 and a child exit does not
prove it processed that request. The normal close path disarms the failure
hook before sending its ordinary stop; if that stop write fails, the hook does
not attempt a second request on the potentially ambiguous stream.

After the reset response passes validation, each simulator stream I/O call is
limited to at most five seconds. The enabled path checks the monotonic clock on
every loop iteration, including after partial progress or interruption; a
clock failure ends the operation and attempts the same unverified stop. This
is a per-call limit, not a whole-action
deadline: writes, response header, JSON and RGB are separate calls, so their
delays can add. Reset and non-simulator streams retain their existing timeout.
The five-second value and the 300 ms wait are exploratory, not physical safety
limits. No recovery motion is added.

An I/O failure can leave an in-flight request or response partially transferred.
The single nonblocking stop write can itself be incomplete, unavailable, or
queued behind other bytes. There is no resynchronization or acknowledgment;
the process logs the failed attempt and exits rather than claiming success.
The simulator child has the existing parent-death kill behavior, but neither
child termination nor an echoed command proves physical braking. Signals,
hard kills, deadlocks outside checked I/O, failure before the simulator stream
is registered, a wedged peer, and logging failures are not covered. No failure
JSON or contact-stop result is promised. This is not a hardware watchdog.

The CPU test compiles the full transformed control entry point and a probe
using the real `ve_step`, `ve_command`, `ve_receive` and `ve_check` functions.
A synthetic local socket peer checks stale driving data, a malformed header,
a missing response after the five-second timeout, and the disabled flag.
Additional compiled probes inject a clock error, repeated interrupted I/O and
repeated partial progress; a separate fork probe checks the bounded child wait
and one-shot latch. These
tests require local socket access; a network-restricted sandbox may require
permission to run them outside it:

```
python3 -B -I experiments/contact-stop-io-failsafe-v1/test.py
```

The probes do not run the full episode loop, rendered simulator, neural
policy, or robot hardware. They do not prove the stop was processed; a real
supervised simulator fault experiment and a separately validated physical
stop mechanism are required before making either claim.
