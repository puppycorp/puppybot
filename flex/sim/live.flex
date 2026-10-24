// Display-only YOLO observations. Each box stays on the exact sampled RGB
// frame that produced it; these results never change the pickup controller.
import "vision.flex";
import "../gym/ipc.flex";

global ps_live_enabled = 0;
global ps_live_job = 0;
global ps_live_buffer = 0;
global ps_live_packet = 0;
global ps_live_targets = 0;
global ps_live_front = -1;
global ps_live_back = 0;
global ps_live_state = 0;
global ps_live_deadline = 0;
global ps_live_next = 0;
global ps_live_sequence = 0;
global ps_live_request = 0;
global ps_live_mode = 2;
global ps_live_front_mode = 2;
global ps_live_front_episode = -1;
global ps_live_pose = 0;
global ps_live_front_pose = 0;
global ps_live_step = 0;
global ps_live_front_step = 0;
global ps_live_episode = -1;
global ps_live_frame = 0;
global ps_live_time = 0;
global ps_live_score = 0;
global ps_live_box = 0;
global ps_live_label = 0;
global ps_live_caption = 0;
global ps_live_caption_mode = 0;
global ps_live_text = 0;
global ps_live_text_mesh = 0;
global ps_live_json = 0;
global ps_live_json_size = 0;
global ps_live_jpeg_size = 0;
global ps_live_saved_jpeg = 0;
global ps_live_saved_size = 0;
global ps_live_jpeg_library = 0;
global ps_live_jpeg_handle = 0;
global ps_live_log = 0;
global ps_live_limit = 48000;

