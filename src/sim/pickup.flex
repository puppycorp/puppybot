import "vision.flex";
import "localization.flex";
import "camera.flex";
import "../runtime/server.flex";
import "../gym/plant.flex";

global ps_pickup_stage = 0;
global ps_pickup_steps = 0;
global ps_pickup_stable = 0;
global ps_pickup_release = 0;
global ps_pickup_reason = 0;
global ps_pickup_ball = 0;
global ps_pickup_targets = 0;
global ps_pickup_passed = 0;

fn ps_pickup_name() {
    if ps_pickup_stage == 1 { return "settling"; } if ps_pickup_stage == 2 { return "approaching"; }
    if ps_pickup_stage == 3 { return "hovering"; } if ps_pickup_stage == 4 { return "lowering"; }
    if ps_pickup_stage == 5 { return "closing"; } if ps_pickup_stage == 6 { return "lifting"; }
    if ps_pickup_stage == 7 { return "holding"; } if ps_pickup_stage == 8 { return "releasing"; }
    if ps_pickup_stage == 9 { return "released"; } if ps_pickup_stage == 10 { return "failed"; } return "idle";
}
fn ps_pickup_running() { return ps_pickup_stage > 0 && ps_pickup_stage < 7; }
fn ps_pickup_phase(stage) { ps_pickup_stage = stage; ps_pickup_steps = 0; ps_pickup_stable = 0; return 0; }
fn ps_pickup_cancel(reason) {
    if ps_pickup_stage { ps_pickup_reason = reason; ps_pickup_phase(0); pr_stop(ps_app, ps_time); } return 0;
}
fn ps_pickup_fail(reason) {
    pl_print(2, "Pickup failed: "); pl_print(2, reason); pl_print(2, "\n");
    ps_pickup_passed = 0; ps_pickup_reason = reason; ps_pickup_phase(10); pr_stop(ps_app, ps_time); return 0;
}
fn ps_pickup_start(release) {
    if !ps_pickup_ball { ps_pickup_ball = alloc(24); ps_pickup_targets = alloc(32); }
    ps_pickup_passed = 0; ps_pickup_release = release; ps_pickup_reason = "running"; ps_gripper_command(1); ps_pickup_phase(1);
    if ps_vision_requested && !ps_camera_drive_target() { return ps_pickup_fail("cannot aim the TCP camera for driving"); } return 0;
}
fn ps_arm_solve_at(point, height, pitch, x, y, heading) {
    // Transform a world TCP target into the controller's calibrated arm frame.
    // Frame translation/yaw are packed from the model profile at build time.
    let frame = ps_asset + 64 + ps_groups * 256 + 24;
    let dx = f64_sub(load64(point), x); let dy = f64_sub(load64(point + 8), y);
    let c = f64_cos(heading); let s = f64_sin(heading);
    let bx = f64_sub(f64_add(f64_mul(c, dx), f64_mul(s, dy)), load64(frame));
    let by = f64_sub(f64_sub(f64_mul(c, dy), f64_mul(s, dx)), load64(frame + 8));
    let az = f64_sub(f64_sub(ps_number(height, 1000), ps_number(32, 1000)), load64(frame + 16));
    c = f64_cos(load64(frame + 40)); s = f64_sin(load64(frame + 40));
    let ax = f64_add(f64_mul(c, bx), f64_mul(s, by)); let ay = f64_sub(f64_mul(c, by), f64_mul(s, bx));
    // Simulation poses specify finger pitch: 0 down, 90 forward. The arm's
    // calibrated tool segment instead measures 0 forward, -90 down.
    let tool_pitch = pb_radians(f64_from_i64(pitch - 90));
    let error = pb_nearest_branch(ps_robot, ps_trace + 1024, f64_mul(ax, f64_from_i64(1000)), f64_mul(ay, f64_from_i64(1000)), f64_mul(az, f64_from_i64(1000)), tool_pitch, 0);
    if error { return 0; }
    pb_angles_ticks(ps_robot, ps_pickup_targets, ps_trace + 1024, 1); return 1;
}
fn ps_arm_solve(point, height, pitch) {
    return ps_arm_solve_at(point, height, pitch, ps_pose_x(), ps_pose_y(), ps_pose_heading());
}
fn ps_arm_move_ticks() {
    let maximum = 0; let i = 0;
    while i < 4 {
        let j = pb_joint(ps_robot, i); let current = load64(ps_plant + 128 + i * 64 + 16); let target = load64(ps_pickup_targets + i * 8);
        let error = pb_target_error(target, current); if pb_j(j, PB_J_LIMIT_ENABLED) { error = pb_limited_error(j, target, current); }
        maximum = pb_max(maximum, pb_abs(error)); i = i + 1;
    }
    return maximum;
}
fn ps_arm_move_timeout() {
    // The position controller uses ticks/second. Allow the commanded travel
    // plus five seconds for acceleration, limit slowdown and settled feedback.
    let speed = pb_max(1, pb_abs(pb_a(pb_robot_arm(ps_robot), PB_A_SPEED)));
    return pb_clamp((ps_arm_move_ticks() * 50 + speed - 1) / speed + 250, 1000, 1500);
}
fn ps_arm_target(point, height, pitch) {
    if !ps_arm_solve(point, height, pitch) { return 0; }
    if pr_apply(ps_app, 5, ps_pickup_targets, ps_time) { return 0; } ps_camera_drive_mode = 0; return 1;
}
fn ps_pickup_target(height, pitch) {
    if !ps_arm_target(ps_pickup_ball, height, pitch) { return ps_pickup_fail("pickup pose exceeds calibrated arm reach or joint limits"); } return 1;
}
fn ps_pickup_settled() {
    if gs_reached(ps_plant, ps_pickup_targets) && gs_stopped(ps_plant) { ps_pickup_stable = ps_pickup_stable + 1; }
    else { ps_pickup_stable = 0; }
    return ps_pickup_stable >= 15;
}
fn ps_pickup_update() {
    if !ps_pickup_stage || ps_pickup_stage >= 9 { return 1; } ps_pickup_steps = ps_pickup_steps + 1;
    if ps_pickup_stage != 7 && ps_pickup_steps > 750 { return ps_pickup_fail("pickup phase timed out"); }
    if ps_pickup_stage == 1 && ps_pickup_steps >= 50 {
        if ps_vision_requested && !ps_pickup_settled() { return 1; }
        if ps_vision_requested {
            if !ps_vision_observe(ps_pickup_ball) { return ps_pickup_fail(ps_vision_reason); }
        } else {
            let ball = ph_body(ps_physics, 3); let i = 0; while i < 3 { pb_vset(ps_pickup_ball, i, pb_f32_to_f64(pb_vget(ball + 8, i))); i = i + 1; }
            if f64_gt(f64_magnitude(f64_sub(load64(ps_pickup_ball + 16), ps_number(35, 1000))), ps_number(2, 1000)) { return ps_pickup_fail("ball has not settled on the floor"); }
        }
        let values = ps_trace + 1024; store64(values, 220); pr_apply(ps_app, 1, values, ps_time); ps_pickup_phase(2);
    }
    else if ps_pickup_stage == 2 {
        if ps_blocked { return ps_pickup_fail("chassis approach is blocked"); }
        let remaining = f64_sub(f64_sub(load64(ps_pickup_ball), ps_number(20, 100)), ps_x);
        if f64_gt(remaining, ps_number(1, 1000)) { pb_drive_steer(pb_robot_drive(ps_robot), 20, 0, ps_time); }
        else { pb_drive_stop(pb_robot_drive(ps_robot), ps_time); if !ps_pickup_target(140, 20) { return 0; } ps_pickup_phase(3); }
    }
    else if ps_pickup_stage == 3 && ps_pickup_settled() { if !ps_pickup_target(80, 0) { return 0; } ps_pickup_phase(4); }
    else if ps_pickup_stage == 4 && ps_pickup_settled() { ps_gripper_command(0); ps_pickup_phase(5); }
    else if ps_pickup_stage == 5 {
        if ps_gripper_held { if !ps_pickup_target(180, 40) { return 0; } ps_pickup_phase(6); }
        else if ps_pickup_steps > 200 { return ps_pickup_fail("both fingers did not contact the ball while closing"); }
    }
    else if ps_pickup_stage == 6 {
        if !ps_gripper_held { return ps_pickup_fail("grasp was lost during lift"); }
        if ps_pickup_settled() {
            if ph_lt(load64(ph_body(ps_physics, 3) + 24), ps_float(10, 100)) { return ps_pickup_fail("ball did not clear the floor by 65 mm"); }
            ps_pickup_phase(7);
        }
    }
    else if ps_pickup_stage == 7 {
        if !ps_gripper_held { return ps_pickup_fail("grasp was lost during hold"); }
        if ps_pickup_steps >= 50 { ps_pickup_passed = 1; ps_pickup_reason = "ball lifted and held"; }
        if ps_pickup_release && ps_pickup_steps >= 75 { ps_gripper_command(1); ps_pickup_phase(8); }
    }
    else if ps_pickup_stage == 8 && ps_pickup_steps >= 50 {
        let b = ph_body(ps_physics, 3);
        if ph_lt(ph_abs(ph_sub(load64(b + 24), ps_float(35, 1000))), ps_float(1, 1000)) && ph_lt(ph_abs(load64(b + 80)), ps_float(1, 100)) {
            ps_pickup_reason = "ball lifted, held and released to the floor"; ps_pickup_phase(9);
        }
    }
    return 1;
}
