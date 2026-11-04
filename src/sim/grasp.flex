// Grasp-centre IK for the straight wrist mount. Targets are camera estimates;
// tool geometry and joint limits come from the robot, never the floorplan.
import "pickup.flex";

global ps_grasp_tcp = 0;
global ps_grasp_pitch = 0;

fn ps_grasp_solve_at(point, lift, pitch, x, y, heading) {
    if !ps_grasp_tcp { ps_grasp_tcp = alloc(24); }
    let angle = pb_radians(f64_from_i64(pitch)); let offset = ps_grasp_offset();
    let reach = f64_mul(offset, f64_sin(angle));
    // Grip slightly above the brick centre so the pads clear the floor.
    let height = f64_to_i64_nearest(f64_mul(f64_add(load64(point + 16), f64_add(ps_number(16 + lift, 1000), f64_mul(offset, f64_cos(angle)))), f64_from_i64(1000)));
    let yaw = f64_atan2(f64_sub(load64(point + 8), y), f64_sub(load64(point), x)); let i = 0;
    while i < 6 {
        store64(ps_grasp_tcp, f64_sub(load64(point), f64_mul(reach, f64_cos(yaw))));
        store64(ps_grasp_tcp + 8, f64_sub(load64(point + 8), f64_mul(reach, f64_sin(yaw)))); store64(ps_grasp_tcp + 16, ps_number(height, 1000));
        if !ps_arm_solve_at(ps_grasp_tcp, height, pitch, x, y, heading) { return 0; }
        yaw = f64_add(f64_add(heading, load64(ps_asset + 64 + ps_groups * 256 + 64)), pb_geometric_yaw(pb_tick_angle(pb_joint(ps_robot, 0), load64(ps_pickup_targets)))); i = i + 1;
    }
    ps_grasp_pitch = pitch; return 1;
}
fn ps_grasp_solve(point, lift, pitch) { return ps_grasp_solve_at(point, lift, pitch, ps_pose_x(), ps_pose_y(), ps_pose_heading()); }
fn ps_grasp_move(point, lift, pitch) {
    if !ps_grasp_solve(point, lift, pitch) || pr_apply(ps_app, 5, ps_pickup_targets, ps_time) { return 0; }
    ps_camera_drive_mode = 0; ps_pickup_stable = 0; return 1;
}
