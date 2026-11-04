# Visual-stall search transfer in the hybrid simulator client

This isolated source transform combines two existing simulator-only research
prototypes: the exact actor-image stall suspicion from
`visual-exact-stall-v1` and the **physical-hybrid simulator client's**
search-only ownership transfer from `physical-search-fallback-v1`. It does
not change the separate virtual-fetch policy client, normal controller,
archived sources or physical robot code. It is not an onboard single-policy
implementation.

When both `PUPPYBOT_VISUAL_SEARCH_RECOVERY=1` and
`PUPPYBOT_PHYSICAL_SEARCH_FALLBACK=1` are explicitly set, the copied hybrid
client checks its already validated, still-driving-camera resized image and
wheel-command echo before each policy action. Five identical image buffers
across four consecutive 10-tick intervals with nonzero echoed wheel commands
cause a single command-8 search-only request before the next policy action.
A fresh target appearing during the transfer follows the existing command-6
target handoff. An invalid detector state or a transfer that neither starts
search nor accepts a target ends in the normal command-3 stop path. Disabled
mode does not emit visual-recovery result fields and retains the existing
navigation-action budget. The run result records the trigger reason, action
number and one of `not_triggered`, `search_started_unverified`,
`target_handoff_unverified`, `transfer_did_not_start`, or
`invalid_observation`. These describe only the transfer attempt. ACK 8 means
search ownership only, not a target, pickup or delivery; a later terminal
collector ACK does not change the outcome to success.

When the detector triggers, the copied client exclusively creates
`visual-trigger.rgb` with the resized image that caused it. That frame is not
otherwise recorded because it is checked before the next actor invocation.
The saved auditor uses these bytes, the preceding saved actor images, frame
and tick metadata, echoed wheel commands and the search journal to reconstruct
the first trigger and validate the early handoff. This does not prove raw-camera
freshness. A create or write failure aborts before the transfer and can occur
before a stop request; the partial file is not a valid audited result. The
artifact is created exclusively and is not overwritten.

The existing simulator search transfer requests zero and validates two
simulated stopped ticks and a fresh camera frame. The collector then uses
its own camera/stereo floor mapping and planner, where unknown floor is not
free; the new client does not supply an invented clearance, target location
or ground-truth pose. The collector is still a simulator prototype and uses
simulated grasp and containment state internally. Its earlier search-only
trial did not complete pickup or delivery. A terminal collector response is
not by itself proof of success. The copied client ultimately issues the
existing simulated stop and retains the original unverified outcome.

The five-frame threshold was selected after examining a known failure. A
frozen camera or repeated scene can cause a false trigger while moving; real
camera noise can prevent exact equality even when stalled. Timestamps prove
only that the simulator returned sequential metadata, not that the sensor is
working. Failure or blockage inside receive, validation, request journal or
handoff may exit before a stop or result can be confirmed. A zero echo or
simulator handoff is not physical braking; no hardware watchdog, verified
task progress or real robot recovery is implemented. This is a research
hybrid, not a replacement for the eventual single-policy deployment goal.

CPU tests compile the complete copied client and use its real socket protocol
with a synthetic simulator and policy. They check an early search transfer,
target-at-transfer routing, explicit failure when the target disappears,
a changing-image negative case, byte-for-byte disabled-path journal and actor
parity, a stale search reply, and required opt-in; the inherited search
protocol tests also run. Saved-protocol tests cover the three early-transfer
outcomes and reject missing or altered images, drive echoes and journals:

```
python3 -B -I experiments/visual-search-recovery-v1/test.py
```

Local socket access may require running this test outside a network-restricted
sandbox. The tests do not execute a real rendered simulator, real neural
policy or physical robot. No candidate was permanently built, no GPU trial
was run and no model was promoted. `audit.py` adapts the prior fallback
protocol audit for explicit early triggers and rechecks the first repeated
image sequence; detector-invalid outcomes are censored because their history
cannot be reconstructed. It audits individual runs, not matched comparison,
source identity or manipulation outcomes. A future trial needs independently
reviewed fresh inputs and paths, bounded process cleanup, resource monitoring,
matched control and explicitly scored failed/unfinished games.
