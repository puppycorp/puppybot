// Joint records and packed vertices come from the owned URDF/glTF export.
import "../core/arm.flex";
import "../host/linux.flex";

global ps_asset = 0;
global ps_groups = 0;
global ps_vertices = 0;
global ps_world_matrices = 0;
global ps_matrix_scratch = 0;
global ps_root = 0;
global ps_rotation = 0;
global ps_tcp = 0;
global ps_model_fraction = 0;
global ps_arm_colliders = 0;
global ps_arm_collider_count = 0;

fn ps_number(n, d) { return f64_div(f64_from_i64(n), f64_from_i64(d)); }
fn ps_joint_angle(robot, plant, index) {
    let j = pb_joint(robot, index); let p = plant + 128 + index * 64; let tick = load64(p + 16); let angle = pb_tick_angle(j, tick);
    if ps_model_fraction { angle = f64_add(angle, f64_div(f64_mul(ps_number(load64(p) - tick * 1000, 1000), f64_div(PB_TAU, f64_from_i64(4096))), pb_j(j, PB_J_SIGN))); }
    return angle;
}
fn ps_identity(m) {
    let i = 0; while i < 16 { store64(m + i * 8, 0); if i % 5 == 0 { store64(m + i * 8, PB_ONE); } i = i + 1; } return m;
}
fn ps_multiply(out, a, b) {
    let col = 0;
    while col < 4 {
        let row = 0;
        while row < 4 {
            let value = 0; let k = 0;
            while k < 4 { value = f64_add(value, f64_mul(pb_vget(a, k * 4 + row), pb_vget(b, col * 4 + k))); k = k + 1; }
            pb_vset(ps_matrix_scratch, col * 4 + row, value); row = row + 1;
        }
        col = col + 1;
    }
    pb_copy(out, ps_matrix_scratch, 128); return out;
}
fn ps_axis_rotation(out, axis, angle) {
    let x = load64(axis); let y = load64(axis + 8); let z = load64(axis + 16);
    let c = f64_cos(angle); let s = f64_sin(angle); let t = f64_sub(PB_ONE, c); ps_identity(out);
    pb_vset(out, 0, f64_add(f64_mul(t, f64_mul(x, x)), c));
    pb_vset(out, 1, f64_add(f64_mul(t, f64_mul(x, y)), f64_mul(s, z)));
    pb_vset(out, 2, f64_sub(f64_mul(t, f64_mul(x, z)), f64_mul(s, y)));
    pb_vset(out, 4, f64_sub(f64_mul(t, f64_mul(x, y)), f64_mul(s, z)));
    pb_vset(out, 5, f64_add(f64_mul(t, f64_mul(y, y)), c));
    pb_vset(out, 6, f64_add(f64_mul(t, f64_mul(y, z)), f64_mul(s, x)));
    pb_vset(out, 8, f64_add(f64_mul(t, f64_mul(x, z)), f64_mul(s, y)));
    pb_vset(out, 9, f64_sub(f64_mul(t, f64_mul(y, z)), f64_mul(s, x)));
    pb_vset(out, 10, f64_add(f64_mul(t, f64_mul(z, z)), c)); return out;
}
fn ps_point(out, m, p) {
    let row = 0;
    while row < 3 {
        let value = pb_vget(m, 12 + row); let k = 0;
        while k < 3 { value = f64_add(value, f64_mul(pb_vget(m, k * 4 + row), pb_vget(p, k))); k = k + 1; }
        pb_vset(out, row, value); row = row + 1;
    }
    return out;
}
fn ps_model_load(path) {
    let fd = syscall(2, path, 0x80000, 0, 0, 0, 0); if fd < 0 { return 0; }
    let size = syscall(8, fd, 0, 2, 0, 0, 0); if size < 64 || size > 268435456 { syscall(3, fd, 0, 0, 0, 0, 0); return 0; }
    ps_asset = syscall(9, 0, size, 1, 2, fd, 0); syscall(3, fd, 0, 0, 0, 0, 0);
    if ps_asset < 0 { return 0; }
    if load64(ps_asset) != load64("PBSIM002") { return 0; }
    ps_groups = load64(ps_asset + 8); ps_vertices = load64(ps_asset + 16);
    if ps_groups < 1 || ps_groups > 256 || ps_vertices < 3 || ps_vertices > 6000000 || load64(ps_asset + 24) < 0 || load64(ps_asset + 24) >= ps_groups || load64(ps_asset + 40) != 36 { return 0; }
    let offset = 64 + (ps_groups + 1) * 256 + ps_vertices * 36; ps_arm_collider_count = load64(ps_asset + 48);
    if ps_arm_collider_count < 1 || ps_arm_collider_count > 512 || load64(ps_asset + 56) != offset || size != offset + ps_arm_collider_count * 56 { return 0; }
    ps_arm_colliders = ps_asset + offset;
    let index = 0;
    while index < ps_arm_collider_count {
        let r = ps_arm_colliders + index * 56; let group = load64(r); let k = 0;
        if group < 0 || group >= ps_groups { return 0; }
        while k < 6 {
            let value = load64(r + 8 + k * 8); if !f64_is_finite(value) || f64_gt(f64_magnitude(value), PB_ONE) || (k >= 3 && !f64_gt(value, 0)) { return 0; } k = k + 1;
        }
        index = index + 1;
    }
    let i = 0;
    while i < ps_groups {
        let r = ps_asset + 64 + i * 256;
        if load64(r) >= i || load64(r) < -1 || (i && load64(r) < 0) || load64(r + 8) < -1 || load64(r + 8) > 5 { return 0; }
        if load64(r + 184) < 0 || load64(r + 192) < 0 || load64(r + 184) + load64(r + 192) > ps_vertices { return 0; }
        i = i + 1;
    }
    let metadata = ps_asset + 64 + ps_groups * 256;
    if load64(metadata + 72) != load64("PBSWH001") || load64(metadata + 80) != 4 { return 0; }
    i = 0;
    while i < 4 {
        let r = metadata + 88 + i * 32; let group = load64(r);
        if group < 0 || group >= ps_groups || load64(ps_asset + 64 + group * 256 + 8) != 4 { return 0; }
        if !f64_is_finite(load64(r + 8)) || !f64_is_finite(load64(r + 16)) || !f64_is_finite(load64(r + 24)) || !f64_gt(load64(r + 16), 0) || !f64_gt(load64(r + 24), 0) || f64_gt(load64(r + 16), ps_number(1, 10)) || f64_gt(load64(r + 24), ps_number(1, 10)) { return 0; }
        i = i + 1;
    }
    ps_world_matrices = alloc(ps_groups * 128); ps_matrix_scratch = alloc(128); ps_root = alloc(128); ps_rotation = alloc(128); ps_tcp = alloc(24); return 1;
}
fn ps_model_evaluate(robot, plant, x, y, heading, wheel, matrices, root, rotation, tcp) {
    ps_identity(root); pb_vset(root, 0, f64_cos(heading)); pb_vset(root, 1, f64_sin(heading));
    pb_vset(root, 4, pb_neg(f64_sin(heading))); pb_vset(root, 5, f64_cos(heading));
    pb_vset(root, 12, x); pb_vset(root, 13, y); pb_vset(root, 14, ps_number(32, 1000));
    let i = 0;
    while i < ps_groups {
        let r = ps_asset + 64 + i * 256; let out = matrices + i * 128; let parent = load64(r);
        let p = root; if parent >= 0 { p = matrices + parent * 128; }
        ps_multiply(out, p, r + 16); let control = load64(r + 8); let angle = 0;
        if control >= 0 && control < 4 { angle = ps_joint_angle(robot, plant, control); }
        if control == 4 { angle = wheel; }
        if control == 5 { let d = pb_robot_drive(robot); angle = pb_radians(f64_from_i64(pb_vget(d, 8) - pb_vget(d, 3))); }
        angle = f64_add(f64_mul(angle, load64(r + 168)), load64(r + 176));
        ps_axis_rotation(rotation, r + 144, angle); ps_multiply(out, out, rotation); i = i + 1;
    }
    return ps_point(tcp, matrices + load64(ps_asset + 24) * 128, ps_asset + 64 + ps_groups * 256);
}
fn ps_model_update(robot, plant, x, y, heading, wheel) {
    return ps_model_evaluate(robot, plant, x, y, heading, wheel, ps_world_matrices, ps_root, ps_rotation, ps_tcp);
}
