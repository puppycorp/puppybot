// RGB camera -> the existing native YOLO executable -> pixel detections ->
// calibrated floor-plane ray. No object poses or simulator IDs enter planning.
import "render.flex";

global ps_vision_requested = 0;
global ps_vision_binary = 0;
global ps_vision_manifest = 0;
global ps_vision_kernel = 0;
global ps_vision_backend = 0;
global ps_vision_root = 0;
global ps_vision_reason = 0;
global ps_vision_state = 0;
global ps_vision_confidence = 0;
global ps_vision_box = 0;
global ps_vision_estimate = 0;
global ps_vision_sensor = 0;
global ps_vision_frame = 0;
global ps_vision_directory = 0;
global ps_vision_image = 0;
global ps_vision_result = 0;
global ps_vision_preview = 0;

fn ps_vision_reset() {
    ps_vision_state = "idle"; ps_vision_reason = "no image analyzed"; ps_vision_confidence = 0;
    ps_vision_directory = 0; ps_vision_frame = 0;
    if !ps_vision_box { ps_vision_box = alloc(32); ps_vision_estimate = alloc(24); }
    pb_zero(ps_vision_box, 32); pb_zero(ps_vision_estimate, 24); return 0;
}
fn ps_vision_fail(reason) { ps_vision_state = "failed"; ps_vision_reason = reason; return 0; }
fn ps_vision_target_create() {
    let target = render_depth_target(ps_device, 640, 480); if !target { return 0; }
    let p = load64(ps_device + 24); gui__put32(p, 0); render_gl(ps_device, "glGenTextures", 1, p, 0, 0, 0, 0);
    let color = render_track(ps_device, 4, gui__u32(p)); if !color { return 0; }
    render_gl(ps_device, "glBindTexture", 0x0de1, color, 0, 0, 0, 0);
    let args = alloc(88); pb_zero(args, 88); store64(args, 0x0de1); store64(args + 16, 0x8051); store64(args + 24, 640); store64(args + 32, 480); store64(args + 48, 0x1907); store64(args + 56, 0x1401);
    ffi_call_words(gui_gl_cached_proc(load64(ps_device), "glTexImage2D"), args); syscall(11, args, 88, 0, 0, 0, 0);
    render_gl(ps_device, "glTexParameteri", 0x0de1, 0x2801, 0x2600, 0, 0, 0); render_gl(ps_device, "glTexParameteri", 0x0de1, 0x2800, 0x2600, 0, 0, 0);
    render_gl(ps_device, "glBindFramebuffer", 0x8d40, load64(target + 16), 0, 0, 0, 0);
    render_gl(ps_device, "glFramebufferTexture2D", 0x8d40, 0x8ce0, 0x0de1, color, 0, 0);
    render_gl(ps_device, "glDrawBuffer", 0x8ce0, 0, 0, 0, 0, 0); render_gl(ps_device, "glReadBuffer", 0x8ce0, 0, 0, 0, 0, 0);
    if render_gl(ps_device, "glCheckFramebufferStatus", 0x8d40, 0, 0, 0, 0, 0) != 0x8cd5 { return 0; }
    return target;
}
fn ps_sensor_capture(path) {
    // Export the two mounted sensors through a clean FBO. Observer panels,
    // colour components and labels never enter a model's input image.
    let target = ps_vision_target_create(); if !target { return 0; }
    let previous_target = ps_render_target; let previous_camera = ps_camera_mode; let mode = 1; let ok = 1;
    while mode <= 2 && ok {
        ps_render_target = target; ps_camera_mode = mode; ps_scene(640, 480, 0, 0);
        let name = ".front.png"; if mode == 2 { name = ".tcp.png"; }
        ok = ps_capture_at(h_cat(path, name), ps_total, ps_time); mode = mode + 1;
    }
    ps_render_target = previous_target; ps_camera_mode = previous_camera; ps_frame(); return ok;
}
fn ps_vision_ray(out, box) {
    let vectors = alloc(96); let forward = vectors; let right = vectors + 24; let up = vectors + 48; let ray = vectors + 72; let i = 0;
    while i < 3 { pb_vset(forward, i, pb_vget(ps_target, i) - pb_vget(ps_eye, i)); i = i + 1; }
    render_normalize(forward); render_cross(right, forward, ps_up); render_normalize(right); render_cross(up, right, forward);
    let u = f64_mul(f64_add(load64(box), load64(box + 16)), ps_number(1, 2));
    let v = f64_mul(f64_add(load64(box + 8), load64(box + 24)), ps_number(1, 2));
    let focal = ps_number(1732051 * 480, 2000000); let x = f64_div(f64_sub(u, f64_from_i64(320)), focal); let y = f64_div(f64_sub(v, f64_from_i64(240)), focal);
    i = 0; while i < 3 { pb_vset(ray, i, f64_sub(f64_add(ps_number(pb_vget(forward, i), 1000000), f64_mul(x, ps_number(pb_vget(right, i), 1000000))), f64_mul(y, ps_number(pb_vget(up, i), 1000000)))); i = i + 1; }
    let ok = f64_lt(load64(ray + 16), ps_number(-1, 100));
    if ok {
        // Known 70 mm ball resting on the known floor: centre height 35 mm.
        // This is a calibrated geometric estimate, not depth from YOLO.
        let distance = f64_div(f64_sub(ps_number(35, 1000), ps_number(load64(ps_eye + 16), 1000)), load64(ray + 16));
        ok = f64_gt(distance, ps_number(5, 100)) && f64_lt(distance, f64_from_i64(3));
        if ok { i = 0; while i < 3 { pb_vset(out, i, f64_add(ps_number(pb_vget(ps_eye, i), 1000), f64_mul(distance, pb_vget(ray, i)))); i = i + 1; } }
    }
    syscall(11, vectors, 96, 0, 0, 0, 0); return ok;
}
fn ps_vision_select(json, size, out) {
    let result = pj_parse(json, size); if pj_error || !result { return ps_vision_fail("detector returned invalid JSON"); }
    let schema = pj_string_field(result, "schema");
    if pj_error || !pl_equal(schema, "puppybot.detections.v1") { return ps_vision_fail("unsupported detector result schema"); }
    let coordinates = pj_string_field(result, "coordinates");
    if pj_error || !pl_equal(coordinates, "image-pixels") { return ps_vision_fail("detector boxes must use source image pixels"); }
    let frame = pj_need(result, "frame", 4); let width = pj_integer(frame, "width", 1, 8192); let height = pj_integer(frame, "height", 1, 8192);
    if pj_error || width != 640 || height != 480 { return ps_vision_fail("detector result does not match the camera dimensions"); }
    let detections = pj_need(result, "detections", 3); if pj_error { return ps_vision_fail("detector result has no detections array"); }
    let i = 0;
    while i < pj_count(detections) {
        let d = pj_index(detections, i); let label = pj_string_field(d, "label"); let score = pj_real(d, "confidence"); let class = pj_integer(d, "classId", 0, 255);
        if pj_error || !f64_is_finite(score) || f64_lt(score, 0) || f64_gt(score, PB_ONE) { return ps_vision_fail("invalid detector class or confidence"); }
        if class == 32 && pl_equal(label, "sports ball") && f64_ge(score, ps_number(25, 100)) && f64_gt(score, ps_vision_confidence) {
            let box = pj_need(d, "box", 3); if pj_error || pj_count(box) != 4 { return ps_vision_fail("invalid sports-ball bounding box"); }
            let k = 0;
            while k < 4 { let value = pj_real_node(pj_index(box, k)); let limit = 640; if k % 2 { limit = 480; }
                if pj_error || !f64_is_finite(value) || f64_lt(value, 0) || f64_gt(value, f64_from_i64(limit)) { return ps_vision_fail("sports-ball box lies outside its image"); }
                pb_vset(ps_vision_box, k, value); k = k + 1;
            }
            if f64_le(load64(ps_vision_box + 16), load64(ps_vision_box)) || f64_le(load64(ps_vision_box + 24), load64(ps_vision_box + 8)) { return ps_vision_fail("empty sports-ball bounding box"); }
            ps_vision_confidence = score;
        }
        i = i + 1;
    }
    if !ps_vision_confidence { return ps_vision_fail("YOLO found no sports ball at confidence >= 0.25; pickup stopped"); }
    if !ps_vision_ray(out, ps_vision_box) { return ps_vision_fail("detected ball ray does not intersect the floor-centre plane in range"); }
    pb_copy(ps_vision_estimate, out, 24); ps_vision_state = "detected"; ps_vision_reason = "native YOLO sports ball + calibrated floor-plane ray"; return 1;
}
fn ps_vision_box_preview() {
    let x1 = f64_to_i64_trunc(load64(ps_vision_box)); let y1 = f64_to_i64_trunc(load64(ps_vision_box + 8));
    let x2 = f64_to_i64_trunc(load64(ps_vision_box + 16)); let y2 = f64_to_i64_trunc(load64(ps_vision_box + 24));
    gui__put32(ps_tint, ps_float(1, 10)); gui__put32(ps_tint + 4, ps_float(1, 1)); gui__put32(ps_tint + 8, ps_float(2, 10)); gui__put32(ps_tint + 12, 0x3f800000);
    render_gl(ps_device, "glEnable", 0x0c11, 0, 0, 0, 0, 0); let i = 0;
    while i < 4 {
        let x = x1; let y = 480 - y2; let width = x2 - x1; let height = 2;
        if i == 1 { y = 480 - y1 - 2; }
        if i >= 2 { width = 2; height = y2 - y1; if i == 3 { x = x2 - 2; } }
        render_gl(ps_device, "glScissor", x, y, width, height, 0, 0); render_gl(ps_device, "glClearBufferfv", 0x1800, 0, ps_tint, 0, 0, 0); i = i + 1;
    }
    render_gl(ps_device, "glDisable", 0x0c11, 0, 0, 0, 0, 0); return 0;
}
fn ps_vision_observe(out) {
    ps_vision_confidence = 0; ps_vision_state = "detecting";
    if !ps_device { return ps_vision_fail("vision pickup requires the native camera renderer"); }
    if syscall(21, ps_vision_binary, 1, 0, 0, 0, 0) { return ps_vision_fail("native detector executable is missing"); }
    let made = syscall(83, ps_vision_root, 448, 0, 0, 0, 0); if made && made != -17 { return ps_vision_fail("cannot create vision output directory"); }
    ps_vision_directory = h_cat3(ps_vision_root, "/run-", h_cat3(h_int(syscall(39, 0, 0, 0, 0, 0, 0)), "-", h_int(ps_episode)));
    if syscall(83, ps_vision_directory, 448, 0, 0, 0, 0) { return ps_vision_fail("vision attempt directory must be new"); }
    ps_vision_image = h_cat(ps_vision_directory, "/camera.png"); ps_vision_result = h_cat(ps_vision_directory, "/detections.json"); ps_vision_preview = h_cat(ps_vision_directory, "/detected.png");
    if !ps_vision_sensor { ps_vision_sensor = ps_vision_target_create(); } if !ps_vision_sensor { return ps_vision_fail("cannot create the RGB camera target"); }
    let previous_camera = ps_camera_mode; let previous_target = ps_render_target;
    ps_camera_mode = 1; ps_render_target = ps_vision_sensor; ps_frame(); ps_vision_frame = ps_total;
    let ok = ps_capture(ps_vision_image);
    if ok {
        let args = h_args(ps_vision_binary, "--model", ps_vision_manifest, "--image", ps_vision_image, "--backend");
        h_add(args, ps_vision_backend); h_add(args, "--kernel"); h_add(args, ps_vision_kernel); h_add(args, "--output"); h_add(args, ps_vision_result);
        let p = h_spawn(args, "", 0); let deadline = pl_now() + 15000;
        while (load64(p + 8) == -999 || load64(p + 40) >= 0 || load64(p + 48) >= 0) && pl_now() < deadline { h_pump(p, 1); }
        if load64(p + 8) == -999 { h_stop(p); ok = ps_vision_fail("native detector timed out after 15 seconds"); }
        else {
            let log = h_err(p); pl_atomic_file(h_cat(ps_vision_directory, "/detector.log"), log, pl_size(log));
            if h_status(p) { pl_print(2, log); ok = ps_vision_fail("native detector failed; see detector.log in the vision attempt directory"); }
            else { ok = ps_vision_select(h_out(p), h_size(load64(p + 16)), out); }
            h_close(load64(p + 32)); store64(p + 32, -1);
        }
        if ok { ps_vision_box_preview(); if !ps_capture(ps_vision_preview) { ok = ps_vision_fail("cannot save the detection preview"); } }
    } else { ps_vision_fail("cannot save camera RGB and calibration"); }
    ps_camera_mode = previous_camera; ps_render_target = previous_target; ps_frame(); return ok;
}
