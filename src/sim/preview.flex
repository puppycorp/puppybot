// Display-only live TCP stream. Own RGB buffers, components and FBO;
// never call the policy samplers or modify their observations/box freshness.
import "brick-vision.flex";

global ps_previews = -1;
global ps_preview_contexts = 0;
global ps_preview_rgb = 0;
global ps_preview_mask = 0;
global ps_preview_queue = 0;
global ps_preview_args = 0;
global ps_preview_text = 0;
global ps_preview_builder = 0;
global ps_preview_mesh = 0;
global ps_preview_next = 0;
global ps_preview_drive_mode = -1;

fn ps_preview_init() {
    if ps_preview_contexts { return 1; }
    ps_preview_contexts = alloc(160); ps_preview_rgb = alloc(640 * 480 * 3); ps_preview_mask = alloc(640 * 480); ps_preview_queue = alloc(640 * 480 * 8);
    ps_preview_args = alloc(88); ps_preview_text = alloc(128); ps_preview_builder = alloc(32); ps_preview_mesh = ps_text_upload(0, "RGB CANDIDATES");
    let c = ps_preview_contexts; store64(c, ps_vision_target_create()); if !load64(c) { return 0; }
    store64(c + 24, alloc(32 * 64)); store64(c + 8, -1); store64(c + 40, ps_text_upload(0, "TCP - INSPECTION"));
    return 1;
}
fn ps_preview_enqueue(pixel, colour, tail) {
    if load8(ps_preview_mask + pixel) == colour { store8(ps_preview_mask + pixel, 0); store64(ps_preview_queue + tail * 8, pixel); return tail + 1; } return tail;
}
fn ps_preview_component(context, start, colour) {
    let head = 0; let tail = ps_preview_enqueue(start, colour, 0); let x1 = 640; let y1 = 480; let x2 = 0; let y2 = 0;
    while head < tail {
        let pixel = load64(ps_preview_queue + head * 8); let x = pixel % 640; let y = pixel / 640;
        x1 = pb_min(x1, x); y1 = pb_min(y1, y); x2 = pb_max(x2, x); y2 = pb_max(y2, y);
        if x { tail = ps_preview_enqueue(pixel - 1, colour, tail); } if x < 639 { tail = ps_preview_enqueue(pixel + 1, colour, tail); }
        if y { tail = ps_preview_enqueue(pixel - 640, colour, tail); } if y < 479 { tail = ps_preview_enqueue(pixel + 640, colour, tail); } head = head + 1;
    }
    let width = x2 - x1 + 1; let height = y2 - y1 + 1; let minimum = 18; if colour == 7 { minimum = 4; }
    if tail < minimum || tail > 102400 || width < 2 || height < 2 || width > height * 5 || height > width * 5 || tail * 5 < width * height || load64(context + 32) >= 32 { return 0; }
    let r = load64(context + 24) + load64(context + 32) * 64;
    store64(r, x1); store64(r + 8, y1); store64(r + 16, x2 + 1); store64(r + 24, y2 + 1); store64(r + 32, ps_number(tail, width * height)); store64(r + 40, colour);
    store64(context + 32, load64(context + 32) + 1); return 1;
}
fn ps_preview_detect(context) {
    store64(context + 32, 0); let i = 0;
    while i < 640 * 480 {
        let p = ps_preview_rgb + i * 3; let r = load8(p); let g = load8(p + 1); let b = load8(p + 2); let colour = ps_brick_colour(p);
        if r > 70 && b > 60 && r > g * 4 && b > g * 4 && b * 10 > r * 7 { colour = 7; }
        store8(ps_preview_mask + i, colour); i = i + 1;
    }
    i = 0; while i < 640 * 480 { let colour = load8(ps_preview_mask + i); if colour { ps_preview_component(context, i, colour); } i = i + 1; } return 1;
}
fn ps_preview_mark(context) {
    render_gl(ps_device, "glEnable", 0x0c11, 0, 0, 0, 0, 0); let i = 0;
    while i < load64(context + 32) {
        let r = load64(context + 24) + i * 64; let x = load64(r); let y = load64(r + 8); let w = load64(r + 16) - x; let h = load64(r + 24) - y; let red = 20; if load64(r + 40) == 7 { red = 100; }
        ps_panel_clear(x, y, w, 3, red, 100, 20); ps_panel_clear(x, y + h - 3, w, 3, red, 100, 20); ps_panel_clear(x, y, 3, h, red, 100, 20); ps_panel_clear(x + w - 3, y, 3, h, red, 100, 20); i = i + 1;
    }
    render_gl(ps_device, "glDisable", 0x0c11, 0, 0, 0, 0, 0); i = 0;
    while i < load64(context + 32) {
        let r = load64(context + 24) + i * 64; pl_builder(ps_preview_builder, ps_preview_text, 128);
        if load64(r + 40) == 7 { pl_text(ps_preview_builder, "RIM "); } else { pl_text(ps_preview_builder, "FILL "); }
        pl_int(ps_preview_builder, f64_to_i64_nearest(f64_mul(load64(r + 32), f64_from_i64(100)))); pl_char(ps_preview_builder, 37);
        ps_preview_mesh = ps_text_upload(ps_preview_mesh, ps_preview_text); ps_text_draw(ps_preview_mesh, 640, 480, pb_clamp(load64(r), 0, 520), pb_clamp(480 - load64(r + 24) - 16, 0, 464)); i = i + 1;
    }
    return 1;
}
fn ps_preview_sample(context) {
    let target = ps_render_target; let camera = ps_camera_mode; ps_render_target = load64(context); ps_camera_mode = 2; ps_scene(640, 480, 0, 0);
    pb_copy(context + 64, ps_eye, 24); pb_copy(context + 88, ps_target, 24); pb_copy(context + 112, ps_up, 24);
    pb_zero(ps_preview_args, 88); store64(ps_preview_args + 16, 640); store64(ps_preview_args + 24, 480); store64(ps_preview_args + 32, 0x1907); store64(ps_preview_args + 40, 0x1401); store64(ps_preview_args + 48, ps_preview_rgb);
    render_gl(ps_device, "glPixelStorei", 0x0d05, 1, 0, 0, 0, 0); ffi_call_words(gui_gl_cached_proc(load64(ps_device), "glReadPixels"), ps_preview_args);
    ps_preview_detect(context); ps_preview_mark(context); store64(context + 8, ps_total); store64(context + 16, ps_time);
    ps_render_target = target; ps_camera_mode = camera; return 1;
}
fn ps_preview_poll() {
    if !ps_previews || ps_render_target { return 0; } let now = pl_now(); if now < ps_preview_next { return 0; }
    ps_require(ps_preview_init());
    if ps_preview_drive_mode != ps_camera_drive_mode {
        let title = "TCP - INSPECTION"; if ps_camera_drive_mode { title = "TCP - DRIVING"; }
        store64(ps_preview_contexts + 40, ps_text_upload(load64(ps_preview_contexts + 40), title)); ps_preview_drive_mode = ps_camera_drive_mode;
    }
    ps_preview_sample(ps_preview_contexts); ps_preview_next = now + 100; return 1;
}
fn ps_preview_context() {
    if ps_stock_enabled && ps_live_front >= 0 && ps_live_front_episode == ps_episode { return ps_stock_context; }
    return ps_preview_contexts;
}
fn ps_preview_present(context, x, y, width, height) {
    render_gl(ps_device, "glEnable", 0x0c11, 0, 0, 0, 0, 0); ps_panel_clear(x - 3, y - 31, width + 6, height + 34, 18, 60, 65); ps_panel_clear(x, y - 28, width, 28, 4, 9, 12);
    render_gl(ps_device, "glDisable", 0x0c11, 0, 0, 0, 0, 0);
    render_gl(ps_device, "glBindFramebuffer", 0x8ca8, load64(load64(context) + 16), 0, 0, 0, 0); render_gl(ps_device, "glBindFramebuffer", 0x8ca9, 0, 0, 0, 0, 0);
    pb_zero(ps_preview_args, 88); store64(ps_preview_args + 16, 640); store64(ps_preview_args + 24, 480); store64(ps_preview_args + 32, x); store64(ps_preview_args + 40, y); store64(ps_preview_args + 48, x + width); store64(ps_preview_args + 56, y + height); store64(ps_preview_args + 64, 0x4000); store64(ps_preview_args + 72, 0x2601);
    ffi_call_words(gui_gl_cached_proc(load64(ps_device), "glBlitFramebuffer"), ps_preview_args);
    render_gl(ps_device, "glBindFramebuffer", 0x8d40, 0, 0, 0, 0, 0); render_gl(ps_device, "glViewport", x, y - 28, width, 28, 0, 0); ps_text_draw(load64(context + 40), width, 28, 10, 7); return 0;
}
fn ps_preview_draw(w, h) {
    if !ps_preview_contexts { return 0; } let width = pb_min(w / 3, 400); let height = width * 3 / 4;
    if height + 60 > h { height = pb_max(30, h - 60); width = height * 4 / 3; }
    let x = w - width - 20; let y = h - height - 20; ps_preview_present(ps_preview_context(), x, y, width, height);
    render_gl(ps_device, "glViewport", 0, 0, w, h, 0, 0); ps_camera_update(w, h); return 0;
}
fn ps_preview_state(b) {
    pl_text(b, "{\"schema\":\"puppybot.sim.views.v1\",\"enabled\":"); pj_bool_text(b, ps_previews); pl_text(b, ",\"updateIntervalMs\":100,\"detector\":");
    if ps_stock_enabled { pj_text(b, "per-view"); pl_text(b, ",\"scoreMeaning\":\"per-view\""); } else { pj_text(b, "rgb-components-2d"); pl_text(b, ",\"scoreMeaning\":\"component-fill-ratio\""); }
    pl_text(b, ",\"views\":[");
    if ps_preview_contexts {
        let c = ps_preview_context(); pl_text(b, "{\"camera\":\"tcp\",\"pose\":"); if ps_camera_drive_mode { pj_text(b, "driving"); } else { pj_text(b, "inspection"); }
        pl_text(b, ",\"detector\":"); if ps_stock_enabled { pj_text(b, "stock-yolo"); } else { pj_text(b, "rgb-components-2d"); }
        pl_text(b, ",\"scoreMeaning\":"); if ps_stock_enabled { pj_text(b, "model-confidence"); } else { pj_text(b, "component-fill-ratio"); }
        pl_text(b, ",\"frameId\":"); pl_int(b, load64(c + 8)); pl_text(b, ",\"capturedMs\":"); pl_int(b, load64(c + 16)); pl_text(b, ",\"detections\":"); pl_int(b, load64(c + 32)); pl_char(b, 125);
    }
    return pl_text(b, "]}");
}
fn ps_preview_capture(path) {
    if !ps_preview_contexts { return 1; } let camera = ps_camera_mode; let target = ps_render_target; let ok = 1;
    let c = ps_preview_context(); ps_render_target = load64(c); ps_camera_mode = 2;
    render_gl(ps_device, "glBindFramebuffer", 0x8d40, load64(ps_render_target + 16), 0, 0, 0, 0);
    pb_copy(ps_eye, c + 64, 24); pb_copy(ps_target, c + 88, 24); pb_copy(ps_up, c + 112, 24);
    ok = ps_capture_at(h_cat(path, ".tcp.png"), load64(c + 8), load64(c + 16));
    ps_camera_mode = camera; ps_render_target = target; render_gl(ps_device, "glBindFramebuffer", 0x8d40, 0, 0, 0, 0, 0);
    ps_camera_update(gui_pixel_width(load64(ps_device)), gui_pixel_height(load64(ps_device)));
    let data = alloc(16384); let builder = alloc(32); pl_builder(builder, data, 16384); ps_preview_state(builder);
    if ok { ok = !load64(builder + 24) && !pl_atomic_file(h_cat(path, ".views.json"), data, load64(builder + 8)); }
    syscall(11, data, 16384, 0, 0, 0, 0); syscall(11, builder, 32, 0, 0, 0, 0); return ok;
}
fn ps_preview_close() {
    if ps_preview_contexts { render_mesh_close(load64(ps_preview_contexts + 40)); render_mesh_close(ps_preview_mesh); } return 0;
}
