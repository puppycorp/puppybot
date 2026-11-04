# 43. From virtual fetch to a physical-grasp experiment

_3 Nov 2026, source review and trace audit_

The `chase-v1` find-return game is a navigation curriculum: its reach event
removes a brick when an RGB detection is associated with a simulator body and
the true distance is within 35 cm; its return event is visual docking, without
a grasp or release. `flex/sim/gripper.flex` also prevents physical capture while
`ps_seek_enabled`. Its scores cannot establish physical delivery, and the
current actor's carry cue comes from this virtual event.

The native discovery/pickup simulator is a separate path. It runs arm and
gripper motion, requires bilateral contacts to capture a body, and tests that
the released body is inside the box and slow for the configured settle time.
Its autonomous discovery controller has not yet been connected to the
learned `chase-v1` drive policy. The existing agent stream is tied to the
find-return case: `main.flex` requires `ps_seek_enabled` for `--agent-fd`, and
`ps_tick` suppresses pickup, case and discovery updates while that stream is
active. `ps_collect_select` also refuses seek mode. Disabling the capture
guard alone is therefore insufficient and would leave the manipulation state
machine inactive.

## First integration experiment

1. Add a separate simulator agent task for the physical discovery/pickup case,
   retaining the existing find-return protocol and results unchanged. Run
   normal case, pickup and discovery ticks, and give exactly one controller
   ownership of the drive and arm at a time. Stop and acknowledge drive output
   before handing control to a bounded pickup or return procedure; failures and
   timeouts stop and report rather than silently resuming.
2. Start on a fixed **selection** scene with one initially visible, reachable
   brick. During navigation, the learned policy receives only its camera frame,
   proprioception and task cues from an explicitly specified event adapter.
   Handoff uses fresh camera detections and estimated/calibrated robot state,
   not true object coordinates, body IDs, contacts or containment. Reuse the
   discovery controller's perception and guarded arm/gripper stages where
   possible; do not let navigation and manipulation issue competing commands.
3. Exercise capture, lift, return, release and settling. Verify the trace with
   `flex/exploration/manipulation_audit.py`: bilateral-contact capture must be
   followed by release of the same simulated body over the box and independent
   containment for the case's full settle window; it also requires orientation
   change no greater than 0.002 radians per 20 ms step. The auditor reads simulator truth only
   **after** the run and is not a policy input. Retain failures, collisions,
   controls, camera frames, simulator/model hashes and exact initial scenes.
   Test no detection, blocked approach, missed grasp, stale cue, dropped object
   and failed stop before expanding to out-of-view bricks and held-out rooms.
4. Freeze the navigation/manipulation interface and separate selection from
   unseen scenes and seeds before measuring full pickup-and-delivery rates.
   A favorable virtual-fetch or single visible-brick result is not completion
   of that benchmark. Simulated contact-based carry cues are not evidence that
   equivalent hardware sensing exists.

The independent auditor passed `python3 -I flex/tests/manipulation-audit.py`
(thirteen synthetic test methods) and a 14,000-step prefix of the retained 81001
heuristic physical-simulation trace: blue-block capture at step 11097,
release at 13673 and a continuous settled interval ending at 13793. The
six-object mission was not complete in that prefix. This verifies the audit
against one actual simulated capture and release; it does not demonstrate a
learned-policy integration or real hardware success. The audit checks case ID,
episode, initial object and container positions, object orientation, consecutive
20 ms frames and a conservative position/velocity continuity bound. It refuses
optimized Python because the independent containment checker uses assertions.
Release eligibility is discarded if the object leaves the wider box corridor,
does not settle within 500 steps after release, or leaves containment after
settling; a fresh capture is then needed for credit. The drop envelope,
deadline and rotation/continuity thresholds are conservative
heuristics; they can reject legitimate releases and do not prove physical
causation. The audit does not itself verify the environment binary, robot start,
simulator identity or that the trace and definition came from the same run;
those need separately recorded, matched provenance.

The configured physical runtime has four arm joints and drive/steering, but
the current Flex configuration and core API do not expose a calibrated gripper
actuator or a verified payload-retention/release signal. `pr_stop` clears arm
and drive commands, and the guarded path cancels the active exchange and
requests stopping; a disconnected servo cannot acknowledge physical stopping.
Before physical trials, specify and test the real gripper actuator, evidence
for grasp/retention and release, and stop acknowledgment under disconnects.
