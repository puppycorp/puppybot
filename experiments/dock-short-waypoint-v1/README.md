# Guarded short waypoint after exhausted box-viewpoint search

This opt-in transform applies to a fresh copy of the `dock-floor-refresh`
simulator. When a single stationary floor retry has completed, no fresh stable
box is visible, and all 36 normal viewpoint plans fail, it tries one bounded
short approach toward the previously RGB-observed box. The remembered box is a
direction hint only; it never authorizes release. A successful route returns to
the existing travel and wrist-survey state machine. Normal fresh-box stability,
observed-floor, swept route, contact-memory, arm-motion and release gates remain
in place. The unchanged physical simulator's guards have not established
held-payload or self-collision safety, and no physical robot is addressed.

The new option `PUPPYBOT_SIM_DOCK_SHORT_WAYPOINT=1` is disabled by default;
invalid values fail startup. It requires the existing bounded floor retry to
have completed in physical-agent simulator collection with a held object, a
remembered visual box and a local map. It makes at most nine route-plan calls
for 20, 30 and 40 cm goals at three bearings. Each goal keeps the current base
heading and is checked by the original planner with its original stored failed
command constraints; any accepted route must have one to eight swept primitives,
an endpoint within 50 cm, at least 10 cm of displacement and at least 10 cm of
progress toward the remembered box. Planning has an eight-second cooperative
wall deadline and an outer supervisor is still required. Only one waypoint may
be accepted per search; failure, timeout or rejected arm travel returns to the
existing stop and failure path. Any post-approach detection must be fresh and
stable before release staging. Survey diagnostics get a distinct sweep number.

Run `python3 -B -I experiments/dock-short-waypoint-v1/test.py`. The tests build
the whole copied simulator, reject invalid flags, exercise state-machine
prerequisites and failure/deadline branches with mocked dependencies, and run
the actual native planner on a saved local map. The separate diagnostic script
`experiments/dock-waypoint-diagnostic-v1/audit.py` reconstructs the two failed
command constraints from neighboring saved trace records; exact insertion timing
is not independently attested. Its planned four-primitive path is a planner
result, not a command, a safety proof or a delivery. A reviewed matched rendered
trial is required before promotion.

The experimental `build.py`, `run.py`, `audit.py` and `monitor.py` stage a
same-binary comparison: both controls enable the earlier floor retry but leave
the waypoint disabled, and the candidate enables it. The inherited external
monitor and output inventory are retained, while the audit explicitly censors
mechanism/safety claims. `python3 -B -I experiments/dock-short-waypoint-v1/trial-test.py`
checks the copied build, flag mismatch, actual frozen manifest, synthetic
three-arm audit routing and malformed waypoint telemetry. No supervised build
or rendered run had been launched when those tests were written. After
independent source and monitor review, a bounded low-priority CPU build completed
with `isolated_build_only` at
`build/flex/sim/levels-v2/pitch82/dock-short-waypoint-build-cpu-monitor-v1/`.
No rendered run has been launched; scheduling requires the existing monitored
GPU and disk preflight.
