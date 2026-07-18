use std::{
    ffi::{OsStr, OsString},
    fs,
    io::ErrorKind,
    path::{Path, PathBuf},
};

#[cfg(test)]
use puppybot_core::config::PUPPYBOT_CONFIG_VERSION;
use puppybot_core::{
    config::{
        CoordinateCalibration, JointCalibration, PuppyArmConfig, PuppybotConfigV1, SERIAL_LEN,
    },
    drive::DriveConfig,
    puppyarm::types::JOINT_COUNT,
};
use serde_json::Value;

pub(crate) const DEFAULT_CONFIG_FILE: &str = "puppybot.json";
pub(crate) const DEFAULT_SIM_CONFIG_FILE: &str = "puppybot.sim.json";
pub(crate) const RUNTIME_CONFIG_ENV: &str = "PUPPYBOT_RUNTIME_CONFIG";

pub(crate) fn runtime_config_path(cli_path: Option<&str>, simulated: bool) -> PathBuf {
    resolve_runtime_config_path(
        cli_path,
        std::env::var_os(RUNTIME_CONFIG_ENV).as_deref(),
        simulated,
    )
}

fn resolve_runtime_config_path(
    cli_path: Option<&str>,
    env_path: Option<&OsStr>,
    simulated: bool,
) -> PathBuf {
    cli_path
        .filter(|path| !path.trim().is_empty())
        .map(PathBuf::from)
        .or_else(|| env_path.filter(|path| !path.is_empty()).map(PathBuf::from))
        .unwrap_or_else(|| {
            if simulated {
                Path::new(env!("CARGO_MANIFEST_DIR")).join(DEFAULT_SIM_CONFIG_FILE)
            } else {
                PathBuf::from(DEFAULT_CONFIG_FILE)
            }
        })
}

pub(crate) fn load_runtime_config(path: &Path) -> Result<Option<PuppybotConfigV1>, String> {
    let contents = match fs::read_to_string(path) {
        Ok(contents) => contents,
        Err(err) if err.kind() == ErrorKind::NotFound => return Ok(None),
        Err(err) => return Err(format!("failed to read config {}: {err}", path.display())),
    };
    parse_config_json(&contents)
        .map(Some)
        .map_err(|err| format!("invalid config {}: {err}", path.display()))
}

pub(crate) fn runtime_config_state_json(
    path: &str,
    dirty: bool,
    config: &PuppybotConfigV1,
) -> Result<String, String> {
    config.validate().map_err(|err| err.to_string())?;
    let value = serde_json::json!({
        "path": path,
        "dirty": dirty,
        "config": config_json(config),
    });
    serde_json::to_string_pretty(&value)
        .map(|json| format!("{json}\n"))
        .map_err(|err| err.to_string())
}

pub(crate) fn save_runtime_config(path: &Path, config: &PuppybotConfigV1) -> Result<(), String> {
    config.validate().map_err(|err| err.to_string())?;

    let contents = runtime_config_json(config)?;
    let temp_path = temp_config_path(path);
    fs::write(&temp_path, contents)
        .map_err(|err| format!("failed to write temp config {}: {err}", temp_path.display()))?;
    fs::rename(&temp_path, path).map_err(|err| {
        let _ = fs::remove_file(&temp_path);
        format!(
            "failed to replace config {} with {}: {err}",
            path.display(),
            temp_path.display()
        )
    })
}

pub(crate) fn runtime_config_json(config: &PuppybotConfigV1) -> Result<String, String> {
    config.validate().map_err(|err| err.to_string())?;
    serde_json::to_string_pretty(&config_json(config))
        .map(|json| format!("{json}\n"))
        .map_err(|err| err.to_string())
}

fn config_json(config: &PuppybotConfigV1) -> Value {
    serde_json::json!({
        "version": config.version,
        "serial": serial_string(&config.serial),
        "drive": {
            "left_motor_id": config.drive.left_motor_id,
            "right_motor_id": config.drive.right_motor_id,
            "steering_servo_id": config.drive.steering_servo_id,
            "steering_center_deg": config.drive.steering_center_deg,
            "steering_range_deg": config.drive.steering_range_deg,
            "command_timeout_ms": config.drive.command_timeout_ms,
        },
        "arm": {
            "joints": config.arm.joints.iter().map(joint_json).collect::<Vec<_>>(),
        },
        "coordinate": {
            "forward_sign": config.coordinate.forward_sign,
            "left_sign": config.coordinate.left_sign,
            "base_yaw_offset_deg": config.coordinate.base_yaw_offset_deg,
        },
    })
}

