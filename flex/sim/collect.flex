// Pickup over a map learned from wrist RGB. The scene supplies robot/object
// dimensions and task count; no coverage route, world pose or wall map enters.
import "grasp.flex";

global ps_collect_enabled = 0;
global ps_collect_busy = 0;
global ps_collect_points = 0;
global ps_collect_count = 0;
global ps_collect_pitch = -30;
global ps_collect_reach = 186;
global ps_collect_carry = 0;
global ps_collect_drive = 0;
global ps_collect_timeout = 0;
global ps_collect_self_point = 0;
global ps_collect_self_box = 0;
global ps_collect_refined = 0;
global ps_collect_map_until = 0;
global ps_collect_lift = 0;
global ps_collect_mapping = 0;
global ps_collect_map_started = 0;
global ps_collect_global_map = 0;
global ps_collect_local_map = 0;
global ps_collect_global_counts = 0;
global ps_collect_resume_goal = 0;
global ps_collect_resume_valid = 0;
global ps_collect_resume_placed = 0;
global ps_collect_resume_tries = 0;
global ps_collect_resume_count = 0;
global ps_collect_restow = 0;

fn ps_collect_reset() {
    ps_collect_busy = 0; ps_collect_count = 0; ps_collect_pitch = -30; ps_collect_refined = 0; ps_collect_map_until = 1; ps_collect_lift = 0; ps_collect_mapping = 0; ps_collect_global_map = 0; ps_collect_local_map = 0;
    ps_collect_resume_valid = 0; ps_collect_resume_placed = 0; ps_collect_resume_tries = 0; ps_collect_resume_count = 0;
    ps_collect_restow = 0;
    if !ps_collect_resume_goal { ps_collect_resume_goal = alloc(24); }
    if !ps_collect_points { ps_collect_points = alloc(64 * 64); ps_collect_carry = alloc(24); ps_collect_drive = alloc(32); ps_collect_self_point = alloc(24); ps_collect_self_box = alloc(48); ps_collect_global_counts = alloc(32); }
    store64(ps_collect_self_box + 16, ps_number(58, 1000)); store64(ps_collect_self_box + 24, ps_number(14, 100)); store64(ps_collect_self_box + 32, ps_number(11, 100)); store64(ps_collect_self_box + 40, ps_number(6, 100));
    return 1;
}
fn ps_collect_map_restore() {
    if !ps_collect_local_map { return 1; }
    // Resume the learned transit map after the close-range task. The local
    // docking worker never overwrites its older observations or evidence.
    if pl_read_file(h_cat(ps_collect_global_map, "/safe.bin"), ps_nav_map, 40000) != 40000 || pl_read_file(h_cat(ps_collect_global_map, "/observed.bin"), ps_discovery_observed, 40000) != 40000 || pl_read_file(h_cat(ps_collect_global_map, "/observed-detail.bin"), ps_discovery_detail, 1000000) != 1000000 { return ps_case_fail("cannot restore learned transit map after docking"); }
    ps_discovery_directory = ps_collect_global_map; ps_discovery_detail_ready = 1; ps_discovery_goal_count = 0;
    ps_discovery_free = load64(ps_collect_global_counts); ps_discovery_occupied = load64(ps_collect_global_counts + 8); ps_discovery_safe = load64(ps_collect_global_counts + 16); ps_discovery_map_frame = load64(ps_collect_global_counts + 24);
    ps_collect_global_map = 0; ps_collect_local_map = 0; return 1;
}
fn ps_collect_map_begin() {
    if !ps_collect_enabled || !ps_gripper_held || !ps_discovery_directory || ps_discovery_job || ps_dock_search_maps >= 2 || ps_dock_search_map_index == ps_dock_search_index { return 0; }
    // Seeing the box does not establish the floor needed to approach it.
    // Scan the surrounding floor with the same stationary wrist stereo as
    // exploration, keeping the jaws closed on the payload throughout.
    if !ps_collect_local_map {
        // Odometry drift can leave an old rim in the transit map. Build the
        // final approach from an unknown local costmap and current RGB,
        // rather than declaring any old or unseen cell free.
        ps_collect_global_map = ps_discovery_directory;
        ps_collect_local_map = h_cat3(ps_collect_global_map, "/dock-", h_int(ps_gripper_grasps));
        if syscall(83, ps_collect_local_map, 493, 0, 0, 0, 0) { ps_collect_local_map = 0; return ps_case_fail("cannot initialize fresh docking map"); }
        store64(ps_collect_global_counts, ps_discovery_free); store64(ps_collect_global_counts + 8, ps_discovery_occupied); store64(ps_collect_global_counts + 16, ps_discovery_safe); store64(ps_collect_global_counts + 24, ps_discovery_map_frame);
        ps_discovery_directory = ps_collect_local_map; ps_discovery_detail_ready = 0; ps_discovery_free = 0; ps_discovery_occupied = 0; ps_discovery_safe = 0; ps_discovery_map_frame = 0;
        let i = 0; while i < 40000 { store8(ps_nav_map + i, 1); store8(ps_discovery_observed + i, 1); i = i + 1; }
    }
    pb_drive_stop(pb_robot_drive(ps_robot), ps_time); ps_collect_mapping = 1; ps_collect_map_started = ps_total;
    ps_dock_search_maps = ps_dock_search_maps + 1; ps_dock_search_map_index = ps_dock_search_index;
    ps_discovery_bearing = f64_atan2(f64_sub(load64(ps_dock_frame + 104), ps_pose_y()), f64_sub(load64(ps_dock_frame + 96), ps_pose_x()));
    ps_discovery_full = 1; ps_discovery_rescans = ps_dock_search_maps - 1;
    ps_case_phase(35); return ps_discovery_first_view();
}
fn ps_collect_map_end() {
    ps_collect_mapping = 0; ps_discovery_phase = 0;
    // Two surrounding scans and the existing wrist/worker timeouts bound it.
    // Keep the circular-search movement budget separate from mapping time.
    ps_dock_search_started = ps_dock_search_started + ps_total - ps_collect_map_started;
    ps_case_survey_index = 0; return ps_case_tcp_survey();
}
fn ps_collect_map_finish() {
    // A newly mapped route is only a reason to look at the box again. The
    // release still needs fresh stable RGB after the arm leaves mapping.
    if ps_dock_seen >= 0 && ps_dock_search_stage() { return ps_collect_map_end(); }
    return ps_discovery_next_sector();
}
fn ps_collect_self_box_hit(point, matrix, centre, half) {
    ps_point(ps_collect_self_point, matrix, centre); let low = 0; let high = PB_ONE; let axis = 0;
    while axis < 3 {
        let start = 0; let delta = 0; let row = 0;
        while row < 3 {
            let direction = load64(matrix + (axis * 4 + row) * 8);
            start = f64_add(start, f64_mul(f64_sub(load64(ps_brick_pose + row * 8), load64(ps_collect_self_point + row * 8)), direction));
            let end = load64(point + row * 8); if row == 2 { end = ps_number(24, 1000); }
            delta = f64_add(delta, f64_mul(f64_sub(end, load64(ps_brick_pose + row * 8)), direction)); row = row + 1;
        }
        let extent = f64_add(load64(half + axis * 8), ps_number(2, 1000));
        if f64_lt(f64_magnitude(delta), ps_number(1, 1000000)) { if f64_gt(f64_magnitude(start), extent) { return 0; } }
        else {
            let a = f64_div(f64_sub(pb_neg(extent), start), delta); let b = f64_div(f64_sub(extent, start), delta);
            low = pb_fmax(low, pb_fmin(a, b)); high = pb_fmin(high, pb_fmax(a, b)); if f64_gt(low, high) { return 0; }
        } axis = axis + 1;
    }
    return 1;
}
fn ps_collect_self_target(point) {
    if !ps_collect_enabled { return 0; }
    // Reject a floor-ray hypothesis hidden by the known rover/arm model.
    // These transforms use encoder FK and the local estimate, not scene IDs.
    if ps_collect_self_box_hit(point, ps_local_root, ps_collect_self_box, ps_collect_self_box + 24) { return 1; }
    let i = 0; while i < ps_arm_collider_count {
        let r = ps_arm_colliders + i * 56;
        if ps_collect_self_box_hit(point, ps_local_matrices + load64(r) * 128, r + 8, r + 32) { return 1; } i = i + 1;
    }
    return 0;
}
fn ps_collect_search_begin() {
    if !ps_collect_map_restore() { return 0; }
    ps_discovery_motion_clear();
    ps_discovery_escape_count = 0; ps_discovery_escape_next = 0;
    let speed = ps_trace + 1400; store64(speed, 200); if pr_apply(ps_app, 1, speed, ps_time) { return ps_case_fail("cannot set scanning arm speed"); }
    ps_collect_busy = 0; ps_house_returning = 0;
    ps_discovery_phase = 1; ps_discovery_sector = 0; ps_discovery_side = 0; ps_discovery_tilt = 0; ps_discovery_rescans = 0;
    ps_discovery_full = ps_collect_map_until || !ps_house_ready || !(ps_discovery_scans % 4); ps_case_phase(26); return 1;
}
fn ps_collect_attention() {
    if ps_seek_enabled { if ps_seek_found && ps_dock_seen >= 0 { return ps_dock_frame + 96; } return 0; }
    if !ps_collect_enabled || !ps_house_ready { return 0; } let best = 0; let distance = f64_from_i64(1000); let i = 0;
    while i < ps_collect_count { let p = ps_collect_points + i * 64;
        let dx = f64_sub(load64(p), ps_pose_x()); let dy = f64_sub(load64(p + 8), ps_pose_y()); let d = f64_add(f64_mul(dx, dx), f64_mul(dy, dy));
        if load64(p + 32) >= 3 && !load64(p + 48) && ps_total >= load64(p + 56) && f64_lt(d, distance) { best = p; distance = d; } i = i + 1;
    } return best;
}
fn ps_collect_frontiers() {
    if ps_seek_enabled { return 0; }
    let target = ps_collect_attention(); if !target { return 0; } let i = 0;
    while i < ps_discovery_goal_count { let best = i; let distance = f64_from_i64(1000); let j = i;
        while j < ps_discovery_goal_count { let p = ps_discovery_goals + j * 24;
            let dx = f64_sub(load64(p), load64(target)); let dy = f64_sub(load64(p + 8), load64(target + 8)); let d = f64_add(f64_mul(dx, dx), f64_mul(dy, dy));
            if f64_lt(d, distance) { best = j; distance = d; } j = j + 1;
        }
        pb_copy(ps_collect_carry, ps_discovery_goals + i * 24, 24); pb_copy(ps_discovery_goals + i * 24, ps_discovery_goals + best * 24, 24); pb_copy(ps_discovery_goals + best * 24, ps_collect_carry, 24); i = i + 1;
    } return 1;
}
fn ps_collect_resume_plan() {
    if !ps_collect_resume_valid || ps_case_placed <= ps_collect_resume_placed { return 0; }
    let x = load64(ps_collect_resume_goal); let y = load64(ps_collect_resume_goal + 8);
    let dx = f64_sub(x, ps_pose_x()); let dy = f64_sub(y, ps_pose_y());
    // A confirmed uncollected brick takes priority. Nearby departures and
    // failed destinations do not justify another transit after delivery.
    if ps_collect_attention() || f64_lt(f64_add(f64_mul(dx, dx), f64_mul(dy, dy)), ps_number(25, 100)) || !ps_discovery_frontier_allowed(x, y) {
        ps_collect_resume_valid = 0; return 0;
    }
    // The ordinary post-delivery scan refreshes the starting floor first.
    // Retry only across three completed scans; never fill a missing route.
    ps_collect_resume_tries = ps_collect_resume_tries + 1;
    if ps_nav_plan(x, y, load64(ps_collect_resume_goal + 16)) {
        ps_collect_resume_valid = 0; ps_collect_resume_count = ps_collect_resume_count + 1; return 1;
    }
    if ps_collect_resume_tries >= 3 { ps_collect_resume_valid = 0; } return 0;
}
fn ps_collect_observe() {
    if ps_seek_enabled { return ps_seek_observe(); }
    if !ps_collect_enabled { return 0; }
    ps_dock_samples = ps_dock_samples + 1; let dock = ps_dock_detect(); ps_dock_attention(dock); let hold = dock && ps_dock_stable < 3;
    if dock && ps_dock_stable >= 3 && !ps_house_ready {
        ps_house_ready = 1; store64(ps_house_home, ps_pose_x()); store64(ps_house_home + 8, ps_pose_y()); store64(ps_house_home + 16, ps_pose_heading());
    }
    ps_brick_detect(); ps_floor_observe(); let i = 0;
    while i < ps_brick_count {
        let r = ps_brick_records + i * 128; let dx = f64_sub(load64(r + 32), ps_pose_x()); let dy = f64_sub(load64(r + 40), ps_pose_y());
        // Distant RGB sightings can guide exploration before their surrounding
        // floor is mapped. Parking and the fresh close inspection still gate
        // pickup; this memory does not declare any floor traversable.
        if f64_lt(f64_add(f64_mul(dx, dx), f64_mul(dy, dy)), f64_from_i64(4)) && ps_house_detection(i) {
            let found = -1; let j = 0;
            while j < ps_collect_count { let p = ps_collect_points + j * 64;
                if load64(p + 24) == load64(r + 64) && ps_floor_near(load64(r + 32), load64(r + 40), p, ps_number(6, 100)) { found = j; } j = j + 1;
            }
            if found < 0 && ps_collect_count < 64 { found = ps_collect_count; ps_collect_count = ps_collect_count + 1; pb_zero(ps_collect_points + found * 64, 64); }
            if found >= 0 { let p = ps_collect_points + found * 64;
                if load64(p + 40) != ps_total { pb_copy(p, r + 32, 24); store64(p + 24, load64(r + 64)); store64(p + 32, load64(p + 32) + 1); store64(p + 40, ps_total); }
                if load64(p + 32) < 3 && !load64(p + 48) { hold = 1; }
            }
        } i = i + 1;
    }
    return hold;
}
fn ps_collect_travel_observe() {
    if !ps_collect_enabled || ps_collect_busy || !ps_camera_drive_mode || ps_total % 10 != 1 || !ps_camera_still() { return 0; }
    if !ps_rgb_sample() { return -1; }
    ps_collect_observe(); ps_brick_mark(); ps_brick_caption = ps_text_upload(ps_brick_caption, "RGB TCP - DISCOVERY TRAVEL");
    if !ps_floor_changed { return 0; }
    // A newly confirmed RGB obstacle invalidates the current frontier route.
    // Stop and scan toward the observation before planning a pickup approach.
    ps_floor_changed = 0; pb_drive_stop(pb_robot_drive(ps_robot), ps_time); ps_collect_search_begin(); return 1;
}
fn ps_collect_pick_base_at(nominal) {
    let c = f64_cos(ps_pose_heading()); let s = f64_sin(ps_pose_heading()); let i = 0;
    while i < 41 {
        let mm = (i + 1) / 2; if i % 2 { mm = -mm; } let distance = f64_add(nominal, ps_number(mm, 1000));
        let x = f64_add(ps_pose_x(), f64_mul(c, distance)); let y = f64_add(ps_pose_y(), f64_mul(s, distance));
        if ps_grasp_solve_at(ps_case_target, 0, ps_collect_pitch, x, y, ps_pose_heading()) && ps_grasp_solve_at(ps_case_target, 140, ps_collect_pitch, x, y, ps_pose_heading()) && ps_house_path(x, y) {
            ps_case_grasp_base = x; ps_case_grasp_y = y; return 1;
        } i = i + 1;
    }
    return 0;
}
fn ps_collect_pick_base() { return ps_collect_pick_base_at(0); }
fn ps_collect_approach_begin() {
    let nominal = f64_sub(f64_add(f64_mul(f64_sub(load64(ps_case_target), ps_pose_x()), f64_cos(ps_pose_heading())), f64_mul(f64_sub(load64(ps_case_target + 8), ps_pose_y()), f64_sin(ps_pose_heading()))), ps_number(ps_collect_reach, 1000));
    if !ps_collect_pick_base_at(nominal) {
        ps_case_repositions = ps_case_repositions + 1; if ps_case_repositions <= 3 && ps_collect_plan_pick() { return 1; }
        return ps_collect_recover_target("staged RGB approach needs another observation");
    }
    ps_case_phase(2); return 1;
}
fn ps_collect_staging_inspect() {
    // The low driving view can see only a side sliver behind a finger at
    // this distance. Look down from above the fingers before the last drive.
    if !ps_camera_drive_pose(1) { return ps_collect_recover_target("cannot aim wrist for staged RGB approach"); }
    ps_camera_drive_mode = 0;
    ps_collect_timeout = ps_arm_move_timeout(); ps_case_phase(32); return 1;
}
fn ps_collect_approach_clear(x, y, heading) {
    let i = 0; while i <= 20 { let distance = ps_number(i, 100);
        if !ps_nav_clear(f64_sub(x, f64_mul(distance, f64_cos(heading))), f64_sub(y, f64_mul(distance, f64_sin(heading))), heading) { return 0; } i = i + 1;
    } return 1;
}
fn ps_collect_drive_clear(speed, steering) {
    let distance = ps_number(speed, 10000); let angle = pb_radians(f64_from_i64(steering * 45 / 100));
    let heading = pb_wrap_pi(f64_sub(ps_pose_heading(), f64_mul(f64_div(distance, ps_number(18, 100)), f64_div(f64_sin(angle), f64_cos(angle)))));
    let x = f64_add(ps_pose_x(), f64_mul(distance, f64_cos(heading))); let y = f64_add(ps_pose_y(), f64_mul(distance, f64_sin(heading)));
    return ps_nav_transition_clear(x, y, heading, ps_pose_x(), ps_pose_y(), ps_pose_heading());
}
fn ps_collect_plan_pick() {
    let view = 0; ps_house_returning = 3;
    while view < 8 {
        let turn = (view + 1) / 2; if !(view % 2) { turn = -turn; }
        let heading = pb_wrap_pi(f64_add(ps_pose_heading(), f64_mul(PB_TAU, ps_number(turn, 8)))); let c = f64_cos(heading); let s = f64_sin(heading);
        // This off-centre grasp keeps the lifted brick clear of the rover.
        let lateral = ps_number(-4, 100);
        let x = f64_add(f64_sub(load64(ps_case_target), f64_mul(c, ps_number(ps_collect_reach, 1000))), f64_mul(s, lateral));
        let y = f64_sub(f64_sub(load64(ps_case_target + 8), f64_mul(s, ps_number(ps_collect_reach, 1000))), f64_mul(c, lateral));
        let staging_x = f64_sub(x, f64_mul(c, ps_number(2, 10))); let staging_y = f64_sub(y, f64_mul(s, ps_number(2, 10)));
        // Include the complete parking correction when choosing an arrival,
        // using the fine local lattice and short drive primitives.
        if ps_grasp_solve_at(ps_case_target, 0, ps_collect_pitch, x, y, heading) && ps_grasp_solve_at(ps_case_target, 140, ps_collect_pitch, x, y, heading) && ps_collect_approach_clear(x, y, heading) && ps_nav_plan_parking(staging_x, staging_y, heading) {
            let speed = ps_trace + 1400; store64(speed, 200); if pr_apply(ps_app, 1, speed, ps_time) { return ps_case_fail("cannot set grasping arm speed"); }
            ps_house_block_replans = 0;
            ps_case_selected = -1; ps_gripper_body = -1; ps_gripper_command(1); ps_case_refine_radius = ps_number(8, 100); ps_case_phase(21); return 1;
        } view = view + 1;
    }
    ps_house_returning = 0; return 0;
}
fn ps_collect_select() {
    if ps_seek_enabled { return 0; }
    if !ps_collect_enabled || !ps_house_ready || ps_collect_busy { return 0; }
    if ps_collect_map_until { if ps_discovery_scans < ps_collect_map_until { return 0; } ps_collect_map_until = 0; }
    ps_collect_busy = 1;
    let i = 0;
    while i < ps_collect_count {
        let p = ps_collect_points + i * 64;
        if load64(p + 32) >= 3 && !load64(p + 48) && ps_total >= load64(p + 56) {
            pb_copy(ps_case_target, p, 24); ps_case_target_colour = load64(p + 24); ps_case_repositions = 0;
            if ps_collect_plan_pick() {
                // Save the robot's own scanning location before pickup and
                // docking replace the navigation goal. No scene pose enters.
                store64(ps_collect_resume_goal, ps_pose_x()); store64(ps_collect_resume_goal + 8, ps_pose_y()); store64(ps_collect_resume_goal + 16, ps_discovery_bearing);
                ps_collect_resume_placed = ps_case_placed; ps_collect_resume_valid = 1; ps_collect_resume_tries = 0;
                ps_discovery_phase = 0; return 1;
            }
        } i = i + 1;
    }
    ps_collect_busy = 0; return 0;
}
fn ps_collect_forget() {
    let i = 0; while i < ps_collect_count { let p = ps_collect_points + i * 64;
        if ps_floor_near(load64(ps_case_target), load64(ps_case_target + 8), p, ps_number(8, 100)) { store64(p + 48, 1); } i = i + 1;
    } return 1;
}
fn ps_collect_inspect() {
    // The folded grasp looks back under the palm, where the close brick is
    // cropped. Refine from a reachable downward view before lowering, while
    // the parked rover and the ungrasped target remain stationary.
    ps_collect_refined = 0;
    if !ps_arm_target(ps_case_target, 200, 0) { return ps_collect_recover_target("cannot reach RGB inspection pose; exploring for another approach"); }
    ps_camera_drive_mode = 0; ps_collect_timeout = ps_arm_move_timeout(); ps_case_phase(31); return 1;
}
fn ps_collect_inspect_update() {
    if ps_case_steps > ps_collect_timeout { return ps_collect_recover_target("RGB inspection wrist motion timed out"); }
    if !ps_pickup_settled() { return 1; }
    if !ps_case_camera_refine() { return 0; }
    let i = 0; while i < ps_collect_count { let p = ps_collect_points + i * 64;
        if load64(p + 24) == ps_case_target_colour && ps_floor_near(load64(ps_case_target), load64(ps_case_target + 8), p, ps_number(8, 100)) { pb_copy(p, ps_case_target, 24); } i = i + 1;
    }
    if ps_case_stage == 32 { return ps_collect_approach_begin(); }
    if !ps_grasp_solve(ps_case_target, 0, ps_collect_pitch) || !ps_grasp_solve(ps_case_target, 140, ps_collect_pitch) {
        ps_case_repositions = ps_case_repositions + 1;
        if ps_case_repositions <= 3 {
            if ps_collect_pick_base() { ps_case_phase(2); return 1; }
            if ps_collect_plan_pick() { return 1; }
        }
        return ps_collect_recover_target("refined brick outside folded-wrist reach; exploring for another approach");
    }
    ps_collect_refined = ps_brick_frame;
    if !ps_grasp_move(ps_case_target, 40, ps_collect_pitch) { return ps_collect_recover_target("cannot reach folded hover above RGB brick"); } ps_case_phase(3); return 1;
}
fn ps_collect_recover_target(reason) {
    let i = 0; while i < ps_collect_count { let p = ps_collect_points + i * 64;
        if ps_floor_near(load64(ps_case_target), load64(ps_case_target + 8), p, ps_number(8, 100)) { store64(p + 32, 0); store64(p + 56, ps_total + 2000); } i = i + 1;
    }
    pb_drive_stop(pb_robot_drive(ps_robot), ps_time); ps_gripper_command(1); ps_case_reason = reason; return ps_collect_search_begin();
}
fn ps_collect_lift_begin(lift) {
    pb_copy(ps_collect_carry, ps_case_target, 24); ps_collect_forget();
    // Independent joint speeds trace a curved TCP path on a large lift.
    // Short Cartesian stages keep the payload outside the chassis until high.
    ps_collect_lift = lift + 5;
    if !ps_grasp_move(ps_collect_carry, ps_collect_lift, ps_collect_pitch) { return ps_case_fail("cannot raise folded grasp clear of rover"); }
    ps_collect_timeout = ps_arm_move_timeout(); ps_case_phase(27); return 1;
}
fn ps_collect_stow_begin() {
    pb_drive_stop(pb_robot_drive(ps_robot), ps_time);
    // A compensated release TCP is not a floor grasp to lift again. Raise
    // the current shoulder first, then unfold high before turning the yaw.
    if !ps_gripper_held || !ps_camera_drive_solve(1) { return ps_case_fail("cannot solve loaded camera recovery"); }
    pb_copy(ps_collect_drive, ps_pickup_targets, 32); let i = 0;
    while i < 4 { if i != 1 { store64(ps_pickup_targets + i * 8, load64(ps_plant + 144 + i * 64)); } i = i + 1; }
    if pr_apply(ps_app, 5, ps_pickup_targets, ps_time) { return ps_case_fail("cannot raise shoulder during loaded recovery"); }
    ps_camera_drive_mode = 0; ps_collect_restow = 1; ps_collect_timeout = ps_arm_move_timeout(); ps_case_phase(27); return 1;
}
fn ps_collect_stow_update() {
    if !ps_gripper_held { return ps_case_fail("brick lost during staged wrist transfer"); }
    if ps_case_steps > ps_collect_timeout { return ps_case_fail("staged wrist transfer timed out"); }
    if !ps_pickup_settled() { return 1; }
    if ps_collect_restow {
        pb_copy(ps_pickup_targets, ps_collect_drive, 32);
        if ps_collect_restow == 1 { store64(ps_pickup_targets, load64(ps_plant + 144)); }
        if pr_apply(ps_app, 5, ps_pickup_targets, ps_time) { return ps_case_fail("cannot finish loaded camera recovery"); }
        if ps_collect_restow == 1 { ps_collect_restow = 2; ps_case_phase(27); }
        else { ps_collect_restow = 0; ps_camera_drive_mode = 1; ps_case_phase(19); }
        ps_collect_timeout = ps_arm_move_timeout(); return 1;
    }
    if ps_case_stage == 27 {
        if ps_collect_lift < 140 {
            ps_collect_lift = ps_collect_lift + 5;
            if !ps_grasp_move(ps_collect_carry, ps_collect_lift, ps_collect_pitch) { return ps_case_fail("cannot raise folded wrist"); } ps_case_phase(27);
        } else { ps_case_phase(28); }
    } else if ps_case_stage == 28 {
        store64(ps_collect_carry, f64_add(load64(ps_collect_carry), f64_mul(ps_number(4, 100), f64_cos(ps_pose_heading()))));
        store64(ps_collect_carry + 8, f64_add(load64(ps_collect_carry + 8), f64_mul(ps_number(4, 100), f64_sin(ps_pose_heading()))));
        if !ps_grasp_move(ps_collect_carry, 140, ps_collect_pitch) { return ps_case_fail("cannot extend loaded wrist clear of rover"); } ps_case_phase(29);
    } else if ps_case_stage == 29 {
        if !ps_camera_drive_target() { return ps_case_fail("cannot solve loaded driving pose"); } pb_copy(ps_collect_drive, ps_pickup_targets, 32); let i = 0;
        while i < 3 { store64(ps_pickup_targets + i * 8, load64(ps_plant + 144 + i * 64)); i = i + 1; }
        if pr_apply(ps_app, 5, ps_pickup_targets, ps_time) { return ps_case_fail("cannot unfold loaded wrist"); } ps_camera_drive_mode = 0; ps_case_phase(30);
    } else {
        pb_copy(ps_pickup_targets, ps_collect_drive, 32); if pr_apply(ps_app, 5, ps_pickup_targets, ps_time) { return ps_case_fail("cannot lower loaded driving pose"); }
        ps_camera_drive_mode = 1; ps_case_phase(19);
    }
    ps_collect_timeout = ps_arm_move_timeout(); return 1;
}
fn ps_collect_observation(b) {
    if !ps_collect_enabled { return 0; }
    pl_text(b, ",\"pickup\":{\"source\":\"remembered-tcp-rgb-bricks\",\"busy\":"); pj_bool_text(b, ps_collect_busy);
    pl_text(b, ",\"observedTargets\":"); pl_int(b, ps_collect_count); pl_text(b, ",\"boxLearned\":"); pj_bool_text(b, ps_house_ready);
    pl_text(b, ",\"fingerPitchDeg\":"); pl_int(b, ps_collect_pitch); pl_text(b, ",\"mappingHeldFloor\":"); pj_bool_text(b, ps_collect_mapping);
    pl_text(b, ",\"localDockMap\":"); pj_bool_text(b, ps_collect_local_map != 0);
    pl_text(b, ",\"resumePending\":"); pj_bool_text(b, ps_collect_resume_valid && ps_case_placed > ps_collect_resume_placed);
    pl_text(b, ",\"resumedRoutes\":"); pl_int(b, ps_collect_resume_count);
    pl_text(b, ",\"resumeGoal\":"); if ps_collect_resume_valid { pl_char(b, 91); let i = 0; while i < 3 { if i { pl_char(b, 44); } pl_float(b, load64(ps_collect_resume_goal + i * 8)); i = i + 1; } pl_char(b, 93); } else { pl_text(b, "null"); }
    if ps_gripper_held { pl_text(b, ",\"attachmentEstimateM\":["); let i = 0; while i < 3 { if i { pl_char(b, 44); } pl_float(b, load64(ps_case_attachment + i * 8)); i = i + 1; } pl_char(b, 93); } return pl_char(b, 125);
}
