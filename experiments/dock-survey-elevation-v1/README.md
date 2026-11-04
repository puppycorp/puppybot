# Simulator high-wrist dock survey candidate

This isolated, default-off source transform is a hypothesis for the return
failure in diary entries 71–72 and the recorded dock-survey diagnostic. In the
saved return survey, the wrist RGB showed floor and the held brick while the
estimated box rim projected below the 640×480 image. The existing survey
aims the remembered box bearing and offsets, but tries finger pitches 60–40°
at a 14 cm radial target and heights 340–220 mm. The fixed wrist-camera
mount makes the saved approximately 50° finger pose point about 66° downward.

With `PUPPYBOT_DOCK_HIGH_SURVEY=1`, the copied simulator's hybrid collection
controller first tries a compact wrist target at 4 cm radius, 380 mm height
and 80° finger pitch along the same estimated box bearing and survey offset.
The attempt is limited to the simulator hybrid collector while its simulated
gripper reports an object held and a previous RGB box estimate exists. It
does not supply a ground-truth position or authorize a base movement, box
approach, pickup, release or success. If inverse kinematics fails or the
existing estimated arm-motion bound exceeds 2,048 ticks, the original
survey logic runs. A rejected `pr_apply` fails the case without falling
through to a second command. When enabled, `case.surveyHigh` records attempts,
accepted commands, IK rejections and motion-bound rejections; acceptance
means only that the target command was issued, not that movement completed.

The opt-in trace also records the accepted `requestId` and its four
`targetTicks`. At the existing phase-20 settling transition it records
`settledStep` only if the live targets still match and the simulator's encoder
and stopped checks pass. At each observation, `armStillMatching` requires the
same targets, those checks, phase 18, a held object and inspection-camera
mode. A new survey or departure from phases 18 and 20 clears the association:
`requestId` becomes 0, `targetTicks` becomes null and `settledStep` is -1.
This is simulator state at the observation, not proof of camera exposure,
chassis stillness, clearance or a fresh detection. To associate a saved image,
the trial must verify that its own matching trace belongs to the same frame.

The existing `ps_solid_step` simulated sweep still checks the arm and gripper
against fixed scenery and cancels on a detected blocked movement. That check
does not establish held-brick or self-collision clearance, real robot safety,
or even safety of this high pose in a different simulator scene. The new
candidate may be blocked or fail, and the existing timeout remains active.
Nothing has been promoted to the normal controller or physical robot.

A native CPU probe reconstructed the recorded local estimated pose and RGB
box centre with the same simulator asset and inverse kinematics. At the
negative 20° survey offset, the original 14 cm/340 mm/50° target projected
the estimated box centre below the image; the 4 cm/380 mm/80° target was
joint-limit reachable and projected all four estimated rim corners inside the
image. Its target ticks differed by at most 282 from the recorded encoder
ticks. These are calibrated-model projections using a stale local RGB estimate,
not raw camera proof, collision clearance, arm-path verification or proof the
real box remains there. The candidate was chosen after observing this failure
and has no generalization evidence.

Run `python3 -B -I experiments/dock-survey-elevation-v1/test.py`. The CPU
suite compiles a disposable full simulator; checks opt-in validation and
dispatch, the original fallback on IK/arm-distance rejection, failure on a
rejected arm command, disabled/not-held/non-hybrid branches and diagnostic
serialization with mocked arm calls; and exercises real native IK and camera
projection at the saved estimated pose. It checks the request association,
the existing settling transition and negative encoder, speed, target, held
object and camera-mode cases. It does not drive an arm, render a
scene, establish full disabled-path simulator parity or assess payload
collision. A separate reviewed matched rendered trial with recorded RGB,
failure accounting and simulated grasp/release/settling audit is required.
