// A Manhattan-world heading observation from existing RGB floorboard lines.
// Joint-calibrated ground projection supplies local directions. The caller
// associates them with wall axes from the supplied map; no live pose is read.
import "breadcrumb-features.flex";

global ps_ground_heading = 0;
global ps_ground_confidence = 0;
global ps_ground_samples = 0;

fn ps_ground_heading_read() {
    ps_ground_heading = 0; ps_ground_confidence = 0; ps_ground_samples = 0; ps_cf_floor_only = 1;
    let real = 0; let imag = 0; let weight = 0; let x = 200000;
    while x < 1100000 { let y = -480000;
        while y < 480000 {
            let a = ps_cf_intensity(x + 4000, y); let b = ps_cf_intensity(x - 4000, y);
            let c = ps_cf_intensity(x, y + 4000); let d = ps_cf_intensity(x, y - 4000);
            if a >= 0 && b >= 0 && c >= 0 && d >= 0 {
                let gx = (a - b) / 1000; let gy = (c - d) / 1000; let xx = gx * gx; let yy = gy * gy; let power = xx + yy;
                if power > 9 {
                    // Fourth angular moment identifies perpendicular floor
                    // lines equally. Cap edge weights so lettering cannot
                    // dominate many weaker board/grid edges.
                    let w = pb_min(power, 100); let norm = power * power;
                    real = real + w * ((xx * xx - 6 * xx * yy + yy * yy) * 1000000 / norm);
                    imag = imag + w * (4 * gx * gy * (xx - yy) * 1000000 / norm);
                    weight = weight + w; ps_ground_samples = ps_ground_samples + 1;
                }
            }
            y = y + 17000;
        }
        x = x + 17000;
    }
    ps_cf_floor_only = 0; if ps_ground_samples < 80 || !weight { return 0; }
    let r = f64_from_i64(real); let i = f64_from_i64(imag);
    ps_ground_confidence = f64_div(f64_sqrt(f64_add(f64_mul(r, r), f64_mul(i, i))), f64_from_i64(weight * 1000000));
    ps_ground_heading = f64_mul(ps_number(1, 4), f64_atan2(i, r)); return f64_gt(ps_ground_confidence, ps_number(7, 10));
}
