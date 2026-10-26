import "vehicle.flex";

global ps_gripper_body = 3;
global ps_gripper_frame = 0;
global ps_gripper_targets = 0;
global ps_gripper_local = 0;
global ps_gripper_quat = 0;
global ps_gripper_gap = 90000;
global ps_gripper_goal = 90000;
global ps_gripper_held = 0;
global ps_gripper_contacts = 0;
global ps_gripper_witnesses = 0;
global ps_gripper_grasps = 0;
global ps_gripper_releases = 0;
global ps_gripper_capture_height = 0;
global ps_gripper_max_height = 0;
global ps_gripper_auto = 0;

fn ps_gripper_release() {
    if ps_gripper_held {
        store64(ph_joint(ps_physics, 0) + 16, 0); ps_gripper_held = 0; ps_gripper_releases = ps_gripper_releases + 1;
    }
    return 0;
}
fn ps_gripper_command(open) {
    ps_gripper_goal = 0;
    if open { ps_gripper_goal = 90000; ps_gripper_release(); }
    return 0;
}
fn ps_gripper_matrix(m, tcp, heading, robot, plant) {
    let yaw = f64_add(f64_add(heading, load64(ps_asset + 64 + ps_groups * 256 + 64)), pb_geometric_yaw(ps_joint_angle(robot, plant, 0)));
    let pitch = ps_gripper_pitch(robot, plant);
    let cy = f64_cos(yaw); let sy = f64_sin(yaw); let cp = f64_cos(pitch); let sp = f64_sin(pitch); ps_identity(m);
    // Local X is jaw travel, local Z is finger length. Mount the palm flat
    // against the TCP plate, with fingers continuing straight out of it.
    pb_vset(m, 0, pb_neg(sy)); pb_vset(m, 1, cy); pb_vset(m, 2, 0);
    pb_vset(m, 4, f64_mul(cy, cp)); pb_vset(m, 5, f64_mul(sy, cp)); pb_vset(m, 6, sp);
    pb_vset(m, 8, f64_mul(cy, sp)); pb_vset(m, 9, f64_mul(sy, sp)); pb_vset(m, 10, pb_neg(cp));
    pb_vset(m, 12, load64(tcp)); pb_vset(m, 13, load64(tcp + 8)); pb_vset(m, 14, load64(tcp + 16)); return yaw;
}
fn ps_gripper_frame_update(robot, plant) {
    let m = ps_gripper_frame; let yaw = ps_gripper_matrix(m, ps_tcp, ps_heading, robot, plant); let pitch = ps_gripper_pitch(robot, plant);
    let a = f64_mul(f64_add(yaw, PB_HALF_PI), ps_number(1, 2)); let b = f64_mul(f64_sub(PB_PI, pitch), ps_number(1, 2));
    store64(ps_gripper_quat, pb_f64_to_f32(f64_mul(f64_cos(a), f64_sin(b))));
    store64(ps_gripper_quat + 8, pb_f64_to_f32(f64_mul(f64_sin(a), f64_sin(b))));
    store64(ps_gripper_quat + 16, pb_f64_to_f32(f64_mul(f64_sin(a), f64_cos(b))));
    store64(ps_gripper_quat + 24, pb_f64_to_f32(f64_mul(f64_cos(a), f64_cos(b))));
    let i = 0;
    while i < 3 {
        pb_zero(ps_gripper_local, 24);
        if !i { pb_vset(ps_gripper_local, 2, ps_number(-6, 1000)); }
        else {
            let side = -1; if i == 2 { side = 1; }
            pb_vset(ps_gripper_local, 0, ps_number(side * (ps_gripper_gap / 2 + 5000), 1000000)); pb_vset(ps_gripper_local, 2, f64_mul(ps_finger_length(), ps_number(1, 2)));
        }
        ps_point(ps_gripper_targets + i * 24, m, ps_gripper_local); i = i + 1;
    }
    pb_zero(ps_gripper_local, 24); pb_vset(ps_gripper_local, 2, ps_grasp_offset()); ps_point(ps_gripper_targets + 72, m, ps_gripper_local); return 0;
}
fn ps_gripper_init(robot, plant) {
    if !ps_gripper_frame { ps_gripper_frame = alloc(128); ps_gripper_targets = alloc(96); ps_gripper_local = alloc(24); ps_gripper_quat = alloc(32); }
    ps_gripper_body = 3; ps_gripper_gap = 90000; ps_gripper_goal = 90000; ps_gripper_held = 0; ps_gripper_contacts = 0; ps_gripper_witnesses = 0;
    ps_gripper_grasps = 0; ps_gripper_releases = 0; ps_gripper_capture_height = 0; ps_gripper_max_height = 0;
    ps_gripper_frame_update(robot, plant); let i = 0;
    while i < 3 {
        let b = ph_body(ps_physics, 5 + i); let p = ps_gripper_targets + i * 24; let k = 0;
        while k < 3 { pb_vset(b + 8, k, pb_f64_to_f32(pb_vget(p, k))); k = k + 1; }
        ph_body_quaternion(ps_physics, 5 + i, load64(ps_gripper_quat), load64(ps_gripper_quat + 8), load64(ps_gripper_quat + 16), load64(ps_gripper_quat + 24)); i = i + 1;
    }
    return 0;
}
fn ps_gripper_contact_mask() {
    let mask = 0; let i = 0;
    while i < load64(ps_physics + 24) {
        let c = ph_contact(ps_physics, i); let a = load64(c); let b = load64(c + 8);
        if a == ps_gripper_body { if b == 6 { mask = mask | 1; } if b == 7 { mask = mask | 2; } }
        if b == ps_gripper_body { if a == 6 { mask = mask | 1; } if a == 7 { mask = mask | 2; } } i = i + 1;
    }
    return mask;
}
fn ps_gripper_contact_select() {
    // In camera mode, choose only from actual finger contacts. Perception
    // never receives a simulator object ID, and capture cannot snap to one.
    let i = 0;
    while i < load64(ps_physics + 24) {
        let c = ph_contact(ps_physics, i); let a = load64(c); let b = load64(c + 8); let candidate = -1;
        if a == 6 || a == 7 { candidate = b; } if b == 6 || b == 7 { candidate = a; }
        if candidate >= 0 && load64(ph_body(ps_physics, candidate)) == 1 {
            ps_gripper_body = candidate; let mask = ps_gripper_contact_mask(); if mask == 3 { return mask; }
        }
        i = i + 1;
    }
    ps_gripper_body = -1; return 0;
}
fn ps_gripper_try_capture() {
    if ps_gripper_held || ps_gripper_goal >= ps_gripper_gap || ps_gripper_contacts != 3 || ps_gripper_gap > 80000 { return 0; }
    let ball = ph_body(ps_physics, ps_gripper_body); let distance = 0; let i = 0;
    while i < 3 {
        let delta = f64_sub(pb_f32_to_f64(pb_vget(ball + 8, i)), pb_vget(ps_gripper_targets + 72, i)); distance = f64_add(distance, f64_mul(delta, delta)); i = i + 1;
    }
    if f64_gt(distance, ps_number(4, 10000)) { return 0; }
    // Capture the existing relative pose only after bilateral contact. The
    // ball stays dynamic; no ball position, velocity or mass is overwritten.
    store64(ps_physics + 32, 0); ph_weld(ps_physics, 5, ps_gripper_body); ps_gripper_held = 1; ps_gripper_goal = ps_gripper_gap;
    ps_gripper_witnesses = ps_gripper_contacts; ps_gripper_grasps = ps_gripper_grasps + 1;
    ps_gripper_capture_height = load64(ball + 24); ps_gripper_max_height = ps_gripper_capture_height; return 1;
}
fn ps_contacts(robot, plant) {
    ps_gripper_frame_update(robot, plant); ps_gripper_contacts = 0;
    let i = 0;
    while i < 10 {
        ps_proxy_target(4, ps_x, ps_y, ps_number(9, 100), i); ps_vehicle_proxies(i); if !i { ps_arm_proxy_update(0); } let j = 0;
        if !i { ph_body_quaternion(ps_physics, 4, 0, 0, pb_f64_to_f32(f64_sin(f64_mul(ps_heading, ps_number(1, 2)))), pb_f64_to_f32(f64_cos(f64_mul(ps_heading, ps_number(1, 2))))); }
        while j < 3 {
            let p = ps_gripper_targets + j * 24; ps_proxy_target(5 + j, load64(p), load64(p + 8), load64(p + 16), i);
            if !i { ph_body_quaternion(ps_physics, 5 + j, load64(ps_gripper_quat), load64(ps_gripper_quat + 8), load64(ps_gripper_quat + 16), load64(ps_gripper_quat + 24)); } j = j + 1;
        }
        if !ph_step(ps_physics) { return 0; }
        let mask = 0;
        if ps_gripper_auto && !ps_gripper_held { mask = ps_gripper_contact_select(); ps_gripper_contacts = mask; }
        else { mask = ps_gripper_contact_mask(); ps_gripper_contacts = ps_gripper_contacts | mask; }
        ps_gripper_try_capture(); i = i + 1;
    }
    ps_bin_update();
    if ps_gripper_held { ps_gripper_max_height = ph_max(ps_gripper_max_height, load64(ph_body(ps_physics, ps_gripper_body) + 24)); }
    ph_body_quaternion(ps_physics, 4, 0, 0, pb_f64_to_f32(f64_sin(f64_mul(ps_heading, ps_number(1, 2)))), pb_f64_to_f32(f64_cos(f64_mul(ps_heading, ps_number(1, 2))))); return !load64(ps_physics + 192);
}
