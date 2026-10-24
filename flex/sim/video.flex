// Stream the composited observer to FFmpeg; sensor inputs remain untouched.
import "render.flex";

global ps_video_fps = 25;
global ps_video_path = 0;
global ps_video_pid = 0;
global ps_video_fd = -1;
global ps_video_frames = 0;
global ps_video_failed = 0;
global ps_video_width = 0;
global ps_video_height = 0;
global ps_video_target = 0;
global ps_video_color = 0;
global ps_video_pixels = 0;
global ps_video_args = 0;
global ps_video_status = 0;

fn ps_video_error(message) {
    ps_video_failed = 1; pl_print(2, "Video recording: "); pl_print(2, message); pl_print(2, "\n"); return 0;
}
fn ps_video_reap() {
    if !ps_video_pid { return 1; }
    let result = syscall(61, ps_video_pid, ps_video_status, 1, 0, 0, 0);
    if result == ps_video_pid { ps_video_pid = 0; return 1; }
    return 0;
}
fn ps_video_close() {
    if ps_video_fd >= 0 { syscall(3, ps_video_fd, 0, 0, 0, 0, 0); ps_video_fd = -1; }
    let deadline = pl_now() + 30000;
    while ps_video_pid && !ps_video_reap() && pl_now() < deadline { syscall(7, 0, 0, 1, 0, 0, 0); }
    if ps_video_pid {
        syscall(62, ps_video_pid, 9, 0, 0, 0, 0); syscall(61, ps_video_pid, ps_video_status, 0, 0, 0, 0); ps_video_pid = 0;
        ps_video_error("FFmpeg did not finish within 30 seconds");
    }
    if ps_video_status && load64(ps_video_status) { ps_video_error("FFmpeg failed; see its diagnostics above"); }
    if ps_video_pixels { syscall(11, ps_video_pixels, ps_video_width * ps_video_height * 3, 0, 0, 0, 0); ps_video_pixels = 0; }
    if ps_video_target { render_target_close(ps_video_target); ps_video_target = 0; }
    if ps_video_color { render_delete(ps_device, 4, ps_video_color); ps_video_color = 0; }
    if ps_video_path && !ps_video_failed {
        pl_print(2, "Video saved: "); pl_print(2, ps_video_path); pl_print(2, " ("); pl_print(2, h_int(ps_video_frames)); pl_print(2, " frames)\n");
    }
    return !ps_video_failed;
}
fn ps_video_target_create() {
    ps_video_target = render_depth_target(ps_device, ps_video_width, ps_video_height); if !ps_video_target { return 0; }
    let p = load64(ps_device + 24); render_gl(ps_device, "glGenTextures", 1, p, 0, 0, 0, 0); ps_video_color = render_track(ps_device, 4, gui__u32(p)); if !ps_video_color { return 0; }
    render_gl(ps_device, "glBindTexture", 0x0de1, ps_video_color, 0, 0, 0, 0); pb_zero(ps_video_args, 88);
    store64(ps_video_args, 0x0de1); store64(ps_video_args + 16, 0x8051); store64(ps_video_args + 24, ps_video_width); store64(ps_video_args + 32, ps_video_height);
    store64(ps_video_args + 48, 0x1907); store64(ps_video_args + 56, 0x1401);
    ffi_call_words(gui_gl_cached_proc(load64(ps_device), "glTexImage2D"), ps_video_args);
    render_gl(ps_device, "glTexParameteri", 0x0de1, 0x2801, 0x2600, 0, 0, 0); render_gl(ps_device, "glTexParameteri", 0x0de1, 0x2800, 0x2600, 0, 0, 0);
    render_gl(ps_device, "glBindFramebuffer", 0x8d40, load64(ps_video_target + 16), 0, 0, 0, 0);
    render_gl(ps_device, "glFramebufferTexture2D", 0x8d40, 0x8ce0, 0x0de1, ps_video_color, 0, 0);
    render_gl(ps_device, "glDrawBuffer", 0x8ce0, 0, 0, 0, 0, 0); render_gl(ps_device, "glReadBuffer", 0x8ce0, 0, 0, 0, 0, 0);
    let ok = render_gl(ps_device, "glCheckFramebufferStatus", 0x8d40, 0, 0, 0, 0, 0) == 0x8cd5;
    render_gl(ps_device, "glBindFramebuffer", 0x8d40, 0, 0, 0, 0, 0); return ok;
}
fn ps_video_open(path) {
    let size = pl_size(path); if size < 5 || !pl_equal(path + size - 4, ".mp4") { return ps_video_error("--video requires an .mp4 filename"); }
    let encoder = h_executable("ffmpeg"); if syscall(21, encoder, 1, 0, 0, 0, 0) { return ps_video_error("install FFmpeg with libx264 support and put ffmpeg on PATH"); }
    let output = syscall(2, path, 0x800c1, 420, 0, 0, 0); if output < 0 { return ps_video_error("output path must be new and its parent directory must exist"); }
    ps_video_width = (gui_pixel_width(load64(ps_device)) + 1) & -2; ps_video_height = (gui_pixel_height(load64(ps_device)) + 1) & -2;
    ps_video_args = alloc(88); ps_video_status = alloc(8); store64(ps_video_status, 0);
    if !ps_video_target_create() { syscall(3, output, 0, 0, 0, 0, 0); return ps_video_error("cannot allocate the recording framebuffer"); }
    let dimensions = h_cat3(h_int(ps_video_width), "x", h_int(ps_video_height));
    let args = h_args(encoder, "-hide_banner", "-loglevel", "error", "-nostdin", "-f");
    h_add(args, "rawvideo"); h_add(args, "-pixel_format"); h_add(args, "rgb24"); h_add(args, "-video_size"); h_add(args, dimensions);
    h_add(args, "-framerate"); h_add(args, h_int(ps_video_fps)); h_add(args, "-i"); h_add(args, "pipe:0"); h_add(args, "-an"); h_add(args, "-vf"); h_add(args, "vflip");
    h_add(args, "-c:v"); h_add(args, "libx264"); h_add(args, "-preset"); h_add(args, "veryfast"); h_add(args, "-crf"); h_add(args, "20"); h_add(args, "-pix_fmt"); h_add(args, "yuv420p");
    h_add(args, "-g"); h_add(args, h_int(ps_video_fps * 2)); h_add(args, "-movflags"); h_add(args, "+frag_keyframe+empty_moov+default_base_moof"); h_add(args, "-f"); h_add(args, "mp4"); h_add(args, "pipe:1"); store64(args + 8 + h_count(args) * 8, 0);
    let pair = alloc(8); if syscall(293, pair, 0x80000, 0, 0, 0, 0) { syscall(3, output, 0, 0, 0, 0, 0); return ps_video_error("cannot create encoder pipe"); }
    let reader = pb_u32(pair); let writer = pb_u32(pair + 4); let owner = syscall(39, 0, 0, 0, 0, 0, 0); let pid = syscall(57, 0, 0, 0, 0, 0, 0);
    if !pid {
        syscall(157, 1, 9, 0, 0, 0, 0); if syscall(110, 0, 0, 0, 0, 0, 0) != owner { syscall(60, 125, 0, 0, 0, 0, 0); }
        store64(pair, 0); syscall(14, 2, pair, 0, 8, 0, 0); h_restore_sigpipe();
        syscall(33, reader, 0, 0, 0, 0, 0); syscall(33, output, 1, 0, 0, 0, 0); syscall(436, 3, 0xffffffff, 0, 0, 0, 0);
        syscall(59, encoder, args + 8, h_env, 0, 0, 0); syscall(60, 127, 0, 0, 0, 0, 0);
    }
    syscall(3, reader, 0, 0, 0, 0, 0); syscall(3, output, 0, 0, 0, 0, 0); syscall(11, pair, 8, 0, 0, 0, 0);
    if pid < 0 { syscall(3, writer, 0, 0, 0, 0, 0); return ps_video_error("cannot start FFmpeg"); }
    ps_video_pid = pid; ps_video_fd = writer; syscall(72, writer, 4, 2048, 0, 0, 0); ps_video_path = path;
    ps_video_pixels = alloc(ps_video_width * ps_video_height * 3); pl_print(2, "Recording video: "); pl_print(2, path); pl_print(2, "\n"); return 1;
}
fn ps_video_count(step, final) {
    let count = step * ps_video_fps / 50;
    if final { count = (step * ps_video_fps + 49) / 50; if !count { count = 1; } } return count;
}
fn ps_video_due(step, final) { return ps_video_pid && ps_video_count(step, final) > ps_video_frames; }
fn ps_video_frame(step, final) {
    let w = gui_pixel_width(load64(ps_device)); let h = gui_pixel_height(load64(ps_device)); if w < 1 || h < 1 { return ps_video_error("window has no drawable framebuffer"); }
    // Keep the original even output dimensions and letterbox window resizes.
    let width = ps_video_width; let height = ps_video_height;
    if width * h > height * w { width = height * w / h; } else { height = width * h / w; }
    let x = (ps_video_width - width) / 2; let y = (ps_video_height - height) / 2;
    render_gl(ps_device, "glBindFramebuffer", 0x8ca9, load64(ps_video_target + 16), 0, 0, 0, 0); render_gl(ps_device, "glDisable", 0x0c11, 0, 0, 0, 0, 0);
    pb_zero(ps_video_args, 88); render_gl(ps_device, "glClearBufferfv", 0x1800, 0, ps_video_args, 0, 0, 0);
    render_gl(ps_device, "glBindFramebuffer", 0x8ca8, 0, 0, 0, 0, 0);
    store64(ps_video_args + 16, w); store64(ps_video_args + 24, h); store64(ps_video_args + 32, x); store64(ps_video_args + 40, y);
    store64(ps_video_args + 48, x + width); store64(ps_video_args + 56, y + height); store64(ps_video_args + 64, 0x4000); store64(ps_video_args + 72, 0x2601);
    ffi_call_words(gui_gl_cached_proc(load64(ps_device), "glBlitFramebuffer"), ps_video_args);
    render_gl(ps_device, "glBindFramebuffer", 0x8ca8, load64(ps_video_target + 16), 0, 0, 0, 0); render_gl(ps_device, "glReadBuffer", 0x8ce0, 0, 0, 0, 0, 0);
    render_gl(ps_device, "glPixelStorei", 0x0d05, 1, 0, 0, 0, 0); pb_zero(ps_video_args, 88);
    store64(ps_video_args + 16, ps_video_width); store64(ps_video_args + 24, ps_video_height); store64(ps_video_args + 32, 0x1907); store64(ps_video_args + 40, 0x1401); store64(ps_video_args + 48, ps_video_pixels);
    ffi_call_words(gui_gl_cached_proc(load64(ps_device), "glReadPixels"), ps_video_args); render_gl(ps_device, "glBindFramebuffer", 0x8d40, 0, 0, 0, 0, 0);
    if render_gl(ps_device, "glGetError", 0, 0, 0, 0, 0, 0) { return ps_video_error("framebuffer readback failed"); }
    let size = ps_video_width * ps_video_height * 3; let count = ps_video_count(step, final);
    while ps_video_frames < count {
        let at = 0; let deadline = pl_now() + 30000;
        while at < size {
            let n = syscall(1, ps_video_fd, ps_video_pixels + at, size - at, 0, 0, 0);
            if n > 0 { at = at + n; }
            else if n == -11 { if ps_video_reap() || !pl_wait(ps_video_fd, 4, deadline) { return ps_video_error("FFmpeg stopped or did not accept a frame within 30 seconds"); } }
            else if n != -4 { return ps_video_error("cannot send a frame to FFmpeg"); }
        }
        ps_video_frames = ps_video_frames + 1;
    }
    return 1;
}
