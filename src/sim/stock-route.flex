// Retrace executed commands and estimated poses. No map, scene geometry or
// live world pose enters this return controller. RGB still confirms home.
import "localization.flex";

global ps_route_nodes = 0;
global ps_route_home = 0;
global ps_route_count = 0;
global ps_route_cursor = -1;
global ps_route_pending = 0;
global ps_route_recorded = -1;
global ps_route_ready = 0;
global ps_route_error = 0;
global ps_route_heading_error = 0;

fn ps_route_reset() {
    ps_route_count = 0; ps_route_cursor = -1; ps_route_pending = 0; ps_route_recorded = -1; ps_route_ready = 0; ps_route_error = 0; ps_route_heading_error = 0; return 0;
}
fn ps_route_teach() {
    if !ps_stock_pickup { return 0; }
    if !ps_route_nodes { ps_route_nodes = alloc(60000 * 64); ps_route_home = alloc(24); }
    ps_route_reset(); store64(ps_route_home, ps_local_x); store64(ps_route_home + 8, ps_local_y); store64(ps_route_home + 16, ps_local_heading); ps_route_ready = 1; return 1;
}
fn ps_route_before_local() {
    ps_route_recorded = -1;
    if !ps_stock_pickup || !ps_route_ready { return 0; }
    if ps_stock_phase == 3 {
        if ps_route_pending { ps_route_cursor = ps_route_cursor - 1; ps_route_pending = 0; } return 0;
    }
    if ps_stock_phase != 2 && ps_stock_phase != 4 { return 0; }
    let d = pb_robot_drive(ps_robot); let speed = (load64(d + 48) + load64(d + 56)) / 2; if !speed { return 0; }
    if ps_route_count >= 60000 { return ps_stock_finish(5, "recorded return route capacity exceeded"); }
    let n = ps_route_nodes + ps_route_count * 64; store64(n, ps_local_x); store64(n + 8, ps_local_y); store64(n + 16, ps_local_heading);
    store64(n + 48, speed); store64(n + 56, load64(d + 64) - load64(d + 24)); ps_route_recorded = ps_route_count; ps_route_count = ps_route_count + 1; return 1;
}
fn ps_route_after_local() {
    if ps_route_recorded < 0 { return 0; } let n = ps_route_nodes + ps_route_recorded * 64;
    store64(n + 24, ps_local_x); store64(n + 32, ps_local_y); store64(n + 40, ps_local_heading); return 1;
}
fn ps_route_distance_home() {
    let dx = f64_sub(ps_local_x, load64(ps_route_home)); let dy = f64_sub(ps_local_y, load64(ps_route_home + 8)); return f64_sqrt(f64_add(f64_mul(dx, dx), f64_mul(dy, dy)));
}
fn ps_route_near_home() {
    if !ps_stock_pickup { return f64_gt(ps_stock_outbound, ps_number(6, 10)) && f64_lt(ps_stock_travel, ps_number(35, 100)); }
    return ps_route_ready && ps_route_cursor < 200 && f64_lt(ps_route_distance_home(), ps_number(35, 100)) && f64_lt(f64_magnitude(pb_wrap_pi(f64_sub(ps_local_heading, load64(ps_route_home + 16)))), ps_number(15, 100));
}
fn ps_route_begin() {
    if !ps_route_ready || !ps_route_count { return ps_case_fail("no driven route recorded before pickup"); }
    ps_route_cursor = ps_route_count - 1; ps_route_pending = 0; return 1;
}
fn ps_route_arrived() {
    if !ps_stock_pickup || !ps_route_ready { return 0; }
    ps_route_count = pb_max(0, ps_route_cursor + 1); ps_route_pending = 0;
    // Dock-search bounds are displacement along the learned staging view,
    // not accumulated signed distance across a route with many turns.
    ps_stock_travel = f64_add(f64_mul(f64_sub(ps_local_x, load64(ps_route_home)), f64_cos(load64(ps_route_home + 16))), f64_mul(f64_sub(ps_local_y, load64(ps_route_home + 8)), f64_sin(load64(ps_route_home + 16)))); return 1;
}
fn ps_route_tick() {
    let d = pb_robot_drive(ps_robot);
    if ps_blocked { return ps_stock_finish(5, "collision guard stopped recorded-route return"); }
    if ps_stock_matches { pb_drive_stop(d, ps_time); return 1; }
    if ps_route_cursor < 0 {
        // A small bounded visual search remains necessary: odometry never
        // authorizes arrival. The original stock-view gate must confirm it.
        if f64_gt(ps_route_distance_home(), ps_number(25, 100)) { return ps_stock_finish(5, "recorded route exhausted without a fresh home view"); }
        pb_drive_steer(d, -4, 0, ps_time); return 1;
    }
    let n = ps_route_nodes + ps_route_cursor * 64; let heading = load64(n + 40); let dx = f64_sub(ps_local_x, load64(n + 24)); let dy = f64_sub(ps_local_y, load64(n + 32));
    let lateral = f64_sub(f64_mul(f64_cos(heading), dy), f64_mul(f64_sin(heading), dx)); let speed = -load64(n + 48); let direction = 1; if speed < 0 { direction = -1; }
    ps_route_error = f64_sqrt(f64_add(f64_mul(dx, dx), f64_mul(dy, dy))); ps_route_heading_error = pb_wrap_pi(f64_sub(ps_local_heading, heading));
    if f64_gt(ps_route_error, ps_number(12, 100)) || f64_gt(f64_magnitude(ps_route_heading_error), ps_number(35, 100)) { return ps_stock_finish(5, "estimated pose left the recorded route corridor"); }
    let error = f64_add(ps_route_heading_error, f64_mul(f64_from_i64(direction * 3), lateral));
    let correction = f64_to_i64_nearest(f64_mul(error, f64_from_i64(direction * 100)));
    pb_drive_steer(d, speed, 0, ps_time); store64(d + 64, load64(d + 24) + pb_clamp(load64(n + 56) + correction, -45, 45)); ps_route_pending = 1; return 1;
}
fn ps_route_state(b) {
    pl_text(b, ",\"route\":{\"source\":\"executed-commands-and-estimated-poses\",\"mapInput\":false,\"oraclePose\":false,\"count\":"); pl_int(b, ps_route_count);
    pl_text(b, ",\"cursor\":"); pl_int(b, ps_route_cursor); pl_text(b, ",\"trackingErrorM\":"); pl_float(b, ps_route_error); pl_text(b, ",\"headingErrorRad\":"); pl_float(b, ps_route_heading_error); return pl_text(b, "}");
}
