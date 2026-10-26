// Navigation curriculum: see one brick, consume it, return to an observed box.
// Consumption is a simulator event. Only RGB detections can trigger it; object
// bodies are consulted here to remove the matching prop, never to plan motion.
global ps_seek_enabled = 0;
global ps_seek_found = 0;
global ps_seek_consumed = -1;
global ps_seek_detection_step = -1;
global ps_seek_detection = 0;
global ps_seek_return_observations = 0;

fn ps_seek_reset() {
    ps_seek_found = 0; ps_seek_consumed = -1; ps_seek_detection_step = -1; ps_seek_return_observations = 0;
    if !ps_seek_detection { ps_seek_detection = alloc(128); } pb_zero(ps_seek_detection, 128); return 1;
}
fn ps_seek_consume(detection) {
    // Undo estimated base localization ONLY inside the simulation's event
    // matcher. The actor receives neither this corrected point nor body poses.
    let dx = f64_sub(load64(detection + 32), ps_pose_x()); let dy = f64_sub(load64(detection + 40), ps_pose_y());
    let forward = f64_add(f64_mul(dx, f64_cos(ps_pose_heading())), f64_mul(dy, f64_sin(ps_pose_heading())));
    let lateral = f64_sub(f64_mul(dy, f64_cos(ps_pose_heading())), f64_mul(dx, f64_sin(ps_pose_heading())));
    let x = f64_add(ps_x, f64_sub(f64_mul(forward, f64_cos(ps_heading)), f64_mul(lateral, f64_sin(ps_heading))));
    let y = f64_add(ps_y, f64_add(f64_mul(forward, f64_sin(ps_heading)), f64_mul(lateral, f64_cos(ps_heading))));
    let best = -1; let distance = ps_number(64, 10000); let i = 0;
    while i < ps_case_count {
        let r = ps_case_objects + i * 256; let body = ph_body(ps_physics, load64(r + 184));
        let bx = f64_sub(pb_f32_to_f64(load64(body + 8)), x); let by = f64_sub(pb_f32_to_f64(load64(body + 16)), y);
        let d = f64_add(f64_mul(bx, bx), f64_mul(by, by));
        if !load64(r + 208) && f64_lt(d, distance) { distance = d; best = i; } i = i + 1;
    }
    if best < 0 { return 0; }
    if ps_agent_fd && ps_agent_task == 1 {
        let body = ph_body(ps_physics, load64(ps_case_objects + best * 256 + 184));
        let dx = f64_sub(pb_f32_to_f64(load64(body + 8)), ps_x); let dy = f64_sub(pb_f32_to_f64(load64(body + 16)), ps_y);
        if f64_gt(f64_add(f64_mul(dx, dx), f64_mul(dy, dy)), ps_number(1225, 10000)) { return 0; }
    }
    let r = ps_case_objects + best * 256; let body = ph_body(ps_physics, load64(r + 184));
    // Retain stable body IDs, but park an inert invisible prop below the world.
    // Both contact physics and swept queries now see it away from the floor.
    store64(r + 208, 1); store64(body, 0); store64(body + 24, ps_float(-10, 1));
    ph_vset(body + 64, 0, 0, 0); ph_vset(body + 88, 0, 0, 0); store64(body + 112, 0); ph_vset(body + 120, 0, 0, 0); ph_cache_body(body);
    ps_seek_found = 1; ps_seek_consumed = best; ps_seek_detection_step = ps_total; pb_copy(ps_seek_detection, detection, 128);
    ps_case_reason = "brick seen and consumed; returning to the RGB box landmark"; return 1;
}
fn ps_seek_observe() {
    ps_dock_samples = ps_dock_samples + 1; let dock = ps_dock_detect(); ps_dock_attention(dock);
    if dock && ps_dock_stable >= 3 && !ps_house_ready {
        ps_house_ready = 1; store64(ps_house_home, ps_pose_x()); store64(ps_house_home + 8, ps_pose_y()); store64(ps_house_home + 16, ps_pose_heading());
    }
    ps_brick_detect(); ps_floor_observe();
    if !ps_seek_found {
        let i = 0; while i < ps_brick_count && !ps_seek_found { ps_seek_consume(ps_brick_records + i * 128); i = i + 1; }
    }
    if ps_seek_found && dock && ps_dock_stable >= 3 && ps_total > ps_seek_detection_step {
        let dx = f64_sub(load64(ps_dock_frame + 96), ps_pose_x()); let dy = f64_sub(load64(ps_dock_frame + 104), ps_pose_y());
        let distance = f64_sqrt(f64_add(f64_mul(dx, dx), f64_mul(dy, dy)));
        let error = f64_magnitude(pb_wrap_pi(f64_sub(f64_atan2(dy, dx), ps_pose_heading())));
        let drive = pb_robot_drive(ps_robot);
        if f64_ge(distance, ps_number(30, 100)) && f64_le(distance, ps_number(65, 100)) && f64_le(error, pb_radians(f64_from_i64(35))) && !load64(drive + 48) && !load64(drive + 56) {
            ps_seek_return_observations = ps_seek_return_observations + 1;
            if ps_seek_return_observations >= 3 {
                ps_case_reason = "one RGB brick consumed and stopped facing the freshly observed box";
                ps_case_passed = 1; ps_case_phase(12); pr_stop(ps_app, ps_time); ps_discovery_finish(ps_case_reason, 0); return 1;
            }
            return 1;
        }
    }
    ps_seek_return_observations = 0; return dock && ps_dock_stable < 3;
}
fn ps_seek_request(b) {
    if !ps_seek_enabled { return 0; }
    pl_text(b, ",\"seek\":{\"returning\":"); pj_bool_text(b, ps_seek_found);
    pl_text(b, ",\"box\":");
    if ps_dock_seen >= 0 { pl_char(b, 91); pl_float(b, load64(ps_dock_frame + 96)); pl_char(b, 44); pl_float(b, load64(ps_dock_frame + 104)); pl_char(b, 93); }
    else { pl_text(b, "null"); } return pl_char(b, 125);
}
fn ps_seek_observation(b) {
    if !ps_seek_enabled { return 0; }
    pl_text(b, ",\"findReturn\":{\"phase\":"); if ps_case_passed { pj_text(b, "docked"); } else if ps_seek_found { pj_text(b, "return"); } else { pj_text(b, "search"); }
    pl_text(b, ",\"consumedIndex\":"); pl_int(b, ps_seek_consumed); pl_text(b, ",\"detectionStep\":"); pl_int(b, ps_seek_detection_step);
    pl_text(b, ",\"detectionPixelBox\":["); let i = 0; while i < 4 { if i { pl_char(b, 44); } pl_int(b, load64(ps_seek_detection + i * 8)); i = i + 1; }
    pl_text(b, "],\"detectedPoint\":["); i = 0; while i < 3 { if i { pl_char(b, 44); } pl_float(b, load64(ps_seek_detection + 32 + i * 8)); i = i + 1; }
    pl_text(b, "],\"stableReturnObservations\":"); pl_int(b, ps_seek_return_observations); return pl_char(b, 125);
}
