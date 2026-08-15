use std::ptr;

use puppybot_core::{
    config::{JointCalibration, PuppyArmConfig},
    puppyarm::{
        puppyarm::PuppyArm,
        types::{ArmCommand, ControllerError, JOINT_COUNT, TcpFrame},
    },
};

const DEFAULT_ARM_SPEED: i16 = 220;

#[repr(C)]
#[derive(Clone, Copy)]
pub struct FirmwareJointConfig {
    servo_id: u8,
    angle_sign: i8,
    drive_sign: i8,
    limit_enabled: u8,
    tick_min: i32,
    tick_max: i32,
    reference_tick: i32,
    reference_angle_rad: f64,
}

pub struct FirmwareArm {
    arm: PuppyArm,
    actuator_targets: [f64; JOINT_COUNT],
    hold_current_on_feedback: bool,
}

fn joint_calibration(config: FirmwareJointConfig) -> JointCalibration {
    JointCalibration {
        servo_id: config.servo_id,
        tick_min: config.tick_min,
        tick_max: config.tick_max,
        reference_tick: config.reference_tick,
        reference_angle_rad: config.reference_angle_rad,
        angle_sign: config.angle_sign,
        drive_sign: config.drive_sign,
        limit_enabled: config.limit_enabled != 0,
    }
}

fn firmware_arm_mut<'a>(arm: *mut FirmwareArm) -> Option<&'a mut FirmwareArm> {
    if arm.is_null() {
        return None;
    }
    // SAFETY: Every exported caller checks the opaque pointer for null. The
    // Python owner serializes access and frees it exactly once on shutdown.
    Some(unsafe { &mut *arm })
}

fn joint_angles(values: *const f64) -> Option<[f64; JOINT_COUNT]> {
    if values.is_null() {
        return None;
    }
    // SAFETY: The ABI contract requires a readable JOINT_COUNT-element array.
    let values = unsafe { std::slice::from_raw_parts(values, JOINT_COUNT) };
    values
        .iter()
        .all(|value| value.is_finite())
        .then(|| std::array::from_fn(|index| values[index]))
}

fn write_targets(arm: &FirmwareArm, output: *mut f64) -> bool {
    if output.is_null() {
        return false;
    }
    // SAFETY: The ABI contract requires a writable JOINT_COUNT-element array.
    let output = unsafe { std::slice::from_raw_parts_mut(output, JOINT_COUNT) };
    for (index, target) in output.iter_mut().enumerate() {
        *target = arm.arm.joints[index]
            .target_angle_rad
            .unwrap_or(arm.actuator_targets[index]);
    }
    true
}

fn record_feedback(arm: &mut PuppyArm, angles: [f64; JOINT_COUNT], now_ms: u64) {
    for (index, angle) in angles.into_iter().enumerate() {
        let tick = arm.joints[index].angle_to_tick(angle).rem_euclid(4096) as u16;
        arm.record_feedback(index, tick, now_ms);
    }
}

