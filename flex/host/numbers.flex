// Exact decimal/binary64 boundary conversion. Fixed 128 base-2^30 limbs;
// no libc math, float FFI, per-number allocation or ambient locale.
import "../core/words.flex";

global pn_work = 0;
global pn_error = 0;
global pn_size = 0;

fn pn_init() { if !pn_work { pn_work = alloc(16384); } return pn_work > 0; }
fn pn_big_zero(a) { store64(a, 0); return 0; }
fn pn_big_word(a, value) {
    let n = 0;
    while value { store64(a + 8 + n * 8, value & 0x3fffffff); value = value >> 30; n = n + 1; }
    store64(a, n); return 0;
}
fn pn_big_copy(out, a) { let n = load64(a); pb_copy(out, a, (n + 1) * 8); return 0; }
fn pn_big_normalize(a) {
    let n = load64(a); while n && !load64(a + n * 8) { n = n - 1; } store64(a, n); return 0;
}
fn pn_big_mul(a, factor) {
    let n = load64(a); let carry = 0; let i = 0;
    while i < n { let value = load64(a + 8 + i * 8) * factor + carry; store64(a + 8 + i * 8, value & 0x3fffffff); carry = value >> 30; i = i + 1; }
    if carry { if n >= 128 { pn_error = 1; return -1; } store64(a + 8 + n * 8, carry); n = n + 1; }
    store64(a, n); return 0;
}
fn pn_big_add_digit(a, digit) {
    let carry = digit; let i = 0; let n = load64(a);
    while carry {
        if i >= 128 { pn_error = 1; return -1; }
        let value = carry; if i < n { value = value + load64(a + 8 + i * 8); }
        store64(a + 8 + i * 8, value & 0x3fffffff); carry = value >> 30;
        i = i + 1; if i > n { n = i; }
    }
    store64(a, n); return 0;
}
fn pn_big_shift(a, bits) {
    let n = load64(a); if !n || !bits { return 0; }
    let words = bits / 30; let shift = bits % 30;
    if bits < 0 || n + words + (shift != 0) > 128 { pn_error = 1; return -1; }
    let i = n - 1;
    while i >= 0 { store64(a + 8 + (i + words) * 8, load64(a + 8 + i * 8)); i = i - 1; }
    i = 0; while i < words { store64(a + 8 + i * 8, 0); i = i + 1; }
    n = n + words;
    if shift {
        let carry = 0; i = words;
        while i < n {
            let value = (load64(a + 8 + i * 8) << shift) | carry;
            store64(a + 8 + i * 8, value & 0x3fffffff); carry = value >> 30; i = i + 1;
        }
        if carry { store64(a + 8 + n * 8, carry); n = n + 1; }
    }
    store64(a, n); return 0;
}
fn pn_big_compare(a, b) {
    let n = load64(a); let m = load64(b);
    if n != m { return pb_sign(n - m); }
    let i = n;
    while i > 0 { let av = load64(a + i * 8); let bv = load64(b + i * 8); if av != bv { return pb_sign(av - bv); } i = i - 1; }
    return 0;
}
fn pn_big_sub(a, b) {
    let n = load64(a); let m = load64(b); let borrow = 0; let i = 0;
    while i < n {
        let value = load64(a + 8 + i * 8) - borrow; if i < m { value = value - load64(b + 8 + i * 8); }
        borrow = value < 0; if borrow { value = value + 0x40000000; }
        store64(a + 8 + i * 8, value); i = i + 1;
    }
    return pn_big_normalize(a);
}
fn pn_big_bits(a) {
    let n = load64(a); if !n { return 0; }
    let top = load64(a + n * 8); let bits = 0;
    while top { bits = bits + 1; top = top >> 1; } return (n - 1) * 30 + bits;
}
fn pn_big_power(a, factor, count) {
    let i = 0; while i < count && !pn_error { pn_big_mul(a, factor); i = i + 1; } return pn_error;
}
// A/B is bounded below 2^58. Round the integer quotient to nearest/even.
fn pn_big_round(a, b, scratch) {
    let shift = pn_big_bits(a) - pn_big_bits(b); let quotient = 0;
    if shift > 58 || !load64(b) { pn_error = 1; return 0; }
    while shift >= 0 {
        pn_big_copy(scratch, b); pn_big_shift(scratch, shift);
        if pn_big_compare(a, scratch) >= 0 { pn_big_sub(a, scratch); quotient = quotient | (1 << shift); }
        shift = shift - 1;
    }
    pn_big_shift(a, 1); let compare = pn_big_compare(a, b);
    if compare > 0 || (!compare && (quotient & 1)) { quotient = quotient + 1; }
    return quotient;
}
fn pn_parse(text, size) {
    pn_error = 0; if !pn_init() || size < 1 || size > 768 { pn_error = 1; return 0; }
    let a = pn_work; let b = pn_work + 2048; let scratch = pn_work + 4096;
    pn_big_zero(a); pn_big_word(b, 1);
    let at = 0; let sign = 0; if load8(text) == 45 { sign = 0x8000000000000000; at = 1; }
    let digits = 0; let fraction = 0; let seen = 0;
    let before = at;
    while at < size && load8(text + at) >= 48 && load8(text + at) <= 57 {
        let digit = load8(text + at) - 48; if digit || seen { seen = 1; digits = digits + 1; }
        pn_big_mul(a, 10); pn_big_add_digit(a, digit); at = at + 1;
    }
    if at == before || (at - before > 1 && load8(text + before) == 48) { pn_error = 1; return 0; }
    if at < size && load8(text + at) == 46 {
        at = at + 1; before = at;
        while at < size && load8(text + at) >= 48 && load8(text + at) <= 57 {
            let digit = load8(text + at) - 48; if digit || seen { seen = 1; digits = digits + 1; }
            pn_big_mul(a, 10); pn_big_add_digit(a, digit); fraction = fraction + 1; at = at + 1;
        }
        if at == before { pn_error = 1; return 0; }
    }
    let exponent = 0;
    if at < size && (load8(text + at) == 101 || load8(text + at) == 69) {
        at = at + 1; let direction = 1;
        if at < size && (load8(text + at) == 43 || load8(text + at) == 45) { if load8(text + at) == 45 { direction = -1; } at = at + 1; }
        before = at;
        while at < size && load8(text + at) >= 48 && load8(text + at) <= 57 {
            exponent = pb_min(exponent * 10 + load8(text + at) - 48, 100000); at = at + 1;
        }
        if at == before { pn_error = 1; return 0; } exponent = exponent * direction;
    }
    if at != size || pn_error { pn_error = 1; return 0; }
    if !seen { return sign; }
    exponent = exponent - fraction; let order = exponent + digits - 1;
    if order < -350 { return sign; } if order > 309 { pn_error = 1; return 0; }
    if exponent >= 0 { pn_big_power(a, 5, exponent); pn_big_shift(a, exponent); }
    else { pn_big_power(b, 5, -exponent); pn_big_shift(b, -exponent); }
    if pn_error { return 0; }
    let e = pn_big_bits(a) - pn_big_bits(b);
    if e >= 0 { pn_big_copy(scratch, b); pn_big_shift(scratch, e); if pn_big_compare(a, scratch) < 0 { e = e - 1; } }
    else { pn_big_copy(scratch, a); pn_big_shift(scratch, -e); if pn_big_compare(scratch, b) < 0 { e = e - 1; } }
    if e < -1075 { return sign; } if e > 1023 { pn_error = 1; return 0; }
    let effective = pb_max(e, -1022); let shift = 52 - effective;
    if shift >= 0 { pn_big_shift(a, shift); } else { pn_big_shift(b, -shift); }
    let significand = pn_big_round(a, b, scratch); if pn_error { return 0; }
    if significand >= 0x20000000000000 { significand = significand >> 1; effective = effective + 1; }
    if effective > 1023 { pn_error = 1; return 0; }
    if significand < 0x10000000000000 { return sign | significand; }
    return sign | ((effective + 1023) << 52) | (significand & 0xfffffffffffff);
}
fn pn_format(word) {
    pn_error = 0; pn_size = 0; if !pn_init() { pn_error = 1; return 0; }
    let out = pn_work + 14336; let digits = pn_work + 14592;
    if !f64_is_finite(word) { pb_copy(out, "null", 5); pn_size = 4; return out; }
    let at = 0; if f64_sign(word) { store8(out, 45); at = 1; }
    let magnitude = f64_magnitude(word);
    if !magnitude { pb_copy(out + at, "0.0", 4); pn_size = at + 3; return out; }
    let a = pn_work; let b = pn_work + 2048; let scratch = pn_work + 4096; let temp = pn_work + 6144;
    let exponent = f64_exponent(word); let mantissa = f64_fraction(word); let binary = -1074;
    if exponent { mantissa = mantissa | 0x10000000000000; binary = exponent - 1023 - 52; }
    pn_big_word(a, mantissa); pn_big_word(b, 1);
    if binary >= 0 { pn_big_shift(a, binary); } else { pn_big_shift(b, -binary); }
    let k = ((pn_big_bits(a) - pn_big_bits(b)) * 78913) >> 18;
    let compare = 0;
    if k >= 0 { pn_big_copy(temp, b); pn_big_power(temp, 10, k); compare = pn_big_compare(a, temp); }
    else { pn_big_copy(temp, a); pn_big_power(temp, 10, -k); compare = pn_big_compare(temp, b); }
    if compare < 0 { k = k - 1; }
    if k + 1 >= 0 { pn_big_copy(temp, b); pn_big_power(temp, 10, k + 1); compare = pn_big_compare(a, temp); }
    else { pn_big_copy(temp, a); pn_big_power(temp, 10, -k - 1); compare = pn_big_compare(temp, b); }
    if compare >= 0 { k = k + 1; }
    let shift = 16 - k;
    if shift >= 0 { pn_big_power(a, 10, shift); } else { pn_big_power(b, 10, -shift); }
    let value = pn_big_round(a, b, scratch); if pn_error { return 0; }
    if value >= 100000000000000000 { value = value / 10; k = k + 1; }
    let i = 16;
    while i >= 0 { store8(digits + i, 48 + value % 10); value = value / 10; i = i - 1; }
    let n = 17; while n > 1 && load8(digits + n - 1) == 48 { n = n - 1; }
    if k >= 0 && k <= 16 {
        i = 0; while i <= k { let digit = 48; if i < n { digit = load8(digits + i); } store8(out + at, digit); at = at + 1; i = i + 1; }
        if n > k + 1 { store8(out + at, 46); at = at + 1; while i < n { store8(out + at, load8(digits + i)); at = at + 1; i = i + 1; } }
        else { store8(out + at, 46); store8(out + at + 1, 48); at = at + 2; }
    } else if k < 0 && k >= -6 {
        store8(out + at, 48); store8(out + at + 1, 46); at = at + 2; i = -1;
        while i > k { store8(out + at, 48); at = at + 1; i = i - 1; }
        pb_copy(out + at, digits, n); at = at + n;
    } else {
        store8(out + at, load8(digits)); at = at + 1;
        if n > 1 { store8(out + at, 46); at = at + 1; pb_copy(out + at, digits + 1, n - 1); at = at + n - 1; }
        store8(out + at, 101); at = at + 1;
        if k < 0 { store8(out + at, 45); at = at + 1; k = -k; }
        let start = 32; i = start;
        while k { i = i - 1; store8(digits + i, 48 + k % 10); k = k / 10; }
        pb_copy(out + at, digits + i, start - i); at = at + start - i;
    }
    store8(out + at, 0); pn_size = at; return out;
}
