// Packed wire/tensor values. No host state or global constants.
import "../vendor/f64.flex";
fn pb_u16(p) { return load8(p) | (load8(p + 1) << 8); }
fn pb_u32(p) { return pb_u16(p) | (pb_u16(p + 2) << 16); }
fn pb_put16(p, n) { store8(p, n); store8(p + 1, n >> 8); return 2; }
fn pb_put32(p, n) { pb_put16(p, n); pb_put16(p + 2, n >> 16); return 4; }
// Binary32 wire values converted without host floating point.
fn pb_f32_to_f64(word) {
    let sign = (word & 0x80000000) << 32;
    let exponent = (word >> 23) & 255;
    let fraction = word & 0x7fffff;
    if exponent == 255 { if fraction { return sign | 0x7ff8000000000000 | (fraction << 29); } return sign | 0x7ff0000000000000; }
    if exponent { return sign | ((exponent + 896) << 52) | (fraction << 29); }
    if !fraction { return sign; }
    exponent = -126;
    while fraction < 0x800000 { fraction = fraction << 1; exponent = exponent - 1; }
    return sign | ((exponent + 1023) << 52) | ((fraction & 0x7fffff) << 29);
}
fn pb_round_shift(n, shift) {
    if shift > 63 { return 0; }
    if shift <= 0 { return n << -shift; }
    let out = n >> shift;
    let remainder = n & ((1 << shift) - 1);
    let half = 1 << (shift - 1);
    if remainder > half || (remainder == half && (out & 1)) { out = out + 1; }
    return out;
}
fn pb_f64_to_f32(word) {
    let sign = (word >> 32) & 0x80000000;
    let exponent = (word >> 52) & 2047;
    let fraction = word & 0xfffffffffffff;
    if exponent == 2047 { if fraction { return sign | 0x7fc00000 | (fraction >> 29); } return sign | 0x7f800000; }
    if !exponent { return sign; }
    let e = exponent - 1023;
    if e > 127 { return sign | 0x7f800000; }
    let mantissa = fraction | 0x10000000000000;
    if e < -126 { return sign | pb_round_shift(mantissa, -e - 97); }
    let rounded = pb_round_shift(mantissa, 29);
    if rounded == 0x1000000 { rounded = rounded >> 1; e = e + 1; }
    if e > 127 { return sign | 0x7f800000; }
    return sign | ((e + 127) << 23) | (rounded & 0x7fffff);
}
fn pb_read_float(p) { return pb_f32_to_f64(pb_u32(p)); }
