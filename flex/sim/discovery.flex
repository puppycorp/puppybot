// Unknown-space exploration. The perception worker receives only wrist RGB,
// encoder-derived robot/camera geometry and a local wheel/visual odometry pose. World
// geometry is used by the renderer and physical guard, never this controller.
import "navigation.flex";

global ps_discovery_enabled = 0;
global ps_discovery_root = 0;
global ps_discovery_directory = 0;
global ps_discovery_initialized = 0;
global ps_discovery_phase = 0;
global ps_discovery_reason = 0;
global ps_discovery_sector = 0;
global ps_discovery_side = 0;
global ps_discovery_tilt = 0;
global ps_discovery_full = 1;
global ps_discovery_scans = 0;
global ps_discovery_limit = 12;
global ps_discovery_samples = 0;
global ps_discovery_frames = 0;
global ps_discovery_left = 0;
global ps_discovery_right = 0;
global ps_discovery_goals = 0;
global ps_discovery_goal_count = 0;
global ps_discovery_job = 0;
global ps_discovery_started = 0;
global ps_discovery_timeout = 1000;
global ps_discovery_distance = 0;
global ps_discovery_free = 0;
global ps_discovery_occupied = 0;
global ps_discovery_safe = 0;
global ps_discovery_stops = 0;
global ps_discovery_observed = 0;
global ps_discovery_detail = 0;
global ps_discovery_detail_ready = 0;
global ps_discovery_frame_id = 0;
global ps_discovery_map_frame = 0;
global ps_discovery_height = 0;
global ps_discovery_pitch = 0;
global ps_discovery_bearing = 0;
global ps_discovery_arm_stops = 0;
global ps_discovery_skip_view = 0;
global ps_discovery_left_step = 0;
global ps_discovery_focus = 0;
global ps_discovery_focus_valid = 0;
global ps_discovery_scan_recorded = 0;
global ps_discovery_robot = 0;
global ps_discovery_robot_scratch = 0;
global ps_discovery_pending = 0;
global ps_discovery_tuck = 0;
global ps_discovery_pending_phase = 0;
global ps_discovery_pending_turn = 0;
global ps_discovery_retries = 0;
global ps_discovery_failed_goals = 0;
global ps_discovery_failed_count = 0;
global ps_discovery_failed_next = 0;
global ps_discovery_bad_poses = 0;
global ps_discovery_bad_count = 0;
global ps_discovery_bad_next = 0;
global ps_discovery_raised_only = 0;
global ps_discovery_rescans = 0;
global ps_discovery_motion = 0;
global ps_discovery_motion_count = 0;
global ps_discovery_motion_next = 0;
global ps_discovery_motion_step = -1;
global ps_discovery_retrace = 0;
global ps_discovery_retrace_issued = 0;
global ps_discovery_escape_poses = 0;
global ps_discovery_escape_count = 0;
global ps_discovery_escape_next = 0;

fn ps_discovery_motion_clear() {
    ps_discovery_motion_count = 0; ps_discovery_motion_next = 0; ps_discovery_motion_step = ps_total;
    ps_discovery_retrace = 0; ps_discovery_retrace_issued = 0; return 1;
}

