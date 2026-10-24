// TCP-camera box pose from rim corner and midpoint patches. Three corners
// initialize the rectangle; two current patches can track it at close range.
// Inputs are RGB, calibration and dimensions/height, never simulated box poses.
import "brick-vision.flex";

global ps_dock_markers = 0;
global ps_dock_count = 0;
global ps_dock_used = 0;
global ps_dock_frame = 0;
global ps_dock_calibration = 0;
global ps_dock_corners = 0;
global ps_dock_valid = 0;
global ps_dock_seen = -1;
global ps_dock_stable = 0;
global ps_dock_samples = 0;
global ps_dock_yaw = 0;
global ps_dock_release_frame = -1;
global ps_dock_hint = 0;
global ps_dock_hint_seen = -1;

fn ps_dock_reset() {
    ps_dock_valid = 0; ps_dock_used = 0; ps_dock_seen = -1; ps_dock_stable = 0; ps_dock_samples = 0; ps_dock_count = 0; ps_dock_yaw = 0; ps_dock_release_frame = -1;
    ps_dock_hint_seen = -1; if !ps_dock_hint { ps_dock_hint = alloc(24); }
    if !ps_dock_frame { ps_dock_frame = alloc(128); ps_dock_markers = alloc(16 * 96); ps_dock_calibration = alloc(96); ps_dock_corners = alloc(32); }
    ps_identity(ps_dock_frame); pb_zero(ps_dock_calibration, 96); return 0;
}
fn ps_dock_component(start) {
    let head = 0; let tail = ps_brick_enqueue(start, 1, 0); let sumx = 0; let sumy = 0; let x1 = 640; let y1 = 480; let x2 = 0; let y2 = 0;
    while head < tail {
        let pixel = load64(ps_brick_queue + head * 8); let x = pixel % 640; let y = pixel / 640;
        sumx = sumx + x; sumy = sumy + y; x1 = pb_min(x1, x); y1 = pb_min(y1, y); x2 = pb_max(x2, x); y2 = pb_max(y2, y);
        if x { tail = ps_brick_enqueue(pixel - 1, 1, tail); } if x < 639 { tail = ps_brick_enqueue(pixel + 1, 1, tail); }
        if y { tail = ps_brick_enqueue(pixel - 640, 1, tail); } if y < 479 { tail = ps_brick_enqueue(pixel + 640, 1, tail); } head = head + 1;
    }
    if tail < 4 || tail > 1500 || x1 == 0 || y1 == 0 || x2 == 639 || y2 == 479 || ps_dock_count >= 16 { return 0; }
    let r = ps_dock_markers + ps_dock_count * 96; let u = f64_add(ps_number(sumx, tail), ps_number(1, 2)); let v = f64_add(ps_number(sumy, tail), ps_number(1, 2));
    let plane = f64_add(f64_add(load64(ps_case_bin + 40), load64(ps_case_bin + 48)), ps_number(1, 1000));
    if !ps_rgb_ray(r + 32, u, v, plane) { return 0; }
    // The house uses an estimated frame and a movable box. A valid RGB rim
    // must not disappear when odometry moves it across a global Y boundary.
    if !ps_house_enabled() && f64_gt(load64(r + 40), ps_number(-6, 100)) { return 0; }
    let scale = f64_div(f64_sub(load64(ps_brick_pose + 16), plane), ps_number(1732051 * 480, 2000000)); let span = f64_mul(f64_from_i64(pb_max(x2 - x1 + 1, y2 - y1 + 1)), scale);
    if f64_lt(span, ps_number(1, 1000)) || f64_gt(span, ps_number(2, 100)) { return 0; }
    store64(r, x1); store64(r + 8, y1); store64(r + 16, x2 + 1); store64(r + 24, y2 + 1); store64(r + 56, u); store64(r + 64, v); store64(r + 72, tail); ps_dock_count = ps_dock_count + 1; return 1;
}
fn ps_dock_pose(x, y, co, si, used) {
    let dx = f64_sub(x, load64(ps_dock_frame + 96)); let dy = f64_sub(y, load64(ps_dock_frame + 104)); let rotation = f64_add(f64_mul(co, load64(ps_dock_frame)), f64_mul(si, load64(ps_dock_frame + 8)));
    if ps_dock_seen >= 0 && ps_total - ps_dock_seen <= 30 && f64_lt(f64_add(f64_mul(dx, dx), f64_mul(dy, dy)), ps_number(9, 1000000)) && f64_gt(rotation, ps_number(9995, 10000)) { ps_dock_stable = ps_dock_stable + 1; }
    else { ps_dock_stable = 1; }
    ps_identity(ps_dock_frame); store64(ps_dock_frame, co); store64(ps_dock_frame + 8, si); store64(ps_dock_frame + 32, pb_neg(si)); store64(ps_dock_frame + 40, co); store64(ps_dock_frame + 96, x); store64(ps_dock_frame + 104, y);
    ps_dock_used = used; ps_dock_yaw = f64_atan2(si, co); ps_dock_seen = ps_total; ps_dock_valid = 1; return 1;
}
fn ps_dock_fit() {
    let width = f64_add(load64(ps_case_bin + 24), load64(ps_case_bin + 48)); let depth = f64_add(load64(ps_case_bin + 32), load64(ps_case_bin + 48));
    let best = f64_from_i64(10); let best_a = -1; let best_b = -1; let best_c = -1; let best_d = -1; let a = 0;
    while a < ps_dock_count {
        let pa = ps_dock_markers + a * 96 + 32; let b = 0;
        while b < ps_dock_count {
            let pb = ps_dock_markers + b * 96 + 32; let ux = f64_sub(load64(pb), load64(pa)); let uy = f64_sub(load64(pb + 8), load64(pa + 8)); let ul = f64_sqrt(f64_add(f64_mul(ux, ux), f64_mul(uy, uy)));
            if b != a && f64_lt(f64_magnitude(f64_sub(ul, width)), ps_number(8, 1000)) {
                let c = 0;
                while c < ps_dock_count {
                    let pc = ps_dock_markers + c * 96 + 32; let vx = f64_sub(load64(pc), load64(pa)); let vy = f64_sub(load64(pc + 8), load64(pa + 8)); let vl = f64_sqrt(f64_add(f64_mul(vx, vx), f64_mul(vy, vy)));
                    let dot = f64_add(f64_mul(ux, vx), f64_mul(uy, vy)); let cross = f64_sub(f64_mul(ux, vy), f64_mul(uy, vx));
                    if c != a && c != b && f64_gt(f64_magnitude(cross), 0) && f64_lt(f64_magnitude(dot), ps_number(2, 1000)) && f64_lt(f64_magnitude(f64_sub(vl, depth)), ps_number(8, 1000)) {
                        let fourth = -1; let closest = ps_number(1, 10000); let d = 0;
                        while d < ps_dock_count {
                            let pd = ps_dock_markers + d * 96 + 32; let dx = f64_sub(load64(pd), f64_add(load64(pb), vx)); let dy = f64_sub(load64(pd + 8), f64_add(load64(pb + 8), vy)); let error = f64_add(f64_mul(dx, dx), f64_mul(dy, dy));
                            if d != a && d != b && d != c && f64_lt(error, closest) { closest = error; fourth = d; } d = d + 1;
                        }
                        let error = f64_add(f64_magnitude(f64_sub(ul, width)), f64_add(f64_magnitude(f64_sub(vl, depth)), f64_magnitude(dot)));
                        if fourth < 0 { error = f64_add(error, ps_number(1, 10)); }
                        if f64_lt(error, best) { best = error; best_a = a; best_b = b; best_c = c; best_d = fourth; }
                    }
                    c = c + 1;
                }
            }
            b = b + 1;
        }
        a = a + 1;
    }
    if best_a < 0 { return 0; }
    store64(ps_dock_corners, best_a); store64(ps_dock_corners + 8, best_b); store64(ps_dock_corners + 16, best_c); store64(ps_dock_corners + 24, best_d);
    let pa = ps_dock_markers + best_a * 96 + 32; let pb = ps_dock_markers + best_b * 96 + 32; let pc = ps_dock_markers + best_c * 96 + 32;
    let x = f64_mul(f64_add(load64(pb), load64(pc)), ps_number(1, 2)); let y = f64_mul(f64_add(load64(pb + 8), load64(pc + 8)), ps_number(1, 2));
    let ux = f64_sub(load64(pb), load64(pa)); let uy = f64_sub(load64(pb + 8), load64(pa + 8));
    if best_d >= 0 {
        let pd = ps_dock_markers + best_d * 96 + 32; x = f64_mul(f64_add(f64_add(load64(pa), load64(pb)), f64_add(load64(pc), load64(pd))), ps_number(1, 4));
        y = f64_mul(f64_add(f64_add(load64(pa + 8), load64(pb + 8)), f64_add(load64(pc + 8), load64(pd + 8))), ps_number(1, 4));
        ux = f64_mul(f64_add(ux, f64_sub(load64(pd), load64(pc))), ps_number(1, 2)); uy = f64_mul(f64_add(uy, f64_sub(load64(pd + 8), load64(pc + 8))), ps_number(1, 2));
    }
    // The unmarked rectangle is symmetric through 180 degrees. Choose its
    // positive-X width axis consistently, regardless of which corner is hidden.
    if f64_lt(ux, 0) { ux = pb_neg(ux); uy = pb_neg(uy); }
    let length = f64_sqrt(f64_add(f64_mul(ux, ux), f64_mul(uy, uy))); let co = f64_div(ux, length); let si = f64_div(uy, length);
    return ps_dock_pose(x, y, co, si, 3 + (best_d >= 0));
}
fn ps_dock_corner_x(index) {
    if index >= 6 { return 0; }
    let x = f64_mul(f64_add(load64(ps_case_bin + 24), load64(ps_case_bin + 48)), ps_number(1, 2)); if !(index % 2) { x = pb_neg(x); } return x;
}
fn ps_dock_corner_y(index) {
    if index == 4 || index == 5 { return 0; }
    let y = f64_mul(f64_add(load64(ps_case_bin + 32), load64(ps_case_bin + 48)), ps_number(1, 2)); if index < 2 || index == 6 { y = pb_neg(y); } return y;
}
fn ps_dock_template() {
    // Five visible corner/midpoint patches can identify the eight-patch rim
    // even when the gripper hides an entire corner row. The centre midpoint
    // distinguishes a rim edge from the middle row; no box pose is consulted.
    if ps_dock_count < 5 { return 0; }
    let width = f64_add(load64(ps_case_bin + 24), load64(ps_case_bin + 48)); let depth = f64_add(load64(ps_case_bin + 32), load64(ps_case_bin + 48));
    let best_count = 0; let best_error = PB_ONE; let best_x = 0; let best_y = 0; let best_c = 0; let best_s = 0; let a = 0;
    while a < ps_dock_count {
        let pa = ps_dock_markers + a * 96 + 32; let b = a + 1;
        while b < ps_dock_count {
            let pb = ps_dock_markers + b * 96 + 32; let ux = f64_sub(load64(pb), load64(pa)); let uy = f64_sub(load64(pb + 8), load64(pa + 8)); let length = f64_sqrt(f64_add(f64_mul(ux, ux), f64_mul(uy, uy)));
            if f64_lt(f64_magnitude(f64_sub(length, width)), ps_number(8, 1000)) {
                if f64_lt(ux, 0) { ux = pb_neg(ux); uy = pb_neg(uy); }
                let co = f64_div(ux, length); let si = f64_div(uy, length); let row = -1;
                while row <= 1 {
                    let offset = f64_mul(f64_from_i64(row), f64_mul(depth, ps_number(1, 2)));
                    let x = f64_add(f64_mul(f64_add(load64(pa), load64(pb)), ps_number(1, 2)), f64_mul(si, offset));
                    let y = f64_sub(f64_mul(f64_add(load64(pa + 8), load64(pb + 8)), ps_number(1, 2)), f64_mul(co, offset));
                    let used = 0; let count = 0; let error = 0; let i = 0;
                    while i < ps_dock_count {
                        let p = ps_dock_markers + i * 96 + 32; let k = 0; let match = -1; let closest = ps_number(64, 1000000);
                        while k < 8 {
                            let lx = ps_dock_corner_x(k); let ly = ps_dock_corner_y(k);
                            let dx = f64_sub(load64(p), f64_add(x, f64_sub(f64_mul(co, lx), f64_mul(si, ly))));
                            let dy = f64_sub(load64(p + 8), f64_add(y, f64_add(f64_mul(si, lx), f64_mul(co, ly)))); let d = f64_add(f64_mul(dx, dx), f64_mul(dy, dy));
                            if !(used & (1 << k)) && f64_lt(d, closest) { match = k; closest = d; } k = k + 1;
                        }
                        if match >= 0 { used = used | (1 << match); count = count + 1; error = f64_add(error, closest); } i = i + 1;
                    }
                    if count >= 5 && (used & 192) && (count > best_count || (count == best_count && f64_lt(error, best_error))) { best_count = count; best_error = error; best_x = x; best_y = y; best_c = co; best_s = si; }
                    row = row + 1;
                }
            } b = b + 1;
        } a = a + 1;
    }
    if best_count < 5 { return 0; }
    let corner = 0;
    while corner < 4 {
        let lx = ps_dock_corner_x(corner); let ly = ps_dock_corner_y(corner); let closest = ps_number(64, 1000000); let match = -1; let i = 0;
        let x = f64_add(best_x, f64_sub(f64_mul(best_c, lx), f64_mul(best_s, ly))); let y = f64_add(best_y, f64_add(f64_mul(best_s, lx), f64_mul(best_c, ly)));
        while i < ps_dock_count {
            let p = ps_dock_markers + i * 96 + 32; let dx = f64_sub(load64(p), x); let dy = f64_sub(load64(p + 8), y); let d = f64_add(f64_mul(dx, dx), f64_mul(dy, dy));
            if f64_lt(d, closest) { closest = d; match = i; } i = i + 1;
        }
        store64(ps_dock_corners + corner * 8, match); corner = corner + 1;
    }
    return ps_dock_pose(best_x, best_y, best_c, best_s, best_count);
}
fn ps_dock_track() {
    // At the lower release pose, the wrist view may contain only two rim
    // corners. Associate them with the box previously learned from RGB, then
    // solve a new translation AND yaw from the current two rays. One corner
    // or a stale remembered pose can never authorize release.
    if ps_dock_seen < 0 || ps_total - ps_dock_seen > 1000 { return 0; }
    let i = 0; let used = 0;
    while i < ps_dock_count {
        let r = ps_dock_markers + i * 96; let best = ps_number(4, 10000); let match = -1; let k = 0;
        while k < 8 {
            let x = ps_dock_corner_x(k); let y = ps_dock_corner_y(k);
            let px = f64_add(load64(ps_dock_frame + 96), f64_sub(f64_mul(load64(ps_dock_frame), x), f64_mul(load64(ps_dock_frame + 8), y)));
            let py = f64_add(load64(ps_dock_frame + 104), f64_add(f64_mul(load64(ps_dock_frame + 8), x), f64_mul(load64(ps_dock_frame), y)));
            let dx = f64_sub(load64(r + 32), px); let dy = f64_sub(load64(r + 40), py); let d = f64_add(f64_mul(dx, dx), f64_mul(dy, dy));
            if !(used & (1 << k)) && f64_lt(d, best) { best = d; match = k; } k = k + 1;
        }
        store64(r + 80, match); if match >= 0 { used = used | (1 << match); } i = i + 1;
    }
    let first = -1; let second = -1; let longest = 0; i = 0;
    while i < ps_dock_count {
        let a = ps_dock_markers + i * 96; let j = i + 1;
        while j < ps_dock_count {
            let b = ps_dock_markers + j * 96; let dx = f64_sub(load64(b + 32), load64(a + 32)); let dy = f64_sub(load64(b + 40), load64(a + 40)); let length = f64_add(f64_mul(dx, dx), f64_mul(dy, dy));
            if load64(a + 80) >= 0 && load64(b + 80) >= 0 && f64_gt(length, longest) { first = i; second = j; longest = length; } j = j + 1;
        }
        i = i + 1;
    }
    if first < 0 || f64_lt(longest, ps_number(1, 100)) { return 0; }
    let a = ps_dock_markers + first * 96; let b = ps_dock_markers + second * 96;
    let ax = ps_dock_corner_x(load64(a + 80)); let ay = ps_dock_corner_y(load64(a + 80)); let bx = ps_dock_corner_x(load64(b + 80)); let by = ps_dock_corner_y(load64(b + 80));
    let lx = f64_sub(bx, ax); let ly = f64_sub(by, ay); let wx = f64_sub(load64(b + 32), load64(a + 32)); let wy = f64_sub(load64(b + 40), load64(a + 40));
    let length = f64_sqrt(longest); let expected = f64_sqrt(f64_add(f64_mul(lx, lx), f64_mul(ly, ly)));
    if f64_gt(f64_magnitude(f64_sub(length, expected)), ps_number(8, 1000)) { return 0; }
    let denominator = f64_mul(length, expected); let co = f64_div(f64_add(f64_mul(wx, lx), f64_mul(wy, ly)), denominator); let si = f64_div(f64_sub(f64_mul(wy, lx), f64_mul(wx, ly)), denominator);
    let x = f64_mul(f64_sub(f64_add(load64(a + 32), load64(b + 32)), f64_sub(f64_mul(co, f64_add(ax, bx)), f64_mul(si, f64_add(ay, by)))), ps_number(1, 2));
    let y = f64_mul(f64_sub(f64_add(load64(a + 40), load64(b + 40)), f64_add(f64_mul(si, f64_add(ax, bx)), f64_mul(co, f64_add(ay, by)))), ps_number(1, 2));
    store64(ps_dock_corners, first); store64(ps_dock_corners + 8, second); store64(ps_dock_corners + 16, -1); store64(ps_dock_corners + 24, -1);
    return ps_dock_pose(x, y, co, si, 2);
}
fn ps_dock_detect() {
    ps_dock_count = 0; ps_dock_valid = 0; let i = 0;
    while i < 640 * 480 {
        let p = ps_brick_rgb + i * 3; let r = load8(p); let g = load8(p + 1); let b = load8(p + 2);
        store8(ps_brick_mask + i, r > 70 && b > 60 && r > g * 4 && b > g * 4 && b * 10 > r * 7); i = i + 1;
    }
    i = 0; while i < 640 * 480 { if load8(ps_brick_mask + i) { ps_dock_component(i); } i = i + 1; }
    pb_copy(ps_dock_calibration, ps_brick_pose, 96); if ps_dock_fit() { return 1; } if ps_house_enabled() && ps_dock_template() { return 1; } return ps_dock_track();
}
fn ps_dock_mark() {
    render_gl(ps_device, "glBindFramebuffer", 0x8d40, load64(ps_brick_sensor + 16), 0, 0, 0, 0); render_gl(ps_device, "glViewport", 0, 0, 640, 480, 0, 0);
    render_gl(ps_device, "glEnable", 0x0c11, 0, 0, 0, 0, 0); let i = 0;
    while i < ps_dock_count { let r = ps_dock_markers + i * 96; let x = load64(r) - 3; let y = 480 - load64(r + 24) - 3; let w = load64(r + 16) - load64(r) + 6; let h = load64(r + 24) - load64(r + 8) + 6;
        ps_panel_clear(x, y, w, 2, 100, 90, 20); ps_panel_clear(x, y + h - 2, w, 2, 100, 90, 20); ps_panel_clear(x, y, 2, h, 100, 90, 20); ps_panel_clear(x + w - 2, y, 2, h, 100, 90, 20); i = i + 1;
    }
    render_gl(ps_device, "glDisable", 0x0c11, 0, 0, 0, 0, 0); let text = "BOX NOT SEEN - HOLDING BRICK"; if ps_house_enabled() && !ps_gripper_held { text = "LOCATING HOME BOX"; } if ps_dock_valid { text = "BOX - RIM MARKERS"; }
    ps_brick_text = ps_text_upload(ps_brick_text, text); ps_text_draw(ps_brick_text, 640, 480, 12, 12); ps_brick_caption = ps_text_upload(ps_brick_caption, "TCP BOX - LAST OBSERVATION"); return 1;
}
fn ps_dock_attention(found) {
    if found { pb_copy(ps_dock_hint, ps_dock_frame + 96, 24); ps_dock_hint_seen = ps_total; }
    else if ps_house_enabled() && ps_dock_count >= 2 {
        // Partial RGB patches are attention cues only. They cannot update a
        // box pose, its freshness or the observations required for release.
        let x = 0; let y = 0; let i = 0;
        while i < ps_dock_count { let r = ps_dock_markers + i * 96; x = f64_add(x, load64(r + 32)); y = f64_add(y, load64(r + 40)); i = i + 1; }
        store64(ps_dock_hint, f64_div(x, f64_from_i64(ps_dock_count))); store64(ps_dock_hint + 8, f64_div(y, f64_from_i64(ps_dock_count))); store64(ps_dock_hint + 16, 0); ps_dock_hint_seen = ps_total;
    }
    return found;
}
fn ps_dock_sample() {
    ps_dock_samples = ps_dock_samples + 1;
    if !ps_rgb_sample() { ps_dock_valid = 0; return 0; }
    let found = ps_dock_detect(); if !found { ps_dock_stable = 0; }
    ps_dock_attention(found); ps_dock_mark(); return found;
}
fn ps_dock_fresh() { return ps_dock_valid && ps_dock_seen >= 0 && ps_total - ps_dock_seen <= 10; }
fn ps_dock_hint_fresh() { return ps_dock_hint_seen >= 0 && ps_total - ps_dock_hint_seen <= 50; }
fn ps_dock_observation(b) {
    pl_text(b, ",\"dockVision\":{\"source\":\"camera-rim-markers-v1\",\"valid\":"); pj_bool_text(b, ps_dock_fresh()); pl_text(b, ",\"samples\":"); pl_int(b, ps_dock_samples); pl_text(b, ",\"frameId\":"); pl_int(b, ps_dock_seen);
    pl_text(b, ",\"stableObservations\":"); pl_int(b, ps_dock_stable); pl_text(b, ",\"releaseFrameId\":"); pl_int(b, ps_dock_release_frame);
    pl_text(b, ",\"camera\":\"tcp\",\"visibleCorners\":"); pl_int(b, ps_dock_used);
    pl_text(b, ",\"attention\":{\"source\":\"rgb-rim-patches\",\"fresh\":"); pj_bool_text(b, ps_dock_hint_fresh()); pl_text(b, ",\"frameId\":"); pl_int(b, ps_dock_hint_seen);
    pl_text(b, ",\"positionM\":["); let attention_i = 0; while attention_i < 3 { if attention_i { pl_char(b, 44); } pl_float(b, load64(ps_dock_hint + attention_i * 8)); attention_i = attention_i + 1; } pl_text(b, "]}");
    pl_text(b, ",\"positionM\":["); let i = 0; while i < 3 { if i { pl_char(b, 44); } pl_float(b, load64(ps_dock_frame + 96 + i * 8)); i = i + 1; }
    pl_text(b, "],\"yawRad\":"); pl_float(b, ps_dock_yaw); pl_text(b, ",\"calibration\":["); i = 0;
    while i < 12 { if i { pl_char(b, 44); } pl_float(b, load64(ps_dock_calibration + i * 8)); i = i + 1; }
    pl_text(b, "],\"corners\":["); i = 0; while i < 4 { if i { pl_char(b, 44); } pl_int(b, load64(ps_dock_corners + i * 8)); i = i + 1; }
    pl_text(b, "],\"markers\":["); i = 0;
    while i < ps_dock_count { if i { pl_char(b, 44); } let r = ps_dock_markers + i * 96; pl_text(b, "{\"pixel\":["); pl_float(b, load64(r + 56)); pl_char(b, 44); pl_float(b, load64(r + 64));
        pl_text(b, "],\"positionM\":["); let k = 0; while k < 3 { if k { pl_char(b, 44); } pl_float(b, load64(r + 32 + k * 8)); k = k + 1; } pl_text(b, "]}"); i = i + 1;
    }
    return pl_text(b, "]}");
}
