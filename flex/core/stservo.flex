import "words.flex";

// Packet errors: -1 invalid ID, -2 packet, -3 capacity, -4 checksum.
// Streaming parser: caller owns 128 bytes; no allocation, I/O or timeout loop.
fn pb_servo_id(id) { return id >= 1 && id <= 253; }
fn pb_servo_checksum(packet, size) {
    let sum = 0; let i = 2; while i < size { sum = (sum + load8(packet + i)) & 255; i = i + 1; } return (~sum) & 255;
}
fn pb_servo_packet(out, capacity, id, instruction, params, size) {
    if size < 0 || size > 244 || capacity < size + 6 { return -3; }
    store8(out, 255); store8(out + 1, 255); store8(out + 2, id); store8(out + 3, size + 2); store8(out + 4, instruction);
    pb_copy(out + 5, params, size); store8(out + 5 + size, pb_servo_checksum(out, size + 5)); return size + 6;
}
fn pb_servo_signed(speed) { if speed < 0 { return pb_min(-speed, 32767) | 32768; } return pb_min(speed, 32767); }
fn pb_servo_angle(degrees) { return pb_min(degrees, 240) * 4095 / 240; }
fn pb_servo_position(out, capacity, id, position, speed, acc, params) {
    if !pb_servo_id(id) { return -1; }
    store8(params, 41); store8(params + 1, acc); pb_put16(params + 2, pb_min(position, 4095)); pb_put16(params + 4, 0); pb_put16(params + 6, speed);
    return pb_servo_packet(out, capacity, id, 3, params, 8);
}
fn pb_servo_wheel(out, capacity, id, speed, acc, params) {
    if !pb_servo_id(id) { return -1; }
    store8(params, 41); store8(params + 1, acc); pb_put32(params + 2, 0); pb_put16(params + 6, pb_servo_signed(speed));
    return pb_servo_packet(out, capacity, id, 3, params, 8);
}
fn pb_servo_write8(out, capacity, id, address, value, params) {
    if !pb_servo_id(id) { return -1; }
    store8(params, address); store8(params + 1, value); return pb_servo_packet(out, capacity, id, 3, params, 2);
}
fn pb_servo_read(out, capacity, id, address, size, params) {
    if !pb_servo_id(id) { return -1; } if size < 0 || size > 64 { return -2; }
    store8(params, address); store8(params + 1, size); return pb_servo_packet(out, capacity, id, 2, params, 2);
}
fn pb_servo_parser_init(parser) { return pb_zero(parser, 128); }
fn pb_servo_byte(parser, byte) {
    let state = pb_vget(parser, 0); byte = byte & 255;
    if state == 0 { if byte == 255 { pb_vset(parser, 0, 1); } return 0; }
    if state == 1 { if byte == 255 { pb_vset(parser, 0, 2); } else { pb_vset(parser, 0, 0); } return 0; }
    if state == 2 {
        if byte > 253 { pb_vset(parser, 0, 0); return 0; }
        pb_vset(parser, 1, byte); pb_vset(parser, 3, byte); pb_vset(parser, 0, 3); return 0;
    }
    if state == 3 {
        if byte < 2 || byte > 250 { pb_vset(parser, 0, 0); return 0; }
        pb_vset(parser, 3, (pb_vget(parser, 3) + byte) & 255); pb_vset(parser, 4, byte - 2);
        if byte - 2 > 64 { pb_vset(parser, 0, 0); return -3; }
        pb_vset(parser, 0, 4); return 0;
    }
    if state == 4 {
        pb_vset(parser, 2, byte); pb_vset(parser, 3, (pb_vget(parser, 3) + byte) & 255); pb_vset(parser, 5, 0);
        if pb_vget(parser, 4) { pb_vset(parser, 0, 5); } else { pb_vset(parser, 0, 6); } return 0;
    }
    if state == 5 {
        let at = pb_vget(parser, 5); store8(parser + 64 + at, byte); pb_vset(parser, 5, at + 1);
        pb_vset(parser, 3, (pb_vget(parser, 3) + byte) & 255); if at + 1 >= pb_vget(parser, 4) { pb_vset(parser, 0, 6); } return 0;
    }
    pb_vset(parser, 0, 0); if byte != ((~pb_vget(parser, 3)) & 255) { return -4; } return 1;
}
