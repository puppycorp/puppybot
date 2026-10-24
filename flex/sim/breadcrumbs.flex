// Visual teach-and-repeat using the wrist camera in its driving pose. Estimated
// poses label images; RGB feature geometry supplies every pose correction.
import "breadcrumb-features.flex";
import "ground-heading.flex";
import "vision.flex";

global ps_crumb_enabled = 0;
global ps_crumb_repeat = 0;
global ps_crumb_apply = 1;
global ps_crumb_output = 0;
global ps_crumb_target = 0;
global ps_crumb_rgb = 0;
global ps_crumb_args = 0;
global ps_crumb_nodes = 0;
global ps_crumb_count = 0;
global ps_crumb_cursor = -1;
global ps_crumb_parking = 0;
global ps_crumb_wait = 0;
global ps_crumb_recording = 0;
global ps_crumb_last = 0;
global ps_crumb_last_count = 0;
global ps_crumb_last_pose = 0;
global ps_crumb_pose = 0;
global ps_crumb_prior = 0;
global ps_crumb_features = 0;
global ps_crumb_samples = 0;
global ps_crumb_corrections = 0;
global ps_crumb_key_matches = 0;
global ps_crumb_seen = -1;
global ps_crumb_matched = -1;
global ps_crumb_replan = 0;
global ps_crumb_log = -1;
global ps_crumb_trip = 0;
global ps_crumb_frame = -1;
global ps_crumb_axis = 0;
global ps_crumb_axis_known = 0;
global ps_crumb_heading_corrections = 0;

