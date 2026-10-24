// Nonblocking Linux termios2 adapter for the shared serial state machine.
import "linux.flex";
import "../core/system.flex";

global ps_open_stage = 0;

fn ps_open(path, baud) {
    ps_open_stage = "validate baud";
    if baud < 1 || baud > 4000000 { return -22; }
    ps_open_stage = "open";
    let fd = syscall(2, path, 0x80902, 0, 0, 0, 0); if fd < 0 { return fd; }
    let termios = pl_scratch + 256;
    ps_open_stage = "read serial settings";
    let error = syscall(16, fd, 0x802c542a, termios, 0, 0, 0);
    if !error {
        pb_put32(termios, 0); pb_put32(termios + 4, 0); pb_put32(termios + 8, 0x18b0); pb_put32(termios + 12, 0);
        store8(termios + 22, 0); store8(termios + 23, 0); pb_put32(termios + 36, baud); pb_put32(termios + 40, baud);
        ps_open_stage = "set serial settings"; error = syscall(16, fd, 0x402c542b, termios, 0, 0, 0);
    }
    if error { syscall(3, fd, 0, 0, 0, 0, 0); return error; }
    syscall(16, fd, 0x540b, 2, 0, 0, 0); return fd;
}
fn ps_open_error(path, error) {
    let b = pl_scratch + 512; let text = alloc(8192); pl_builder(b, text, 8192);
    pl_text(b, "Cannot open/configure STServo device "); pl_text(b, path); pl_text(b, " ("); pl_text(b, ps_open_stage);
    pl_text(b, ", error "); pl_int(b, error); pl_text(b, "): ");
    if error == -13 || error == -1 { pl_text(b, "permission denied. Check device ownership and your serial-device group membership; log in again after adding a group.\n"); }
    else if error == -2 { pl_text(b, "path not found. Check /dev/serial/by-id/ and reconnect the adapter.\n"); }
    else if error == -16 { pl_text(b, "device busy. Close any other application using this adapter.\n"); }
    else if error == -25 { pl_text(b, "the selected path is not a supported serial terminal.\n"); }
    else if error == -22 { pl_text(b, "the device rejected the serial settings or baud rate.\n"); }
    else { pl_text(b, "serial operation failed.\n"); }
    return pl_print(2, text);
}
// 512 bytes: fd, pending size/offset/deadline, drain deadline, disconnection,
// output admission (position/temperature reads remain allowed in monitor mode).
fn ps_init(serial, fd) { pb_zero(serial, 512); store64(serial, fd); pb_vset(serial, 6, 1); return 0; }
fn ps_lost(serial, system) {
    let fd = load64(serial); if fd >= 0 { syscall(3, fd, 0, 0, 0, 0, 0); }
    store64(serial, -1); pb_vset(serial, 5, 1); pb_vset(serial, 1, 0);
    let robot = load64(system); pb_arm_stop(robot, pb_vget(system, 3)); pb_drive_stop(pb_robot_drive(robot), pb_vget(system, 3));
    pb_vset(system, 9, 0); let i = 0; while i < 4 {
        pb_arm_feedback_error(robot, i);
        if pb_vget(system, 11) { pb_arm_temperature(robot, i, 0, pb_j(pb_joint(robot, i), PB_J_TEMP)); pb_vset(system, 12 + i, -1); }
        i = i + 1;
    }
    pb_vset(system, 8, 0); pb_vset(system, 1, 0); pb_vset(system, 6, 0); return 0;
}
fn ps_pump(serial, system, now) {
    let fd = load64(serial); if fd < 0 { return -1; }
    let iterations = 0;
    while pb_system_active(system) && iterations < 8 {
        iterations = iterations + 1;
        if pb_vget(serial, 1) {
            let size = pb_vget(serial, 1); let at = pb_vget(serial, 2);
            let n = syscall(1, fd, pb_system_packet(system) + at, size - at, 0, 0, 0);
            if n > 0 { at = at + n; pb_vset(serial, 2, at); if at == size { pb_vset(serial, 1, 0); pb_system_written(system, now); } }
            else if n != -4 && n != -11 { ps_lost(serial, system); return -1; }
            if pb_vget(serial, 1) {
                if now >= pb_vget(serial, 3) { syscall(16, fd, 0x540b, 1, 0, 0, 0); pb_vset(serial, 1, 0); pb_system_error(system); }
                return 0;
            }
        } else if pb_vget(system, 6) {
            if !pb_vget(serial, 6) && pb_vget(system, 1) != 1 {
                pb_system_take_tx(system); pb_system_error(system);
            } else {
                if !pb_vget(serial, 4) { pb_vset(serial, 4, now + 20); }
                let drained = 0; let quiet = 0;
                while drained < 1024 && !quiet {
                    let n = syscall(0, fd, serial + 128, 256, 0, 0, 0);
                    if n > 0 { drained = drained + n; } else if n == 0 || n == -11 { quiet = 1; }
                    else if n != -4 { ps_lost(serial, system); return -1; }
                }
                if !quiet {
                    if now >= pb_vget(serial, 4) { pb_vset(serial, 4, 0); pb_system_error(system); } return 0;
                }
                pb_vset(serial, 4, 0); let n = pb_system_take_tx(system);
                pb_vset(serial, 1, n); pb_vset(serial, 2, 0); pb_vset(serial, 3, now + 20);
            }
        } else {
            let n = syscall(0, fd, serial + 128, 256, 0, 0, 0);
            if n > 0 { pb_system_receive(system, serial + 128, n, now); if pb_vget(system, 11) { return 0; } }
            else if n != 0 && n != -4 && n != -11 { ps_lost(serial, system); return -1; }
            else { pb_system_poll(system, now); if !pb_vget(system, 6) { return 0; } }
        }
    }
    return 0;
}
