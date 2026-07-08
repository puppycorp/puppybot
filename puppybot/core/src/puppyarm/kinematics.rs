use core::f64::consts::PI;

pub const ARM_L1_MM: f64 = 147.75108525844107;
pub const ARM_L2_MM: f64 = 153.82056899073126;
pub const ARM_L3_MM: f64 = 53.09036380503875;
pub const ARM_TOOL_PHI_RAD: f64 = -PI / 2.0;
pub const Z_ORIGIN_MM: f64 = 0.0;

const ARM_BASE_R_MM: f64 = 34.66365061672025;
const ARM_BASE_Z_MM: f64 = 78.92044218483846;
const ARM_L1_PHASE_RAD: f64 = -0.04455098757637516;
const ARM_L2_PHASE_RAD: f64 = 2.3049867004356583;
const ARM_L3_PHASE_RAD: f64 = -1.2793333267189992;

const NEAR_ZERO_XY: f64 = 1.0e-12;

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct IkResult {
    pub yaw: f64,
    pub shoulder: f64,
    pub elbow: f64,
    pub wrist: f64,
    pub reachable: bool,
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

pub fn tooltip_target_to_wrist_target(
    x: f64,
    y: f64,
    z: f64,
    tool_phi_rad: f64,
) -> (f64, f64, f64) {
    let radial_backoff = ARM_L3_MM * libm::cos(tool_phi_rad);
    let vertical_backoff = ARM_L3_MM * libm::sin(tool_phi_rad);
    let r_xy = libm::sqrt(x * x + y * y);

    let (wrist_x, wrist_y) = if r_xy < 1.0e-9 || radial_backoff.abs() < 1.0e-9 {
        (x, y)
    } else {
        let ux = x / r_xy;
        let uy = y / r_xy;
        (x - radial_backoff * ux, y - radial_backoff * uy)
    };

    (wrist_x, wrist_y, z - ARM_BASE_Z_MM - vertical_backoff)
}

pub fn ik_with_tool_pitch(x: f64, y: f64, z: f64, tool_phi_rad: f64) -> IkResult {
    let (yaw, r_xy) = if x * x + y * y < NEAR_ZERO_XY {
        (0.0, 0.0)
    } else {
        (libm::atan2(y, x), libm::sqrt(x * x + y * y))
    };

    let (wrist_x, wrist_y, zw) = tooltip_target_to_wrist_target(x, y, z, tool_phi_rad);
    let rw = if x * x + y * y < NEAR_ZERO_XY {
        r_xy - ARM_BASE_R_MM
    } else {
        libm::sqrt(wrist_x * wrist_x + wrist_y * wrist_y) - ARM_BASE_R_MM
    };
    let d2 = rw * rw + zw * zw;
    let cos_q2 =
        (d2 - ARM_L1_MM * ARM_L1_MM - ARM_L2_MM * ARM_L2_MM) / (2.0 * ARM_L1_MM * ARM_L2_MM);
    let reachable = (-1.0..=1.0).contains(&cos_q2);
    let cos_q2 = clamp(cos_q2, -1.0, 1.0);

    let link_delta = libm::acos(cos_q2);
    let k1 = ARM_L1_MM + ARM_L2_MM * libm::cos(link_delta);
    let k2 = ARM_L2_MM * libm::sin(link_delta);
    let link1_angle = libm::atan2(zw, rw) - libm::atan2(k2, k1);
    let link2_angle = link1_angle + link_delta;
    let shoulder = link1_angle - ARM_L1_PHASE_RAD;
    let elbow = shoulder + ARM_L2_PHASE_RAD - link2_angle;
    let wrist = solve_tip_angle_down(shoulder, elbow, tool_phi_rad);

    IkResult {
        yaw: wrap_pi(yaw),
        shoulder,
        elbow,
        wrist,
        reachable,
    }
}

pub fn ik(x: f64, y: f64, z: f64) -> IkResult {
    ik_with_tool_pitch(x, y, z, ARM_TOOL_PHI_RAD)
}

pub fn fk(yaw: f64, shoulder: f64, elbow: f64, wrist: f64) -> (f64, f64, f64) {
    let link1_pitch = shoulder + ARM_L1_PHASE_RAD;
    let link2_pitch = shoulder - elbow + ARM_L2_PHASE_RAD;
    let tool_pitch = shoulder - elbow + wrist + ARM_L3_PHASE_RAD;
    let r = ARM_BASE_R_MM
        + ARM_L1_MM * libm::cos(link1_pitch)
        + ARM_L2_MM * libm::cos(link2_pitch)
        + ARM_L3_MM * libm::cos(tool_pitch);
    let x = r * libm::cos(yaw);
    let y = r * libm::sin(yaw);
    let z = ARM_BASE_Z_MM
        + ARM_L1_MM * libm::sin(link1_pitch)
        + ARM_L2_MM * libm::sin(link2_pitch)
        + ARM_L3_MM * libm::sin(tool_pitch);
    (x, y, z)
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
