// Synchronous pixel/control Gym bridge. Physics and actuator guards still run;
// navigation, mapping workers and autonomous camera sweeps do not.
import "oracle-cache.flex";
global ps_agent_fd = 0;
global ps_agent_task = 2;
global ps_agent_sequence = 0;
global ps_agent_blocked = 0;
global ps_agent_oracle = 0;
global ps_agent_oracle_queries = 0;
global ps_agent_oracle_label_ok = 0;
global ps_agent_oracle_steering = 0;
global ps_agent_oracle_speed = 0;
global ps_agent_primitive = 0;
global ps_agent_primitive_continuations = 0;

fn ps_agent_oracle_state(b) {
    pl_text(b, ",\"trainingOracle\":{\"enabled\":"); pj_bool_text(b, ps_agent_oracle);
    pl_text(b, ",\"queries\":"); pl_uint(b, ps_agent_oracle_queries); pl_text(b, ",\"label\":");
    if ps_agent_oracle_queries && ps_agent_oracle_label_ok { pl_char(b, 91); pl_float(b, ps_number(ps_agent_oracle_steering, 1000)); pl_char(b, 44); pl_float(b, ps_number(ps_agent_oracle_speed, 1000)); pl_char(b, 93); } else { pl_text(b, "null"); }
    pl_text(b, ",\"cacheHits\":"); pl_uint(b, ps_oracle_cache_hits); pl_text(b, ",\"cacheChecks\":"); pl_uint(b, ps_oracle_cache_checks); pl_text(b, ",\"primitiveContinuations\":"); pl_uint(b, ps_agent_primitive_continuations); return pl_char(b, 125);
}
fn ps_agent_primitive_advance(reply, continuing) {
    let p = ps_agent_primitive; if continuing && load64(p + 80) == 10 { store64(p + 96, load64(p + 96) + 1); }
    store64(p + 24, ps_total); store64(p + 32, load64(reply + 24)); store64(p + 40, load64(reply + 32)); store64(p + 80, load64(reply + 40));
    let x = ps_x; let y = ps_y; let h = ps_heading; let distance = ps_number(load64(reply + 32) * 60 / 1000, 10000);
    let angle = pb_radians(f64_from_i64((load64(reply + 24) / 10) * 45 / 100)); let turn = pb_neg(f64_mul(f64_div(distance, ps_number(18, 100)), f64_div(f64_sin(angle), f64_cos(angle))));
    let tick = 0; while tick < 10 { h = pb_wrap_pi(f64_add(h, turn)); x = f64_add(x, f64_mul(distance, f64_cos(h))); y = f64_add(y, f64_mul(distance, f64_sin(h))); tick = tick + 1; }
    store64(p + 48, x); store64(p + 56, y); store64(p + 64, h); store64(p + 72, 1); return 1;
}
fn ps_agent_primitive_save(request, reply) {
    if !ps_agent_primitive { ps_agent_primitive = alloc(104 + 2048 * 8); } let p = ps_agent_primitive; store64(p + 72, 0);
    if !load64(reply + 16) || load64(reply + 40) != 20 || !load64(reply + 32) || ps_nav_path_count < 1 || ps_nav_path_count > 2048 { return 0; }
    pb_copy(p, request + 16, 24); store64(p + 88, ps_nav_path_count); store64(p + 96, 0); let i = 0;
    while i < ps_nav_path_count { store64(p + 104 + i * 8, load64(ps_nav_path + (ps_nav_path_count - 1 - i) * 8)); i = i + 1; }
    return ps_agent_primitive_advance(reply, 0);
}
fn ps_agent_primitive_read(request, reply) {
    let p = ps_agent_primitive; if load64(request + 40) != 1 || !p || !load64(p + 72) || ps_agent_blocked || ps_total != load64(p + 24) + 10 { return 0; }
    let i = 0; while i < 3 { if f64_gt(f64_magnitude(f64_sub(load64(request + 16 + i * 8), load64(p + i * 8))), ps_number(1, 100000)) { return 0; } i = i + 1; }
    if f64_gt(f64_hypot(f64_sub(ps_x, load64(p + 48)), f64_sub(ps_y, load64(p + 56))), ps_number(1, 10000000)) || f64_gt(f64_magnitude(pb_wrap_pi(f64_sub(ps_heading, load64(p + 64)))), ps_number(1, 10000000)) { return 0; }
    let ticks = 10; let steer = load64(p + 32); let speed = load64(p + 40);
    // Preserve the complete planned route after finishing a primitive. A new
    // short-horizon search here can undo the preceding reverse escape.
    if load64(p + 80) == 10 {
        let next = load64(p + 96) + 1; if next >= load64(p + 88) { return 0; } let index = load64(p + 104 + next * 8); if index < 0 || index >= 12 { return 0; }
        let planned = ps_nav_actions + index * 128; steer = load64(planned) * 10; speed = load64(planned + 8) * load64(planned + 112) * 1000 / 60; ticks = 20;
    }
    let a = alloc(128); store64(a, steer / 10); store64(a + 8, pb_sign(speed)); store64(a + 112, pb_abs(speed * 60 / 1000));
    let hit = ps_vehicle_hit; let part = ps_vehicle_part; let fault = ps_vehicle_fault; let planning = ps_vehicle_planning; ps_vehicle_planning = 1;
    let clear = ps_vehicle_primitive_ticks(ps_x, ps_y, ps_heading, a, ticks); ps_vehicle_planning = planning; ps_vehicle_hit = hit; ps_vehicle_part = part; ps_vehicle_fault = fault; syscall(11, a, 128, 0, 0, 0, 0);
    if !clear { return 0; } pb_zero(reply, 64); store64(reply + 16, 1); store64(reply + 24, steer); store64(reply + 32, speed); store64(reply + 40, ticks); return 1;
}
fn ps_agent_oracle_snapshot(request) {
    ps_oracle_key_begin();
    // Memoization is restricted to the mapless, fixed-goal training planner.
    // Compare complete current collision inputs, not pose rounded to a cell.
    if !ps_discovery_enabled || ps_nav_parking_goal || ps_nav_escape { return 0; }
    ps_oracle_key_word(ps_x); ps_oracle_key_word(ps_y); ps_oracle_key_word(ps_heading); ps_oracle_key_add(request + 16, 24);
    ps_oracle_key_add(ps_environment, ps_environment_size); ps_oracle_key_add(ps_body_shape(4), 256); ps_oracle_key_add(ps_wheel_local, 192);
    ps_oracle_key_word(ps_arm_collider_count); let i = 0;
    while i < ps_arm_collider_count { let r = ps_arm_colliders + i * 56; ps_oracle_key_add(r, 56); ps_oracle_key_add(ps_world_matrices + load64(r) * 128, 128); i = i + 1; }
    ps_oracle_key_add(ps_gripper_frame, 128); ps_oracle_key_add(ps_gripper_targets, 72); i = 0;
    while i < 3 { ps_oracle_key_add(ph_shape(ps_physics, 5 + i) + 72, 24); i = i + 1; }
    ps_oracle_key_word(ps_wheel_shape); i = 1;
    while i < ps_wheel_shape { let shape = ph_shape(ps_physics, i); let body = load64(shape);
        if body < 4 || body >= 8 { ps_oracle_key_add(shape, 256); ps_oracle_key_add(ph_body(ps_physics, body), 64); } i = i + 1;
    }
    return ps_oracle_key_bytes > 0;
}
fn ps_agent_label(request) {
    if !ps_agent_oracle { return 0; }
    let x = load64(request + 16); let y = load64(request + 24); let heading = load64(request + 32);
    if !f64_is_finite(x) || !f64_is_finite(y) || !f64_is_finite(heading) || !ps_environment_inside(x, y) || load64(request + 40) < 0 || load64(request + 40) > 1 { return 0; }
    if !ps_nav_map && !ps_nav_init() { return 0; }
    let reply = alloc(64); let continuing = ps_agent_primitive_read(request, reply); let cached = 0; if !continuing { cached = ps_agent_oracle_snapshot(request) && ps_oracle_cache_read(reply); }
    let saved_steering = load64(reply + 24); let saved_speed = load64(reply + 32);
    if !continuing && (!cached || ps_oracle_cache_verify) {
        let hit = ps_vehicle_hit; let part = ps_vehicle_part; let fault = ps_vehicle_fault; let planning = ps_vehicle_planning;
        let localization = ps_local_mode; ps_local_mode = 0;
        ps_nav_training_oracle = 1; ps_vehicle_planning = 1; let ok = ps_nav_plan(x, y, heading);
        ps_nav_training_oracle = 0; ps_vehicle_planning = planning; ps_local_mode = localization;
        ps_vehicle_hit = hit; ps_vehicle_part = part; ps_vehicle_fault = fault;
        pb_zero(reply, 64); store64(reply + 16, ok);
        if ok && ps_nav_path_count {
            let index = load64(ps_nav_path + (ps_nav_path_count - 1) * 8); let action = ps_nav_actions + index * 128;
            store64(reply + 24, load64(action) * 10); store64(reply + 32, load64(action + 8) * load64(action + 112) * 1000 / 60);
            store64(reply + 40, 20);
        }
        store64(reply + 48, ps_nav_path_count); store64(reply + 56, ps_nav_expanded);
        if cached {
            if !ok || saved_steering != load64(reply + 24) || saved_speed != load64(reply + 32) { pl_print(2, "Oracle cache differs from a fresh physical plan.\n"); syscall(11, reply, 64, 0, 0, 0, 0); return 0; }
            ps_oracle_cache_checks = ps_oracle_cache_checks + 1;
        }
        ps_oracle_cache_save(reply);
    }
    if continuing { ps_agent_primitive_continuations = ps_agent_primitive_continuations + 1; ps_agent_primitive_advance(reply, 1); } else { ps_agent_primitive_save(request, reply); }
    ps_agent_oracle_queries = ps_agent_oracle_queries + 1;
    store64(reply, load64("VCLAB001")); store64(reply + 8, ps_agent_sequence);
    ps_agent_oracle_label_ok = load64(reply + 16); ps_agent_oracle_steering = load64(reply + 24); ps_agent_oracle_speed = load64(reply + 32);
    let written = !pl_write(ps_agent_fd, reply, 64); syscall(11, reply, 64, 0, 0, 0, 0); return written;
}

