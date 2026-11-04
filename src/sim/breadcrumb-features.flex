// Floor-plane registration from TCP RGB and joint-calibrated camera rays.
// The flat floor provides scale; no scene geometry or true pose is read.
import "localization.flex";

global ps_cf_gray = 0;
global ps_cf_candidates = 0;
global ps_cf_pattern = 0;
global ps_cf_points = 0;
global ps_cf_matches = 0;
global ps_cf_count = 0;
global ps_cf_match_count = 0;
global ps_cf_result = 0;
global ps_cf_inliers = 0;
global ps_cf_best = 0;
global ps_cf_second = 0;
global ps_cf_temp = 0;
global ps_cf_camera = 0;
global ps_cf_floor = 0;
global ps_cf_floor_only = 0;

global ps_cf_gate_mm = 65;

fn ps_cf_init() {
    if ps_cf_gray { return 1; }
    ps_cf_gray = alloc(640 * 480); ps_cf_floor = alloc(640 * 480); ps_cf_candidates = alloc(4096 * 24); ps_cf_pattern = alloc(64 * 32); ps_cf_points = alloc(384 * 48);
    ps_cf_matches = alloc(384 * 48); ps_cf_result = alloc(24); ps_cf_temp = alloc(96); ps_cf_camera = alloc(96); let seed = 17; let i = 0;
    while i < 256 { seed = (seed * 1664525 + 1013904223) & 0xffffffff; store64(ps_cf_pattern + i * 8, (seed % 45 - 22) * 1000); i = i + 1; } return 1;
}
fn ps_cf_corner(x, y) {
    let xx = 0; let yy = 0; let xy = 0; let row = -1;
    while row <= 1 { let col = -1;
        while col <= 1 {
            let p = ps_cf_gray + (y + row) * 640 + x + col; let gx = load8(p + 1) - load8(p - 1); let gy = load8(p + 640) - load8(p - 640);
            xx = xx + gx * gx; yy = yy + gy * gy; xy = xy + gx * gy; col = col + 1;
        } row = row + 1;
    }
    return (xx * yy - xy * xy) / (xx + yy + 1);
}
fn ps_cf_intensity(x, y) {
    // Micrometre base-plane coordinates -> bilinear grey sample. Subpixel
    // sampling prevents the thin floor grid from changing descriptor bits
    // simply because a projected point crosses an integer pixel boundary.
    let dx = x - load64(ps_cf_camera); let dy = y - load64(ps_cf_camera + 8); let dz = -load64(ps_cf_camera + 16);
    let depth = (load64(ps_cf_camera + 24) * dx + load64(ps_cf_camera + 32) * dy + load64(ps_cf_camera + 40) * dz) / 1000000;
    if depth < 20000 { return -1; }
    let right = (load64(ps_cf_camera + 48) * dx + load64(ps_cf_camera + 56) * dy + load64(ps_cf_camera + 64) * dz) / 1000000;
    let down = (load64(ps_cf_camera + 72) * dx + load64(ps_cf_camera + 80) * dy + load64(ps_cf_camera + 88) * dz) / 1000000;
    let u = 320000 + 415692 * right / depth; let v = 240000 + 415692 * down / depth;
    if u < 2000 || u > 637000 || v < 2000 || v > 477000 { return -1; }
    let p = ps_cf_gray + v / 1000 * 640 + u / 1000; let a = u % 1000; let b = v % 1000;
    if ps_cf_floor_only && !load8(ps_cf_floor + v / 1000 * 640 + u / 1000) { return -1; }
    return (load8(p) * (1000 - a) * (1000 - b) + load8(p + 1) * a * (1000 - b) + load8(p + 640) * (1000 - a) * b + load8(p + 641) * a * b) / 1000;
}
fn ps_cf_calibrate() {
    ps_cf_init(); ps_local_camera(ps_cf_temp); let c = f64_cos(ps_pose_heading()); let s = f64_sin(ps_pose_heading()); let i = 0;
    while i < 4 {
        let x = load64(ps_cf_temp + i * 24); let y = load64(ps_cf_temp + i * 24 + 8);
        if !i { x = f64_sub(x, ps_pose_x()); y = f64_sub(y, ps_pose_y()); }
        store64(ps_cf_camera + i * 24, f64_to_i64_nearest(f64_mul(f64_add(f64_mul(c, x), f64_mul(s, y)), f64_from_i64(1000000))));
        store64(ps_cf_camera + i * 24 + 8, f64_to_i64_nearest(f64_mul(f64_sub(f64_mul(c, y), f64_mul(s, x)), f64_from_i64(1000000))));
        store64(ps_cf_camera + i * 24 + 16, f64_to_i64_nearest(f64_mul(load64(ps_cf_temp + i * 24 + 16), f64_from_i64(1000000)))); i = i + 1;
    }
    return 1;
}
fn ps_cf_ground(u, v, out) {
    let fx = (u - 320) * 1000; let fy = (v - 240) * 1000; let i = 0;
    while i < 3 {
        store64(out + i * 8, load64(ps_cf_camera + 24 + i * 8) + load64(ps_cf_camera + 48 + i * 8) * fx / 415692 + load64(ps_cf_camera + 72 + i * 8) * fy / 415692); i = i + 1;
    }
    let z = load64(out + 16); if z >= -1 { return 0; } let distance = -load64(ps_cf_camera + 16) * 1000000 / z;
    store64(out, load64(ps_cf_camera) + distance * load64(out) / 1000000); store64(out + 8, load64(ps_cf_camera + 8) + distance * load64(out + 8) / 1000000);
    return load64(out) > 0 && load64(out) < 1200000;
}
fn ps_cf_describe(out, x, y, heading) {
    let co = f64_to_i64_nearest(f64_mul(f64_cos(heading), f64_from_i64(1000000))); let si = f64_to_i64_nearest(f64_mul(f64_sin(heading), f64_from_i64(1000000)));
    let descriptor = 0; let bit = 0;
    while bit < 64 {
        let r = ps_cf_pattern + bit * 32; let ax = load64(r); let ay = load64(r + 8); let bx = load64(r + 16); let by = load64(r + 24);
        let a = ps_cf_intensity(x + (co * ax + si * ay) / 1000000, y + (co * ay - si * ax) / 1000000);
        let b = ps_cf_intensity(x + (co * bx + si * by) / 1000000, y + (co * by - si * bx) / 1000000);
        if a < 0 || b < 0 { return 0; } if a < b { descriptor = descriptor | (1 << bit); } bit = bit + 1;
    }
    store64(out, x); store64(out + 8, y); store64(out + 16, descriptor); return 1;
}
fn ps_cf_extract(rgb, heading, out) {
    ps_cf_init(); let i = 0;
    while i < 640 * 480 {
        let p = rgb + i * 3; let r = load8(p); let g = load8(p + 1); let b = load8(p + 2);
        store8(ps_cf_gray + i, (77 * r + 150 * g + 29 * b) / 256);
        store8(ps_cf_floor + i, r * 100 > g * 108 && g * 100 > b * 108 && r < g * 2 && g < b * 2); i = i + 1;
    }
    let candidates = 0; let by = 174;
    while by < 434 { let bx = 30;
        while bx < 610 {
            let best = 20; let px = 0; let py = 0; let y = by;
            while y < by + 8 { let x = bx;
                while x < bx + 8 {
                    let p = rgb + (y * 640 + x) * 3; let r = load8(p); let g = load8(p + 1); let b = load8(p + 2);
                    // Ignore bright loose bricks, rim patches and the cyan
                    // robot. No simulator object masks or identities enter.
                    if r >= b && r < g * 2 && g < r * 2 && r < b * 4 && b > 15 {
                        let score = ps_cf_corner(x, y); if score > best { best = score; px = x; py = y; }
                    } x = x + 1;
                } y = y + 1;
            }
            if px && candidates < 4096 { let r = ps_cf_candidates + candidates * 24; store64(r, best); store64(r + 8, px); store64(r + 16, py); candidates = candidates + 1; } bx = bx + 8;
        } by = by + 8;
    }
    let count = 0; let selected = 0;
    while selected < candidates && count < 384 {
        let best = 0; let index = -1; i = 0;
        while i < candidates { let score = load64(ps_cf_candidates + i * 24); if score > best { best = score; index = i; } i = i + 1; }
        if index < 0 { selected = candidates; } else {
            let r = ps_cf_candidates + index * 24; let u = load64(r + 8); let v = load64(r + 16); store64(r, 0); let near = 0; i = 0;
            while i < count { let p = out + i * 48; let dx = load64(p + 32) - u; let dy = load64(p + 40) - v; if dx * dx + dy * dy < 25 { near = 1; } i = i + 1; }
            if !near {
                let point = out + count * 48;
                if ps_cf_ground(u, v, ps_cf_temp) && ps_cf_describe(point, load64(ps_cf_temp), load64(ps_cf_temp + 8), heading) {
                    store64(point + 24, best); store64(point + 32, u); store64(point + 40, v); count = count + 1;
                }
            } selected = selected + 1;
        }
    }
    return count;
}
fn ps_cf_popcount(value) {
    value = value - ((value >> 1) & 0x5555555555555555); value = (value & 0x3333333333333333) + ((value >> 2) & 0x3333333333333333);
    value = (value + (value >> 4)) & 0x0f0f0f0f0f0f0f0f; return ((value * 0x0101010101010101) >> 56) & 255;
}
fn ps_cf_pair(current, count, reference, total, pose, prior) {
    ps_cf_match_count = 0; let co = f64_to_i64_nearest(f64_mul(f64_cos(load64(pose + 16)), f64_from_i64(1000000))); let si = f64_to_i64_nearest(f64_mul(f64_sin(load64(pose + 16)), f64_from_i64(1000000)));
    let rx = f64_to_i64_nearest(f64_mul(load64(pose), f64_from_i64(1000000))); let ry = f64_to_i64_nearest(f64_mul(load64(pose + 8), f64_from_i64(1000000))); let i = 0;
    let pc = f64_to_i64_nearest(f64_mul(f64_cos(load64(prior + 16)), f64_from_i64(1000000))); let ps = f64_to_i64_nearest(f64_mul(f64_sin(load64(prior + 16)), f64_from_i64(1000000)));
    let px = f64_to_i64_nearest(f64_mul(load64(prior), f64_from_i64(1000000))); let py = f64_to_i64_nearest(f64_mul(load64(prior + 8), f64_from_i64(1000000))); let gate = ps_cf_gate_mm * 1000;
    while i < count {
        let p = current + i * 48; let first = 65; let second = 65; let index = -1; let j = 0;
        let wx = px + (pc * load64(p) - ps * load64(p + 8)) / 1000000; let wy = py + (ps * load64(p) + pc * load64(p + 8)) / 1000000;
        while j < total {
            let q = reference + j * 48; let dx = rx + (co * load64(q) - si * load64(q + 8)) / 1000000 - wx; let dy = ry + (si * load64(q) + co * load64(q + 8)) / 1000000 - wy;
            if dx * dx + dy * dy < gate * gate {
                let distance = ps_cf_popcount(load64(p + 16) ^ load64(q + 16));
                if distance < first { second = first; first = distance; index = j; } else if distance < second { second = distance; }
            }
            j = j + 1;
        }
        if index >= 0 && first < 24 && first * 10 < second * 8 {
            let q = reference + index * 48; let world_x = rx + (co * load64(q) - si * load64(q + 8)) / 1000000; let world_y = ry + (si * load64(q) + co * load64(q + 8)) / 1000000;
            let match = ps_cf_matches + ps_cf_match_count * 48; store64(match, load64(p)); store64(match + 8, load64(p + 8)); store64(match + 16, world_x); store64(match + 24, world_y); store64(match + 32, i); store64(match + 40, index);
            ps_cf_match_count = ps_cf_match_count + 1;
        } i = i + 1;
    }
    return ps_cf_match_count;
}
fn ps_cf_support(co, si, tx, ty) {
    let count = 0; let i = 0;
    while i < ps_cf_match_count {
        let p = ps_cf_matches + i * 48; let dx = tx + (co * load64(p) - si * load64(p + 8)) / 1000000 - load64(p + 16); let dy = ty + (si * load64(p) + co * load64(p + 8)) / 1000000 - load64(p + 24);
        if dx * dx + dy * dy < 36000000 { count = count + 1; } i = i + 1;
    } return count;
}
fn ps_cf_fit(current, count, reference, total, pose, prior) {
    ps_cf_inliers = 0; ps_cf_best = 0; ps_cf_second = 0;
    if count < 10 || total < 10 || ps_cf_pair(current, count, reference, total, pose, prior) < 10 { return 0; }
    let best_c = 0; let best_s = 0; let best_x = 0; let best_y = 0; let trial = 0; let n = ps_cf_match_count;
    while trial < pb_min(800, n * n) {
        let a = ps_cf_matches + (trial % n) * 48; let b = ps_cf_matches + ((trial / n * 17 + trial * 7 + 1) % n) * 48;
        let px = load64(b) - load64(a); let py = load64(b + 8) - load64(a + 8); let qx = load64(b + 16) - load64(a + 16); let qy = load64(b + 24) - load64(a + 24);
        let pl = f64_sqrt(f64_from_i64(px * px + py * py)); let ql = f64_sqrt(f64_from_i64(qx * qx + qy * qy));
        if f64_gt(pl, f64_from_i64(50000)) && f64_lt(f64_magnitude(f64_sub(pl, ql)), f64_from_i64(6000)) {
            let norm = f64_mul(pl, ql); let c = f64_to_i64_nearest(f64_mul(f64_div(f64_from_i64(px * qx + py * qy), norm), f64_from_i64(1000000))); let s = f64_to_i64_nearest(f64_mul(f64_div(f64_from_i64(px * qy - py * qx), norm), f64_from_i64(1000000)));
            let tx = load64(a + 16) - (c * load64(a) - s * load64(a + 8)) / 1000000; let ty = load64(a + 24) - (s * load64(a) + c * load64(a + 8)) / 1000000;
            let dx = f64_sub(ps_number(tx, 1000000), load64(prior)); let dy = f64_sub(ps_number(ty, 1000000), load64(prior + 8)); let yaw = f64_atan2(f64_from_i64(s), f64_from_i64(c));
            if f64_lt(f64_add(f64_mul(dx, dx), f64_mul(dy, dy)), ps_number(ps_cf_gate_mm * ps_cf_gate_mm, 1000000)) && f64_lt(f64_magnitude(pb_wrap_pi(f64_sub(yaw, load64(prior + 16)))), ps_number(2, 10)) {
                let support = ps_cf_support(c, s, tx, ty);
                if support > ps_cf_best { ps_cf_second = ps_cf_best; ps_cf_best = support; best_c = c; best_s = s; best_x = tx; best_y = ty; }
            }
        } trial = trial + 1;
    }
    if ps_cf_best < 10 { return 0; }
    let px = 0; let py = 0; let qx = 0; let qy = 0; let i = 0; let inliers = 0; let minx = 999999999; let maxx = -999999999; let miny = minx; let maxy = maxx;
    while i < n {
        let p = ps_cf_matches + i * 48; let dx = best_x + (best_c * load64(p) - best_s * load64(p + 8)) / 1000000 - load64(p + 16); let dy = best_y + (best_s * load64(p) + best_c * load64(p + 8)) / 1000000 - load64(p + 24);
        if dx * dx + dy * dy < 36000000 { px = px + load64(p); py = py + load64(p + 8); qx = qx + load64(p + 16); qy = qy + load64(p + 24); inliers = inliers + 1; minx = pb_min(minx, load64(p)); maxx = pb_max(maxx, load64(p)); miny = pb_min(miny, load64(p + 8)); maxy = pb_max(maxy, load64(p + 8)); }
        i = i + 1;
    }
    if maxx - minx < 50000 || maxy - miny < 50000 { return 0; } px = px / inliers; py = py / inliers; qx = qx / inliers; qy = qy / inliers;
    let dot = 0; let cross = 0; i = 0;
    while i < n {
        let p = ps_cf_matches + i * 48; let dx = best_x + (best_c * load64(p) - best_s * load64(p + 8)) / 1000000 - load64(p + 16); let dy = best_y + (best_s * load64(p) + best_c * load64(p + 8)) / 1000000 - load64(p + 24);
        if dx * dx + dy * dy < 36000000 { let x = load64(p) - px; let y = load64(p + 8) - py; let u = load64(p + 16) - qx; let v = load64(p + 24) - qy; dot = dot + x * u + y * v; cross = cross + x * v - y * u; } i = i + 1;
    }
    let angle = f64_atan2(f64_from_i64(cross), f64_from_i64(dot)); let co = f64_cos(angle); let si = f64_sin(angle);
    store64(ps_cf_result, f64_sub(ps_number(qx, 1000000), f64_sub(f64_mul(co, ps_number(px, 1000000)), f64_mul(si, ps_number(py, 1000000)))));
    store64(ps_cf_result + 8, f64_sub(ps_number(qy, 1000000), f64_add(f64_mul(si, ps_number(px, 1000000)), f64_mul(co, ps_number(py, 1000000))))); store64(ps_cf_result + 16, angle);
    ps_cf_inliers = inliers; return 1;
}
