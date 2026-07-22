use std::{collections::HashMap, fs, path::Path};

use puppybot_core::{
    config::{JointCalibration, PuppybotConfigV1},
    puppyarm::{servo_safety::TICK_WRAP, types::JOINT_COUNT},
};
use robotdreams_core::project::{
    load_model_profile, project_config_for_input_path, DeviceConfig, ModelProfile, ProjectConfig,
    ProjectRobotConfig,
};
use serde_json::Value;

const ROBOT_ID: &str = "puppybot";
const SERVO_MAIN_BUS_ID: &str = "main_bus";
const MODEL_JOINT_NAMES: [&str; JOINT_COUNT] = ["yaw", "shoulder", "elbow", "wrist"];

#[derive(Clone, Copy, Debug, PartialEq)]
struct AnalyticJointMapping {
    scale: f64,
    offset_rad: f64,
}

fn json_object<'a>(
    value: &'a Value,
    path: &str,
) -> Result<&'a serde_json::Map<String, Value>, String> {
    value
        .as_object()
        .ok_or_else(|| format!("RobotDreams model profile {path} must be an object"))
}

fn json_f64(value: &Value, path: &str) -> Result<f64, String> {
    let value = value
        .as_f64()
        .ok_or_else(|| format!("RobotDreams model profile {path} must be a number"))?;
    if !value.is_finite() {
        return Err(format!("RobotDreams model profile {path} must be finite"));
    }
    Ok(value)
}

#[derive(Clone, Debug, PartialEq)]
pub struct SimulationJointMapping {
    pub bus_id: String,
    pub servo_id: u8,
    pub reference_tick: i32,
    pub alignment_reference_tick: i32,
    pub joint_position_at_reference_rad: f64,
    pub radians_per_tick: f64,
    pub ticks_per_turn: u16,
    pub wrapped: bool,
}

fn profile_json(profile: &ModelProfile) -> Result<Value, String> {
    let contents = fs::read_to_string(&profile.manifest_path).map_err(|err| {
        format!(
            "read RobotDreams model profile {}: {err}",
            profile.manifest_path.display()
        )
    })?;
    serde_json::from_str(&contents).map_err(|err| {
        format!(
            "parse RobotDreams model profile {}: {err}",
            profile.manifest_path.display()
        )
    })
}

fn analytic_mapping(
    profile_json: &Value,
    semantic_name: &str,
    urdf_joint: &str,
) -> Result<AnalyticJointMapping, String> {
    let analytic = profile_json
        .get("analyticToUrdf")
        .ok_or_else(|| "RobotDreams model profile is missing analyticToUrdf".to_string())?;
    let analytic = json_object(analytic, "analyticToUrdf")?;
    if analytic.get("unit").and_then(Value::as_str) != Some("rad") {
        return Err("RobotDreams model profile analyticToUrdf.unit must be 'rad'".to_string());
    }
    let joints = analytic
        .get("joints")
        .ok_or_else(|| "RobotDreams model profile is missing analyticToUrdf.joints".to_string())?;
    let joints = json_object(joints, "analyticToUrdf.joints")?;
    let mapping = joints.get(semantic_name).ok_or_else(|| {
        format!("RobotDreams model profile is missing analyticToUrdf.joints.{semantic_name}")
    })?;
    let mapping = json_object(mapping, &format!("analyticToUrdf.joints.{semantic_name}"))?;
    let mapped_joint = mapping
        .get("joint")
        .and_then(Value::as_str)
        .ok_or_else(|| {
            format!(
            "RobotDreams model profile analyticToUrdf.joints.{semantic_name}.joint must be a string"
        )
        })?;
    if mapped_joint != urdf_joint {
        return Err(format!(
            "RobotDreams {semantic_name} mapping is ambiguous: jointNames selects '{urdf_joint}' but analyticToUrdf selects '{mapped_joint}'"
        ));
    }
    let scale = json_f64(
        mapping.get("scale").ok_or_else(|| {
            format!(
                "RobotDreams model profile is missing analyticToUrdf.joints.{semantic_name}.scale"
            )
        })?,
        &format!("analyticToUrdf.joints.{semantic_name}.scale"),
    )?;
    if scale != -1.0 && scale != 1.0 {
        return Err(format!(
            "RobotDreams analyticToUrdf scale for {semantic_name} must be -1 or 1, got {scale}"
        ));
    }
    let offset_rad = json_f64(
        mapping.get("offset").ok_or_else(|| {
            format!(
                "RobotDreams model profile is missing analyticToUrdf.joints.{semantic_name}.offset"
            )
        })?,
        &format!("analyticToUrdf.joints.{semantic_name}.offset"),
    )?;
    Ok(AnalyticJointMapping { scale, offset_rad })
}

