# PuppyBot RobotDreams Calibration Handoff

`robotdreams.calibration.v1.template.json` is intentionally invalid until it
contains observations from one named, assembled hardware revision. It is a
template for the `robotdreams.calibration.v1` schema implemented by
RobotDreams—not a fallback physics profile.

Use the passive capture helper to combine measured metadata and externally
recorded CSV traces. It never opens a serial port, drives a motor, changes a
servo, or supplies provisional simulation values:

```sh
cd projects/PuppyBot
python3 puppybot/scenarios/capture_robotdreams_calibration.py capture \
  --metadata robotdreams/calibration/puppybot-r1-metadata.json \
  --drive-trace robotdreams/calibration/puppybot-r1-drive.csv \
  --servo-trace robotdreams/calibration/puppybot-r1-servo.csv \
  --output robotdreams/calibration/puppybot-r1.json
python3 puppybot/scenarios/capture_robotdreams_calibration.py validate \
  --input robotdreams/calibration/puppybot-r1.json
```

`--metadata` starts as a copy of the template. It supplies `format`,
`hardware_revision`, `provenance`, `vehicle`, and `servos`; remove the empty
trace fields from that input if desired. The helper rejects placeholder,
`provisional`, `unmeasured`, `unknown`, or `TODO` provenance/identity values.
It also rejects missing/non-finite measurements and trace data inconsistent
with the declared motor/servo limits.

The drive CSV must use this exact header:

```text
time_sec,left_command,right_command,observed_linear_mps,observed_yaw_rps
```

The servo CSV keeps this existing required header, so earlier captures remain
valid:

```text
time_sec,servo_id,target_ticks,observed_present_ticks
```

When the hardware logger actually captured them, append either or both of
these optional columns, in this order:

```text
time_sec,servo_id,target_ticks,observed_present_ticks,observed_load,observed_current_raw
```

`observed_load` is the signed actuator load reading (`-1000..1000`), recorded
without scaling. `observed_current_raw` is the measured 12-bit Feetech current
register value (`0..4095`), copied without conversion or a substituted zero
for an absent measurement. Optional columns must be present for every row when
declared. Use
`servo-trace.csv.template` as a header-only starting point, then add only
values recorded by the external logger.

Commands must be normalized to `[-1, 1]`; time is seconds from the start of
that capture and must increase. Drive observations are ground-truth linear and
yaw velocity measurements. Servo observations are measured present ticks, not
the requested position copied into a trace. Keep raw video, tachometer/encoder,
current/voltage and servo-bus logs at the `provenance.source` location.

Do not use `puppybot-physics-prototype.json` as metadata input. Its values are
explicitly prototype assumptions and the capture helper rejects their
`prototype-unmeasured` identity.
