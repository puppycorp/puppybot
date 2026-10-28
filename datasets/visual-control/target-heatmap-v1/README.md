# Training-only target heatmap comparison

The layouts 6/7 episode scores below are development results: 21 of the 32
cases also occur in demonstration validation histories used for checkpoint
selection. See `../expanded-rooms-v1/README.md` for the audit and new layouts.

This experiment adds a 1x1 convolutional readout of the first camera feature
map. For each candidate target image position, it trains the nearest of the
20x20 spatial cells and 16 separated negative cells. Other frames are masked.
The head adds 17 training parameters but no inference inputs or outputs. The
candidate labels use an offline color/projection heuristic and are not proven
instance segmentation; see `../target-visibility-v1/README.md`.

The event-only control is the completed `memory-pose-v1` seed-197 run. Both
arms use the same admitted172 data, shuffle and starting actor/event weights.
Initial weights and first/final sample orders are checked byte for byte. Native
tests verify sampling, finite differences, masked batches, split isolation,
mirrors and exact exported inference. The task and predeclared 8-case screens,
paired full-32 trigger and reserved final gates remain unchanged.

Training and evaluation completed under `build/flex/sim/target-heatmap-v1/`.
At epochs 1, 5, 10, 20, 40 and the validation-selected epoch 24, the heatmap
model returned 0, 1, 0, 1, 0 and 1 times out of eight. The event-only control
returned 0, 1, 0, 0, 1 and 1. No checkpoint returned in a hidden-room case,
so none triggered predeclared full-32 validation. All 48 heatmap episode audits
passed. The retained policy is untouched.

At epoch 5, the heatmap's top cell was within eight pixels of 659/965 held-out
candidate frames, versus 3/965 at initialization. These are correlated frames
from recorded histories with heuristic labels, not independent task successes.
The improved visual readout has not established faster or more reliable
complete episodes.