fn joint_json(joint: &JointCalibration) -> Value {
    serde_json::json!({
        "servo_id": joint.servo_id,
        "tick_min": joint.tick_min,
        "tick_max": joint.tick_max,
        "reference_tick": joint.reference_tick,
        "reference_angle_deg": joint.reference_angle_rad.to_degrees(),
        "angle_sign": joint.angle_sign,
        "drive_sign": joint.drive_sign,
        "limit_enabled": joint.limit_enabled,
    })
}

fn parse_config_json(contents: &str) -> Result<PuppybotConfigV1, String> {
    let root: Value = serde_json::from_str(contents).map_err(|err| err.to_string())?;
    let root = object(&root, "root")?;
    let config = PuppybotConfigV1 {
        version: u16_field(root, "version")?,
        serial: serial_field(root, "serial")?,
        drive: drive_field(root, "drive")?,
        arm: arm_field(root, "arm")?,
        coordinate: coordinate_field(root, "coordinate")?,
    };
    config.validate().map_err(|err| err.to_string())?;
    Ok(config)
}

fn serial_string(serial: &[u8; SERIAL_LEN]) -> String {
    let len = serial
        .iter()
        .position(|byte| *byte == 0)
        .unwrap_or(SERIAL_LEN);
    String::from_utf8_lossy(&serial[..len]).to_string()
}

fn temp_config_path(path: &Path) -> PathBuf {
    let file_name = path.file_name().unwrap_or(OsStr::new(DEFAULT_CONFIG_FILE));
    let mut temp_name = OsString::from(".");
    temp_name.push(file_name);
    temp_name.push(".tmp");
    path.with_file_name(temp_name)
}

fn arm_field(root: &serde_json::Map<String, Value>, name: &str) -> Result<PuppyArmConfig, String> {
    let arm = object(field(root, name)?, name)?;
    let joints = array_field(arm, "joints")?;
    if joints.len() != JOINT_COUNT {
        return Err(format!(
            "arm.joints must contain exactly {JOINT_COUNT} entries"
        ));
    }
    let mut parsed = [joint(1), joint(2), joint(3), joint(4)];
    for (index, value) in joints.iter().enumerate() {
        parsed[index] = joint_field(value, index)?;
    }
    Ok(PuppyArmConfig { joints: parsed })
}

fn array_field<'a>(
    root: &'a serde_json::Map<String, Value>,
    name: &str,
) -> Result<&'a Vec<Value>, String> {
    field(root, name)?
        .as_array()
        .ok_or_else(|| format!("{name} must be an array"))
}

fn bool_field(root: &serde_json::Map<String, Value>, name: &str) -> Result<bool, String> {
    field(root, name)?
        .as_bool()
        .ok_or_else(|| format!("{name} must be a boolean"))
}

fn coordinate_field(
    root: &serde_json::Map<String, Value>,
    name: &str,
) -> Result<CoordinateCalibration, String> {
    let Some(value) = root.get(name) else {
        return Ok(CoordinateCalibration::default());
    };
    let coordinate = object(value, name)?;
    Ok(CoordinateCalibration {
        forward_sign: i8_sign_field(coordinate, "forward_sign")?,
        left_sign: i8_sign_field(coordinate, "left_sign")?,
        base_yaw_offset_deg: optional_f64_field(coordinate, "base_yaw_offset_deg")?
            .unwrap_or_default(),
    })
}

fn drive_field(root: &serde_json::Map<String, Value>, name: &str) -> Result<DriveConfig, String> {
    let drive = object(field(root, name)?, name)?;
    Ok(DriveConfig {
        left_motor_id: u8_field(drive, "left_motor_id")?,
        right_motor_id: u8_field(drive, "right_motor_id")?,
        steering_servo_id: u8_field(drive, "steering_servo_id")?,
        steering_center_deg: u16_field(drive, "steering_center_deg")?,
        steering_range_deg: u16_field(drive, "steering_range_deg")?,
        command_timeout_ms: u64_field(drive, "command_timeout_ms")?,
    })
}

fn f64_field(root: &serde_json::Map<String, Value>, name: &str) -> Result<f64, String> {
    let value = field(root, name)?
        .as_f64()
        .ok_or_else(|| format!("{name} must be a number"))?;
    if value.is_finite() {
        Ok(value)
    } else {
        Err(format!("{name} must be finite"))
    }
}

fn field<'a>(root: &'a serde_json::Map<String, Value>, name: &str) -> Result<&'a Value, String> {
    root.get(name)
        .ok_or_else(|| format!("missing required field {name}"))
}

