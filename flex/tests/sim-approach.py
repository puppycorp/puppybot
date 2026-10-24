#!/usr/bin/env python3
"""Reproduce a seen-but-missed brick using its recorded front RGB observation."""
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def word(value):
    return hex(struct.unpack('<Q', struct.pack('<d', value))[0])


def main():
    fixture = json.loads((ROOT/'flex/tests/fixtures/stock-room-approach.json').read_text())
    source = (ROOT/'flex/sim/main.flex').read_text().replace('fn main(argc, argv)', 'fn ps_application_main(argc, argv)')
    source = re.sub(r'^import "([^"]+)";', lambda m: 'import '+json.dumps(str(ROOT/'flex/sim'/m[1]))+';', source, flags=re.MULTILINE)
    source += r'''
fn main() {
    pl_init(); if !ps_model_load("build/flex/sim/puppybot.bin") || !ps_environment_load("build/flex/sim/environments/apartment/apartment.bin") { return 1; }
    ps_robot = alloc(8192); ps_config = alloc(448); ps_plant = alloc(2048); ps_trace = alloc(69632); ps_pickup_targets = alloc(32);
    pb_config_default(ps_config); pb_robot_configure(ps_robot, ps_config, 0);
    ps_stock_pickup = 1; ps_case_camera = 2; ps_case_stage = 21; ps_case_target = alloc(24); ps_case_point = alloc(24);
    ps_case_bin = alloc(128); ps_house_home = alloc(24); store64(ps_house_home, ps_number(37, 10)); ps_house_ready = 1;
    ps_local_mode = 1; ps_floor_points = alloc(128 * 32); ps_floor_count = 1; store64(ps_floor_points + 16, 3);
    ps_brick_records = alloc(128); ps_brick_count = 1;
'''
    for name, value in zip(('ps_local_x', 'ps_local_y', 'ps_local_heading'), fixture['pose']):
        source += f'\n    {name} = {word(value)};'
    for i, value in enumerate(fixture['detection']['targetM']):
        source += f'\n    store64(ps_brick_records + {32+i*8}, {word(value)});'
        if i < 2:
            source += f'\n    store64(ps_floor_points + {i*8}, {word(value)});'
    for i, value in enumerate(fixture['detection']['box']):
        source += f'\n    store64(ps_brick_records + {i*8}, {value});'
    source += r'''
    if !ps_nav_init() { return 1; }
    // The map is declared input; live world geometry is deliberately invalid.
    ps_x = f64_from_i64(999); ps_y = f64_from_i64(-999); ps_heading = f64_from_i64(2); ps_physics = 1; ps_world_matrices = 1; ps_tcp = 1;
    let x = ps_local_x; let y = ps_local_y; let h = ps_local_heading;
    if !ps_case_camera_select() { pl_print(2, "confirmed RGB brick still ignored outside near pickup range\n"); return 2; }
    if ps_case_stage != 21 || ps_house_returning != 3 || !ps_nav_path_count { return 3; }
    if x != ps_local_x || y != ps_local_y || h != ps_local_heading { return 4; }
    pl_print(1, "Camera approach passed: recorded far RGB target, reachable viewing/grasp pose, physical drive plan, poisoned live truth\n"); return 0;
}
'''
    with tempfile.TemporaryDirectory(prefix='approach-probe-', dir=ROOT/'build/flex/sim') as temporary:
        entry = Path(temporary)/'probe.flex'
        binary = entry.with_suffix('')
        entry.write_text(source)
        env = dict(os.environ, FLEXSCRIPT_ROOT=os.environ.get('FLEXSCRIPT_ROOT', str(ROOT.parent/'flexscript')))
        subprocess.run([str(ROOT/'build/flex/pup-compiler'), str(entry), '-o', str(binary)], cwd=ROOT, env=env, check=True)
        subprocess.run([str(binary)], cwd=ROOT, check=True)


if __name__ == '__main__':
    main()
