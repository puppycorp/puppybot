// Small stock-YOLO teach/return experiment. Policy inputs are RGB, detections
// and drive commands only. World pose/map/body IDs belong to the judge.
import "live.flex";
import "stock-route.flex";

global ps_stock_enabled = 0;
global ps_stock_pickup = 0;
global ps_stock_output = 0;
global ps_stock_quality = 95;
global ps_stock_confidence = 40;
global ps_stock_phase = 0;
global ps_stock_reason = 0;
global ps_stock_rgb = 0;
global ps_stock_records = 0;
global ps_stock_count = 0;
global ps_stock_reference = 0;
global ps_stock_candidate = 0;
global ps_stock_patch = 0;
global ps_stock_home_patch = 0;
global ps_stock_run = 0;
global ps_stock_matches = 0;
global ps_stock_frames = 0;
global ps_stock_frame = -1;
global ps_stock_received = -1;
global ps_stock_start = 0;
global ps_stock_travel = 0;
global ps_stock_outbound = 0;
global ps_stock_iou = 0;
global ps_stock_appearance = 0;
global ps_stock_context = 0;
global ps_stock_log = -1;
global ps_stock_log_text = 0;
global ps_stock_log_builder = 0;
global ps_stock_terminal_saved = 0;
global ps_stock_scene = 0;
global ps_stock_scene_done = 0;