fn i32_field(root: &serde_json::Map<String, Value>, name: &str) -> Result<i32, String> {
    let value = field(root, name)?
        .as_i64()
        .ok_or_else(|| format!("{name} must be an integer"))?;
    i32::try_from(value).map_err(|_| format!("{name} is outside i32 range"))
}

fn optional_i32_field(
    root: &serde_json::Map<String, Value>,
    name: &str,
) -> Result<Option<i32>, String> {
    let Some(value) = root.get(name) else {
        return Ok(None);
    };
    let value = value
        .as_i64()
        .ok_or_else(|| format!("{name} must be an integer"))?;
    i32::try_from(value)
        .map(Some)
        .map_err(|_| format!("{name} is outside i32 range"))
}

fn optional_f64_field(
    root: &serde_json::Map<String, Value>,
    name: &str,
) -> Result<Option<f64>, String> {
    let Some(value) = root.get(name) else {
        return Ok(None);
    };
    let value = value
        .as_f64()
        .ok_or_else(|| format!("{name} must be a number"))?;
    if value.is_finite() {
        Ok(Some(value))
    } else {
        Err(format!("{name} must be finite"))
    }
}

fn compatible_i32_field(
    root: &serde_json::Map<String, Value>,
    name: &str,
    legacy_name: &str,
) -> Result<i32, String> {
    match (
        optional_i32_field(root, name)?,
        optional_i32_field(root, legacy_name)?,
    ) {
        (Some(value), Some(legacy_value)) if value != legacy_value => {
            Err(format!("{name} conflicts with legacy field {legacy_name}"))
        }
        (Some(value), _) | (None, Some(value)) => Ok(value),
        (None, None) => Err(format!("missing required field {name}")),
    }
}

fn i8_sign_field(root: &serde_json::Map<String, Value>, name: &str) -> Result<i8, String> {
    match i32_field(root, name)? {
        -1 => Ok(-1),
        1 => Ok(1),
        _ => Err(format!("{name} must be -1 or 1")),
    }
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

fn joint_field(value: &Value, index: usize) -> Result<JointCalibration, String> {
    let name = format!("arm.joints[{index}]");
    let joint = object(value, &name)?;
    let tick_min = compatible_i32_field(joint, "tick_min", "soft_tick_min")?;
    let tick_max = compatible_i32_field(joint, "tick_max", "soft_tick_max")?;
    Ok(JointCalibration {
        servo_id: u8_field(joint, "servo_id")?,
        tick_min,
        tick_max,
        reference_tick: i32_field(joint, "reference_tick")?,
        reference_angle_rad: f64_field(joint, "reference_angle_deg")?.to_radians(),
        angle_sign: i8_sign_field(joint, "angle_sign")?,
        drive_sign: i8_sign_field(joint, "drive_sign")?,
        limit_enabled: bool_field(joint, "limit_enabled")?,
    })
}

fn object<'a>(value: &'a Value, name: &str) -> Result<&'a serde_json::Map<String, Value>, String> {
    value
        .as_object()
        .ok_or_else(|| format!("{name} must be an object"))
}

fn serial_field(
    root: &serde_json::Map<String, Value>,
    name: &str,
) -> Result<[u8; SERIAL_LEN], String> {
    let value = field(root, name)?
        .as_str()
        .ok_or_else(|| format!("{name} must be a string"))?;
    if value.is_empty() {
        return Err(format!("{name} must not be empty"));
    }
    if !value.is_ascii() {
        return Err(format!("{name} must be ASCII"));
    }
    let bytes = value.as_bytes();
    if bytes.len() > SERIAL_LEN {
        return Err(format!("{name} must be at most {SERIAL_LEN} bytes"));
    }
    let mut serial = [0; SERIAL_LEN];
    serial[..bytes.len()].copy_from_slice(bytes);
    Ok(serial)
}

fn u16_field(root: &serde_json::Map<String, Value>, name: &str) -> Result<u16, String> {
    let value = u64_field(root, name)?;
    u16::try_from(value).map_err(|_| format!("{name} is outside u16 range"))
}

fn u64_field(root: &serde_json::Map<String, Value>, name: &str) -> Result<u64, String> {
    field(root, name)?
        .as_u64()
        .ok_or_else(|| format!("{name} must be a non-negative integer"))
}

fn u8_field(root: &serde_json::Map<String, Value>, name: &str) -> Result<u8, String> {
    let value = u64_field(root, name)?;
    u8::try_from(value).map_err(|_| format!("{name} is outside u8 range"))
}

#[cfg(test)]
mod tests {
    use super::*;

    const SIMULATION_LIMITS: [(i32, i32); 4] =
        [(69, 3000), (2000, 3920), (560, 3593), (2400, 3006)];

