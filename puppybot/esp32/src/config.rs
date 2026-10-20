#![cfg(feature = "esp32")]

use core::f64::consts::FRAC_PI_2;

use puppybot_core::{
    config::{CoordinateCalibration, JointCalibration, PuppyArmConfig, PuppybotConfigV1},
    drive::DriveConfig,
};

/// Physical calibration mirrored from `runtime/puppybot.json`.
pub fn runtime_config() -> PuppybotConfigV1 {
    PuppybotConfigV1 {
        version: 1,
        serial: [
            b'P', b'B', b'-', b'D', b'E', b'V', b'-', b'0', b'0', b'0', b'1', 0, 0, 0, 0, 0, 0, 0,
            0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        ],
        drive: DriveConfig {
            left_motor_id: 1,
            right_motor_id: 2,
            steering_servo_id: 5,
            steering_center_deg: 90,
            steering_range_deg: 45,
            command_timeout_ms: 500,
        },
        arm: PuppyArmConfig {
            joints: [
                JointCalibration {
                    servo_id: 1,
                    tick_min: 2000,
                    tick_max: 1600,
                    reference_tick: 3538,
                    reference_angle_rad: FRAC_PI_2,
                    angle_sign: 1,
                    drive_sign: 1,
                    limit_enabled: true,
                },
                JointCalibration {
                    servo_id: 2,
                    tick_min: 4000,
                    tick_max: 1000,
                    reference_tick: 518,
                    reference_angle_rad: FRAC_PI_2,
                    angle_sign: -1,
                    drive_sign: 1,
                    limit_enabled: true,
                },
                JointCalibration {
                    servo_id: 3,
                    tick_min: 2000,
                    tick_max: 800,
                    reference_tick: 2553,
                    reference_angle_rad: FRAC_PI_2,
                    angle_sign: -1,
                    drive_sign: 1,
                    limit_enabled: true,
                },
                JointCalibration {
                    servo_id: 4,
                    tick_min: 600,
                    tick_max: 3000,
                    reference_tick: 2791,
                    reference_angle_rad: FRAC_PI_2,
                    angle_sign: -1,
                    drive_sign: 1,
                    limit_enabled: true,
                },
            ],
        },
        coordinate: CoordinateCalibration {
            forward_sign: -1,
            left_sign: 1,
            up_sign: 1,
            base_yaw_offset_deg: -7.15244988058,
            tcp_forward_sign: 1,
            tcp_left_sign: -1,
            tcp_up_sign: -1,
        },
    }
}