fn servo_profile_ticks(profile_json: &Value, profile_name: &str) -> Result<u64, String> {
    profile_json
        .get("motorProfiles")
        .and_then(|profiles| profiles.get(profile_name))
        .and_then(|profile| profile.get("positionTicks"))
        .and_then(Value::as_u64)
        .ok_or_else(|| {
            format!(
                "RobotDreams model profile is missing motorProfiles.{profile_name}.positionTicks"
            )
        })
}

fn project_robot<'a>(project: &'a ProjectConfig) -> Result<&'a ProjectRobotConfig, String> {
    let matches = project
        .robots
        .iter()
        .filter(|robot| robot.id == ROBOT_ID)
        .collect::<Vec<_>>();
    match matches.as_slice() {
        [robot] => Ok(*robot),
        [] => Err(format!(
            "RobotDreams project has no robot with id '{ROBOT_ID}'"
        )),
        _ => Err(format!(
            "RobotDreams project has multiple robots with id '{ROBOT_ID}'"
        )),
    }
}

fn semantic_joint_names(
    profile: &ModelProfile,
    robot: &ProjectRobotConfig,
) -> HashMap<String, String> {
    let mut names = profile.robot.joint_names.clone();
    names.extend(profile.joint_names.clone());
    names.extend(robot.joint_names.clone());
    names
}

fn urdf_joint_for_semantic(
    joint_names: &HashMap<String, String>,
    semantic_name: &str,
) -> Result<String, String> {
    let matches = joint_names
        .iter()
        .filter_map(|(urdf, semantic)| (semantic == semantic_name).then_some(urdf.clone()))
        .collect::<Vec<_>>();
    match matches.as_slice() {
        [joint] => Ok(joint.clone()),
        [] => Err(format!(
            "RobotDreams project/model mapping has no '{semantic_name}' joint"
        )),
        _ => Err(format!(
            "RobotDreams project/model mapping has multiple '{semantic_name}' joints: {}",
            matches.join(", ")
        )),
    }
}

fn main_bus<'a>(
    project: &'a ProjectConfig,
) -> Result<&'a robotdreams_core::project::BusConfig, String> {
    let matches = project
        .hardware
        .buses
        .iter()
        .filter(|bus| bus.id == SERVO_MAIN_BUS_ID)
        .collect::<Vec<_>>();
    match matches.as_slice() {
        [bus] => Ok(*bus),
        [] => Err(format!(
            "RobotDreams project has no '{SERVO_MAIN_BUS_ID}' servo bus"
        )),
        _ => Err(format!(
            "RobotDreams project has multiple '{SERVO_MAIN_BUS_ID}' buses"
        )),
    }
}

fn servo_for_joint<'a>(
    bus: &'a robotdreams_core::project::BusConfig,
    urdf_joint: &str,
) -> Result<&'a robotdreams_core::project::ServoDeviceConfig, String> {
    let matches = bus
        .devices
        .iter()
        .filter_map(|device| match device {
            DeviceConfig::Servo(servo)
                if servo.drives.as_ref().is_some_and(|drives| {
                    drives.robot == ROBOT_ID && drives.target == urdf_joint
                }) =>
            {
                Some(servo)
            }
            _ => None,
        })
        .collect::<Vec<_>>();
    match matches.as_slice() {
        [servo] => Ok(*servo),
        [] => Err(format!(
            "RobotDreams bus '{SERVO_MAIN_BUS_ID}' has no servo driving {ROBOT_ID}.{urdf_joint}"
        )),
        _ => Err(format!(
            "RobotDreams bus '{SERVO_MAIN_BUS_ID}' has multiple servos driving {ROBOT_ID}.{urdf_joint}"
        )),
    }
}

