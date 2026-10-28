# Gradient-separated heatmap actor

The layouts 6/7 episode scores below are development results: 21 of the 32
cases also occur in demonstration validation histories used for checkpoint
selection. See `../expanded-rooms-v1/README.md` for the audit and new layouts.

The model architecture and inference graph match `target-actor-v1`: camera
pixels produce a target heatmap that contributes learned features to the
recurrent driving policy. This experiment stops the driving-loss gradient at
that connection while the heatmap label loss continues to train its head. The
camera encoder remains shared and receives gradients from both objectives.
The simulator-derived target positions are masked, heuristic training labels;
no coordinates, map or task-event hint enter the actor at inference.

The control is the concurrently trained fully differentiable connected model,
with identical starting weights, seed, data and sample order. Native direct
probes confirm the driving gradient is zero at the heatmap head and nonzero at
the visual merge and shared encoder, while label gradients reach the head.
Other tests check exact initial raw inference, data isolation and trained policy
parity. The predeclared 8-case screens, paired 32-case trigger and reserved final
gates remain unchanged. Training and evaluation artifacts are under
`build/flex/sim/target-detach-v1/`; the retained policy is not overwritten.

The completed 40-epoch run returned 1/8 at every checked checkpoint (epochs
1, 5, 10, 20, 40 and the validation-selected epoch 16). All returns were in
the open room. The fully connected control returned 1/8 at epoch 1 and 0/8
at the other checked checkpoints; neither arm returned in a hidden-room
episode. Initial model bytes and final training shuffle matched. No checkpoint
qualified for promotion, and these overlapping development cases cannot prove
generalization.

An exploratory 32-case comparison of the epoch-1 checkpoints was selected
after the small screens. Both the fully connected and gradient-separated
models returned 4/32 times on the same four cases; the heatmap-only model
returned 2/32. Each approached 7/32 bricks, none returned in the 16 hidden-room
cases, and all 96 episode audits passed. This small, selected comparison does
not establish general improvement. Detailed recordings are in the build
folder's `diagnostic1/`; compact results are in `exploratory-results.json`.

At epoch 5, the detached head's top cell was within eight pixels in 665/965
validation candidate frames, compared with 17/965 for the fully connected
model and 659/965 for heatmap-only. These are correlated frames with heuristic
labels, not independent episodes. The frame-level localization difference does
not by itself establish a faster or more reliable full task.