fn ps_discovery_finish(reason, failed) {
    if ps_discovery_job { h_stop(ps_discovery_job); ps_discovery_job = 0; }
    if ps_collect_enabled && !ps_case_passed { failed = 1; }
    if ps_collect_enabled && failed && ps_case_stage != 13 { ps_case_fail(reason); }
    pb_drive_stop(pb_robot_drive(ps_robot), ps_time); ps_discovery_reason = reason; ps_discovery_phase = 6 + failed; return 0;
}
fn ps_discovery_reset() {
    if ps_discovery_job { h_stop(ps_discovery_job); ps_discovery_job = 0; }
    if !ps_discovery_failed_goals { ps_discovery_failed_goals = alloc(16 * 16); } ps_discovery_failed_count = 0; ps_discovery_failed_next = 0;
    ps_discovery_phase = 1; ps_discovery_sector = 0; ps_discovery_side = 0; ps_discovery_tilt = 0; ps_discovery_full = 1; ps_discovery_scans = 0; ps_discovery_samples = 0; ps_discovery_rescans = 0;
    if !ps_discovery_motion { ps_discovery_motion = alloc(64 * 48); } ps_discovery_motion_clear();
    if !ps_discovery_escape_poses { ps_discovery_escape_poses = alloc(16 * 16); } ps_discovery_escape_count = 0; ps_discovery_escape_next = 0;
    ps_discovery_free = 0; ps_discovery_occupied = 0; ps_discovery_safe = 0; ps_discovery_stops = 0; ps_discovery_goal_count = 0; ps_discovery_directory = 0; ps_discovery_map_frame = 0; ps_discovery_detail_ready = 0;
    if !ps_discovery_detail { ps_discovery_detail = alloc(1000000); }
    ps_discovery_reason = "scanning unknown space"; ps_crumb_recording = 1; ps_discovery_arm_stops = 0; ps_discovery_skip_view = 0; ps_discovery_focus_valid = 0; ps_discovery_scan_recorded = 0; ps_discovery_pending_phase = 0; ps_discovery_pending_turn = 0; ps_discovery_bad_count = 0; ps_discovery_bad_next = 0;
    if !ps_discovery_frames { ps_discovery_frames = alloc(192); ps_discovery_goals = alloc(8 * 24); ps_discovery_robot = alloc((ps_arm_collider_count + 5) * 240); ps_discovery_robot_scratch = alloc(224); ps_discovery_pending = alloc(32); ps_discovery_tuck = alloc(32); ps_discovery_bad_poses = alloc(16 * 16); }
    if !ps_pickup_targets { ps_pickup_targets = alloc(32); }
    return ps_nav_init();
}
fn ps_discovery_frontier_focus(point) {
    if !ps_discovery_focus { ps_discovery_focus = alloc(24); }
    store64(ps_discovery_focus, f64_add(load64(point), f64_mul(ps_number(4, 10), f64_cos(load64(point + 16)))));
    store64(ps_discovery_focus + 8, f64_add(load64(point + 8), f64_mul(ps_number(4, 10), f64_sin(load64(point + 16)))));
    store64(ps_discovery_focus + 16, 0); ps_discovery_focus_valid = 1; return 1;
}
fn ps_discovery_scan_bearing() {
    let target = ps_collect_attention(); if !target && ps_discovery_focus_valid { target = ps_discovery_focus; }
    if target { return f64_atan2(f64_sub(load64(target + 8), ps_pose_y()), f64_sub(load64(target), ps_pose_x())); }
    return ps_pose_heading();
}
fn ps_discovery_aim_solve(height, pitch, side) {
    let turn = (ps_discovery_sector + 1) / 2; if !(ps_discovery_sector % 2) { turn = -turn; }
    let angle = f64_add(ps_discovery_bearing, f64_mul(PB_TAU, ps_number(turn, 8)));
    // Translate radially with a fixed yaw, above the rover. The fingers stay
    // close to its footprint while the camera looks out into unknown space.
    let point = ps_trace + 1024;
    let radial = 11 + side * 50; if ps_discovery_raised_only { radial = 6 + side * 35; }
    ps_camera_compact_point(point, angle, ps_number(radial, 1000));
    if !ps_arm_solve(point, height, pitch) { return 0; }
    // A reachable negative-radius IK branch looks in the opposite direction.
    // Both stereo endpoints must retain the requested optical bearing.
    let frame = ps_asset + 64 + ps_groups * 256 + 24;
    let yaw = f64_add(f64_add(pb_geometric_yaw(load64(ps_trace + 1024)), load64(frame + 40)), ps_pose_heading());
    return f64_lt(f64_magnitude(pb_wrap_pi(f64_sub(yaw, angle))), ps_number(1, 100));
}
fn ps_discovery_apply(phase) {
    ps_discovery_retries = 0; ps_discovery_timeout = ps_arm_move_timeout(); ps_discovery_started = ps_total;
    if pr_apply(ps_app, 5, ps_pickup_targets, ps_time) { return 0; }
    ps_camera_drive_mode = phase == 4; ps_pickup_stable = 0; ps_discovery_phase = phase; return 1;
}
fn ps_discovery_settled() {
    if ps_pickup_settled() { return 1; }
    // Serialized feedback can clear a target within the controller's eight
    // tick band, then coast one tick beyond it. Correct that final tick with
    // a real command rather than accepting a looser camera pose tolerance.
    if ps_camera_still() && !pb_a(ps_robot, PB_A_MODE) && !gs_reached(ps_plant, ps_pickup_targets) {
        ps_discovery_retries = ps_discovery_retries + 1;
        if ps_discovery_retries > 3 || pr_apply(ps_app, 5, ps_pickup_targets, ps_time) { return ps_discovery_finish("mapping arm did not reach its calibrated target", 1); }
    } return 0;
}
fn ps_discovery_pose_allowed(x, y) {
    let i = 0; while i < ps_discovery_bad_count { let p = ps_discovery_bad_poses + i * 16;
        let dx = f64_sub(x, load64(p)); let dy = f64_sub(y, load64(p + 8));
        if f64_lt(f64_add(f64_mul(dx, dx), f64_mul(dy, dy)), ps_number(9, 100)) { return 0; } i = i + 1;
    } return 1;
}
fn ps_discovery_frontier_allowed(x, y) {
    if !ps_discovery_pose_allowed(x, y) { return 0; } let i = 0;
    while i < ps_discovery_failed_count { let p = ps_discovery_failed_goals + i * 16;
        let dx = f64_sub(x, load64(p)); let dy = f64_sub(y, load64(p + 8));
        if f64_lt(f64_add(f64_mul(dx, dx), f64_mul(dy, dy)), ps_number(9, 100)) { return 0; } i = i + 1;
    } return 1;
}
fn ps_discovery_frontier_failed() {
    // A stopped approach must not select the same frontier again after its
    // next scan. Remember only the selected goal in our local map, never the
    // obstacle that stopped us. Other routes and pickup parking remain usable.
    if ps_gripper_held || ps_collect_busy || ps_discovery_retrace || !ps_nav_path_count || !ps_discovery_frontier_allowed(load64(ps_nav_goal), load64(ps_nav_goal + 8)) { return 0; }
    let p = ps_discovery_failed_goals + (ps_discovery_failed_next % 16) * 16; ps_discovery_failed_next = ps_discovery_failed_next + 1;
    store64(p, load64(ps_nav_goal)); store64(p + 8, load64(ps_nav_goal + 8)); ps_discovery_failed_count = pb_min(16, ps_discovery_failed_count + 1); return 1;
}
fn ps_discovery_box_reach(box, c, s, origin) {
    let reach = f64_sub(f64_add(f64_mul(c, load64(box)), f64_mul(s, load64(box + 8))), origin); let axis = 0;
    while axis < 3 {
        let projection = f64_add(f64_mul(c, load64(box + 24 + axis * 24)), f64_mul(s, load64(box + 32 + axis * 24)));
        reach = f64_add(reach, f64_mul(f64_magnitude(projection), load64(box + 96 + axis * 8))); axis = axis + 1;
    } return reach;
}
fn ps_discovery_elbow_first() {
    // Choose from the actual encoder-derived envelope, including finger
    // extension. Pitch alone cannot distinguish a near view from a far one.
    ps_discovery_robot_frame(0);
    let yaw = f64_add(f64_add(ps_pose_heading(), load64(ps_asset + 64 + ps_groups * 256 + 64)), pb_geometric_yaw(ps_joint_angle(ps_robot, ps_plant, 0)));
    let c = f64_cos(yaw); let s = f64_sin(yaw); let point = ps_discovery_robot_scratch; ps_camera_compact_point(point, yaw, 0);
    let origin = f64_add(f64_mul(c, load64(point)), f64_mul(s, load64(point + 8))); let rear = 0; let front = 0; let i = 0;
    while i < ps_arm_collider_count {
        let group = load64(ps_arm_colliders + i * 56); let moving = 0;
        while group >= 0 {
            let row = ps_asset + 64 + group * 256; let control = load64(row + 8);
            if control >= 1 && control <= 3 { moving = 1; } group = load64(row);
        }
        if moving { rear = pb_fmax(rear, ps_discovery_box_reach(ps_discovery_robot + i * 120, pb_neg(c), pb_neg(s), pb_neg(origin))); } i = i + 1;
    }
    i = ps_arm_collider_count + 1;
    while i < ps_arm_collider_count + 4 { front = pb_fmax(front, ps_discovery_box_reach(ps_discovery_robot + i * 120, c, s, origin)); i = i + 1; }
    return f64_gt(front, rear);
}
fn ps_discovery_stage(phase) {
    // Retract the more exposed end first. Fingers use an elbow retreat;
    // the back of the empty forearm starts with the shoulder alone. A
    // simultaneous command can advance the elbow a tick before the shoulder.
    pb_copy(ps_discovery_pending, ps_pickup_targets, 32); let elbow_first = ps_discovery_elbow_first();
    let angle = f64_add(f64_add(ps_pose_heading(), load64(ps_asset + 64 + ps_groups * 256 + 64)), pb_geometric_yaw(ps_joint_angle(ps_robot, ps_plant, 0)));
    let point = ps_discovery_robot_scratch; ps_camera_compact_point(point, angle, ps_number(16, 1000));
    if !ps_arm_solve(point, 410, 85) { return 0; }
    let yaw = f64_add(f64_add(pb_geometric_yaw(load64(ps_trace + 1024)), load64(ps_asset + 64 + ps_groups * 256 + 64)), ps_pose_heading());
    if f64_gt(f64_magnitude(pb_wrap_pi(f64_sub(yaw, angle))), ps_number(1, 100)) { return 0; }
    store64(ps_pickup_targets, load64(ps_plant + 144)); pb_copy(ps_discovery_tuck, ps_pickup_targets, 32);
    ps_discovery_pending_phase = phase; ps_discovery_pending_turn = 1;
    if elbow_first {
        let i = 0; while i < 4 { store64(ps_pickup_targets + i * 8, load64(ps_plant + 144 + i * 64)); i = i + 1; }
        store64(ps_pickup_targets + 16, load64(ps_discovery_tuck + 16)); ps_discovery_pending_turn = 0;
    } else if !ps_gripper_held {
        let i = 0; while i < 4 { store64(ps_pickup_targets + i * 8, load64(ps_plant + 144 + i * 64)); i = i + 1; }
        store64(ps_pickup_targets + 8, load64(ps_discovery_tuck + 8)); ps_discovery_pending_turn = -1;
    }
    return ps_discovery_apply(0);
}
fn ps_discovery_motion_record() {
    // Called after the physical step, before choosing the next drive command.
    // Keep completed motion and its encoder posture, never a proposed route.
    if ps_discovery_motion_step == ps_total { return 0; } ps_discovery_motion_step = ps_total;
    if ps_blocked || ps_gripper_held || !ps_nav_heading_free() { return 0; }
    let d = pb_robot_drive(ps_robot); let speed = (load64(d + 48) + load64(d + 56)) / 2; if !speed { return 0; }
    let turn = load64(d + 64) - load64(d + 24);
    if load64(d + 48) != load64(d + 56) || speed < -60 || speed > 60 || (turn * 100) % 45 {
        ps_discovery_motion_clear(); return 0;
    }
    let r = ps_discovery_motion + (ps_discovery_motion_next % 64) * 48;
    store64(r, speed); store64(r + 8, turn * 100 / 45); let i = 0;
    while i < 4 { store64(r + 16 + i * 8, load64(ps_plant + 144 + i * 64)); i = i + 1; }
    ps_discovery_motion_next = ps_discovery_motion_next + 1; ps_discovery_motion_count = pb_min(64, ps_discovery_motion_count + 1); return 1;
}
fn ps_discovery_scan_after_motion(full) {
    pb_drive_stop(pb_robot_drive(ps_robot), ps_time); ps_discovery_sector = 0; ps_discovery_side = 0; ps_discovery_tilt = 0;
    ps_discovery_full = full; ps_discovery_rescans = 0; ps_discovery_phase = 1; return 1;
}
fn ps_discovery_protective_stop() {
    ps_discovery_frontier_failed(); ps_nav_contact_add(); ps_discovery_stops = ps_discovery_stops + 1; pb_drive_stop(pb_robot_drive(ps_robot), ps_time);
    if ps_discovery_stops > 12 { return ps_discovery_finish("protective stop budget reached", 1); } return 1;
}
fn ps_discovery_retrace_begin() {
    if !ps_discovery_motion_count || ps_gripper_held || !ps_nav_heading_free() { return 0; }
    // Return at most one primitive along the completed approach, then require
    // new stereo. A stopped rover already in that driving posture can back
    // away without first sweeping its wrist beside the stopped obstacle.
    ps_discovery_retrace = pb_min(20, ps_discovery_motion_count); ps_discovery_retrace_issued = 0;
    pb_copy(ps_pickup_targets, ps_discovery_motion + ((ps_discovery_motion_next - 1) % 64) * 48 + 16, 32);
    let matched = ps_camera_drive_mode && ps_camera_still() && !pb_a(ps_robot, PB_A_MODE); let i = 0;
    while i < 4 { if load64(ps_plant + 144 + i * 64) != load64(ps_pickup_targets + i * 8) { matched = 0; } i = i + 1; }
    if matched { ps_discovery_pending_phase = 0; ps_discovery_phase = 5; return 1; }
    if !ps_discovery_stage(4) { return ps_discovery_finish("cannot restore previous driving posture", 1); } return 1;
}
fn ps_discovery_retrace_tick() {
    if ps_blocked {
        let ok = ps_discovery_protective_stop(); ps_discovery_motion_clear();
        if !ok { return 0; } return ps_discovery_scan_after_motion(1);
    }
    if ps_discovery_retrace_issued {
        if ps_discovery_retrace_issued >= ps_total + 1 { return 1; }
        let last = ps_discovery_motion + ((ps_discovery_motion_next - 1) % 64) * 48; let drive = pb_robot_drive(ps_robot);
        if load64(drive + 48) != -load64(last) || load64(drive + 56) != -load64(last) || load64(drive + 64) != load64(drive + 24) + load64(last + 8) * 45 / 100 {
            ps_discovery_motion_clear(); return ps_discovery_scan_after_motion(1);
        }
        ps_discovery_motion_count = ps_discovery_motion_count - 1; ps_discovery_motion_next = ps_discovery_motion_next - 1;
        ps_discovery_retrace = ps_discovery_retrace - 1; ps_discovery_retrace_issued = 0;
    }
    if !ps_discovery_retrace { return ps_discovery_scan_after_motion(1); }
    let r = ps_discovery_motion + ((ps_discovery_motion_next - 1) % 64) * 48; let speed = -load64(r); let steering = load64(r + 8);
    let distance = ps_number(speed, 10000); let angle = pb_radians(f64_from_i64(steering * 45 / 100));
    let heading = pb_wrap_pi(f64_sub(ps_pose_heading(), f64_mul(f64_div(distance, ps_number(18, 100)), f64_div(f64_sin(angle), f64_cos(angle)))));
    let x = f64_add(ps_pose_x(), f64_mul(distance, f64_cos(heading))); let y = f64_add(ps_pose_y(), f64_mul(distance, f64_sin(heading)));
    // Completed commands and the restored encoder posture justify a
    // command-specific check here. Ordinary exploration keeps its broader
    // travel-direction exclusion; the same failed command remains forbidden.
    if !ps_nav_contact_clear_mode(x, y, heading, ps_pose_x(), ps_pose_y(), ps_pose_heading(), 2) {
        ps_discovery_motion_clear(); return ps_discovery_scan_after_motion(1);
    }
    // The old successful sweep supplies local free-space evidence here; no
    // unknown map cells are changed. The physical guard still checks every step.
    pb_drive_steer(pb_robot_drive(ps_robot), speed, steering, ps_time); ps_discovery_retrace_issued = ps_total + 1; return 1;
}
fn ps_discovery_aim() {
    if ps_discovery_raised_only { ps_discovery_tilt = 1; }
    if !ps_discovery_side {
        let pitch = 50 + ps_discovery_rescans * 5; let maximum = 65; let minimum_height = 370 + ps_discovery_rescans * 5; let maximum_height = 380; let step = 5;
        if ps_discovery_tilt { pitch = 65; step = -5; }
        if ps_discovery_raised_only { pitch = 90 + ps_discovery_rescans * 2; maximum = 95; minimum_height = 410 + ps_discovery_rescans * 2; maximum_height = 415; step = 5; }
        let found = 0;
        while pitch >= 50 && pitch <= maximum && !found { let height = minimum_height;
            while height <= maximum_height && !found {
                if ps_discovery_aim_solve(height, pitch, 0) && ps_discovery_aim_solve(height, pitch, 1) { ps_discovery_height = height; ps_discovery_pitch = pitch; found = 1; }
                height = height + 5;
            }
            pitch = pitch + step;
        }
        if !found { return 0; }
    }
    if !ps_discovery_aim_solve(ps_discovery_height, ps_discovery_pitch, ps_discovery_side) { return 0; }
    if !ps_discovery_side && (ps_discovery_raised_only || ps_collect_mapping) { return ps_discovery_stage(2); } return ps_discovery_apply(2);
}
fn ps_discovery_robot_box(out, m, centre, half) {
    ps_point(out, m, centre); let axis = 0;
    while axis < 3 { let row = 0;
        while row < 3 { store64(out + 24 + (axis * 3 + row) * 8, load64(m + (axis * 4 + row) * 8)); row = row + 1; }
        store64(out + 96 + axis * 8, load64(half + axis * 8)); axis = axis + 1;
    } return 1;
}
fn ps_discovery_robot_frame(side) {
    // Only known robot dimensions and encoder FK enter this self mask.
    // Scene collision boxes and live world transforms are never read.
    ps_local_kinematics(); let out = ps_discovery_robot + side * (ps_arm_collider_count + 5) * 120; let i = 0;
    while i < ps_arm_collider_count { let r = ps_arm_colliders + i * 56;
        ps_discovery_robot_box(out + i * 120, ps_local_matrices + load64(r) * 128, r + 8, r + 32); i = i + 1;
    }
    let centre = ps_discovery_robot_scratch; let half = centre + 24; let m = half + 24; pb_zero(centre, 48);
    store64(centre + 16, ps_number(58, 1000)); store64(half, ps_number(14, 100)); store64(half + 8, ps_number(11, 100)); store64(half + 16, ps_number(6, 100));
    ps_discovery_robot_box(out + i * 120, ps_local_root, centre, half); i = i + 1;
    ps_gripper_matrix(m, ps_local_tcp, ps_pose_heading(), ps_robot, ps_plant); let part = 0;
    while part < 3 {
        pb_zero(centre, 48); store64(half + 8, ps_number(15, 1000));
        if !part { store64(centre + 16, ps_number(-6, 1000)); store64(half, ps_number(55, 1000)); store64(half + 16, ps_number(6, 1000)); }
        else {
            let sign = -1; if part == 2 { sign = 1; }
            store64(centre, ps_number(sign * (ps_gripper_gap / 2 + 5000), 1000000)); store64(centre + 16, f64_mul(ps_finger_length(), ps_number(1, 2)));
            store64(half, ps_number(5, 1000)); store64(half + 16, load64(centre + 16));
        }
        ps_discovery_robot_box(out + i * 120, m, centre, half); part = part + 1; i = i + 1;
    }
    if ps_gripper_held {
        // Cover the known Lego size in any orientation around the grasp
        // estimate. Neither a held-body position nor its rotation is read.
        store64(half, ps_number(35, 1000)); store64(half + 8, ps_number(35, 1000)); store64(half + 16, ps_number(35, 1000));
        ps_discovery_robot_box(out + i * 120, m, ps_case_attachment, half);
    } return 1;
}
fn ps_discovery_frame_text(b, name, calibration) {
    pl_text(b, "{\"rgb\":"); pj_text(b, name); pl_text(b, ",\"frameId\":"); let frame = ps_total; if calibration == ps_discovery_frames { frame = ps_discovery_left_step; } pl_int(b, frame); pl_text(b, ",\"calibration\":["); let i = 0;
    while i < 12 { if i { pl_char(b, 44); } pl_float(b, load64(calibration + i * 8)); i = i + 1; } pl_text(b, "],\"robot\":[");
    let boxes = ps_discovery_robot; if calibration != ps_discovery_frames { boxes = boxes + (ps_arm_collider_count + 5) * 120; } i = 0; let count = ps_arm_collider_count + 4 + ps_gripper_held;
    while i < count { if i { pl_char(b, 44); } pl_char(b, 91); let k = 0;
        while k < 15 { if k { pl_char(b, 44); } pl_float(b, load64(boxes + i * 120 + k * 8)); k = k + 1; }
        pl_char(b, 93); i = i + 1;
    } return pl_text(b, "]}");
}
fn ps_discovery_request() {
    ps_discovery_frame_id = ps_total;
    let capacity = (ps_arm_collider_count + 5) * 1024 + 4096; let text = alloc(capacity); let b = alloc(32); pl_builder(b, text, capacity);
    pl_text(b, "{\"schema\":\"puppybot.discovery-input.v1\",\"frameId\":"); pl_int(b, ps_total); pl_text(b, ",\"newScan\":"); pj_bool_text(b, !ps_discovery_scan_recorded);
    pl_text(b, ",\"pose\":["); pl_float(b, ps_pose_x()); pl_char(b, 44); pl_float(b, ps_pose_y()); pl_char(b, 44); pl_float(b, ps_pose_heading()); pl_text(b, "],\"frames\":[");
    ps_discovery_frame_text(b, ps_discovery_left, ps_discovery_frames); pl_char(b, 44); ps_discovery_frame_text(b, ps_discovery_right, ps_discovery_frames + 96); pl_text(b, "]}\n");
    let request = h_cat(ps_discovery_directory, "/request.json"); let ok = !load64(b + 24) && !pl_atomic_file(request, text, load64(b + 8));
    syscall(11, text, capacity, 0, 0, 0, 0); syscall(11, b, 32, 0, 0, 0, 0); if !ok { return 0; }
    let args = h_args(h_executable("python3"), "flex/vision/discovery.py", "--request", request, "--output", ps_discovery_directory);
    ps_discovery_job = h_spawn(args, "", 0); ps_discovery_scan_recorded = 1; ps_discovery_started = pl_now(); ps_discovery_phase = 3; return 1;
}
fn ps_discovery_result() {
    let job = ps_discovery_job; let root = pj_parse(h_out(job), h_size(load64(job + 16)));
    if h_status(job) || !root { pl_print(2, h_err(job)); return 0; }
    if !pl_equal(pj_string_field(root, "source"), "tcp-rgb-active-stereo") || pj_integer(root, "frameId", 0, ps_total) != ps_discovery_frame_id { return 0; }
    if pj_integer(root, "cells", 200, 200) != 200 || pj_error { return 0; }
    ps_discovery_free = pj_integer(root, "freeCells", 0, 40000); ps_discovery_occupied = pj_integer(root, "occupiedCells", 0, 40000); ps_discovery_safe = pj_integer(root, "safeCells", 0, 40000);
    let goals = pj_get(root, "goals"); ps_discovery_goal_count = pb_min(8, pj_count(goals)); let i = 0;
    while i < ps_discovery_goal_count { let p = pj_index(goals, i); let k = 0;
        if pj_kind(p) != 3 || pj_count(p) != 3 { return 0; }
        while k < 3 { let value = pj_real_node(pj_index(p, k)); if pj_error || !f64_is_finite(value) || f64_gt(f64_magnitude(value), f64_from_i64(10)) { return 0; } store64(ps_discovery_goals + i * 24 + k * 8, value); k = k + 1; } i = i + 1;
    }
    if pj_error || pl_read_file(h_cat(ps_discovery_directory, "/safe.bin"), ps_nav_map, 40000) != 40000 || pl_read_file(h_cat(ps_discovery_directory, "/observed.bin"), ps_discovery_observed, 40000) != 40000 { return 0; }
    if pl_read_file(h_cat(ps_discovery_directory, "/observed-detail.bin"), ps_discovery_detail, 1000000) != 1000000 { return 0; }
    i = 0; while i < 1000000 { if load8(ps_discovery_detail + i) > 1 { return 0; } i = i + 1; }
    ps_discovery_detail_ready = 1;
    i = 0; while i < 40000 { if load8(ps_nav_map + i) > 1 || load8(ps_discovery_observed + i) > 1 { return 0; } i = i + 1; } ps_discovery_map_frame = ps_discovery_frame_id; return 1;
}
fn ps_discovery_escape_unvisited(x, y) {
    let i = 0;
    while i < ps_discovery_escape_count {
        let r = ps_discovery_escape_poses + i * 16; let dx = f64_sub(x, load64(r)); let dy = f64_sub(y, load64(r + 8));
        if f64_lt(f64_add(f64_mul(dx, dx), f64_mul(dy, dy)), ps_number(36, 10000)) { return 0; } i = i + 1;
    } return 1;
}
fn ps_discovery_escape_remember(x, y) {
    let r = ps_discovery_escape_poses + (ps_discovery_escape_next % 16) * 16; store64(r, x); store64(r + 8, y);
    ps_discovery_escape_next = ps_discovery_escape_next + 1; ps_discovery_escape_count = pb_min(16, ps_discovery_escape_count + 1); return 1;
}
fn ps_discovery_escape() {
    if ps_gripper_held || !ps_nav_heading_free() { return 0; }
    let direction = 1;
    while direction >= -1 {
        if ps_nav_straight_escape(ps_pose_x(), ps_pose_y(), ps_pose_heading(), direction) {
            // A turn was rejected, but this straight command has not
            // failed. Move only one fully observed primitive, then scan from
            // the new pose; do not invent a route to an unreachable frontier.
            let action = 1; if direction < 0 { action = 4; } let r = ps_nav_actions + action * 128;
            let c = f64_cos(ps_pose_heading()); let s = f64_sin(ps_pose_heading()); let sample = 0; let clear = 1;
            let x = ps_pose_x(); let y = ps_pose_y(); let from_x = x; let from_y = y;
            while sample < 5 && clear {
                let dx = load64(r + 24 + sample * 16); let dy = load64(r + 32 + sample * 16);
                x = f64_add(ps_pose_x(), f64_sub(f64_mul(c, dx), f64_mul(s, dy))); y = f64_add(ps_pose_y(), f64_add(f64_mul(s, dx), f64_mul(c, dy)));
                clear = ps_nav_transition_clear(x, y, ps_pose_heading(), from_x, from_y, ps_pose_heading());
                from_x = x; from_y = y; sample = sample + 1;
            }
            if clear && ps_discovery_escape_unvisited(x, y) {
                // Scanning after a short escape must not simply undo it and
                // repeat forever. Remember both endpoints in our own frame;
                // alternate views and completed-motion retracing handle a
                // dead end instead. Observed floor and guards stay unchanged.
                ps_discovery_escape_remember(ps_pose_x(), ps_pose_y()); ps_discovery_escape_remember(x, y);
                ps_nav_path_count = 1; ps_nav_path_index = 0; ps_nav_remaining = 0; store64(ps_nav_path, action); ps_nav_plans = ps_nav_plans + 1;
                store64(ps_nav_goal, x); store64(ps_nav_goal + 8, y); let heading = ps_pose_heading(); if direction < 0 { heading = pb_wrap_pi(f64_add(heading, PB_PI)); }
                store64(ps_nav_goal + 16, heading); return 1;
            }
        } direction = direction - 2;
    } return 0;
}
fn ps_discovery_next_sector() {
    ps_discovery_side = 0;
    if !ps_discovery_tilt { ps_discovery_tilt = 1; if ps_discovery_aim() { return 1; } }
    ps_discovery_tilt = 0; ps_discovery_sector = ps_discovery_sector + 1; let count = 3; if ps_discovery_full { count = 8; }
    while ps_discovery_sector < count {
        ps_discovery_tilt = 0; if ps_discovery_aim() { return 1; }
        ps_discovery_tilt = 1; if ps_discovery_aim() { return 1; } ps_discovery_sector = ps_discovery_sector + 1;
    }
    ps_discovery_scans = ps_discovery_scans + 1;
    if ps_collect_mapping { return ps_collect_map_end(); }
    if ps_collect_enabled && ps_collect_select() { ps_discovery_phase = 0; return 1; }
    if ps_discovery_scans >= ps_discovery_limit { return ps_discovery_finish("scan budget reached; map retained", 0); }
    let i = 0; let found = 0;
    if ps_collect_enabled { found = ps_collect_resume_plan(); if !found { ps_collect_frontiers(); } }
    while i < ps_discovery_goal_count && !found {
        let p = ps_discovery_goals + i * 24;
        if ps_discovery_frontier_allowed(load64(p), load64(p + 8)) { found = ps_nav_plan(load64(p), load64(p + 8), load64(p + 16)); } i = i + 1;
    }
    if !found { found = ps_discovery_escape(); }
    if !found {
        if ps_discovery_full {
            // A narrow unknown patch can block every car exit after one
            // scan. Acquire new stereo geometry before declaring a dead end;
            // neither unknown floor nor the physical guard is relaxed.
            if ps_discovery_rescans >= 2 {
                if ps_discovery_motion_count { return ps_discovery_retrace_begin(); }
                return ps_discovery_finish("no reachable frontier after alternate wrist views", 1);
            }
            ps_discovery_rescans = ps_discovery_rescans + 1;
        }
        ps_discovery_full = 1; return ps_discovery_first_view();
    }
    ps_discovery_frontier_focus(ps_nav_goal);
    if ps_discovery_raised_only {
        let point = ps_discovery_robot_scratch; ps_camera_compact_point(point, ps_pose_heading(), ps_number(16, 1000));
        if !ps_arm_solve(point, 370, 75) || !ps_discovery_stage(4) { return ps_discovery_finish("cannot aim wrist for discovery travel", 1); }
    } else {
        if !ps_camera_drive_target() { return ps_discovery_finish("cannot aim wrist for discovery travel", 1); }
        ps_discovery_phase = 4; ps_discovery_started = ps_total;
    }
    ps_floor_changed = 0; ps_discovery_distance = ps_local_distance; return 1;
}
fn ps_discovery_first_view() {
    ps_discovery_sector = 0; ps_discovery_side = 0; ps_discovery_tilt = 0; ps_discovery_scan_recorded = 0; ps_discovery_raised_only = !ps_discovery_pose_allowed(ps_pose_x(), ps_pose_y());
    // Empty jaws need no capture clearance while scanning beside walls.
    // Pickup opens them again before the approach and visual refinement.
    if !ps_gripper_held { ps_gripper_command(0); }
    // Keep the frontier bearing even if the nearest wrist pose is outside
    // joint limits. Try the far pose and neighbouring bearings first.
    if ps_discovery_aim() { return 1; } return ps_discovery_next_sector();
}
fn ps_discovery_arm_stop() {
    // Consume only the rejected-motion bit. Obstacle identity/geometry stays
    // in the physical guard and never becomes a hidden mapping observation.
    if !ps_discovery_enabled || ps_collect_busy || ps_gripper_held || ps_discovery_phase != 2 { return 0; }
    pb_drive_stop(pb_robot_drive(ps_robot), ps_time); ps_discovery_arm_stops = ps_discovery_arm_stops + 1; ps_discovery_skip_view = 1; ps_discovery_raised_only = 1;
    if ps_discovery_pose_allowed(ps_pose_x(), ps_pose_y()) {
        let slot = ps_discovery_bad_next % 16; ps_discovery_bad_next = ps_discovery_bad_next + 1; store64(ps_discovery_bad_poses + slot * 16, ps_pose_x()); store64(ps_discovery_bad_poses + slot * 16 + 8, ps_pose_y()); ps_discovery_bad_count = pb_min(16, ps_discovery_bad_count + 1);
    } return 1;
}
fn ps_discovery_update() {
    if ps_collect_enabled && (ps_case_stage == 12 || ps_case_stage == 13) { if ps_discovery_phase < 6 { ps_discovery_finish(ps_case_reason, !ps_case_passed); } return 1; }
    if ps_collect_enabled && ps_collect_busy && !ps_collect_mapping { return 1; }
    if !ps_discovery_enabled || ps_discovery_phase >= 6 { return 1; }
    if ps_discovery_skip_view {
        ps_discovery_skip_view = 0;
        if ps_discovery_arm_stops > 12 { return ps_discovery_finish("wrist protective-stop budget reached", 1); }
        return ps_discovery_next_sector();
    }
    if !ps_discovery_phase && ps_discovery_pending_phase {
        if ps_total - ps_discovery_started > ps_discovery_timeout { return ps_discovery_finish("compact wrist staging timed out", 1); }
        if !ps_discovery_settled() { return 1; }
        if ps_discovery_pending_turn == -1 {
            pb_copy(ps_pickup_targets, ps_discovery_tuck, 32); ps_discovery_pending_turn = 1;
            if !ps_discovery_apply(0) { return ps_discovery_finish("cannot raise compact wrist after shoulder retreat", 1); } return 1;
        }
        if !ps_discovery_pending_turn {
            pb_copy(ps_pickup_targets, ps_discovery_tuck, 32); ps_discovery_pending_turn = 1;
            if !ps_discovery_apply(0) { return ps_discovery_finish("cannot raise compact wrist", 1); } return 1;
        }
        if ps_discovery_pending_turn == 1 {
            store64(ps_pickup_targets, load64(ps_discovery_pending)); ps_discovery_pending_turn = 2;
            if !ps_discovery_apply(0) { return ps_discovery_finish("cannot turn compact wrist", 1); } return 1;
        }
        let phase = ps_discovery_pending_phase; ps_discovery_pending_phase = 0; pb_copy(ps_pickup_targets, ps_discovery_pending, 32);
        if !ps_discovery_apply(phase) { return ps_discovery_finish("cannot finish compact wrist staging", 1); } return 1;
    }
    if ps_discovery_phase == 1 {
        pb_drive_stop(pb_robot_drive(ps_robot), ps_time);
        if !ps_discovery_initialized {
            if !ps_discovery_root { ps_discovery_root = h_cat("build/flex/sim/discovery-", h_int(syscall(39, 0, 0, 0, 0, 0, 0))); }
            if syscall(83, ps_discovery_root, 493, 0, 0, 0, 0) { return ps_discovery_finish("mapping output directory must be new", 1); } ps_discovery_initialized = 1;
        }
        if !ps_discovery_directory {
            ps_discovery_directory = h_cat3(ps_discovery_root, "/episode-", h_int(ps_episode));
            if syscall(83, ps_discovery_directory, 493, 0, 0, 0, 0) { return ps_discovery_finish("cannot create mapping episode", 1); }
        }
        ps_discovery_bearing = ps_discovery_scan_bearing(); return ps_discovery_first_view();
    }
    if ps_discovery_phase == 2 {
        if ps_total - ps_discovery_started > ps_discovery_timeout { return ps_discovery_finish("discovery wrist motion timed out", 1); }
        if !ps_discovery_settled() || ps_gripper_gap != ps_gripper_goal { return 1; }
        if !ps_rgb_sample() { return ps_discovery_finish("cannot capture clean wrist RGB", 1); }
        if ps_collect_enabled && !ps_collect_mapping && ps_collect_observe() { return 1; }
        let path = h_cat3(ps_discovery_directory, "/rgb-", h_cat(h_int(ps_discovery_samples), ".bin")); ps_discovery_samples = ps_discovery_samples + 1;
        if pl_atomic_file(path, ps_brick_rgb, 640 * 480 * 3) { return ps_discovery_finish("cannot save mapping RGB", 1); }
        pb_copy(ps_discovery_frames + ps_discovery_side * 96, ps_brick_pose, 96); ps_discovery_robot_frame(ps_discovery_side);
        if !ps_discovery_side { ps_discovery_left = path; ps_discovery_left_step = ps_total; ps_discovery_side = 1; if !ps_discovery_aim() { return ps_discovery_next_sector(); } return 1; }
        ps_discovery_right = path; if !ps_discovery_request() { return ps_discovery_finish("cannot submit stereo pair", 1); } return 1;
    }
    if ps_discovery_phase == 3 {
        h_pump(ps_discovery_job, 1);
        if load64(ps_discovery_job + 8) == -999 { if pl_now() - ps_discovery_started > 15000 { h_stop(ps_discovery_job); ps_discovery_job = 0; return ps_discovery_finish("mapping worker timed out", 1); } return 1; }
        if load64(ps_discovery_job + 40) >= 0 || load64(ps_discovery_job + 48) >= 0 { return 1; }
        let ok = ps_discovery_result(); h_close(load64(ps_discovery_job + 32)); store64(ps_discovery_job + 32, -1); ps_discovery_job = 0;
        if !ok { return ps_discovery_finish("stereo worker failed; no blind motion", 1); }
        if ps_collect_mapping { return ps_collect_map_finish(); }
        if ps_collect_select() { return 1; } return ps_discovery_next_sector();
    }
    if ps_discovery_phase == 4 {
        if ps_total - ps_discovery_started > 1500 { return ps_discovery_finish("driving camera pose timed out", 1); }
        if ps_discovery_settled() { ps_discovery_phase = 5; } return 1;
    }
    if ps_discovery_phase == 5 {
        if ps_discovery_retrace { return ps_discovery_retrace_tick(); }
        ps_discovery_motion_record();
        let travel = ps_number(3, 10); if ps_collect_enabled { travel = ps_number(8, 10); }
        if !ps_blocked {
            let observation = ps_collect_travel_observe(); if observation < 0 { return ps_discovery_finish("cannot observe wrist RGB during travel", 1); } if observation { return 1; }
        }
        if ps_blocked {
            if !ps_discovery_protective_stop() { return 0; }
            if !ps_gripper_held && ps_nav_heading_free() && ps_discovery_motion_count { return ps_discovery_retrace_begin(); }
        } else if !ps_nav_tick() {
            if f64_lt(f64_sub(ps_local_distance, ps_discovery_distance), travel) { return 1; }
            // A long transit already lies inside observed floor. Refresh its
            // route from wheel/visual odometry without spending another scan
            // on the same floor. New RGB targets and physical stops still
            // interrupt immediately; an invalid route falls back to scanning.
            if ps_collect_enabled && ps_nav_plan(load64(ps_nav_goal), load64(ps_nav_goal + 8), load64(ps_nav_goal + 16)) {
                pb_drive_stop(pb_robot_drive(ps_robot), ps_time); ps_discovery_distance = ps_local_distance; ps_crumb_replan = 0; return 1;
            }
        }
        return ps_discovery_scan_after_motion(!(ps_discovery_scans % 4));
    }
    return 1;
}
fn ps_discovery_observation(b) {
    if !ps_discovery_enabled { return 0; }
    pl_text(b, ",\"discovery\":{\"source\":\"tcp-rgb-active-stereo\",\"suppliedMap\":false,\"worldPoseInput\":false,\"phase\":"); pl_int(b, ps_discovery_phase);
    pl_text(b, ",\"reason\":"); pj_text(b, ps_discovery_reason); pl_text(b, ",\"scans\":"); pl_int(b, ps_discovery_scans); pl_text(b, ",\"images\":"); pl_int(b, ps_discovery_samples);
    pl_text(b, ",\"mapFrameId\":"); pl_int(b, ps_discovery_map_frame);
    pl_text(b, ",\"scanBearingRad\":"); pl_float(b, ps_discovery_bearing); pl_text(b, ",\"viewSector\":"); pl_int(b, ps_discovery_sector); pl_text(b, ",\"viewTilt\":"); pl_int(b, ps_discovery_tilt);
    pl_text(b, ",\"armProtectiveStops\":"); pl_int(b, ps_discovery_arm_stops);
    pl_text(b, ",\"freeCells\":"); pl_int(b, ps_discovery_free); pl_text(b, ",\"occupiedCells\":"); pl_int(b, ps_discovery_occupied); pl_text(b, ",\"safeCells\":"); pl_int(b, ps_discovery_safe);
    pl_text(b, ",\"failedFrontiers\":"); pl_int(b, ps_discovery_failed_count);
    pl_text(b, ",\"protectiveStops\":"); pl_int(b, ps_discovery_stops); pl_text(b, ",\"output\":"); if ps_discovery_directory { pj_text(b, ps_discovery_directory); } else { pl_text(b, "null"); }
    pl_text(b, ",\"motionHistory\":{\"source\":\"completed-wheel-and-encoder-commands\",\"retainedSteps\":"); pl_int(b, ps_discovery_motion_count);
    pl_text(b, ",\"retraceSteps\":"); pl_int(b, ps_discovery_retrace); pl_char(b, 125); ps_collect_observation(b); return pl_char(b, 125);
}
