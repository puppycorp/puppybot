// Command dead reckoning: initial configured pose, wheel-speed/steering
// commands and an independent seeded error model. Never correct from truth.
import "model.flex";

global ps_local_requested = -1;
global ps_local_mode = 0;
global ps_local_seed = 42;
global ps_local_random = 42;
global ps_local_drift = 10;
global ps_local_x = 0;
global ps_local_y = 0;
global ps_local_heading = 0;
global ps_local_distance = 0;
global ps_local_max_error = 0;
global ps_local_matrices = 0;
global ps_local_root = 0;
global ps_local_rotation = 0;
global ps_local_tcp = 0;
global ps_local_vectors = 0;
global ps_local_visual_x = 0;
global ps_local_visual_y = 0;
global ps_local_visual_heading = 0;

fn ps_pose_x() { if ps_local_mode { return ps_local_x; } return ps_x; }
fn ps_pose_y() { if ps_local_mode { return ps_local_y; } return ps_y; }
fn ps_pose_heading() { if ps_local_mode { return ps_local_heading; } return ps_heading; }
fn ps_local_reset() {
    ps_local_mode = ps_local_requested; if ps_local_mode < 0 { ps_local_mode = 2 * ps_house_enabled(); }
    if !ps_house_enabled() { ps_local_mode = 0; }
    ps_local_x = 0; ps_local_y = 0; ps_local_heading = 0; ps_local_distance = 0; ps_local_max_error = 0; ps_local_random = ps_local_seed;
    ps_local_visual_x = 0; ps_local_visual_y = 0; ps_local_visual_heading = 0;
    // This is a declared starting prior, not a read of the running world.
    if ps_environment { ps_local_x = load64(ps_environment_start); ps_local_y = load64(ps_environment_start + 8); ps_local_heading = load64(ps_environment_start + 16); }
    return 0;
}
fn ps_local_step() {
    ps_local_visual_x = 0; ps_local_visual_y = 0; ps_local_visual_heading = 0;
    if !ps_local_mode { return 0; }
    let d = pb_robot_drive(ps_robot); let distance = ps_number(load64(d + 48) + load64(d + 56), 20000);
    if !distance { return 0; } let steering = pb_radians(f64_from_i64(load64(d + 64) - load64(d + 24)));
    if ps_local_mode == 2 {
        ps_local_random = (ps_local_random * 1664525 + 1013904223) & 0xffffffff;
        let noise = ps_number(ps_local_random % 2001 - 1000, 1000); let drift = ps_number(ps_local_drift, 1000);
        distance = f64_mul(distance, f64_add(PB_ONE, f64_mul(drift, f64_add(PB_ONE, f64_mul(noise, ps_number(1, 5))))));
        steering = f64_add(steering, pb_radians(ps_number(ps_local_drift, 50)));
    }
    let turn = pb_neg(f64_mul(f64_div(distance, ps_number(18, 100)), f64_div(f64_sin(steering), f64_cos(steering))));
    ps_local_heading = pb_wrap_pi(f64_add(ps_local_heading, turn));
    ps_local_x = f64_add(ps_local_x, f64_mul(distance, f64_cos(ps_local_heading))); ps_local_y = f64_add(ps_local_y, f64_mul(distance, f64_sin(ps_local_heading)));
    ps_local_distance = f64_add(ps_local_distance, f64_magnitude(distance)); return 0;
}
fn ps_local_kinematics() {
    if !ps_local_matrices {
        ps_local_matrices = alloc(ps_groups * 128); ps_local_root = alloc(128); ps_local_rotation = alloc(128); ps_local_tcp = alloc(24); ps_local_vectors = alloc(144);
    }
    return ps_model_evaluate(ps_robot, ps_plant, ps_pose_x(), ps_pose_y(), ps_pose_heading(), 0, ps_local_matrices, ps_local_root, ps_local_rotation, ps_local_tcp);
}
fn ps_local_camera(out) {
    ps_local_kinematics(); let eye = ps_local_vectors; let target = eye + 24; let up = target + 24; let forward = up + 24; let right = forward + 24; let down = right + 24;
    pb_zero(eye, 144); store64(up + 16, 1000000);
    let yaw = f64_add(f64_add(ps_pose_heading(), load64(ps_asset + 64 + ps_groups * 256 + 64)), pb_geometric_yaw(ps_joint_angle(ps_robot, ps_plant, 0)));
    let pitch = pb_tool_pitch(ps_joint_angle(ps_robot, ps_plant, 1), ps_joint_angle(ps_robot, ps_plant, 2), ps_joint_angle(ps_robot, ps_plant, 3));
    let i = 0;
    while i < 3 {
        let radial = f64_cos(yaw); if i == 1 { radial = f64_sin(yaw); }
        let y = f64_mul(radial, f64_cos(pitch)); let z = f64_mul(radial, f64_sin(pitch)); if i == 2 { y = f64_sin(pitch); z = pb_neg(f64_cos(pitch)); }
        let origin = f64_mul(load64(ps_local_tcp + i * 8), f64_from_i64(1000));
        store64(eye + i * 8, f64_to_i64_nearest(f64_sub(f64_add(origin, f64_mul(y, f64_from_i64(65))), f64_mul(z, f64_from_i64(65)))));
        let look = f64_to_i64_nearest(f64_add(origin, f64_mul(z, f64_from_i64(65))));
        store64(target + i * 8, load64(eye + i * 8) + (look - load64(eye + i * 8)) * 1000);
        let sign = -1000000; if ps_camera_drive_mode { sign = 1000000; }
        store64(up + i * 8, f64_to_i64_nearest(f64_mul(y, f64_from_i64(sign)))); i = i + 1;
    }
    i = 0; while i < 3 { store64(forward + i * 8, load64(target + i * 8) - load64(eye + i * 8)); i = i + 1; }
    render_normalize(forward); render_cross(right, forward, up); render_normalize(right); render_cross(down, right, forward); i = 0;
    while i < 3 {
        store64(out + i * 8, ps_number(load64(eye + i * 8), 1000)); store64(out + 24 + i * 8, ps_number(load64(forward + i * 8), 1000000));
        store64(out + 48 + i * 8, ps_number(load64(right + i * 8), 1000000)); store64(out + 72 + i * 8, ps_number(-load64(down + i * 8), 1000000)); i = i + 1;
    }
    return 1;
}
fn ps_local_observation(b) {
    if !ps_house_enabled() && !ps_local_mode { return 0; }
    pl_text(b, ",\"localization\":{\"mode\":"); let mode = "oracle"; if ps_local_mode == 1 { mode = "wheel"; } if ps_local_mode == 2 { mode = "wheel-drift"; } pj_text(b, mode);
    pl_text(b, ",\"source\":"); if ps_crumb_enabled { pj_text(b, "wheel-steering-and-tcp-rgb-features"); } else if ps_local_mode { pj_text(b, "wheel-steering-command-integration"); } else { pj_text(b, "simulator-truth"); }
    pl_text(b, ",\"initialPrior\":\"configured-spawn\",\"cameraCalibration\":"); if ps_local_mode { pj_text(b, "estimated-base-and-joint-feedback"); } else { pj_text(b, "simulator-truth"); }
    pl_text(b, ",\"pose\":["); pl_float(b, ps_pose_x()); pl_char(b, 44); pl_float(b, ps_pose_y()); pl_char(b, 44); pl_float(b, ps_pose_heading());
    pl_text(b, "],\"seed\":"); pl_int(b, ps_local_seed); pl_text(b, ",\"driftPermille\":"); pl_int(b, ps_local_drift * (ps_local_mode == 2));
    pl_text(b, ",\"estimatedDistanceM\":"); pl_float(b, ps_local_distance);
    // Evaluation only. Nothing above this function reads the live true pose
    // in either wheel mode; the controller never consumes these error fields.
    let dx = f64_sub(ps_pose_x(), ps_x); let dy = f64_sub(ps_pose_y(), ps_y); let error = f64_sqrt(f64_add(f64_mul(dx, dx), f64_mul(dy, dy)));
    ps_local_max_error = pb_fmax(ps_local_max_error, error);
    pl_text(b, ",\"evaluation\":{\"positionErrorM\":"); pl_float(b, error); pl_text(b, ",\"maxPositionErrorM\":"); pl_float(b, ps_local_max_error);
    pl_text(b, ",\"headingErrorRad\":"); pl_float(b, pb_wrap_pi(f64_sub(ps_pose_heading(), ps_heading))); return pl_text(b, "}}");
}