fn simulation_joint_mapping(
    physical: JointCalibration,
    servo: &robotdreams_core::project::ServoDeviceConfig,
    analytic: AnalyticJointMapping,
    position_ticks: u64,
    semantic_name: &str,
) -> Result<SimulationJointMapping, String> {
    if position_ticks != TICK_WRAP as u64 {
        return Err(format!(
            "RobotDreams servo profile '{}' must use {TICK_WRAP} position ticks, got {position_ticks}",
            servo.profile
        ));
    }
    let servo_id = u8::try_from(servo.id)
        .map_err(|_| format!("RobotDreams servo id {} is out of PuppyBot range", servo.id))?;
    if servo_id != physical.servo_id {
        return Err(format!(
            "PuppyBot {semantic_name} uses servo {}, but RobotDreams routes servo {} to {}.{}",
            physical.servo_id,
            servo.id,
            ROBOT_ID,
            servo
                .drives
                .as_ref()
                .map(|drives| drives.target.as_str())
                .unwrap_or("<none>")
        ));
    }
    if physical.angle_sign != -1 && physical.angle_sign != 1 {
        return Err(format!(
            "PuppyBot {semantic_name} angle_sign must be -1 or 1, got {}",
            physical.angle_sign
        ));
    }
    let joint_position_at_reference_rad =
        analytic.scale * physical.reference_angle_rad + analytic.offset_rad;
    let radians_per_tick = analytic.scale * f64::from(physical.angle_sign) * std::f64::consts::TAU
        / position_ticks as f64;
    if !joint_position_at_reference_rad.is_finite() || !radians_per_tick.is_finite() {
        return Err(format!(
            "PuppyBot {semantic_name} simulation mapping must be finite"
        ));
    }
    Ok(SimulationJointMapping {
        bus_id: SERVO_MAIN_BUS_ID.to_string(),
        servo_id,
        reference_tick: physical.reference_tick,
        alignment_reference_tick: (TICK_WRAP - 1) / 2,
        joint_position_at_reference_rad,
        radians_per_tick,
        ticks_per_turn: TICK_WRAP as u16,
        wrapped: true,
    })
}

fn load_project_and_profile(
    project_path: &Path,
) -> Result<(ProjectConfig, ModelProfile, Value), String> {
    let project = project_config_for_input_path(Some(project_path)).ok_or_else(|| {
        format!(
            "{} is not a RobotDreams project with a readable project manifest",
            project_path.display()
        )
    })?;
    let profile_path = project.model_profile_path.as_ref().ok_or_else(|| {
        format!(
            "RobotDreams project {} is missing modelProfile",
            project.manifest_path.display()
        )
    })?;
    let profile = load_model_profile(project.base_dir.join(profile_path)).map_err(|err| {
        format!(
            "load RobotDreams model profile for {}: {err}",
            project.manifest_path.display()
        )
    })?;
    let json = profile_json(&profile)?;
    Ok((project, profile, json))
}

pub fn derive_simulation_joint_mappings(
    project_path: impl AsRef<Path>,
    physical_config: &PuppybotConfigV1,
) -> Result<Vec<SimulationJointMapping>, String> {
    let project_path = project_path.as_ref();
    physical_config
        .validate()
        .map_err(|err| format!("physical PuppyBot config is invalid: {err}"))?;
    let (project, profile, profile_json) = load_project_and_profile(project_path)?;
    let robot = project_robot(&project)?;
    let joint_names = semantic_joint_names(&profile, robot);
    let bus = main_bus(&project)?;
    let mut mappings = Vec::with_capacity(JOINT_COUNT);

    for (index, semantic_name) in MODEL_JOINT_NAMES.into_iter().enumerate() {
        let urdf_joint = urdf_joint_for_semantic(&joint_names, semantic_name)?;
        let analytic = analytic_mapping(&profile_json, semantic_name, &urdf_joint)?;
        let servo = servo_for_joint(bus, &urdf_joint)?;
        let position_ticks = servo_profile_ticks(&profile_json, &servo.profile)?;
        mappings.push(simulation_joint_mapping(
            physical_config.arm.joints[index],
            servo,
            analytic,
            position_ticks,
            semantic_name,
        )?);
    }
    Ok(mappings)
}

#[cfg(test)]
mod tests {
    use super::*;
    use puppybot_core::puppyarm::servo_safety::align_tick_to_reference;

