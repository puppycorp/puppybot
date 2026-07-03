use crate::{
    drive::DriveConfig,
    puppyarm::{
        servo_safety::{
            ELBOW_TICK_MAX, ELBOW_TICK_MIN, SHOULDER_TICK_MAX, SHOULDER_TICK_MIN, TICK_WRAP,
            TIP_TICK_MAX, TIP_TICK_MIN, YAW_TICK_MAX, YAW_TICK_MIN,
        },
        types::JOINT_COUNT,
    },
    stservo::{MAX_SERVO_ID, MIN_SERVO_ID},
};

pub const PUPPYBOT_CONFIG_VERSION: u16 = 1;
pub const SERIAL_LEN: usize = 32;

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct PuppybotConfigV1 {
    pub version: u16,
    pub serial: [u8; SERIAL_LEN],
    pub drive: DriveConfig,
    pub arm: PuppyArmConfig,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct PuppyArmConfig {
    pub joints: [JointCalibration; JOINT_COUNT],
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct JointCalibration {
    pub servo_id: u8,
    pub tick_min: i32,
    pub tick_max: i32,
    pub reference_tick: i32,
    pub reference_angle_rad: f64,
    pub angle_sign: i8,
    pub drive_sign: i8,
    pub limit_enabled: bool,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ConfigError {
    UnsupportedVersion,
    EmptySerial,
    InvalidSerial,
    InvalidDrive,
    InvalidServoId,
    DuplicateServoId,
    InvalidTickRange,
    InvalidSign,
    InvalidReferenceAngle,
}

fn default_serial() -> [u8; SERIAL_LEN] {
    let mut serial = [0; SERIAL_LEN];
    serial[..11].copy_from_slice(b"PB-DEV-0001");
    serial
}

fn default_joint(
    servo_id: u8,
    tick_min: i32,
    tick_max: i32,
    reference_tick: i32,
    reference_angle_rad: f64,
    angle_sign: i8,
    drive_sign: i8,
) -> JointCalibration {
    JointCalibration {
        servo_id,
        tick_min,
        tick_max,
        reference_tick,
        reference_angle_rad,
        angle_sign,
        drive_sign,
        limit_enabled: true,
    }
}

impl core::fmt::Display for ConfigError {
    fn fmt(&self, formatter: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        match self {
            Self::UnsupportedVersion => formatter.write_str("unsupported config version"),
            Self::EmptySerial => formatter.write_str("config serial is empty"),
            Self::InvalidSerial => formatter.write_str("config serial must be printable ASCII"),
            Self::InvalidDrive => formatter.write_str("invalid drive config"),
            Self::InvalidServoId => formatter.write_str("invalid servo id"),
            Self::DuplicateServoId => formatter.write_str("duplicate arm servo id"),
            Self::InvalidTickRange => formatter.write_str("invalid tick range"),
            Self::InvalidSign => formatter.write_str("invalid joint sign"),
            Self::InvalidReferenceAngle => formatter.write_str("invalid reference angle"),
        }
    }
}

impl Default for PuppybotConfigV1 {
    fn default() -> Self {
        Self {
            version: PUPPYBOT_CONFIG_VERSION,
            serial: default_serial(),
            drive: DriveConfig::default(),
            arm: PuppyArmConfig::default(),
        }
    }
}

impl Default for PuppyArmConfig {
    fn default() -> Self {
        Self {
            joints: [
                default_joint(1, YAW_TICK_MIN, YAW_TICK_MAX, 2048, 0.0, 1, 1),
                default_joint(
                    2,
                    SHOULDER_TICK_MIN,
                    SHOULDER_TICK_MAX,
                    530,
                    core::f64::consts::PI / 2.0,
                    -1,
                    1,
                ),
                default_joint(3, ELBOW_TICK_MIN, ELBOW_TICK_MAX, 3565, 0.0, -1, 1),
                default_joint(4, TIP_TICK_MIN, TIP_TICK_MAX, 1783, 0.0, 1, 1),
            ],
        }
    }
}

impl PuppybotConfigV1 {
    pub fn validate(&self) -> Result<(), ConfigError> {
        if self.version != PUPPYBOT_CONFIG_VERSION {
            return Err(ConfigError::UnsupportedVersion);
        }
        validate_serial(&self.serial)?;
        validate_drive(&self.drive)?;
        self.arm.validate()
    }
}

impl PuppyArmConfig {
    pub fn validate(&self) -> Result<(), ConfigError> {
        let mut seen = [false; 256];
        for joint in &self.joints {
            joint.validate()?;
            let servo_index = joint.servo_id as usize;
            if seen[servo_index] {
                return Err(ConfigError::DuplicateServoId);
            }
            seen[servo_index] = true;
        }
        Ok(())
    }

    pub fn servo_ids(&self) -> [u8; JOINT_COUNT] {
        core::array::from_fn(|index| self.joints[index].servo_id)
    }
}

impl JointCalibration {
    pub fn validate(&self) -> Result<(), ConfigError> {
        if !(MIN_SERVO_ID..=MAX_SERVO_ID).contains(&self.servo_id) {
            return Err(ConfigError::InvalidServoId);
        }
        if self.tick_min == self.tick_max
            || !(0..TICK_WRAP).contains(&self.tick_min)
            || !(0..TICK_WRAP).contains(&self.tick_max)
        {
            return Err(ConfigError::InvalidTickRange);
        }
        if self.angle_sign != -1 && self.angle_sign != 1 {
            return Err(ConfigError::InvalidSign);
        }
        if self.drive_sign != -1 && self.drive_sign != 1 {
            return Err(ConfigError::InvalidSign);
        }
        if !self.reference_angle_rad.is_finite() {
            return Err(ConfigError::InvalidReferenceAngle);
        }
        Ok(())
    }
}

fn validate_drive(config: &DriveConfig) -> Result<(), ConfigError> {
    if config.left_motor_id == 0
        || config.right_motor_id == 0
        || config.steering_servo_id == 0
        || config.left_motor_id == config.right_motor_id
    {
        return Err(ConfigError::InvalidDrive);
    }
    if config.steering_range_deg == 0 {
        return Err(ConfigError::InvalidDrive);
    }
    Ok(())
}

fn validate_serial(serial: &[u8; SERIAL_LEN]) -> Result<(), ConfigError> {
    let mut saw_value = false;
    let mut saw_padding = false;
    for byte in serial {
        if *byte == 0 {
            saw_padding = true;
            continue;
        }
        if saw_padding {
            return Err(ConfigError::InvalidSerial);
        }
        if !(0x20..=0x7e).contains(byte) {
            return Err(ConfigError::InvalidSerial);
        }
        saw_value = true;
    }
    if saw_value {
        Ok(())
    } else {
        Err(ConfigError::EmptySerial)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn serial(value: &str) -> [u8; SERIAL_LEN] {
        let mut serial = [0; SERIAL_LEN];
        serial[..value.len()].copy_from_slice(value.as_bytes());
        serial
    }

    fn joint(servo_id: u8) -> JointCalibration {
        JointCalibration {
            servo_id,
            tick_min: 0,
            tick_max: 4095,
            reference_tick: 2048,
            reference_angle_rad: 0.0,
            angle_sign: 1,
            drive_sign: 1,
            limit_enabled: true,
        }
    }

    fn config() -> PuppybotConfigV1 {
        PuppybotConfigV1 {
            version: PUPPYBOT_CONFIG_VERSION,
            serial: serial("PB-DEV-0001"),
            drive: DriveConfig::default(),
            arm: PuppyArmConfig {
                joints: [joint(1), joint(2), joint(3), joint(4)],
            },
        }
    }

    #[test]
    fn valid_config_passes_validation() {
        assert_eq!(config().validate(), Ok(()));
    }

    #[test]
    fn equal_joint_tick_limits_are_rejected() {
        let mut config = config();
        config.arm.joints[0].tick_min = 100;
        config.arm.joints[0].tick_max = 100;

        assert_eq!(config.validate(), Err(ConfigError::InvalidTickRange));
    }

    #[test]
    fn joint_tick_limits_must_be_inside_servo_range() {
        let mut low = config();
        low.arm.joints[0].tick_min = -1;

        assert_eq!(low.validate(), Err(ConfigError::InvalidTickRange));

        let mut high = config();
        high.arm.joints[0].tick_max = TICK_WRAP;

        assert_eq!(high.validate(), Err(ConfigError::InvalidTickRange));
    }

    #[test]
    fn wrapped_joint_tick_limits_are_allowed() {
        let mut config = config();
        config.arm.joints[0].tick_min = 3500;
        config.arm.joints[0].tick_max = 300;

        assert_eq!(config.validate(), Ok(()));
    }

    #[test]
    fn duplicate_arm_servo_ids_are_rejected() {
        let mut config = config();
        config.arm.joints[1].servo_id = 1;

        assert_eq!(config.validate(), Err(ConfigError::DuplicateServoId));
    }

    #[test]
    fn empty_serial_is_rejected() {
        let mut config = config();
        config.serial = [0; SERIAL_LEN];

        assert_eq!(config.validate(), Err(ConfigError::EmptySerial));
    }

    #[test]
    fn non_ascii_serial_is_rejected() {
        let mut config = config();
        config.serial[2] = 0xff;

        assert_eq!(config.validate(), Err(ConfigError::InvalidSerial));
    }

    #[test]
    fn zero_sign_is_rejected() {
        let mut config = config();
        config.arm.joints[0].angle_sign = 0;

        assert_eq!(config.validate(), Err(ConfigError::InvalidSign));
    }
}
