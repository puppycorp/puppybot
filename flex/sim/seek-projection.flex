// Simulation-only association between a colour detection and a physical prop.
// Camera vectors are eye, forward, right and down, in that order.
fn ps_seek_projection_match(detection, camera, point) {
    let depth = 0; let horizontal = 0; let vertical = 0; let i = 0;
    while i < 3 {
        let d = f64_sub(load64(point + i * 8), load64(camera + i * 8));
        depth = f64_add(depth, f64_mul(d, load64(camera + 24 + i * 8)));
        horizontal = f64_add(horizontal, f64_mul(d, load64(camera + 48 + i * 8)));
        vertical = f64_add(vertical, f64_mul(d, load64(camera + 72 + i * 8))); i = i + 1;
    }
    if !f64_gt(depth, 0) { return 0; }
    let focal = f64_div(f64_from_i64(1732051 * 480), f64_from_i64(2000000));
    let x = f64_add(f64_from_i64(320), f64_mul(focal, f64_div(horizontal, depth)));
    let y = f64_add(f64_from_i64(240), f64_mul(focal, f64_div(vertical, depth)));
    return f64_ge(x, f64_from_i64(load64(detection) - 12)) && f64_le(x, f64_from_i64(load64(detection + 16) + 12)) && f64_ge(y, f64_from_i64(load64(detection + 8) - 12)) && f64_le(y, f64_from_i64(load64(detection + 24) + 12));
}