fn ps_live_init() {
    ps_live_limit = 48000; if ps_stock_enabled { ps_live_limit = 131072; }
    ps_live_job = alloc(32); pb_zero(ps_live_job, 32); ps_live_buffer = alloc(65536); ps_live_packet = alloc(ps_live_limit + 16); ps_live_targets = alloc(16);
    ps_live_pose = alloc(72); ps_live_front_pose = alloc(72);
    ps_live_box = alloc(32); ps_live_label = alloc(128); ps_live_text = alloc(256); ps_live_json = alloc(32768); ps_live_saved_jpeg = alloc(ps_live_limit);
    ps_live_caption = ps_text_upload(0, "YOLO TCP"); ps_live_text_mesh = ps_text_upload(0, "YOLO"); ps_live_state = "starting";
    return 1;
}
fn ps_live_stop() {
    if ps_live_job && load64(ps_live_job) > 0 { gx_finish(load64(ps_live_job), load64(ps_live_job + 8)); store64(ps_live_job, 0); }
    ps_live_deadline = 0; return 0;
}
fn ps_live_error() { ps_live_stop(); ps_live_front = -1; ps_live_score = 0; ps_live_state = "error"; return 0; }
fn ps_live_start() {
    let made = syscall(83, ps_vision_root, 448, 0, 0, 0, 0); if made && made != -17 { return ps_live_error(); }
    ps_live_log = h_cat3(ps_vision_root, "/live-", h_cat3(h_int(syscall(39, 0, 0, 0, 0, 0, 0)), "-", h_cat(h_int(ps_live_sequence), ".log")));
    ps_live_sequence = ps_live_sequence + 1;
    let args = alloc(96); store64(args, ps_vision_binary); store64(args + 8, "worker"); store64(args + 16, "--model"); store64(args + 24, ps_vision_manifest);
    store64(args + 32, "--kernel"); store64(args + 40, ps_vision_kernel); store64(args + 48, "--backend"); store64(args + 56, ps_vision_backend); store64(args + 64, 0);
    if ps_stock_enabled { store64(args + 64, "--frame-bytes"); store64(args + 72, "131072"); store64(args + 80, 0); }
    let ok = gx_spawn(ps_vision_binary, args, ps_live_log, ps_live_job); syscall(11, args, 96, 0, 0, 0, 0);
    if !ok { return ps_live_error(); } ps_live_state = "loading"; ps_live_deadline = pl_now() + 15000; return 1;
}
fn ps_live_encode() {
    if !ps_live_jpeg_library {
        ps_live_jpeg_library = ffi_open("libturbojpeg.so.0"); if !ps_live_jpeg_library { return 0; }
        ps_live_jpeg_handle = ffi_call(ffi_symbol(ps_live_jpeg_library, "tjInitCompress"), 0, 0, 0, 0, 0, 0);
    }
    if !ps_live_jpeg_handle { return 0; }
    let rgb = alloc(640 * 480 * 3); let args = alloc(88); pb_zero(args, 88);
    render_gl(ps_device, "glPixelStorei", 0x0d05, 1, 0, 0, 0, 0); store64(args + 16, 640); store64(args + 24, 480); store64(args + 32, 0x1907); store64(args + 40, 0x1401); store64(args + 48, rgb);
    ffi_call_words(gui_gl_cached_proc(load64(ps_device), "glReadPixels"), args);
    let output = alloc(16); pb_zero(output, 16); pb_zero(args, 88); store64(args, ps_live_jpeg_handle); store64(args + 8, rgb); store64(args + 16, 640); store64(args + 24, 640 * 3); store64(args + 32, 480);
    store64(args + 48, output); store64(args + 56, output + 8); store64(args + 64, 2); store64(args + 72, 80); if ps_stock_enabled { store64(args + 72, ps_stock_quality); } store64(args + 80, 2);
    let ok = !ffi_call_words(ffi_symbol(ps_live_jpeg_library, "tjCompress2"), args); let size = load64(output + 8);
    if ps_stock_enabled { pb_copy(ps_stock_rgb, rgb, 640 * 480 * 3); }
    if size > ps_live_limit { ok = 0; }
    if ok { pb_copy(ps_live_packet + 16, load64(output), size); ps_live_jpeg_size = size; }
    ffi_call(ffi_symbol(ps_live_jpeg_library, "tjFree"), load64(output), 0, 0, 0, 0, 0);
    syscall(11, rgb, 640 * 480 * 3, 0, 0, 0, 0); syscall(11, args, 88, 0, 0, 0, 0); syscall(11, output, 16, 0, 0, 0, 0); return ok;
}
fn ps_live_sample() {
    if !load64(ps_live_targets + ps_live_back * 8) { store64(ps_live_targets + ps_live_back * 8, ps_vision_target_create()); }
    let target = load64(ps_live_targets + ps_live_back * 8); if !target { return ps_live_error(); }
    let previous_target = ps_render_target; let previous_mode = ps_camera_mode;
    ps_live_mode = 2; if ps_camera_mode == 1 || ps_stock_enabled { ps_live_mode = 1; }
    ps_render_target = target; ps_camera_mode = ps_live_mode; ps_scene(640, 480, 0, 0);
    pb_copy(ps_live_pose, ps_eye, 24); pb_copy(ps_live_pose + 24, ps_target, 24); pb_copy(ps_live_pose + 48, ps_up, 24); ps_live_step = ps_total;
    let ok = ps_live_encode(); ps_render_target = previous_target; ps_camera_mode = previous_mode;
    if !ok { return ps_live_error(); }
    ps_live_request = ps_live_sequence; ps_live_sequence = ps_live_sequence + 1; ps_live_episode = ps_episode;
    store64(ps_live_packet, ps_live_request); store64(ps_live_packet + 8, ps_time);
    let sent = syscall(44, load64(ps_live_job + 8), ps_live_packet, ps_live_jpeg_size + 16, 16384, 0, 0);
    if sent != ps_live_jpeg_size + 16 { return ps_live_error(); }
    ps_live_state = "busy"; ps_live_deadline = pl_now() + 5000; return 1;
}
fn ps_live_select(size) {
    let result = pj_parse(ps_live_buffer, size); if pj_error { return 0; }
    let schema = pj_string_field(result, "schema"); let coordinates = pj_string_field(result, "coordinates"); let frame = pj_need(result, "frame", 4);
    let id = pj_integer(frame, "id", 0, 1000000000); let time = pj_integer(frame, "capturedMs", 0, 1000000000);
    let width = pj_integer(frame, "width", 1, 8192); let height = pj_integer(frame, "height", 1, 8192); let detections = pj_need(result, "detections", 3);
    if pj_error || !pl_equal(schema, "puppybot.detections.v1") || !pl_equal(coordinates, "image-pixels") || width != 640 || height != 480 || id != ps_live_request { return 0; }
    ps_live_score = 0; store8(ps_live_label, 0); pb_zero(ps_live_box, 32); let i = 0;
    while i < pj_count(detections) {
        let d = pj_index(detections, i); let class = pj_integer(d, "classId", 0, 255); let label = pj_string_field(d, "label"); let score = pj_real(d, "confidence");
        if pj_error || !f64_is_finite(score) || f64_lt(score, 0) || f64_gt(score, PB_ONE) { return 0; }
        // Both are common classifications for this orange sphere. Preserve
        // the model's actual label; the pickup planner still requires class 32.
        if (ps_stock_enabled || (class == 32 && pl_equal(label, "sports ball")) || (class == 49 && pl_equal(label, "orange"))) && f64_ge(score, ps_number(25, 100)) && f64_gt(score, ps_live_score) {
            let box = pj_need(d, "box", 3); if pj_error || pj_count(box) != 4 { return 0; } let k = 0;
            while k < 4 {
                let value = pj_real_node(pj_index(box, k)); let limit = 640; if k % 2 { limit = 480; }
                if pj_error || !f64_is_finite(value) || f64_lt(value, 0) || f64_gt(value, f64_from_i64(limit)) { return 0; }
                pb_vset(ps_live_box, k, value); k = k + 1;
            }
            if f64_le(load64(ps_live_box + 16), load64(ps_live_box)) || f64_le(load64(ps_live_box + 24), load64(ps_live_box + 8)) { return 0; }
            ps_live_score = score; pb_copy(ps_live_label, label, pb_min(pl_size(label), 127)); store8(ps_live_label + pb_min(pl_size(label), 127), 0);
        }
        i = i + 1;
    }
    ps_live_frame = id; ps_live_time = time; pb_copy(ps_live_json, ps_live_buffer, size); ps_live_json_size = size;
    if ps_stock_enabled && !ps_stock_result(result, size) { return 0; }
    pb_copy(ps_live_saved_jpeg, ps_live_packet + 16, ps_live_jpeg_size); ps_live_saved_size = ps_live_jpeg_size; return 1;
}
fn ps_live_mark() {
    let target = load64(ps_live_targets + ps_live_back * 8); render_gl(ps_device, "glBindFramebuffer", 0x8d40, load64(target + 16), 0, 0, 0, 0); render_gl(ps_device, "glViewport", 0, 0, 640, 480, 0, 0);
    if !ps_stock_enabled {
        let text = "NO DETECTION"; let builder = alloc(32); pl_builder(builder, ps_live_text, 256);
        if ps_live_score { pl_text(builder, ps_live_label); pl_char(builder, 32); pl_int(builder, f64_to_i64_nearest(f64_mul(ps_live_score, f64_from_i64(100)))); pl_char(builder, 37); text = ps_live_text; }
        ps_live_text_mesh = ps_text_upload(ps_live_text_mesh, text); syscall(11, builder, 32, 0, 0, 0, 0);
        render_gl(ps_device, "glEnable", 0x0c11, 0, 0, 0, 0, 0);
        let x1 = 12; let y1 = 34;
        if ps_live_score {
            x1 = f64_to_i64_trunc(load64(ps_live_box)); y1 = f64_to_i64_trunc(load64(ps_live_box + 8));
            let x2 = f64_to_i64_trunc(load64(ps_live_box + 16)); let y2 = f64_to_i64_trunc(load64(ps_live_box + 24));
            ps_panel_clear(x1, 480 - y2, x2 - x1, pb_min(3, y2 - y1), 10, 100, 20);
            ps_panel_clear(x1, 480 - y1 - pb_min(3, y2 - y1), x2 - x1, pb_min(3, y2 - y1), 10, 100, 20);
            ps_panel_clear(x1, 480 - y2, pb_min(3, x2 - x1), y2 - y1, 10, 100, 20);
            ps_panel_clear(x2 - pb_min(3, x2 - x1), 480 - y2, pb_min(3, x2 - x1), y2 - y1, 10, 100, 20);
        }
        let label_width = pl_size(text) * 12 + 12; x1 = pb_clamp(x1, 0, 640 - label_width); let top = pb_max(0, y1 - 25);
        ps_panel_clear(x1, 480 - top - 24, label_width, 24, 3, 12, 8); render_gl(ps_device, "glScissor", 0, 0, 640, 480, 0, 0);
        ps_text_draw(ps_live_text_mesh, 640, 480, x1 + 6, top + 5); render_gl(ps_device, "glDisable", 0x0c11, 0, 0, 0, 0, 0);
    }
    if ps_stock_enabled { ps_stock_mark(); }
    ps_live_front_mode = ps_live_mode; ps_live_front_episode = ps_live_episode; ps_live_front_step = ps_live_step; pb_copy(ps_live_front_pose, ps_live_pose, 72);
    ps_live_front = ps_live_back; ps_live_back = 1 - ps_live_back; return 1;
}
fn ps_live_poll() {
    if !ps_live_enabled { return 0; } if !ps_live_job { ps_live_init(); }
    if ps_live_episode != ps_episode && ps_live_episode >= 0 { ps_live_front = -1; ps_live_score = 0; }
    if pl_equal(ps_live_state, "starting") { return ps_live_start(); }
    if load64(ps_live_job) <= 0 { return 0; }
    let now = pl_now(); let n = syscall(45, load64(ps_live_job + 8), ps_live_buffer, 65536, 32, 0, 0);
    if n > 0 {
        if pl_equal(ps_live_state, "loading") && n == 14 && pl_case_equal(ps_live_buffer, n, "{\"ready\":true}") { ps_live_state = "ready"; ps_live_deadline = 0; }
        else if pl_equal(ps_live_state, "busy") && n <= 30000 {
            if ps_live_episode == ps_episode { if !ps_live_select(n) { return ps_live_error(); } ps_live_mark(); }
            ps_live_state = "ready"; ps_live_deadline = 0; ps_live_next = now + 150;
        } else { return ps_live_error(); }
    }
    if !n || (n < 0 && n != -11 && n != -4) || gx_reap(load64(ps_live_job), 0) != -2 || (ps_live_deadline && now >= ps_live_deadline) { return ps_live_error(); }
    if pl_equal(ps_live_state, "ready") && now >= ps_live_next { return ps_live_sample(); } return 1;
}
fn ps_live_present(width, height, x, y, mode) {
    if !ps_live_enabled || !ps_live_job { return 0; }
    let key = mode; let text = "YOLO TCP"; if mode == 1 { text = "YOLO ROVER"; }
    if pl_equal(ps_live_state, "error") { key = 10; text = "YOLO ERROR"; } else if ps_live_front < 0 { key = 11; text = "YOLO LOADING"; }
    if ps_live_caption_mode != key { ps_live_caption = ps_text_upload(ps_live_caption, text); ps_live_caption_mode = key; }
    if ps_live_front < 0 || ps_live_front_mode != mode || ps_live_front_episode != ps_episode { return 0; }
    let target = load64(ps_live_targets + ps_live_front * 8); let args = alloc(88); pb_zero(args, 88);
    store64(args + 16, 640); store64(args + 24, 480); store64(args + 32, x); store64(args + 40, y); store64(args + 48, x + width); store64(args + 56, y + height); store64(args + 64, 0x4000); store64(args + 72, 0x2601);
    render_gl(ps_device, "glBindFramebuffer", 0x8ca8, load64(target + 16), 0, 0, 0, 0); render_gl(ps_device, "glBindFramebuffer", 0x8ca9, 0, 0, 0, 0, 0);
    ffi_call_words(gui_gl_cached_proc(load64(ps_device), "glBlitFramebuffer"), args); render_gl(ps_device, "glBindFramebuffer", 0x8ca8, 0, 0, 0, 0, 0);
    syscall(11, args, 88, 0, 0, 0, 0); return 1;
}
fn ps_live_finish_frame() {
    // Finite captures wait for a sample of the final pose. Interactive frames
    // only poll; model loading and inference never block their event loop.
    let deadline = pl_now() + 16000; let wanted = ps_time; ps_live_next = 0;
    while pl_now() < deadline && !pl_equal(ps_live_state, "error") {
        ps_live_poll(); if ps_live_front >= 0 && ps_live_time == wanted && ps_live_episode == ps_episode { return 1; }
        syscall(7, 0, 0, 1, 0, 0, 0);
    }
    return 0;
}
fn ps_live_capture(path) {
    if ps_live_front < 0 { return 1; }
    let jpg = h_cat(path, ".yolo.jpg"); let json = h_cat(path, ".yolo.json"); let png = h_cat(path, ".yolo.png"); let ok = 1;
    let fd = syscall(2, jpg, 0x800c1, 420, 0, 0, 0); if fd < 0 { return 0; } ok = !pl_write(fd, ps_live_saved_jpeg, ps_live_saved_size); syscall(3, fd, 0, 0, 0, 0, 0);
    fd = syscall(2, json, 0x800c1, 420, 0, 0, 0); if fd < 0 { return 0; } if pl_write(fd, ps_live_json, ps_live_json_size) { ok = 0; } syscall(3, fd, 0, 0, 0, 0, 0);
    let target = load64(ps_live_targets + ps_live_front * 8); render_gl(ps_device, "glBindFramebuffer", 0x8d40, load64(target + 16), 0, 0, 0, 0);
    let previous = ps_render_target; ps_render_target = target; let data = alloc(640 * 480 * 3); let args = alloc(88); pb_zero(args, 88);
    store64(args + 16, 640); store64(args + 24, 480); store64(args + 32, 0x1907); store64(args + 40, 0x1401); store64(args + 48, data); render_gl(ps_device, "glPixelStorei", 0x0d05, 1, 0, 0, 0, 0);
    ffi_call_words(gui_gl_cached_proc(load64(ps_device), "glReadPixels"), args); fd = syscall(2, png, 0x800c1, 420, 0, 0, 0);
    if fd < 0 { ok = 0; } else { if !ps_capture_png(fd, data, 640, 480) { ok = 0; } syscall(3, fd, 0, 0, 0, 0, 0); }
    syscall(11, data, 640 * 480 * 3, 0, 0, 0, 0); syscall(11, args, 88, 0, 0, 0, 0); ps_render_target = previous; return ok;
}
fn ps_live_close() {
    ps_live_stop(); if ps_live_caption { render_mesh_close(ps_live_caption); render_mesh_close(ps_live_text_mesh); }
    if ps_live_jpeg_handle { ffi_call(ffi_symbol(ps_live_jpeg_library, "tjDestroy"), ps_live_jpeg_handle, 0, 0, 0, 0, 0); }
    return 0;
}