    const HALF_TICK_RAD: f64 = std::f64::consts::TAU / (TICK_WRAP as f64 * 2.0);

    fn default_project_path() -> std::path::PathBuf {
        Path::new(env!("CARGO_MANIFEST_DIR")).join("../../robotdreams/project.json")
    }

    fn angle_delta(left: f64, right: f64) -> f64 {
        (left - right + std::f64::consts::PI).rem_euclid(std::f64::consts::TAU)
            - std::f64::consts::PI
    }

    fn puppybot_angle_at_tick(joint: JointCalibration, tick: i32) -> f64 {
        let alignment_reference_tick = (TICK_WRAP - 1) / 2;
        let reference_tick =
            align_tick_to_reference(joint.reference_tick, alignment_reference_tick);
        let tick = align_tick_to_reference(tick, alignment_reference_tick);
        joint.reference_angle_rad
            + f64::from(joint.angle_sign) * f64::from(tick - reference_tick) * std::f64::consts::TAU
                / TICK_WRAP as f64
    }

    #[test]
    fn semantic_mapping_errors_identify_missing_and_ambiguous_joints() {
        let missing = urdf_joint_for_semantic(&HashMap::new(), "yaw")
            .expect_err("missing yaw mapping must fail");
        assert!(missing.contains("no 'yaw' joint"), "{missing}");

        let ambiguous = HashMap::from([
            ("joint_a".to_string(), "yaw".to_string()),
            ("joint_b".to_string(), "yaw".to_string()),
        ]);
        let ambiguous = urdf_joint_for_semantic(&ambiguous, "yaw")
            .expect_err("ambiguous yaw mapping must fail");
        assert!(ambiguous.contains("multiple 'yaw' joints"), "{ambiguous}");
        assert!(ambiguous.contains("joint_a"), "{ambiguous}");
        assert!(ambiguous.contains("joint_b"), "{ambiguous}");
    }

    #[test]
    fn session_mapping_preserves_physical_references_and_composes_analytic_to_urdf() {
        let mut physical = PuppybotConfigV1::default();
        for (index, joint) in physical.arm.joints.iter_mut().enumerate() {
            joint.servo_id = (index + 1) as u8;
            joint.reference_tick = (113 + index * 733) as i32;
            joint.reference_angle_rad = -2.4 + index as f64 * 0.73;
            joint.angle_sign = if index % 2 == 0 { -1 } else { 1 };
        }
        let mappings = derive_simulation_joint_mappings(default_project_path(), &physical)
            .expect("derive simulation mapping");
        let (project, profile, profile_json) =
            load_project_and_profile(&default_project_path()).expect("RobotDreams contract");
        let robot = project_robot(&project).expect("PuppyBot robot");
        let names = semantic_joint_names(&profile, robot);
        let bus = main_bus(&project).expect("main bus");

        for (index, semantic) in MODEL_JOINT_NAMES.into_iter().enumerate() {
            let urdf = urdf_joint_for_semantic(&names, semantic).expect("URDF joint");
            let analytic = analytic_mapping(&profile_json, semantic, &urdf).expect("analytic map");
            let _servo = servo_for_joint(bus, &urdf).expect("mapped servo");
            let mapping = &mappings[index];
            assert_eq!(
                mapping.reference_tick,
                physical.arm.joints[index].reference_tick
            );
            assert_eq!(mapping.servo_id, physical.arm.joints[index].servo_id);
            for tick in [0, 1, 17, 1023, 2048, 3715, 4094, 4095] {
                let puppybot = puppybot_angle_at_tick(physical.arm.joints[index], tick);
                let expected_urdf = puppybot * analytic.scale + analytic.offset_rad;
                let aligned_reference = align_tick_to_reference(
                    mapping.reference_tick,
                    mapping.alignment_reference_tick,
                );
                let aligned_tick = align_tick_to_reference(tick, mapping.alignment_reference_tick);
                let mapped_urdf = mapping.joint_position_at_reference_rad
                    + f64::from(aligned_tick - aligned_reference) * mapping.radians_per_tick;
                assert!(
                    angle_delta(mapped_urdf, expected_urdf).abs() <= HALF_TICK_RAD,
                    "{semantic} tick {tick}: mapped={mapped_urdf} expected={expected_urdf}"
                );
            }
        }
    }
}
