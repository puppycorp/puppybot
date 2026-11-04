// Seeded floor layouts are generated in Flexscript before bodies are created.
import "catalog.flex";

global ps_case_seed = 42;
global ps_layout_rng = 0;
global ps_layout_scratch = 0;

fn ps_layout_unit() {
    ps_layout_rng = (ps_layout_rng * 1664525 + 1013904223) & 0xffffffff; return ps_number(ps_layout_rng, 4294967296);
}
fn ps_layout_box_clear(x, y, radius, bx, by, hx, hy) {
    let dx = pb_fmax(f64_sub(f64_magnitude(f64_sub(x, bx)), hx), 0); let dy = pb_fmax(f64_sub(f64_magnitude(f64_sub(y, by)), hy), 0);
    return f64_gt(f64_add(f64_mul(dx, dx), f64_mul(dy, dy)), f64_mul(radius, radius));
}
fn ps_layout_clear(index, x, y, radius, spawn, bin) {
    let padding = load64(spawn + 32); let guard = f64_add(radius, padding);
    if !ps_layout_box_clear(x, y, guard, 0, 0, ps_number(14, 100), ps_number(12, 100)) { return 0; }
    if !ps_layout_box_clear(x, y, guard, ps_number(65, 100), ps_number(-35, 100), ps_number(12, 100), ps_number(12, 100)) { return 0; }
    if !ps_layout_box_clear(x, y, guard, ps_number(-55, 100), ps_number(45, 100), ps_number(10, 100), ps_number(18, 100)) { return 0; }
    let hx = f64_add(f64_mul(load64(bin + 24), ps_number(1, 2)), load64(bin + 48)); let hy = f64_add(f64_mul(load64(bin + 32), ps_number(1, 2)), load64(bin + 48));
    if !ps_layout_box_clear(x, y, guard, load64(bin), load64(bin + 8), hx, hy) { return 0; }
    let i = 0;
    while i < index {
        let r = ps_layout_scratch + i * 32; let dx = f64_sub(x, load64(r)); let dy = f64_sub(y, load64(r + 8)); let distance = f64_add(guard, load64(r + 24));
        if f64_lt(f64_add(f64_mul(dx, dx), f64_mul(dy, dy)), f64_mul(distance, distance)) { return 0; } i = i + 1;
    }
    return 1;
}
fn ps_layout_generate(records, count, bin, spawn, seed) {
    if !ps_layout_scratch { ps_layout_scratch = alloc(8 * 32); } ps_layout_rng = seed; let index = 0; let attempts = 0;
    while index < count && attempts < 4096 {
        let r = records + index * 256; let hx = load64(r + 96); let hy = load64(r + 104); let radius = f64_sqrt(f64_add(f64_mul(hx, hx), f64_mul(hy, hy)));
        let x = f64_add(load64(spawn), f64_mul(ps_layout_unit(), f64_sub(load64(spawn + 16), load64(spawn))));
        let y = f64_add(load64(spawn + 8), f64_mul(ps_layout_unit(), f64_sub(load64(spawn + 24), load64(spawn + 8))));
        let yaw = f64_mul(f64_sub(f64_mul(ps_layout_unit(), f64_from_i64(2)), PB_ONE), load64(spawn + 40));
        // Rotated corners stay within the configured region, with extra
        // spacing for a finger to reach either side of every brick.
        if f64_ge(f64_sub(x, radius), load64(spawn)) && f64_le(f64_add(x, radius), load64(spawn + 16)) && f64_ge(f64_sub(y, radius), load64(spawn + 8)) && f64_le(f64_add(y, radius), load64(spawn + 24)) && ps_layout_clear(index, x, y, radius, spawn, bin) {
            let out = ps_layout_scratch + index * 32; store64(out, x); store64(out + 8, y); store64(out + 16, yaw); store64(out + 24, radius); index = index + 1;
        }
        attempts = attempts + 1;
        // Restart an unlucky partial packing instead of biasing the last
        // object's distribution or ever relaxing the clearance.
        if attempts % 256 == 0 && index < count { index = 0; }
    }
    if index != count { return 0; }
    index = 0;
    while index < count {
        let out = records + index * 256; let r = ps_layout_scratch + index * 32; store64(out + 72, load64(r)); store64(out + 80, load64(r + 8)); store64(out + 88, f64_add(load64(out + 112), ps_number(1, 1000))); store64(out + 200, load64(r + 16)); index = index + 1;
    }
    return 1;
}

fn ps_layout_reset() {
    if !ps_case_random { return 1; } return ps_layout_generate(ps_case_objects, ps_case_count, ps_case_bin, ps_case_spawn, ps_case_seed);
}
