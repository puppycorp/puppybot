# Matched simulated contact-stop trial (staged)

This diagnostic revisits the two known training cases in diary 70. It applies
the opt-in contact stop to a copy of the archived hysteresis controller and
runs the resulting **same binary** with the stop disabled and enabled on each
case. The 300-action horizon, scenes, seeds, model and virtual task are fixed.
These cases were selected after observing failure and cannot estimate held-out
reliability or justify promotion.

The disabled arm must reproduce the previously recorded hysteresis episode;
the enabled arm must match its saved scene, initial state, decisions and actor
records until its stop. A stopped arm must contain a verified zero action and
zero drive echo, an explicit incomplete-horizon/failure report, and an
incomplete run summary. Stopped episodes count as failures at the original
300-action boundary; an echoed zero is not a physical stop acknowledgement.
Missing, malformed or mismatched evidence censors the diagnostic. This design
does not test stale-input stopping, contact hardware, physical braking or
recovery motion.

`build-supervisor.py` stages a fresh CPU build under the shared pitch82 lock,
low CPU/I/O priority, bounded worker and disk floors. It verifies the archived
controller source and build before applying the contact transform, then pins
and checks the compiled binary and modified sources. `trial.py` freezes a
separate plan and uses the existing GPU/disk monitor, per-arm supervisors and
final inventory in fresh paths. Their command-line entry points remain
disabled; execution requires independent review and a dedicated process.

CPU checks, including a disposable build and a stopped-game fixture derived
from the prior saved trace:

```
python3 -B -I experiments/contact-stop-trial-v1/test.py
```

`contact-stop-v1` separately tests its local socket protocol; it does not
establish actual full-episode or physical behavior. The one-frame observation
convention matters: in the saved failure, responses after actions 144, 145
and 146 have contact; the expected first zero command is action 147.
