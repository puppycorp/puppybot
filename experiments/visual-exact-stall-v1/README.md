# Exact actor-image stall suspicion (simulator prototype)

The read-only `audit.py` screens saved actor-image digests from four existing
training diagnostics. It requires recorded driving-camera metadata, matching
frame ID, ten-tick consecutive action observations and a nonzero wheel-command
echo between identical actor images. Simulator truth is used only afterward to
classify the interval as stationary, moving or ambiguous. The post-hoc results
and their correlation limits are in [diary entry 75](../../diary/75-retrospective-exact-image-stall-screen.md).

`transform.py` adds a separate opt-in `--visual-stall-stop` to a copied
simulator policy controller. It compares the actual resized actor image bytes,
not truth pose, object positions or wheel odometry. Five byte-identical fresh
actor frames separated by four nonzero commanded-wheel echoes latch suspicion.
The option rejects `--blackout`, which would make the policy receive different
image values from the resized camera bytes used by this detector.
A stopped command or a timing gap resets the count; a stale timestamp or
invalid camera input latches an invalid-observation reason. The controller then
requests zero, checks the simulator's zero wheel-command echo, reports the
reason and marks the episode and its summary incomplete/failed. Its final
horizon observation is checked once; a zero action then occurs outside the
scored policy horizon. This option cannot be combined with `--contact-stop`.

Five frames was chosen after seeing one stalled trajectory, not before an
independent evaluation. Byte equality can miss a stall if the camera or image
changes due to noise, light or dynamic objects. A frozen camera, repeated
texture or repeated appearance can trigger while the robot moves; fresh
timestamps do not prove image freshness. The stop is a conservative suspicion,
not a measured successful recovery or proof that the robot was stationary.

The copied controller's existing receive and validation paths may abort before
the hook sees a bad frame. A zero action, malformed response or report-write
failure may exit without a report, and neither a simulated zero echo nor the
subsequent unacknowledged close command proves physical braking. This version
does not integrate the separately staged error-path failure-stop prototype or
any hardware contact sensor. It is not a robot safety mechanism.

The saved-stream audit requires the exact expected 24, 36, 6 and 4 stream
paths for the four diagnostics, and refuses a missing or extra stream. It does
not attest file content or the completeness of any unlisted experiment.

CPU checks compile the whole transformed controller, exercise its detector
and mocked stop hook, reject stale frames and bad zero echoes, check reset on
noise, zero command or time gaps, and show a synthetic moving-truth sequence
that can produce a false suspicion from frozen images:

```
python3 -B -I experiments/visual-exact-stall-v1/test.py
python3 -B -I experiments/visual-exact-stall-v1/audit.py
```

The hook test mocks `ve_step`; neither a real simulator peer, full episode,
independent selection cases nor physical hardware has been tested. A matched
rendered diagnostic with stopped episodes counted as failures and separate
camera-freeze/noise controls is needed before drawing behavioral conclusions.
