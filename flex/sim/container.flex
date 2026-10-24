// One compound open box: five shapes share mass, inertia and a single pose.
import "layout.flex";
import "../../build/flex/sim/dependencies.flex";

global ps_case_bin_shape = 0;
global ps_bin_frame = 0;
global ps_bin_parts = 0;
global ps_bin_local_point = 0;

fn ps_float(n, d) { return pb_f64_to_f32(ps_number(n, d)); }
fn ps_body_shape(id) {
    let index = id; if ps_case_index >= 0 && id > ps_case_bin_body { index = index + 4; } return ph_shape(ps_physics, index);
}
fn ps_bin_part(i, x, y, z, hx, hy, hz) {
    let p = ps_bin_parts + i * 64; store64(p, x); store64(p + 8, y); store64(p + 16, z); store64(p + 24, hx); store64(p + 32, hy); store64(p + 40, hz); store64(p + 48, f64_mul(hx, f64_mul(hy, hz))); return 0;
}
fn ps_case_add_bin() {
    if !ps_bin_frame { ps_bin_frame = alloc(128); ps_bin_parts = alloc(5 * 64); ps_bin_local_point = alloc(24); }
    let b = ps_case_bin; let t = load64(b + 48); let ht = f64_mul(t, ps_number(1, 2));
    let hx = f64_mul(load64(b + 24), ps_number(1, 2)); let hy = f64_mul(load64(b + 32), ps_number(1, 2)); let hz = f64_mul(load64(b + 40), ps_number(1, 2)); let z = f64_add(t, hz);
    ps_bin_part(0, 0, 0, ht, f64_add(hx, t), f64_add(hy, t), ht);
    ps_bin_part(1, pb_neg(f64_add(hx, ht)), 0, z, ht, f64_add(hy, t), hz);
    ps_bin_part(2, f64_add(hx, ht), 0, z, ht, f64_add(hy, t), hz);
    ps_bin_part(3, 0, pb_neg(f64_add(hy, ht)), z, hx, ht, hz);
    ps_bin_part(4, 0, f64_add(hy, ht), z, hx, ht, hz);
    let volume = 0; let moment = 0; let i = 0;
    while i < 5 { let p = ps_bin_parts + i * 64; volume = f64_add(volume, load64(p + 48)); moment = f64_add(moment, f64_mul(load64(p + 48), load64(p + 16))); i = i + 1; }
    let centre = f64_div(moment, volume); store64(b + 72, centre); let mass = load64(b + 56); let ix = 0; let iy = 0; let iz = 0; i = 0;
    while i < 5 {
        let p = ps_bin_parts + i * 64; let m = f64_mul(mass, f64_div(load64(p + 48), volume)); let x = load64(p); let y = load64(p + 8); let dz = f64_sub(load64(p + 16), centre);
        let xx = f64_mul(load64(p + 24), load64(p + 24)); let yy = f64_mul(load64(p + 32), load64(p + 32)); let zz = f64_mul(load64(p + 40), load64(p + 40));
        ix = f64_add(ix, f64_mul(m, f64_add(f64_mul(f64_add(yy, zz), ps_number(1, 3)), f64_add(f64_mul(y, y), f64_mul(dz, dz)))));
        iy = f64_add(iy, f64_mul(m, f64_add(f64_mul(f64_add(xx, zz), ps_number(1, 3)), f64_add(f64_mul(x, x), f64_mul(dz, dz)))));
        iz = f64_add(iz, f64_mul(m, f64_add(f64_mul(f64_add(xx, yy), ps_number(1, 3)), f64_add(f64_mul(x, x), f64_mul(y, y))))); i = i + 1;
    }
    let kind = 1; if load64(b + 64) { kind = 0; }
    ps_case_bin_body = ph_body_add(ps_physics, kind, pb_f64_to_f32(load64(b)), pb_f64_to_f32(load64(b + 8)), pb_f64_to_f32(f64_add(load64(b + 16), centre)), pb_f64_to_f32(mass), pb_f64_to_f32(ix), pb_f64_to_f32(iy), pb_f64_to_f32(iz));
    ps_case_bin_shape = load64(ps_physics + 16); i = 0;
    while i < 5 {
        let p = ps_bin_parts + i * 64;
        ph_box(ps_physics, ps_case_bin_body, pb_f64_to_f32(load64(p)), pb_f64_to_f32(load64(p + 8)), pb_f64_to_f32(f64_sub(load64(p + 16), centre)), pb_f64_to_f32(load64(p + 24)), pb_f64_to_f32(load64(p + 32)), pb_f64_to_f32(load64(p + 40))); i = i + 1;
    }
    return ps_bin_update();
}
fn ps_bin_update() {
    if ps_case_index < 0 { return 0; } let body = ph_body(ps_physics, ps_case_bin_body); ph_cache_body(body); ps_identity(ps_bin_frame); let col = 0;
    while col < 3 {
        let row = 0; while row < 3 { store64(ps_bin_frame + (col * 4 + row) * 8, pb_f32_to_f64(load64(body + 256 + (col * 3 + row) * 8))); row = row + 1; }
        store64(ps_bin_frame + (12 + col) * 8, f64_sub(pb_f32_to_f64(load64(body + 8 + col * 8)), f64_mul(pb_f32_to_f64(load64(body + 304 + col * 8)), load64(ps_case_bin + 72)))); col = col + 1;
    }
    col = 0; while col < 5 { ph_cache_shape(ps_physics, ph_shape(ps_physics, ps_case_bin_shape + col)); col = col + 1; } return 1;
}
fn ps_bin_to_local(out, point) {
    let col = 0;
    while col < 3 {
        let value = 0; let row = 0;
        while row < 3 { value = f64_add(value, f64_mul(load64(ps_bin_frame + (col * 4 + row) * 8), f64_sub(load64(point + row * 8), load64(ps_bin_frame + (12 + row) * 8)))); row = row + 1; }
        store64(out + col * 8, value); col = col + 1;
    }
    return out;
}
fn ps_bin_settled() {
    if ps_case_index < 0 { return 1; } let b = ph_body(ps_physics, ps_case_bin_body); let speed = 0; let spin = 0; let i = 0;
    while i < 3 { let v = pb_f32_to_f64(load64(b + 64 + i * 8)); let w = pb_f32_to_f64(load64(b + 88 + i * 8)); speed = f64_add(speed, f64_mul(v, v)); spin = f64_add(spin, f64_mul(w, w)); i = i + 1; }
    return f64_le(speed, f64_mul(ps_case_speed, ps_case_speed)) && f64_lt(spin, ps_number(1, 100)) && f64_gt(load64(ps_bin_frame + 80), ps_number(98, 100));
}
fn ps_bin_observation(b) {
    let body = ph_body(ps_physics, ps_case_bin_body); pl_text(b, ",\"container\":{\"body\":"); pl_int(b, ps_case_bin_body); pl_text(b, ",\"dynamic\":"); pj_bool_text(b, load64(body) == 1); pl_text(b, ",\"massKg\":"); pl_float(b, load64(ps_case_bin + 56));
    pl_text(b, ",\"visualMarkers\":"); pj_bool_text(b, load64(ps_case_bin + 80));
    pl_text(b, ",\"position\":["); let i = 0; while i < 3 { if i { pl_char(b, 44); } pl_float(b, load64(ps_bin_frame + (12 + i) * 8)); i = i + 1; }
    pl_text(b, "],\"quaternion\":["); i = 0; while i < 4 { if i { pl_char(b, 44); } pl_float(b, pb_f32_to_f64(load64(body + 32 + i * 8))); i = i + 1; }
    pl_text(b, "],\"velocity\":["); i = 0; while i < 3 { if i { pl_char(b, 44); } pl_float(b, pb_f32_to_f64(load64(body + 64 + i * 8))); i = i + 1; }
    pl_text(b, "],\"angularVelocity\":["); i = 0; while i < 3 { if i { pl_char(b, 44); } pl_float(b, pb_f32_to_f64(load64(body + 88 + i * 8))); i = i + 1; }
    pl_text(b, "],\"settled\":"); pj_bool_text(b, ps_bin_settled()); pl_text(b, ",\"surfaces\":["); i = 0;
    while i < 5 {
        if i { pl_char(b, 44); } let s = ph_shape(ps_physics, ps_case_bin_shape + i); pl_text(b, "{\"body\":"); pl_int(b, load64(s)); pl_text(b, ",\"centre\":["); let k = 0;
        while k < 3 { if k { pl_char(b, 44); } pl_float(b, pb_f32_to_f64(load64(s + 96 + k * 8))); k = k + 1; } pl_text(b, "]}"); i = i + 1;
    }
    return pl_text(b, "]}");
}
