# Camera-event visual supervision

This controlled comparison trains the same flat seven-action CNN/GRU on the
accepted 172-history corpus. Both arms begin with byte-identical original core
parameters, use seed 181, batch 2 and learning rate 0.0001, and train for 40
epochs. Their episode order is identical. The treatment adds only the existing
training-time 128-to-1 image-event head, before feedback and recurrent memory.
Its positive label is the first audited consumption image; BCE weight is 1 and
positive weight is 50. Labels never become actor inputs or event hints.

The base training graph has 324,184 parameters; the treatment adds 129. The
exported actor remains the same 324,055-parameter RGB/feedback/GRU graph. All
original parameters match exactly at initialization, and the first shuffled
episode orders match. The flat/event gradient configuration passed native
central finite differences across all 18 parameter tensors and an independent
first-Adam check. Those checks validate implementation, not robot performance.

The underlying trainer now includes epoch 0 in validation selection. Native
tests verify that improving runs select their new weights and regressing warm
starts retain their initial weights while preserving actual optimizer updates,
periodic checkpoints and validation-independent gradients. The real control CLI
also retained the original c38fa6 weights on a regressing warm-start fixture;
zero-epoch initialization remains compatible.

Training and fixed epoch-10/20/40 plus standard loss-selected evaluation
completed under `build/flex/sim/camera-event-v1/`. All eight-case screens had
four open and four hidden-room episodes, with successful native audits. The
event-head model returned in 2/8, 0/8 and 0/8 episodes at epochs 10, 20 and
40 respectively; the matching plain model returned in 0/8, 1/8 and 1/8. Each
loss-selected model returned in 1/8. None returned in a hidden-room episode, so
no checkpoint triggered the predeclared paired 32-episode evaluation. These
small screens do not establish an overall improvement. The original
qualification and final gates remain unchanged, and the retained policy was
not overwritten. Exact episode records and results are in the build directory.
