#!/usr/bin/env python3
"""Exercise recorded-route steering through turns with unusable world/map inputs."""
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def main():
    source = (ROOT/'flex/sim/main.flex').read_text().replace('fn main(argc, argv)', 'fn ps_application_main(argc, argv)')
    source = re.sub(r'^import "([^"]+)";', lambda m: f'import "{ROOT / "flex/sim" / m[1]}";', source, flags=re.MULTILINE)
    source += r'''
fn drive_segment(speed, steer, ticks) {
    let d = pb_robot_drive(ps_robot); let i = 0;
    while i < ticks { pb_drive_steer(d, speed, steer, ps_time); ps_route_before_local(); ps_local_step(); ps_route_after_local(); i = i + 1; } return 1;
}
fn return_route() {
    if !ps_route_begin() { return 0; } ps_stock_phase = 3; let ticks = 0;
    while ps_route_cursor >= 0 && ticks < 10000 {
        if !ps_route_tick() { return 0; } ps_route_before_local(); ps_local_step(); ps_route_after_local(); ticks = ticks + 1;
    }
    if ps_route_cursor >= 0 || f64_gt(ps_route_distance_home(), ps_number(2, 100)) || f64_gt(f64_magnitude(ps_local_heading), ps_number(2, 100)) { return 0; }
    ps_stock_finish(4, "probe home"); return 1;
}
fn main() {
    pl_init(); ps_robot = alloc(8192); pb_drive_init(pb_robot_drive(ps_robot), 0);
    ps_stock_pickup = 1; ps_stock_enabled = 1; ps_local_mode = 1; ps_route_teach(); ps_stock_phase = 2;
    // Any dependency on live truth, collider lists or map planning would fail.
    ps_x = f64_from_i64(999); ps_y = f64_from_i64(-999); ps_heading = f64_from_i64(2);
    ps_environment = 1; ps_environment_start = 1; ps_world_matrices = 1; ps_tcp = 1; ps_physics = 1; ps_nav_nodes = 1;
    drive_segment(60, 0, 120); drive_segment(60, -60, 100); drive_segment(-30, 40, 45); drive_segment(20, 0, 70);
    if ps_route_count != 335 || !return_route() { return 1; }
    // Dock search and the second trip must retain a continuous route home.
    drive_segment(-4, 0, 100); drive_segment(60, 0, 100); drive_segment(60, 60, 140); drive_segment(-40, -60, 80);
    ps_local_y = f64_add(ps_local_y, ps_number(1, 100)); ps_local_heading = f64_add(ps_local_heading, ps_number(1, 100));
    if !return_route() { return 2; }
    // Reaching the route origin alone must never mark the stock view matched.
    ps_stock_phase = 3; ps_stock_matches = 0; ps_route_cursor = -1;
    if !ps_route_tick() || ps_stock_phase != 3 { return 3; }
    // Stale camera results stop movement without consuming the next entry.
    ps_route_cursor = 10; ps_route_pending = 0; ps_stock_frame = 0; ps_total = 100; ps_stock_start = 100; ps_live_state = "ready";
    ps_stock_update(); ps_route_before_local();
    if load64(pb_robot_drive(ps_robot) + 48) || ps_route_cursor != 10 { return 4; }
    ps_route_reset(); if ps_route_count || ps_route_ready || ps_route_pending || ps_route_cursor != -1 { return 5; }
    pl_print(1, "Route guards passed: turns, reverse approaches, second trip with dock motion, tracking disturbance, visual arrival requirement, stale camera stop, reset and poisoned truth/map\n"); return 0;
}
'''
    with tempfile.TemporaryDirectory(prefix='route-probe-', dir=ROOT/'build/flex/sim') as temporary:
        directory = Path(temporary)
        entry, binary = directory/'probe.flex', directory/'probe'
        entry.write_text(source)
        env = dict(os.environ, FLEXSCRIPT_ROOT=os.environ.get('FLEXSCRIPT_ROOT', str(ROOT.parent/'flexscript')))
        subprocess.run([str(ROOT/'build/flex/pup-compiler'), str(entry), '-o', str(binary)], cwd=ROOT, env=env, check=True)
        subprocess.run([str(binary)], cwd=ROOT, check=True)


if __name__ == '__main__':
    main()
