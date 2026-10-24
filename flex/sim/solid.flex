// Explicit static-world queries also cover pairs skipped by the impulse solver
// (kinematic arm/gripper versus fixed container). Model parts use visual OBBs.
import "gripper.flex";

global ps_solid_shape = 0;
global ps_solid_scratch = 0;
global ps_solid_saved = 0;
global ps_solid_next = 0;
global ps_solid_point = 0;
global ps_solid_hit = -1;
global ps_solid_part = -1;
global ps_arm_blocked = 0;
global ps_arm_hit = -1;
global ps_arm_part = -1;

fn ps_solid_init() {
    if !ps_solid_shape { ps_solid_shape = alloc(256); ps_solid_scratch = alloc(16384); ps_solid_saved = alloc(256); ps_solid_next = alloc(256); ps_solid_point = alloc(24); }
    ps_arm_blocked = 0; ps_arm_hit = -1; ps_arm_part = -1; return 0;
}
fn ps_solid_test(part, x, y, heading) {
    let a = ps_solid_shape; let angle = f64_sub(heading, ps_heading); let c = f64_cos(angle); let s = f64_sin(angle);
    let dx = f64_sub(pb_f32_to_f64(load64(a + 96)), ps_x); let dy = f64_sub(pb_f32_to_f64(load64(a + 104)), ps_y);
    store64(a + 96, pb_f64_to_f32(f64_add(x, f64_sub(f64_mul(c, dx), f64_mul(s, dy)))));
    store64(a + 104, pb_f64_to_f32(f64_add(y, f64_add(f64_mul(s, dx), f64_mul(c, dy))))); let col = 0;
    while col < 3 {
        let r = a + 120 + col * 24; let rx = pb_f32_to_f64(load64(r)); let ry = pb_f32_to_f64(load64(r + 8));
        store64(r, pb_f64_to_f32(f64_sub(f64_mul(c, rx), f64_mul(s, ry)))); store64(r + 8, pb_f64_to_f32(f64_add(f64_mul(s, rx), f64_mul(c, ry)))); col = col + 1;
    }
    let k = 0;
    while k < 3 {
        let extent = ph_dot(ph_abs(load64(a + 120 + k * 8)), ph_abs(load64(a + 144 + k * 8)), ph_abs(load64(a + 168 + k * 8)), load64(a + 72), load64(a + 80), load64(a + 88));
        store64(a + 192 + k * 8, ph_sub(load64(a + 96 + k * 8), extent)); store64(a + 216 + k * 8, ph_add(load64(a + 96 + k * 8), extent)); k = k + 1;
    }
    let id = 1;
    while id < ps_wheel_shape {
        let b = ph_shape(ps_physics, id); let body = load64(b);
        if !load64(ph_body(ps_physics, body)) || (ps_vehicle_planning && ps_case_index >= 0 && body == ps_case_bin_body) { let overlap = 1; k = 0;
            while k < 3 {
                if ph_lt(load64(a + 216 + k * 8), load64(b + 192 + k * 8)) || ph_lt(load64(b + 216 + k * 8), load64(a + 192 + k * 8)) { overlap = 0; } k = k + 1;
            }
            if overlap && ph_sat(a, b, ps_solid_scratch) {
                ps_solid_hit = body; ps_solid_part = part; return 0;
            }
        }
        id = id + 1;
    }
    return 1;
}
fn ps_solid_box(m, centre, half) {
    let a = ps_solid_shape; ps_point(ps_solid_point, m, centre); let k = 0;
    while k < 3 {
        store64(a + 72 + k * 8, pb_f64_to_f32(load64(half + k * 8))); store64(a + 96 + k * 8, pb_f64_to_f32(load64(ps_solid_point + k * 8))); let row = 0;
        while row < 3 { store64(a + 120 + (k * 3 + row) * 8, pb_f64_to_f32(load64(m + (k * 4 + row) * 8))); row = row + 1; } k = k + 1;
    }
    return 0;
}
fn ps_solid_free(x, y, heading) {
    if !ps_solid_shape { return 1; } let index = 0; ps_solid_hit = -1; ps_solid_part = -1;
    while index < ps_arm_collider_count {
        let r = ps_arm_colliders + index * 56; ps_solid_box(ps_world_matrices + load64(r) * 128, r + 8, r + 32);
        if !ps_solid_test(index + 3, x, y, heading) { return 0; } index = index + 1;
    }
    index = 0;
    while index < 3 {
        let a = ps_solid_shape; let shape = ph_shape(ps_physics, 5 + index); let k = 0;
        while k < 3 {
            store64(a + 72 + k * 8, load64(shape + 72 + k * 8)); store64(a + 96 + k * 8, pb_f64_to_f32(load64(ps_gripper_targets + index * 24 + k * 8))); let row = 0;
            while row < 3 { store64(a + 120 + (k * 3 + row) * 8, pb_f64_to_f32(load64(ps_gripper_frame + (k * 4 + row) * 8))); row = row + 1; } k = k + 1;
        }
        if !ps_solid_test(index, x, y, heading) { return 0; } index = index + 1;
    }
    return 1;
}
fn ps_solid_step() {
    pb_copy(ps_solid_saved, ps_plant + 128, 256); let gap = ps_gripper_gap; gs_step(ps_plant); pb_copy(ps_solid_next, ps_plant + 128, 256);
    let next_gap = gap; if !ps_gripper_held { next_gap = gap + pb_clamp(ps_gripper_goal - gap, -1000, 1000); }
    let travel = 0; let i = 0;
    while i < 4 { travel = travel + pb_abs(pb_mod(load64(ps_solid_next + 16 + i * 64) - load64(ps_solid_saved + 16 + i * 64) + 2048, 4096) - 2048) * 1000; i = i + 1; }
    if !travel && gap == next_gap { return 1; }
    // A 0.5 m reach bound and <= 1 tick of summed interpolation make the maximum
    // summed joint arc < 1 mm; fingers also advance by at most 0.5 mm/sample.
    let count = travel / 1000 + pb_abs(next_gap - gap) / 500 + 1; let sample = 1; ps_arm_blocked = 0; ps_model_fraction = 1;
    while sample <= count {
        i = 0;
        while i < 4 {
            let start = load64(ps_solid_saved + 16 + i * 64); let delta = pb_mod(load64(ps_solid_next + 16 + i * 64) - start + 2048, 4096) - 2048;
            let position = pb_mod(start * 1000 + delta * 1000 * sample / count, 4096000);
            store64(ps_plant + 128 + i * 64, position); store64(ps_plant + 144 + i * 64, position / 1000); i = i + 1;
        }
        ps_gripper_gap = gap + (next_gap - gap) * sample / count;
        ps_model_update(ps_robot, ps_plant, ps_x, ps_y, ps_heading, ps_wheel); ps_gripper_frame_update(ps_robot, ps_plant);
        if !ps_solid_free(ps_x, ps_y, ps_heading) { ps_arm_blocked = 1; ps_arm_hit = ps_solid_hit; ps_arm_part = ps_solid_part; sample = count; } sample = sample + 1;
    }
    ps_model_fraction = 0;
    if ps_arm_blocked {
        pb_copy(ps_plant + 128, ps_solid_saved, 256); ps_gripper_gap = gap; ps_gripper_goal = gap; i = 0;
        while i < 4 {
            let j = ps_plant + 128 + i * 64; store64(j + 8, 0); store64(ps_bus + load64(j + 24) * 48 + 16, load64(j + 16)); i = i + 1;
        }
        ps_task_cancel("robot motion blocked by a fixed obstacle"); pb_arm_stop(ps_robot, ps_time);
    } else { pb_copy(ps_plant + 128, ps_solid_next, 256); ps_gripper_gap = next_gap; ps_arm_hit = -1; ps_arm_part = -1; }
    ps_model_update(ps_robot, ps_plant, ps_x, ps_y, ps_heading, ps_wheel); ps_gripper_frame_update(ps_robot, ps_plant); return !ps_arm_blocked;
}
fn ps_solid_observation(b) {
    pl_text(b, ",\"collision\":{\"armBlocked\":"); pj_bool_text(b, ps_arm_blocked); pl_text(b, ",\"body\":"); pl_int(b, ps_arm_hit); pl_text(b, ",\"part\":"); pl_int(b, ps_arm_part);
    pl_text(b, ",\"armProxies\":"); pl_int(b, ps_arm_collider_count); pl_text(b, "}"); return 0;
}
