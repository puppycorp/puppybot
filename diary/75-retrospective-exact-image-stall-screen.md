# Retrospective exact-image stall screen (3 Nov 2026)

The blocked debug trajectory in [entry 70](70-steering-hysteresis-failure-replay.md)
contains 157 consecutive identical saved actor-input image digests. A
retrospective screen examined all 70 saved games with this instrumentation:
24 in the first steering-kick diagnostic, 36 in the later hysteresis
diagnostic, six in the two-case replay, and four in the contact-stop replay.
These are correlated training-family runs, not 70 independent cases.

The screen requires recorded driving-camera pose and settled arm, frame ID
matching the simulator tick, consecutive ten-tick policy observations, and
nonzero echoed wheel commands between equal actor images. It then uses
simulator truth only after the run to classify a repeated-image interval as
stationary, moving or ambiguous. A recorded image digest and timestamp do not
independently prove raw camera freshness or policy execution.

At thresholds of five, ten and twenty consecutive identical images, only two
saved games triggered: seed 6800107 with kick plus hysteresis, and the
disabled-stop replay of that same trajectory. Each had 157 equal images from
decision 144 through 300; simulator truth recorded no displacement or heading
change over that interval. The other 68 saved game streams had no run of five
or more matching images under the same conditions. A five-frame rule would
first trigger before decision 148, after four nonzero-command intervals.

Thresholds were considered after observing this failure. No held-out scenes,
hardware camera, low-texture stress suite or controlled frozen-camera test is
included. These counts cannot establish a false-stop rate or reliability:
sensor noise can prevent exact equality during a real stall, and a frozen
camera or repeating appearance can produce identical frames while the robot
is moving. Existing [entry 54](54-visual-stop-validation-aborted.md) also
documents a separate, incomplete visual-stop validation.

Reproduce the saved-stream screen with
`python3 -B -I experiments/visual-exact-stall-v1/audit.py`; it reads existing
local evidence and does not run the simulator or change saved outputs.
