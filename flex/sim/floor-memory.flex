// Loose floor obstacles remembered from RGB camera rays, never body IDs.
import "localization.flex";

global ps_floor_points = 0;
global ps_floor_count = 0;
global ps_floor_changed = 0;
global ps_floor_approach = 0;

fn ps_floor_reset() { ps_floor_count = 0; ps_floor_changed = 0; ps_floor_approach = 0; return 0; }
fn ps_floor_near(x, y, point, radius) {
    let dx = f64_sub(x, load64(point)); let dy = f64_sub(y, load64(point + 8)); return f64_lt(f64_add(f64_mul(dx, dx), f64_mul(dy, dy)), f64_mul(radius, radius));
}
fn ps_floor_confirmed(target) {
    let i = 0;
    while i < ps_floor_count {
        let p = ps_floor_points + i * 32;
        if load64(p + 16) >= 3 && ps_floor_near(load64(target), load64(target + 8), p, ps_number(7, 100)) { return 1; } i = i + 1;
    } return 0;
}
fn ps_floor_observe() {
    if !ps_stock_pickup { return 0; } if !ps_floor_points { ps_floor_points = alloc(128 * 32); } let i = 0;
    while i < ps_brick_count {
        let r = ps_brick_records + i * 128; let x = load64(r + 32); let y = load64(r + 40);
        let ahead = f64_add(f64_mul(f64_sub(x, ps_local_x), f64_cos(ps_local_heading)), f64_mul(f64_sub(y, ps_local_y), f64_sin(ps_local_heading)));
        if f64_ge(ahead, ps_number(16, 100)) && f64_le(ahead, ps_number(12, 10)) && ps_house_filter(x, y) && ps_house_detection(i) {
            let index = -1; let j = 0;
            while j < ps_floor_count { if ps_floor_near(x, y, ps_floor_points + j * 32, ps_number(6, 100)) { index = j; } j = j + 1; }
            if index < 0 && ps_floor_count < 128 { index = ps_floor_count; ps_floor_count = ps_floor_count + 1; pb_zero(ps_floor_points + index * 32, 32); }
            if index >= 0 && (!load64(ps_floor_points + index * 32 + 16) || load64(ps_floor_points + index * 32 + 24) != ps_total) {
                let p = ps_floor_points + index * 32; let count = load64(p + 16);
                if count { store64(p, f64_mul(f64_add(load64(p), x), ps_number(1, 2))); store64(p + 8, f64_mul(f64_add(load64(p + 8), y), ps_number(1, 2))); }
                else { store64(p, x); store64(p + 8, y); }
                store64(p + 16, pb_min(1000, count + 1)); store64(p + 24, ps_total); if count == 2 { ps_floor_changed = 1; }
            }
        } i = i + 1;
    }
    return 1;
}
fn ps_floor_forget(target) {
    let i = 0;
    while i < ps_floor_count {
        if ps_floor_near(load64(target), load64(target + 8), ps_floor_points + i * 32, ps_number(7, 100)) {
            ps_floor_count = ps_floor_count - 1; pb_copy(ps_floor_points + i * 32, ps_floor_points + ps_floor_count * 32, 32);
        } else { i = i + 1; }
    } return 1;
}
fn ps_floor_clear(x, y, heading) {
    if !ps_stock_pickup { return 1; } let c = f64_cos(heading); let s = f64_sin(heading); let i = 0;
    while i < ps_floor_count {
        let p = ps_floor_points + i * 32; let ignore = (ps_floor_approach || ps_house_returning == 3) && ps_floor_near(load64(ps_case_target), load64(ps_case_target + 8), p, ps_number(7, 100));
        if load64(p + 16) >= 3 && !ignore {
            let dx = f64_sub(load64(p), x); let dy = f64_sub(load64(p + 8), y);
            let along = f64_magnitude(f64_add(f64_mul(c, dx), f64_mul(s, dy))); let across = f64_magnitude(f64_sub(f64_mul(c, dy), f64_mul(s, dx)));
            if f64_lt(along, ps_number(19, 100)) && f64_lt(across, ps_number(15, 100)) { return 0; }
        } i = i + 1;
    } return 1;
}
