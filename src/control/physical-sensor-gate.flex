// The simulator must supply a fresh image from a still driving camera and an
// unchanged arm before the diagnostic client can pass pixels to its actor.
fn pc_sensor_ok(driving, still, frame, total, previous, command, hold, unchanged) {
    if !driving || !still || frame < 0 || frame != total { return 0; }
    if previous < 0 { return command == 1; }
    if !unchanged { return 0; }
    if command == 2 { return hold >= 1 && hold <= 20 && frame == previous + hold; }
    // A rejected handoff takes two stopped simulator ticks before its reply.
    if command == 6 { return frame == previous + 2; }
    return 0;
}
fn pc_status_ok(command, owner, ack) {
    if command == 1 { return !owner && !ack; }
    if command == 2 { return !owner && ack == 1; }
    if command == 3 { return owner == 2 && ack == 7; }
    if command == 6 { return (!owner && ack == 2) || (owner == 1 && ack == 3); }
    if command == 7 { return (owner == 1 && ack == 4) || (owner == 2 && (ack == 5 || ack == 6)); }
    return 0;
}
fn pc_drive_ok(command, ack, left, right, angle, steering, speed) {
    if command == 1 || command == 3 || command == 6 || (command == 7 && (ack == 5 || ack == 6)) { return !left && !right && angle == 90; }
    if command != 2 { return 1; }
    let throttle = speed * 60 / 1000; if speed > -80 && speed < 80 { throttle = 0; }
    return left == throttle && right == throttle && angle == 90 + (steering / 10) * 45 / 100;
}
