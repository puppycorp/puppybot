// Exercise the real observed-floor guard with one blocked coarse cell at a
// time. The caller supplies no robot, camera, or simulated environment.
fn main(argc, argv) {
    if !pl_init() { return 1; }
    ps_discovery_enabled = 1; ps_nav_columns = 200; ps_nav_rows = 200;
    ps_discovery_observed = alloc(40000); pb_zero(ps_discovery_observed, 40000);
    ps_discovery_detail = alloc(1000000); pb_zero(ps_discovery_detail, 1000000);
    let output = alloc(65536); let b = alloc(32); pl_builder(b, output, 65536);
    let angle = 0;
    while angle < 360 {
        let px = 0;
        while px <= 80 { let py = 0;
            while py <= 80 { let row = 98;
                while row <= 102 { let column = 98;
                    while column <= 102 {
                        let cell = row * 200 + column; store8(ps_discovery_observed + cell, 1);
                        let clear = ps_nav_observed_clear(ps_number(px, 1000), ps_number(py, 1000), f64_mul(PB_PI, ps_number(angle, 180)));
                        pl_char(b, 48 + clear); store8(ps_discovery_observed + cell, 0); column = column + 1;
                    } row = row + 1;
                } py = py + 20;
            } px = px + 20;
        } angle = angle + 5;
    }
    pl_char(b, 10);
    let x = ps_number(15, 1000); let y = ps_number(85, 1000); let heading = f64_mul(PB_PI, ps_number(5, 180));
    store8(ps_discovery_observed + 102 * 200 + 99, 1);
    pl_char(b, 48 + ps_nav_observed_clear(x, y, heading)); ps_discovery_detail_ready = 1;
    pl_char(b, 48 + ps_nav_observed_clear(x, y, heading));
    store8(ps_discovery_detail + 510 * 1000 + 499, 1);
    pl_char(b, 48 + ps_nav_observed_clear(x, y, heading));
    store8(ps_discovery_detail + 510 * 1000 + 499, 0); store8(ps_discovery_detail + 514 * 1000 + 495, 1);
    pl_char(b, 48 + ps_nav_observed_clear(x, y, heading));
    pl_char(b, 48 + ps_nav_observed_clear(ps_number(999, 100), 0, 0));
    pb_zero(ps_discovery_observed, 40000); store8(ps_discovery_detail + 510 * 1000 + 499, 1);
    pl_char(b, 48 + ps_nav_observed_clear(x, y, heading)); pl_char(b, 10);
    if argc == 2 {
        pl_char(b, 48 + ps_nav_observed_clear(f64_nan(), y, heading));
        pl_char(b, 48 + ps_nav_observed_clear(x, f64_nan(), heading));
        pl_char(b, 48 + ps_nav_observed_clear(x, y, f64_nan()));
        pl_char(b, 48 + ps_nav_observed_clear(0x7ff0000000000000, y, heading)); pl_char(b, 10);
    }
    pl_print(1, output); return 0;
}
