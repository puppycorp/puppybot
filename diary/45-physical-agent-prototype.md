# 45. Opt-in hybrid physical simulator protocol

_3 Nov 2026, protocol smoke only_

An isolated simulator protocol is available through `--agent-physical` with
`--agent-fd` on an RGB-discovery case. It rejects oracle labels, virtual
placement, nonsequential requests, navigation during collector ownership,
and unbounded per-command holds. A handoff requests a full controller stop,
checks two still ticks in the simulator's command-derived odometry and requires
a fresh RGB brick detection, then gives the existing autonomous discovery and
manipulation controller exclusive ownership. Collector polling has a 30,000
tick limit. Once that controller stops, acknowledgment 5 means **outcome
unverified**; the independent trace audit must assess capture and containment.
The client receives RGB and own command/joint feedback, not simulator body
identities, grasp contacts, containment or world coordinates. While the
collector owns the camera, replies carry `imageValid=false` and blank pixels
so polling does not mutate its perception buffers.

This is a hybrid: a policy can navigate, then the existing autonomous
discovery/collection controller explores, manipulates and returns. No learned
policy, handoff, physical grasp or delivery was exercised in the smoke test;
this protocol is not an end-to-end learned-fetch result. `physical-client.flex`
is a compiled but untested experimental client. It uses the same 84×84
box-area RGB resize, recurrent model interface, 10-tick drive actions, previous
action and normalized drive commands as the virtual chase client. Compatibility
is **not established**: the virtual agent closes its gripper while this case
starts with an open, automatic gripper, affecting both RGB and collision. Its
collision feedback and carry cue are always zero,
while chase supplies collision feedback and a virtual carrying event. The
client now requests the 82° camera pitch used to train `more1`. It refuses
to run unless `--allow-zero-contact` explicitly acknowledges the missing
contact feedback. A native fixture checks bitwise feedback equality with
chase for four drive inputs where contact and carry are zero; that does not prove
live image, proprioception, timing, camera-pose or model parity. The client
now rejects a missing, stale or non-driving camera observation, a moving arm,
changed joint ticks or an unexpected tick count. Its decision artifacts record
the resized actor RGB, seven feedback values, pre-inference recurrent state and
chosen action; `inputs.json` records source hashes and `result.json` records
action count, handoff and terminal status with outcome explicitly unverified.
The client requires a nonempty trace and records its SHA256 before writing a
result; this identifies the file but does not itself prove a real grasp.
The client also checks that returned wheel and steering commands match the
policy action's chase throttle deadband and steering mapping, and requires
zero wheels and centered steering for reset and stop acknowledgments. These
are simulated command checks rather than wheel-motion measurements.
These additions have compiled and passed pure gate fixtures, but have not run
against the rendered simulator or a policy. A visible brick can cause a handoff
before any policy action; the result's action count must be checked before
attributing behavior to the model.

The protocol requires a nonblocking socket, uses 30-second absolute deadlines
for reads and writes, and requests `pr_stop` and stops the discovery worker on
EOF, timeout or protocol error. Operational failures return acknowledgment 6
when transport still permits; explicit stop returns 7 after the stop command
is requested. This is simulated stop-command acknowledgment, not independent
hardware feedback. A crash or kill can prevent cleanup; notably the existing
process launcher kills child processes on client death, so the simulator's EOF
cleanup is not guaranteed in that case. Neither the protocol nor the client is
approved for physical motors.

Native compilation to separate `/tmp` binaries succeeded. The pure request
gate tests cover reset, ordering, bounds, ownership and replay rejection.
Two rendered tests in `flex/tests/physical-agent-protocol.py` exercised reset,
a zero drive, explicit stop/clean exit, and rejection of a forbidden oracle
command with stopped/error response and nonzero exit. They did not exercise
handoff, collector motion, partial reads, a timed-out peer, crashes, the client
policy process, or physical actuator feedback. Existing virtual-protocol
behavior still needs an independent runtime parity check.

`flex/tests/physical-client-stub.py` uses synthetic simulator and policy
processes, not the renderer or GPU. It exercises a one-action handoff and a
visible-at-reset zero-action handoff, reconstructs the exact actor input from
the saved artifacts, and verifies that incorrect drive echo, stale camera
frames and a missing trace fail without a result. A simulator-facing run of
the revised protocol and an independent virtual-protocol parity check remain
open.

## Bounded visible-brick trial

