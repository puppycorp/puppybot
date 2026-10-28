# Single-frame visual sensitivity check

The native probe replays all 300 original actions from an independently audited
hidden-room episode of the exploratory epoch-10 pose-supervised policy. It
requires matching policy hashes and a successful replay audit, and asserts that
every decoded action remains identical to the recording. At one frame, it runs
additional inference with the exact same feedback and recurrent state while
replacing a 6x6 image patch by nearby pixels. The original, unmodified state
continues the replay. A same-sized nearby floor patch is a control.

For recorded frame 1005 of hidden case 23, an independent projection of the
stationary target using the recorded sensor calibration lies at pixel
(12.50, 14.14) in the 84x84 image, inside the replaced patch at x=10..15,
y=12..17. This is offline simulator information; it never enters the actor.
The projected point and assumptions are recorded in `projection.json`.

Removing that patch changed the largest action logit by 0.225, while the floor
control changed it by 0.00064. The chosen action was reverse straight in all
three evaluations. This demonstrates sensitivity to the patch in one frame,
not reliable recognition or an episode-level causal effect. Occlusion changes
both the object and nearby pixels, and later recurrent effects were not tested.
The complete machine-readable result and projection are in
`build/flex/sim/memory-pose-v1/vision-sensitivity-hidden-23/`.
