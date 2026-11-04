# Simulator-only sustained-contact stop prototype

This isolated source transform adds an opt-in `--contact-stop` to a copied
simulator fetch-policy controller. It uses the existing simulated contact
feedback and validated commanded-drive echoes, not wheel odometry, truth pose,
scene identity or a target location. After three consecutive observations
with contact and a nonzero wheel command, it latches a stop reason before the
next policy action. A cleared contact or zero-drive observation resets the
count. The three-observation threshold is exploratory and was chosen after
inspecting known failures; it is not a generalization or promotion result.

The integration sends a zero action first, then checks its simulated drive
echo and writes `contact-stop.json`. It stops that episode, flags it as a
failed game and incomplete horizon, and marks the run summary incomplete if
any episode was stopped. Existing elapsed-time `deliveriesPerMinute` is not a
fixed-horizon score; comparisons must include every stopped episode as a
failure and use the original game and time limits. The zero action itself is
recorded as an action and advances ten simulated ticks. The final observation
at the game horizon is checked once too; if that sample triggers, the additional
zero action occurs after the scored horizon (action 301 for a 300-action game)
and must not be treated as policy time. The report records both the trigger
action count and the extra zero action.
A zero echo establishes
only an echoed command. `ve_close` sends simulator command 3 without reading a
stop acknowledgement; neither operation proves physical braking or a hardware
stop. The prototype performs no recovery motion.

The isolated detector can latch an invalid/stale-observation reason, but the
integrated hook receives only observations that made it through the existing
`ve_receive` and `ve_check` functions. Those functions can fail or block on a
malformed, stale, or missing response *before* the hook runs. A stop or report
is not guaranteed in those paths. A failed zero request, invalid echo, process
termination or report-write failure can also leave no `contact-stop.json`.
An external watchdog and a separately validated stop mechanism are necessary
for any physical work. The experimental physical client currently forces
contact feedback to zero; this simulator-only prototype cannot detect contact
on the real robot.

The existing `progress-guard.flex` monitors idle time between verified task
events and asks an external executor for bounded recovery. This prototype
addresses a different immediate contact condition and does not treat the
simulator's virtual consumption/delivery events as verified physical progress.
Combining them requires a real event source, a cancellable recovery executor,
and stop/report handling across sensor and transport failures.

Run CPU checks with:

```
python3 -B -I experiments/contact-stop-v1/test.py
python3 -B -I experiments/contact-stop-v1/protocol-test.py
```

The test copies the current Flexscript source to a temporary directory, applies
the transform, and compiles the complete copied control entry point. It exercises
the actual detector and stop hook with a mocked `ve_step`, including a final
horizon sample, a rejected echo and a report-write failure after the zero
request. The second test drives the real `ve_step`, `ve_command`, `ve_receive`
and `ve_check` functions over a local socket pair with a synthetic peer. Its
enabled and disabled cases match for the first three drive requests and saved
decisions; only the enabled case then sends zero. Wrong zero echo, stale stop
response and wrong sequence fail without a success report. A stale response
during driving demonstrates the earlier limitation: the client exits before
the guard sends a zero command or writes its report. Local socket operations
may require permission outside a network-restricted sandbox.

These tests do **not** run the real simulator peer, the actual episode loop,
or the neural policy, and do not establish full disabled-path parity, transport
timeout handling or hardware behavior. No GPU trial or policy promotion has
been performed.

As a post-hoc trace check only, counting the pinned earlier two-case debug run
would first trigger at action 147 for seed 6800107's kick-plus-hysteresis arm;
the other five recorded arms have no three-sample trigger. This does not prove
what the changed controller would do after stopping, nor establish false-stop
rates in fresh scenes. Before drawing behavioral conclusions, independently
review the copied build and protocol, run matched enabled/disabled simulator
cases with fixed scoring, then evaluate on separate selection data.
