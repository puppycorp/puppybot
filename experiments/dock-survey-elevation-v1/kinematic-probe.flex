// Reconstruct the saved estimated-frame survey target. Real IK and local
// camera kinematics are used; this does not simulate movement or collisions.
fn main() {
    if !pl_init() || !ps_model_load("build/flex/sim/puppybot.bin") { return 1; }
    ps_robot = alloc(8192); ps_config = alloc(448); ps_trace = alloc(69632);
    ps_pickup_targets = alloc(32); ps_plant = alloc(2048);
    pb_config_default(ps_config); if pb_robot_configure(ps_robot, ps_config, 0) { return 2; }
    ps_local_mode = 2; ps_local_x = ps_number(-1022843491, 1000000000);
    ps_local_y = ps_number(675456618, 1000000000); ps_local_heading = ps_number(-2332748595, 1000000000);
    let frame = ps_asset + 64 + ps_groups * 256 + 24;
    let c = f64_cos(ps_pose_heading()); let s = f64_sin(ps_pose_heading());
    let x = f64_add(ps_pose_x(), f64_sub(f64_mul(c, load64(frame)), f64_mul(s, load64(frame + 8))));
    let y = f64_add(ps_pose_y(), f64_add(f64_mul(s, load64(frame)), f64_mul(c, load64(frame + 8))));
    let tx = ps_number(-1276618640, 1000000000); let ty = ps_number(-439258946, 1000000000);
    let angle = f64_sub(f64_atan2(f64_sub(ty, y), f64_sub(tx, x)), f64_div(PB_TAU, f64_from_i64(18)));
    let point = alloc(24); let camera = alloc(96); let b = alloc(32); let out = alloc(4096);
    pl_builder(b, out, 4096); pl_char(b, 91); let choice = 0;
    while choice < 2 {
        let radial = ps_number(14, 100); let height = 340; let pitch = 50;
        if choice { radial = ps_number(4, 100); height = 380; pitch = 80; }
        store64(point, f64_add(x, f64_mul(radial, f64_cos(angle))));
        store64(point + 8, f64_add(y, f64_mul(radial, f64_sin(angle))));
        if !ps_arm_solve(point, height, pitch) { return 3 + choice; }
        let k = 0; while k < 4 { store64(ps_plant + 128 + k * 64 + 16, load64(ps_pickup_targets + k * 8)); k = k + 1; }
        if !ps_local_camera(camera) { return 5; }
        if choice { pl_char(b, 44); } pl_text(b, "{\"camera\":["); k = 0;
        while k < 12 { if k { pl_char(b, 44); } pl_float(b, load64(camera + k * 8)); k = k + 1; }
        pl_text(b, "],\"ticks\":["); k = 0;
        while k < 4 { if k { pl_char(b, 44); } pl_int(b, load64(ps_pickup_targets + k * 8)); k = k + 1; }
        pl_text(b, "]}"); choice = choice + 1;
    }
    pl_text(b, "]\n"); return pl_write(1, out, load64(b + 8));
}