    fn valid_json() -> &'static str {
        r#"{
            "version": 1,
            "serial": "PB-DEV-0001",
            "drive": {
                "left_motor_id": 1,
                "right_motor_id": 2,
                "steering_servo_id": 9,
                "steering_center_deg": 90,
                "steering_range_deg": 45,
                "command_timeout_ms": 500
            },
            "arm": {
                "joints": [
                    {
                        "servo_id": 11,
                        "tick_min": 0,
                        "tick_max": 4095,
                        "reference_tick": 2048,
                        "reference_angle_deg": 0.0,
                        "angle_sign": 1,
                        "drive_sign": 1,
                        "limit_enabled": true
                    },
                    {
                        "servo_id": 12,
                        "tick_min": 100,
                        "tick_max": 1000,
                        "reference_tick": 530,
                        "reference_angle_deg": 90.0,
                        "angle_sign": -1,
                        "drive_sign": 1,
                        "limit_enabled": true
                    },
                    {
                        "servo_id": 13,
                        "tick_min": 2200,
                        "tick_max": 3600,
                        "reference_tick": 3565,
                        "reference_angle_deg": 0.0,
                        "angle_sign": -1,
                        "drive_sign": 1,
                        "limit_enabled": true
                    },
                    {
                        "servo_id": 14,
                        "tick_min": 500,
                        "tick_max": 3000,
                        "reference_tick": 1783,
                        "reference_angle_deg": 0.0,
                        "angle_sign": 1,
                        "drive_sign": 1,
                        "limit_enabled": true
                    }
                ]
            }
        }"#
    }

    fn valid_json_with_coordinate(
        forward_sign: i8,
        left_sign: i8,
        base_yaw_offset_deg: f64,
    ) -> String {
        valid_json().replace(
            "\n            \"arm\": {",
            &format!(
                "\n            \"coordinate\": {{\n                \"forward_sign\": {forward_sign},\n                \"left_sign\": {left_sign},\n                \"base_yaw_offset_deg\": {base_yaw_offset_deg}\n            }},\n            \"arm\": {{"
            ),
        )
    }

    #[test]
    fn parse_valid_json_config() {
        let config = parse_config_json(valid_json()).unwrap();

        assert_eq!(config.version, PUPPYBOT_CONFIG_VERSION);
        assert_eq!(config.drive.steering_servo_id, 9);
        assert_eq!(config.arm.servo_ids(), [11, 12, 13, 14]);
        assert_eq!(config.arm.joints[1].tick_min, 100);
        assert_eq!(config.arm.joints[1].tick_max, 1000);
        assert_eq!(config.coordinate, CoordinateCalibration::default());
    }

    #[test]
    fn parse_coordinate_calibration() {
        let json = valid_json_with_coordinate(-1, 1, 90.0);

        let config = parse_config_json(&json).unwrap();

        assert_eq!(config.coordinate.forward_sign, -1);
        assert_eq!(config.coordinate.left_sign, 1);
        assert_eq!(config.coordinate.base_yaw_offset_deg, 90.0);
    }

    #[test]
    fn reject_invalid_coordinate_calibration_sign() {
        let json = valid_json_with_coordinate(0, 1, 0.0);

        assert!(
            parse_config_json(&json)
                .unwrap_err()
                .contains("forward_sign must be -1 or 1")
        );
    }

    #[test]
    fn reject_invalid_coordinate_rotation() {
        let json = valid_json_with_coordinate(1, 1, 0.0).replace(
            "\"base_yaw_offset_deg\": 0",
            "\"base_yaw_offset_deg\": null",
        );

        assert!(
            parse_config_json(&json)
                .unwrap_err()
                .contains("base_yaw_offset_deg must be a number")
        );
    }

    #[test]
    fn parse_legacy_soft_tick_limits() {
        let json = valid_json()
            .replace("\"tick_min\": 100", "\"soft_tick_min\": 123")
            .replace("\"tick_max\": 1000", "\"soft_tick_max\": 987");

        let config = parse_config_json(&json).unwrap();

        assert_eq!(config.arm.joints[1].tick_min, 123);
        assert_eq!(config.arm.joints[1].tick_max, 987);
    }

    #[test]
    fn reject_conflicting_legacy_soft_tick_limits() {
        let json = valid_json().replace(
            "\"tick_min\": 100",
            "\"tick_min\": 100, \"soft_tick_min\": 123",
        );

        assert!(
            parse_config_json(&json)
                .unwrap_err()
                .contains("conflicts with legacy field")
        );
    }

    #[test]
    fn reject_too_long_serial() {
        let json = valid_json().replace("PB-DEV-0001", "PB-DEV-0001-012345678901234567890123");

        assert!(parse_config_json(&json).unwrap_err().contains("serial"));
    }

    #[test]
    fn reject_duplicate_servo_ids() {
        let json = valid_json().replace("\"servo_id\": 12", "\"servo_id\": 11");

        assert!(parse_config_json(&json).unwrap_err().contains("duplicate"));
    }

    #[test]
    fn missing_file_uses_defaults() {
        let path = std::env::temp_dir().join(format!(
            "missing-puppybot-config-{}.json",
            std::process::id()
        ));
        let _ = std::fs::remove_file(&path);

        assert_eq!(load_runtime_config(&path).unwrap(), None);
    }

    #[test]
    fn runtime_config_path_uses_cli_override() {
        assert_eq!(
            runtime_config_path(Some("custom.json"), true),
            PathBuf::from("custom.json")
        );
    }

    #[test]
    fn simulation_without_override_uses_tracked_simulation_profile() {
        assert_eq!(
            resolve_runtime_config_path(None, None, true),
            Path::new(env!("CARGO_MANIFEST_DIR")).join(DEFAULT_SIM_CONFIG_FILE)
        );
    }

    #[test]
    fn non_simulation_without_override_keeps_physical_default() {
        assert_eq!(
            resolve_runtime_config_path(None, None, false),
            PathBuf::from(DEFAULT_CONFIG_FILE)
        );
    }

    #[test]
    fn environment_override_precedes_simulation_default() {
        assert_eq!(
            resolve_runtime_config_path(None, Some(OsStr::new("environment.json")), true),
            PathBuf::from("environment.json")
        );
    }

    #[test]
    fn save_runtime_config_writes_round_trippable_json() {
        let path =
            std::env::temp_dir().join(format!("saved-puppybot-config-{}.json", std::process::id()));
        let _ = std::fs::remove_file(&path);

        let mut config = parse_config_json(valid_json()).unwrap();
        config.arm.joints[1].tick_min = 123;
        config.arm.joints[1].tick_max = 987;
        config.arm.joints[1].limit_enabled = false;

        save_runtime_config(&path, &config).unwrap();

        let saved = std::fs::read_to_string(&path).unwrap();
        let parsed = parse_config_json(&saved).unwrap();
        assert_eq!(parsed, config);
        assert!(saved.contains("\"tick_min\": 123"));
        assert!(saved.contains("\"coordinate\""));
        assert!(!saved.contains("soft_tick"));
        assert!(!saved.contains("raw_tick"));
        assert!(saved.ends_with('\n'));

        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn simulation_joint_limits_survive_save_and_restart() {
        let source_path = resolve_runtime_config_path(None, None, true);
        let source = load_runtime_config(&source_path)
            .expect("load simulation runtime config")
            .expect("simulation runtime config exists");
        assert_eq!(
            source
                .arm
                .joints
                .map(|joint| (joint.tick_min, joint.tick_max)),
            SIMULATION_LIMITS
        );
        assert!(source.arm.joints.iter().all(|joint| joint.limit_enabled));

        let restart_path = std::env::temp_dir().join(format!(
            "saved-puppybot-sim-config-{}.json",
            std::process::id()
        ));
        let _ = std::fs::remove_file(&restart_path);
        save_runtime_config(&restart_path, &source).expect("save simulation runtime config");
        let restarted = load_runtime_config(&restart_path)
            .expect("reload simulation runtime config")
            .expect("saved simulation runtime config exists");
        assert_eq!(restarted, source);
        assert_eq!(
            restarted
                .arm
                .joints
                .map(|joint| (joint.tick_min, joint.tick_max)),
            SIMULATION_LIMITS
        );
        assert!(restarted.arm.joints.iter().all(|joint| joint.limit_enabled));

        let _ = std::fs::remove_file(&restart_path);
    }

    #[test]
    fn runtime_config_state_json_includes_metadata_and_config() {
        let config = parse_config_json(valid_json()).unwrap();
        let json = runtime_config_state_json("./puppybot.json", true, &config).unwrap();
        let value: Value = serde_json::from_str(&json).unwrap();

        assert_eq!(value["path"], "./puppybot.json");
        assert_eq!(value["dirty"], true);
        assert_eq!(value["config"]["serial"], "PB-DEV-0001");
        assert_eq!(value["config"]["arm"]["joints"][0]["servo_id"], 11);
        assert_eq!(value["config"]["coordinate"]["forward_sign"], 1);
        assert_eq!(value["config"]["coordinate"]["base_yaw_offset_deg"], 0.0);
    }
}
