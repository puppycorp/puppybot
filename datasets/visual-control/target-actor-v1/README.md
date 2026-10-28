# Learned heatmap-to-policy connection

This experiment feeds a learned projection of the camera-derived 20x20 target
heatmap into the recurrent driving features. It adds 51,328 trainable policy
parameters plus the 17-parameter heatmap head. Its inference inputs remain TCP
RGB, own feedback and recurrent state; simulator target coordinates are used
only in masked, heuristic training labels. The model still emits the same
seven driving-action scores and recurrent state.

The projection starts at zero. Shared actor and heatmap-head parameters match
the seed-197 heatmap-only control, with the same data and episode order. Native
tests cover a nonzero-connection finite-difference gradient, zero initial merge,
bit-exact initial raw output on a fixture, changed merge weights after training,
label/split/mirror guards and exact exported inference. The full comparison also
checks initial raw parity on 708 frames before running any episode screen.

The predeclared 8-case screens, paired 32-case trigger and reserved final gates
remain unchanged. Training and evaluation artifacts live in
`build/flex/sim/target-actor-v1/`. No production policy is overwritten and
no improvement is claimed before task evaluation.
