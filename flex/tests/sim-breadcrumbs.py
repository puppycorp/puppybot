#!/usr/bin/env python3
"""Validate native visual registration on real TCP-driving image pairs."""
import argparse
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import struct
import subprocess
import sys

sys.path = [p for p in sys.path if Path(p).resolve() != Path(__file__).resolve().parent]
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]


def capture(directory):
    directory.mkdir(parents=True, exist_ok=False)
    spec = importlib.util.spec_from_file_location('tcp_camera_checks', Path(__file__).with_name('sim-tcp-camera.py'))
    camera = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(camera)
    binary = camera.native(directory)
    for name, pose in (('home', [0.18, 0, 0]), ('offset', [0.21, -0.04, 0.02]), ('other', [2.3, -0.8, -1.8])):
        result = camera.capture(binary, directory/name, pose)
        c, s = math.cos(pose[2]), math.sin(pose[2])
        calibration = result['estimatedCamera']
        body = []
        for i in range(4):
            x, y, z = calibration[i*3:i*3+3]
            if i == 0:
                x, y = x-pose[0], y-pose[1]
            body.extend(round(v*1e6) for v in (c*x+s*y, c*y-s*x, z))
        (directory/(name+'.camera.bin')).write_bytes(struct.pack('<12q', *body))


def probe(directory):
    directory = directory.resolve()
    for name in ('home', 'offset', 'other'):
        with Image.open(directory/(name+'.png')) as image:
            (directory/(name+'.rgb')).write_bytes(image.convert('RGB').tobytes())
    source = (ROOT/'flex/sim/main.flex').read_text().replace('fn main(argc, argv)', 'fn ps_application_main(argc, argv)')
    source = re.sub(r'^import "([^"]+)";', lambda m: 'import '+json.dumps(str(ROOT/'flex/sim'/m[1]))+';', source, flags=re.MULTILINE)
    source += r'''
fn motion_gate() {
    let reference=alloc(16*48);let current=alloc(16*48);let pose=alloc(24);let prior=alloc(24);let i=0;let seed=73;
    while i<16 {
        let p=reference+i*48;store64(p,300000+i%4*120000);store64(p+8,-180000+i/4*120000);
        seed=(seed*1664525+1013904223)&0xffffffff;let high=seed;seed=(seed*1664525+1013904223)&0xffffffff;store64(p+16,(high<<32)|seed);i=i+1;
    }
    pb_copy(current,reference,16*48);store64(prior,ps_number(6,100));ps_cf_gate_mm=12;
    // Body-fixed image features must not erase measured wheel travel.
    if ps_cf_fit(current,16,reference,16,pose,prior) {return 1;}
    i=0;while i<16 {store64(current+i*48,load64(current+i*48)-60000);i=i+1;}
    if !ps_cf_fit(current,16,reference,16,pose,prior) {return 2;}
    if f64_gt(f64_magnitude(f64_sub(load64(ps_cf_result),ps_number(6,100))),ps_number(1,10000)) {return 3;}
    ps_cf_gate_mm=65;return 0;
}
fn main() {
    pl_init(); ps_cf_init(); let rgb = alloc(640 * 480 * 3); let reference = alloc(384 * 48); let pose = alloc(24); let prior = alloc(24); let saved = alloc(24);
    store64(pose, ps_number(18, 100)); pb_copy(prior, pose, 24);
    if pl_read_file("PAIR_DIR/home.rgb", rgb, 640 * 480 * 3) != 640 * 480 * 3 { return 1; }
    if pl_read_file("PAIR_DIR/home.camera.bin", ps_cf_camera, 96) != 96 { return 8; }
    let n = ps_cf_extract(rgb, 0, reference);
    pl_read_file("PAIR_DIR/offset.rgb", rgb, 640 * 480 * 3); pl_read_file("PAIR_DIR/offset.camera.bin", ps_cf_camera, 96); let m = ps_cf_extract(rgb, 0, ps_cf_points);
    if !ps_cf_fit(ps_cf_points, m, reference, n, pose, prior) || ps_cf_inliers < 10 { return 2; }
    if f64_gt(f64_magnitude(f64_sub(load64(ps_cf_result), ps_number(21, 100))), ps_number(5, 1000)) || f64_gt(f64_magnitude(f64_sub(load64(ps_cf_result + 8), ps_number(-4, 100))), ps_number(5, 1000)) || f64_gt(f64_magnitude(f64_sub(load64(ps_cf_result + 16), ps_number(2, 100))), ps_number(15, 1000)) { return 3; }
    pb_copy(saved, ps_cf_result, 24);
    pl_atomic_file("PAIR_DIR/reference.features.bin", reference, n * 48); pl_atomic_file("PAIR_DIR/current.features.bin", ps_cf_points, m * 48);
    pl_atomic_file("PAIR_DIR/matches.bin", ps_cf_matches, ps_cf_match_count * 48); pl_atomic_file("PAIR_DIR/estimated-pose.bin", saved, 24);
    ps_x = f64_from_i64(50); ps_y = f64_from_i64(-50); ps_heading = f64_from_i64(2); ps_eye = 0; ps_target = 0;
    if !ps_cf_fit(ps_cf_points, m, reference, n, pose, prior) { return 4; } let i = 0;
    while i < 3 { if load64(saved + i * 8) != load64(ps_cf_result + i * 8) { return 5; } i = i + 1; }
    let text = alloc(1024); let b = alloc(32); pl_builder(b, text, 1024);
    pl_text(b, "{\"estimatedPose\":["); i = 0; while i < 3 { if i { pl_char(b, 44); } pl_float(b, load64(saved + i * 8)); i = i + 1; }
    pl_text(b, "],\"inliers\":"); pl_int(b, ps_cf_inliers); pl_text(b, ",\"truthPoisoningUnchanged\":true}\n"); pl_print(1, text);
    pl_read_file("PAIR_DIR/other.rgb", rgb, 640 * 480 * 3); pl_read_file("PAIR_DIR/other.camera.bin", ps_cf_camera, 96); m = ps_cf_extract(rgb, 0, ps_cf_points);
    if ps_cf_fit(ps_cf_points, m, reference, n, pose, prior) { return 6; }
    pb_zero(rgb, 640 * 480 * 3); m = ps_cf_extract(rgb, 0, ps_cf_points); if m || ps_cf_fit(ps_cf_points, m, reference, n, pose, prior) { return 7; }
    if motion_gate() {return 9;}
    pl_print(1, "Visual registration checks passed: metric image offset, poisoned truth, unrelated view, blackout and body-fixed feature rejection\n"); return 0;
}
'''.replace('PAIR_DIR', str(directory))
    entry, binary = directory/'probe.flex', directory/'probe'
    entry.write_text(source)
    env = dict(os.environ, FLEXSCRIPT_ROOT=os.environ.get('FLEXSCRIPT_ROOT', str(ROOT.parent/'flexscript')))
    subprocess.run([os.environ.get('FLEXSCRIPT_COMPILER', str(ROOT/'build/flex/pup-compiler')), str(entry), '-o', str(binary)], cwd=ROOT, env=env, check=True)
    result = subprocess.run([str(binary)], cwd=ROOT, capture_output=True, text=True, check=True)
    (directory/'probe.log').write_text(result.stdout+result.stderr)
    print(result.stdout, end='')