After the protocol fields were extended, the updated rendered smoke passed
again: reset, fresh/still camera and exact ten-tick zero drive, explicit stop,
and forbidden-oracle rejection. Then a unique one-brick selection case at
`levels-v2/pitch82/physical-hybrid-visible-trial/case.json` ran with the
`more1-s0` model and the `/tmp` simulator and client binaries. A supervisor
started the client in its own process group with a 180-second wall-clock
watchdog (TERM, then KILL on timeout); it completed normally with exit 0, and
the supervisor confirmed the process group had exited. Limits were 30 policy
actions and 30 collector polls of at most 20 simulation ticks each.

The brick was already detected on the reset image. The model therefore took
**zero actions** before handoff; no learned navigation was demonstrated. The
collector had not reached a terminal state at the 600-tick poll limit, and
the client requested and received a simulated stop-command acknowledgment.
The independently audited 1,097-step trace contains zero captures, releases
or settled deliveries and does not meet the manipulation criteria. Its hash
matches `result.json`, and the case hash matches `inputs.json`. Outputs,
model/simulator/scene hashes, sensor-only journal and audit are retained in
`levels-v2/pitch82/physical-hybrid-visible-trial/run`. This is an incomplete
selection trial, not evidence of a physical or simulated delivery.

At handoff (step 497) the collector began scanning: the trace records image
1 at step 649, image 2 at 721, and 33 free map cells at 1074. The trial ended
at step 1097 while the arm was moving for another view, with no completed
scan or reported collector fault. This is early mapping activity, not proof
of progress toward a pickup. A subsequent selection trial could allow 4,000
collector ticks under a 300-second wall watchdog, then inspect the trace
before extending it. The earlier heuristic trace needed over 14,000 total
steps to show one settled delivery; it is not a performance guarantee for
this hybrid on the new case.

The supervised 4,000-tick continuation ran from the same hashed case, scene,
simulator and `more1-s0` model, using frozen copies under
`levels-v2/pitch82/physical-hybrid-visible-4000/inputs`. The client exited 0
after 16.373 seconds; the supervisor reported no timeout or remaining worker.
The brick was still visible at reset, so the policy again took zero actions.
The collector remained in its first full discovery scan at the limit: images
increased from 2 to 16, free map cells from 33 to 69, and its view advanced
from sector 0 to sector 3 of 8. It observed one target and learned the box;
the robot remained at its start. The trace reports no physics/query faults or
protective stops, but also no grasps, releases or settled deliveries. The
independent audit reports `traceMeetsManipulationCriteria: false`. A stop
command was acknowledged and the trace hash was checked. The case-reason
string was stale ("physical agent owns navigation") after collector handoff;
protocol ownership and discovery phase identify who was actually in control.
This is still an incomplete selection run and does not demonstrate learned
navigation or a pickup.

`flex/tests/run-physical-hybrid-trial.py --check` validates the reference
inputs without launching the GPU. Its supervised run requires a new output
directory, freezes those inputs, enforces a bounded collector-tick budget and
a 300 s wall limit, uses a subreaper to stop orphaned workers, and retains the
audit. The worker cleanup path passed a synthetic test with a child in a
separate process group. The default is 4,000 ticks; longer runs require the
same client as the 4,000-tick trial. A prospective 24,000-tick run has passed
preflight but has not yet been launched.

`flex/tests/virtual-agent-runtime-parity.py` compared the original and
candidate simulators using one training-layout selection scene and six fixed
virtual commands. All six complete JSON responses and RGB hashes matched.
The binaries, scene hashes, per-frame outputs and logs are retained under
`levels-v2/pitch82/physical-virtual-protocol-parity`. This single-case check
does not establish broad protocol or task parity, and host graphics/runtime
libraries were not pinned.

The 16,000-tick continuation used the same hashed scene, simulator and model,
with a 300 s wall watchdog. It completed in 59.459 s with no timeout or
remaining workers. As in the shorter run, the brick was visible at reset, so
the learned policy took **zero actions**. The collector completed its first
scan at step 9638, approached and closed the simulated gripper, and the
independent audit found bilateral-contact capture at step 12126. The trace
shows the object held with an active constraint continuously until the last
step, 16497; there was no release or settled delivery, and the audit's
manipulation criterion remained false. At step 13858 it returned near the box;
from step 14089 to the limit it was mapping the docking floor, taking six more
images and moving the wrist through new views. No physics/query fault or
protective stop was reported. This is continued activity, not proof of a
successful delivery or learned navigation. The simulated stop was acknowledged
and the supervisor reported no remaining worker; output is retained under
`levels-v2/pitch82/physical-hybrid-visible-16000`.

