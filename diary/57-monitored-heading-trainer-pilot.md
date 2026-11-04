# Monitored matched one-epoch trainer pilot

3 November 2026: the small stock-versus-reflink trainer pilot completed and an
independent read-only rerun of `verify_small_pilot()` passed, including the
monitored completion receipt, current input hashes, model receipts, original
roll-in data, per-arm supervisor status, model comparison and reflink extent
checks. This was one matched pair on a 34-game training-layout dataset: 31
fitting games and three validation games. Both arms used the same parent,
seed 7110000, batch size two and one epoch. The recorded commands differ in
control binary and output path; each arm exited 0 without timeout, signal or
residual-worker cleanup, in 2.686 s stock and 3.541 s reflink.

Both arms recorded 16 optimizer steps and 18 mirrored fitting sequences out of
31. The checked initial weights, first gradients, first update, first/final
ordering, initial mirror mask, epoch/final/selected weights, published policy
artifacts and checked epoch metrics matched. Both selected weights have
SHA-256 `06f352a6cfb684f4134ff746f505525a6478ace4a189f27adfe01bfa247943d5`.
Recorded final training and validation losses were approximately 0.261616 and
0.616166 in both arms; elapsed milliseconds in the logs differed. This is a
single small comparison, not proof of general GPU determinism or improvement
in robot behavior.

At recheck Btrfs reported the 216,485,888-byte reflink data file entirely
set-shared, with zero exclusive bytes, while the stock copy had 216,485,888
exclusive bytes. The reflink and source physical maps matched; the stock map
differed. This verifies the present small files, not peak space or behavior of
full-size training. Available filesystem space at audit was 51,320,684,544
bytes (47.796 GiB); no before/after training allocation delta is asserted.

The outer monitor exited 0 in 55.158 s. It logged 31 baseline samples across
30.000 s, 25 samples during the trainer worker, and one afterward. Baseline
busy was 3% in 31/31 samples; during the worker it ranged 3–57% in 25/25.
Minimum nominal free VRAM during the worker was 8,736,694,272 bytes
(8.137 GiB); there were no telemetry errors. Samples can miss transient peaks,
and whole-device busy does not measure Kennel responsiveness. The pilot does
not authorize full collection or training, establish full-scale disk or VRAM
requirements, qualify held-out performance, or demonstrate a physical robot
task. Artifacts remain under `search-dagger-heading-trainer-pilot` and
`heading-trainer-pilot-monitored-v1`.
