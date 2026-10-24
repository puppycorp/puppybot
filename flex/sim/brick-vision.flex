// A simple RGB detector for the coloured simulation bricks. This is not YOLO.
// Inputs are a clean camera framebuffer, calibration and a known 24 mm brick
// height. No physics bodies, object poses, object IDs or instance colours are
// read here. Connected components and calibrated rays supply every target.
import "vision.flex";
import "localization.flex";

global ps_brick_sensor = 0;
global ps_brick_rgb = 0;
global ps_brick_mask = 0;
global ps_brick_queue = 0;
global ps_brick_records = 0;
global ps_brick_count = 0;
global ps_brick_pose = 0;
global ps_brick_scratch = 0;
global ps_brick_frame = 0;
global ps_brick_time = 0;
global ps_brick_samples = 0;
global ps_brick_chosen = -1;
global ps_brick_text = 0;
global ps_brick_caption = 0;
global ps_brick_output = 0;
global ps_rgb_image = 0;

fn ps_brick_reset() {
    ps_brick_count = 0; ps_brick_samples = 0; ps_brick_frame = 0; ps_brick_time = 0; ps_brick_chosen = -1; return 0;
}
fn ps_brick_init() {
    if ps_brick_rgb { return 1; } if !ps_device { return 0; }
    ps_brick_sensor = ps_vision_target_create(); if !ps_brick_sensor { return 0; }
    ps_brick_rgb = alloc(640 * 480 * 3); ps_brick_mask = alloc(640 * 480); ps_brick_queue = alloc(640 * 480 * 8);
    ps_brick_records = alloc(16 * 128); ps_brick_pose = alloc(96); ps_brick_scratch = alloc(128);
    ps_brick_text = ps_text_upload(0, "RGB BRICK SEARCH"); ps_brick_caption = ps_text_upload(0, "RGB TCP - COLOUR / SHAPE"); return 1;
}
fn ps_brick_colour(p) {
    let r = load8(p); let g = load8(p + 1); let b = load8(p + 2); let peak = pb_max(r, pb_max(g, b));
    if peak < 45 { return 0; }
    if r > g * 2 && r > b * 2 { return 1; }
    if b * 10 > r * 18 && b * 10 > g * 17 { return 2; }
    if r > b * 3 && g > b * 3 && g * 10 > r * 7 { return 3; }
    if g * 10 > r * 18 && g * 10 > b * 16 { return 4; }
    if b > r && r * 10 > g * 18 && b * 10 > g * 22 { return 5; }
    if r * 10 > g * 18 && r > b * 4 && g * 10 > r * 4 { return 6; }
    return 0;
}
fn ps_brick_calibrate() {
    if ps_local_mode { return ps_local_camera(ps_brick_pose); }
    let forward = ps_brick_scratch; let right = forward + 24; let up = right + 24; let i = 0;
    while i < 3 { store64(forward + i * 8, load64(ps_target + i * 8) - load64(ps_eye + i * 8)); i = i + 1; }
    render_normalize(forward); render_cross(right, forward, ps_up); render_normalize(right); render_cross(up, right, forward); i = 0;
    while i < 3 {
        store64(ps_brick_pose + i * 8, ps_number(load64(ps_eye + i * 8), 1000));
        store64(ps_brick_pose + 24 + i * 8, ps_number(load64(forward + i * 8), 1000000));
        store64(ps_brick_pose + 48 + i * 8, ps_number(load64(right + i * 8), 1000000));
        store64(ps_brick_pose + 72 + i * 8, ps_number(-load64(up + i * 8), 1000000)); i = i + 1;
    }
    return 0;
}
fn ps_rgb_ray(out, u, v, plane) {
    let focal = ps_number(1732051 * 480, 2000000); let x = f64_div(f64_sub(u, f64_from_i64(320)), focal); let y = f64_div(f64_sub(v, f64_from_i64(240)), focal); let i = 0;
    while i < 3 {
        store64(out + i * 8, f64_add(load64(ps_brick_pose + 24 + i * 8), f64_add(f64_mul(x, load64(ps_brick_pose + 48 + i * 8)), f64_mul(y, load64(ps_brick_pose + 72 + i * 8))))); i = i + 1;
    }
    if f64_ge(load64(out + 16), ps_number(-1, 100)) { return 0; }
    let distance = f64_div(f64_sub(plane, load64(ps_brick_pose + 16)), load64(out + 16));
    if f64_le(distance, 0) || f64_gt(distance, f64_from_i64(2)) { return 0; }
    i = 0; while i < 3 { store64(out + i * 8, f64_add(load64(ps_brick_pose + i * 8), f64_mul(distance, load64(out + i * 8)))); i = i + 1; }
    return 1;
}
fn ps_brick_ray(out, u, v) {
    if !ps_rgb_ray(out, u, v, ps_number(24, 1000)) { return 0; } store64(out + 16, ps_number(12, 1000)); return 1;
}
fn ps_brick_enqueue(pixel, colour, tail) {
    if load8(ps_brick_mask + pixel) == colour { store8(ps_brick_mask + pixel, 0); store64(ps_brick_queue + tail * 8, pixel); return tail + 1; } return tail;
}
fn ps_brick_component(start, colour) {
    let head = 0; let tail = ps_brick_enqueue(start, colour, 0); let x1 = 640; let y1 = 480; let x2 = 0; let y2 = 0; let peak = 0;
    while head < tail {
        let pixel = load64(ps_brick_queue + head * 8); let x = pixel % 640; let y = pixel / 640;
        x1 = pb_min(x1, x); y1 = pb_min(y1, y); x2 = pb_max(x2, x); y2 = pb_max(y2, y);
        let p = ps_brick_rgb + pixel * 3; peak = pb_max(peak, pb_max(load8(p), pb_max(load8(p + 1), load8(p + 2))));
        if x { tail = ps_brick_enqueue(pixel - 1, colour, tail); } if x < 639 { tail = ps_brick_enqueue(pixel + 1, colour, tail); }
        if y { tail = ps_brick_enqueue(pixel - 640, colour, tail); } if y < 479 { tail = ps_brick_enqueue(pixel + 640, colour, tail); } head = head + 1;
    }
    let width = x2 - x1 + 1; let height = y2 - y1 + 1;
    if tail < 18 || width < 4 || height < 4 || width > height * 5 || height > width * 5 || tail * 5 < width * height || x1 == 0 || x2 == 639 || y1 == 0 || y2 == 479 { return 0; }
    // Bright top faces receive more light than vertical sides. Their centroid
    // on the known top plane avoids the usual side-face bounding-box bias.
    let sumx = 0; let sumy = 0; let count = 0; head = 0;
    while head < tail {
        let pixel = load64(ps_brick_queue + head * 8); let p = ps_brick_rgb + pixel * 3; let value = pb_max(load8(p), pb_max(load8(p + 1), load8(p + 2)));
        if value * 100 >= peak * 88 { sumx = sumx + pixel % 640; sumy = sumy + pixel / 640; count = count + 1; } head = head + 1;
    }
    if count < 8 || ps_brick_count >= 16 { return 0; }
    let r = ps_brick_records + ps_brick_count * 128; pb_zero(r, 128); let u = f64_add(ps_number(sumx, count), ps_number(1, 2)); let v = f64_add(ps_number(sumy, count), ps_number(1, 2));
    if !ps_brick_ray(r + 32, u, v) { return 0; }
    // Restrict collection to the positive-Y floor lane. The known return dock
    // is on the other side, so deposited pieces are not collected again.
    if ps_house_enabled() { if !ps_house_filter(load64(r + 32), load64(r + 40)) { return 0; } }
    else if f64_lt(load64(r + 40), ps_number(5, 1000)) || f64_gt(load64(r + 40), ps_number(30, 100)) { return 0; }
    let scale = f64_div(f64_sub(load64(ps_brick_pose + 16), ps_number(24, 1000)), ps_number(1732051 * 480, 2000000));
    let span = f64_mul(f64_from_i64(pb_max(width, height)), scale);
    if f64_lt(span, ps_number(8, 1000)) || f64_gt(span, ps_number(9, 100)) { return 0; }
    store64(r, x1); store64(r + 8, y1); store64(r + 16, x2 + 1); store64(r + 24, y2 + 1);
    // A geometric fill score, not a learned probability.
    store64(r + 56, ps_number(tail, width * height)); store64(r + 64, colour); store64(r + 72, u); store64(r + 80, v); store64(r + 88, tail);
    ps_brick_count = ps_brick_count + 1; return 1;
}
fn ps_brick_detect() {
    ps_brick_count = 0; ps_brick_chosen = -1; let i = 0;
    while i < 640 * 480 { store8(ps_brick_mask + i, ps_brick_colour(ps_brick_rgb + i * 3)); i = i + 1; }
    i = 0; while i < 640 * 480 { let colour = load8(ps_brick_mask + i); if colour { ps_brick_component(i, colour); } i = i + 1; } return 1;
}
fn ps_rgb_sample() {
    if !ps_brick_init() { return 0; } let previous_target = ps_render_target; let previous_mode = ps_camera_mode;
    ps_render_target = ps_brick_sensor; ps_camera_mode = 2; ps_scene(640, 480, 0, 0); ps_brick_calibrate();
    let ok = 1;
    if ps_brick_output {
        let made = syscall(83, ps_brick_output, 493, 0, 0, 0, 0); if made && made != -17 { ok = 0; }
        ps_rgb_image = h_cat3("frame-", h_int(ps_total), ".png");
        if ok { ok = ps_capture(h_cat3(ps_brick_output, "/", ps_rgb_image)); }
    }
    if !ok { ps_render_target = previous_target; ps_camera_mode = previous_mode; return 0; }
    let args = ps_brick_scratch; pb_zero(args, 88); store64(args + 16, 640); store64(args + 24, 480); store64(args + 32, 0x1907); store64(args + 40, 0x1401); store64(args + 48, ps_brick_rgb);
    render_gl(ps_device, "glPixelStorei", 0x0d05, 1, 0, 0, 0, 0); ffi_call_words(gui_gl_cached_proc(load64(ps_device), "glReadPixels"), args);
    // Work in normal top-left image coordinates, independently of OpenGL.
    let row = alloc(640 * 3); let y = 0;
    while y < 240 { let a = ps_brick_rgb + y * 640 * 3; let b = ps_brick_rgb + (479 - y) * 640 * 3; pb_copy(row, a, 640 * 3); pb_copy(a, b, 640 * 3); pb_copy(b, row, 640 * 3); y = y + 1; }
    syscall(11, row, 640 * 3, 0, 0, 0, 0); ps_brick_frame = ps_total; ps_brick_time = ps_time; ps_brick_samples = ps_brick_samples + 1; ps_brick_count = 0; ps_brick_chosen = -1;
    ps_render_target = previous_target; ps_camera_mode = previous_mode; return 1;
}
fn ps_brick_sample() {
    if !ps_rgb_sample() { return 0; } ps_brick_detect();
    ps_brick_caption = ps_text_upload(ps_brick_caption, "RGB TCP - LAST OBSERVATION");
    return 1;
}
fn ps_brick_mark() {
    if !ps_brick_sensor { return 0; }
    render_gl(ps_device, "glBindFramebuffer", 0x8d40, load64(ps_brick_sensor + 16), 0, 0, 0, 0); render_gl(ps_device, "glViewport", 0, 0, 640, 480, 0, 0);
    render_gl(ps_device, "glEnable", 0x0c11, 0, 0, 0, 0, 0); let i = 0;
    while i < ps_brick_count {
        let r = ps_brick_records + i * 128; let x = load64(r); let y = 480 - load64(r + 24); let width = load64(r + 16) - x; let height = load64(r + 24) - load64(r + 8); let k = 0;
        while k < 4 {
            let px = x; let py = y; let w = width; let h = 2;
            if k == 1 { py = y + height - 2; } if k >= 2 { w = 2; h = height; if k == 3 { px = x + width - 2; } }
            let red = 20; if i == ps_brick_chosen { red = 100; } ps_panel_clear(px, py, w, h, red, 100, 30); k = k + 1;
        }
        i = i + 1;
    }
    render_gl(ps_device, "glDisable", 0x0c11, 0, 0, 0, 0, 0);
    let text = "NO BRICK - SEARCHING"; if ps_brick_count { text = "BRICK - RGB COLOUR / SHAPE"; }
    ps_brick_text = ps_text_upload(ps_brick_text, text); ps_text_draw(ps_brick_text, 640, 480, 12, 12); return 1;
}
fn ps_brick_present(width, height, x, y) {
    if !ps_brick_sensor || !ps_brick_samples { return 0; }
    render_gl(ps_device, "glBindFramebuffer", 0x8ca8, load64(ps_brick_sensor + 16), 0, 0, 0, 0); render_gl(ps_device, "glBindFramebuffer", 0x8ca9, 0, 0, 0, 0, 0);
    let args = ps_brick_scratch; pb_zero(args, 88); store64(args + 16, 640); store64(args + 24, 480); store64(args + 32, x); store64(args + 40, y); store64(args + 48, x + width); store64(args + 56, y + height); store64(args + 64, 0x4000); store64(args + 72, 0x2601);
    ffi_call_words(gui_gl_cached_proc(load64(ps_device), "glBlitFramebuffer"), args); render_gl(ps_device, "glBindFramebuffer", 0x8d40, 0, 0, 0, 0, 0); return 1;
}
fn ps_brick_metadata(path) {
    if !ps_brick_samples { return 1; } let text = alloc(4096); let b = alloc(32); pl_builder(b, text, 4096);
    pl_text(b, "{\"schema\":\"puppybot.camera.v1\",\"view\":"); pj_text(b, "tcp");
    pl_text(b, ",\"width\":640,\"height\":480,\"frameId\":"); pl_int(b, ps_brick_frame); pl_text(b, ",\"capturedMs\":"); pl_int(b, ps_brick_time);
    pl_text(b, ",\"intrinsics\":{\"fx\":"); pl_float(b, ps_number(1732051 * 480, 2000000)); pl_text(b, ",\"fy\":"); pl_float(b, ps_number(1732051 * 480, 2000000)); pl_text(b, ",\"cx\":320,\"cy\":240}");
    let names = alloc(32); store64(names, "eyeM"); store64(names + 8, "forward"); store64(names + 16, "right"); store64(names + 24, "down"); let i = 0;
    while i < 4 { pl_char(b, 44); pj_text(b, load64(names + i * 8)); pl_text(b, ":["); let k = 0; while k < 3 { if k { pl_char(b, 44); } pl_float(b, load64(ps_brick_pose + (i * 3 + k) * 8)); k = k + 1; } pl_char(b, 93); i = i + 1; }
    pl_text(b, "}\n"); let ok = !load64(b + 24) && !pl_atomic_file(h_cat(path, ".sensor.camera.json"), text, load64(b + 8));
    syscall(11, names, 32, 0, 0, 0, 0); syscall(11, text, 4096, 0, 0, 0, 0); syscall(11, b, 32, 0, 0, 0, 0); return ok;
}
fn ps_brick_observation(b) {
    pl_text(b, ",\"perception\":{\"detector\":\"rgb-components-v1\",\"targetSource\":\"camera-rgb\",\"scoreMeaning\":\"component-fill-ratio\",\"samples\":"); pl_int(b, ps_brick_samples);
    pl_text(b, ",\"frameId\":"); pl_int(b, ps_brick_frame); pl_text(b, ",\"view\":"); pj_text(b, "tcp");
    pl_text(b, ",\"image\":"); if ps_brick_output && ps_rgb_image { pj_text(b, ps_rgb_image); } else { pl_text(b, "null"); }
    pl_text(b, ",\"chosen\":"); pl_int(b, ps_brick_chosen); pl_text(b, ",\"calibration\":["); let i = 0;
    while i < 12 { if i { pl_char(b, 44); } let value = 0; if ps_brick_pose { value = load64(ps_brick_pose + i * 8); } pl_float(b, value); i = i + 1; }
    pl_text(b, "],\"detections\":["); i = 0;
    while i < ps_brick_count {
        if i { pl_char(b, 44); } let r = ps_brick_records + i * 128; pl_text(b, "{\"box\":["); let k = 0;
        while k < 4 { if k { pl_char(b, 44); } pl_int(b, load64(r + k * 8)); k = k + 1; }
        pl_text(b, "],\"targetM\":["); k = 0; while k < 3 { if k { pl_char(b, 44); } pl_float(b, load64(r + 32 + k * 8)); k = k + 1; }
        pl_text(b, "],\"pixel\":["); pl_float(b, load64(r + 72)); pl_char(b, 44); pl_float(b, load64(r + 80)); pl_text(b, "],\"fill\":"); pl_float(b, load64(r + 56)); pl_char(b, 125); i = i + 1;
    }
    return pl_text(b, "]}");
}