The same-input 24,000-tick run ended cleanly in 93.321 seconds with no
remaining workers. Again the policy took zero actions. The independent audit
found one bilateral-contact capture at step 12102, no release and no settled
delivery; its criterion remained false. The trace shows the brick held
continuously from capture to step 24497, with the collector still scanning
the docking floor: between steps 16000 and 24000 it acquired 20 more images
and advanced from view sector 1 to sector 5. No physics/query fault or
protective stop was reported. Output and audit are retained under
`levels-v2/pitch82/physical-hybrid-visible-24000`.

Although both input manifests, client hash and initial positions match, the
16,000- and 24,000-tick traces are not exact replays: the first map update is
at step 991 versus 999, and capture is at 12126 versus 12102. Discovery
spawns and polls a wall-clock stereo worker, so its scheduling is a plausible
contributor to the timing difference, not a proven sole cause. The worker's
Python executable, script/dependencies and graphics/runtime libraries were
not pinned. Do not compare these traces as simulator-identical replays or
attribute the timing difference to a policy change.

The 29,980-tick run stayed below the protocol's 30,000-tick hard cap and
completed in 122.665 seconds with no timeout or remaining workers. Its
supervisor recorded and verified the discovery worker script, Python
executable and 491 probe-time imported module/mapped-library hashes before and
after the run. That manifest cannot retrospectively identify the earlier
workers, cover every lazy-loaded dependency, or remove scheduling
nondeterminism. Outputs are under `levels-v2/pitch82/physical-hybrid-visible-29980`.

The visible brick again caused a handoff before any policy action. The
independent trace audit reports a bilateral-contact capture at step 12134,
with no release or settled delivery, so the manipulation criterion is false.
The trace shows the object held continuously through the final step 30477,
with no reported physics/query fault or protective stop. The collector
completed one docking-floor scan at step 27508, looked for and circled the
box, then began a second docking-floor scan at step 28301; at cutoff it was
waiting on a stereo worker in sector 1. This is continued mapping activity,
not demonstrated success or proof of a stall. The simulated stop command was
acknowledged. The actor's zero actions mean none of these events demonstrates
learned navigation, and this simulation does not prove physical robot success.

An additional initial-detector-miss **selection** trial ran:
`flex/tests/run-physical-hidden-trial.py` starts with one brick behind the
robot, freezes source/model/scene inputs, and enforces a 90-action navigation
limit, 29,980-tick collector limit and 300-second wall watchdog. It rejects
a case if the first RGB frame already has a detector output; a detector miss
alone does not prove that the brick is geometrically outside the image. It records each actor
input/action and post-run simulator-truth path, and separately audits any
capture, release and containment. A handoff after policy actions establishes
temporal order only, not that the motion caused detection; the collector is
still heuristic. A completed run without handoff is a negative result, not a
successful navigation. CPU-only fixtures test invalid initial visibility,
drive/actor mismatches, trace continuity, subprocess completion, interruption
and detached-worker cleanup. In the rendered run the first frame had no
detection, the policy issued 90 nonzero drive actions and then stopped without
handoff; the post-run truth trace recorded 2.394 m of travel and 0.762 m net
displacement. The simulated stop command was acknowledged and the supervisor
reported no timeout or remaining workers. No capture, release or delivery
occurred. The actor input files were recorded but camera-to-actor resize and
runtime execution were not independently replayed. This is one negative
selection result, not a physical-robot or held-out outcome. Artifacts are in
`levels-v2/pitch82/physical-hybrid-hidden-v1`.

Post-run diagnosis from the retained trace: after action 40 the simulator
reported contact with `Wall.outer-west` for all remaining 501 simulation
ticks. The true base pose did not change, while the policy kept commanding
reverse. Recorded actor feedback contained zero contact throughout, as the
experimental client documents; this is a possible missing cue, not proof
that contact feedback would have led the policy to recover. The command-based
odometry continued integrating during the block: its path grew about 3.03 m,
with position error peaking at 0.784 m and heading error at 3.137 rad.