fn controller_error_code(error: ControllerError) -> i32 {
    match error {
        ControllerError::Ik(_) => 10,
        ControllerError::CartesianJointLimits(_) => 11,
        ControllerError::MissingFeedback => 12,
        ControllerError::InvalidLimit => 13,
        ControllerError::InvalidJoint => 14,
        ControllerError::InvalidServoIds => 15,
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn puppybot_arm_new(
    configs: *const FirmwareJointConfig,
    count: usize,
) -> *mut FirmwareArm {
    if configs.is_null() || count != JOINT_COUNT {
        return ptr::null_mut();
    }
    // SAFETY: Count was checked against the fixed ABI array length.
    let configs = unsafe { std::slice::from_raw_parts(configs, count) };
    let config = PuppyArmConfig {
        joints: std::array::from_fn(|index| joint_calibration(configs[index])),
    };
    let Ok(mut arm) = PuppyArm::new_with_config(&config, 0) else {
        return ptr::null_mut();
    };
    arm.handle_arm_cmd(ArmCommand::SetSpeed(DEFAULT_ARM_SPEED), 0);
    let actuator_targets = arm.joints.map(|joint| joint.reference_angle_rad);
    Box::into_raw(Box::new(FirmwareArm {
        arm,
        actuator_targets,
        hold_current_on_feedback: true,
    }))
}

#[unsafe(no_mangle)]
pub extern "C" fn puppybot_arm_free(arm: *mut FirmwareArm) {
    if arm.is_null() {
        return;
    }
    // SAFETY: The pointer came from Box::into_raw in puppybot_arm_new and the
    // Python owner calls this once when replacing or closing the controller.
    drop(unsafe { Box::from_raw(arm) });
}

#[unsafe(no_mangle)]
pub extern "C" fn puppybot_arm_feedback(
    arm: *mut FirmwareArm,
    angles: *const f64,
    now_ms: u64,
    targets: *mut f64,
) -> i32 {
    let Some(arm) = firmware_arm_mut(arm) else {
        return 1;
    };
    let Some(angles) = joint_angles(angles) else {
        return 2;
    };
    record_feedback(&mut arm.arm, angles, now_ms);
    if arm.hold_current_on_feedback {
        arm.actuator_targets = angles;
        arm.hold_current_on_feedback = false;
    }
    arm.arm.update(now_ms);
    for (index, joint) in arm.arm.joints.iter().enumerate() {
        if let Some(target) = joint.target_angle_rad {
            arm.actuator_targets[index] = target;
        }
    }
    if !write_targets(arm, targets) {
        return 3;
    }
    0
}

#[unsafe(no_mangle)]
pub extern "C" fn puppybot_arm_move_tcp_relative(
    arm: *mut FirmwareArm,
    dx_mm: f64,
    dy_mm: f64,
    dz_mm: f64,
    now_ms: u64,
) -> i32 {
    let Some(arm) = firmware_arm_mut(arm) else {
        return 1;
    };
    if ![dx_mm, dy_mm, dz_mm].iter().all(|value| value.is_finite()) {
        return 2;
    }
    match arm.arm.try_handle_arm_cmd(
        ArmCommand::MoveTcp {
            frame: TcpFrame::Base,
            dx_mm,
            dy_mm,
            dz_mm,
        },
        now_ms,
    ) {
        Ok(()) => 0,
        Err(error) => controller_error_code(error),
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn puppybot_arm_stop(arm: *mut FirmwareArm, now_ms: u64) -> i32 {
    let Some(arm) = firmware_arm_mut(arm) else {
        return 1;
    };
    arm.hold_current_on_feedback = true;
    match arm.arm.try_handle_arm_cmd(ArmCommand::StopAll, now_ms) {
        Ok(()) => 0,
        Err(_) => 2,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn test_configs() -> [FirmwareJointConfig; JOINT_COUNT] {
        let config = puppybot_core::config::PuppybotConfigV1::default();
        config.arm.joints.map(|joint| FirmwareJointConfig {
            servo_id: joint.servo_id,
            angle_sign: joint.angle_sign,
            drive_sign: joint.drive_sign,
            limit_enabled: u8::from(joint.limit_enabled),
            tick_min: joint.tick_min,
            tick_max: joint.tick_max,
            reference_tick: joint.reference_tick,
            reference_angle_rad: joint.reference_angle_rad,
        })
    }

    #[test]
    fn ffi_controller_accepts_feedback_and_relative_tcp_motion() {
        let configs = test_configs();
        let arm = puppybot_arm_new(configs.as_ptr(), configs.len());
        assert!(!arm.is_null());
        let angles = [0.0, 1.2, 1.8, 0.2];
        let mut targets = [0.0; JOINT_COUNT];
        assert_eq!(
            puppybot_arm_feedback(arm, angles.as_ptr(), 20, targets.as_mut_ptr()),
            0
        );
        assert_eq!(puppybot_arm_move_tcp_relative(arm, 0.0, 0.0, 2.0, 20), 0);
        assert_eq!(
            puppybot_arm_feedback(arm, angles.as_ptr(), 40, targets.as_mut_ptr()),
            0
        );
        assert!(targets.iter().all(|target| target.is_finite()));
        puppybot_arm_free(arm);
    }
}
