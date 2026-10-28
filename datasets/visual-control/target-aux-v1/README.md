# Training-only visual target-position experiment

The layouts 6/7 episode scores below are development results: 21 of the 32
cases also occur in demonstration validation histories used for checkpoint
selection. See `../expanded-rooms-v1/README.md` for the audit and new layouts.

This matched comparison adds a two-value training-only readout of the current
camera encoder. For candidate frames it predicts normalized target image x/y.
The labels combine simulator camera projection, nearby saturated pixels and a
fresh recorded colour component. This is a visibility heuristic, not proven
instance segmentation; other frames receive no target-position loss.

The sidecar is bound to the exact admitted 172-history corpus. It contains
3,864 fitting and 965 validation candidates; projection and source RGB were
independently rechecked, and eight examples were visually inspected. That
small sample does not establish the entire sidecar's label accuracy. No target
position, scene map or event hint is an actor input; the exported policy uses
only camera RGB, own feedback and recurrent state.

The treatment uses the same seed, data order, initial actor and camera-event
head as the completed `eventOnly` control in `memory-pose-v1`. The script
checks initial parameter bytes and full episode shuffle order. Native tests
cover finite-difference gradients, fitting/validation isolation, rejected bad
labels, empty batches, mirrored sequences and exact exported inference.

Training and predefined episode screens completed under
`build/flex/sim/target-aux-v1/`. Returns with target supervision at epochs 1,
5, 10, 20, 40 and the validation-selected checkpoint were 0, 1, 0, 1, 0 and 0
out of eight. The matching control achieved 0, 1, 0, 0, 1 and 1. No checkpoint
returned in a hidden-room case, so none triggered the predeclared paired full-32
validation. The existing 24/32 qualification, per-room minimum and separate
reserved final layouts remain unchanged. No production policy was overwritten.

At epoch 20 the initial screen returned 1/8 with target supervision and 0/8
without it. A wider comparison of this checkpoint, selected after observing that
screen, was exploratory: both returned 1/32, while target supervision approached
5/32 bricks and the control approached 6/32. Both had 0/16 hidden-room returns;
all 64 episode audits passed. The successful cases differed (0 versus 7), and
this sample does not establish an improvement. Detailed rows, recordings and
input hash checks are in `build/flex/sim/target-aux-v1/diagnostic20/`; compact
results are in `exploratory-results.json`.

At epoch 20, on the heuristic candidate-label validation frames, the auxiliary
head's mean absolute coordinate errors were 18.42 pixels in x and 10.66 in y
on an 84x84 input. Always predicting the fitting-label mean gave 17.87 and
10.86 pixels. This offline metric does not establish autonomous success.
