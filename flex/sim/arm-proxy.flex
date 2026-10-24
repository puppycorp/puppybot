// Physical arm visual proxies let contacts push a dynamic container.
import "solid.flex";

global ps_arm_proxy_body = 0;
global ps_arm_proxy_quat = 0;
global ps_arm_proxy_point = 0;

fn ps_arm_proxy_create() {
    if !ps_arm_proxy_quat { ps_arm_proxy_quat = alloc(32); ps_arm_proxy_point = alloc(24); }
    ps_arm_proxy_body = load64(ps_physics + 8); let i = 0;
    while i < ps_arm_collider_count {
        let r = ps_arm_colliders + i * 56; ph_box_body(ps_physics, 2, 0, 0, ps_float(1, 1), 0, pb_f64_to_f32(load64(r + 32)), pb_f64_to_f32(load64(r + 40)), pb_f64_to_f32(load64(r + 48))); i = i + 1;
    }
    return 0;
}
fn ps_arm_matrix_quat(m) {
    let trace = f64_add(load64(m), f64_add(load64(m + 40), load64(m + 80))); let q = ps_arm_proxy_quat;
    if f64_gt(trace, 0) {
        let s = f64_mul(f64_sqrt(f64_add(trace, PB_ONE)), f64_from_i64(2));
        store64(q, pb_f64_to_f32(f64_div(f64_sub(load64(m + 48), load64(m + 72)), s)));
        store64(q + 8, pb_f64_to_f32(f64_div(f64_sub(load64(m + 64), load64(m + 16)), s)));
        store64(q + 16, pb_f64_to_f32(f64_div(f64_sub(load64(m + 8), load64(m + 32)), s))); store64(q + 24, pb_f64_to_f32(f64_mul(s, ps_number(1, 4))));
    } else {
        let axis = 0; if f64_gt(load64(m + 40), load64(m)) { axis = 1; } if f64_gt(load64(m + 80), load64(m + axis * 40)) { axis = 2; }
        let u = (axis + 1) % 3; let v = (axis + 2) % 3;
        let s = f64_mul(f64_sqrt(f64_sub(f64_add(PB_ONE, load64(m + axis * 40)), f64_add(load64(m + u * 40), load64(m + v * 40)))), f64_from_i64(2));
        store64(q + axis * 8, pb_f64_to_f32(f64_mul(s, ps_number(1, 4))));
        store64(q + u * 8, pb_f64_to_f32(f64_div(f64_add(load64(m + (u * 4 + axis) * 8), load64(m + (axis * 4 + u) * 8)), s)));
        store64(q + v * 8, pb_f64_to_f32(f64_div(f64_add(load64(m + (v * 4 + axis) * 8), load64(m + (axis * 4 + v) * 8)), s)));
        store64(q + 24, pb_f64_to_f32(f64_div(f64_sub(load64(m + (u * 4 + v) * 8), load64(m + (v * 4 + u) * 8)), s)));
    }
    return q;
}
fn ps_arm_proxy_update(initial) {
    let i = 0;
    while i < ps_arm_collider_count {
        let r = ps_arm_colliders + i * 56; let m = ps_world_matrices + load64(r) * 128; let id = ps_arm_proxy_body + i; ps_point(ps_arm_proxy_point, m, r + 8); let p = ps_arm_proxy_point;
        if initial { let k = 0; while k < 3 { store64(ph_body(ps_physics, id) + 8 + k * 8, pb_f64_to_f32(load64(p + k * 8))); k = k + 1; } }
        else { ps_proxy_target(id, load64(p), load64(p + 8), load64(p + 16), 0); }
        let q = ps_arm_matrix_quat(m); ph_body_quaternion(ps_physics, id, load64(q), load64(q + 8), load64(q + 16), load64(q + 24)); i = i + 1;
    }
    return 0;
}
