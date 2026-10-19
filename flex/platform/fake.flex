import "../core/system.flex";

// Fake state is indexed by physical ID, independently of arm joint order.
// Each record: present, mode, position, wheel speed, fail read, fail write.
fn pb_fake_init(bus) { return pb_zero(bus, 16384); }
fn pb_fake_servo(bus, id, position) {
    if !pb_servo_id(id) { return -1; }
    let servo = bus + id * 48; pb_vset(servo, 0, 1); pb_vset(servo, 2, position); return 0;
}
fn pb_fake_transaction(bus, packet, size, reply) {
    if size < 6 || load8(packet) != 255 || load8(packet + 1) != 255 || load8(packet + 3) + 4 != size || pb_servo_checksum(packet, size - 1) != load8(packet + size - 1) { return -2; }
    let id = load8(packet + 2); let servo = bus + id * 48;
    let instruction = load8(packet + 4); let params = packet + 5; let n = size - 6;
    if (instruction == 2 && pb_vget(servo, 4)) || (instruction == 3 && pb_vget(servo, 5)) { return -5; }
    if !pb_vget(servo, 0) { return 0; }
    let scratch = bus + 13000; let count = 0;
    if instruction == 2 {
        if n < 2 { return -2; }
        let address = load8(params); count = load8(params + 1);
        if address == 56 && count == 2 { pb_put16(scratch, pb_vget(servo, 2)); }
        else if address == 33 && count == 1 { store8(scratch, pb_vget(servo, 1)); }
        else { return -2; }
    } else if instruction == 3 {
        if n < 2 { return -2; }
        let address = load8(params);
        if address == 33 { pb_vset(servo, 1, load8(params + 1)); }
        else if address == 41 && n >= 8 {
            if pb_vget(servo, 1) {
                let speed = pb_u16(params + 6); let signed = speed & 32767; if speed & 32768 { signed = -signed; }
                pb_vset(servo, 3, signed);
            } else { pb_vset(servo, 2, pb_u16(params + 2)); }
        }
    }
    return pb_servo_packet(reply, 128, id, 0, scratch, count);
}
fn pb_fake_cycle(system, bus, now, trace, capacity) {
    let at = 0; let replies = bus + 14000;
    pb_system_begin(system, now); let exchanges = 0;
    while pb_system_active(system) {
        exchanges = exchanges + 1; if exchanges > 20 { return -1; }
        let n = pb_system_take_tx(system); if !n || at + n + 2 > capacity { return -2; }
        pb_put16(trace + at, n); pb_copy(trace + at + 2, pb_system_packet(system), n); at = at + n + 2;
        let response = pb_fake_transaction(bus, pb_system_packet(system), n, replies);
        if response < 0 { pb_system_error(system); }
        else {
            pb_system_written(system, now);
            if !response { pb_system_poll(system, now + 50); }
            else {
                // Deliberately fragment every status frame into single bytes.
                let i = 0; while i < response { pb_system_receive(system, replies + i, 1, now); i = i + 1; }
            }
        }
    }
    return at;
}
