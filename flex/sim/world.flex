import "environment.flex";

global ps_physics = 0;
global ps_x = 0;
global ps_y = 0;
global ps_heading = 0;
global ps_wheel = 0;
global ps_blocked = 0;

fn ps_case_add_object(index) {
    let r = ps_case_objects + index * 256; let x = pb_f64_to_f32(load64(r + 72)); let y = pb_f64_to_f32(load64(r + 80)); let z = pb_f64_to_f32(load64(r + 88));
    let mass = pb_f64_to_f32(load64(r + 128)); let hx = pb_f64_to_f32(load64(r + 96)); let hy = pb_f64_to_f32(load64(r + 104)); let hz = pb_f64_to_f32(load64(r + 112)); let id = 0;
    if load64(r + 64) { id = ph_sphere_body(ps_physics, 1, x, y, z, mass, hx); } else { id = ph_box_body(ps_physics, 1, x, y, z, mass, hx, hy, hz); }
    if !load64(r + 64) { let half = f64_mul(load64(r + 200), ps_number(1, 2)); ph_body_quaternion(ps_physics, id, 0, 0, pb_f64_to_f32(f64_sin(half)), pb_f64_to_f32(f64_cos(half))); }
    store64(r + 184, id); store64(r + 192, 0); store64(r + 208, 0); return id;
}
fn ps_world_init() {
    ps_x = 0; ps_y = 0; ps_heading = 0; ps_wheel = 0; ps_blocked = 0;
    let bodies = 64; let shapes = 96;
    if ps_environment { ps_x = load64(ps_environment_start); ps_y = load64(ps_environment_start + 8); ps_heading = load64(ps_environment_start + 16); bodies = bodies + ps_environment_count; shapes = shapes + ps_environment_count; }
    if !ps_physics { ps_physics = ph_world(bodies, shapes, 2048, 1); }
    else { ph_world_init(ps_physics, bodies, shapes, 2048, 1); }
    ph_settings(ps_physics, ps_float(2, 1000), 12, ps_float(7, 10), ps_float(1, 5));
    // Preserve floor/obstacle/object/chassis/gripper IDs. Compound container,
    // tyres and physical arm proxies are appended after the loose objects.
    if ps_environment {
        let x = f64_mul(f64_add(load64(ps_environment + 64), load64(ps_environment + 80)), ps_number(1, 2));
        let y = f64_mul(f64_add(load64(ps_environment + 72), load64(ps_environment + 88)), ps_number(1, 2));
        let hx = f64_mul(f64_sub(load64(ps_environment + 80), load64(ps_environment + 64)), ps_number(1, 2));
        let hy = f64_mul(f64_sub(load64(ps_environment + 88), load64(ps_environment + 72)), ps_number(1, 2));
        ph_box_body(ps_physics, 0, pb_f64_to_f32(x), pb_f64_to_f32(y), ps_float(-25, 1000), 0, pb_f64_to_f32(hx), pb_f64_to_f32(hy), ps_float(25, 1000));
        // Keep legacy body IDs 1 and 2, out of the usable scene. Every loaded
        // collider then retains the existing body-to-shape mapping after bin.
        ph_box_body(ps_physics, 0, ps_float(-99, 1), 0, ps_float(-2, 1), 0, ps_float(1, 100), ps_float(1, 100), ps_float(1, 100));
        ph_box_body(ps_physics, 0, ps_float(-99, 1), ps_float(1, 1), ps_float(-2, 1), 0, ps_float(1, 100), ps_float(1, 100), ps_float(1, 100));
    } else {
    ph_box_body(ps_physics, 0, 0, 0, ps_float(-25, 1000), 0, ps_float(2, 1), ps_float(2, 1), ps_float(25, 1000));
    ph_box_body(ps_physics, 0, ps_float(65, 100), ps_float(-35, 100), ps_float(10, 100), 0, ps_float(12, 100), ps_float(12, 100), ps_float(10, 100));
    ph_box_body(ps_physics, 0, ps_float(-55, 100), ps_float(45, 100), ps_float(15, 100), 0, ps_float(10, 100), ps_float(18, 100), ps_float(15, 100));
    }
    if ps_case_index >= 0 { ps_case_add_object(0); } else { ph_sphere_body(ps_physics, 1, ps_float(38, 100), ps_float(8, 100), ps_float(45, 100), ps_float(1, 10), ps_float(35, 1000)); }
    ph_box_body(ps_physics, 2, 0, 0, ps_float(9, 100), 0, ps_float(14, 100), ps_float(11, 100), ps_float(6, 100));
    if ps_environment { ph_vset(ph_body(ps_physics, 4) + 8, pb_f64_to_f32(ps_x), pb_f64_to_f32(ps_y), ps_float(9, 100)); ph_body_quaternion(ps_physics, 4, 0, 0, pb_f64_to_f32(f64_sin(f64_mul(ps_heading, ps_number(1, 2)))), pb_f64_to_f32(f64_cos(f64_mul(ps_heading, ps_number(1, 2))))); }
    ph_box_body(ps_physics, 2, 0, 0, ps_float(4, 10), 0, ps_float(55, 1000), ps_float(15, 1000), ps_float(6, 1000));
    ph_box_body(ps_physics, 2, 0, 0, ps_float(4, 10), 0, ps_float(5, 1000), ps_float(15, 1000), pb_f64_to_f32(f64_mul(ps_finger_length(), ps_number(1, 2))));
    ph_box_body(ps_physics, 2, 0, 0, ps_float(4, 10), 0, ps_float(5, 1000), ps_float(15, 1000), pb_f64_to_f32(f64_mul(ps_finger_length(), ps_number(1, 2))));
    if ps_case_index >= 0 {
        let i = 1; while i < ps_case_count { ps_case_add_object(i); i = i + 1; } ps_case_add_bin(); i = 0;
        // Before the vehicle proxies so the existing swept chassis, wheel
        // and arm queries include these fixed props as real obstacles.
        while i < ps_case_scenery_count {
            let r = ps_case_scenery + i * 128;
            let id = ph_box_body(ps_physics, 0, pb_f64_to_f32(load64(r + 48)), pb_f64_to_f32(load64(r + 56)), pb_f64_to_f32(load64(r + 64)), 0, pb_f64_to_f32(load64(r + 72)), pb_f64_to_f32(load64(r + 80)), pb_f64_to_f32(load64(r + 88)));
            store64(r + 120, id); i = i + 1;
        }
    } ps_environment_create(); ps_vehicle_create(); ps_arm_proxy_create(); return 0;
}
fn ps_drive_step(robot) {
    let d = pb_robot_drive(robot); let distance = ps_number(pb_vget(d, 6) + pb_vget(d, 7), 20000);
    let steer = pb_radians(f64_from_i64(pb_vget(d, 8) - pb_vget(d, 3)));
    let turn = pb_neg(f64_mul(f64_div(distance, ps_number(18, 100)), f64_div(f64_sin(steer), f64_cos(steer))));
    let heading = pb_wrap_pi(f64_add(ps_heading, turn));
    let x = f64_add(ps_x, f64_mul(distance, f64_cos(heading))); let y = f64_add(ps_y, f64_mul(distance, f64_sin(heading)));
    ps_vehicle_refresh();
    if !distance { ps_blocked = 0; ps_vehicle_hit = -1; ps_vehicle_part = -1; ps_vehicle_fault = 0; return 0; }
    ps_blocked = !ps_vehicle_path(x, y, turn);
    if !ps_blocked { ps_x = x; ps_y = y; ps_heading = heading; ps_wheel = pb_wrap_pi(f64_add(ps_wheel, f64_div(distance, ps_number(325, 10000)))); }
    return 0;
}
fn ps_proxy_target(id, x, y, z, substep) {
    let b = ph_body(ps_physics, id);
    // Reach the next 20 ms pose over ten solver steps, preserving contact speed.
    if !substep {
        store64(b + 64, ph_div(ph_sub(pb_f64_to_f32(x), load64(b + 8)), ps_float(20, 1000)));
        store64(b + 72, ph_div(ph_sub(pb_f64_to_f32(y), load64(b + 16)), ps_float(20, 1000)));
        store64(b + 80, ph_div(ph_sub(pb_f64_to_f32(z), load64(b + 24)), ps_float(20, 1000)));
    }
    // The shared solver integrates kinematic velocity itself.
    return 0;
}
