# Training-only relative-motion targets

These labels describe the robot's movement from its episode start: local
forward and sideways displacement, plus sine and cosine of its heading change.
Distances are divided by eight metres. Each row labels the current pre-action
RGB/feedback frame. The episode start is `[0, 0, 0, 1]`; later labels use the
preceding recorded post-action pose. Absolute world coordinates, object
positions and maps are not actor inputs.

The accepted labels cover all 172 histories with their original 136 fitting /
36 validation roles and sequence length 354. All 24,639 actual pre-action frames
match the source dataset pixels and own-feedback files. A separate inverse
transform check uses the complete per-tick physical trace, verifying 296,958
motion increments. Native checks reject changed split roles, a one-frame shift
and nonzero target padding. The actor dataset and input protocol are unchanged.

Artifacts are `build/flex/sim/odometry-aux-v1/accepted/targets.bin` and its
receipt. Target SHA256:
`ab0bc0582ad9d743593891b13db7b3478b8b6f32037c39a6e8059e17e69606d7`.
Preparation, physical verification and negative guards passed. The source data
remain the admitted172 corpus with SHA256 `05032e0e...` recorded in the receipt.

The native trainer now supports an optional training-only four-value readout of
recurrent memory via `--memory-pose DIRECTORY`. It validates the sidecar and
receipt against the exact source data, uses valid frames for the auxiliary
loss, and leaves the exported actor inputs unchanged. The readout can be
combined with camera-event supervision and correctly follows sequence mirrors.
Native finite-difference/Adam checks, label-isolation and masking tests, negative
receipt/target guards, mirrored-gradient equivalence and exact exported-actor
forward checks passed on controlled fixtures. Disabled behavior remains
byte-identical to the previous trainer in the checked optimizer step.

The labels have now been used in a matched 40-epoch full-data experiment. The
eight-case screens did not produce a checkpoint that returned in both room
types. An exploratory epoch-10 comparison on 32 matched cases gave 4/32
returns with pose supervision and 3/32 without; both approached 7/32 bricks and
neither returned in the 16 hidden-room episodes. All 64 audits passed. This is
not sufficient evidence of a general improvement. See the
[experiment results](../memory-pose-v1/README.md) for the selection caveat and
artifact locations.