The RGB detector reported zero targets at every action observation. Using
the initial recorded camera calibration and post-run true base pose to
reconstruct the fixed camera, the brick center projects outside the 640×480
image at every action observation; after the wall contact, its top corners
project approximately 725–852 pixels down, below the image. This is a
geometric reconstruction, not verification of the original full-resolution
camera frames, which were not saved. It explains a plausible visibility
constraint without claiming the learned actor saw the object or proving the
cause of the learned reverse loop.

An offline candidate detector (`levels/visual-stagnation.py`) uses only the
recorded 84×84 actor pixels, requested drive actions and camera timestamps.
It requires ten consecutive textured frames, nine drive requests and low
per-pixel image change after a per-channel additive brightness adjustment.
On this same trace it flags the 41 windows beginning with actor sequence 41;
the first flag arrives at tick 985, 90 ticks (1.8 simulated seconds) after
the first blocked sample at tick 895. A separate **post-run truth-only**
audit compares each eligible window with the base pose at every simulation
tick: all 41 flagged windows were within 1 cm and 2° of their starting pose,
and all 40 unflagged windows moved beyond at least one threshold. The detector
and audit outputs, with their input hashes, are retained as
`visual-stagnation-v2.json` and `visual-stagnation-truth-audit-v2.json` beside
the hidden-trial run. The first-version reports are retained but superseded:
the second version checks applied drive echoes and rejects nonfinite poses.

This is a fit to one trace, not generalization evidence. CPU tests cover
static textured frames, uniform additive lighting changes, synthetic
translation and rotation, a changing foreground patch, missing texture,
stopped commands and timestamp gaps. A periodic striped scene translated by
one full period renders the same pixels and is deliberately flagged despite
synthetic motion: images alone cannot prove the robot is blocked. Moving
objects, lighting changes, camera jitter, blank/low-texture scenes and static
gripper occlusion can also hide or mimic changes. The detector is offline;
it does not issue a command or feed simulator truth to the actor.

With the thresholds unchanged, a separate offline diagnostic evaluated all
32 existing student-driven games from historical `chase-v1/dagger-1/shard-0`.
The audit checked each saved actor-image hash and action/drive echo, matched
decision poses to the tick-level trace, and evaluated 9,312 overlapping
windows. Among the 3,820 eligible windows, 387 flagged/stationary and 3,433
unflagged/moving; no eligible window had the opposite result. But 5,492
windows (59.0%) abstained for low texture: 112 were truth-stationary and
5,380 truth-moving. One game accounted for 110 stationary abstentions and
had no flag. A system that silently ignores abstentions would miss those
windows; one that stops on all of them could stop during many moving windows.

The 387 flags came from just three games (27, 207 and 153 overlapping
windows), not 387 independent events. The first flags in those games occurred
96, 98 and 97 simulation ticks (1.92, 1.96 and 1.94 simulated seconds) after
the retrospective start of a continuous 1 cm/2° pose interval. That is not
necessarily the onset of physical contact or a wall-clock delay. Output and
exact detector/audit source snapshots are in
`visual-stagnation/historical-dagger1-shard0-fixed-v2b`; the unchanged v1
output is retained. The low-priority CPU audit took 19.57 seconds on this
host, not a deployment benchmark. These are old virtual-chase **training**
games with unpinned historical simulator identity and correlated windows,
not held-out or physical-robot evidence.

Before deployment, freeze thresholds and test paired,
provenance-matched simulator runs on independently chosen selection scenes,
including moving textured scenes, periodic patterns, lighting and moving
objects. Measure false stops and missed stalls against post-run truth. A
first bounded simulator intervention should request stop and report an
unconfirmed visual-stagnation reason; missing, stale or low-texture images
should also fail closed. Do not turn or reverse solely from this image test.
A physical recovery maneuver additionally requires a validated clearance and
contact source, real stop acknowledgment and separate safety tests.

One stop-only paired simulator selection test was subsequently run on the
recorded wall case with the same client binary and image/command prefix.
The enabled arm stopped after 49 policy actions on visual-stagnation
suspicion; the disabled arm continued to its 90-action limit. The first 49
recorded actor-input byte sequences matched, and post-run simulator truth
showed no movement during the flagged window. The stop command was
acknowledged in simulation. This is the same case used to motivate the
detector, not independent validation, and it neither establishes obstruction
nor performs a recovery maneuver. Periodic visual patterns can still trigger
false suspicion. Artifacts are in `physical-visual-stop-pair-v1`.
