# Post-consumption heatmap supervision

The gradient-separated heatmap actor had a positive maximum heatmap logit in
all 2,401 measured held-out post-consumption frames, with a mean peak similar
to candidate-positive frames. These scores are not calibrated probabilities.
This experiment adds sampled negative heatmap loss after consumption to help
the camera head learn when the brick is absent. The first consumption-labelled
image is excluded: it is also the image that triggered consumption and can
still contain the brick. Other uncertain pre-consumption frames remain masked.

The model's runtime graph and inputs are unchanged. Target positions and phase
are training-only; the actor sees camera RGB, own feedback and recurrent state.
The matched control is `target-detach-v1`, with identical initial weights,
data, ordering and gradient separation. Tests verify finite differences,
first-frame exclusion, post-consumption gradients, validation isolation,
mirroring and exact initial/exported inference.

Training is queued behind the earlier connected-model run to limit GPU
contention. The predeclared 8-case screens, paired full-32 trigger and reserved
final gates remain unchanged. Artifacts are under
`build/flex/sim/target-absence-v1/`; the retained policy is untouched.
