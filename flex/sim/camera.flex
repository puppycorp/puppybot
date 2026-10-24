// One fixed wrist sensor. Driving and inspection move the real arm, not the
// camera mount or a virtual front-camera calibration.
global ps_camera_drive_mode = 0;
global ps_camera_drive_point = 0;

fn ps_camera_drive_target() {
    if !ps_pickup_targets { ps_pickup_targets = alloc(32); }
    if !ps_camera_drive_point { ps_camera_drive_point = alloc(24); }
    let c = f64_cos(ps_pose_heading()); let s = f64_sin(ps_pose_heading());
    store64(ps_camera_drive_point, f64_add(ps_pose_x(), f64_add(f64_mul(c, ps_number(18, 100)), f64_mul(s, ps_number(4, 100)))));
    store64(ps_camera_drive_point + 8, f64_add(ps_pose_y(), f64_sub(f64_mul(s, ps_number(18, 100)), f64_mul(c, ps_number(4, 100))))); store64(ps_camera_drive_point + 16, 0);
    if !ps_arm_target(ps_camera_drive_point, 180, 90) { return 0; }
    ps_camera_drive_mode = 1; ps_pickup_stable = 0; return 1;
}
fn ps_camera_still() {
    if !gs_stopped(ps_plant) { return 0; } let i = 0;
    while i < 4 { if load64(ps_plant + 128 + i * 64 + 8) { return 0; } i = i + 1; } return 1;
}
fn ps_camera_observation(b) {
    pl_text(b, ",\"camera\":{\"sensor\":\"tcp\",\"pose\":"); if ps_camera_drive_mode { pj_text(b, "driving"); } else { pj_text(b, "inspection"); }
    pl_text(b, ",\"imageRotationDeg\":"); pl_int(b, 180 * ps_camera_drive_mode);
    pl_text(b, ",\"armSettled\":"); pj_bool_text(b, ps_camera_still()); return pl_char(b, 125);
}
