#!/usr/bin/env python3
"""Verify one wrist camera in driving/inspection poses, empty and loaded."""
import argparse
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

sys.path = [p for p in sys.path if Path(p).resolve() != Path(__file__).resolve().parent]
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]


def native(directory):
    source = (ROOT/'flex/sim/main.flex').read_text().replace('fn main(argc, argv)', 'fn ps_application_main(argc, argv)')
    source = re.sub(r'^import "([^"]+)";', lambda m: 'import '+json.dumps(str(ROOT/'flex/sim'/m[1]))+';', source, flags=re.MULTILINE)
    source += r'''
fn main(argc, argv) {
    if !pl_init() { return 1; } h_environment(argc, argv);
    if !ps_model_load("build/flex/sim/puppybot.bin") || !ps_environment_load("build/flex/sim/environments/apartment/apartment.bin") || !ps_environment_spawn(load64(argv + 16)) { return 2; }
    ps_robot=alloc(8192);ps_system=alloc(2048);ps_config=alloc(448);ps_app=alloc(2048);ps_bus=alloc(16384);ps_plant=alloc(2048);ps_trace=alloc(69632);ps_json=alloc(16384);ps_builder=alloc(32);
    pb_config_default(ps_config);pb_vset(ps_config+40,2,5);ps_previews=0;ps_camera_mode=2;
    if !ps_reset() {return 3;} ps_render_init(1);
    if argc>3 {
        ps_pickup_start(0);let steps=0;
        while steps<3000 && !ps_pickup_passed {if !ps_tick(0) {return 4;}steps=steps+1;}
        if !ps_gripper_held {return 5;} ps_pickup_stage=0;
        ps_frame();if !ps_capture(h_cat(load64(argv+8),"-inspection.png")) {return 6;}
    }
    if !ps_pickup_targets {ps_pickup_targets=alloc(32);}
    if !ps_camera_drive_target() {return 7;}let steps=0;let stable=0;
    while steps<1000 && stable<15 {
        if !ps_tick(0) {return 8;}
        if gs_reached(ps_plant,ps_pickup_targets) && gs_stopped(ps_plant) {stable=stable+1;}else{stable=0;}steps=steps+1;
    }
    if stable<15 {return 9;}ps_frame();if !ps_capture(h_cat(load64(argv+8),".png")) {return 10;}
    ps_cf_calibrate();let camera=alloc(96);ps_local_camera(camera);let data=alloc(4096);let b=alloc(32);pl_builder(b,data,4096);
    pl_text(b,"{\"estimatedCamera\":[");let i=0;while i<12 {if i {pl_char(b,44);}pl_float(b,load64(camera+i*8));i=i+1;}
    pl_text(b,"],\"groundProjection\":[");i=0;
    while i<3 {if i {pl_char(b,44);}let u=240+i*80;let v=320;if !ps_cf_ground(u,v,ps_cf_temp) {return 11;}pl_char(b,91);pl_int(b,u);pl_char(b,44);pl_int(b,v);pl_char(b,44);pl_int(b,load64(ps_cf_temp));pl_char(b,44);pl_int(b,load64(ps_cf_temp+8));pl_char(b,93);i=i+1;}
    pl_text(b,"],\"basePose\":[");pl_float(b,ps_pose_x());pl_char(b,44);pl_float(b,ps_pose_y());pl_char(b,44);pl_float(b,ps_pose_heading());
    pl_text(b,"],\"held\":");pj_bool_text(b,ps_gripper_held);pl_text(b,"}\n");pl_print(1,data);
    ps_render_close();ph_world_close(ps_physics);ps_environment_close();return 0;
}
'''
    entry, binary = directory/'camera-probe.flex', directory/'camera-probe'
    entry.write_text(source)
    compiler = os.environ.get('FLEXSCRIPT_COMPILER', str(ROOT/'build/flex/pup-compiler'))
    subprocess.run([compiler, str(entry), '-o', str(binary)], cwd=ROOT, check=True)
    return binary


def capture(binary, prefix, pose, held=False):
    args = [str(binary), str(prefix), json.dumps(pose)]
    if held:
        args.append('held')
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    data = json.loads(result.stdout.strip().splitlines()[-1])
    Path(str(prefix)+'.json').write_text(json.dumps(data, indent=2)+'\n')
    return data


def check(directory):
    binary = native(directory)
    for name, pose, held in [('empty', [.18, 0, 0], False), ('loaded', [0, 0, 0], True)]:
        prefix = directory/name
        result = capture(binary, prefix, pose, held)
        camera = json.loads(Path(str(prefix)+'.png.camera.json').read_text())
        assert camera['view'] == 'tcp' and camera['imageRotationDeg'] == 180
        forward = camera['forward']
        assert forward[0] > .85 and abs(forward[1]) < .12 and -.6 < forward[2] < -.3
        assert camera['down'][2] < -.8, 'driving image is upside-down'
        assert .135 < camera['eyeM'][2] < .165
        expected = result['estimatedCamera']
        assert math.dist(expected[:3], camera['eyeM']) < .002
        assert math.dist(expected[3:6], forward) < .01
        assert result['held'] == held
        # Independently project the native floor-ray intersections back into
        # the actual image, including the driving frame's 180 degree rotation.
        base = result['basePose']
        c, s = math.cos(base[2]), math.sin(base[2])
        for u, v, x, y in result['groundProjection']:
            world = [base[0]+c*x/1e6-s*y/1e6, base[1]+s*x/1e6+c*y/1e6, 0]
            ray = [a-b for a, b in zip(world, camera['eyeM'])]
            depth = sum(a*b for a, b in zip(ray, forward))
            pu = 320+camera['intrinsics']['fx']*sum(a*b for a, b in zip(ray, camera['right']))/depth
            pv = 240+camera['intrinsics']['fy']*sum(a*b for a, b in zip(ray, camera['down']))/depth
            assert math.dist([pu, pv], [u, v]) < 1.5
        with Image.open(Path(str(prefix)+'.png')) as image:
            assert image.size == (640, 480) and len(image.convert('RGB').getcolors(640*480)) > 100
        print(name+': physical arm pose, forward/upright TCP view, calibration and floor rays passed', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.output:
        args.output.mkdir(parents=True, exist_ok=False)
        check(args.output)
    else:
        with tempfile.TemporaryDirectory(prefix='tcp-camera-', dir=ROOT/'build/flex/sim') as temporary:
            check(Path(temporary))


if __name__ == '__main__':
    main()
