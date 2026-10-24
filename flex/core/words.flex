// Portable word helpers; these modules contain no host I/O.
import "../vendor/f64-math.flex";
import "packed.flex";

// Linux uses exact binary64 instructions; other targets keep portable bodies.
lowering f64_add "f64.add" "native-x86_64";
lowering f64_sub "f64.sub" "native-x86_64";
lowering f64_mul "f64.mul" "native-x86_64";
lowering f64_div "f64.div" "native-x86_64";
lowering f64_sqrt "f64.sqrt" "native-x86_64";

global PB_PI = 0x400921fb54442d18;
global PB_TAU = 0x401921fb54442d18;
global PB_HALF_PI = 0x3ff921fb54442d18;
global PB_ONE = 0x3ff0000000000000;
global PB_EPSILON = 0x3cb0000000000000;

fn pb_abs(n) { if n < 0 { return -n; } return n; }
fn pb_sign(n) { if n > 0 { return 1; } if n < 0 { return -1; } return 0; }
fn pb_min(a, b) { if a < b { return a; } return b; }
fn pb_max(a, b) { if a > b { return a; } return b; }
fn pb_clamp(n, lo, hi) { return pb_min(pb_max(n, lo), hi); }
fn pb_elapsed(now, before) { return pb_max(now - before, 0); }
fn pb_unsigned_ge(a, b) { return (a ^ 0x8000000000000000) >= (b ^ 0x8000000000000000); }
fn pb_i8(n) { return (n & 255) - ((n & 128) << 1); }
fn pb_i16(n) { return (n & 65535) - ((n & 32768) << 1); }
fn pb_i32(n) { return (n & 0xffffffff) - ((n & 0x80000000) << 1); }
fn pb_copy(out, source, n) { let i = 0; while i < n { store8(out + i, load8(source + i)); i = i + 1; } return n; }
fn pb_zero(out, n) { let i = 0; while i < n { store8(out + i, 0); i = i + 1; } return 0; }
fn pb_neg(x) { return x ^ 0x8000000000000000; }
fn pb_fmin(a, b) { if f64_lt(a, b) { return a; } return b; }
fn pb_fmax(a, b) { if f64_gt(a, b) { return a; } return b; }
fn pb_fclamp(x, lo, hi) { return pb_fmin(pb_fmax(x, lo), hi); }
fn pb_wrap_pi(angle) {
    // Reject nonfinite values before the bounded joint math reaches here.
    if !f64_is_finite(angle) { return f64_nan(); }
    while f64_gt(angle, PB_PI) { angle = f64_sub(angle, PB_TAU); }
    while f64_lt(angle, pb_neg(PB_PI)) { angle = f64_add(angle, PB_TAU); }
    return angle;
}
fn pb_degrees(angle) { return f64_div(f64_mul(pb_wrap_pi(angle), 0x4066800000000000), PB_PI); }
fn pb_radians(degrees) { if !f64_is_finite(degrees) { return degrees; } return f64_div(f64_mul(degrees, PB_PI), 0x4066800000000000); }
fn pb_vget(p, index) { return load64(p + index * 8); }
fn pb_vset(p, index, value) { store64(p + index * 8, value); return value; }
fn pb_length3(p) { return f64_sqrt(f64_add(f64_add(f64_mul(pb_vget(p, 0), pb_vget(p, 0)), f64_mul(pb_vget(p, 1), pb_vget(p, 1))), f64_mul(pb_vget(p, 2), pb_vget(p, 2)))); }
