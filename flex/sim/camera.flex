// One fixed wrist sensor. Driving and inspection move the real arm, not the
// camera mount or a virtual front-camera calibration.
global ps_camera_drive_mode = 0;
global ps_camera_drive_point = 0;

fn ps_camera_compact_point(point, angle, radial) {
    let frame = ps_asset + 64 + ps_groups * 256 + 24; let c = f64_cos(ps_pose_heading()); let s = f64_sin(ps_pose_heading());
    let x = f64_add(ps_pose_x(), f64_sub(f64_mul(c, load64(frame)), f64_mul(s, load64(frame + 8))));
    let y = f64_add(ps_pose_y(), f64_add(f64_mul(s, load64(frame)), f64_mul(c, load64(frame + 8))));
    let lateral = f64_div(pb_arm_lateral_offset(), f64_from_i64(1000)); c = f64_cos(angle); s = f64_sin(angle);
    store64(point, f64_add(x, f64_sub(f64_mul(c, radial), f64_mul(s, lateral))));
    store64(point + 8, f64_add(y, f64_add(f64_mul(s, radial), f64_mul(c, lateral)))); store64(point + 16, 0); return 1;
}
fn ps_camera_compact_target() {
    if !ps_pickup_targets { ps_pickup_targets = alloc(32); } if !ps_camera_drive_point { ps_camera_drive_point = alloc(24); }
    ps_camera_compact_point(ps_camera_drive_point, ps_pose_heading(), ps_number(16, 1000));
    if !ps_arm_target(ps_camera_drive_point, 370, 75) { return 0; } ps_camera_drive_mode = 1; ps_pickup_stable = 0; return 1;
}
fn ps_camera_drive_solve(raised) {
    if !ps_pickup_targets { ps_pickup_targets = alloc(32); }
    if !ps_camera_drive_point { ps_camera_drive_point = alloc(24); }
    let reach = ps_number(22, 100); let height = 80; let pitch = 90;
    // Keep a payload on the open side of the forearm. The low empty pose
    // requires a wrist sweep through the forearm when a brick is attached.
    if raised { reach = ps_number(18, 100); height = 370; pitch = 65; }
    let c = f64_cos(ps_pose_heading()); let s = f64_sin(ps_pose_heading());
    store64(ps_camera_drive_point, f64_add(ps_pose_x(), f64_add(f64_mul(c, reach), f64_mul(s, ps_number(4, 100)))));
    store64(ps_camera_drive_point + 8, f64_add(ps_pose_y(), f64_sub(f64_mul(s, reach), f64_mul(c, ps_number(4, 100))))); store64(ps_camera_drive_point + 16, 0);
    return ps_arm_solve(ps_camera_drive_point, height, pitch);
}
fn ps_camera_drive_pose(raised) {
    if !ps_camera_drive_solve(raised) || pr_apply(ps_app, 5, ps_pickup_targets, ps_time) { return 0; }
    ps_camera_drive_mode = 1; ps_pickup_stable = 0; return 1;
}
fn ps_camera_drive_target() {
    if ps_discovery_enabled && !ps_gripper_held { return ps_camera_compact_target(); }
    return ps_camera_drive_pose(ps_gripper_held);
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
