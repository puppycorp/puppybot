# Missing PuppyArm Safety Tests

This lists safety cases present in `workdir/controller/tests/test_roboband_controller.py`
that are not fully mirrored by the Rust `puppybot/core/src/puppyarm/tests.rs`
suite after the `ServoSafety` container removal.

## Retargeting Changes Direction

Python source: `test_goto_ticks_changes_direction`

What it tests:
- Start a `goto_ticks` move toward a positive yaw target.
- After feedback reaches that target, submit a new lower yaw target.
- The next speed command should reverse direction.

Why it matters:
- This catches stale target/direction state when a new target replaces an active or recently
  completed target.
- Current Rust tests cover a fresh negative target through `PuppyArm`, but not replacing an earlier
  target after feedback has moved the joint to that earlier target.

## Goto From Wrapped Out-Of-Bounds Tick Does Not Drive Deeper Out

Python source: `test_goto_q_from_wrap_outside_should_not_drive_deeper_outside`

What it tests:
- Configure a wrapped yaw soft-limit interval such as `[-500, 1300]`.
- Put feedback outside that interval on the wrapped side.
- Set a target that could produce a direction deeper outside the valid interval.
- The commanded speed should not move farther away from the allowed range.

Why it matters:
- This is a real safety edge case for wraparound joints.
- It verifies target tracking still respects recovery direction when the current tick is already
  outside a wrapped interval.
- Rust has direct limit math tests for wrapped intervals, but not this full `PuppyArm` target
  tracking case.

## Wrapped Boundary Goto Does Not Oscillate Direction

Python source: `test_goto_wrap_boundary_should_not_oscillate_yaw_direction`

What it tests:
- Configure a wrapped yaw interval near the 0/4096 boundary.
- Feed alternating ticks just inside and just outside the boundary.
- Run a target move near that boundary.
- All emitted speeds should keep a consistent safe direction rather than flipping back and forth.

Why it matters:
- Prevents boundary chatter where the controller alternates direction due to modulo alignment.
- This can cause mechanical jitter or repeated limit hits.
- Rust covers wrapped interval classification, but not repeated `PuppyArm` updates with boundary
  feedback jitter.

## Feedback Read Failure Stops Active Target Motion

Python source: `test_read_failure_with_active_target_stops_motion`

What it tests:
- A joint has an active target and a previously sent nonzero wheel speed.
- Feedback read fails for that joint.
- The next safety update commands speed `0` and clears runtime speed.

Why it matters:
- Losing feedback while moving to a target should fail safe immediately.
- Rust has stale-feedback coverage, but not explicit `record_feedback_error` coverage while target
  tracking is active.

## Feedback Read Failure Stops Free Spin

Python source: `test_read_failure_with_limits_enabled_should_stop_free_spin`

What it tests:
- Start a free-spin jog with limits enabled.
- Make the next feedback read fail.
- The next update should command speed `0`.

Why it matters:
- Free-spin jog is open-loop except for safety feedback, so feedback loss must stop motion.
- Rust covers stale feedback timeout for free-spin, but not immediate feedback-error handling.

## Deadman Command Timeout Does Not Cancel Target Tracking

Python source: `test_deadman_command_timeout_should_not_cancel_target_tracking`

What it tests:
- A joint is actively tracking a target.
- Command deadman timeout has elapsed.
- Feedback is still fresh.
- Target tracking should continue instead of being canceled by the free-spin command deadman.

Why it matters:
- The command deadman should protect free-spin jogs, not interrupt closed-loop target moves.
- Rust currently has `deadman_stops_free_spin`, but no positive case that target tracking survives
  command deadman timeout.

## Overtemperature Fault Stops Motion

Python source: `test_safety_fault_reason_should_report_overtemp`

What it tests:
- A joint temperature exceeds `MAX_TEMP_C`.
- Safety fault logic reports an overtemperature fault and blocks motion.

Why it matters:
- Temperature protection is implemented in Rust safety logic, but runtime temperature feedback is
  not wired through the current `PuppyArm` path.
- A test would document whether this is intended dormant behavior or a required safety feature to
  wire up.

## Stall Fault Stops Motion

Python source: `test_safety_fault_reason_should_report_stall_when_ticks_do_not_change`

What it tests:
- A joint is commanded above the stall speed threshold.
- Feedback is fresh but tick delta remains zero long enough to exceed the stall trip duration.
- Safety logic reports a stall and stops motion.

Why it matters:
- Prevents pushing a stuck joint indefinitely.
- Rust has stall fields and logic, but no `PuppyArm`-level or low-level test exercising the trip.

## Clear Faults Command

Python source: `test_clear_faults_command_should_clear_selected_and_all_faults`

What it tests:
- A selected joint fault can be cleared without clearing other joint faults.
- A global clear clears all joint faults and aggregate controller error state.

Why it matters:
- Faults are latched and block motion, so reset semantics must be precise.
- Rust exposes `ArmCommand::ClearFaults`, but current tests do not verify selected-vs-all behavior.

## Spin Cancels Active Target

Python source: `test_spin_should_cancel_active_target`

What it tests:
- A joint has an active target.
- A spin command is issued for the same joint.
- The target is cleared and the joint begins spinning in the requested direction.

Why it matters:
- Jogging should take over cleanly from target tracking.
- Rust indirectly covers stop canceling targets, but not spin canceling targets.

## Spin Clears Latched Fault

Python source: `test_spin_should_clear_latched_fault_for_joint`

What it tests:
- A joint has a latched fault and stall timestamp.
- A spin command for that joint clears the fault state and sets the requested speed.

Why it matters:
- This defines whether user motion commands are allowed to clear per-joint latched faults.
- Rust `Joint::spin` clears faults, but there is no test covering this through `PuppyArm`.

## Target Tracking Preserves Joint Drive Direction

Python sources:
- `test_elbow_target_tracking_should_preserve_original_drive_direction`
- `test_shoulder_target_tracking_should_preserve_original_drive_direction`

What they test:
- Shoulder and elbow use joint-specific angle/sign calibration.
- Target tracking should still command the physically correct wheel direction for those joints.

Why it matters:
- A sign regression can make a joint drive away from the target even when tick math looks correct.
- Rust has positive/negative yaw-like tracking tests, but not shoulder/elbow drive-sign regression
  tests through calibrated joints.

## Calibration Reference Points

Python sources:
- `test_tick_to_angle_should_match_joint_calibration_reference_points`
- `test_angle_to_tick_should_match_joint_calibration_reference_points`
- `test_tip_full_rotation_should_map_ninety_degrees_to_plus_1024_ticks`
- `test_elbow_angle_sign_should_flip_around_zero_reference`
- `test_yaw_angle_to_tick_should_use_full_servo_rotation`

What they test:
- Known zero/reference ticks map to known joint angles.
- Known joint angles map back to known ticks.
- Full-rotation math uses raw calibration range rather than mutable soft limits.
- Elbow sign convention is correct around its reference tick.

Why it matters:
- These are not safety-stop tests, but they protect target safety indirectly because `goto_angles`
  and `goto_coords` depend on calibrated tick conversion.
- Rust has some conversion tests, but not all reference-point and sign-specific cases from the
  Python suite.
