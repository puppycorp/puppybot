// Kinematic vehicle with physical tyres and a swept narrow-phase drive guard.
import "world.flex";

global ps_wheel_body = 0;
global ps_wheel_shape = 0;
global ps_vehicle_planning = 0;
global ps_wheel_local = 0;
global ps_vehicle_query = 0;
global ps_vehicle_hit = -1;
global ps_vehicle_part = -1;
global ps_vehicle_fault = 0;

fn ps_wheel_record(i) { return ps_asset + 64 + ps_groups * 256 + 88 + i * 32; }
fn ps_vehicle_create() {
    ps_vehicle_hit = -1; ps_vehicle_part = -1; ps_vehicle_fault = 0;
    if !ps_wheel_local { ps_wheel_local = alloc(4 * 48); ps_vehicle_query = ph_world(2, 2, 32, 0); }
    else { ph_world_init(ps_vehicle_query, 2, 2, 32, 0); }
    ph_box_body(ps_vehicle_query, 2, 0, 0, 0, 0, ps_float(1, 1), ps_float(1, 1), ps_float(1, 1));
    ph_box_body(ps_vehicle_query, 1, 0, 0, 0, ps_float(1, 1), ps_float(1, 1), ps_float(1, 1), ps_float(1, 1));
    ps_wheel_body = load64(ps_physics + 8); ps_wheel_shape = load64(ps_physics + 16); let i = 0;
    while i < 4 {
        let r = ps_wheel_record(i); ph_cylinder_body(ps_physics, 2, 0, 0, ps_float(1, 10), 0, pb_f64_to_f32(load64(r + 16)), pb_f64_to_f32(load64(r + 24))); i = i + 1;
    }
    return 0;
}
fn ps_vehicle_refresh() {
    let c = f64_cos(ps_heading); let s = f64_sin(ps_heading); let i = 0;
    while i < 4 {
        let r = ps_wheel_record(i); let g = ps_asset + 64 + load64(r) * 256; let m = ps_world_matrices + load64(r) * 128; let local = ps_wheel_local + i * 48; let k = 0;
        while k < 3 {
            let axis = 0; let j = 0;
            while j < 3 { axis = f64_add(axis, f64_mul(load64(m + (j * 4 + k) * 8), load64(g + 144 + j * 8))); j = j + 1; }
            store64(local + 24 + k * 8, axis); store64(local + k * 8, f64_add(load64(m + (12 + k) * 8), f64_mul(axis, load64(r + 8)))); k = k + 1;
        }
        let x = f64_sub(load64(local), ps_x); let y = f64_sub(load64(local + 8), ps_y);
        store64(local, f64_add(f64_mul(c, x), f64_mul(s, y))); store64(local + 8, f64_sub(f64_mul(c, y), f64_mul(s, x)));
        x = load64(local + 24); y = load64(local + 32);
        store64(local + 24, f64_add(f64_mul(c, x), f64_mul(s, y))); store64(local + 32, f64_sub(f64_mul(c, y), f64_mul(s, x))); i = i + 1;
    }
    i = 1;
    while i < ps_wheel_body {
        ph_cache_body(ph_body(ps_physics, i)); i = i + 1;
    }
    i = 1; while i < ps_wheel_shape { ph_cache_shape(ps_physics, ph_shape(ps_physics, i)); i = i + 1; }
    return 0;
}
fn ps_vehicle_pose(w, id, part, x, y, heading) {
    let b = ph_body(w, id); let c = f64_cos(heading); let s = f64_sin(heading);
    if !part {
        ph_vset(b + 8, pb_f64_to_f32(x), pb_f64_to_f32(y), ps_float(9, 100));
        ph_body_quaternion(w, id, 0, 0, pb_f64_to_f32(f64_sin(f64_mul(heading, ps_number(1, 2)))), pb_f64_to_f32(f64_cos(f64_mul(heading, ps_number(1, 2))))); return 0;
    }
    let p = ps_wheel_local + (part - 1) * 48;
    let px = f64_add(x, f64_sub(f64_mul(c, load64(p)), f64_mul(s, load64(p + 8))));
    let py = f64_add(y, f64_add(f64_mul(s, load64(p)), f64_mul(c, load64(p + 8))));
    ph_vset(b + 8, pb_f64_to_f32(px), pb_f64_to_f32(py), pb_f64_to_f32(load64(p + 16)));
    let ax = f64_sub(f64_mul(c, load64(p + 24)), f64_mul(s, load64(p + 32)));
    let ay = f64_add(f64_mul(s, load64(p + 24)), f64_mul(c, load64(p + 32)));
    // Quaternion taking cylinder Z to the wheel axle; all four axles are horizontal.
    ph_body_quaternion(w, id, pb_f64_to_f32(pb_neg(ay)), pb_f64_to_f32(ax), 0, pb_f64_to_f32(f64_add(PB_ONE, load64(p + 40)))); return 0;
}
fn ps_vehicle_free(x, y, heading) {
    if !ps_environment_inside(x, y) { ps_vehicle_hit = 0; ps_vehicle_part = 0; return 0; }
    let w = ps_vehicle_query; let a = ph_shape(w, 0); let b = ph_shape(w, 1); let part = 0;
    while part < 5 {
        let source = 4; if part { source = ps_wheel_body + part - 1; }
        pb_copy(a, ps_body_shape(source), 256); store64(a, 0); ps_vehicle_pose(w, 0, part, x, y, heading); ph_cache_shape(w, a);
        let i = 1;
        while i < ps_wheel_shape {
            let obstacle = ph_shape(ps_physics, i); let body = load64(obstacle);
            // Floor and the rover's own gripper are excluded. A held object is
            // still an obstacle if it intersects the chassis or a tyre.
            if (body < 4 || body >= 8) && !(ps_case_index >= 0 && body == ps_case_bin_body && load64(ph_body(ps_physics, body)) == 1 && !ps_vehicle_planning && !ps_house_enabled()) {
                // Apply the solver's exact cached AABB rejection before copying
                // either record into the query world. Touching bounds still pass.
                let overlap = 1; let k = 0;
                while k < 3 {
                    if ph_lt(load64(a + 216 + k * 8), load64(obstacle + 192 + k * 8)) || ph_lt(load64(obstacle + 216 + k * 8), load64(a + 192 + k * 8)) { overlap = 0; } k = k + 1;
                }
                if overlap {
                    pb_copy(ph_body(w, 1) + 8, ph_body(ps_physics, body) + 8, 56);
                    pb_copy(b, obstacle, 256); store64(b, 1); store64(w + 24, 0); store64(w + 192, 0);
                    ph_collide_pair(w, a, b, ph_scratch(w));
                    if load64(w + 24) || load64(w + 192) { ps_vehicle_hit = body; ps_vehicle_part = part; ps_vehicle_fault = load64(w + 192); return 0; }
                }
            }
            i = i + 1;
        }
        part = part + 1;
    }
    if !ps_solid_free(x, y, heading) { ps_vehicle_hit = ps_solid_hit; ps_vehicle_part = ps_solid_part + 5; return 0; }
    return 1;
}
fn ps_vehicle_sweep(from_x, from_y, from_heading, x, y, turn) {
    // Bound each sample's translation plus the arc of the outermost corner
    // to 1 mm. This covers forward, reverse and steering at maximum speed.
    let dx = f64_sub(x, from_x); let dy = f64_sub(y, from_y);
    let length = f64_add(f64_sqrt(f64_add(f64_mul(dx, dx), f64_mul(dy, dy))), f64_mul(f64_magnitude(turn), ps_number(20, 100)));
    let count = f64_to_i64_nearest(f64_mul(length, f64_from_i64(1000))) + 1;
    ps_vehicle_hit = -1; ps_vehicle_part = -1; ps_vehicle_fault = 0;
    let i = 1;
    while i <= count {
        let t = ps_number(i, count);
        if !ps_vehicle_free(f64_add(from_x, f64_mul(dx, t)), f64_add(from_y, f64_mul(dy, t)), f64_add(from_heading, f64_mul(turn, t))) { return 0; }
        i = i + 1;
    }
    return 1;
}
fn ps_vehicle_path(x, y, turn) { return ps_vehicle_sweep(ps_x, ps_y, ps_heading, x, y, turn); }
fn ps_vehicle_primitive_ticks(x, y, heading, action, ticks) {
    // Validate the teacher's executable first primitive at physics tick rate.
    // The search lattice's four-tick endpoint samples can miss a narrow box
    // rim between samples. Keep the same one-millimetre swept execution guard.
    let distance = ps_number(load64(action + 8) * load64(action + 112), 10000);
    let angle = pb_radians(f64_from_i64(load64(action) * 45 / 100));
    let turn = pb_neg(f64_mul(f64_div(distance, ps_number(18, 100)), f64_div(f64_sin(angle), f64_cos(angle))));
    let tick = 0; while tick < ticks {
        let next_heading = pb_wrap_pi(f64_add(heading, turn)); let next_x = f64_add(x, f64_mul(distance, f64_cos(next_heading))); let next_y = f64_add(y, f64_mul(distance, f64_sin(next_heading)));
        if !ps_vehicle_sweep(x, y, heading, next_x, next_y, turn) { return 0; }
        x = next_x; y = next_y; heading = next_heading; tick = tick + 1;
    } return 1;
}
fn ps_vehicle_primitive_free(x, y, heading, action) { return ps_vehicle_primitive_ticks(x, y, heading, action, 20); }
fn ps_vehicle_plan(x, y, turn) {
    ps_vehicle_planning = 1; let clear = ps_vehicle_path(x, y, turn); ps_vehicle_planning = 0; return clear;
}
fn ps_vehicle_init() {
    ps_vehicle_refresh(); let i = 0;
    while i < 4 { ps_vehicle_pose(ps_physics, ps_wheel_body + i, i + 1, ps_x, ps_y, ps_heading); ph_cache_shape(ps_physics, ps_body_shape(ps_wheel_body + i)); i = i + 1; } return 0;
}
fn ps_vehicle_proxies(substep) {
    if substep { return 0; } let i = 0;
    while i < 4 {
        ps_vehicle_pose(ps_vehicle_query, 0, i + 1, ps_x, ps_y, ps_heading); let b = ph_body(ps_vehicle_query, 0);
        ps_proxy_target(ps_wheel_body + i, pb_f32_to_f64(load64(b + 8)), pb_f32_to_f64(load64(b + 16)), pb_f32_to_f64(load64(b + 24)), 0);
        ph_body_quaternion(ps_physics, ps_wheel_body + i, load64(b + 32), load64(b + 40), load64(b + 48), load64(b + 56)); i = i + 1;
    }
    return 0;
}
fn ps_vehicle_observation(b) {
    pl_text(b, ",\"vehicle\":{\"driveModel\":\"swept-kinematic-v1\",\"blockedBody\":"); pl_int(b, ps_vehicle_hit);
    pl_text(b, ",\"blockedPart\":"); pl_int(b, ps_vehicle_part); pl_text(b, ",\"queryFault\":"); pl_int(b, ps_vehicle_fault); pl_text(b, ",\"wheels\":["); let i = 0;
    while i < 4 {
        if i { pl_char(b, 44); } let id = ps_wheel_body + i; let r = ps_wheel_record(i); let body = ph_body(ps_physics, id);
        pl_text(b, "{\"body\":"); pl_int(b, id); pl_text(b, ",\"radius\":"); pl_float(b, load64(r + 16)); pl_text(b, ",\"halfWidth\":"); pl_float(b, load64(r + 24)); pl_text(b, ",\"centre\":["); let k = 0;
        while k < 3 { if k { pl_char(b, 44); } pl_float(b, pb_f32_to_f64(load64(body + 8 + k * 8))); k = k + 1; }
        pl_text(b, "],\"axis\":["); k = 0; while k < 3 { if k { pl_char(b, 44); } pl_float(b, pb_f32_to_f64(load64(body + 304 + k * 8))); k = k + 1; } pl_text(b, "]}"); i = i + 1;
    }
    pl_text(b, "]}"); return 0;
}