fn ps_stock_case(id) { return pl_equal(id, "stock-landmark-pickup") || pl_equal(id, "stock-landmark-room"); }
fn ps_stock_name() {
    if ps_stock_phase == 1 { return "learning"; } if ps_stock_phase == 2 { return "outbound"; }
    if ps_stock_phase == 3 { return "returning"; } if ps_stock_phase == 4 { return "matched"; }
    if ps_stock_phase == 5 { return "failed"; } return "idle";
}
fn ps_stock_reset() {
    ps_route_reset(); ps_floor_reset();
    ps_stock_phase = 0; ps_stock_run = 0; ps_stock_matches = 0; ps_stock_frames = 0; ps_stock_frame = -1; ps_stock_received = -1;
    ps_stock_count = 0; ps_stock_travel = 0; ps_stock_outbound = 0; ps_stock_iou = 0; ps_stock_appearance = 0; ps_stock_reason = "waiting for stock YOLO";
    ps_stock_terminal_saved = 0;
    ps_stock_scene = 0; ps_stock_scene_done = 0;
    if ps_stock_reference { pb_zero(ps_stock_reference, 64); pb_zero(ps_stock_candidate, 64); }
    if ps_stock_log >= 0 { syscall(3, ps_stock_log, 0, 0, 0, 0, 0); ps_stock_log = -1; } return 0;
}
fn ps_stock_init() {
    if ps_stock_rgb { return 1; }
    ps_stock_rgb = alloc(640 * 480 * 3); ps_stock_records = alloc(100 * 64); ps_stock_reference = alloc(64); ps_stock_candidate = alloc(64);
    ps_stock_patch = alloc(256); ps_stock_home_patch = alloc(256); ps_stock_context = alloc(160);
    store64(ps_stock_context + 8, -1); store64(ps_stock_context + 40, ps_text_upload(0, "TCP - STOCK YOLO"));
    ps_stock_log_text = alloc(16384); ps_stock_log_builder = alloc(32); return 1;
}
fn ps_stock_begin() {
    if !ps_stock_pickup && !ps_camera_drive_target() { return 0; }
    ps_stock_init(); ps_stock_reset(); ps_stock_phase = 1; if ps_stock_pickup { ps_stock_phase = 0; } ps_stock_start = ps_total;
    if ps_live_job && load64(ps_live_job) <= 0 { ps_live_state = "starting"; }
    if ps_stock_output {
        let directory = ps_stock_output; if ps_episode > 0 { directory = h_cat3(ps_stock_output, "/episode-", h_int(ps_episode)); }
        if syscall(83, directory, 493, 0, 0, 0, 0) { return 0; }
        ps_stock_log = syscall(2, h_cat(directory, "/observations.jsonl"), 0x800c1, 384, 0, 0, 0);
        if ps_stock_log < 0 { return 0; }
    }
    return 1;
}
fn ps_stock_restart() { if !ps_stock_begin() { return 0; } if ps_stock_pickup { return ps_case_start(); } return 1; }
fn ps_stock_teach() {
    ps_route_teach(); ps_stock_phase = 1; ps_stock_start = ps_total; ps_stock_travel = 0; ps_stock_outbound = 0; ps_stock_run = 0;
    ps_stock_reason = "learning furniture at the visually observed box staging area"; return 1;
}
fn ps_stock_return_begin() {
    if !load64(ps_stock_reference + 32) { return ps_case_fail("no stock landmark learned before pickup"); }
    if !ps_route_begin() { return 0; }
    ps_stock_phase = 3; ps_stock_start = ps_total; ps_stock_matches = 0; ps_stock_reason = "retracing driven route; stock furniture view confirms home";
    pb_drive_stop(pb_robot_drive(ps_robot), ps_time); return 1;
}
fn ps_stock_finish(phase, reason) {
    if phase == 4 { ps_route_arrived(); }
    ps_stock_phase = phase; ps_stock_reason = reason; pb_drive_stop(pb_robot_drive(ps_robot), ps_time); return 0;
}
fn ps_stock_static(class) { return class == 56 || class == 57 || class == 58 || class == 60 || class == 62 || class == 73 || class == 74 || class == 75; }
fn ps_stock_overlap(a, b) {
    let w = f64_sub(pb_fmin(load64(a + 16), load64(b + 16)), pb_fmax(load64(a), load64(b)));
    let h = f64_sub(pb_fmin(load64(a + 24), load64(b + 24)), pb_fmax(load64(a + 8), load64(b + 8)));
    if f64_le(w, 0) || f64_le(h, 0) { return 0; }
    let intersection = f64_mul(w, h);
    let area = f64_mul(f64_sub(load64(a + 16), load64(a)), f64_sub(load64(a + 24), load64(a + 8)));
    let other = f64_mul(f64_sub(load64(b + 16), load64(b)), f64_sub(load64(b + 24), load64(b + 8)));
    return f64_div(intersection, f64_sub(f64_add(area, other), intersection));
}
fn ps_stock_describe(box, out) {
    let x = f64_to_i64_nearest(load64(box)); let y = f64_to_i64_nearest(load64(box + 8));
    let w = f64_to_i64_nearest(f64_sub(load64(box + 16), load64(box))); let h = f64_to_i64_nearest(f64_sub(load64(box + 24), load64(box + 8))); let i = 0;
    while i < 256 {
        let u = pb_clamp(x + (i % 16 * 2 + 1) * w / 32, 0, 639); let v = pb_clamp(y + (i / 16 * 2 + 1) * h / 32, 0, 479);
        let p = ps_stock_rgb + ((479 - v) * 640 + u) * 3;
        store8(out + i, (77 * load8(p) + 150 * load8(p + 1) + 29 * load8(p + 2)) / 256); i = i + 1;
    } return 1;
}
fn ps_stock_difference(a, b) {
    let total = 0; let i = 0; while i < 256 { total = total + pb_abs(load8(a + i) - load8(b + i)); i = i + 1; } return ps_number(total, 256);
}
fn ps_stock_state(b) {
    pl_text(b, ",\"stockLandmarks\":{\"source\":\"stock-yolo-rgb-and-drive-commands\",\"oraclePose\":false,\"mapInput\":false,\"depthInput\":false,\"phase\":"); pj_text(b, ps_stock_name());
    pl_text(b, ",\"reason\":"); pj_text(b, ps_stock_reason); pl_text(b, ",\"frameId\":"); pl_int(b, ps_stock_frame); pl_text(b, ",\"receivedStep\":"); pl_int(b, ps_stock_received);
    pl_text(b, ",\"jpegQuality\":"); pl_int(b, ps_stock_quality);
    pl_text(b, ",\"pickupSequence\":"); pj_bool_text(b, ps_stock_pickup);
    pl_text(b, ",\"minimumConfidence\":"); pl_float(b, ps_number(ps_stock_confidence, 100));
    pl_text(b, ",\"frames\":"); pl_int(b, ps_stock_frames); pl_text(b, ",\"stableObservations\":"); pl_int(b, ps_stock_run); pl_text(b, ",\"returnMatches\":"); pl_int(b, ps_stock_matches);
    pl_text(b, ",\"commandTravelM\":"); pl_float(b, ps_stock_travel); pl_text(b, ",\"outboundM\":"); pl_float(b, ps_stock_outbound);
    pl_text(b, ",\"overlap\":"); pl_float(b, ps_stock_iou); pl_text(b, ",\"appearanceDifference\":"); pl_float(b, ps_stock_appearance);
    pl_text(b, ",\"referenceClassId\":"); if ps_stock_reference && load64(ps_stock_reference + 32) { pl_int(b, load64(ps_stock_reference + 40)); } else { pl_text(b, "null"); }
    if ps_stock_pickup { ps_route_state(b); }
    return pl_text(b, "}");
}
fn ps_stock_event() {
    if ps_stock_log < 0 { return 1; } let b = ps_stock_log_builder; pl_builder(b, ps_stock_log_text, 16384);
    pl_text(b, "{\"step\":"); pl_int(b, ps_total); ps_stock_state(b);
    if ps_stock_pickup { pl_text(b, ",\"casePhase\":"); pj_text(b, ps_case_phase_name()); pl_text(b, ",\"held\":"); pj_bool_text(b, ps_gripper_held); }
    pl_text(b, "}\n");
    return !load64(b + 24) && !pl_write(ps_stock_log, ps_stock_log_text, load64(b + 8));
}
fn ps_stock_decide() {
    if ps_stock_phase != 1 && ps_stock_phase != 3 { return 0; }
    let best = -1; let quality = 0; let ambiguous = 0; let i = 0;
    ps_stock_iou = 0; ps_stock_appearance = 0;
    while i < ps_stock_count {
        let r = ps_stock_records + i * 64; let score = load64(r + 32); let class = load64(r + 40);
        if ps_stock_static(class) && f64_ge(score, ps_number(ps_stock_confidence, 100)) {
            if ps_stock_phase == 1 && f64_gt(score, quality) { best = i; quality = score; }
            if ps_stock_phase == 3 && class == load64(ps_stock_reference + 40) {
                let overlap = ps_stock_overlap(r, ps_stock_reference); ps_stock_describe(r, ps_stock_patch);
                let appearance = ps_stock_difference(ps_stock_patch, ps_stock_home_patch);
                if f64_ge(overlap, ps_number(88, 100)) && f64_le(appearance, f64_from_i64(14)) {
                    ambiguous = ambiguous + 1; best = i; ps_stock_iou = overlap; ps_stock_appearance = appearance;
                }
            }
        } i = i + 1;
    }
    if ps_stock_phase == 1 {
        if best < 0 { ps_stock_run = 0; return 0; } let selected = ps_stock_records + best * 64;
        if ps_stock_run && load64(selected + 40) == load64(ps_stock_candidate + 40) && f64_ge(ps_stock_overlap(selected, ps_stock_candidate), ps_number(7, 10)) { ps_stock_run = ps_stock_run + 1; }
        else { ps_stock_run = 1; }
        pb_copy(ps_stock_candidate, selected, 64);
        if ps_stock_run >= 3 {
            pb_copy(ps_stock_reference, selected, 64); ps_stock_describe(selected, ps_stock_home_patch);
            ps_stock_phase = 2; ps_stock_start = ps_total; ps_stock_reason = "stock furniture landmark learned from three RGB observations";
        }
    } else {
        if best >= 0 && ambiguous == 1 && ps_route_near_home() { ps_stock_matches = ps_stock_matches + 1; }
        else { ps_stock_matches = 0; }
        if ps_stock_matches >= 3 { ps_stock_finish(4, "saved furniture view matched in three fresh stock-YOLO frames"); }
    } return 1;
}
fn ps_stock_result(result, size) {
    if !ps_stock_pickup && (!gs_reached(ps_plant, ps_pickup_targets) || !gs_stopped(ps_plant)) { return 0; }
    // Raw detections retain all classes. The policy's static-class, confidence,
    // temporal and appearance gates are explicit, independent of the model.
    let detections = pj_need(result, "detections", 3); ps_stock_count = 0; let i = 0;
    while i < pj_count(detections) && i < 100 {
        let d = pj_index(detections, i); let box = pj_need(d, "box", 3); if pj_error || pj_count(box) != 4 { return 0; }
        let r = ps_stock_records + i * 64; let k = 0;
        while k < 4 {
            let v = pj_real_node(pj_index(box, k)); let limit = 640; if k % 2 { limit = 480; }
            if pj_error || !f64_is_finite(v) || f64_lt(v, 0) || f64_gt(v, f64_from_i64(limit)) { return 0; } store64(r + k * 8, v); k = k + 1;
        }
        if f64_le(load64(r + 16), load64(r)) || f64_le(load64(r + 24), load64(r + 8)) { return 0; }
        store64(r + 32, pj_real(d, "confidence")); store64(r + 40, pj_integer(d, "classId", 0, 255)); store64(r + 48, pj_string_field(d, "label"));
        ps_stock_count = ps_stock_count + 1; i = i + 1;
    }
    if pj_error { return 0; } ps_stock_frame = ps_live_step; ps_stock_received = ps_total; ps_stock_frames = ps_stock_frames + 1;
    if ps_total - ps_stock_frame <= 20 && !ps_paused { ps_stock_decide(); }
    if ps_stock_terminal_saved { return 1; }
    if !ps_stock_event() { return 0; }
    if ps_stock_output {
        let directory = ps_stock_output; if ps_episode > 0 { directory = h_cat3(ps_stock_output, "/episode-", h_int(ps_episode)); }
        let stem = h_cat3(directory, "/frame-", h_int(ps_stock_frames));
        if pl_atomic_file(h_cat(stem, ".json"), ps_live_buffer, size) { return 0; }
        if pl_atomic_file(h_cat(stem, ".jpg"), ps_live_packet + 16, ps_live_jpeg_size) { return 0; }
        let target = ps_render_target; let camera = ps_camera_mode; ps_render_target = load64(ps_live_targets + ps_live_back * 8); ps_camera_mode = 2;
        render_gl(ps_device, "glBindFramebuffer", 0x8d40, load64(ps_render_target + 16), 0, 0, 0, 0);
        pb_copy(ps_eye, ps_live_pose, 24); pb_copy(ps_target, ps_live_pose + 24, 24); pb_copy(ps_up, ps_live_pose + 48, 24);
        let ok = ps_capture_at(h_cat(stem, ".png"), ps_stock_frame, ps_live_time); ps_render_target = target; ps_camera_mode = camera; if !ok { return 0; }
    }
    if (!ps_stock_pickup && ps_stock_phase >= 4) || (ps_stock_pickup && (ps_case_stage == 12 || ps_case_stage == 13)) { ps_stock_terminal_saved = 1; }
    return 1;
}
fn ps_stock_mark() {
    render_gl(ps_device, "glEnable", 0x0c11, 0, 0, 0, 0, 0); let i = 0;
    while i < ps_stock_count {
        let r = ps_stock_records + i * 64; let x1 = f64_to_i64_trunc(load64(r)); let y1 = f64_to_i64_trunc(load64(r + 8));
        let x2 = f64_to_i64_trunc(load64(r + 16)); let y2 = f64_to_i64_trunc(load64(r + 24));
        ps_panel_clear(x1, 480 - y2, x2 - x1, 2, 10, 100, 20); ps_panel_clear(x1, 480 - y1 - 2, x2 - x1, 2, 10, 100, 20);
        ps_panel_clear(x1, 480 - y2, 2, y2 - y1, 10, 100, 20); ps_panel_clear(x2 - 2, 480 - y2, 2, y2 - y1, 10, 100, 20);
        pl_builder(ps_preview_builder, ps_preview_text, 128); pl_text(ps_preview_builder, load64(r + 48)); pl_char(ps_preview_builder, 32);
        pl_int(ps_preview_builder, f64_to_i64_nearest(f64_mul(load64(r + 32), f64_from_i64(100)))); pl_char(ps_preview_builder, 37);
        ps_preview_mesh = ps_text_upload(ps_preview_mesh, ps_preview_text); render_gl(ps_device, "glScissor", 0, 0, 640, 480, 0, 0);
        ps_text_draw(ps_preview_mesh, 640, 480, pb_clamp(x1, 0, 450), pb_max(0, y1 - 18)); i = i + 1;
    }
    render_gl(ps_device, "glDisable", 0x0c11, 0, 0, 0, 0, 0);
    store64(ps_stock_context, load64(ps_live_targets + ps_live_back * 8)); store64(ps_stock_context + 8, ps_stock_frame); store64(ps_stock_context + 16, ps_live_time);
    store64(ps_stock_context + 32, ps_stock_count); pb_copy(ps_stock_context + 64, ps_live_pose, 72); return 1;
}
fn ps_stock_update() {
    if !ps_stock_enabled || ps_stock_phase < 1 || ps_stock_phase == 5 { return 0; }
    if ps_stock_phase == 4 && !ps_stock_pickup { return 0; }
    let d = pb_robot_drive(ps_robot); let distance = ps_number(load64(d + 48) + load64(d + 56), 20000);
    ps_stock_travel = f64_add(ps_stock_travel, distance); ps_stock_outbound = pb_fmax(ps_stock_outbound, ps_stock_travel);
    if ps_stock_pickup && ps_stock_phase == 4 { return 0; }
    if pl_equal(ps_live_state, "error") { return ps_stock_finish(5, "stock detector worker failed"); }
    let limit = 2500; if ps_stock_pickup && ps_stock_phase == 3 { limit = ps_route_count + 2500; }
    if (!ps_stock_pickup || ps_stock_phase != 2) && ps_total - ps_stock_start > limit { return ps_stock_finish(5, "landmark not recognized before timeout"); }
    if ps_stock_phase == 1 || ps_stock_frame < 0 || ps_total - ps_stock_frame > 20 { pb_drive_stop(d, ps_time); return 0; }
    if ps_stock_pickup && ps_stock_phase == 2 { return 1; }
    if ps_stock_phase == 2 && f64_ge(ps_stock_travel, ps_number(8, 10)) { ps_stock_phase = 3; ps_stock_start = ps_total; ps_stock_matches = 0; ps_stock_reason = "returning by saved stock landmark view"; }
    if ps_stock_pickup && ps_stock_phase == 3 { return ps_route_tick(); }
    if ps_stock_phase == 3 && f64_lt(ps_stock_travel, ps_number(-25, 100)) { return ps_stock_finish(5, "passed the return search window without a visual match"); }
    let speed = 20; if ps_stock_phase == 3 { speed = -10; }
    // Stop on a potential match while collecting independent confirmations.
    if ps_stock_phase == 3 && ps_stock_matches { speed = 0; }
    pb_drive_steer(d, speed, 0, ps_time); return 1;
}
fn ps_stock_capture_scene() {
    if !ps_stock_pickup || !ps_stock_output || !ps_stock_frames || ps_stock_frames == ps_stock_scene || ps_stock_scene_done { return 1; }
    let done = ps_case_stage == 12 || ps_case_stage == 13; if ps_stock_frames % 2 && !done { return 1; }
    let directory = ps_stock_output; if ps_episode > 0 { directory = h_cat3(ps_stock_output, "/episode-", h_int(ps_episode)); }
    ps_stock_scene = ps_stock_frames; if done { ps_stock_scene_done = 1; }
    return ps_capture(h_cat3(directory, "/scene-", h_cat(h_int(ps_stock_scene), ".png")));
}
