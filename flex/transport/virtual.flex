// Opt-in PTY peripheral output, alongside ordinary STServo arm packets.
// DC drive outputs have no STServo register addresses (IDs overlap the arm).
import "../core/stservo.flex";

fn pv_drive_frame(out, left, right, steering, enabled) {
    let data = out + 64; pb_copy(data, "PBV1", 4);
    store8(data + 4, left); store8(data + 5, right); pb_put16(data + 6, steering); store8(data + 8, enabled);
    return pb_servo_packet(out, 128, 254, 160, data, 9);
}
fn pv_drive_frame_valid(packet, size) {
    return size == 15 && load8(packet + 2) == 254 && load8(packet + 4) == 160 && pb_u32(packet + 5) == pb_u32("PBV1") && load8(packet + 13) <= 1;
}