fn ps_crumb_reset() {
    ps_crumb_count = 0; ps_crumb_cursor = -1; ps_crumb_parking = 0; ps_crumb_wait = 0; ps_crumb_recording = 0; ps_crumb_last_count = 0;
    ps_crumb_samples = 0; ps_crumb_corrections = 0; ps_crumb_key_matches = 0; ps_crumb_seen = -1; ps_crumb_matched = -1; ps_crumb_replan = 0; ps_crumb_trip = 0; ps_crumb_frame = -1;
    ps_crumb_axis_known = 0; ps_crumb_heading_corrections = 0;
    ps_ground_heading = 0; ps_ground_confidence = 0; ps_ground_samples = 0;
    if ps_crumb_log >= 0 { syscall(3, ps_crumb_log, 0, 0, 0, 0, 0); ps_crumb_log = -1; } return 0;
}
fn ps_crumb_init() {
    if ps_crumb_target { return 1; } ps_cf_init(); ps_crumb_target = ps_vision_target_create(); if !ps_crumb_target { return 0; }
    ps_crumb_rgb = alloc(640 * 480 * 3); ps_crumb_args = alloc(88); ps_crumb_nodes = alloc(256 * 64); ps_crumb_last = alloc(384 * 48);
    ps_crumb_last_pose = alloc(24); ps_crumb_pose = alloc(24); ps_crumb_prior = alloc(24); return 1;
}
fn ps_crumb_current_pose(out) { store64(out, ps_pose_x()); store64(out + 8, ps_pose_y()); store64(out + 16, ps_pose_heading()); return out; }
fn ps_crumb_distance(pose) { let dx = f64_sub(ps_pose_x(), load64(pose)); let dy = f64_sub(ps_pose_y(), load64(pose + 8)); return f64_sqrt(f64_add(f64_mul(dx, dx), f64_mul(dy, dy))); }
fn ps_crumb_sample() {
    if !ps_crumb_init() { return 0; } let target = ps_render_target; let mode = ps_camera_mode; ps_render_target = ps_crumb_target; ps_camera_mode = 2; ps_scene(640, 480, 0, 0);
    pb_zero(ps_crumb_args, 88); store64(ps_crumb_args + 16, 640); store64(ps_crumb_args + 24, 480); store64(ps_crumb_args + 32, 0x1907); store64(ps_crumb_args + 40, 0x1401); store64(ps_crumb_args + 48, ps_crumb_rgb);
    render_gl(ps_device, "glPixelStorei", 0x0d05, 1, 0, 0, 0, 0); ffi_call_words(gui_gl_cached_proc(load64(ps_device), "glReadPixels"), ps_crumb_args);
    let row = alloc(1920); let y = 0;
    while y < 240 { let a = ps_crumb_rgb + y * 1920; let b = ps_crumb_rgb + (479 - y) * 1920; pb_copy(row, a, 1920); pb_copy(a, b, 1920); pb_copy(b, row, 1920); y = y + 1; }
    syscall(11, row, 1920, 0, 0, 0, 0); ps_render_target = target; ps_camera_mode = mode;
    ps_cf_calibrate(); ps_crumb_features = ps_cf_extract(ps_crumb_rgb, ps_pose_heading(), ps_cf_points); ps_crumb_samples = ps_crumb_samples + 1; ps_crumb_frame = ps_total; return 1;
}
fn ps_crumb_capture(name) {
    if !ps_crumb_output { return 1; } let mode = ps_camera_mode; let target = ps_render_target; ps_camera_mode = 2; ps_render_target = ps_crumb_target;
    render_gl(ps_device, "glBindFramebuffer", 0x8d40, load64(ps_crumb_target + 16), 0, 0, 0, 0); ps_camera_update(640, 480);
    let ok = ps_capture_at(h_cat3(ps_crumb_output, "/", name), ps_total, ps_time); ps_camera_mode = mode; ps_render_target = target; return ok;
}
fn ps_crumb_event(kind) {
    if !ps_crumb_output { return 0; }
    if ps_crumb_log < 0 {
        let made = syscall(83, ps_crumb_output, 493, 0, 0, 0, 0); if made && made != -17 { return 0; }
        ps_crumb_log = syscall(2, h_cat3(ps_crumb_output, "/events-", h_cat(h_int(ps_episode), ".jsonl")), 0x800c1, 384, 0, 0, 0); if ps_crumb_log < 0 { return 0; }
    }
    let text = alloc(2048); let b = alloc(32); pl_builder(b, text, 2048); pl_text(b, "{\"event\":"); pj_text(b, kind); pl_text(b, ",\"frameId\":"); pl_int(b, ps_total);
    pl_text(b, ",\"trip\":"); pl_int(b, ps_crumb_trip); pl_text(b, ",\"count\":"); pl_int(b, ps_crumb_count); pl_text(b, ",\"cursor\":"); pl_int(b, ps_crumb_cursor);
    pl_text(b, ",\"inliers\":"); pl_int(b, ps_cf_inliers); pl_text(b, ",\"features\":"); pl_int(b, ps_crumb_features); pl_text(b, ",\"pose\":["); let i = 0;
    while i < 3 { if i { pl_char(b, 44); } pl_float(b, load64(ps_crumb_pose + i * 8)); i = i + 1; } pl_text(b, "],\"prior\":["); i = 0;
    while i < 3 { if i { pl_char(b, 44); } pl_float(b, load64(ps_crumb_prior + i * 8)); i = i + 1; } pl_text(b, "]}\n");
    if !load64(b + 24) { pl_write(ps_crumb_log, text, load64(b + 8)); } syscall(11, text, 2048, 0, 0, 0, 0); syscall(11, b, 32, 0, 0, 0, 0); return 1;
}
fn ps_crumb_reference() {
    pb_copy(ps_crumb_last, ps_cf_points, ps_crumb_features * 48); ps_crumb_last_count = ps_crumb_features; ps_crumb_current_pose(ps_crumb_last_pose); return 1;
}
fn ps_crumb_save() {
    if ps_crumb_features < 60 || ps_crumb_count >= 256 { return 0; } let n = ps_crumb_nodes + ps_crumb_count * 64;
    ps_crumb_current_pose(n); store64(n + 24, ps_total); if !load64(n + 32) { store64(n + 32, alloc(384 * 48)); }
    pb_copy(load64(n + 32), ps_cf_points, ps_crumb_features * 48); store64(n + 40, ps_crumb_features); ps_crumb_count = ps_crumb_count + 1;
    ps_crumb_current_pose(ps_crumb_pose); pb_copy(ps_crumb_prior, ps_crumb_pose, 24); ps_crumb_event("save");
    if ps_crumb_output { ps_crumb_capture(h_cat3("checkpoint-", h_int(ps_total), ".png")); }
    return 1;
}
fn ps_crumb_depart() {
    if !ps_crumb_enabled || !ps_house_ready { return 1; }
    if !ps_crumb_recording {
        ps_crumb_trip = ps_crumb_trip + 1; ps_crumb_count = pb_min(ps_crumb_count, 1); ps_crumb_cursor = -1; ps_crumb_recording = 1;
        if !ps_crumb_sample() { return 0; } if !ps_crumb_count { ps_crumb_save(); } ps_crumb_reference();
    } return 1;
}
fn ps_crumb_ground_heading() {
    if !ps_crumb_axis_known {
        let index = 0;
        while index < ps_environment_count {
            let r = ps_environment + 256 + index * 128;
            if pl_case_equal(r, 5, "Wall.") { ps_crumb_axis = load64(r + 96); ps_crumb_axis_known = 1; index = ps_environment_count; } index = index + 1;
        }
    }
    if !ps_crumb_axis_known || !ps_ground_heading_read() { return 0; }
    let observed = f64_sub(ps_crumb_axis, ps_ground_heading);
    let quadrant = f64_to_i64_nearest(f64_div(f64_sub(ps_local_heading, observed), PB_HALF_PI));
    observed = f64_add(observed, f64_mul(f64_from_i64(quadrant), PB_HALF_PI)); let delta = pb_wrap_pi(f64_sub(observed, ps_local_heading));
    if f64_gt(f64_magnitude(delta), ps_number(25, 100)) { return 0; }
    delta = f64_mul(delta, ps_number(1, 2)); ps_local_heading = pb_wrap_pi(f64_add(ps_local_heading, delta));
    ps_local_visual_heading = f64_add(ps_local_visual_heading, delta); ps_crumb_heading_corrections = ps_crumb_heading_corrections + 1; return 1;
}
fn ps_crumb_poll() {
    if !ps_crumb_enabled || !ps_house_enabled() || !ps_house_ready || !ps_crumb_recording || ps_total % 10 != 1 { return 0; }
    if !ps_camera_drive_mode { ps_crumb_last_count = 0; ps_ground_confidence = 0; ps_ground_samples = 0; return 0; }
    if !ps_camera_still() { ps_crumb_last_count = 0; return 0; }
    let d = pb_robot_drive(ps_robot); if !load64(d + 48) && !load64(d + 56) && ps_crumb_cursor < 0 { return 0; }
    if !ps_crumb_sample() { return 0; } ps_crumb_current_pose(ps_crumb_prior); let reference = ps_crumb_last; let count = ps_crumb_last_count; let pose = ps_crumb_last_pose; let key = 0;
    if !count { ps_crumb_reference(); return 1; }
    if ps_crumb_cursor >= 0 {
        let n = ps_crumb_nodes + ps_crumb_cursor * 64;
        if f64_lt(ps_crumb_distance(n), ps_number(18, 100)) && f64_lt(f64_magnitude(pb_wrap_pi(f64_sub(ps_pose_heading(), load64(n + 16)))), ps_number(2, 10)) { reference = load64(n + 32); count = load64(n + 40); pose = n; key = 1; }
    }
    // Consecutive frames are only 200 ms apart. Wheel integration bounds
    // association; a body-fixed feature must not cancel six centimetres of
    // measured travel by matching itself in the next image.
    ps_cf_gate_mm = 12; if key { ps_cf_gate_mm = 65; }
    if ps_cf_fit(ps_cf_points, ps_crumb_features, reference, count, pose, ps_crumb_prior) {
        pb_copy(ps_crumb_pose, ps_cf_result, 24); let dx = f64_sub(load64(ps_crumb_pose), ps_local_x); let dy = f64_sub(load64(ps_crumb_pose + 8), ps_local_y); let dh = pb_wrap_pi(f64_sub(load64(ps_crumb_pose + 16), ps_local_heading));
        if ps_crumb_apply {
            ps_local_x = load64(ps_crumb_pose); ps_local_y = load64(ps_crumb_pose + 8); ps_local_heading = load64(ps_crumb_pose + 16);
            ps_local_visual_x = f64_add(ps_local_visual_x, dx); ps_local_visual_y = f64_add(ps_local_visual_y, dy); ps_local_visual_heading = f64_add(ps_local_visual_heading, dh);
            if f64_gt(f64_add(f64_mul(dx, dx), f64_mul(dy, dy)), ps_number(225, 1000000)) || f64_gt(f64_magnitude(dh), ps_number(25, 1000)) { ps_crumb_replan = 1; }
            ps_crumb_corrections = ps_crumb_corrections + 1;
        }
        if key { ps_crumb_seen = ps_total; ps_crumb_matched = ps_crumb_cursor; ps_crumb_key_matches = ps_crumb_key_matches + 1; ps_crumb_event("checkpoint-match"); }
        else { ps_crumb_event("temporal-match"); }
    }
    ps_crumb_ground_heading();
    // Keep a short-lived reference across several frames instead of
    // integrating a new pixel/rounding error at every 200 ms sample.
    if f64_gt(ps_crumb_distance(ps_crumb_last_pose), ps_number(15, 100)) || f64_gt(f64_magnitude(pb_wrap_pi(f64_sub(ps_pose_heading(), load64(ps_crumb_last_pose + 16)))), ps_number(15, 100)) { ps_crumb_reference(); }
    if ps_crumb_cursor < 0 && !ps_house_returning && ps_crumb_count {
        let n = ps_crumb_nodes + (ps_crumb_count - 1) * 64;
        if ps_cf_inliers >= 12 && (f64_gt(ps_crumb_distance(n), ps_number(18, 100)) || f64_gt(f64_magnitude(pb_wrap_pi(f64_sub(ps_pose_heading(), load64(n + 16)))), ps_number(18, 100))) { ps_crumb_save(); }
    } return 1;
}
fn ps_crumb_plan() {
    let target = ps_crumb_nodes + ps_crumb_cursor * 64; pb_drive_stop(pb_robot_drive(ps_robot), ps_time); ps_house_parking = 0; ps_crumb_parking = 0; ps_crumb_wait = 0; ps_crumb_replan = 0;
    if !ps_nav_plan(load64(target), load64(target + 8), load64(target + 16)) { return ps_case_fail("no mapped route to the next visual breadcrumb"); } return 1;
}
fn ps_crumb_return_begin() {
    ps_crumb_cursor = ps_crumb_count - 1; if ps_crumb_cursor < 0 { return ps_case_fail("no visual breadcrumbs recorded"); }
    if !ps_crumb_plan() { return 0; } ps_case_phase(21); return 1;
}
fn ps_crumb_return_tick() {
    if ps_crumb_replan && !ps_crumb_parking && !ps_crumb_plan() { return 0; }
    if !ps_crumb_parking { if !ps_nav_tick() { return 1; } ps_crumb_parking = 1; ps_house_parking = 0; }
    let target = ps_crumb_nodes + ps_crumb_cursor * 64; if ps_house_park_to(target) != 2 { return 1; }
    if ps_crumb_matched != ps_crumb_cursor || ps_total - ps_crumb_seen > 20 { ps_crumb_wait = ps_crumb_wait + 1; if ps_crumb_wait > 100 { return ps_case_fail("visual breadcrumb not recognized; refusing blind return"); } return 1; }
    ps_crumb_event("checkpoint-reached"); ps_crumb_cursor = ps_crumb_cursor - 1;
    if ps_crumb_cursor < 0 { ps_crumb_recording = 0; return ps_case_tcp_survey(); } return ps_crumb_plan();
}
fn ps_crumb_observation(b) {
    if !ps_crumb_enabled || !ps_house_enabled() { return 0; }
    pl_text(b, ",\"breadcrumbs\":{\"source\":\"tcp-rgb-floor-features-v1\",\"oraclePose\":false,\"flatFloor\":true,\"applyCorrections\":"); pj_bool_text(b, ps_crumb_apply); pl_text(b, ",\"count\":"); pl_int(b, ps_crumb_count);
    pl_text(b, ",\"returnIndex\":"); pl_int(b, ps_crumb_cursor); pl_text(b, ",\"samples\":"); pl_int(b, ps_crumb_samples); pl_text(b, ",\"frameId\":"); pl_int(b, ps_crumb_frame);
    pl_text(b, ",\"features\":"); pl_int(b, ps_crumb_features); pl_text(b, ",\"inliers\":"); pl_int(b, ps_cf_inliers); pl_text(b, ",\"corrections\":"); pl_int(b, ps_crumb_corrections);
    pl_text(b, ",\"checkpointMatches\":"); pl_int(b, ps_crumb_key_matches);
    pl_text(b, ",\"groundHeading\":{\"source\":\"tcp-floor-lines-and-known-wall-axis\",\"mapAxisKnown\":"); pj_bool_text(b, ps_crumb_axis_known);
    pl_text(b, ",\"samples\":"); pl_int(b, ps_ground_samples); pl_text(b, ",\"confidence\":"); pl_float(b, ps_ground_confidence); pl_text(b, ",\"corrections\":"); pl_int(b, ps_crumb_heading_corrections); pl_char(b, 125);
    pl_text(b, ",\"correctionDelta\":["); pl_float(b, ps_local_visual_x); pl_char(b, 44); pl_float(b, ps_local_visual_y); pl_char(b, 44); pl_float(b, ps_local_visual_heading); return pl_text(b, "]}");
}
