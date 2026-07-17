use core::f64::consts::PI;

pub const ARM_L1_MM: f64 = 149.00090135823393;
pub const ARM_L2_MM: f64 = 155.00027915891692;
pub const ARM_L3_MM: f64 = 38.00009136344675;
pub const ARM_TOOL_PHI_RAD: f64 = -PI / 2.0;
pub const Z_ORIGIN_MM: f64 = 0.0;

pub(crate) const ARM_YAW_TO_SHOULDER_X_MM: f64 = 0.0007026911535341386;
pub(crate) const ARM_YAW_TO_SHOULDER_Y_MM: f64 = -19.150050229126062;
pub(crate) const ARM_YAW_TO_SHOULDER_Z_MM: f64 = 20.00000056097148;
const ARM_YAW_PHASE_RAD: f64 = 1.4404079598246167;
const ARM_L1_PHASE_RAD: f64 = 0.021156497956719415;
const ARM_L2_PHASE_RAD: f64 = 3.1272689969908543;
const ARM_L3_PHASE_RAD: f64 = -3.1709794666200595;

const NEAR_ZERO_XY: f64 = 1.0e-12;

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct IkResult {
    pub yaw: f64,
    pub shoulder: f64,
    pub elbow: f64,
    pub wrist: f64,
    pub reachable: bool,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct ArmChainPoints {
    pub yaw: [f64; 3],
    pub shoulder: [f64; 3],
    pub elbow: [f64; 3],
    pub wrist: [f64; 3],
    pub tcp: [f64; 3],
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum IkError {
    Unreachable,
}

pub fn clamp(value: f64, lo: f64, hi: f64) -> f64 {
    value.max(lo).min(hi)
}

pub fn wrap_pi(mut angle: f64) -> f64 {
    while angle > PI {
        angle -= 2.0 * PI;
    }
    while angle < -PI {
        angle += 2.0 * PI;
    }
    angle
}

pub fn solve_tip_angle_down(shoulder: f64, elbow: f64, tool_phi_rad: f64) -> f64 {
    wrap_pi(tool_phi_rad - shoulder + elbow - ARM_L3_PHASE_RAD)
}

pub fn tool_pitch(shoulder: f64, elbow: f64, wrist: f64) -> f64 {
    wrap_pi(shoulder - elbow + wrist + ARM_L3_PHASE_RAD)
}

pub fn geometric_yaw(yaw: f64) -> f64 {
    yaw + ARM_YAW_PHASE_RAD
}

pub fn tooltip_target_to_wrist_target(
    x: f64,
    y: f64,
    z: f64,
    tool_phi_rad: f64,
) -> (f64, f64, f64) {
    let radial_backoff = ARM_L3_MM * libm::cos(tool_phi_rad);
    let vertical_backoff = ARM_L3_MM * libm::sin(tool_phi_rad);
    let radial =
        libm::sqrt((x * x + y * y - ARM_YAW_TO_SHOULDER_Y_MM * ARM_YAW_TO_SHOULDER_Y_MM).max(0.0));
    let yaw = libm::atan2(y, x) - libm::atan2(ARM_YAW_TO_SHOULDER_Y_MM, radial);
    let wrist_x = x - radial_backoff * libm::cos(yaw);
    let wrist_y = y - radial_backoff * libm::sin(yaw);

    (
        wrist_x,
        wrist_y,
        z - ARM_YAW_TO_SHOULDER_Z_MM - vertical_backoff,
    )
}

fn ik_branch(
    x: f64,
    y: f64,
    z: f64,
    tool_phi_rad: f64,
    radial_sign: f64,
    elbow_sign: f64,
) -> IkResult {
    let radius_squared = x * x + y * y;
    let lateral_squared = ARM_YAW_TO_SHOULDER_Y_MM * ARM_YAW_TO_SHOULDER_Y_MM;
    let radial = radial_sign * libm::sqrt((radius_squared - lateral_squared).max(0.0));
    let geometric_yaw = if radius_squared < NEAR_ZERO_XY {
        0.0
    } else {
        libm::atan2(y, x) - libm::atan2(ARM_YAW_TO_SHOULDER_Y_MM, radial)
    };
    let radial_backoff = ARM_L3_MM * libm::cos(tool_phi_rad);
    let vertical_backoff = ARM_L3_MM * libm::sin(tool_phi_rad);
    let rw = radial - ARM_YAW_TO_SHOULDER_X_MM - radial_backoff;
    let zw = z - ARM_YAW_TO_SHOULDER_Z_MM - vertical_backoff;
    let d2 = rw * rw + zw * zw;
    let cos_q2 =
        (d2 - ARM_L1_MM * ARM_L1_MM - ARM_L2_MM * ARM_L2_MM) / (2.0 * ARM_L1_MM * ARM_L2_MM);
    let reachable = radius_squared >= lateral_squared && (-1.0..=1.0).contains(&cos_q2);
    let cos_q2 = clamp(cos_q2, -1.0, 1.0);

    let link_delta = libm::acos(cos_q2);
    let signed_delta = elbow_sign * link_delta;
    let k1 = ARM_L1_MM + ARM_L2_MM * libm::cos(signed_delta);
    let k2 = ARM_L2_MM * libm::sin(signed_delta);
    let link1_angle = libm::atan2(zw, rw) - libm::atan2(k2, k1);
    let link2_angle = link1_angle + signed_delta;
    let shoulder = link1_angle - ARM_L1_PHASE_RAD;
    let elbow = shoulder + ARM_L2_PHASE_RAD - link2_angle;
    let wrist = solve_tip_angle_down(shoulder, elbow, tool_phi_rad);

    IkResult {
        yaw: wrap_pi(geometric_yaw - ARM_YAW_PHASE_RAD),
        shoulder,
        elbow,
        wrist,
        reachable,
    }
}

pub fn ik_with_tool_pitch(x: f64, y: f64, z: f64, tool_phi_rad: f64) -> IkResult {
    ik_branch(x, y, z, tool_phi_rad, 1.0, 1.0)
}

pub fn ik_with_tool_pitch_branches(x: f64, y: f64, z: f64, tool_phi_rad: f64) -> [IkResult; 4] {
    [
        ik_branch(x, y, z, tool_phi_rad, 1.0, 1.0),
        ik_branch(x, y, z, tool_phi_rad, 1.0, -1.0),
        ik_branch(x, y, z, tool_phi_rad, -1.0, 1.0),
        ik_branch(x, y, z, tool_phi_rad, -1.0, -1.0),
    ]
}

pub fn ik(x: f64, y: f64, z: f64) -> IkResult {
    ik_with_tool_pitch(x, y, z, ARM_TOOL_PHI_RAD)
}

pub fn fk(yaw: f64, shoulder: f64, elbow: f64, wrist: f64) -> (f64, f64, f64) {
    let yaw = geometric_yaw(yaw);
    let link1_pitch = shoulder + ARM_L1_PHASE_RAD;
    let link2_pitch = shoulder - elbow + ARM_L2_PHASE_RAD;
    let tool_pitch = shoulder - elbow + wrist + ARM_L3_PHASE_RAD;
    let radial = ARM_YAW_TO_SHOULDER_X_MM
        + ARM_L1_MM * libm::cos(link1_pitch)
        + ARM_L2_MM * libm::cos(link2_pitch)
        + ARM_L3_MM * libm::cos(tool_pitch);
    let x = radial * libm::cos(yaw) - ARM_YAW_TO_SHOULDER_Y_MM * libm::sin(yaw);
    let y = radial * libm::sin(yaw) + ARM_YAW_TO_SHOULDER_Y_MM * libm::cos(yaw);
    let z = ARM_YAW_TO_SHOULDER_Z_MM
        + ARM_L1_MM * libm::sin(link1_pitch)
        + ARM_L2_MM * libm::sin(link2_pitch)
        + ARM_L3_MM * libm::sin(tool_pitch);
    (x, y, z)
}

pub fn arm_chain_points(yaw: f64, shoulder: f64, elbow: f64, wrist: f64) -> ArmChainPoints {
    let yaw = geometric_yaw(yaw);
    let link1_pitch = shoulder + ARM_L1_PHASE_RAD;
    let link2_pitch = shoulder - elbow + ARM_L2_PHASE_RAD;
    let tool_pitch = shoulder - elbow + wrist + ARM_L3_PHASE_RAD;
    let point = |radial: f64, z: f64| {
        [
            radial * libm::cos(yaw) - ARM_YAW_TO_SHOULDER_Y_MM * libm::sin(yaw),
            radial * libm::sin(yaw) + ARM_YAW_TO_SHOULDER_Y_MM * libm::cos(yaw),
            z,
        ]
    };
    let shoulder_radial = ARM_YAW_TO_SHOULDER_X_MM;
    let elbow_radial = shoulder_radial + ARM_L1_MM * libm::cos(link1_pitch);
    let elbow_z = ARM_YAW_TO_SHOULDER_Z_MM + ARM_L1_MM * libm::sin(link1_pitch);
    let wrist_radial = elbow_radial + ARM_L2_MM * libm::cos(link2_pitch);
    let wrist_z = elbow_z + ARM_L2_MM * libm::sin(link2_pitch);
    let tcp_radial = wrist_radial + ARM_L3_MM * libm::cos(tool_pitch);
    let tcp_z = wrist_z + ARM_L3_MM * libm::sin(tool_pitch);

    ArmChainPoints {
        yaw: [0.0, 0.0, 0.0],
        shoulder: point(shoulder_radial, ARM_YAW_TO_SHOULDER_Z_MM),
        elbow: point(elbow_radial, elbow_z),
        wrist: point(wrist_radial, wrist_z),
        tcp: point(tcp_radial, tcp_z),
    }
}

pub fn angle_distance(a: f64, b: f64) -> f64 {
    wrap_pi(a - b).abs()
}

pub fn solve_coords_with_tool_pitch(
    x: f64,
    y: f64,
    z: f64,
    tool_phi_rad: f64,
) -> Result<(f64, f64, f64, f64), IkError> {
    let result = ik_with_tool_pitch(x, y, z, tool_phi_rad);
    if !result.reachable {
        return Err(IkError::Unreachable);
    }
    Ok((result.yaw, result.shoulder, result.elbow, result.wrist))
}

pub fn solve_coords_tool_down(x: f64, y: f64, z: f64) -> Result<(f64, f64, f64, f64), IkError> {
    solve_coords_with_tool_pitch(x, y, z, ARM_TOOL_PHI_RAD)
}

pub fn table_to_shoulder_z(z_table_mm: f64) -> f64 {
    z_table_mm - Z_ORIGIN_MM
}

pub fn shoulder_to_table_z(z_shoulder_mm: f64) -> f64 {
    z_shoulder_mm + Z_ORIGIN_MM
}
