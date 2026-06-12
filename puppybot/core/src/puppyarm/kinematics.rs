use core::f64::consts::PI;

pub const ARM_L1_MM: f64 = 150.0;
pub const ARM_L2_MM: f64 = 152.0;
pub const ARM_L3_MM: f64 = 130.0;
pub const ARM_TOOL_PHI_RAD: f64 = -PI / 2.0;
pub const Z_ORIGIN_MM: f64 = 60.0;

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
    wrap_pi(shoulder - elbow - tool_phi_rad)
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

    (wrist_x, wrist_y, z - vertical_backoff)
}

pub fn ik_with_tool_pitch(x: f64, y: f64, z: f64, tool_phi_rad: f64) -> IkResult {
    let (yaw, r_xy) = if x * x + y * y < NEAR_ZERO_XY {
        (0.0, 0.0)
    } else {
        (libm::atan2(y, -x), libm::sqrt(x * x + y * y))
    };

    let (wrist_x, wrist_y, zw) = tooltip_target_to_wrist_target(x, y, z, tool_phi_rad);
    let rw = if x * x + y * y < NEAR_ZERO_XY {
        r_xy
    } else {
        libm::sqrt(wrist_x * wrist_x + wrist_y * wrist_y)
    };
    let d2 = rw * rw + zw * zw;
    let cos_q2 =
        (d2 - ARM_L1_MM * ARM_L1_MM - ARM_L2_MM * ARM_L2_MM) / (2.0 * ARM_L1_MM * ARM_L2_MM);
    let reachable = (-1.0..=1.0).contains(&cos_q2);
    let cos_q2 = clamp(cos_q2, -1.0, 1.0);

    let gamma = -libm::acos(cos_q2);
    let k1 = ARM_L1_MM + ARM_L2_MM * libm::cos(gamma);
    let k2 = ARM_L2_MM * libm::sin(gamma);
    let shoulder = libm::atan2(zw, rw) - libm::atan2(k2, k1);
    let elbow = -gamma;
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
    let link2_pitch = shoulder - elbow;
    let tool_pitch = link2_pitch - wrist;
    let r = ARM_L1_MM * libm::cos(shoulder)
        + ARM_L2_MM * libm::cos(link2_pitch)
        + ARM_L3_MM * libm::cos(tool_pitch);
    let x = -r * libm::cos(yaw);
    let y = r * libm::sin(yaw);
    let z = ARM_L1_MM * libm::sin(shoulder)
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

#[cfg(test)]
#[allow(dead_code)]
mod tests {
    #[allow(unused_imports)]
    use super::*;

    const EPS: f64 = 1.0e-6;

    fn assert_close(left: f64, right: f64) {
        assert!(
            (left - right).abs() <= EPS,
            "left={left} right={right} diff={}",
            (left - right).abs()
        );
    }

    #[test]
    fn fk_straight_forward_pose_maps_to_negative_x_extent() {
        let (x, y, z) = fk(0.0, 0.0, 0.0, 0.0);
        assert_close(x, -432.0);
        assert_close(y, 0.0);
        assert_close(z, 0.0);
    }

    #[test]
    fn fk_tip_down_pose_adds_tool_height_in_z() {
        let (x, y, z) = fk(0.0, 0.0, 0.0, PI / 2.0);
        assert_close(x, -302.0);
        assert_close(y, 0.0);
        assert_close(z, -130.0);
    }

    #[test]
    fn ik_straight_reach_along_x_uses_roboband_yaw_convention() {
        let result = ik(ARM_L1_MM + ARM_L2_MM, 0.0, -ARM_L3_MM);
        assert!(result.reachable);
        assert_close(result.yaw, PI);
        assert_close(result.shoulder, 0.0);
        assert_close(result.elbow, 0.0);
    }

    #[test]
    fn ik_target_along_positive_y_has_positive_half_pi_yaw() {
        let result = ik(0.0, ARM_L1_MM + ARM_L2_MM, -ARM_L3_MM);
        assert!(result.reachable);
        assert_close(result.yaw, PI / 2.0);
    }

    #[test]
    fn ik_fk_round_trip_for_reachable_target() {
        let result = ik(200.0, 0.0, 0.0);
        assert!(result.reachable);
        let (x, y, z) = fk(
            result.yaw,
            result.shoulder,
            result.elbow,
            solve_tip_angle_down(result.shoulder, result.elbow, ARM_TOOL_PHI_RAD),
        );
        assert_close(x, 200.0);
        assert_close(y, 0.0);
        assert_close(z, 0.0);
    }

    #[test]
    fn solve_coords_with_tool_pitch_round_trips_requested_pose() {
        let tool_phi = -PI / 4.0;
        let (yaw, shoulder, elbow, wrist) =
            solve_coords_with_tool_pitch(180.0, 40.0, 20.0, tool_phi).unwrap();
        let (x, y, z) = fk(yaw, shoulder, elbow, wrist);
        assert_close(x, 180.0);
        assert_close(y, 40.0);
        assert_close(z, 20.0);
        assert_close(wrap_pi(shoulder - elbow - wrist), tool_phi);
    }

    #[test]
    fn solve_coords_rejects_unreachable_target() {
        assert_eq!(
            solve_coords_tool_down(ARM_L1_MM + ARM_L2_MM + 500.0, 0.0, 0.0),
            Err(IkError::Unreachable)
        );
    }
}
