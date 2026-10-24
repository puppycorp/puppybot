#!/usr/bin/env python3
"""Verify RGB obstacle memory rejects the loose-brick collision pose."""
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
fn main() {
    pl_init(); ps_stock_pickup = 1; ps_local_mode = 1; ps_local_x = ps_number(57, 10); ps_local_y = ps_number(4, 10);
    ps_house_home = alloc(24); store64(ps_house_home, ps_number(37, 10)); ps_case_target = alloc(24); ps_brick_records = alloc(128); ps_brick_count = 1;
    let r = ps_brick_records; store64(r, 100); store64(r + 8, 100); store64(r + 16, 120); store64(r + 24, 120);
    store64(r + 32, ps_number(635, 100)); store64(r + 40, ps_number(4, 10)); pb_copy(ps_case_target, r + 32, 24);
    ps_environment = 1; ps_physics = 1; ps_nav_nodes = 1; ps_x = f64_from_i64(999); ps_y = f64_from_i64(-999); ps_world_matrices = 1;
    ps_total = 1; ps_floor_observe(); ps_floor_observe();
    if ps_floor_count != 1 || load64(ps_floor_points + 16) != 1 || ps_floor_changed { return 1; }
    ps_total = 2; ps_floor_observe(); ps_total = 3; ps_floor_observe();
    if !ps_floor_changed || load64(ps_floor_points + 16) != 3 { return 2; }
    // Recorded wheel-collision pose: yellow brick was behind the rover.
    if ps_floor_clear(ps_number(65123, 10000), ps_number(42095, 100000), ps_number(-42464, 100000)) { return 3; }
    if !ps_floor_clear(ps_number(67, 10), ps_number(7, 10), 0) { return 4; }
    ps_floor_approach = 1;
    if !ps_floor_clear(ps_number(635, 100), ps_number(4, 10), 0) { return 5; }
    ps_floor_approach = 0; ps_floor_forget(ps_case_target); if ps_floor_count { return 6; }
    ps_floor_reset(); if ps_floor_changed || ps_floor_count { return 7; }
    // Reproduce the blocked coverage goal with the declared static map.
    // Live world/body inputs remain unusable; this planner is map-assisted.
    ps_environment = 0; ps_nav_nodes = 0;
    if !ps_environment_load("build/flex/sim/environments/apartment/apartment.bin") || !ps_nav_init() { return 8; }
    ps_local_x = ps_number(662785, 100000); ps_local_y = ps_number(149212, 100000); ps_local_heading = ps_number(152828, 100000);
    ps_floor_count = 1; store64(ps_floor_points, ps_number(52, 10)); store64(ps_floor_points + 8, ps_number(145, 100)); store64(ps_floor_points + 16, 3);
    let goal = alloc(24); store64(goal, ps_number(52, 10)); store64(goal + 8, ps_number(15, 10)); store64(goal + 16, PB_PI);
    if ps_nav_plan(load64(goal), load64(goal + 8), PB_PI) { return 9; }
    if !ps_house_plan_view(goal) || !ps_nav_path_count || f64_lt(load64(ps_nav_goal), ps_number(54, 10)) { return 10; }
    pl_print(1, "RGB floor memory passed: independent frames, recorded rear-wheel collision rejected, target approach, grasp removal, reset, poisoned truth/map, safe viewing goal\n"); return 0;
}
'''
    with tempfile.TemporaryDirectory(prefix='floor-probe-', dir=ROOT/'build/flex/sim') as temporary:
        entry = Path(temporary)/'probe.flex'
        binary = entry.with_suffix('')
        entry.write_text(source)
        env = dict(os.environ, FLEXSCRIPT_ROOT=os.environ.get('FLEXSCRIPT_ROOT', str(ROOT.parent/'flexscript')))
        subprocess.run([str(ROOT/'build/flex/pup-compiler'), str(entry), '-o', str(binary)], cwd=ROOT, env=env, check=True)
        subprocess.run([str(binary)], cwd=ROOT, check=True)


if __name__ == '__main__':
    main()
