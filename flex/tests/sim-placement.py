#!/usr/bin/env python3
"""Reproduce a release reach failure using recorded camera and feedback inputs."""
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


def pose(values):
    return '\n'+'\n'.join(f'    {name} = {word(value)};' for name, value in
                     zip(('ps_local_x', 'ps_local_y', 'ps_local_heading'), values))


def probe(fixture):
    source = (ROOT/'flex/sim/main.flex').read_text().replace('fn main(argc, argv)', 'fn ps_application_main(argc, argv)')
    source = re.sub(r'^import "([^"]+)";', lambda m: 'import '+json.dumps(str(ROOT/'flex/sim'/m[1]))+';', source, flags=re.MULTILINE)
    source += r'''
fn main() {
    pl_init(); if !ps_model_load("build/flex/sim/puppybot.bin") { return 1; }
    ps_robot = alloc(8192); ps_config = alloc(448); ps_plant = alloc(2048); ps_bus = alloc(16384); ps_trace = alloc(69632); ps_pickup_targets = alloc(32);
    pb_config_default(ps_config); pb_robot_configure(ps_robot, ps_config, 0); gs_init(ps_plant, ps_config, ps_bus, 42, -1);
    ps_case_target = alloc(24); ps_case_attachment = alloc(24); ps_case_drop = alloc(24); ps_case_bin = alloc(128); ps_case_point = alloc(24); ps_bin_local_point = alloc(24);
    ps_local_mode = 1; ps_case_camera = 2; ps_dock_reset();
'''
    source += f'\n    ps_case_count = {fixture["release"]["count"]}; ps_case_placed = {fixture["release"]["placed"]};'
    for i, size in enumerate(fixture['release']['boxSize']):
        source += f'\n    store64(ps_case_bin + {24+i*8}, {word(size)});'
    source += pose(fixture['grasp']['pose'])
    for i, tick in enumerate(fixture['grasp']['ticks']):
        source += f'\n    store64(ps_plant + {128+i*64+16}, {tick});'
    for i, value in enumerate(fixture['grasp']['target']):
        source += f'\n    store64(ps_case_target + {i*8}, {word(value)});'
    source += '\n    ps_case_attachment_capture();'
    source += pose(fixture['release']['pose'])
    source += f'\n    let h = {word(fixture["release"]["boxYaw"])};'
    source += '''
    store64(ps_dock_frame, f64_cos(h)); store64(ps_dock_frame + 8, f64_sin(h));
    store64(ps_dock_frame + 32, pb_neg(f64_sin(h))); store64(ps_dock_frame + 40, f64_cos(h));
'''
    for i, value in enumerate(fixture['release']['boxPosition']):
        source += f'\n    store64(ps_dock_frame + {96+i*8}, {word(value)});'
    source += f'\n    let approach = {int(fixture.get("requiresBaseApproach", False))};'
    source += r'''
    ps_system = alloc(2048); ps_app = alloc(2048); pb_system_init(ps_system, ps_robot);
    pr_init(ps_app, ps_robot, ps_system, ps_config, "build/flex/sim/config.json", 1, 0); pb_vset(ps_app, 3, ps_bus);
    ps_case_drop_frame = alloc(128); ps_dock_valid = 1; ps_dock_seen = 0; ps_total = 0;
    ps_x = f64_from_i64(999); ps_y = f64_from_i64(-999); ps_heading = f64_from_i64(2);
    ps_tcp = 1; ps_world_matrices = 1; ps_physics = 1; ps_environment = 1; ps_nav_nodes = 1;
    if approach {
        if ps_case_drop_find(180, ps_pose_x(), ps_pose_y(), ps_pose_heading()) { return 5; }
        ps_case_stage = 18; ps_stock_pickup = 1; ps_stock_travel = 0; let start_x = ps_local_x; let start_y = ps_local_y; let steps = 0;
        while ps_case_stage == 18 && steps < 250 {
            if !ps_case_dock_approach() { return 6; }
            if pb_abs(load64(pb_robot_drive(ps_robot) + 48)) > 4 { return 7; }
            ps_local_step(); steps = steps + 1;
        }
        let dx = f64_sub(ps_local_x, start_x); let dy = f64_sub(ps_local_y, start_y); let distance = f64_sqrt(f64_add(f64_mul(dx, dx), f64_mul(dy, dy)));
        if !ps_case_drop_clearance(180, ps_pose_x(), ps_pose_y(), ps_pose_heading()) { return 9; }
        if ps_case_stage != 7 || f64_lt(distance, ps_number(1, 1000)) || f64_gt(distance, ps_number(8, 100)) { return 8; }
    } else { if !ps_case_drop_target(180) { pl_print(2, "recorded fourth release could not be solved\n"); return 2; } }
    let i = 0;
    while i < 4 { store64(ps_plant + 128 + i * 64 + 16, load64(ps_pickup_targets + i * 8)); i = i + 1; }
    ps_local_kinematics();
    if !approach && (f64_lt(load64(ps_local_tcp + 16), ps_number(23, 100)) || f64_gt(load64(ps_local_tcp + 16), ps_number(27, 100))) { return 3; }
    ps_stock_pickup = 1;
    if !ps_case_withdraw() { return 10; }
    i = 0; while i < 4 { if load64(ps_pickup_targets + i * 8) != load64(pb_config_joint(ps_config, i) + 24) { return 11; } i = i + 1; }
    // A stale camera observation must still prevent issuing another drop.
    ps_dock_seen = -1; if ps_case_drop_target(180) { return 4; }
    pl_print(1, "Release regression passed: recorded grasp offset, higher reachable pose, bounded base approach, fresh camera requirement, calibrated withdrawal, poisoned truth/map\n"); return 0;
}
'''
    with tempfile.TemporaryDirectory(prefix='release-probe-', dir=ROOT/'build/flex/sim') as temporary:
        entry = Path(temporary)/'probe.flex'
        binary = entry.with_suffix('')
        entry.write_text(source)
        env = dict(os.environ, FLEXSCRIPT_ROOT=os.environ.get('FLEXSCRIPT_ROOT', str(ROOT.parent/'flexscript')))
        subprocess.run([str(ROOT/'build/flex/pup-compiler'), str(entry), '-o', str(binary)], cwd=ROOT, env=env, check=True)
        subprocess.run([str(binary)], cwd=ROOT, check=True)


def main():
    for name in ('stock-room-release.json', 'stock-room-release-drift.json'):
        probe(json.loads((ROOT/'flex/tests/fixtures'/name).read_text()))


if __name__ == '__main__':
    main()
