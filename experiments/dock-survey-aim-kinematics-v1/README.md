# Offline dock-survey camera geometry

`audit.py` reconstructs the joint feedback and wheel-local pose recorded at
frame 11477 of the matched footprint trial. It compiles the native simulator
kinematics into a temporary CPU probe, verifies the resulting camera frame
against the saved calibration, and checks that the original high-survey target
is reproduced. It samples a small grid of arm radius, height, pitch and angular
offset values using the existing native IK; it does not command the arm.

The target used to calculate candidate wrist commands is the earlier saved RGB
box estimate already available to the survey. Candidate pixel coordinates and
camera depths are scored offline against the three-pixel native fit from the
previously examined image, assumed at 99 mm marker height. That fit is not
sufficient to authorize a release and its value is transcribed from diary 98;
the input RGB is checked against that experiment's pinned frame. The optional
truth-box error is calculated only after scoring, from saved simulator truth,
and is never used to generate a target. Source and input hashes are checked
before and after the run, but the recorded hashes do not constitute a complete
transitive compiler/runtime provenance chain.

Run from the project root:

```
python3 -B -I experiments/dock-survey-aim-kinematics-v1/audit.py > /tmp/dock-aim.json
cmp /tmp/dock-aim.json experiments/dock-survey-aim-kinematics-v1/report.json
```

IK feasibility and encoder travel are not collision checks. This probe does
not simulate arm motion, payload/self-collision, visual occlusion, camera
rasterization, fresh detection, chassis movement, or any release. It is one
known training-family pose; a full guarded rendered test and physical checks
are needed before any behavioral conclusion.
