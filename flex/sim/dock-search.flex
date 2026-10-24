// Search a ring of camera viewpoints around the last RGB box observation.
// Only remembered image geometry, estimated odometry and the supplied map
// supply goals. Live body poses remain private to collision guards/judging.
import "house.flex";

global ps_dock_search_active = 0;
global ps_dock_search_index = 0;
global ps_dock_search_mode = 0;
global ps_dock_search_started = 0;
global ps_dock_search_wait = 0;
global ps_dock_search_anchor = 0;
global ps_dock_search_goal = 0;
global ps_dock_search_blocks = 0;
global ps_dock_search_staging = 0;
global ps_dock_search_staged = 0;
global ps_dock_search_hint = 0;
global ps_dock_search_view_start = 0;

fn ps_dock_search_reset() {
    ps_dock_search_active = 0; ps_dock_search_index = 0; ps_dock_search_mode = 0; ps_dock_search_started = 0; ps_dock_search_blocks = 0; ps_dock_search_staged = 0; ps_dock_search_hint = 0; ps_dock_search_view_start = 0; return 0;
}
fn ps_dock_search_candidate(index, out) {
    // Clockwise viewpoints change both position and heading. The camera's
    // original box-facing orientation rotates with each point on the ring.
    let angle = pb_neg(f64_mul(PB_TAU, ps_number((index - ps_dock_search_view_start) % 12, 12)));
    let radius = ps_number(36, 100); if index >= 12 { radius = ps_number(46, 100); } if index >= 24 { radius = ps_number(30, 100); }
    let bearing = f64_add(load64(ps_dock_search_anchor + 16), angle);
    store64(out, f64_add(load64(ps_dock_search_anchor), f64_mul(radius, f64_cos(bearing))));
    store64(out + 8, f64_add(load64(ps_dock_search_anchor + 8), f64_mul(radius, f64_sin(bearing))));
    store64(out + 16, pb_wrap_pi(f64_add(load64(ps_dock_search_anchor + 24), angle))); return 1;
}
fn ps_dock_search_stage() {
    // Once RGB supplies the box pose, search actual arm-feasible staging
    // poses instead of circling merely to obtain another view of it.
    if !ps_dock_search_staging { ps_dock_search_staging = alloc(24); }
    let best = f64_from_i64(100); let found = 0; let view = 0;
    while view < 24 {
        let angle = pb_neg(f64_mul(PB_TAU, ps_number(view, 24)));
        let bearing = f64_add(load64(ps_dock_search_anchor + 16), angle); let radius = 28;
        while radius <= 40 {
            let x = f64_add(load64(ps_dock_frame + 96), f64_mul(ps_number(radius, 100), f64_cos(bearing)));
            let y = f64_add(load64(ps_dock_frame + 104), f64_mul(ps_number(radius, 100), f64_sin(bearing))); let turn = 0;
            while turn < 5 {
                let offset = (turn + 1) / 2; if !(turn % 2) { offset = -offset; }
                let heading = pb_wrap_pi(f64_add(f64_add(load64(ps_dock_search_anchor + 24), angle), f64_mul(PB_TAU, ps_number(offset, 24))));
                let dx = f64_sub(x, ps_pose_x()); let dy = f64_sub(y, ps_pose_y()); let distance = f64_sqrt(f64_add(f64_mul(dx, dx), f64_mul(dy, dy)));
                let score = f64_add(distance, f64_mul(ps_number(1, 10), f64_magnitude(pb_wrap_pi(f64_sub(heading, ps_pose_heading())))));
                if f64_gt(distance, ps_number(5, 100)) && f64_lt(score, best) && ps_nav_clear(x, y, heading) && ps_case_drop_clearance(180, x, y, heading) {
                    best = score; found = 1; store64(ps_dock_search_staging, x); store64(ps_dock_search_staging + 8, y); store64(ps_dock_search_staging + 16, heading);
                }
                turn = turn + 1;
            }
            radius = radius + 4;
        }
        view = view + 1;
    }
    if !found || !ps_nav_plan(load64(ps_dock_search_staging), load64(ps_dock_search_staging + 8), load64(ps_dock_search_staging + 16)) { return 0; }
    pb_copy(ps_dock_search_goal, ps_dock_search_staging, 24); return 1;
}
fn ps_dock_search_next() {
    pb_drive_stop(pb_robot_drive(ps_robot), ps_time);
    ps_dock_search_staged = 0;
    if ps_dock_search_index < 36 && ps_dock_fresh() && ps_dock_stable >= 3 && ps_dock_search_stage() {
        if !ps_case_travel_pose() { return ps_case_fail("cannot aim the TCP camera before docking travel"); }
        ps_dock_search_index = ps_dock_search_index + 1; ps_dock_search_mode = 3; ps_dock_search_staged = 1; return 1;
    }
    while ps_dock_search_index < 36 {
        ps_dock_search_candidate(ps_dock_search_index, ps_dock_search_goal); ps_dock_search_index = ps_dock_search_index + 1;
        if ps_nav_plan(load64(ps_dock_search_goal), load64(ps_dock_search_goal + 8), load64(ps_dock_search_goal + 16)) {
            if !ps_case_travel_pose() { return ps_case_fail("cannot aim the TCP camera before box search travel"); }
            ps_dock_search_mode = 1; return 1;
        }
    }
    return ps_case_fail("box not reacquired from the bounded circular camera search");
}
fn ps_dock_search_attention() {
    // A partial sighting can retarget exploration once. Keep its reference
    // fixed across the sweep instead of rotating every subsequent goal.
    if ps_dock_search_hint || ps_dock_fresh() || !ps_dock_hint_fresh() { return 0; }
    store64(ps_dock_search_anchor, load64(ps_dock_hint)); store64(ps_dock_search_anchor + 8, load64(ps_dock_hint + 8));
    store64(ps_dock_search_anchor + 16, f64_atan2(f64_sub(ps_pose_y(), load64(ps_dock_hint + 8)), f64_sub(ps_pose_x(), load64(ps_dock_hint))));
    store64(ps_dock_search_anchor + 24, ps_pose_heading());
    ps_dock_search_hint = 1; ps_dock_search_view_start = ps_dock_search_index; return 1;
}
fn ps_dock_search_begin() {
    if ps_dock_seen < 0 { return ps_case_fail("circular box search needs a previously learned RGB box"); }
    if !ps_dock_search_anchor { ps_dock_search_anchor = alloc(32); ps_dock_search_goal = alloc(24); }
    if !ps_dock_search_active {
        ps_dock_search_index = 0; ps_dock_search_started = ps_total; ps_dock_search_hint = 0; ps_dock_search_view_start = 0;
        store64(ps_dock_search_anchor, load64(ps_dock_frame + 96)); store64(ps_dock_search_anchor + 8, load64(ps_dock_frame + 104));
        store64(ps_dock_search_anchor + 16, f64_atan2(f64_sub(load64(ps_house_home + 8), load64(ps_dock_frame + 104)), f64_sub(load64(ps_house_home), load64(ps_dock_frame + 96))));
        store64(ps_dock_search_anchor + 24, load64(ps_house_home + 16)); ps_dock_search_active = 1;
    }
    ps_dock_search_attention();
    ps_case_phase(24); return ps_dock_search_next();
}
fn ps_dock_search_reachable() {
    if ps_nav_clear(ps_pose_x(), ps_pose_y(), ps_pose_heading()) && ps_case_drop_clearance(180, ps_pose_x(), ps_pose_y(), ps_pose_heading()) { return 1; }
    let step = 1;
    while step <= 16 {
        let offset = ps_number(((step + 1) / 2) * 10, 1000); if !(step % 2) { offset = pb_neg(offset); }
        let x = f64_add(ps_pose_x(), f64_mul(offset, f64_cos(ps_pose_heading()))); let y = f64_add(ps_pose_y(), f64_mul(offset, f64_sin(ps_pose_heading())));
        if ps_nav_clear(x, y, ps_pose_heading()) && ps_case_drop_clearance(180, x, y, ps_pose_heading()) { return 1; } step = step + 1;
    }
    return 0;
}
fn ps_dock_search_update() {
    if !ps_gripper_held { return ps_case_fail("brick lost during circular box search"); }
    if ps_total - ps_dock_search_started > 12000 { return ps_case_fail("circular box search exhausted its time budget"); }
    if !ps_pickup_settled() { pb_drive_stop(pb_robot_drive(ps_robot), ps_time); return 1; }
    if ps_blocked { ps_dock_search_blocks = ps_dock_search_blocks + 1; pb_drive_stop(pb_robot_drive(ps_robot), ps_time); ps_case_survey_index = 0; return ps_case_tcp_survey(); }
    if ps_dock_search_mode == 4 {
        if ps_house_park_to(ps_dock_search_goal) != 2 { return 1; }
        ps_case_survey_index = 0; return ps_case_tcp_survey();
    }
    if !ps_nav_tick() { return 1; }
    if ps_dock_search_staged { ps_house_parking = 0; ps_dock_search_mode = 4; return 1; }
    pb_drive_stop(pb_robot_drive(ps_robot), ps_time); ps_case_survey_index = 0; return ps_case_tcp_survey();
}
fn ps_dock_search_observation(b) {
    pl_text(b, ",\"boxSearch\":{\"strategy\":\"circular-camera-viewpoints\",\"active\":"); pj_bool_text(b, ps_case_stage == 24);
    pl_text(b, ",\"viewpoint\":"); pl_int(b, ps_dock_search_index); pl_text(b, ",\"maxViewpoints\":36,\"blockedMoves\":"); pl_int(b, ps_dock_search_blocks);
    if ps_dock_search_active {
        pl_text(b, ",\"centreM\":["); pl_float(b, load64(ps_dock_search_anchor)); pl_char(b, 44); pl_float(b, load64(ps_dock_search_anchor + 8));
        pl_text(b, "],\"goal\":["); let i = 0; while i < 3 { if i { pl_char(b, 44); } pl_float(b, load64(ps_dock_search_goal + i * 8)); i = i + 1; } pl_char(b, 93);
    }
    return pl_text(b, "}");
}
