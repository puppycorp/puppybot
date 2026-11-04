// Camera-driven collection across a mapped house. Coverage poses are a search
// itinerary, independent of the bricks. Only the physical judge knows IDs.
import "navigation.flex";

global ps_house_home = 0;
global ps_house_waypoint = 0;
global ps_house_laps = 0;
global ps_house_returning = 0;
global ps_house_distance = 0;
global ps_house_previous = 0;
global ps_house_parking = 0;
global ps_house_park_angle = 0;
global ps_house_ready = 0;
global ps_house_block_replans = 0;

fn ps_house_enabled() { return ps_case_camera == 2; }
fn ps_house_reset() {
    ps_house_waypoint = 0; ps_house_laps = 0; ps_house_returning = 0; ps_house_distance = 0; ps_house_parking = 0; ps_house_ready = 0;
    if !ps_house_home { ps_house_home = alloc(24); ps_house_previous = alloc(24); }
    store64(ps_house_home, f64_add(ps_pose_x(), f64_mul(ps_number(18, 100), f64_cos(ps_pose_heading()))));
    store64(ps_house_home + 8, f64_add(ps_pose_y(), f64_mul(ps_number(18, 100), f64_sin(ps_pose_heading())))); store64(ps_house_home + 16, ps_pose_heading());
    store64(ps_house_previous, ps_pose_x()); store64(ps_house_previous + 8, ps_pose_y()); return ps_nav_init();
}
fn ps_house_plan_view(target) {
    let x = load64(target); let y = load64(target + 8); let heading = load64(target + 16);
    if ps_nav_clear(x, y, heading) && ps_nav_plan(x, y, heading) { return 1; }
    // A coverage waypoint can intersect a camera-observed brick or box.
    // Find a nearby safe viewing pose, retaining the intended camera heading.
    let offset = 220;
    while offset <= 420 {
        let distance = ps_number(offset, 1000); let bx = f64_sub(x, f64_mul(distance, f64_cos(heading))); let by = f64_sub(y, f64_mul(distance, f64_sin(heading)));
        if ps_nav_clear(bx, by, heading) && ps_nav_plan(bx, by, heading) { return 1; } offset = offset + 20;
    }
    let radius = 1;
    while radius <= 4 {
        let view = 0;
        while view < 8 {
            let angle = f64_add(heading, f64_mul(PB_TAU, ps_number(view, 8))); let distance = ps_number(radius, 10);
            let bx = f64_add(x, f64_mul(distance, f64_cos(angle))); let by = f64_add(y, f64_mul(distance, f64_sin(angle)));
            if ps_nav_clear(bx, by, heading) && ps_nav_plan(bx, by, heading) { return 1; } view = view + 1;
        }
        radius = radius + 1;
    }
    return 0;
}
fn ps_house_begin(returning) {
    if ps_collect_enabled && returning != 1 { return ps_collect_search_begin(); }
    ps_house_block_replans = 0;
    ps_house_returning = returning; let target = ps_case_coverage + ps_house_waypoint * 24; if returning { target = ps_house_home; }
    if ps_stock_pickup && returning == 1 { if !ps_stock_return_begin() { return 0; } ps_case_phase(21); return 1; }
    if ps_stock_pickup && !returning && !ps_stock_phase { ps_stock_teach(); }
    if ps_crumb_enabled && ps_crumb_repeat && returning == 1 { return ps_crumb_return_begin(); }
    if ps_crumb_enabled && !returning && !ps_crumb_depart() { return ps_case_fail("cannot record TCP-camera route"); }
    pb_drive_stop(pb_robot_drive(ps_robot), ps_time);
    if !ps_house_plan_view(target) { return ps_case_fail("no car path through mapped furniture to the next room/home"); }
    ps_floor_changed = 0; ps_case_phase(21); return 1;
}
fn ps_house_filter(x, y) {
    // The home staging area is not searched for floor bricks. After learning
    // the box from RGB, also reject its observed footprint, even if moved.
    let dx = f64_sub(x, load64(ps_house_home)); let dy = f64_sub(y, load64(ps_house_home + 8));
    if !ps_collect_enabled && f64_lt(f64_add(f64_mul(dx, dx), f64_mul(dy, dy)), ps_number(25, 100)) { return 0; }
    if ps_dock_seen >= 0 {
        dx = f64_sub(x, load64(ps_dock_frame + 96)); dy = f64_sub(y, load64(ps_dock_frame + 104));
        if f64_lt(f64_add(f64_mul(dx, dx), f64_mul(dy, dy)), ps_number(4, 100)) { return 0; }
    }
    return 1;
}
fn ps_house_path(x, y) {
    if !ps_local_mode { return ps_vehicle_plan(x, y, 0); }
    // Plan against the supplied map and camera-observed box only. The world
    // collision guard acts during execution, not as a hidden obstacle sensor.
    let dx = f64_sub(x, ps_pose_x()); let dy = f64_sub(y, ps_pose_y());
    let count = f64_to_i64_nearest(f64_mul(f64_sqrt(f64_add(f64_mul(dx, dx), f64_mul(dy, dy))), f64_from_i64(100))) + 1; let i = 1;
    while i <= count {
        let t = ps_number(i, count);
        if !ps_nav_clear(f64_add(ps_pose_x(), f64_mul(dx, t)), f64_add(ps_pose_y(), f64_mul(dy, t)), ps_pose_heading()) { return 0; } i = i + 1;
    }
    return 1;
}
fn ps_house_pick_base() {
    if ps_collect_enabled { return ps_collect_pick_base(); }
    let original_x = ps_pose_x(); let original_y = ps_pose_y(); let c = f64_cos(ps_pose_heading()); let s = f64_sin(ps_pose_heading());
    let ahead = f64_add(f64_mul(c, f64_sub(load64(ps_case_target), ps_pose_x())), f64_mul(s, f64_sub(load64(ps_case_target + 8), ps_pose_y()))); let step = 0;
    while step <= 240 {
        let offset = (step + 1) / 2; if step % 2 { offset = -offset; }
        let travel = f64_add(f64_sub(ahead, ps_number(20, 100)), ps_number(offset, 1000));
        let x = f64_add(original_x, f64_mul(c, travel)); let y = f64_add(original_y, f64_mul(s, travel));
        let valid = ps_arm_solve_at(ps_case_target, ps_case_pick_height(), 0, x, y, ps_pose_heading()) && ps_arm_solve_at(ps_case_target, 200, 40, x, y, ps_pose_heading());
        let corner = 0; let tx = load64(ps_case_target); let ty = load64(ps_case_target + 8);
        while valid && corner < 4 {
            let dx = -2; let dy = -2; if corner % 2 { dx = 2; } if corner >= 2 { dy = 2; }
            store64(ps_case_target, f64_add(tx, ps_number(dx, 1000))); store64(ps_case_target + 8, f64_add(ty, ps_number(dy, 1000)));
            valid = ps_arm_solve_at(ps_case_target, ps_case_pick_height(), 0, x, y, ps_pose_heading()); corner = corner + 1;
        }
        store64(ps_case_target, tx); store64(ps_case_target + 8, ty);
        if valid && ps_house_path(x, y) { ps_case_grasp_base = x; ps_case_grasp_y = y; return 1; } step = step + 1;
    }
    return 0;
}
fn ps_house_detection(index) {
    // Lighting can split one orange top/side across colour classes. Prefer
    // the larger overlapping component rather than targeting its near edge.
    let a = ps_brick_records + index * 128; let area = (load64(a + 16) - load64(a)) * (load64(a + 24) - load64(a + 8)); let i = 0;
    while i < ps_brick_count {
        let b = ps_brick_records + i * 128; let other = (load64(b + 16) - load64(b)) * (load64(b + 24) - load64(b + 8));
        let width = pb_min(load64(a + 16), load64(b + 16)) - pb_max(load64(a), load64(b)); let height = pb_min(load64(a + 24), load64(b + 24)) - pb_max(load64(a + 8), load64(b + 8));
        if i != index && other > area && width > 0 && height > 0 && width * height * 3 > area {
            let dx = f64_sub(load64(a + 32), load64(b + 32)); let dy = f64_sub(load64(a + 40), load64(b + 40));
            if f64_lt(f64_add(f64_mul(dx, dx), f64_mul(dy, dy)), ps_number(25, 10000)) { return 0; }
        } i = i + 1;
    }
    return 1;
}
fn ps_house_reposition() {
    if ps_collect_enabled { if ps_collect_plan_pick() { return 1; } return ps_case_fail("no observed-space path to the refined RGB grasp pose"); }
    let view = 0;
    while view < 8 {
        let turn = (view + 1) / 2; if !(view % 2) { turn = -turn; }
        let heading = pb_wrap_pi(f64_add(ps_pose_heading(), f64_mul(f64_from_i64(turn), f64_div(PB_PI, f64_from_i64(4)))));
        let c = f64_cos(heading); let s = f64_sin(heading); let i = 0;
        while i < 3 {
            let lateral = ps_number(8, 100); if i == 1 { lateral = 0; } if i == 2 { lateral = ps_number(-8, 100); }
            let x = f64_add(f64_sub(load64(ps_case_target), f64_mul(c, ps_number(22, 100))), f64_mul(s, lateral));
            let y = f64_sub(f64_sub(load64(ps_case_target + 8), f64_mul(s, ps_number(22, 100))), f64_mul(c, lateral));
            let valid = ps_arm_solve_at(ps_case_target, ps_case_pick_height(), 0, x, y, heading) && ps_arm_solve_at(ps_case_target, 200, 40, x, y, heading);
            ps_house_returning = 3;
            if valid && ps_nav_plan(x, y, heading) { ps_case_phase(21); return 1; } i = i + 1;
        }
        view = view + 1;
    }
    return ps_case_fail("no collision-free reachable approach to the RGB brick target");
}
fn ps_house_probe_drive(point, speed, steering) {
    let distance = ps_number(speed, 10000); let angle = pb_radians(f64_from_i64(steering * 45 / 100));
    let heading = pb_wrap_pi(f64_sub(load64(point + 16), f64_mul(f64_div(distance, ps_number(18, 100)), f64_div(f64_sin(angle), f64_cos(angle)))));
    let x = f64_add(load64(point), f64_mul(distance, f64_cos(heading))); let y = f64_add(load64(point + 8), f64_mul(distance, f64_sin(heading)));
    if !ps_nav_transition_clear(x, y, heading, load64(point), load64(point + 8), load64(point + 16)) { return 0; }
    let corner = 0;
    while corner < 4 {
        let dx = ps_number(-5, 1000); let dy = dx; if corner % 2 { dx = pb_neg(dx); } if corner >= 2 { dy = pb_neg(dy); }
        if !ps_nav_clear(f64_add(x, dx), f64_add(y, dy), heading) { return 0; } corner = corner + 1;
    }
    store64(point, x); store64(point + 8, y); store64(point + 16, heading); return 1;
}
fn ps_house_probe_heading(point, target) {
    let i = 0;
    while i < 200 {
        let error = pb_wrap_pi(f64_sub(target, load64(point + 16)));
        if f64_lt(f64_magnitude(error), ps_number(1, 1000)) { return 1; }
        let steering = 100; if f64_lt(error, 0) { steering = -100; }
        let speed = -pb_clamp(f64_to_i64_nearest(f64_mul(f64_magnitude(error), f64_from_i64(1800))), 1, 40);
        if !ps_house_probe_drive(point, speed, steering) { return 0; } i = i + 1;
    }
    return 0;
}
fn ps_house_parking_clear(point, target) {
    // Simulate the production parking corrections over observed floor before
    // accepting a coarse Hybrid A* arrival. Only the scratch pose is changed.
    let heading = load64(target + 16); if !ps_house_probe_heading(point, heading) { return 0; } let i = 0; let aligned = 0;
    while i < 4 && !aligned {
        let dx = f64_sub(load64(target), load64(point)); let dy = f64_sub(load64(target + 8), load64(point + 8));
        let lateral = f64_sub(f64_mul(f64_cos(heading), dy), f64_mul(f64_sin(heading), dx));
        if f64_lt(f64_magnitude(lateral), ps_number(2, 1000)) { aligned = 1; }
        else {
            let co = f64_sub(PB_ONE, f64_div(f64_magnitude(lateral), ps_number(36, 100))); if f64_lt(co, 0) { return 0; }
            let angle = f64_atan2(f64_sqrt(f64_sub(PB_ONE, f64_mul(co, co))), co); if f64_gt(lateral, 0) { angle = pb_neg(angle); }
            if !ps_house_probe_heading(point, pb_wrap_pi(f64_add(heading, angle))) || !ps_house_probe_heading(point, heading) { return 0; }
        } i = i + 1;
    }
    if !aligned { return 0; } i = 0;
    while i < 256 {
        let remaining = f64_add(f64_mul(f64_sub(load64(target), load64(point)), f64_cos(heading)), f64_mul(f64_sub(load64(target + 8), load64(point + 8)), f64_sin(heading)));
        if !f64_gt(f64_magnitude(remaining), ps_number(1, 1000)) { return 1; }
        if !ps_house_probe_drive(point, pb_clamp(f64_to_i64_nearest(f64_mul(remaining, f64_from_i64(10000))), -40, 40), 0) { return 0; } i = i + 1;
    }
    return 0;
}
fn ps_house_park_drive(speed, steering) {
    if ps_collect_enabled && !ps_collect_drive_clear(speed, steering) {
        pb_drive_stop(pb_robot_drive(ps_robot), ps_time);
        if ps_gripper_held { ps_case_survey_index = 0; return ps_case_tcp_survey(); }
        ps_collect_map_until = ps_discovery_scans + 1;
        return ps_collect_recover_target("pickup parking requires another floor scan");
    }
    pb_drive_steer(pb_robot_drive(ps_robot), speed, steering, ps_time); return 1;
}
fn ps_house_park_heading(target) {
    let error = pb_wrap_pi(f64_sub(target, ps_pose_heading()));
    if f64_lt(f64_magnitude(error), ps_number(1, 1000)) { pb_drive_stop(pb_robot_drive(ps_robot), ps_time); return 1; }
    let steering = 100; if f64_lt(error, 0) { steering = -100; }
    let speed = pb_clamp(f64_to_i64_nearest(f64_mul(f64_magnitude(error), f64_from_i64(1800))), 1, 40);
    ps_house_park_drive(-speed, steering); return 0;
}
fn ps_house_park_to(target) {
    if ps_blocked { return ps_case_fail("collision guard stopped home parking"); }
    let heading = load64(target + 16);
    if !ps_house_parking { if ps_house_park_heading(heading) { ps_house_parking = 1; } return 1; }
    if ps_house_parking == 1 {
        let dx = f64_sub(load64(target), ps_pose_x()); let dy = f64_sub(load64(target + 8), ps_pose_y());
        let lateral = f64_sub(f64_mul(f64_cos(heading), dy), f64_mul(f64_sin(heading), dx));
        if f64_lt(f64_magnitude(lateral), ps_number(2, 1000)) { ps_house_parking = 4; return 1; }
        // Two reverse 0.18 m-radius arcs shift sideways and restore heading.
        // Parking uses remembered odometry, never a hidden container pose.
        let co = f64_sub(PB_ONE, f64_div(f64_magnitude(lateral), ps_number(36, 100)));
        if f64_lt(co, 0) { return ps_case_fail("home parking correction exceeds local manoeuvre space"); }
        let angle = f64_atan2(f64_sqrt(f64_sub(PB_ONE, f64_mul(co, co))), co); if f64_gt(lateral, 0) { angle = pb_neg(angle); }
        ps_house_park_angle = pb_wrap_pi(f64_add(heading, angle)); ps_house_parking = 2; return 1;
    }
    if ps_house_parking == 2 { if ps_house_park_heading(ps_house_park_angle) { ps_house_parking = 3; } return 1; }
    if ps_house_parking == 3 { if ps_house_park_heading(heading) { ps_house_parking = 1; } return 1; }
    let remaining = f64_add(f64_mul(f64_sub(load64(target), ps_pose_x()), f64_cos(heading)), f64_mul(f64_sub(load64(target + 8), ps_pose_y()), f64_sin(heading)));
    if f64_gt(f64_magnitude(remaining), ps_number(1, 1000)) {
        ps_house_park_drive(pb_clamp(f64_to_i64_nearest(f64_mul(remaining, f64_from_i64(10000))), -40, 40), 0); return 1;
    }
    pb_drive_stop(pb_robot_drive(ps_robot), ps_time); return 2;
}
fn ps_house_park_update() {
    if ps_blocked {
        pb_drive_stop(pb_robot_drive(ps_robot), ps_time); ps_dock_search_blocks = ps_dock_search_blocks + 1; ps_case_survey_index = 0; return ps_case_tcp_survey();
    }
    let result = ps_house_park_to(ps_house_home); if result == 2 { return ps_case_tcp_survey(); } return result;
}
fn ps_house_pick_park_update() {
    if ps_house_park_to(ps_nav_goal) != 2 { return 1; }
    if ps_collect_enabled { return ps_collect_staging_inspect(); }
    if !ps_house_pick_base() { return ps_case_fail("RGB pickup approach remains unreachable after precise parking"); }
    ps_case_phase(2); return 1;
}
fn ps_house_learn_dock() {
    pb_drive_stop(pb_robot_drive(ps_robot), ps_time);
    if ps_case_steps % 10 == 1 { ps_dock_sample(); }
    if !ps_dock_fresh() || ps_dock_stable < 3 { return 1; }
    ps_house_ready = 1;
    if !ps_case_travel_pose() { return ps_case_fail("cannot aim the TCP camera after learning the box"); }
    ps_case_phase(14); return 1;
}
fn ps_house_update() {
    let dx = f64_sub(ps_pose_x(), load64(ps_house_previous)); let dy = f64_sub(ps_pose_y(), load64(ps_house_previous + 8));
    ps_house_distance = f64_add(ps_house_distance, f64_sqrt(f64_add(f64_mul(dx, dx), f64_mul(dy, dy)))); store64(ps_house_previous, ps_pose_x()); store64(ps_house_previous + 8, ps_pose_y());
    if ps_stock_pickup && ps_stock_phase == 5 { return ps_case_fail(ps_stock_reason); }
    if ps_stock_pickup && ps_stock_phase == 1 { pb_drive_stop(pb_robot_drive(ps_robot), ps_time); return 1; }
    if ps_stock_pickup && ps_house_returning == 1 {
        if !ps_gripper_held { return ps_case_fail("brick lost during stock-landmark return"); }
        if ps_stock_phase == 4 { return ps_case_tcp_survey(); } return 1;
    }
    if !ps_house_returning && ps_case_steps % 10 == 1 {
        if !ps_brick_sample() { return ps_case_fail("cannot read forward TCP camera during room search"); }
        ps_floor_observe(); let found = ps_case_camera_select(); ps_brick_mark(); if found { return 1; }
        if ps_floor_changed {
            ps_floor_changed = 0;
            if !ps_house_plan_view(ps_nav_goal) { return ps_case_fail("no mapped path around camera-observed floor bricks"); }
        }
    }
    if ps_blocked {
        ps_house_block_replans = ps_house_block_replans + 1;
        if ps_house_block_replans > 8 { return ps_case_fail("room navigation exhausted its protective-stop replans"); }
        let dx = f64_sub(ps_pose_x(), load64(ps_dock_frame + 96)); let dy = f64_sub(ps_pose_y(), load64(ps_dock_frame + 104));
        if ps_house_returning == 1 && ps_gripper_held && f64_lt(f64_add(f64_mul(dx, dx), f64_mul(dy, dy)), PB_ONE) {
            pb_drive_stop(pb_robot_drive(ps_robot), ps_time); ps_dock_search_blocks = ps_dock_search_blocks + 1; ps_case_survey_index = 0; return ps_case_tcp_survey();
        }
        ps_nav_contact_add(); pb_drive_stop(pb_robot_drive(ps_robot), ps_time);
        if !ps_house_plan_view(ps_nav_goal) { return ps_case_fail("no safe room route after a protective stop"); } return 1;
    }
    if ps_crumb_replan && !ps_crumb_repeat {
        ps_crumb_replan = 0;
        if !ps_house_plan_view(ps_nav_goal) { return ps_case_fail("no safe route after TCP visual odometry correction"); }
    }
    if ps_house_returning == 1 && !ps_gripper_held { return ps_case_fail("brick lost during room-to-room carry"); }
    if ps_crumb_enabled && ps_crumb_repeat && ps_house_returning == 1 { return ps_crumb_return_tick(); }
    if !ps_nav_tick() { return 1; }
    if ps_house_returning == 3 {
        if ps_collect_enabled { ps_house_parking = 0; ps_case_phase(25); return 1; }
        if !ps_house_pick_base() { ps_house_parking = 0; ps_case_phase(25); return 1; } ps_case_phase(2); return 1;
    }
    if ps_house_returning { ps_house_parking = 0; ps_case_phase(22); return 1; }
    ps_house_waypoint = ps_house_waypoint + 1;
    if ps_house_waypoint >= ps_case_coverage_count { ps_house_waypoint = 0; ps_house_laps = ps_house_laps + 1; }
    if ps_house_laps >= 2 { return ps_case_fail("searched the room coverage route twice without finding all bricks"); }
    return ps_house_begin(0);
}
fn ps_house_observation(b) {
    if !ps_house_enabled() { return 0; }
    pl_text(b, ",\"navigation\":{\"planner\":\"hybrid-a-star-ackermann-v1\",\"mapSource\":"); if ps_discovery_enabled { pj_text(b, "tcp-rgb-active-stereo"); } else { pj_text(b, "known-blender-static-colliders"); } pl_text(b, ",\"localization\":");
    if ps_crumb_enabled { pj_text(b, "wheel-steering-and-tcp-rgb-features"); } else if ps_local_mode { pj_text(b, "wheel-steering-command-integration"); } else { pj_text(b, "simulator-odometry"); }
    pl_text(b, ",\"objectTargets\":\"camera-rgb-only\",\"returning\":"); pj_bool_text(b, ps_house_returning);
    pl_text(b, ",\"rememberedRgbObstacles\":"); pl_int(b, ps_floor_count);
    pl_text(b, ",\"failedCommandConstraints\":"); pl_int(b, ps_nav_contact_count);
    pl_text(b, ",\"coverageWaypoint\":"); pl_int(b, ps_house_waypoint); pl_text(b, ",\"coverageCount\":"); pl_int(b, ps_case_coverage_count); pl_text(b, ",\"laps\":"); pl_int(b, ps_house_laps);
    pl_text(b, ",\"plans\":"); pl_int(b, ps_nav_plans); pl_text(b, ",\"expanded\":"); pl_int(b, ps_nav_expanded); pl_text(b, ",\"distanceM\":"); pl_float(b, ps_house_distance);
    pl_text(b, ",\"pathIndex\":"); pl_int(b, ps_nav_path_index); pl_text(b, ",\"pathCount\":"); pl_int(b, ps_nav_path_count);
    pl_text(b, ",\"goal\":["); let i = 0; while i < 3 { if i { pl_char(b, 44); } pl_float(b, load64(ps_nav_goal + i * 8)); i = i + 1; } return pl_text(b, "]}");
}
