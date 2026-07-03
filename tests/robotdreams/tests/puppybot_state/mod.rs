use robotdreams_core::{RobotState, SceneLocation};

#[derive(Clone, Debug, PartialEq)]
pub struct PuppyBotState {
    pub base: SceneLocation,
    pub yaw_rad: f64,
    pub shoulder_rad: f64,
    pub elbow_rad: f64,
    pub wrist_rad: f64,
    pub tcp: SceneLocation,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PuppyBotStateError {
    MissingSemanticJoint(&'static str),
    MissingTcp,
    MissingTcpLocation,
}

impl PuppyBotState {
    pub fn parse(robot_state: RobotState) -> Result<PuppyBotState, PuppyBotStateError> {
        let yaw_rad = semantic_joint_rad(&robot_state, "yaw")?;
        let shoulder_rad = semantic_joint_rad(&robot_state, "shoulder")?;
        let elbow_rad = semantic_joint_rad(&robot_state, "elbow")?;
        let wrist_rad = semantic_joint_rad(&robot_state, "wrist")?;
        let tcp = robot_state
            .tcp
            .ok_or(PuppyBotStateError::MissingTcp)?
            .location
            .ok_or(PuppyBotStateError::MissingTcpLocation)?;

        Ok(PuppyBotState {
            base: robot_state.base,
            yaw_rad,
            shoulder_rad,
            elbow_rad,
            wrist_rad,
            tcp,
        })
    }
}

fn semantic_joint_rad(
    robot_state: &RobotState,
    semantic_name: &'static str,
) -> Result<f64, PuppyBotStateError> {
    robot_state
        .joints
        .values()
        .find(|joint| joint.semantic_name.as_deref() == Some(semantic_name))
        .map(|joint| joint.position_rad)
        .ok_or(PuppyBotStateError::MissingSemanticJoint(semantic_name))
}
