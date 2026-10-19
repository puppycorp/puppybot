import "words.flex";
// 0 left ID, 1 right ID, 2 steering ID, 3 center, 4 range, 5 timeout,
// 6 left speed, 7 right speed, 8 steering angle, 9 active, 10 last command.
fn pb_drive_stop(drive, now) {
    pb_vset(drive, 6, 0); pb_vset(drive, 7, 0);
    pb_vset(drive, 8, pb_vget(drive, 3)); pb_vset(drive, 9, 0);
    pb_vset(drive, 10, now); return 0;
}
fn pb_drive_init(drive, now) {
    pb_zero(drive, 88);
    pb_vset(drive, 0, 1); pb_vset(drive, 1, 2); pb_vset(drive, 2, 1);
    pb_vset(drive, 3, 90); pb_vset(drive, 4, 45); pb_vset(drive, 5, 500);
    return pb_drive_stop(drive, now);
}
fn pb_drive_steer(drive, throttle, steering, now) {
    throttle = pb_clamp(throttle, -100, 100); steering = pb_clamp(steering, -100, 100);
    pb_vset(drive, 6, throttle); pb_vset(drive, 7, throttle);
    pb_vset(drive, 8, pb_clamp(pb_i16(pb_vget(drive, 3)) + steering * pb_i16(pb_vget(drive, 4)) / 100, 0, 180));
    pb_vset(drive, 9, throttle != 0 || steering != 0); pb_vset(drive, 10, now); return 0;
}
fn pb_drive_motor(drive, id, speed, now) {
    let slot = 0;
    if id == pb_vget(drive, 0) { slot = 6; }
    else if id == pb_vget(drive, 1) { slot = 7; } else { return 0; }
    pb_vset(drive, slot, pb_clamp(speed, -100, 100));
    pb_vset(drive, 9, pb_vget(drive, 6) != 0 || pb_vget(drive, 7) != 0 || pb_vget(drive, 8) != pb_vget(drive, 3));
    pb_vset(drive, 10, now); return 0;
}
fn pb_drive_tick(drive, now) {
    if pb_vget(drive, 5) && pb_vget(drive, 9) && pb_elapsed(now, pb_vget(drive, 10)) >= pb_vget(drive, 5) { pb_drive_stop(drive, now); }
    return 0;
}
