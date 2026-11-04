# Monitored matched eight-epoch heading training

3 November 2026: the saved full-training report says
`training_diagnostic_only`, and the monitored completion receipt says `passed`.
Both arm supervisors recorded exit 0 with no timeout, signal or residual-worker
cleanup: control in 281.885 s and treatment in 279.766 s. The outer monitor
recorded exit 0 under its 15,000-second limit in 1,224.819 s. This inspection
reads saved reports, receipts and telemetry; it does not rehash the multi-GiB
training data or independently attest what the operating system executed.

Both model receipts record the same initial weights, seed 6900000, batch size
two, eight epochs, checkpoint interval eight, mirror augmentation, carry cue,
unit transition weight and `joint-seven-v1` action codec. Their inputs are
their respective matched overlays. The logged curves contain epoch 0 plus
epochs 1–8 and 3,712 optimizer steps per arm. The saved matched-artifact audit
passed for initial weights, first and final ordering, first mirror mask and
per-epoch aggregate mirror counts; the final count was 3,787 per arm. This does
not establish identical intermediate orders or individual later mirror draws.

The recorded validation-selected weight hashes begin `0403290e57b1` for
control and `b4256b8177d8` for treatment. Both differ from their own recorded
epoch-8 hashes, which begin `a8c2573f11e0` and `cc427c7c7ae7` respectively.
For each arm the completion receipt records the same hash for epoch-8 and
`last.bin`. Fixed-epoch evaluation is therefore needed alongside any
validation-selected comparison; no selection or policy improvement is
established by these training results. The original paired overlays have the
same 96 validation games, but only one matched training seed has been run.

The training report records each model data clone as 6,520,016,896 total
Btrfs extent bytes, zero exclusive and 6,520,016,896 set-shared. Those are
recorded point-in-time extent figures, not a net-space-saved measurement.
The completion receipt recorded 50,012,762,112 free bytes (46.578 GiB) before
publication. Recorded disk samples during the worker bottomed at
50,011,541,504 bytes (46.577 GiB), above the 34 GiB sampled stop threshold and
32 GiB floor; the available space can change between samples.

GPU telemetry has 31 baseline samples across 30.001 s, 1,194 samples while
the training worker—including its CPU audits—ran, and one afterward. Baseline
busy was 3% in 31/31 samples; worker samples ranged 3–71% in 1,194/1,194,
with minimum nominal free VRAM of 8,093,736,960 bytes (7.538 GiB). GPU and
disk logs recorded no errors. One-second device-wide samples can miss spikes
and do not establish Kennel responsiveness or GPU execution identity.

These are simulator-training artifacts, with a simulator-derived carry cue;
they do not demonstrate held-out success, physical pickup/delivery, or robot
readiness. The model files and report remain under
`search-dagger-heading/models`, with monitor evidence under
`heading-full-training-monitored-v1`.
