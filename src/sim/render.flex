import "arm-proxy.flex";

global ps_device = 0;
global ps_material = 0;
global ps_mesh = 0;
global ps_cube = 0;
global ps_ball_mesh = 0;
global ps_tyre_mesh = 0;
global ps_colliders = 0;
global ps_view = 0;
global ps_gpu_model = 0;
global ps_draw_model = 0;
global ps_tint = 0;
global ps_eye = 0;
global ps_target = 0;
global ps_up = 0;
global ps_azimuth = -40;
global ps_elevation = 32;
global ps_radius = 900;
// Main camera: 0 = world orbit, 2 = the single wrist/TCP sensor.
global ps_camera_mode = 0;
global ps_render_target = 0;
global ps_tcp_view = 0;
global ps_tcp_view_width = 0;
global ps_tcp_view_height = 0;
global ps_label_material = 0;
global ps_label_mesh = 0;

fn ps_require(ok) {
    if !ok { pl_print(2, "PuppyBot simulation renderer: "); if gui_error { pl_print(2, gui_error); } pl_print(2, "\n"); syscall(231, 1, 0, 0, 0, 0, 0); } return ok;
}
fn ps_vertex(p, x, y, z, nx, ny, nz, r, g, b) {
    gui__put32(p, pb_f64_to_f32(x)); gui__put32(p + 4, pb_f64_to_f32(y)); gui__put32(p + 8, pb_f64_to_f32(z));
    gui__put32(p + 12, pb_f64_to_f32(nx)); gui__put32(p + 16, pb_f64_to_f32(ny)); gui__put32(p + 20, pb_f64_to_f32(nz));
    gui__put32(p + 24, r); gui__put32(p + 28, g); gui__put32(p + 32, b); return 0;
}
fn ps_new_mesh(data, count) {
    let attributes = alloc(144); pb_zero(attributes, 144); let i = 0;
    while i < 3 { let a = attributes + i * 48; store64(a, i); store64(a + 8, 3); store64(a + 16, 0x1406); store64(a + 32, i * 12); i = i + 1; }
    let mesh = render_mesh(ps_device, 36, attributes, 3); syscall(11, attributes, 144, 0, 0, 0, 0); ps_require(mesh);
    ps_require(render_mesh_upload(mesh, data, count, 0x88e4)); return mesh;
}
fn ps_shapes() {
    let data = alloc(36 * 36); let face = 0;
    while face < 6 {
        let axis = face / 2; let sign = 1; if face % 2 { sign = -1; } let i = 0;
        while i < 6 {
            let corner = i; if i == 3 { corner = 0; } if i == 4 { corner = 2; } if i == 5 { corner = 3; }
            let u = -1; let v = -1; if corner == 1 || corner == 2 { u = 1; } if corner >= 2 { v = 1; }
            let p = data + (face * 6 + i) * 36; let k = 0;
            while k < 3 { let position = 0; let normal = 0;
                if k == axis { position = sign; normal = sign; } else if k == (axis + 1) % 3 { position = u * sign; } else { position = v; }
                render_float(p + k * 4, position, 1); render_float(p + 12 + k * 4, normal, 1); render_float(p + 24 + k * 4, 1, 1); k = k + 1;
            }
            i = i + 1;
        }
        face = face + 1;
    }
    ps_cube = ps_new_mesh(data, 36); syscall(11, data, 36 * 36, 0, 0, 0, 0);
    data = alloc(24 * 12 * 6 * 36); let at = 0; let lat = 0;
    while lat < 12 {
        let lon = 0;
        while lon < 24 {
            let i = 0;
            while i < 6 {
                let a = lon; let b = lat;
                if i == 1 || i == 2 || i == 4 { a = a + 1; } if i == 2 || i == 4 || i == 5 { b = b + 1; }
                let theta = f64_mul(PB_TAU, ps_number(a, 24)); let phi = f64_sub(f64_mul(PB_PI, ps_number(b, 12)), PB_HALF_PI);
                let x = f64_mul(f64_cos(phi), f64_cos(theta)); let y = f64_mul(f64_cos(phi), f64_sin(theta)); let z = f64_sin(phi);
                ps_vertex(data + at * 36, x, y, z, x, y, z, 0x3f800000, 0x3f800000, 0x3f800000); at = at + 1; i = i + 1;
            }
            lon = lon + 1;
        }
        lat = lat + 1;
    }
    ps_ball_mesh = ps_new_mesh(data, at); syscall(11, data, at * 36, 0, 0, 0, 0);
    data = alloc(24 * 12 * 36); at = 0; let segment = 0;
    while segment < 24 {
        let i = 0;
        while i < 12 {
            let a = segment; let z = -1; let centre = 0;
            if i < 6 { if i == 1 || i == 2 || i == 4 { a = a + 1; } if i == 2 || i == 4 || i == 5 { z = 1; } }
            else { if i >= 9 { z = 1; } if i % 3 == 0 { centre = 1; } if i % 3 == 2 { a = a + 1; } }
            let theta = f64_mul(PB_TAU, ps_number(a, 24)); let x = f64_cos(theta); let y = f64_sin(theta);
            let nx = x; let ny = y; let nz = 0;
            if i >= 6 { nx = 0; ny = 0; nz = f64_from_i64(z); } if centre { x = 0; y = 0; }
            ps_vertex(data + at * 36, x, y, f64_from_i64(z), nx, ny, nz, 0x3f800000, 0x3f800000, 0x3f800000); at = at + 1; i = i + 1;
        }
        segment = segment + 1;
    }
    ps_tyre_mesh = ps_new_mesh(data, at); syscall(11, data, at * 36, 0, 0, 0, 0); return 0;
}
fn ps_glyph(code) {
    if code >= 97 && code <= 122 { code = code - 32; }
    if code == 65 { return 0x4631fc62e; }
    if code == 66 { return 0x3e317c62f; }
    if code == 67 { return 0x78210843e; }
    if code == 68 { return 0x3e318c62f; }
    if code == 69 { return 0x7c217843f; }
    if code == 70 { return 0x4217843f; }
    if code == 71 { return 0x7a31e843e; }
    if code == 72 { return 0x4631fc631; }
    if code == 73 { return 0x7c842109f; }
    if code == 74 { return 0x19294211c; }
    if code == 75 { return 0x452519531; }
    if code == 76 { return 0x7c2108421; }
    if code == 77 { return 0x4631ad771; }
    if code == 78 { return 0x4739ace71; }
    if code == 79 { return 0x3a318c62e; }
    if code == 80 { return 0x4217c62f; }
    if code == 81 { return 0x59358c62e; }
    if code == 82 { return 0x45257c62f; }
    if code == 83 { return 0x3e107043e; }
    if code == 84 { return 0x10842109f; }
    if code == 85 { return 0x3a318c631; }
    if code == 86 { return 0x11518c631; }
    if code == 87 { return 0x2ab5ac631; }
    if code == 88 { return 0x462a22a31; }
    if code == 89 { return 0x108422a31; }
    if code == 90 { return 0x7c222221f; }
    if code == 48 { return 0x3a33ae62e; }
    if code == 49 { return 0x3884210c4; }
    if code == 50 { return 0x7c444422e; }
    if code == 51 { return 0x3e107420f; }
    if code == 52 { return 0x211f4a988; }
    if code == 53 { return 0x3e107843f; }
    if code == 54 { return 0x3a317842e; }
    if code == 55 { return 0x8422221f; }
    if code == 56 { return 0x3a317462e; }
    if code == 57 { return 0x3a10f462e; }
    if code == 37 { return 0x18d11173; }
    if code == 45 { return 0xf8000; }
    if code == 46 { return 0x318000000; }
    return 0;
}
fn ps_text_upload(mesh, text) {
    let length = pb_min(pl_size(text), 48); let capacity = pb_max(1, length * 35 * 6 * 36); let data = alloc(capacity); let count = 0; let letter = 0;
    while letter < length {
        let glyph = ps_glyph(load8(text + letter)); let pixel = 0;
        while pixel < 35 {
            if (glyph >> pixel) & 1 {
                let i = 0;
                while i < 6 {
                    let x = 0; let y = 0; if i == 1 || i == 2 || i == 4 { x = 2; } if i == 2 || i == 4 || i == 5 { y = 2; }
                    ps_vertex(data + count * 36, f64_from_i64(letter * 12 + pixel % 5 * 2 + x), f64_from_i64(pixel / 5 * 2 + y), 0, 0, 0, PB_ONE, 0x3f800000, 0x3f800000, 0x3f800000);
                    count = count + 1; i = i + 1;
                }
            }
            pixel = pixel + 1;
        }
        letter = letter + 1;
    }
    if !mesh { mesh = ps_new_mesh(data, count); } else { ps_require(render_mesh_upload(mesh, data, count, 0x88e8)); }
    syscall(11, data, capacity, 0, 0, 0, 0); return mesh;
}
fn ps_text_draw(mesh, width, height, x, y) {
    let i = 0; while i < 16 { render_float(ps_view + i * 4, 0, 1); i = i + 1; }
    render_float(ps_view, 2, width); render_float(ps_view + 20, -2, height); render_float(ps_view + 48, 2 * x - width, width); render_float(ps_view + 52, height - 2 * y, height); render_float(ps_view + 60, 1, 1);
    ps_require(render_matrix(ps_label_material, 0, "uCamera", ps_view)); render_gl(ps_device, "glDisable", 0x0b71, 0, 0, 0, 0, 0);
    return ps_require(render_draw(ps_device, load64(mesh + 8), 4, 0, load64(mesh + 32)));
}
fn ps_label_init() {
    ps_label_mesh = ps_text_upload(0, "TCP LIVE");
    ps_label_material = render_material(ps_device, "#version 450 core\nlayout(location=0) in vec3 aPosition; uniform mat4 uCamera; void main(){gl_Position=uCamera*vec4(aPosition,1);}", "#version 450 core\nout vec4 color; void main(){color=vec4(0.55,0.95,0.95,1);}");
    ps_require(ps_label_material); return render_material_state(ps_label_material, 0, 0);
}
fn ps_render_init(hidden) {
    let flags = GUI_RESIZABLE; if hidden { flags = GUI_HIDDEN; }
    let width = 1280; let height = 800; if ps_camera_mode { width = 640; height = 480; }
    ps_device = render_open("PuppyBot | WASD drive | 1-4 joint, Q/E jog | Space pause | drag orbit, wheel zoom | R reset", width, height, flags); ps_require(ps_device);
    gui_gl_swap_interval(load64(ps_device), 0);
    let vertex = "#version 450 core\nlayout(location=0) in vec3 aPosition; layout(location=1) in vec3 aNormal; layout(location=2) in vec3 aColor; uniform mat4 uCamera; uniform mat4 uModel; out vec3 vNormal; out vec3 vColor; out vec3 vWorld; void main(){ vec4 p=uModel*vec4(aPosition,1); vWorld=p.xyz; vNormal=normalize(mat3(uModel)*aNormal); vColor=aColor; gl_Position=uCamera*p; }";
    let fragment = "#version 450 core\nin vec3 vNormal; in vec3 vColor; in vec3 vWorld; uniform vec4 uTint; uniform vec4 uScene; out vec4 color; void main(){ vec3 n=normalize(vNormal); if(!gl_FrontFacing)n=-n; vec3 base=vColor*uTint.rgb; if(vWorld.z<0.001 && n.z>0.9){ vec2 p=vWorld.xy*10; vec2 d=abs(fract(p-0.5)-0.5)/max(fwidth(p),vec2(0.0001)); float grid=1-min(min(d.x,d.y),1); base=mix(base,base+vec3(0.13),grid*0.65); } float light=0.40+0.60*max(dot(n,normalize(vec3(-0.3,-0.5,1))),0); vec3 lit=base*light; float fog=1-exp(-uScene.x*dot(vWorld.xy,vWorld.xy)); color=vec4(mix(lit,vec3(0.055,0.075,0.105),fog),1); }";
    ps_material = render_material(ps_device, vertex, fragment); ps_require(ps_material); render_material_state(ps_material, 0, 0);
    ps_mesh = ps_new_mesh(ps_asset + 64 + (ps_groups + 1) * 256, ps_vertices); ps_shapes();
    if ps_environment { ps_environment_mesh = ps_new_mesh(ps_environment_data, ps_environment_vertices); ps_environment_overview = ps_new_mesh(ps_environment_data + ps_environment_vertices * 36, ps_environment_vertices); }
    ps_view = alloc(64); ps_gpu_model = alloc(64); ps_draw_model = alloc(128); ps_tint = alloc(16); ps_eye = alloc(24); ps_target = alloc(24); ps_up = alloc(24);
    pb_zero(ps_up, 24); store64(ps_up + 16, 1000000);
    ps_label_init();
    pl_print(1, "OpenGL: "); pl_print(1, render_gl(ps_device, "glGetString", 0x1f01, 0, 0, 0, 0, 0)); pl_print(1, "\n"); return 1;
}
fn ps_draw(mesh, matrix, first, count, r, g, b) {
    let i = 0; while i < 16 { gui__put32(ps_gpu_model + i * 4, pb_f64_to_f32(pb_vget(matrix, i))); i = i + 1; }
    ps_require(render_matrix(ps_material, 0, "uModel", ps_gpu_model));
    gui__put32(ps_tint, ps_float(r, 100)); gui__put32(ps_tint + 4, ps_float(g, 100)); gui__put32(ps_tint + 8, ps_float(b, 100)); gui__put32(ps_tint + 12, 0x3f800000);
    render_gl(ps_device, "glUniform4fv", render_uniform(ps_material, 0, "uTint"), 1, ps_tint, 0, 0, 0);
    return ps_require(render_mesh_draw(mesh, ps_material, 0, first, count));
}
fn ps_box_matrix(x, y, z, hx, hy, hz) {
    ps_identity(ps_draw_model);
    // Arguments are centre then half-extents; retain the shared draw matrix.
    pb_vset(ps_draw_model, 0, hx); pb_vset(ps_draw_model, 5, hy); pb_vset(ps_draw_model, 10, hz);
    pb_vset(ps_draw_model, 12, x); pb_vset(ps_draw_model, 13, y); pb_vset(ps_draw_model, 14, z); return ps_draw_model;
}
fn ps_camera_update(width, height) {
    pb_zero(ps_up, 24); store64(ps_up + 16, 1000000);
    let az = pb_radians(f64_from_i64(ps_azimuth)); let el = pb_radians(f64_from_i64(ps_elevation));
    let radius = f64_from_i64(ps_radius); let horizontal = f64_mul(radius, f64_cos(el));
    store64(ps_target, f64_to_i64_trunc(f64_mul(ps_x, f64_from_i64(1000)))); store64(ps_target + 8, f64_to_i64_trunc(f64_mul(ps_y, f64_from_i64(1000)))); store64(ps_target + 16, 120);
    if ps_environment && !ps_camera_mode && ps_radius >= 6000 {
        store64(ps_target, f64_to_i64_trunc(f64_mul(f64_add(load64(ps_environment + 64), load64(ps_environment + 80)), f64_from_i64(500))));
        store64(ps_target + 8, f64_to_i64_trunc(f64_mul(f64_add(load64(ps_environment + 72), load64(ps_environment + 88)), f64_from_i64(500))));
    }
    store64(ps_eye, load64(ps_target) + f64_to_i64_trunc(f64_mul(horizontal, f64_cos(az))));
    store64(ps_eye + 8, load64(ps_target + 8) + f64_to_i64_trunc(f64_mul(horizontal, f64_sin(az))));
    store64(ps_eye + 16, 120 + f64_to_i64_trunc(f64_mul(radius, f64_sin(el))));
    if ps_camera_mode {
        // Fixed outboard wrist mount: eye (80,65,-65) mm, looking toward
        // (80,0,65) mm. It sees past the palm without hiding robot geometry.
        let i = 0;
        while i < 3 {
            let origin = f64_mul(pb_vget(ps_gripper_frame, 12 + i), f64_from_i64(1000));
            origin = f64_add(origin, f64_mul(pb_vget(ps_gripper_frame, i), f64_from_i64(80)));
            let y = pb_vget(ps_gripper_frame, 4 + i); let z = pb_vget(ps_gripper_frame, 8 + i);
            store64(ps_eye + i * 8, f64_to_i64_nearest(f64_sub(f64_add(origin, f64_mul(y, f64_from_i64(65))), f64_mul(z, f64_from_i64(65)))));
            // Round a direction from the fixed mount axes, so translation
            // does not introduce false rotation into the stereo baseline.
            let look = f64_sub(f64_mul(z, f64_from_i64(130000)), f64_mul(y, f64_from_i64(65000)));
            store64(ps_target + i * 8, load64(ps_eye + i * 8) + f64_to_i64_nearest(look));
            let sign = -1000000; if ps_camera_drive_mode { sign = 1000000; }
            store64(ps_up + i * 8, f64_to_i64_nearest(f64_mul(y, f64_from_i64(sign)))); i = i + 1;
        }
    }
    let far = 10000; if ps_environment && !ps_camera_mode { far = 30000; }
    return ps_require(render_camera(ps_view, ps_eye, ps_target, ps_up, width, height, 1732051, 10, far));
}
fn ps_body_matrix(id, hx, hy, hz) {
    let body = ph_body(ps_physics, id); let scale = ps_gripper_local; store64(scale, hx); store64(scale + 8, hy); store64(scale + 16, hz); ps_identity(ps_draw_model);
    let col = 0; while col < 3 { let row = 0; while row < 3 { pb_vset(ps_draw_model, col * 4 + row, f64_mul(pb_f32_to_f64(load64(body + 256 + (col * 3 + row) * 8)), pb_vget(scale, col))); row = row + 1; } col = col + 1; }
    pb_vset(ps_draw_model, 12, pb_f32_to_f64(load64(body + 8))); pb_vset(ps_draw_model, 13, pb_f32_to_f64(load64(body + 16))); pb_vset(ps_draw_model, 14, pb_f32_to_f64(load64(body + 24))); return ps_draw_model;
}
fn ps_vehicle_render() {
    if !ps_colliders || ps_render_target || ps_camera_mode { return 0; }
    render_gl(ps_device, "glDisable", 0x0b71, 0, 0, 0, 0, 0); render_gl(ps_device, "glDisable", 0x0b44, 0, 0, 0, 0, 0);
    render_gl(ps_device, "glPolygonMode", 0x0408, 0x1b01, 0, 0, 0, 0); let part = 0;
    while part < 5 {
        let id = 4; let mesh = ps_cube; let count = 36; if part { id = ps_wheel_body + part - 1; mesh = ps_tyre_mesh; count = 24 * 12; }
        let shape = ps_body_shape(id); let hx = pb_f32_to_f64(load64(shape + 72)); let hy = pb_f32_to_f64(load64(shape + 80)); let hz = pb_f32_to_f64(load64(shape + 88));
        if part { hz = hy; hy = hx; }
        ps_body_matrix(id, hx, hy, hz); let red = 15; let green = 95;
        if ps_blocked && part == ps_vehicle_part { red = 100; green = 25; }
        ps_draw(mesh, ps_draw_model, 0, count, red, green, 95); part = part + 1;
    }
    part = 0;
    while part < ps_arm_collider_count + 3 {
        if part < 3 {
            let id = 5 + part; let shape = ph_shape(ps_physics, id); ps_body_matrix(id, pb_f32_to_f64(load64(shape + 72)), pb_f32_to_f64(load64(shape + 80)), pb_f32_to_f64(load64(shape + 88)));
        } else {
            let r = ps_arm_colliders + (part - 3) * 56; let m = ps_world_matrices + load64(r) * 128; ps_point(ps_solid_point, m, r + 8); ps_identity(ps_draw_model); let col = 0;
            while col < 3 {
                let row = 0; while row < 3 { store64(ps_draw_model + (col * 4 + row) * 8, f64_mul(load64(m + (col * 4 + row) * 8), load64(r + 32 + col * 8))); row = row + 1; }
                store64(ps_draw_model + (12 + col) * 8, load64(ps_solid_point + col * 8)); col = col + 1;
            }
        }
        let red = 15; let green = 95;
        if (ps_arm_blocked && part == ps_arm_part) || (ps_blocked && part + 5 == ps_vehicle_part) { red = 100; green = 25; }
        ps_draw(ps_cube, ps_draw_model, 0, 36, red, green, 95); part = part + 1;
    }
    render_gl(ps_device, "glPolygonMode", 0x0408, 0x1b02, 0, 0, 0, 0); render_gl(ps_device, "glEnable", 0x0b71, 0, 0, 0, 0, 0); render_gl(ps_device, "glEnable", 0x0b44, 0, 0, 0, 0, 0); return 0;
}
fn ps_case_render() {
    let i = 0;
    while i < ps_case_scenery_count {
        let r = ps_case_scenery + i * 128; ps_body_matrix(load64(r + 120), load64(r + 72), load64(r + 80), load64(r + 88));
        ps_draw(ps_cube, ps_draw_model, 0, 36, f64_to_i64_nearest(load64(r + 96)), f64_to_i64_nearest(load64(r + 104)), f64_to_i64_nearest(load64(r + 112))); i = i + 1;
    }
    i = 0;
    while i < ps_case_count {
        let record = ps_case_objects + i * 256;
        if !load64(record + 208) {
            let id = load64(record + 184); let mesh = ps_cube; let count = 36;
            if load64(record + 64) { mesh = ps_ball_mesh; count = 24 * 12 * 6; }
            ps_body_matrix(id, load64(record + 96), load64(record + 104), load64(record + 112));
            let red = f64_to_i64_nearest(load64(record + 160)); let green = f64_to_i64_nearest(load64(record + 168)); let blue = f64_to_i64_nearest(load64(record + 176));
            ps_draw(mesh, ps_draw_model, 0, count, red, green, blue);
            if !load64(record + 64) {
                // Decorative studs follow the same physical box transform. The
                // collider stays a cuboid; interlocking brick physics is separate.
                let body = ph_body(ps_physics, id); let stud = 0;
                while stud < 4 {
                    let x = f64_mul(load64(record + 96), ps_number(-1, 2)); if stud % 2 { x = pb_neg(x); }
                    let y = f64_mul(load64(record + 104), ps_number(-1, 2)); if stud >= 2 { y = pb_neg(y); }
                    let z = f64_add(load64(record + 112), ps_number(2, 1000)); let axis = 0;
                    while axis < 3 {
                        let position = pb_f32_to_f64(load64(body + 8 + axis * 8));
                        position = f64_add(position, f64_add(f64_add(f64_mul(pb_f32_to_f64(load64(body + 256 + axis * 8)), x), f64_mul(pb_f32_to_f64(load64(body + 280 + axis * 8)), y)), f64_mul(pb_f32_to_f64(load64(body + 304 + axis * 8)), z)));
                        pb_vset(ps_gripper_local, axis, position); axis = axis + 1;
                    }
                    ps_box_matrix(load64(ps_gripper_local), load64(ps_gripper_local + 8), load64(ps_gripper_local + 16), ps_number(4, 1000), ps_number(4, 1000), ps_number(3, 1000)); ps_draw(ps_ball_mesh, ps_draw_model, 0, 24 * 12 * 6, red, green, blue); stud = stud + 1;
                }
            }
        }
        i = i + 1;
    }
    i = 0;
    while i < 5 {
        let shape = ph_shape(ps_physics, ps_case_bin_shape + i); ps_identity(ps_draw_model); let col = 0;
        while col < 3 {
            let row = 0; while row < 3 { store64(ps_draw_model + (col * 4 + row) * 8, f64_mul(pb_f32_to_f64(load64(shape + 120 + (col * 3 + row) * 8)), pb_f32_to_f64(load64(shape + 72 + col * 8)))); row = row + 1; }
            store64(ps_draw_model + (12 + col) * 8, pb_f32_to_f64(load64(shape + 96 + col * 8))); col = col + 1;
        }
        if !i { ps_draw(ps_cube, ps_draw_model, 0, 36, 24, 36, 48); } else { ps_draw(ps_cube, ps_draw_model, 0, 36, 35, 57, 72); } i = i + 1;
    }
    if load64(ps_case_bin + 80) {
        // Corner and midpoint optical patches attached to the physical rim.
        // They have no detector IDs, depth output or special sensor render pass.
        i = 0;
        while i < 8 {
            let x = f64_mul(f64_add(load64(ps_case_bin + 24), load64(ps_case_bin + 48)), ps_number(1, 2)); let y = f64_mul(f64_add(load64(ps_case_bin + 32), load64(ps_case_bin + 48)), ps_number(1, 2));
            if !(i % 2) { x = pb_neg(x); } if i < 2 { y = pb_neg(y); }
            if i == 4 || i == 5 { y = 0; } if i == 6 || i == 7 { x = 0; if i == 6 { y = pb_neg(y); } }
            store64(ps_bin_local_point, x); store64(ps_bin_local_point + 8, y); store64(ps_bin_local_point + 16, f64_add(f64_add(load64(ps_case_bin + 40), load64(ps_case_bin + 48)), ps_number(1, 2000)));
            ps_point(ps_gripper_local, ps_bin_frame, ps_bin_local_point); ps_identity(ps_draw_model); let col = 0;
            while col < 3 { let row = 0; let half = ps_number(3, 1000); if col == 2 { half = ps_number(1, 2000); }
                while row < 3 { store64(ps_draw_model + (col * 4 + row) * 8, f64_mul(load64(ps_bin_frame + (col * 4 + row) * 8), half)); row = row + 1; }
                store64(ps_draw_model + (12 + col) * 8, load64(ps_gripper_local + col * 8)); col = col + 1;
            }
            ps_draw(ps_cube, ps_draw_model, 0, 36, 95, 5, 90); i = i + 1;
        }
    }
    return 1;
}
fn ps_scene(width, height, x, y) {
    ps_camera_update(width, height); ps_require(render_begin(ps_device, ps_render_target, width, height));
    render_gl(ps_device, "glViewport", x, y, width, height, 0, 0);
    gui__put32(ps_tint, ps_float(55, 1000)); gui__put32(ps_tint + 4, ps_float(75, 1000)); gui__put32(ps_tint + 8, ps_float(105, 1000)); gui__put32(ps_tint + 12, 0x3f800000);
    render_gl(ps_device, "glClearBufferfv", 0x1800, 0, ps_tint, 0, 0, 0); ps_require(render_matrix(ps_material, 0, "uCamera", ps_view));
    // The original fog suits a 4 m arena. Keep distant apartment furniture
    // visible without changing either robot camera or the legacy scene.
    let fog = ps_float(25, 1000); if ps_environment { fog = ps_float(2, 1000); } gui__put32(ps_tint, fog);
    render_gl(ps_device, "glUniform4fv", render_uniform(ps_material, 0, "uScene"), 1, ps_tint, 0, 0, 0);
    let i = 0;
    while i < 3 && !ps_environment {
        let body = ph_body(ps_physics, i); let shape = ph_shape(ps_physics, i);
        ps_box_matrix(pb_f32_to_f64(load64(body + 8)), pb_f32_to_f64(load64(body + 16)), pb_f32_to_f64(load64(body + 24)), pb_f32_to_f64(load64(shape + 72)), pb_f32_to_f64(load64(shape + 80)), pb_f32_to_f64(load64(shape + 88)));
        if !i { ps_draw(ps_cube, ps_draw_model, 0, 36, 16, 22, 29); } else { ps_draw(ps_cube, ps_draw_model, 0, 36, 60, 36, 20); } i = i + 1;
    }
    if ps_environment {
        ps_identity(ps_draw_model); let mesh = ps_environment_mesh; if !ps_camera_mode { mesh = ps_environment_overview; }
        ps_draw(mesh, ps_draw_model, 0, ps_environment_vertices, 100, 100, 100);
    }
    // World origin axes and a destination pad remain independent of the robot.
    if !ps_camera_mode && !ps_environment {
    ps_box_matrix(ps_number(15, 100), 0, ps_number(1, 1000), ps_number(15, 100), ps_number(2, 1000), ps_number(1, 1000)); ps_draw(ps_cube, ps_draw_model, 0, 36, 95, 30, 28);
    ps_box_matrix(0, ps_number(15, 100), ps_number(1, 1000), ps_number(2, 1000), ps_number(15, 100), ps_number(1, 1000)); ps_draw(ps_cube, ps_draw_model, 0, 36, 25, 85, 55);
    ps_box_matrix(ps_number(6, 10), ps_number(35, 100), ps_number(1, 1000), ps_number(9, 100), ps_number(9, 100), ps_number(1, 1000)); ps_draw(ps_cube, ps_draw_model, 0, 36, 15, 65, 60);
    }
    i = 0;
    while i < ps_groups { let r = ps_asset + 64 + i * 256; ps_draw(ps_mesh, ps_world_matrices + i * 128, load64(r + 184), load64(r + 192), 100, 100, 100); i = i + 1; }
    i = 0;
    while i < 3 {
        let body = ph_body(ps_physics, 5 + i); let shape = ph_shape(ps_physics, 5 + i); ps_identity(ps_draw_model); let col = 0;
        while col < 3 { let row = 0; while row < 3 { pb_vset(ps_draw_model, col * 4 + row, f64_mul(pb_vget(ps_gripper_frame, col * 4 + row), pb_f32_to_f64(pb_vget(shape + 72, col)))); row = row + 1; } col = col + 1; }
        pb_vset(ps_draw_model, 12, pb_f32_to_f64(load64(body + 8))); pb_vset(ps_draw_model, 13, pb_f32_to_f64(load64(body + 16))); pb_vset(ps_draw_model, 14, pb_f32_to_f64(load64(body + 24)));
        if !i { ps_draw(ps_cube, ps_draw_model, 0, 36, 32, 60, 70); } else { ps_draw(ps_cube, ps_draw_model, 0, 36, 18, 80, 85); } i = i + 1;
    }
    if ps_case_index >= 0 { ps_case_render(); } else {
    let ball = ph_body(ps_physics, 3); ps_box_matrix(pb_f32_to_f64(load64(ball + 8)), pb_f32_to_f64(load64(ball + 16)), pb_f32_to_f64(load64(ball + 24)), ps_number(35, 1000), ps_number(35, 1000), ps_number(35, 1000)); ps_draw(ps_ball_mesh, ps_draw_model, 0, 24 * 12 * 6, 100, 65, 15);
    }
    if !ps_gripper_held && !ps_camera_mode { let centre = ps_gripper_targets + 72; ps_box_matrix(load64(centre), load64(centre + 8), load64(centre + 16), ps_number(3, 1000), ps_number(3, 1000), ps_number(3, 1000)); ps_draw(ps_ball_mesh, ps_draw_model, 0, 24 * 12 * 6, 15, 95, 85); }
    ps_vehicle_render(); return ps_require(!render_gl(ps_device, "glGetError", 0, 0, 0, 0, 0, 0));
}
fn ps_panel_clear(x, y, width, height, r, g, b) {
    render_gl(ps_device, "glScissor", x, y, width, height, 0, 0);
    gui__put32(ps_tint, ps_float(r, 100)); gui__put32(ps_tint + 4, ps_float(g, 100)); gui__put32(ps_tint + 8, ps_float(b, 100)); gui__put32(ps_tint + 12, 0x3f800000);
    return render_gl(ps_device, "glClearBufferfv", 0x1800, 0, ps_tint, 0, 0, 0);
}
fn ps_case_menu_draw(width, height) {
    if !ps_case_menu { return 0; }
    if !ps_case_menu_mesh {
        ps_case_menu_mesh = alloc((ps_catalog_count + 2) * 8); store64(ps_case_menu_mesh, ps_text_upload(0, "CASE CATALOG"));
        let i = 0; while i < ps_catalog_count { store64(ps_case_menu_mesh + (i + 1) * 8, ps_text_upload(0, ps_catalog_entries + i * 768 + 128)); i = i + 1; }
        store64(ps_case_menu_mesh + (ps_catalog_count + 1) * 8, ps_text_upload(0, "TAB HIDE   P RUN   G SHUFFLE"));
    }
    let key = ps_case_index * 4096 + ps_case_stage * 16 + ps_case_placed;
    if key != ps_case_status_key {
        let text = alloc(512); let b = alloc(32); pl_builder(b, text, 512);
        if ps_case_index >= 0 { pl_text(b, "PLACED "); pl_int(b, ps_case_placed); pl_text(b, " OF "); pl_int(b, ps_case_count); pl_text(b, " - "); pl_text(b, ps_case_phase_name()); }
        else { pl_text(b, "SELECT A CASE WITH BRACKET KEYS"); }
        ps_case_status_mesh = ps_text_upload(ps_case_status_mesh, text); ps_case_status_key = key;
        syscall(11, text, 512, 0, 0, 0, 0); syscall(11, b, 32, 0, 0, 0, 0);
    }
    let panel_width = pb_min(440, width - 40); let panel_height = 116 + ps_catalog_count * 28;
    render_gl(ps_device, "glViewport", 0, 0, width, height, 0, 0); render_gl(ps_device, "glEnable", 0x0c11, 0, 0, 0, 0, 0);
    ps_panel_clear(20, height - 20 - panel_height, panel_width, panel_height, 4, 9, 13);
    ps_text_draw(load64(ps_case_menu_mesh), width, height, 32, 32);
    let i = 0;
    while i < ps_catalog_count {
        if ps_case_index == i { ps_panel_clear(26, height - 82 - i * 28, panel_width - 12, 25, 12, 30, 32); }
        render_gl(ps_device, "glScissor", 20, height - 20 - panel_height, panel_width, panel_height, 0, 0);
        ps_text_draw(load64(ps_case_menu_mesh + (i + 1) * 8), width, height, 36, 62 + i * 28); i = i + 1;
    }
    ps_text_draw(ps_case_status_mesh, width, height, 32, 68 + ps_catalog_count * 28);
    ps_text_draw(load64(ps_case_menu_mesh + (ps_catalog_count + 1) * 8), width, height, 32, 98 + ps_catalog_count * 28);
    render_gl(ps_device, "glDisable", 0x0c11, 0, 0, 0, 0, 0); ps_camera_update(width, height); return 1;
}
fn ps_frame() {
    let w = gui_pixel_width(load64(ps_device)); let h = gui_pixel_height(load64(ps_device)); ps_tcp_view_width = 0; ps_tcp_view_height = 0;
    if ps_render_target { w = load64(ps_render_target + 24); h = load64(ps_render_target + 32); }
    if w < 1 || h < 1 { return 1; }
    // Displayed frames use the current wrist pose, including fast recordings.
    // The live panel owns its buffers and never refreshes policy observations.
    if !ps_render_target && ps_previews { ps_preview_next = 0; ps_preview_poll(); } ps_scene(w, h, 0, 0);
    // Scissor keeps both color and depth clears inside the inset. Detector
    // framebuffers always receive one clean camera, irrespective of UI layout.
    if !ps_render_target && !ps_previews && w >= 320 && h >= 240 && ((ps_tcp_view && ps_camera_mode != 2) || ps_live_enabled || (ps_case_index >= 0 && ps_case_camera)) {
        let width = w / 3; if width > 480 { width = 480; } if ps_environment && !ps_camera_mode && width > 360 { width = 360; } let height = width * 3 / 4;
        if height > h - 64 { height = h - 64; width = height * 4 / 3; }
        let x = w - width - 20; let y = h - height - 20; let camera = ps_camera_mode;
        render_gl(ps_device, "glEnable", 0x0c11, 0, 0, 0, 0, 0);
        ps_panel_clear(x - 3, y - 31, width + 6, height + 34, 18, 60, 65);
        ps_panel_clear(x, y - 28, width, 28, 4, 9, 12);
        render_gl(ps_device, "glScissor", x, y, width, height, 0, 0);
        ps_camera_mode = 2;
        ps_scene(width, height, x, y);
        if !(ps_case_index >= 0 && ps_case_camera) { ps_live_present(width, height, x, y, ps_camera_mode); } ps_camera_mode = camera;
        render_gl(ps_device, "glViewport", x, y - 28, width, 28, 0, 0); render_gl(ps_device, "glScissor", x, y - 28, width, 28, 0, 0);
        if ps_live_enabled && !(ps_case_index >= 0 && ps_case_camera) { ps_text_draw(ps_live_caption, width, 28, 12, 7); } else { ps_text_draw(ps_label_mesh, width, 28, 12, 7); }
        render_gl(ps_device, "glDisable", 0x0c11, 0, 0, 0, 0, 0); render_gl(ps_device, "glViewport", 0, 0, w, h, 0, 0);
        if camera != 1 || !ps_live_enabled { ps_tcp_view_width = width; ps_tcp_view_height = height; } ps_camera_update(w, h);
    }
    if !ps_render_target { if ps_previews { ps_preview_draw(w, h); } ps_case_menu_draw(w, h); }
    return ps_require(!render_gl(ps_device, "glGetError", 0, 0, 0, 0, 0, 0));
}
fn ps_capture_png(fd, data, width, height) {
    let library = ffi_open("libpng16.so.16"); let libc = ffi_open("libc.so.6");
    if !library || !libc { pl_print(2, "PNG capture requires libpng16.so.16 and libc.\n"); return 0; }
    let write = ffi_symbol(library, "png_image_write_to_stdio"); let open = ffi_symbol(libc, "fdopen"); let flush = ffi_symbol(libc, "fflush"); let close = ffi_symbol(libc, "fclose");
    if !write || !open || !flush || !close { pl_print(2, "PNG capture symbols unavailable.\n"); return 0; }
    let copy = syscall(32, fd, 0, 0, 0, 0, 0); if copy < 0 { return 0; }
    let stream = ffi_call(open, copy, "wb", 0, 0, 0, 0); if !stream { syscall(3, copy, 0, 0, 0, 0, 0); return 0; }
    let image = alloc(104); pb_zero(image, 104); pb_put32(image + 8, 1); pb_put32(image + 12, width); pb_put32(image + 16, height); pb_put32(image + 20, 2);
    // libpng's simplified API accepts a negative stride for bottom-up GL RGB.
    let ok = ffi_call_i32(write, image, stream, 0, data, -width * 3, 0);
    if !ok { pl_print(2, "PNG capture failed: "); pl_print(2, image + 36); pl_print(2, "\n"); }
    if ffi_call_i32(flush, stream, 0, 0, 0, 0, 0) { ok = 0; }
    if ffi_call_i32(close, stream, 0, 0, 0, 0, 0) { ok = 0; }
    syscall(11, image, 104, 0, 0, 0, 0); let dlclose = ffi_symbol(libc, "dlclose");
    if dlclose { ffi_call_i32(dlclose, library, 0, 0, 0, 0, 0); ffi_call_i32(dlclose, libc, 0, 0, 0, 0, 0); } return ok;
}
fn ps_camera_vector(b, v, divisor, negate) {
    pl_char(b, 91); let i = 0;
    while i < 3 { if i { pl_char(b, 44); } pl_float(b, ps_number(pb_vget(v, i) * negate, divisor)); i = i + 1; } return pl_char(b, 93);
}
fn ps_camera_metadata_at(path, width, height, frame, time) {
    let text = alloc(4096); let name = alloc(4096); let b = alloc(32); let vectors = alloc(72);
    pl_builder(b, name, 4096); pl_text(b, path); pl_text(b, ".camera.json"); if load64(b + 24) { return 0; }
    let forward = vectors; let right = vectors + 24; let up = vectors + 48; let i = 0;
    while i < 3 { pb_vset(forward, i, pb_vget(ps_target, i) - pb_vget(ps_eye, i)); i = i + 1; }
    render_normalize(forward); render_cross(right, forward, ps_up); render_normalize(right); render_cross(up, right, forward);
    pl_builder(b, text, 4096); pl_text(b, "{\"schema\":\"puppybot.camera.v1\",\"view\":");
    if ps_camera_mode { pj_text(b, "tcp"); } else { pj_text(b, "orbit"); }
    pl_text(b, ",\"imageRotationDeg\":"); pl_int(b, 180 * (ps_camera_mode && ps_camera_drive_mode));
    pl_text(b, ",\"width\":"); pl_int(b, width); pl_text(b, ",\"height\":"); pl_int(b, height);
    pl_text(b, ",\"frameId\":"); pl_uint(b, frame); pl_text(b, ",\"capturedMs\":"); pl_uint(b, time);
    pl_text(b, ",\"intrinsics\":{\"fx\":"); pl_float(b, ps_number(1732051 * height, 2000000)); pl_text(b, ",\"fy\":"); pl_float(b, ps_number(1732051 * height, 2000000));
    pl_text(b, ",\"cx\":"); pl_float(b, ps_number(width, 2)); pl_text(b, ",\"cy\":"); pl_float(b, ps_number(height, 2));
    pl_text(b, "},\"eyeM\":"); ps_camera_vector(b, ps_eye, 1000, 1); pl_text(b, ",\"right\":"); ps_camera_vector(b, right, 1000000, 1);
    pl_text(b, ",\"down\":"); ps_camera_vector(b, up, 1000000, -1); pl_text(b, ",\"forward\":"); ps_camera_vector(b, forward, 1000000, 1); pl_text(b, "}\n");
    let fd = syscall(2, name, 0x800c1, 384, 0, 0, 0); let ok = fd >= 0 && !load64(b + 24);
    if fd >= 0 { if pl_write(fd, text, load64(b + 8)) || syscall(74, fd, 0, 0, 0, 0, 0) { ok = 0; } syscall(3, fd, 0, 0, 0, 0, 0); }
    syscall(11, text, 4096, 0, 0, 0, 0); syscall(11, name, 4096, 0, 0, 0, 0); syscall(11, b, 32, 0, 0, 0, 0); syscall(11, vectors, 72, 0, 0, 0, 0); return ok;
}
fn ps_capture_at(path, capture_frame, capture_time) {
    let w = gui_pixel_width(load64(ps_device)); let h = gui_pixel_height(load64(ps_device));
    if ps_render_target { w = load64(ps_render_target + 24); h = load64(ps_render_target + 32); }
    let data = alloc(w * h * 3); let args = alloc(88); pb_zero(args, 88);
    render_gl(ps_device, "glPixelStorei", 0x0d05, 1, 0, 0, 0, 0);
    store64(args + 16, w); store64(args + 24, h); store64(args + 32, 0x1907); store64(args + 40, 0x1401); store64(args + 48, data);
    ffi_call_words(gui_gl_cached_proc(load64(ps_device), "glReadPixels"), args);
    let header = alloc(128); let b = alloc(32); pl_builder(b, header, 128); pl_text(b, "P6\n"); pl_int(b, w); pl_char(b, 32); pl_int(b, h); pl_text(b, "\n255\n");
    let fd = syscall(2, path, 0x800c1, 420, 0, 0, 0); if fd < 0 { pl_print(2, "Capture path must be new.\n"); return 0; }
    let length = pl_size(path); let png = length >= 4 && pl_equal(path + length - 4, ".png"); let ok = 1;
    if png { ok = ps_capture_png(fd, data, w, h); }
    else { ok = !pl_write(fd, header, load64(b + 8)); let y = h - 1; while y >= 0 && ok { ok = !pl_write(fd, data + y * w * 3, w * 3); y = y - 1; } }
    if syscall(74, fd, 0, 0, 0, 0, 0) { ok = 0; } syscall(3, fd, 0, 0, 0, 0, 0);
    syscall(11, data, w * h * 3, 0, 0, 0, 0); syscall(11, args, 88, 0, 0, 0, 0); syscall(11, header, 128, 0, 0, 0, 0); syscall(11, b, 32, 0, 0, 0, 0);
    if ok { ok = ps_camera_metadata_at(path, w, h, capture_frame, capture_time); }
    if ok && !ps_render_target && ps_case_index >= 0 && ps_case_camera { ok = ps_brick_metadata(path); }
    if ok && ps_tcp_view_width && !ps_render_target {
        let camera = ps_camera_mode; ps_camera_mode = 2; ps_camera_update(ps_tcp_view_width, ps_tcp_view_height);
        let name = alloc(4096); let builder = alloc(32); pl_builder(builder, name, 4096); pl_text(builder, path); pl_text(builder, ".tcp");
        let frame = ps_total; let time = ps_time;
        if ps_live_enabled && !(ps_case_index >= 0 && ps_case_camera) && ps_live_front >= 0 && ps_live_front_mode == 2 && ps_live_front_episode == ps_episode {
            pb_copy(ps_eye, ps_live_front_pose, 24); pb_copy(ps_target, ps_live_front_pose + 24, 24); pb_copy(ps_up, ps_live_front_pose + 48, 24); frame = ps_live_front_step; time = ps_live_time;
        }
        ok = !load64(builder + 24) && ps_camera_metadata_at(name, ps_tcp_view_width, ps_tcp_view_height, frame, time);
        syscall(11, name, 4096, 0, 0, 0, 0); syscall(11, builder, 32, 0, 0, 0, 0); ps_camera_mode = camera; ps_camera_update(w, h);
    }
    if ok && !ps_render_target && ps_previews { ok = ps_preview_capture(path); }
    return ok;
}
fn ps_capture(path) { return ps_capture_at(path, ps_total, ps_time); }
fn ps_render_close() {
    ps_preview_close();
    if ps_case_menu_mesh { let i = 0; while i < ps_catalog_count + 2 { render_mesh_close(load64(ps_case_menu_mesh + i * 8)); i = i + 1; } }
    if ps_case_status_mesh { render_mesh_close(ps_case_status_mesh); }
    render_mesh_close(ps_label_mesh); render_material_close(ps_label_material);
    if ps_environment_mesh { render_mesh_close(ps_environment_mesh); render_mesh_close(ps_environment_overview); }
    render_mesh_close(ps_mesh); render_mesh_close(ps_cube); render_mesh_close(ps_ball_mesh); render_mesh_close(ps_tyre_mesh); render_material_close(ps_material); render_close(ps_device); gui_quit(); return 0;
}