def audit(path):
    spec = importlib.util.spec_from_file_location('odometry_audit', Path(__file__).with_name('sim-odometry.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    report = module.audit(path)
    last = None
    cursor = None
    reached = []
    transitions = 0
    max_corrections = 0
    for line in path.open():
        state = json.loads(line)
        visual = state['breadcrumbs']
        assert visual['source'] == 'tcp-rgb-floor-features-v1' and visual['oraclePose'] is False
        assert state['environment']['sensorCameras'] == ['tcp']
        if max_corrections != visual['corrections']:
            assert visual['frameId'] == state['totalSteps'] and visual['inliers'] >= 10
            max_corrections = visual['corrections']
        index = visual['returnIndex']
        if cursor is not None and cursor >= 0 and index < cursor:
            assert index == cursor-1
            assert visual['checkpointMatches'] > 0
            reached.append(dict(step=state['step'], index=cursor))
        if cursor is not None and cursor < 0 <= index:
            transitions += 1
        cursor = index
        last = visual
    assert last and last['corrections'] > 0 and reached
    report.update(visualCorrections=last['corrections'], checkpointMatches=last['checkpointMatches'],
                  reverseRouteStarts=transitions, reverseCheckpointsReached=reached)
    (path.parent/'breadcrumb-audit.json').write_text(json.dumps(report, indent=2)+'\n')
    print(f'Breadcrumb audit: {len(reached)} checkpoints reached in reverse order; {max_corrections} RGB corrections')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='capture independent camera pairs in a new directory')
    parser.add_argument('--pairs', type=Path, help='check existing home/offset/other camera images')
    parser.add_argument('--trace', type=Path)
    args = parser.parse_args()
    if args.output:
        capture(args.output.resolve())
        probe(args.output)
    if args.pairs:
        probe(args.pairs)
    if args.trace:
        audit(args.trace)
    if not (args.output or args.pairs or args.trace):
        parser.error('choose --output NEW_DIRECTORY, --pairs DIRECTORY or --trace FILE')


if __name__ == '__main__':
    main()
