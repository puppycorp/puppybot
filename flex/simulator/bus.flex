// STServo byte-stream endpoint backed by Gym's encoder/velocity plant.
import "../gym/plant.flex";
import "../host/serial.flex";
import "../transport/virtual.flex";

// 512 bytes: master fd, slave keeper fd, plant, bus, temperature, received
// packet count, malformed count, input used, output used/sent, partial deadline.
fn pv_pty(context, path) {
    let fd = syscall(2, "/dev/ptmx", 0x80902, 0, 0, 0, 0); if fd < 0 { return fd; }
    store64(context, fd); let scratch = pl_scratch + 256; store64(scratch, 0);
    let error = syscall(16, fd, 0x40045431, scratch, 0, 0, 0);
    if !error { error = syscall(16, fd, 0x80045430, scratch, 0, 0, 0); }
    if error { syscall(3, fd, 0, 0, 0, 0, 0); store64(context, -1); return error; }
    let number = pb_u32(scratch); let b = pl_scratch + 512;
    pl_builder(b, path, 128); pl_text(b, "/dev/pts/"); pl_uint(b, number);
    // Keeping a raw slave open avoids startup EIO/echo and allows reconnects.
    let keeper = ps_open(path, 1000000);
    if keeper < 0 { syscall(3, fd, 0, 0, 0, 0, 0); store64(context, -1); return keeper; }
    pb_vset(context, 1, keeper); return fd;
}
fn pv_velocity(context, id) {
    let plant = pb_vget(context, 2); let i = 0;
    while i < 4 { let j = plant + 128 + i * 64; if pb_vget(j, 3) == id { return pb_vget(j, 1); } i = i + 1; }
    return pb_vget(pb_vget(context, 3) + id * 48, 3);
}
fn pv_transaction(context, packet, size, reply) {
    // Optional 3D-world peripheral:12 drive view,13 last output,14 enabled,
    // 15 sensor quarantine (-1 paused),17 last valid serial request.
    pb_vset(context, 17, pb_vget(context, 11));
    let drive = pb_vget(context, 12); let quarantine = pb_vget(context, 15);
    let blocked = quarantine < 0 || pb_vget(context, 11) < quarantine;
    if drive && pv_drive_frame_valid(packet, size) {
        let enabled = load8(packet + 13) && !blocked; pb_vset(context, 14, enabled); pb_vset(context, 13, pb_vget(context, 11));
        if enabled {
            pb_vset(drive, 6, pb_clamp(pb_i8(load8(packet + 9)), -100, 100)); pb_vset(drive, 7, pb_clamp(pb_i8(load8(packet + 10)), -100, 100));
            pb_vset(drive, 8, pb_clamp(pb_u16(packet + 11), 0, 180)); pb_vset(drive, 9, pb_vget(drive, 6) || pb_vget(drive, 7));
        } else {
            pb_drive_stop(drive, pb_vget(context, 11)); let i = 0;
            while i < 4 { let j = pb_vget(context, 2) + 128 + i * 64; pb_vset(pb_vget(context, 3) + pb_vget(j, 3) * 48, 3, 0); i = i + 1; }
        }
        return 0;
    }
    let bus = pb_vget(context, 3); let id = load8(packet + 2); let servo = bus + id * 48;
    if !pb_vget(servo, 0) { return 0; }
    if load8(packet + 4) == 2 && size == 8 {
        let address = load8(packet + 5); let count = load8(packet + 6);
        if address >= 56 && count > 0 && address + count <= 64 {
            let data = context + 256; pb_zero(data, 8); pb_put16(data, pb_vget(servo, 2));
            let velocity = pv_velocity(context, id); let encoded = pb_abs(velocity); if velocity < 0 { encoded = encoded | 32768; }
            pb_put16(data + 2, encoded); store8(data + 6, 120); store8(data + 7, pb_vget(context, 4));
            if drive && blocked && address + count == 64 { let short = 0; if address == 56 { short = 2; } return pb_servo_packet(reply, 128, id, 0, data, short); }
            return pb_servo_packet(reply, 128, id, 0, data + address - 56, count);
        }
    }
    if drive && blocked && load8(packet + 4) == 3 && load8(packet + 5) == 41 { return pb_servo_packet(reply, 128, id, 0, 0, 0); }
    let n = pb_fake_transaction(bus, packet, size, reply);
    if n > 0 && load8(packet + 4) == 3 && load8(packet + 5) == 41 && !pb_vget(servo, 1) {
        // Position-mode writes update the plant as well as its register image.
        let plant = pb_vget(context, 2); let i = 0;
        while i < 4 {
            let j = plant + 128 + i * 64;
            if pb_vget(j, 3) == id { store64(j, pb_canonical(pb_vget(servo, 2)) * 1000); pb_vset(j, 1, 0); pb_vset(j, 2, pb_canonical(pb_vget(servo, 2))); }
            i = i + 1;
        }
    } return n;
}
fn pv_flush(context, output) {
    let used = pb_vget(context, 8); let sent = pb_vget(context, 9);
    if sent < used {
        let n = syscall(1, load64(context), output + sent, used - sent, 0, 0, 0);
        if n > 0 { pb_vset(context, 9, sent + n); }
        else if n != -11 && n != -4 { return -1; }
    }
    if pb_vget(context, 9) == used { pb_vset(context, 8, 0); pb_vset(context, 9, 0); } return 0;
}
fn pv_bytes(context, input, output, reply, now) {
    pb_vset(context, 11, now);
    let used = pb_vget(context, 7); let deadline = pb_vget(context, 10);
    if used && deadline && now >= deadline { used = 0; deadline = 0; pb_vset(context, 6, pb_vget(context, 6) + 1); }
    let n = syscall(0, load64(context), input + used, 4096 - used, 0, 0, 0);
    if n > 0 { used = used + n; }
    else if n != -11 && n != -4 && n != 0 { return -1; }
    let at = 0; let parsing = 1;
    while parsing && used - at >= 4 {
        let packet = input + at; let size = load8(packet + 3) + 4;
        if load8(packet) != 255 || load8(packet + 1) != 255 || size < 6 {
            at = at + 1; pb_vset(context, 6, pb_vget(context, 6) + 1);
        } else if size > used - at { parsing = 0; }
        else if pb_servo_checksum(packet, size - 1) != load8(packet + size - 1) {
            at = at + 1; pb_vset(context, 6, pb_vget(context, 6) + 1);
        } else {
            let count = pv_transaction(context, packet, size, reply); pb_vset(context, 5, pb_vget(context, 5) + 1);
            if count > 0 {
                let size = pb_vget(context, 8); let sent = pb_vget(context, 9);
                if sent { pb_copy(output, output + sent, size - sent); size = size - sent; pb_vset(context, 9, 0); }
                if size + count > 16384 { return -1; }
                pb_copy(output + size, reply, count); pb_vset(context, 8, size + count);
            }
            at = at + size;
        }
    }
    if at { pb_copy(input, input + at, used - at); used = used - at; }
    if !used { pb_vset(context, 10, 0); }
    else if at || !deadline { pb_vset(context, 10, now + 50); }
    pb_vset(context, 7, used); return pv_flush(context, output);
}
