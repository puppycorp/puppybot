import "protocol.flex";

// 448 caller-owned bytes: version at 0, inline serial[32] at 8,
// DriveConfig at 40, CoordinateCalibration at 128, four calibrations at 192.
// Joint calibration words: ID, min, max, reference tick, reference radians,
// angle sign, drive sign, enabled. Config errors mirror Rust enum order + 1.
fn pb_config_joint(config, index) { return config + 192 + index * 64; }
fn pb_config_set_joint(j, id, lo, hi, reference, angle, sign, drive_sign) {
    pb_vset(j, 0, id); pb_vset(j, 1, lo); pb_vset(j, 2, hi); pb_vset(j, 3, reference);
    pb_vset(j, 4, angle); pb_vset(j, 5, sign); pb_vset(j, 6, drive_sign); pb_vset(j, 7, 1); return 0;
}
fn pb_config_default(config) {
    pb_zero(config, 448); store64(config, 1); pb_copy(config + 8, "PB-DEV-0001", 11);
    pb_drive_init(config + 40, 0);
    let i = 0; while i < 7 { if i != 3 { pb_vset(config + 128, i, 1); } i = i + 1; }
    pb_config_set_joint(pb_config_joint(config, 0), 1, 0, 4095, 2048, 0, 1, 1);
    pb_config_set_joint(pb_config_joint(config, 1), 2, 100, 1000, 530, PB_HALF_PI, -1, 1);
    pb_config_set_joint(pb_config_joint(config, 2), 3, 2200, 3600, 3565, 0, -1, 1);
    pb_config_set_joint(pb_config_joint(config, 3), 4, 500, 3000, 1783, 0, 1, 1); return 0;
}
fn pb_config_validate(config) {
    if load64(config) != 1 { return 1; }
    let any = 0; let padding = 0; let i = 0;
    while i < 32 {
        let byte = load8(config + 8 + i);
        if !byte { padding = 1; }
        else { if padding || byte < 32 || byte > 126 { return 3; } any = 1; }
        i = i + 1;
    }
    if !any { return 2; }
    let drive = config + 40;
    if !pb_vget(drive, 0) || !pb_vget(drive, 1) || pb_vget(drive, 0) == pb_vget(drive, 1) || !pb_vget(drive, 4) { return 4; }
    i = 0;
    while i < 4 {
        let j = pb_config_joint(config, i); let id = pb_vget(j, 0); let lo = pb_vget(j, 1); let hi = pb_vget(j, 2);
        if id < 1 || id > 253 { return 5; }
        if lo == hi || lo < 0 || lo >= 4096 || hi < 0 || hi >= 4096 { return 7; }
        if (pb_vget(j, 5) != -1 && pb_vget(j, 5) != 1) || (pb_vget(j, 6) != -1 && pb_vget(j, 6) != 1) { return 8; }
        if !f64_is_finite(pb_vget(j, 4)) { return 9; }
        let k = 0; while k < i { if pb_vget(pb_config_joint(config, k), 0) == id { return 6; } k = k + 1; }
        i = i + 1;
    }
    i = 0;
    while i < 7 { let value = pb_vget(config + 128, i); if i != 3 && value != -1 && value != 1 { return 8; } i = i + 1; }
    if !f64_is_finite(pb_vget(config + 128, 3)) { return 10; } return 0;
}
fn pb_robot_configure(robot, config, now) {
    let error = pb_config_validate(config); if error { return error; }
    pb_robot_init(robot, now);
    pb_copy(pb_robot_drive(robot), config + 40, 48); pb_drive_stop(pb_robot_drive(robot), now);
    store64(robot + 4200, pb_vget(config + 40, 2));
    let i = 0;
    while i < 4 {
        let calibration = pb_config_joint(config, i); let j = pb_joint(robot, i);
        pb_joint_calibrate(j, pb_vget(calibration, 0), pb_vget(calibration, 1), pb_vget(calibration, 2), pb_vget(calibration, 3), pb_vget(calibration, 4), pb_vget(calibration, 5), pb_vget(calibration, 6));
        pb_js(j, PB_J_LIMIT_ENABLED, pb_vget(calibration, 7)); pb_js(j, PB_J_LAST_FEEDBACK, now); pb_js(j, PB_J_LAST_SPEED_CMD, now);
        store64(pb_wheel_id(robot, i), pb_vget(calibration, 0)); store64(robot + 4208 + i * 8, pb_vget(calibration, 0)); i = i + 1;
    }
    return 0;
}
