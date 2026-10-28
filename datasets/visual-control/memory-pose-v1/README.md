# Training-only recurrent pose supervision

The episode screens below use layouts 6/7, where 21 of 32 cases also appear in
the demonstration validation set used for checkpoint selection. These are
development results, not an independent generalization test. See
`../expanded-rooms-v1/README.md` for the overlap audit and new test layouts.

The matched experiment uses 172 audited histories and the same initial actor,
camera-event auxiliary head, data order and 40-epoch training settings for both
arms. `eventPose` additionally trains a four-output GRU-state readout against
simulator-provided displacement from the starting body frame and the sine and
cosine of heading change. These labels and the readout are training only. The
exported actor still receives TCP RGB, its own feedback and recurrent state;
it receives no map, ground-truth pose, target coordinates or task-event hint.

Native tests cover gradient flow into the recurrent core, validation-label
isolation, target/source bindings, augmentation, and exact export/inference
parity. The experiment definition and hashes are in `protocol.json`; artifacts
and full episode recordings are under `build/flex/sim/memory-pose-v1/`.

At epoch 10, a fixed eight-case screen returned 0/8 for `eventOnly` and 1/8
for `eventPose`. Because that result was observed before selecting the epoch,
a wider 32-case comparison is exploratory. In that matched comparison,
`eventOnly` returned 3/32 and approached 7/32 bricks; `eventPose` returned
4/32 and approached 7/32. All 64 audits passed, but neither returned in any of
16 hidden-room cases. The successful case sets were {5,6,12} and {0,5,6,7}.
The one-case difference does not establish general improvement. Structured
results are in `exploratory-results.json`; detailed episode rows, recordings,
and input hash checks are in the build directory's `diagnostic10/`.

The predeclared screens at epochs 1, 5, 10, 20, 40 and the minimum validation
loss checkpoint are complete; all 96 episode audits passed. With pose
supervision, returns were respectively 0, 1, 1, 1, 1 and 0 out of eight; the
matching control achieved 0, 1, 0, 0, 1 and 1. No checkpoint returned in a
hidden-room episode, so no pair triggered the predeclared full-32 validation.
The selected checkpoints were epoch 28 for pose and epoch 24 for the control.
The original promotion requirement remains 24/32 returns with at least 8/16
in each room type, followed by separate reserved final layouts. The retained
production policy has not been changed.
