// Bounded USB-UART envelope: "PB", version=1, kind, payload length:u16,
// payload[0..256], CRC16-CCITT(version through payload), little-endian CRC.
import "../core/packed.flex";

fn pf_crc(crc, byte) {
    crc = crc ^ (byte << 8); let bit = 0;
    while bit < 8 { if crc & 32768 { crc = (crc << 1) ^ 0x1021; } else { crc = crc << 1; } bit = bit + 1; }
    return crc & 65535;
}
fn pf_envelope(out, kind, payload, size) {
    if size < 0 || size > 256 { return -90; }
    store8(out, 80); store8(out + 1, 66); store8(out + 2, 1); store8(out + 3, kind); pb_put16(out + 4, size);
    let crc = 65535; let i = 2;
    while i < size + 6 { let byte = load8(out + i); if i >= 6 { byte = load8(payload + i - 6); store8(out + i, byte); } crc = pf_crc(crc, byte); i = i + 1; }
    pb_put16(out + size + 6, crc); return size + 8;
}
// Parser owns 320 bytes. Completed payload remains at +64 until next byte.
fn pf_serial_reset(parser) { store64(parser, 0); return 0; }
fn pf_serial_byte(parser, byte, now) {
    let at = load64(parser);
    if at && now - load64(parser + 8) > 100 { at = 0; }
    store64(parser + 8, now);
    if at == 0 { if byte == 80 { store64(parser, 1); } else { store64(parser, 0); } return 0; }
    if at == 1 { if byte == 66 { store64(parser, 2); } else { store64(parser, byte == 80); } return 0; }
    if at == 2 { if byte != 1 { store64(parser, byte == 80); return -71; } store64(parser + 16, 65535); }
    if at == 3 { store64(parser + 24, byte); }
    if at == 4 { store64(parser + 32, byte); }
    if at == 5 { let size = load64(parser + 32) | (byte << 8); store64(parser + 32, size); if size > 256 { pf_serial_reset(parser); return -90; } }
    let size = load64(parser + 32);
    if at >= 6 && at < size + 6 { store8(parser + 64 + at - 6, byte); }
    if at < 6 || at < size + 6 { store64(parser + 16, pf_crc(load64(parser + 16), byte)); }
    else if at == size + 6 { store64(parser + 40, byte); }
    else { pf_serial_reset(parser); if (load64(parser + 40) | (byte << 8)) != load64(parser + 16) { return -74; } return 1; }
    store64(parser, at + 1); return 0;
}
