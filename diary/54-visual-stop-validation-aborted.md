# Simulated visual-stop validation stopped early

The frozen v3 visual-stop suite was intended to run twelve paired selection
cases: nine appearance/heading variants of one training apartment and three
existing training rooms. Each pair used the same client, simulator, model and
scene, with the visual-stop flag disabled in one arm and enabled in the other.
The suite did not complete and must not be reported as a completed validation.
The original inputs, partial outputs and audit remain in
`build/flex/sim/levels-v2/pitch82/visual-stop-validation-inputs-v3` and
`build/flex/sim/levels-v2/pitch82/physical-visual-validation-v3`.

The disabled arm of `room-13` exited with status 1 after 0.372 seconds. The
supervisor reported no timeout, signal or remaining-worker cleanup, and no
policy observation was recorded. Its client log reports a closed local process
stream; `run/native.log` says that `--agent-physical` requires an RGB discovery
case. The frozen room case specifies `rgb-find-return`: the archived simulator
maps this to `ps_seek_enabled`, which its physical-agent startup guard rejects.
The other two room cases use the same controller. This is a case compatibility
error in the suite setup, not evidence of a policy or GPU failure.

The suite stopped immediately and wrote `audit.partial.json`; its audit error
log is empty. The existing audit rechecked the pinned inputs and classifies
all twelve planned cases, including cases that did not run:

| Partial-audit result | Cases |
| --- | ---: |
| Completed, prefix-matched pairs with eligible windows | 4 |
| Censored after collector handoff | 5 |
| Censored after the room-13 disabled-arm failure | 1 |
| Censored because room-15 and room-17 did not start | 2 |

In the four completed pairs, the enabled guard stopped for visual suspicion
and the simulator-truth stop window was stationary in each case. The audit
found zero moving-truth suspicion stops in these four cases; this small result
does not establish a false-stop rate. Retrospective disabled-arm windows in two
cases were stationary without suspicion. Those windows are not necessarily
observed misses in the enabled arm, which may already have stopped. There were
no eligible low-texture windows and no cases meeting the report's periodic
visual indicator, so these results do not validate either stress condition.

Stationary means every pose in a window remains within 1 cm and 2 degrees of
its starting pose; moving means at least one reaches 5 cm or 10 degrees, with
intermediate motion classified as ambiguous. Windows overlap and are not
independent trials. Retrospective stable-pose timing is measured in simulated
ticks, not from collision onset or in wall-clock time. A stationary pose does
not establish an obstruction, and simulated zero-command acknowledgment does
not establish a physical motor stop. These are training-selection scenes,
not held-out or hardware evidence.

Changing a copied room case to `rgb-discovery` is a candidate correction for
the demonstrated startup incompatibility, but it changes controller semantics
and does not prove the spawn, detection or visual coverage will be useful. Any
follow-up requires a separately frozen and reviewed matrix and startup checks;
the v3 inputs and partial results are retained without restarting the suite.
