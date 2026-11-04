// Optional Blender-authored visual world and independent fixed box colliders.
// PBENV001: 256-byte header, N 128-byte OBBs, full and cutaway vertex streams.
import "container.flex";

global ps_environment = 0;
global ps_environment_size = 0;
global ps_environment_count = 0;
global ps_environment_vertices = 0;
global ps_environment_data = 0;
global ps_environment_bodies = 0;
global ps_environment_start = 0;
global ps_environment_mesh = 0;
global ps_environment_overview = 0;

fn ps_environment_inside(x, y) {
    if !ps_environment { return !f64_gt(f64_magnitude(x), ps_number(18, 10)) && !f64_gt(f64_magnitude(y), ps_number(18, 10)); }
    return f64_gt(x, load64(ps_environment + 64)) && f64_gt(y, load64(ps_environment + 72)) && f64_lt(x, load64(ps_environment + 80)) && f64_lt(y, load64(ps_environment + 88));
}
fn ps_environment_load(path) {
    let fd = syscall(2, path, 0x80000, 0, 0, 0, 0); if fd < 0 { return 0; }
    let size = syscall(8, fd, 0, 2, 0, 0, 0); if size < 256 || size > 75497472 { syscall(3, fd, 0, 0, 0, 0, 0); return 0; }
    let data = syscall(9, 0, size, 1, 2, fd, 0); syscall(3, fd, 0, 0, 0, 0, 0); if data < 0 { return 0; }
    let count = load64(data + 8); let vertices = load64(data + 16); let valid = load64(data) == load64("PBENV001");
    valid = valid && count >= 1 && count <= 160 && vertices >= 3 && vertices <= 1000000 && vertices % 3 == 0 && load64(data + 24) == vertices;
    valid = valid && size == 256 + count * 128 + vertices * 72;
    let i = 0;
    while valid && i < 7 {
        let value = load64(data + 64 + i * 8); valid = f64_is_finite(value) && !f64_gt(f64_magnitude(value), f64_from_i64(100)); i = i + 1;
    }
    valid = valid && f64_lt(load64(data + 64), load64(data + 80)) && f64_lt(load64(data + 72), load64(data + 88));
    i = 0; let title = 0;
    while valid && i < 64 { let c = load8(data + 128 + i); if !c { title = 1; } else if !title && (c < 32 || c > 126) { valid = 0; } i = i + 1; }
    valid = valid && title && load8(data + 128); i = 0;
    while valid && i < count {
        let r = data + 256 + i * 128; let k = 0; let terminated = 0;
        while valid && k < 48 { let c = load8(r + k); if !c { terminated = 1; } else if !terminated && (c < 32 || c > 126) { valid = 0; } k = k + 1; }
        valid = valid && terminated && load8(r); k = 0;
        while valid && k < 7 {
            let value = load64(r + 48 + k * 8); valid = f64_is_finite(value) && !f64_gt(f64_magnitude(value), f64_from_i64(100));
            if k >= 3 && k < 6 { valid = valid && f64_gt(value, ps_number(1, 100000)); } k = k + 1;
        }
        i = i + 1;
    }
    // Reject malformed GPU payloads before uploading; each vertex is position,
    // normal and base colour in binary32. No texture or shader source is loaded.
    let offset = 256 + count * 128; i = offset;
    while valid && i < size {
        let value = gui__u32(data + i); valid = (value & 0x7f800000) != 0x7f800000; i = i + 4;
    }
    if !valid { syscall(11, data, size, 0, 0, 0, 0); return 0; }
    ps_environment = data; ps_environment_size = size; ps_environment_count = count; ps_environment_vertices = vertices; ps_environment_data = data + offset;
    ps_environment_bodies = alloc(count * 8); ps_environment_start = alloc(24); pb_copy(ps_environment_start, data + 96, 24);
    return ps_environment_inside(load64(ps_environment_start), load64(ps_environment_start + 8));
}
fn ps_environment_spawn(text) {
    if !ps_environment { return 0; } let root = pj_parse(text, pl_size(text)); if !root || pj_kind(root) != 3 || pj_count(root) != 3 { return 0; } let i = 0;
    while i < 3 {
        let value = pj_real_node(pj_index(root, i)); if pj_error || !f64_is_finite(value) || f64_gt(f64_magnitude(value), f64_from_i64(100)) { return 0; }
        store64(ps_environment_start + i * 8, value); i = i + 1;
    }
    return ps_environment_inside(load64(ps_environment_start), load64(ps_environment_start + 8));
}
fn ps_environment_create() {
    if !ps_environment { return 0; } let i = 0;
    while i < ps_environment_count {
        let r = ps_environment + 256 + i * 128;
        let body = ph_box_body(ps_physics, 0, pb_f64_to_f32(load64(r + 48)), pb_f64_to_f32(load64(r + 56)), pb_f64_to_f32(load64(r + 64)), 0, pb_f64_to_f32(load64(r + 72)), pb_f64_to_f32(load64(r + 80)), pb_f64_to_f32(load64(r + 88)));
        let half = f64_mul(load64(r + 96), ps_number(1, 2)); ph_body_quaternion(ps_physics, body, 0, 0, pb_f64_to_f32(f64_sin(half)), pb_f64_to_f32(f64_cos(half)));
        store64(ps_environment_bodies + i * 8, body); i = i + 1;
    }
    return 0;
}
fn ps_environment_observation(b) {
    pl_text(b, ",\"environment\":"); if !ps_environment { return pl_text(b, "null"); }
    pl_text(b, "{\"name\":"); pj_text(b, ps_environment + 128); pl_text(b, ",\"staticColliders\":"); pl_int(b, ps_environment_count);
    pl_text(b, ",\"bounds\":["); let i = 0; while i < 4 { if i { pl_char(b, 44); } pl_float(b, load64(ps_environment + 64 + i * 8)); i = i + 1; }
    pl_text(b, "],\"blockedCollider\":"); let name = 0; i = 0;
    while i < ps_environment_count { if load64(ps_environment_bodies + i * 8) == ps_vehicle_hit { name = ps_environment + 256 + i * 128; } i = i + 1; }
    if name { pj_text(b, name); } else { pl_text(b, "null"); }
    return pl_text(b, ",\"furnitureDynamic\":false,\"sensorCameras\":[\"tcp\"],\"overviewCutaway\":true}");
}
fn ps_environment_close() {
    if ps_environment { syscall(11, ps_environment, ps_environment_size, 0, 0, 0, 0); } return 0;
}
