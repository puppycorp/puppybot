// Optional virtual peripheral adapter; accepted only on a Linux slave PTY.
import "serial.flex";
import "../transport/virtual.flex";

fn ps_virtual_capable(fd) {
    let info = pl_scratch + 256; if syscall(5, fd, info, 0, 0, 0, 0) { return 0; }
    let device = load64(info + 40); let major = ((device >> 8) & 4095) | ((device >> 32) & 0xfffff000);
    return (pb_u32(info + 24) & 0xf000) == 0x2000 && major >= 136 && major <= 143;
}
fn ps_virtual_cancel(serial) {
    pb_zero(serial + 56, 32); pb_vset(serial, 12, -1); return 0;
}
// Serial words7..12: pending bytes/offset,last heartbeat,deadline,opt-in,last value.
// The packet occupies384..511, beyond the ordinary RX buffer at128..383.
fn ps_virtual_pump(serial, robot, enabled, now) {
    if !pb_vget(serial, 11) { return 1; }
    let fd = load64(serial); if fd < 0 { return -1; }
    if !pb_vget(serial, 7) {
        let drive = pb_robot_drive(robot); let left = 0; let right = 0; let angle = pb_vget(drive, 3);
        if enabled { left = pb_vget(drive, 6); right = pb_vget(drive, 7); angle = pb_vget(drive, 8); }
        let value = (left & 255) | ((right & 255) << 8) | (angle << 16) | (enabled << 32);
        if value == pb_vget(serial, 12) && now - pb_vget(serial, 9) < 50 { return 1; }
        let n = pv_drive_frame(serial + 384, left, right, angle, enabled);
        pb_vset(serial, 7, n); pb_vset(serial, 8, 0); pb_vset(serial, 10, now + 50); pb_vset(serial, 12, value);
    }
    let at = pb_vget(serial, 8); let size = pb_vget(serial, 7);
    let n = syscall(1, fd, serial + 384 + at, size - at, 0, 0, 0);
    if n > 0 { at = at + n; pb_vset(serial, 8, at); }
    else if n != -4 && n != -11 { return -1; }
    if at == size { pb_vset(serial, 7, 0); pb_vset(serial, 8, 0); pb_vset(serial, 9, now); return 1; }
    if now >= pb_vget(serial, 10) { return -1; } return 0;
}