// Chase game: restore a consumed or visible brick at a requested floor pose.
// Placement is a training/evaluation event; the actor still receives only RGB.
fn ps_agent_place(request) {
    let index = load64(request + 16); let x = load64(request + 24); let y = load64(request + 32); let yaw = load64(request + 40);
    if index < 0 || index >= ps_case_count || !f64_is_finite(x) || !f64_is_finite(y) || !f64_is_finite(yaw) || !ps_environment_inside(x, y) { return 0; }
    let r = ps_case_objects + index * 256; if load64(r + 64) { return 0; } let body = ph_body(ps_physics, load64(r + 184));
    let mass = pb_f64_to_f32(load64(r + 128)); let hx = pb_f64_to_f32(load64(r + 96)); let hy = pb_f64_to_f32(load64(r + 104)); let hz = pb_f64_to_f32(load64(r + 112));
    let half = f64_mul(yaw, ps_number(1, 2));
    store64(r + 208, 0); store64(body, 1); ph_vset(body + 8, pb_f64_to_f32(x), pb_f64_to_f32(y), pb_f64_to_f32(load64(r + 88)));
    ph_vset(body + 32, 0, 0, pb_f64_to_f32(f64_sin(half))); store64(body + 56, pb_f64_to_f32(f64_cos(half)));
    ph_vset(body + 64, 0, 0, 0); ph_vset(body + 88, 0, 0, 0); store64(body + 112, ph_rcp(mass));
    ph_vset(body + 120, ph_rcp(ph_box_inertia(mass, hx, hy, hz, 0)), ph_rcp(ph_box_inertia(mass, hx, hy, hz, 1)), ph_rcp(ph_box_inertia(mass, hx, hy, hz, 2))); ph_cache_body(body);
    ps_seek_found = 0; ps_seek_consumed = -1; ps_seek_detection_step = -1; ps_seek_return_observations = 0; return 1;
}
fn ps_agent_read(data, size) {
    let offset = 0;
    while offset < size {
        let count = syscall(0, ps_agent_fd, data + offset, size - offset, 0, 0, 0);
        if count <= 0 { return 0; } offset = offset + count;
    } return 1;
}
fn ps_agent_begin() {
    ps_gripper_auto = 0; ps_gripper_command(0); ps_case_phase(26);
    ps_discovery_phase = 0; ps_agent_blocked = 0;
    ps_case_reason = "external visual policy controls steering and speed";
    return ps_camera_drive_target();
}
fn ps_agent_render(video, final) {
    if !video || !ps_video_due(ps_total, final) { return 1; }
    ps_frame(); let ok = ps_video_frame(ps_total, final); gui_gl_swap(load64(ps_device)); return ok;
}
fn ps_agent_observe() {
    if !ps_rgb_sample() { return 0; }
    ps_seek_observe();
    if ps_agent_task == 1 && ps_seek_found {
        ps_case_reason = "visual approach curriculum completed"; ps_case_passed = 1; ps_case_phase(12);
        pr_stop(ps_app, ps_time); ps_discovery_finish(ps_case_reason, 0);
    }
    let output = ps_output; ps_output = -1; let ok = ps_observation(); ps_output = output;
    if !ok { return 0; }
    let header = alloc(32); store64(header, load64(ps_builder + 8)); store64(header + 8, 640 * 480 * 3);
    store64(header + 16, ps_agent_sequence); store64(header + 24, ps_agent_blocked);
    ok = !pl_write(ps_agent_fd, header, 32) && !pl_write(ps_agent_fd, ps_json, load64(ps_builder + 8)) && !pl_write(ps_agent_fd, ps_brick_rgb, 640 * 480 * 3);
    syscall(11, header, 32, 0, 0, 0, 0); return ok;
}
fn ps_agent_loop(video, capture) {
    let request = alloc(64); let running = 1;
    while running && ps_agent_read(request, 64) {
        let command = load64(request); ps_agent_sequence = load64(request + 8);
        if command == 3 { running = 0; }
        else if command == 1 {
            ps_agent_oracle_queries = 0; ps_agent_oracle_label_ok = 0; ps_agent_oracle_steering = 0; ps_agent_oracle_speed = 0;
            ps_oracle_cache_reset();
            if ps_agent_primitive { store64(ps_agent_primitive + 72, 0); } ps_agent_primitive_continuations = 0;
            let task = load64(request + 48); if task < 1 || task > 3 { return 1; } ps_agent_task = task;
            if !ps_case_load(ps_case_index) || !ps_reset() || !ps_case_start() { return 1; }
            let ticks = 0;
            while ticks < 2500 && (!ps_camera_still() || !ps_pickup_settled() || ps_gripper_gap != ps_gripper_goal) {
                if !ps_tick(0) { return 1; } ticks = ticks + 1;
            }
            if !ps_camera_still() || !ps_pickup_settled() { pl_print(2, "Agent driving-camera pose did not settle.\n"); return 1; }
            if !ps_agent_observe() || !ps_agent_render(video, 0) { return 1; }
        } else if command == 4 {
            if !ps_agent_label(request) { return 1; }
        } else if command == 5 {
            // The re-render shares this step's frame number; its sensor PNG already exists.
            if ps_agent_task != 3 || !ps_agent_place(request) { return 1; }
            let output = ps_brick_output; ps_brick_output = 0; let ok = ps_agent_observe(); ps_brick_output = output; if !ok { return 1; }
        } else if command == 2 {
            let steering = load64(request + 16); let speed = load64(request + 24); let hold = load64(request + 32);
            if steering < -1000 || steering > 1000 || speed < -1000 || speed > 1000 || hold < 1 || hold > 20 || !ps_case_running() { return 1; }
            // Normalized actions map to steering and bounded wheel speed.
            // The dead zone permits an actual stop under a continuous policy.
            let throttle = speed * 60 / 1000; if pb_abs(speed) < 80 { throttle = 0; }
            ps_agent_blocked = 0; let tick = 0;
            while tick < hold {
                pb_drive_steer(pb_robot_drive(ps_robot), throttle, steering / 10, ps_time);
                if !ps_tick(0) { return 1; } if ps_blocked { ps_agent_blocked = 1; } tick = tick + 1;
            }
            if !ps_agent_observe() || !ps_agent_render(video, ps_case_passed) { return 1; }
        } else { return 1; }
    }
    pb_drive_stop(pb_robot_drive(ps_robot), ps_time); ps_discovery_phase = 6;
    if video && !ps_agent_render(video, 1) { return 1; }
    if capture { ps_frame(); if !ps_capture(capture) { return 1; } }
    syscall(11, request, 64, 0, 0, 0, 0); return 0;
}
