// Hybrid A* over a known Blender floor map. Targets come from coverage poses
// or remembered home, never loose-object/body poses. Execute Ackermann drive
// commands; the existing swept chassis/wheel/arm guard remains authoritative.
import "vehicle.flex";
import "floor-memory.flex";

global ps_nav_map = 0;
global ps_nav_nodes = 0;
global ps_nav_heap = 0;
global ps_nav_path = 0;
global ps_nav_actions = 0;
global ps_nav_columns = 0;
global ps_nav_rows = 0;
global ps_nav_cells = 0;
global ps_nav_capacity = 0;
global ps_nav_heap_count = 0;
global ps_nav_path_count = 0;
global ps_nav_path_index = 0;
global ps_nav_remaining = 0;
global ps_nav_expanded = 0;
global ps_nav_plans = 0;
global ps_nav_goal = 0;

fn ps_nav_cell(x, y) {
    let ix = f64_to_i64_trunc(f64_mul(f64_sub(x, load64(ps_environment + 64)), f64_from_i64(10)));
    let iy = f64_to_i64_trunc(f64_mul(f64_sub(y, load64(ps_environment + 72)), f64_from_i64(10)));
    if ix < 0 || iy < 0 || ix >= ps_nav_columns || iy >= ps_nav_rows || !ps_environment_inside(x, y) { return -1; }
    return iy * ps_nav_columns + ix;
}
fn ps_nav_index(x, y, heading) {
    let cell = ps_nav_cell(x, y); if cell < 0 { return -1; }
    let angle = f64_add(pb_wrap_pi(heading), PB_PI); let bucket = f64_to_i64_nearest(f64_div(f64_mul(angle, f64_from_i64(32)), f64_mul(PB_PI, f64_from_i64(2)))) % 32;
    return cell * 32 + bucket;
}
fn ps_nav_clear(x, y, heading) {
    if !ps_floor_clear(x, y, heading) { return 0; }
    let cell = ps_nav_cell(x, y); if cell < 0 || load8(ps_nav_map + cell) { return 0; }
    if ps_house_returning == 3 {
        let dx = f64_sub(load64(ps_case_target), x); let dy = f64_sub(load64(ps_case_target + 8), y); let c = f64_cos(heading); let s = f64_sin(heading);
        let along = f64_magnitude(f64_add(f64_mul(c, dx), f64_mul(s, dy))); let across = f64_magnitude(f64_sub(f64_mul(c, dy), f64_mul(s, dx)));
        if f64_lt(along, ps_number(19, 100)) && f64_lt(across, ps_number(14, 100)) { return 0; }
    }
    if ps_house_ready && ps_dock_seen >= 0 {
        let dx = f64_sub(x, load64(ps_dock_frame + 96)); let dy = f64_sub(y, load64(ps_dock_frame + 104));
        let co = load64(ps_dock_frame); let si = load64(ps_dock_frame + 8);
        let lx = f64_magnitude(f64_add(f64_mul(co, dx), f64_mul(si, dy))); let ly = f64_magnitude(f64_sub(f64_mul(co, dy), f64_mul(si, dx)));
        let angle = f64_sub(heading, ps_dock_yaw); let c = f64_magnitude(f64_cos(angle)); let s = f64_magnitude(f64_sin(angle));
        let hx = f64_add(f64_add(f64_mul(load64(ps_case_bin + 24), ps_number(1, 2)), load64(ps_case_bin + 48)), f64_add(f64_mul(c, ps_number(15, 100)), f64_mul(s, ps_number(12, 100))));
        let hy = f64_add(f64_add(f64_mul(load64(ps_case_bin + 32), ps_number(1, 2)), load64(ps_case_bin + 48)), f64_add(f64_mul(c, ps_number(12, 100)), f64_mul(s, ps_number(15, 100))));
        if f64_lt(lx, hx) && f64_lt(ly, hy) { return 0; }
    }
    return 1;
}
fn ps_nav_init() {
    if !ps_environment { return 0; }
    ps_nav_columns = f64_to_i64_nearest(f64_mul(f64_sub(load64(ps_environment + 80), load64(ps_environment + 64)), f64_from_i64(10)));
    ps_nav_rows = f64_to_i64_nearest(f64_mul(f64_sub(load64(ps_environment + 88), load64(ps_environment + 72)), f64_from_i64(10)));
    let cells = ps_nav_columns * ps_nav_rows; if cells < 1 || cells > 20000 { return 0; }
    if !ps_nav_map {
        ps_nav_cells = cells; ps_nav_capacity = cells * 32; ps_nav_map = alloc(cells); ps_nav_nodes = alloc(ps_nav_capacity * 80); ps_nav_heap = alloc(ps_nav_capacity * 8);
        ps_nav_path = alloc(2048 * 8); ps_nav_actions = alloc(6 * 128); ps_nav_goal = alloc(24);
    }
    if cells != ps_nav_cells { return 0; } ps_nav_plans = 0;
    let cell = 0; let radius = ps_number(28, 100);
    while cell < cells {
        let x = f64_add(load64(ps_environment + 64), ps_number((cell % ps_nav_columns) * 2 + 1, 20));
        let y = f64_add(load64(ps_environment + 72), ps_number((cell / ps_nav_columns) * 2 + 1, 20));
        let blocked = f64_lt(f64_sub(x, radius), load64(ps_environment + 64)) || f64_gt(f64_add(x, radius), load64(ps_environment + 80)) || f64_lt(f64_sub(y, radius), load64(ps_environment + 72)) || f64_gt(f64_add(y, radius), load64(ps_environment + 88)); let i = 0;
        while !blocked && i < ps_environment_count {
            let r = ps_environment + 256 + i * 128;
            // Stowed robot fits beneath the dining tabletop. Low tops, seats,
            // legs, walls and shelves occupy the map independently.
            if f64_lt(f64_sub(load64(r + 64), load64(r + 88)), ps_number(55, 100)) {
                let c = f64_cos(load64(r + 96)); let s = f64_sin(load64(r + 96)); let dx = f64_sub(x, load64(r + 48)); let dy = f64_sub(y, load64(r + 56));
                let lx = f64_add(f64_mul(c, dx), f64_mul(s, dy)); let ly = f64_sub(f64_mul(c, dy), f64_mul(s, dx));
                let ax = pb_fmax(f64_sub(f64_magnitude(lx), load64(r + 72)), 0); let ay = pb_fmax(f64_sub(f64_magnitude(ly), load64(r + 80)), 0);
                blocked = f64_lt(f64_add(f64_mul(ax, ax), f64_mul(ay, ay)), f64_mul(radius, radius));
            } i = i + 1;
        }
        store8(ps_nav_map + cell, blocked); cell = cell + 1;
    }
    let action = 0;
    while action < 6 {
        let r = ps_nav_actions + action * 128; let steer = (action % 3 - 1) * 60; let direction = 1; if action >= 3 { direction = -1; }
        store64(r, steer); store64(r + 8, direction); let angle = pb_radians(f64_from_i64(steer * 45 / 100));
        let turn = pb_neg(f64_mul(ps_number(direction, 30), f64_div(f64_sin(angle), f64_cos(angle))));
        let x = 0; let y = 0; let h = 0; let tick = 1;
        while tick <= 20 {
            h = pb_wrap_pi(f64_add(h, turn)); x = f64_add(x, f64_mul(ps_number(direction * 6, 1000), f64_cos(h))); y = f64_add(y, f64_mul(ps_number(direction * 6, 1000), f64_sin(h)));
            if tick % 4 == 0 { store64(r + 24 + (tick / 4 - 1) * 16, x); store64(r + 32 + (tick / 4 - 1) * 16, y); } tick = tick + 1;
        }
        store64(r + 16, h); action = action + 1;
    }
    return 1;
}
fn ps_nav_heap_swap(a, b) {
    let first = load64(ps_nav_heap + a * 8); let second = load64(ps_nav_heap + b * 8); store64(ps_nav_heap + a * 8, second); store64(ps_nav_heap + b * 8, first);
    store64(ps_nav_nodes + first * 80 + 72, b); store64(ps_nav_nodes + second * 80 + 72, a); return 0;
}
fn ps_nav_less(a, b) { return f64_lt(load64(ps_nav_nodes + load64(ps_nav_heap + a * 8) * 80 + 32), load64(ps_nav_nodes + load64(ps_nav_heap + b * 8) * 80 + 32)); }
fn ps_nav_heap_up(at) {
    while at > 0 { let parent = (at - 1) / 2; if !ps_nav_less(at, parent) { return 0; } ps_nav_heap_swap(at, parent); at = parent; } return 0;
}
fn ps_nav_heap_down(at) {
    while at * 2 + 1 < ps_nav_heap_count {
        let next = at * 2 + 1; if next + 1 < ps_nav_heap_count && ps_nav_less(next + 1, next) { next = next + 1; }
        if !ps_nav_less(next, at) { at = ps_nav_heap_count; } else { ps_nav_heap_swap(at, next); at = next; }
    }
    return 0;
}
fn ps_nav_pop() {
    let result = load64(ps_nav_heap); ps_nav_heap_count = ps_nav_heap_count - 1;
    if ps_nav_heap_count {
        let last = load64(ps_nav_heap + ps_nav_heap_count * 8); store64(ps_nav_heap, last); store64(ps_nav_nodes + last * 80 + 72, 0); ps_nav_heap_down(0);
    }
    store64(ps_nav_nodes + result * 80 + 64, 2); return result;
}
fn ps_nav_distance(x, y) { let dx = f64_sub(x, load64(ps_nav_goal)); let dy = f64_sub(y, load64(ps_nav_goal + 8)); return f64_sqrt(f64_add(f64_mul(dx, dx), f64_mul(dy, dy))); }
fn ps_nav_offer(index, x, y, heading, cost, parent, action) {
    let r = ps_nav_nodes + index * 80; let state = load64(r + 64); if state == 2 || (state && !f64_lt(cost, load64(r + 24))) { return 0; }
    store64(r, x); store64(r + 8, y); store64(r + 16, heading); store64(r + 24, cost);
    store64(r + 32, f64_add(cost, f64_add(f64_mul(ps_number(15, 10), ps_nav_distance(x, y)), f64_mul(ps_number(18, 100), f64_magnitude(pb_wrap_pi(f64_sub(heading, load64(ps_nav_goal + 16))))))));
    store64(r + 40, parent); store64(r + 48, action);
    if !state { store64(r + 64, 1); store64(r + 72, ps_nav_heap_count); store64(ps_nav_heap + ps_nav_heap_count * 8, index); ps_nav_heap_count = ps_nav_heap_count + 1; }
    // A better continuous pose in the same lattice cell can increase its
    // heuristic even while reducing travel cost. Repair in both directions.
    ps_nav_heap_up(load64(r + 72)); ps_nav_heap_down(load64(r + 72)); return 0;
}
fn ps_nav_plan(x, y, heading) {
    ps_nav_plans = ps_nav_plans + 1; store64(ps_nav_goal, x); store64(ps_nav_goal + 8, y); store64(ps_nav_goal + 16, pb_wrap_pi(heading));
    ps_nav_path_count = 0; ps_nav_path_index = 0; ps_nav_remaining = 0; ps_nav_heap_count = 0; ps_nav_expanded = 0;
    if !ps_nav_clear(x, y, heading) { return 0; } pb_zero(ps_nav_nodes, ps_nav_capacity * 80); let start = ps_nav_index(ps_pose_x(), ps_pose_y(), ps_pose_heading()); if start < 0 { return 0; }
    ps_nav_offer(start, ps_pose_x(), ps_pose_y(), ps_pose_heading(), 0, -1, 0); let found = -1;
    while ps_nav_heap_count && ps_nav_expanded < 60000 && found < 0 {
        let index = ps_nav_pop(); let r = ps_nav_nodes + index * 80; ps_nav_expanded = ps_nav_expanded + 1;
        if f64_lt(ps_nav_distance(load64(r), load64(r + 8)), ps_number(10, 100)) && f64_lt(f64_magnitude(pb_wrap_pi(f64_sub(load64(r + 16), heading))), ps_number(22, 100)) { found = index; }
        let c = f64_cos(load64(r + 16)); let s = f64_sin(load64(r + 16)); let action = 0;
        while action < 6 {
            let a = ps_nav_actions + action * 128; let sample = 0; let clear = 1; let nx = 0; let ny = 0;
            while sample < 5 && clear {
                let dx = load64(a + 24 + sample * 16); let dy = load64(a + 32 + sample * 16);
                nx = f64_add(load64(r), f64_sub(f64_mul(c, dx), f64_mul(s, dy))); ny = f64_add(load64(r + 8), f64_add(f64_mul(s, dx), f64_mul(c, dy)));
                clear = ps_nav_clear(nx, ny, f64_add(load64(r + 16), f64_mul(load64(a + 16), ps_number(sample + 1, 5)))); sample = sample + 1;
            }
            if clear {
                let nh = pb_wrap_pi(f64_add(load64(r + 16), load64(a + 16))); let next = ps_nav_index(nx, ny, nh); let cost = ps_number(12, 100); if action >= 3 { cost = ps_number(18, 100); } if action % 3 != 1 { cost = f64_add(cost, ps_number(1, 100)); }
                if next >= 0 { ps_nav_offer(next, nx, ny, nh, f64_add(load64(r + 24), cost), index, action); }
            } action = action + 1;
        }
    }
    if found < 0 { return 0; }
    while load64(ps_nav_nodes + found * 80 + 40) >= 0 {
        if ps_nav_path_count >= 2048 { return 0; } store64(ps_nav_path + ps_nav_path_count * 8, load64(ps_nav_nodes + found * 80 + 48)); ps_nav_path_count = ps_nav_path_count + 1; found = load64(ps_nav_nodes + found * 80 + 40);
    }
    return 1;
}
fn ps_nav_tick() {
    if ps_nav_remaining > 0 { ps_nav_remaining = ps_nav_remaining - 1; if !ps_nav_remaining { ps_nav_path_index = ps_nav_path_index + 1; } }
    if ps_nav_path_index >= ps_nav_path_count { pb_drive_stop(pb_robot_drive(ps_robot), ps_time); return 1; }
    if !ps_nav_remaining {
        let action = load64(ps_nav_path + (ps_nav_path_count - 1 - ps_nav_path_index) * 8); let r = ps_nav_actions + action * 128;
        pb_drive_steer(pb_robot_drive(ps_robot), load64(r + 8) * 60, load64(r), ps_time); ps_nav_remaining = 20;
    } else {
        // Refresh the production controller watchdog during long primitives.
        let d = pb_robot_drive(ps_robot); store64(d + 80, ps_time);
    }
    return 0;
}
