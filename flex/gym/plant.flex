// Deterministic encoder/velocity plant. No rigid-body or articulated physics.
import "../platform/fake.flex";
import "../core/config.flex";

// 2048 bytes: config, bus, seed, jam index (-1=no jam), then 4*64 joint state.
// Joint state: encoder milli-ticks, velocity ticks/sec, encoder ticks, drive ID.
fn gs_init(plant, config, bus, seed, jam) {
    pb_zero(plant, 2048); pb_fake_init(bus); pb_vset(plant, 0, config); pb_vset(plant, 1, bus); pb_vset(plant, 2, seed); pb_vset(plant, 3, jam);
    let i = 0;
    while i < 4 {
        let c = pb_config_joint(config, i); let j = plant + 128 + i * 64; let tick = pb_canonical(pb_vget(c, 3));
        store64(j, tick * 1000); pb_vset(j, 2, tick); pb_vset(j, 3, pb_vget(c, 0)); pb_fake_servo(bus, pb_vget(c, 0), tick); i = i + 1;
    }
    let id = pb_vget(config + 40, 2); if id && pb_servo_id(id) { pb_fake_servo(bus, id, pb_servo_angle(pb_vget(config + 40, 3))); } return 0;
}
fn gs_step(plant) {
    let bus = pb_vget(plant, 1); let i = 0;
    while i < 4 {
        let j = plant + 128 + i * 64; let servo = bus + pb_vget(j, 3) * 48;
        let speed = 0; if pb_vget(servo, 1) { speed = pb_clamp(pb_vget(servo, 3), -32767, 32767); }
        let velocity = pb_vget(j, 1); velocity = velocity + pb_clamp(speed - velocity, -40, 40);
        if i == pb_vget(plant, 3) { velocity = 0; }
        let position = pb_mod(load64(j) + velocity * 20, 4096000);
        store64(j, position); pb_vset(j, 1, velocity); pb_vset(j, 2, position / 1000); pb_vset(servo, 2, position / 1000); i = i + 1;
    }
    return 0;
}
fn gs_targets(out, config, seed, stalled) {
    let state = seed & 0xffffffff; let i = 0;
    while i < 4 {
        state = (state * 1664525 + 1013904223) & 0xffffffff;
        let c = pb_config_joint(config, i); let offset = state % 81 - 40;
        let target = pb_clamp(pb_vget(c, 3) + offset, pb_vget(c, 1) + 16, pb_vget(c, 2) - 16);
        if stalled && !i { target = pb_vget(c, 3) + 200; }
        store64(out + i * 8, target); i = i + 1;
    }
    return 0;
}
fn gs_reached(plant, targets) {
    let i = 0;
    while i < 4 { let j = plant + 128 + i * 64; if pb_abs(pb_vget(j, 2) - pb_vget(targets, i)) > 8 || pb_vget(j, 1) { return 0; } i = i + 1; }
    return 1;
}
fn gs_stopped(plant) {
    let bus = pb_vget(plant, 1); let i = 0;
    while i < 4 { let j = plant + 128 + i * 64; if pb_vget(bus + pb_vget(j, 3) * 48, 3) { return 0; } i = i + 1; } return 1;
}
