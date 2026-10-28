import "render.flex";
import "pickup.flex";
import "live.flex";
import "case.flex";
import "preview.flex";
import "breadcrumbs.flex";
import "landmarks.flex";
import "video.flex";
import "discovery.flex";
import "grasp.flex";
import "collect.flex";
import "seek.flex";
import "gym.flex";
import "serial.flex";
import "agent.flex";

global ps_robot = 0;
global ps_system = 0;
global ps_config = 0;
global ps_app = 0;
global ps_bus = 0;
global ps_plant = 0;
global ps_trace = 0;
global ps_time = 0;
global ps_step = 0;
global ps_total = 0;
global ps_episode = -1;
global ps_paused = 0;
global ps_selected = 0;
global ps_keyboard_drive = 0;
global ps_keyboard_joint = -1;
global ps_output = -1;
global ps_json = 0;
global ps_builder = 0;

fn ps_reset() {
    if ps_external && ps_serial_context { ps_serial_quarantine(pl_now() + 350); }
    ps_preview_next = 0; ps_camera_drive_mode = 0;
    ps_stock_reset();
    ps_crumb_reset();
    if ps_case_index >= 0 { store64(ps_case_bin + 80, load64(ps_case_bin + 88)); }
    if ps_case_index >= 0 && !ps_layout_reset() { pl_print(2, "Cannot fit random floor layout with configured clearances.\n"); return 0; }
    if ps_case_index >= 0 && ps_case_count > 3 && ps_radius < 1200 { ps_radius = 1200; }
    ps_case_reset(); ps_vision_reset(); if ps_live_job { ps_live_front = -1; ps_live_score = 0; ps_live_frame = 0; ps_live_time = 0; }
    ps_pickup_phase(0); ps_pickup_passed = 0; ps_pickup_reason = "idle";
    ps_episode = ps_episode + 1;
    ps_time = 0; ps_step = 0; ps_keyboard_drive = 0; ps_keyboard_joint = -1;
    let jam = -1; if ps_external { jam = ps_serial_jam; }
    gs_init(ps_plant, ps_config, ps_bus, 42, jam); if pb_robot_configure(ps_robot, ps_config, 0) { return 0; }
    pb_system_init(ps_system, ps_robot); pr_init(ps_app, ps_robot, ps_system, ps_config, "build/flex/sim/config.json", 1, pl_now());
    pb_vset(ps_app, 3, ps_bus); pb_vset(ps_app, 30, ps_trace + 2048); ps_world_init();
    // Warm up the production controller's feedback and wheel-mode handshake.
    let i = 0;
    while !ps_external && i < 64 { gs_step(ps_plant); if pb_fake_cycle(ps_system, ps_bus, ps_time, ps_trace, 1024) < 0 { return 0; } ps_time = ps_time + 20; i = i + 1; }
    if ps_external { ps_serial_feedback(); }
    ps_model_update(ps_robot, ps_plant, ps_x, ps_y, ps_heading, ps_wheel);
    ps_vehicle_init(); ps_gripper_init(ps_robot, ps_plant); ps_solid_init(); ps_arm_proxy_update(1);
    ps_local_reset();
    if ps_discovery_enabled && !ps_discovery_reset() { return 0; }
    if ps_house_enabled() && !ps_house_reset() { pl_print(2, "Cannot initialize the house navigation map.\n"); return 0; }
    if ps_collect_enabled { ps_collect_reset(); }
    if ps_seek_enabled { ps_seek_reset(); }
    if ps_environment && !ps_vehicle_free(ps_x, ps_y, ps_heading) { pl_print(2, "Environment spawn intersects the robot or lies outside the floor.\n"); return 0; } return 1;
}
fn ps_observation() {
    let b = ps_builder; pl_builder(b, ps_json, 16384);
    pl_text(b, "{\"schema\":\"puppybot.sim.v1\",\"step\":"); pl_uint(b, ps_step); pl_text(b, ",\"timeMs\":"); pl_uint(b, ps_time);
    pl_text(b, ",\"episode\":"); pl_uint(b, ps_episode); pl_text(b, ",\"totalSteps\":"); pl_uint(b, ps_total);
    pl_text(b, ",\"paused\":"); pj_bool_text(b, ps_paused); pl_text(b, ",\"modelLinks\":"); pl_uint(b, load64(ps_asset + 32));
    pl_text(b, ",\"backend\":\"flexscript-kinematic-contact-v1\",\"articulatedDynamics\":false,\"pose\":["); pl_float(b, ps_x); pl_char(b, 44); pl_float(b, ps_y); pl_char(b, 44); pl_float(b, ps_heading);
    pl_text(b, "],\"tcp\":["); let i = 0; while i < 3 { if i { pl_char(b, 44); } pl_float(b, pb_vget(ps_tcp, i)); i = i + 1; }
    pl_text(b, "],\"ball\":["); i = 0; let ball = ph_body(ps_physics, 3);
    while i < 3 { if i { pl_char(b, 44); } pl_float(b, pb_f32_to_f64(pb_vget(ball + 8, i))); i = i + 1; }
    pl_text(b, "],\"ticks\":["); i = 0; while i < 4 { if i { pl_char(b, 44); } pl_int(b, pb_vget(ps_plant + 128 + i * 64, 2)); i = i + 1; }
    pl_text(b, "],\"jointAnglesRad\":["); i = 0;
    while i < 4 { if i { pl_char(b, 44); } pl_float(b, pb_tick_angle(pb_joint(ps_robot, i), pb_vget(ps_plant + 128 + i * 64, 2))); i = i + 1; }
    pl_text(b, "],\"blocked\":"); pj_bool_text(b, ps_blocked); pl_text(b, ",\"contacts\":"); pl_int(b, load64(ps_physics + 24));
    ps_vehicle_observation(b); ps_solid_observation(b); ps_environment_observation(b); ps_local_observation(b); ps_crumb_observation(b); ps_camera_observation(b);
    pl_text(b, ",\"physicsFault\":"); pl_int(b, load64(ps_physics + 192));
    pl_text(b, ",\"gripper\":{\"model\":\"parallel-jaw-v1\",\"graspModel\":\"bilateral-contact-weld-v1\",\"openingMm\":"); pl_float(b, ps_number(ps_gripper_gap, 1000));
    pl_text(b, ",\"targetOpeningMm\":"); pl_float(b, ps_number(ps_gripper_goal, 1000)); pl_text(b, ",\"held\":"); pj_bool_text(b, ps_gripper_held);
    pl_text(b, ",\"body\":"); pl_int(b, ps_gripper_body);
    pl_text(b, ",\"constraintActive\":"); pj_bool_text(b, load64(ps_physics + 32) && load64(ph_joint(ps_physics, 0) + 16));
    pl_text(b, ",\"ballDynamic\":"); pj_bool_text(b, load64(ball) == 1 && load64(ball + 112) != 0);
    pl_text(b, ",\"contactMask\":"); pl_int(b, ps_gripper_contacts); pl_text(b, ",\"captureContactMask\":"); pl_int(b, ps_gripper_witnesses);
    pl_text(b, ",\"grasps\":"); pl_int(b, ps_gripper_grasps); pl_text(b, ",\"releases\":"); pl_int(b, ps_gripper_releases);
    pl_text(b, ",\"captureBallHeight\":"); pl_float(b, pb_f32_to_f64(ps_gripper_capture_height)); pl_text(b, ",\"maxHeldBallHeight\":"); pl_float(b, pb_f32_to_f64(ps_gripper_max_height));
    pl_text(b, ",\"centre\":["); i = 0; while i < 3 { if i { pl_char(b, 44); } pl_float(b, pb_vget(ps_gripper_targets + 72, i)); i = i + 1; }
    pl_text(b, "]},\"pickup\":{\"source\":");
    if ps_vision_requested { pj_text(b, "yolo-floor-plane-v1"); } else { pj_text(b, "simulator-truth"); }
    pl_text(b, ",\"phase\":"); pj_text(b, ps_pickup_name()); pl_text(b, ",\"phaseSteps\":"); pl_int(b, ps_pickup_steps);
    pl_text(b, ",\"passed\":"); pj_bool_text(b, ps_pickup_passed); pl_text(b, ",\"reason\":"); pj_text(b, ps_pickup_reason);
    pl_text(b, "},\"vision\":{\"state\":"); pj_text(b, ps_vision_state); pl_text(b, ",\"reason\":"); pj_text(b, ps_vision_reason);
    pl_text(b, ",\"confidence\":"); pl_float(b, ps_vision_confidence); pl_text(b, ",\"cameraFrameId\":"); pl_uint(b, ps_vision_frame);
    pl_text(b, ",\"directory\":"); if ps_vision_directory { pj_text(b, ps_vision_directory); } else { pl_text(b, "null"); }
    pl_text(b, ",\"targetM\":"); if pl_equal(ps_vision_state, "detected") { pl_char(b, 91); i = 0; while i < 3 { if i { pl_char(b, 44); } pl_float(b, pb_vget(ps_vision_estimate, i)); i = i + 1; } pl_char(b, 93); } else { pl_text(b, "null"); }
    pl_text(b, ",\"live\":{\"enabled\":"); pj_bool_text(b, ps_live_enabled); pl_text(b, ",\"state\":"); if ps_live_job { pj_text(b, ps_live_state); } else { pj_text(b, "off"); }
    pl_text(b, ",\"view\":\"tcp\"");
    pl_text(b, ",\"frameId\":"); pl_uint(b, ps_live_frame); pl_text(b, ",\"capturedMs\":"); pl_uint(b, ps_live_time);
    pl_text(b, ",\"confidence\":"); pl_float(b, ps_live_score); pl_text(b, ",\"label\":"); if ps_live_label && ps_live_score { pj_text(b, ps_live_label); } else { pl_text(b, "null"); }
    pl_text(b, ",\"box\":"); if ps_live_score { pl_char(b, 91); i = 0; while i < 4 { if i { pl_char(b, 44); } pl_float(b, pb_vget(ps_live_box, i)); i = i + 1; } pl_char(b, 93); } else { pl_text(b, "null"); } pl_char(b, 125);
    pl_char(b, 125); ps_case_observation(b); ps_discovery_observation(b); ps_seek_observation(b); if ps_stock_enabled { ps_stock_state(b); } ps_serial_observation(b); ps_agent_oracle_state(b); pl_text(b, ",\"controller\":"); if ps_external { pl_text(b, "null"); } else { pr_state(ps_app, b, ps_time, 0); } pl_text(b, "}\n");
    if load64(b + 24) { return 0; } if ps_output >= 0 && pl_write(ps_output, ps_json, load64(b + 8)) { return 0; } return 1;
}
fn ps_demo() {
    let values = ps_trace + 1024;
    if !ps_step {
        let i = 0; while i < 4 { let c = pb_config_joint(ps_config, i); pb_vset(values, i, pb_vget(c, 3) + 80); i = i + 1; }
        if pr_apply(ps_app, 5, values, ps_time) { return 0; }
    }
    if ps_step < 100 { pb_drive_steer(pb_robot_drive(ps_robot), 20, -25, ps_time); }
    else { pb_drive_stop(pb_robot_drive(ps_robot), ps_time); } return 1;
}
fn ps_tick(demo) {
    if demo && !ps_demo() { pl_print(2, "Demo joint target was rejected by the controller.\n"); return 0; }
    if !ps_external { pr_refresh(ps_app, ps_time); } ps_solid_step();
    let cycle = 0; if !ps_external { cycle = pb_fake_cycle(ps_system, ps_bus, ps_time, ps_trace, 1024); }
    else { ps_serial_feedback(); }
    if cycle < 0 { pl_print(2, "Serialized servo cycle failed.\n"); return 0; }
    ps_model_update(ps_robot, ps_plant, ps_x, ps_y, ps_heading, ps_wheel);
    ps_drive_step(ps_robot); ps_model_update(ps_robot, ps_plant, ps_x, ps_y, ps_heading, ps_wheel);
    if !ps_external { ps_route_before_local(); ps_local_step(); ps_route_after_local(); }
    if !ps_contacts(ps_robot, ps_plant) {
        pl_builder(ps_builder, ps_json, 16384); pl_text(ps_builder, "Physics fault code: "); pl_int(ps_builder, load64(ps_physics + 192)); pl_text(ps_builder, "\n"); pl_print(2, ps_json); return 0;
    }
    ps_step = ps_step + 1; ps_total = ps_total + 1; ps_time = ps_time + 20;
    if !ps_external { ps_crumb_poll(); if !ps_agent_fd { ps_pickup_update(); ps_case_update(); ps_stock_update(); ps_discovery_update(); } }
    if ps_gym_directory && !(ps_step % 25) && !ps_gym_sample() { return 0; }
    // HTTP state replies and the final summary serialize their own observation.
    if ps_output >= 0 && !ps_observation() { pl_print(2, "Cannot serialize or write the simulation recording.\n"); return 0; } return 1;
}
fn ps_task_running() { return (ps_discovery_enabled && ps_discovery_phase < 6) || ps_pickup_running() || ps_case_running() || (ps_stock_enabled && ps_stock_phase > 0 && ps_stock_phase < 4); }
fn ps_task_cancel(reason) { if ps_discovery_enabled && ps_discovery_phase < 6 { ps_discovery_finish(reason, 1); } ps_pickup_cancel(reason); ps_case_cancel(reason); if ps_stock_enabled && ps_stock_phase > 0 && ps_stock_phase < 4 { ps_stock_finish(5, reason); } return 0; }
fn ps_case_available(index) {
    if load64(ps_catalog_cameras + index * 8) >= 3 { return 0; }
    if ps_stock_case(ps_catalog_entries + index * 768) { return 0; }
    return load64(ps_catalog_cameras + index * 8) != 2 || ps_environment;
}
fn ps_case_route(c, wall) {
    let path = c + 160; let method = c + 128;
    if pl_equal(method, "GET") && pl_equal(path, "/api/sim/cases") { pnet_reply(c, 200, "application/json", ps_catalog, ps_catalog_size, wall); return 1; }
    if pl_equal(method, "POST") && pl_starts(path, "/api/sim/cases/") {
        if ps_discovery_enabled { pnet_error(c, 400, "restart without --discover to select a collection case", wall); return 1; }
        let index = ps_case_find(path + 15);
        if index < 0 { pnet_error(c, 404, "unknown simulation case", wall); return 1; }
        if load64(ps_catalog_cameras + index * 8) >= 3 { pnet_error(c, 400, "launch unknown-map cases in a fresh simulator", wall); return 1; }
        if ps_stock_case(ps_catalog_entries + index * 768) { pnet_error(c, 400, "launch this stock-landmark case in a fresh simulator", wall); return 1; }
        if load64(ps_catalog_cameras + index * 8) == 2 && !ps_environment { pnet_error(c, 400, "house search requires --environment apartment", wall); return 1; }
        if !ps_device && load64(ps_catalog_cameras + index * 8) { pnet_error(c, 400, "camera search requires rendering; use --hidden", wall); return 1; }
        let seed = ps_case_seed;
        if pb_vget(c, 9) {
            let root = pj_parse(c + 512 + pb_vget(c, 10), pb_vget(c, 9));
            if !root || pj_kind(root) != 4 { pnet_error(c, 400, "invalid case options", wall); return 1; }
            if pj_get(root, "seed") { seed = pj_integer(root, "seed", 0, 4294967295); }
            if pj_error { pnet_error(c, 400, "seed must be an integer between 0 and 4294967295", wall); return 1; }
        }
        let previous_seed = ps_case_seed; ps_case_seed = seed;
        if !ps_case_load(index) { ps_case_seed = previous_seed; pnet_error(c, 400, "invalid simulation case definition", wall); return 1; }
        ps_case_seed = seed; ps_vision_requested = 0;
        if !ps_reset() || !ps_case_start() { pnet_error(c, 500, "cannot initialize simulation case", wall); return 1; }
        let output = ps_output; ps_output = -1; ps_observation(); ps_output = output;
        pnet_reply(c, 200, "application/json", ps_json, load64(ps_builder + 8), wall); return 1;
    }
    return 0;
}
fn ps_stop() { if ps_external { ps_serial_stop(); } pr_stop(ps_app, ps_time); ps_keyboard_drive = 0; ps_keyboard_joint = -1; return 0; }
fn ps_container_route(c, wall) {
    let path = c + 160;
    if !pl_equal(c + 128, "POST") || (!pl_equal(path, "/api/sim/container/push") && !pl_equal(path, "/api/sim/container/markers")) { return 0; }
    if ps_case_index < 0 { pnet_error(c, 400, "no case container is loaded", wall); return 1; }
    let root = pj_parse(c + 512 + pb_vget(c, 10), pb_vget(c, 9));
    if !root || pj_kind(root) != 4 { pnet_error(c, 400, "container control requires a JSON object", wall); return 1; }
    if pl_equal(path, "/api/sim/container/markers") {
        let enabled = pj_boolean(root, "enabled"); if pj_error { pnet_error(c, 400, "enabled must be a boolean", wall); return 1; } store64(ps_case_bin + 80, enabled);
    } else {
        let body = ph_body(ps_physics, ps_case_bin_body);
        if load64(body) != 1 { pnet_error(c, 400, "fixed containers cannot be pushed", wall); return 1; }
        let values = alloc(48); pb_zero(values, 48); let valid = ps_case_vector(values, root, "impulse", ps_number(-1, 2), ps_number(1, 2));
        if pj_get(root, "pointOffset") { valid = valid && ps_case_vector(values + 24, root, "pointOffset", ps_number(-15, 100), ps_number(15, 100)); }
        if !valid || pj_error { syscall(11, values, 48, 0, 0, 0, 0); pnet_error(c, 400, "invalid impulse or pointOffset vector", wall); return 1; }
        let i = 0; while i < 6 { store64(values + i * 8, pb_f64_to_f32(load64(values + i * 8))); i = i + 1; }
        ph_cache_body(body); ph_impulse(body, values + 24, values, ps_float(1, 1), ph_scratch(ps_physics)); syscall(11, values, 48, 0, 0, 0, 0);
    }
    // These perturb the simulated world only. The task learns the new box
    // pose or missing patches through its next RGB observation.
    let output = ps_output; ps_output = -1; ps_observation(); ps_output = output;
    pnet_reply(c, 200, "application/json", ps_json, load64(ps_builder + 8), wall); return 1;
}
fn ps_dispatch(wall) {
    let i = 0;
    while i < 32 {
        let c = pn_clients + i * 65536;
        if ps_external && load64(c) >= 0 && pb_vget(c, 1) == 2 { pnet_ws_close(c, 1008, wall); }
        if ps_external && load64(c) >= 0 && pb_vget(c, 1) == 1 {
            let path = c + 160; let method = c + 128; let allowed = 0;
            if pl_equal(method, "GET") && (pl_equal(path, "/api/sim/state") || pl_equal(path, "/api/sim/views")) { allowed = 1; }
            if pl_equal(method, "POST") && (pl_equal(path, "/api/sim/pause") || pl_equal(path, "/api/sim/resume") || pl_equal(path, "/api/sim/reset") || pl_equal(path, "/api/sim/gripper/open") || pl_equal(path, "/api/sim/gripper/close")) { allowed = 1; }
            if pl_equal(method, "GET") && pl_equal(path, "/health") { pnet_reply(c, 200, "application/json", "{\"ok\":true}", 11, wall); }
            else if !allowed { pnet_error(c, 409, "External controller mode: connect Puppybot to the printed serial device; this endpoint only controls the scene", wall); }
        }
        if load64(c) >= 0 && pb_vget(c, 1) == 1 && pl_starts(c + 160, "/api/sim/") {
            let path = c + 160; let method = c + 128; let handled = 0; if ps_case_route(c, wall) { handled = 2; }
            if !handled && ps_container_route(c, wall) { handled = 2; }
            if pl_equal(path, "/api/sim/views") && pl_equal(method, "GET") {
                pl_builder(ps_builder, ps_json, 16384); ps_preview_state(ps_builder); pnet_reply(c, 200, "application/json", ps_json, load64(ps_builder + 8), wall); handled = 2;
            }
            if pl_equal(path, "/api/sim/state") && pl_equal(method, "GET") { handled = 1; }
            if pl_equal(method, "POST") {
                if pl_equal(path, "/api/sim/pause") { if !ps_task_running() { ps_stop(); } if ps_external { ps_serial_quarantine(-1); } ps_paused = 1; handled = 1; }
                if pl_equal(path, "/api/sim/resume") { ps_paused = 0; handled = 1; }
                if pl_equal(path, "/api/sim/shuffle") {
                    if ps_case_index < 0 || !ps_case_random { pnet_error(c, 400, "selected case has no random floor placement", wall); handled = 2; }
                    else { ps_case_seed = (ps_case_seed + 1) & 0xffffffff; if !ps_reset() || !ps_case_start() { return 0; } handled = 1; }
                }
                if pl_equal(path, "/api/sim/reset") { if !ps_reset() || (ps_stock_enabled && !ps_stock_restart()) { return 0; } handled = 1; }
                if pl_equal(path, "/api/sim/pickup") { ps_case_index = -1; ps_vision_requested = 0; if !ps_reset() { return 0; } ps_pickup_start(0); handled = 1; }
                if pl_equal(path, "/api/sim/vision-pickup") { ps_case_index = -1; ps_vision_requested = 1; if !ps_reset() { return 0; } ps_pickup_start(0); handled = 1; }
                if pl_equal(path, "/api/sim/gripper/open") { ps_task_cancel("manual gripper open"); ps_gripper_command(1); handled = 1; }
                if pl_equal(path, "/api/sim/gripper/close") { ps_task_cancel("manual gripper close"); ps_gripper_command(0); handled = 1; }
            }
            if handled == 1 {
                let output = ps_output; ps_output = -1; let ok = ps_observation(); ps_output = output; if !ok { return 0; }
                pnet_reply(c, 200, "application/json; charset=utf-8", ps_json, load64(ps_builder + 8), wall);
            }
            else if !handled { pnet_error(c, 404, "unsupported Flexscript simulation route or method", wall); }
        }
        i = i + 1;
    }
    if !ps_external { pnet_dispatch_at(ps_app, wall, ps_time); } return 1;
}
fn ps_title() {
    pl_builder(ps_builder, ps_json, 16384); pl_text(ps_builder, "PuppyBot | ");
    if ps_paused { pl_text(ps_builder, "PAUSED (N step)"); } else { pl_text(ps_builder, "RUNNING"); }
    if ps_external {
        pl_text(ps_builder, " | EXTERNAL SERIAL "); pl_text(ps_builder, ps_serial_path);
        if ps_blocked { pl_text(ps_builder, " | DRIVE BLOCKED"); } if ps_arm_blocked { pl_text(ps_builder, " | ARM BLOCKED"); }
        pl_text(ps_builder, " | Control from Puppybot dashboard | V world/TCP | T TCP inset | K colliders | Space pause | R reset | O/C gripper");
        return gui_title(load64(ps_device), ps_json);
    }
    pl_text(ps_builder, " | joint "); pl_text(ps_builder, pr_joint_name(ps_selected, 0));
    pl_text(ps_builder, " | ");
    if ps_case_index >= 0 { pl_text(ps_builder, ps_case_name()); pl_text(ps_builder, " | "); pl_text(ps_builder, ps_case_phase_name()); pl_text(ps_builder, " | "); pl_int(ps_builder, ps_case_placed); pl_char(ps_builder, 47); pl_int(ps_builder, ps_case_count); }
    else if ps_discovery_enabled { pl_text(ps_builder, "MAPPING | scan "); pl_int(ps_builder, ps_discovery_scans); pl_text(ps_builder, " | observed cells "); pl_int(ps_builder, ps_discovery_free + ps_discovery_occupied); }
    else { pl_text(ps_builder, ps_pickup_name()); }
    if ps_blocked { pl_text(ps_builder, " | DRIVE BLOCKED"); }
    if ps_arm_blocked { pl_text(ps_builder, " | ARM BLOCKED"); }
    if ps_case_index >= 0 && ps_case_random { pl_text(ps_builder, " | seed "); pl_uint(ps_builder, ps_case_seed); }
    if ps_environment { pl_text(ps_builder, " | "); pl_text(ps_builder, ps_environment + 128); }
    if ps_local_mode { pl_text(ps_builder, " | WHEEL ODOM"); if ps_local_mode == 2 { pl_text(ps_builder, " + DRIFT"); } }
    if ps_crumb_enabled { pl_text(ps_builder, " | RGB ROUTE "); pl_int(ps_builder, ps_crumb_count); pl_text(ps_builder, " / matches "); pl_int(ps_builder, ps_crumb_key_matches); }
    if ps_stock_enabled { pl_text(ps_builder, " | STOCK LANDMARK "); pl_text(ps_builder, ps_stock_name()); pl_text(ps_builder, " / confirmed "); pl_int(ps_builder, ps_stock_matches); }
    if ps_gripper_held { if ps_case_index >= 0 { pl_text(ps_builder, " OBJECT HELD"); } else { pl_text(ps_builder, " BALL HELD"); } }
    if ps_vision_requested { pl_text(ps_builder, " | YOLO "); pl_text(ps_builder, ps_vision_state); if ps_vision_confidence { pl_char(ps_builder, 32); pl_int(ps_builder, f64_to_i64_nearest(f64_mul(ps_vision_confidence, f64_from_i64(100)))); pl_char(ps_builder, 37); } }
    pl_text(ps_builder, " | VIEW "); if ps_camera_mode == 2 { pl_text(ps_builder, "TCP"); } else { pl_text(ps_builder, "WORLD"); }
    if ps_previews { pl_text(ps_builder, " + TCP LIVE"); }
    else if ps_case_index >= 0 && ps_case_camera { pl_text(ps_builder, " + RGB CAMERA"); }
    else if ps_tcp_view && ps_camera_mode != 2 { pl_text(ps_builder, " + TCP"); }
    pl_text(ps_builder, " | V world/TCP | T TCP inset | L live cameras | B YOLO | K colliders | G shuffle | [ ] cases | Tab catalog | P run | O/C gripper | Space pause | R reset");
    return gui_title(load64(ps_device), ps_json);
}
fn ps_keyboard() {
    if ps_external { return 0; }
    let w = load64(ps_device); let throttle = (gui_key(w, 26) - gui_key(w, 22)) * 40; let steer = (gui_key(w, 7) - gui_key(w, 4)) * 60;
    if !ps_paused && (throttle || steer || gui_key(w, 8) || gui_key(w, 20)) { ps_task_cancel("manual robot control"); }
    if !ps_paused && (throttle || steer) { pb_drive_steer(pb_robot_drive(ps_robot), throttle, steer, ps_time); ps_keyboard_drive = 1; }
    else if ps_keyboard_drive { pb_drive_stop(pb_robot_drive(ps_robot), ps_time); ps_keyboard_drive = 0; }
    let direction = gui_key(w, 8) - gui_key(w, 20); let values = ps_trace + 1024;
    if !ps_paused && direction {
        if ps_keyboard_joint >= 0 && ps_keyboard_joint != ps_selected { pb_arm_stop(ps_robot, ps_time); }
        store64(values, ps_selected); store64(values + 8, direction); pr_apply(ps_app, 2, values, ps_time); ps_keyboard_joint = ps_selected;
    } else if ps_keyboard_joint >= 0 { pb_arm_stop(ps_robot, ps_time); ps_keyboard_joint = -1; }
    return 0;
}
fn ps_usage() {
    if ps_external {
        return pl_print(1, "Usage: flexscript run simulator.flex [--headless | --hidden --steps N] [options]\n       [--config PATH] [--environment apartment|FILE] [--spawn '[x,y,heading]']\n       [--temperature 0..255] [--jam 0..3] [--bind IPv4:PORT]\n       [--capture NEW_PNG --steps N] [--record NEW_JSONL] [--colliders]\n\nCreates a private serial bus for an independent puppybot.flex controller.\nCopy the printed connection command, then enable outputs in the dashboard.\nDefault configuration: ./puppybot.json. Arm packets use STServo; the explicit\n--virtual-bus adapter supplies DC-drive outputs on the same private PTY.\nNo embedded controller, keyboard drive/jog, or autonomous policy runs here.\nDrag/wheel change the view; V/T cameras, K colliders, O/C auxiliary gripper,\nSpace pause, R reset. Pause/reset stops motion and requires output re-enable.\nUse --servo-only for the lightweight non-rendering servo model.\n");
    }
    return pl_print(1, "Usage: flexscript run sim.flex [--case ID] [--drift 0..100] [options]\nNative: puppybot-sim [--headless | --hidden] [--steps N]\n       [--external-serial --config PATH --temperature 0..255 --jam 0..3]\n       [--demo | --pickup | --pickup-release | --vision-pickup | --vision-pickup-release]\n       [--environment apartment|FILE] [--spawn '[x,y,headingRadians]']\n       [--case ID | --case-file FILE | --list-cases] [--seed N] [--bind IPv4:PORT] [--model FILE] [--record NEW_JSONL]\n       [--discover] [--map-output NEW_DIRECTORY] [--mapping-scans 1..100]\n       [--video NEW_MP4] [--video-fps 1..50] [--gym-output NEW_DIRECTORY]\n       [--capture NEW_PPM_OR_PNG] [--sensor-capture NEW_PREFIX] [--camera orbit|tcp] [--tcp-view | --no-tcp-view] [--camera-panels | --no-camera-panels] [--observer-distance-mm 300..16000] [--colliders] [--realtime] [--paused]\n       [--stock-landmarks | --stock-pickup] [--landmark-output NEW_DIRECTORY] [--landmark-jpeg-quality 1..100] [--landmark-confidence 25..100]\n       [--visual-odometry | --no-visual-odometry | --breadcrumbs] [--breadcrumb-output NEW_DIRECTORY] [--no-breadcrumb-corrections]\n       [--localization oracle|wheel|wheel-drift] [--odometry-seed N] [--drift 0..100 | --odometry-drift 0..100]\n       [--until-done] [--detector-model MODEL.json] [--vision-binary EXECUTABLE]\n       [--vision-kernel DIRECTORY] [--vision-backend auto|sass|cuda|hip|cpu]\n       [--vision-output DIRECTORY] [--search-output NEW_DIRECTORY] [--detector-view | --no-detector-view]\n\nWASD drive; 1-4 select joint; Q/E jog; Space pause; N single step; R reset.\nTab shows catalog; [ / ] selects a case; P runs selected case or pickup; O/C opens/closes gripper; V cycles world/TCP camera; T toggles TCP inset; L toggles the live TCP panel; B toggles live YOLO markings; K toggles robot colliders; G shuffles random cases.\nDrag mouse to orbit; wheel zoom. Escape closes. Robot API: 127.0.0.1:8082.\nHeadless requires --steps. Vision requires rendering (use --hidden for batches).\n--until-done stops a finite case run on success/failure and captures that outcome.\nRobot motion is kinematic; grasp uses a constraint after both fingers contact.\n");
}
fn main(argc, argv) {
    if !pl_init() { return 1; } h_environment(argc, argv); gx_env = argv + (argc + 1) * 8;
    ps_serial_config = "./puppybot.json";
    ps_vision_binary = "build/flex/puppybot-vision"; ps_vision_manifest = "build/flex/vision/yolo26n/model.json"; ps_vision_kernel = "build/flex/pup-kernels"; ps_vision_backend = "auto"; ps_vision_root = "build/flex/sim/vision";
    let headless = 0; let hidden = 0; let steps = 0; let demo = 0; let pickup = 0; let realtime = 0; let capture = 0; let record = 0; let tcp_view = -1; let detector_view = -1; let case_id = 0; let list_cases = 0;
    let model = "build/flex/sim/puppybot.bin"; let bind = "127.0.0.1:8082"; let i = 1; let environment = 0; let spawn = 0;
    let until_done = 0; let drift_arg = 0; let sensor_capture = 0; let video = 0; let video_fps = 0; let visual_mode = -1; let mapping_arg = 0; let case_file = 0; let observer_distance = 0;
    while i < argc {
        let arg = pb_vget(argv, i);
        if pl_equal(arg, "--help") { ps_usage(); return 0; }
        if pl_equal(arg, "--list-cases") { list_cases = 1; }
        else if pl_equal(arg, "--external-serial") { ps_external = 1; realtime = 1; }
        else if pl_equal(arg, "--headless") { headless = 1; }
        else if pl_equal(arg, "--hidden") { hidden = 1; }
        else if pl_equal(arg, "--oracle-labels") { ps_agent_oracle = 1; }
        else if pl_equal(arg, "--oracle-cache-check") { ps_oracle_cache_verify = 1; }
        else if pl_equal(arg, "--colliders") { ps_colliders = 1; }
        else if pl_equal(arg, "--demo") { demo = 1; }
        else if pl_equal(arg, "--pickup") { pickup = 1; }
        else if pl_equal(arg, "--pickup-release") { pickup = 2; }
        else if pl_equal(arg, "--vision-pickup") { pickup = 1; ps_vision_requested = 1; }
        else if pl_equal(arg, "--vision-pickup-release") { pickup = 2; ps_vision_requested = 1; }
        else if pl_equal(arg, "--realtime") { realtime = 1; }
        else if pl_equal(arg, "--paused") { ps_paused = 1; }
        else if pl_equal(arg, "--until-done") { until_done = 1; }
        else if pl_equal(arg, "--discover") { ps_discovery_enabled = 1; }
        else if pl_equal(arg, "--detector-view") { detector_view = 1; }
        else if pl_equal(arg, "--no-detector-view") { detector_view = 0; }
        else if pl_equal(arg, "--tcp-view") { tcp_view = 1; }
        else if pl_equal(arg, "--no-tcp-view") { tcp_view = 0; }
        else if pl_equal(arg, "--camera-panels") { ps_previews = 1; }
        else if pl_equal(arg, "--no-camera-panels") { ps_previews = 0; }
        else if pl_equal(arg, "--breadcrumbs") { ps_crumb_enabled = 1; ps_crumb_repeat = 1; }
        else if pl_equal(arg, "--visual-odometry") { ps_crumb_enabled = 1; visual_mode = 1; }
        else if pl_equal(arg, "--no-visual-odometry") { visual_mode = 0; }
        else if pl_equal(arg, "--stock-landmarks") { ps_stock_enabled = 1; }
        else if pl_equal(arg, "--stock-pickup") { ps_stock_enabled = 1; ps_stock_pickup = 1; }
        else if pl_equal(arg, "--no-breadcrumb-corrections") { ps_crumb_enabled = 1; ps_crumb_apply = 0; }
        else {
            if i + 1 >= argc { ps_usage(); return 2; } let value = pb_vget(argv, i + 1); i = i + 1;
            if pl_equal(arg, "--config") { ps_serial_config = value; }
            else if pl_equal(arg, "--temperature") { ps_serial_temperature = pl_integer(value, pl_size(value)); if pl_bad_number || ps_serial_temperature < 0 || ps_serial_temperature > 255 { return 2; } }
            else if pl_equal(arg, "--jam") { ps_serial_jam = pl_integer(value, pl_size(value)); if pl_bad_number || ps_serial_jam < 0 || ps_serial_jam > 3 { return 2; } }
            else if pl_equal(arg, "--steps") { steps = pl_integer(value, pl_size(value)); if pl_bad_number || steps < 1 || steps > 1000000 { return 2; } }
            else if pl_equal(arg, "--agent-fd") { ps_agent_fd = pl_integer(value, pl_size(value)); if pl_bad_number || ps_agent_fd < 3 { return 2; } }
            else if pl_equal(arg, "--observer-distance-mm") { observer_distance = pl_integer(value, pl_size(value)); if pl_bad_number || observer_distance < 300 || observer_distance > 16000 { pl_print(2, "--observer-distance-mm must be 300..16000.\n"); return 2; } }
            else if pl_equal(arg, "--video") { video = value; }
            else if pl_equal(arg, "--video-fps") { ps_video_fps = pl_integer(value, pl_size(value)); if pl_bad_number || ps_video_fps < 1 || ps_video_fps > 50 { pl_print(2, "--video-fps must be an integer from 1 to 50.\n"); return 2; } video_fps = 1; }
            else if pl_equal(arg, "--seed") { ps_case_seed = pl_integer(value, pl_size(value)); if pl_bad_number || ps_case_seed < 0 || ps_case_seed > 4294967295 { return 2; } }
            else if pl_equal(arg, "--localization") { if pl_equal(value, "oracle") { ps_local_requested = 0; } else if pl_equal(value, "wheel") { ps_local_requested = 1; } else if pl_equal(value, "wheel-drift") { ps_local_requested = 2; } else { return 2; } }
            else if pl_equal(arg, "--odometry-seed") { ps_local_seed = pl_integer(value, pl_size(value)); if pl_bad_number || ps_local_seed < 0 || ps_local_seed > 4294967295 { return 2; } }
            else if pl_equal(arg, "--odometry-drift") || pl_equal(arg, "--drift") { ps_local_drift = pl_integer(value, pl_size(value)); if pl_bad_number || ps_local_drift < 0 || ps_local_drift > 100 { return 2; } if pl_equal(arg, "--drift") { drift_arg = 1; } }
            else if pl_equal(arg, "--case") { case_id = value; }
            else if pl_equal(arg, "--case-file") { case_file = value; }
            else if pl_equal(arg, "--map-output") { ps_discovery_root = value; mapping_arg = 1; }
            else if pl_equal(arg, "--mapping-scans") { mapping_arg = 1; ps_discovery_limit = pl_integer(value, pl_size(value)); if pl_bad_number || ps_discovery_limit < 1 || ps_discovery_limit > 100 { return 2; } }
            else if pl_equal(arg, "--model") { model = value; }
            else if pl_equal(arg, "--environment") { environment = value; }
            else if pl_equal(arg, "--spawn") { spawn = value; }
            else if pl_equal(arg, "--bind") { bind = value; }
            else if pl_equal(arg, "--record") { record = value; }
            else if pl_equal(arg, "--gym-output") { ps_gym_directory = value; }
            else if pl_equal(arg, "--search-output") { ps_brick_output = value; }
            else if pl_equal(arg, "--breadcrumb-output") { ps_crumb_output = value; ps_crumb_enabled = 1; }
            else if pl_equal(arg, "--capture") { capture = value; }
            else if pl_equal(arg, "--sensor-capture") { sensor_capture = value; }
            else if pl_equal(arg, "--landmark-output") { ps_stock_output = value; ps_stock_enabled = 1; }
            else if pl_equal(arg, "--landmark-jpeg-quality") { ps_stock_quality = pl_integer(value, pl_size(value)); if pl_bad_number || ps_stock_quality < 1 || ps_stock_quality > 100 { return 2; } }
            else if pl_equal(arg, "--landmark-confidence") { ps_stock_confidence = pl_integer(value, pl_size(value)); if pl_bad_number || ps_stock_confidence < 25 || ps_stock_confidence > 100 { return 2; } }
            else if pl_equal(arg, "--camera") { if pl_equal(value, "tcp") { ps_camera_mode = 2; } else if pl_equal(value, "orbit") { ps_camera_mode = 0; } else { return 2; } }
            else if pl_equal(arg, "--vision-binary") { ps_vision_binary = value; }
            else if pl_equal(arg, "--detector-model") { ps_vision_manifest = value; }
            else if pl_equal(arg, "--vision-kernel") { ps_vision_kernel = value; }
            else if pl_equal(arg, "--vision-backend") { ps_vision_backend = value; }
            else if pl_equal(arg, "--vision-output") { ps_vision_root = value; }
            else { ps_usage(); return 2; }
        }
        i = i + 1;
    }
    if ps_external && (case_id || case_file || demo || pickup || ps_discovery_enabled || ps_stock_enabled || ps_gym_directory || ps_crumb_enabled) { pl_print(2, "External serial mode requires a manual scene, without an embedded policy or Gym worker.\n"); return 2; }
    if !ps_catalog_load() { pl_print(2, "Invalid/missing simulation case catalog.\n"); return 2; }
    if list_cases { pl_write(1, ps_catalog, ps_catalog_size); return 0; }
    if case_file {
        if case_id { pl_print(2, "Choose --case or --case-file.\n"); return 2; }
        let index = ps_case_file(case_file); if index < 0 { pl_print(2, "Invalid external case file or duplicate case ID.\n"); return 2; } case_id = ps_catalog_entries + index * 768;
    }
    if ps_stock_pickup && !case_id { case_id = "stock-landmark-pickup"; }
    if case_id && ps_stock_case(case_id) { ps_stock_enabled = 1; ps_stock_pickup = 1; }
    if until_done && ((!case_id && !ps_stock_enabled && !ps_discovery_enabled) || !steps) { ps_usage(); return 2; }
    if ps_stock_enabled && (headless || (case_id && !ps_stock_pickup) || demo || pickup || detector_view == 0 || ps_previews == 0) { pl_print(2, "Stock landmarks require rendering and their own controller/camera panels.\n"); return 2; }
    if ps_stock_pickup && (!ps_stock_case(case_id) || ps_crumb_enabled || ps_local_requested == 0) { pl_print(2, "Stock pickup requires a stock-landmark case and wheel localization.\n"); return 2; }
    if ps_stock_pickup && ps_local_requested < 0 { ps_local_requested = 1; }
    if case_id {
        if demo || pickup || !ps_case_load(ps_case_find(case_id)) { pl_print(2, "Unknown/invalid case or conflicting controller options.\n"); return 2; } ps_case_menu = !ps_stock_pickup;
    }
    if mapping_arg && !ps_discovery_enabled { pl_print(2, "Mapping options require --discover or a discovery pickup case.\n"); return 2; }
    if ps_discovery_enabled && ((case_id && !ps_collect_enabled) || demo || pickup || ps_stock_enabled || headless || ps_local_requested == 0 || ps_crumb_repeat) { pl_print(2, "Discovery requires rendering, wheel localization and its own controller.\n"); return 2; }
    if ps_agent_fd && (!hidden || headless || !ps_seek_enabled || ps_gym_directory) { pl_print(2, "--agent-fd requires a hidden RGB find-return case.\n"); return 2; }
    if ps_agent_oracle && (!ps_agent_fd || ps_external) { pl_print(2, "--oracle-labels requires the training agent bridge.\n"); return 2; }
    if ps_oracle_cache_verify && !ps_agent_oracle { pl_print(2, "--oracle-cache-check requires --oracle-labels.\n"); return 2; }
    if ps_collect_enabled && !mapping_arg { ps_discovery_limit = 100; }
    if (headless && ((!steps && !ps_external) || capture || hidden || ps_paused)) || (capture && !steps) || (hidden && !steps) || (ps_paused && hidden && !ps_gym_directory) || (demo && pickup) { ps_usage(); return 2; }
    if ps_gym_directory && (!case_id || !steps || headless || record || capture || video || !hidden || pl_size(ps_gym_directory) > 3000) { pl_print(2, "Gym output requires a finite hidden case without separate recording/capture options.\n"); return 2; }
    if sensor_capture && (headless || !steps) { pl_print(2, "--sensor-capture requires rendering and a finite --steps budget.\n"); return 2; }
    if (video && headless) || (video_fps && !video) { pl_print(2, "--video requires rendering; --video-fps requires --video.\n"); return 2; }
    if headless && detector_view == 1 { pl_print(2, "Detector view requires rendering; use --hidden instead of --headless.\n"); return 2; }
    if headless && (ps_vision_requested || (case_id && ps_case_camera)) { pl_print(2, "Camera pickup requires rendering; use --hidden instead of --headless.\n"); return 2; }
    if headless && ps_previews == 1 { pl_print(2, "Camera panels require rendering.\n"); return 2; }
    if ps_local_requested > 0 && !ps_house_enabled() && !ps_discovery_enabled { pl_print(2, "Wheel localization requires house collection or discovery.\n"); return 2; }
    if drift_arg && !ps_house_enabled() && !ps_discovery_enabled { pl_print(2, "--drift requires house collection or discovery.\n"); return 2; }
    if drift_arg && ps_local_requested == 0 { pl_print(2, "--drift requires wheel localization; omit --localization oracle.\n"); return 2; }
    if drift_arg { ps_local_requested = 2; }
    if visual_mode == 0 && ps_crumb_enabled { pl_print(2, "--no-visual-odometry conflicts with visual route/correction options.\n"); return 2; }
    if visual_mode < 0 && !ps_crumb_enabled && (ps_house_enabled() || ps_discovery_enabled) && !ps_stock_pickup && ps_local_requested != 0 { ps_crumb_enabled = 1; }
    if ps_crumb_enabled && ((!ps_house_enabled() && !ps_discovery_enabled) || ps_local_requested == 0) { pl_print(2, "Visual odometry requires house collection or discovery with wheel localization.\n"); return 2; }
    if ps_previews < 0 { ps_previews = !hidden && !headless && ps_house_enabled(); }
    if ps_stock_enabled { ps_previews = 1; detector_view = 1; realtime = 1; if !environment { environment = "apartment"; } if !spawn { spawn = "[3.7,0,0]"; if ps_stock_pickup { spawn = "[3.52,0,0]"; } } }
    if (ps_house_enabled() || ps_discovery_enabled) && !environment { environment = "apartment"; }
    if environment {
        if pl_equal(environment, "apartment") { environment = "build/flex/sim/environments/apartment/apartment.bin"; }
        if !ps_environment_load(environment) { pl_print(2, "Invalid/missing Blender environment. Run prepare-environment.py in Blender first.\n"); return 2; }
        ps_radius = 10500; ps_elevation = 60; ps_azimuth = -65;
    }
    if observer_distance { ps_radius = observer_distance; }
    if spawn && !ps_environment_spawn(spawn) { pl_print(2, "--spawn requires an environment and [x,y,headingRadians] inside its bounds.\n"); return 2; }
    ps_tcp_view = tcp_view; if tcp_view < 0 { ps_tcp_view = !hidden && !headless; }
    ps_live_enabled = detector_view; if detector_view < 0 { ps_live_enabled = !hidden && !headless && ps_vision_requested; }
    if !ps_model_load(model) { pl_print(2, "Invalid/missing simulation assets. Run ./flex/scripts/build-sim.sh first.\n"); return 2; }
    if ps_gym_directory {
        if syscall(83, ps_gym_directory, 448, 0, 0, 0, 0) { pl_print(2, "Gym output directory must be new and its parent must exist.\n"); return 2; }
        record = ps_gym_path("simulation.jsonl"); video = ps_gym_path("mission.mp4"); capture = ps_gym_path("outcome.png"); ps_video_fps = 5; until_done = 1;
        ps_brick_output = ps_gym_path("sensor"); if ps_discovery_enabled { ps_discovery_root = ps_gym_path("map"); }
    }
    ps_robot = alloc(8192); ps_system = alloc(2048); ps_config = alloc(448); ps_app = alloc(2048); ps_bus = alloc(16384); ps_plant = alloc(2048);
    ps_trace = alloc(69632); ps_json = alloc(16384); ps_builder = alloc(32); pb_config_default(ps_config); pb_vset(ps_config + 40, 2, 5);
    if ps_external && pc_load(ps_config, ps_serial_config, ps_trace) != 1 { pl_print(2, "External serial mode requires an existing valid --config file.\n"); return 2; }
    if !ps_reset() { pl_print(2, "Controller initialization failed.\n"); return 1; }
    if ps_external && !ps_serial_open() { return 1; }
    if pickup { ps_pickup_start(pickup == 2); }
    let address = alloc(16); let size = pl_size(bind); let colon = ph_find(bind, size, ":", 1);
    if colon < 1 { return 2; } let port = pl_integer(bind + colon + 1, size - colon - 1);
    if pl_bad_number || port < 0 || port > 65535 || !pl_sockaddr(address, bind, colon, port) { return 2; }
    if pnet_init(address) < 0 { pl_print(2, "Cannot bind simulator robot API.\n"); return 1; }
    if record { ps_output = syscall(2, record, 0x800c1, 384, 0, 0, 0); if ps_output < 0 { pl_print(2, "Recording path must be new.\n"); return 2; } }
    pl_builder(ps_builder, ps_json, 16384); pl_text(ps_builder, "PuppyBot Flexscript simulation | robot API port "); pl_int(ps_builder, pn_port); pl_text(ps_builder, "\n"); pl_print(1, ps_json);
    if !headless { ps_render_init(hidden); if ps_live_enabled { ps_live_init(); } ps_usage(); }
    if ps_external { ps_serial_announce(); }
    if ps_stock_enabled { ps_preview_init(); if !ps_stock_begin() { pl_print(2, "Landmark output must be a new writable directory.\n"); return 2; } }
    if ps_environment { pl_print(1, "Blender apartment: full walls in TCP; cutaway world overview. WASD drive, V camera, T TCP inset.\n"); }
    if case_id { ps_case_start(); }
    if !ps_gym_start(steps, model, environment) { pl_print(2, "Cannot initialize Gym artifacts.\n"); return 1; }
    if hidden && video { ps_case_menu = 0; }
    let event = 0; if !headless { event = gui_event(); } let signal = pl_signals(); if signal < 0 { return 1; }
    if video && !ps_video_open(video) { ps_video_close(); ps_render_close(); return 1; }
    let signals = alloc(128); let active = 1; let result = 0; let next = pl_now(); let next_draw = 0; let single = 0; let frames = 0;
    if ps_agent_fd { result = ps_agent_loop(video, capture); active = 0; }
    while active && (!steps || ps_total < steps) {
        let wall = pl_now(); if syscall(0, signal, signals, 128, 0, 0, 0) > 0 { active = 0; if ps_gym_directory { ps_gym_cancelled = 1; } }
        if !ps_gym_poll(wall) { active = 0; if !ps_gym_cancelled { result = 1; } }
        if !headless {
            while gui_poll(event) {
                let kind = gui_event_kind(event); let code = gui_event_code(event);
                if kind == GUI_QUIT || kind == GUI_CLOSE || (kind == GUI_KEY_DOWN && code == GUI_KEY_ESCAPE) { active = 0; }
                if kind == GUI_FOCUS && !code && !ps_external && !ps_task_running() { ps_stop(); }
                if kind == GUI_KEY_DOWN && !gui_event_repeat(event) {
                    if code >= 30 && code <= 33 { ps_selected = code - 30; }
                    if code == 44 { if !ps_task_running() { ps_stop(); } ps_paused = !ps_paused; }
                    if code == 17 && ps_paused { single = 1; }
                    if code == 21 { if !ps_reset() || (ps_stock_enabled && !ps_stock_restart()) { result = 1; active = 0; } }
                    if !ps_external && code == 19 { if !ps_reset() { result = 1; active = 0; } else { if ps_stock_enabled { if !ps_stock_restart() { result = 1; active = 0; } } else if ps_case_index >= 0 { ps_case_start(); } else { ps_pickup_start(0); } } }
                    if code == 18 { ps_task_cancel("manual gripper open"); ps_gripper_command(1); }
                    if code == 6 { ps_task_cancel("manual gripper close"); ps_gripper_command(0); }
                    if code == 10 && ps_case_index >= 0 && ps_case_random { ps_case_seed = (ps_case_seed + 1) & 0xffffffff; if !ps_reset() || !ps_case_start() { result = 1; active = 0; } }
                    if code == 14 { ps_colliders = !ps_colliders; }
                    if !ps_external && code == 43 { ps_case_menu = !ps_case_menu; }
                    if !ps_external && (code == 47 || code == 48) && !ps_discovery_enabled {
                        if ps_stock_enabled { ps_task_cancel("case selection"); ps_stock_enabled = 0; ps_stock_pickup = 0; }
                        let direction = 1; if code == 47 { direction = -1; }
                        let next_case = (ps_case_index + direction + ps_catalog_count) % ps_catalog_count; let tries = 0;
                        // A running arena has no apartment allocation/meshes.
                        // Keep its case cycling valid; CLI loads the house on startup.
                        while tries < ps_catalog_count && !ps_case_available(next_case) { next_case = (next_case + direction + ps_catalog_count) % ps_catalog_count; tries = tries + 1; }
                        if tries < ps_catalog_count && ps_case_load(next_case) { ps_vision_requested = 0; if !ps_reset() { result = 1; active = 0; } ps_case_menu = 1; }
                    }
                    if code == 25 { ps_camera_mode = 2 * !ps_camera_mode; }
                    if code == 23 { ps_tcp_view = !ps_tcp_view; }
                    if code == 15 { ps_previews = !ps_previews; ps_preview_next = 0; }
                    if code == 5 {
                        ps_live_enabled = !ps_live_enabled;
                        if ps_live_job { ps_live_stop(); ps_live_front = -1; ps_live_score = 0; ps_live_state = "starting"; }
                    }
                }
                if kind == GUI_MOUSE_MOVE && gui_mouse_buttons(load64(ps_device)) { ps_azimuth = (ps_azimuth - gui_event_dx(event)) % 360; ps_elevation = pb_clamp(ps_elevation + gui_event_dy(event), 5, 85); }
                if kind == GUI_WHEEL { let limit = 4500; if ps_environment { limit = 16000; } ps_radius = pb_clamp(ps_radius - gui_event_dy(event) * 80, 300, limit); }
            }
            ps_keyboard();
        }
        if !ps_serial_poll(wall) { result = 1; active = 0; }
        pnet_io(wall); if !ps_dispatch(wall) { result = 1; active = 0; }
        if active && (!ps_paused || single) && ((!realtime && (headless || hidden)) || wall >= next || single) {
            next = wall + 20; single = 0;
            if !ps_tick(demo) { pl_print(2, "Simulation step failed (controller, physics or recording).\n"); result = 1; active = 0; }
            pnet_telemetry(ps_app, wall);
        }
        let done = until_done && ((ps_discovery_enabled && ps_discovery_phase >= 6) || ps_case_stage == 12 || ps_case_stage == 13 || (ps_stock_enabled && !ps_stock_pickup && ps_stock_phase >= 4));
        // Camera policies render their clean sensor FBOs at sampling time.
        // Hidden batches need the observer frame only for the final capture;
        // live detector jobs still keep their regular polling/frame cadence.
        if hidden && ps_stock_enabled { ps_live_poll(); }
        if hidden && ps_previews && !ps_stock_enabled { ps_preview_poll(); }
        let draw = (!hidden && wall >= next_draw) || (hidden && ps_live_enabled);
        if hidden && ps_stock_enabled {
            // Keep detector polling independent of the expensive observer.
            // Hidden recordings only need a world frame when saving a scene.
            draw = ps_stock_output && ps_stock_frames && ps_stock_frames != ps_stock_scene && !(ps_stock_frames % 2);
        }
        let video_final = !active || done || (steps && ps_total >= steps);
        let video_due = ps_video_due(ps_total, video_final);
        if video_due { draw = 1; }
        if ps_gym_directory && !active { draw = 1; }
        if !headless && (draw || (steps && ps_total >= steps) || done) {
            next_draw = wall + 20;
            if !hidden || !ps_stock_enabled { ps_live_poll(); } ps_frame(); frames = frames + 1; if frames % 10 == 1 { ps_title(); }
            if !ps_stock_capture_scene() { result = 1; active = 0; }
            if capture && (ps_total >= steps || done || (ps_gym_directory && !active)) { if ps_previews { ps_preview_next = 0; ps_frame(); } if ps_live_enabled { if !ps_live_finish_frame() { result = 1; } ps_frame(); } if !ps_capture(capture) { result = 1; } if ps_live_enabled && !ps_live_capture(capture) { result = 1; } }
            if sensor_capture && (ps_total >= steps || done) { if !ps_sensor_capture(sensor_capture) { result = 1; } }
            if video_due && !ps_video_frame(ps_total, video_final) { result = 1; active = 0; }
            gui_gl_swap(load64(ps_device));
        }
        if done { active = 0; }
        if headless { if realtime { syscall(7, 0, 0, 1, 0, 0, 0); } }
        else if !hidden || realtime || ps_paused { gui_delay(1); }
    }
    let recording = ps_output; ps_output = -1; ps_observation(); ps_output = recording;
    if pickup && (!ps_pickup_passed || (pickup == 2 && ps_pickup_stage != 9)) { pl_print(2, "Pickup incomplete: "); pl_print(2, ps_pickup_reason); pl_print(2, "\n"); result = 1; }
    // A synchronous agent owns its episode horizon. Clean transport shutdown
    // can end an unsuccessful episode; keep mission outcome in the state and
    // reserve a nonzero process status for bridge/render/physics failures.
    if case_id && !ps_case_passed { pl_print(2, "Case incomplete: "); pl_print(2, ps_case_reason); pl_print(2, "\n"); if !ps_agent_fd { result = 1; } }
    if ps_discovery_enabled && ps_discovery_phase != 6 { pl_print(2, "Discovery stopped: "); pl_print(2, ps_discovery_reason); pl_print(2, "\n"); result = 1; }
    if ps_discovery_job { h_stop(ps_discovery_job); ps_discovery_job = 0; }
    if ps_stock_enabled && ps_stock_phase != 4 { pl_print(2, "Landmark return incomplete: "); pl_print(2, ps_stock_reason); pl_print(2, "\n"); result = 1; }
    pl_print(1, ps_json); ps_stop(); if !ps_external { pb_fake_cycle(ps_system, ps_bus, ps_time, ps_trace, 1024); } ps_serial_close();
    if ps_output >= 0 { if syscall(74, ps_output, 0, 0, 0, 0, 0) { result = 1; } syscall(3, ps_output, 0, 0, 0, 0, 0); }
    if video && !ps_video_close() { result = 1; }
    result = ps_gym_finish(result);
    if !headless { ps_live_close(); ps_render_close(); } ph_world_close(ps_physics); ps_environment_close();
    if ps_crumb_log >= 0 { syscall(3, ps_crumb_log, 0, 0, 0, 0, 0); }
    if ps_stock_log >= 0 { syscall(3, ps_stock_log, 0, 0, 0, 0, 0); }
    syscall(3, pn_listener, 0, 0, 0, 0, 0); i = 0; while i < 32 { pnet_close(pn_clients + i * 65536); i = i + 1; } return result;
}
