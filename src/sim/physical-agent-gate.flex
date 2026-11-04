// Pure request gate for the opt-in physical agent protocol. This accepts no
// scene or pose values and does not itself command hardware or simulation.
fn ps_physical_sequence(previous, next) { return previous >= 0 && previous < 2147483647 && next == previous + 1; }
fn ps_physical_permit(initialized, owner, command, steering, speed, hold, task) {
    if command == 3 { return 1; }
    if command == 1 { return !initialized && task == 4; }
    if !initialized { return 0; }
    if command == 2 {
        return !owner && steering >= -1000 && steering <= 1000 && speed >= -1000 && speed <= 1000 && hold >= 1 && hold <= 20;
    }
    if command == 6 { return !owner; }
    if command == 7 { return owner == 1 && hold >= 1 && hold <= 20; }
    return 0;
}
