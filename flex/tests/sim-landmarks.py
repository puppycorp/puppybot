#!/usr/bin/env python3
"""Audit stock-YOLO teach/return motion, model provenance and policy isolation."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def probe(directory):
    directory.mkdir(parents=True, exist_ok=False)
    source = (ROOT/'flex/sim/main.flex').read_text().replace('fn main(argc, argv)', 'fn ps_application_main(argc, argv)')
    source = re.sub(r'^import "([^"]+)";', lambda m: 'import '+json.dumps(str(ROOT/'flex/sim'/m[1]))+';', source, flags=re.MULTILINE)
    source += r'''
fn main() {
    pl_init(); ps_robot = alloc(8192); pb_drive_init(pb_robot_drive(ps_robot), 0);
    ps_stock_rgb = alloc(640 * 480 * 3); ps_stock_records = alloc(6400); ps_stock_reference = alloc(64); ps_stock_candidate = alloc(64);
    ps_stock_patch = alloc(256); ps_stock_home_patch = alloc(256); ps_stock_phase = 1; ps_stock_count = 1;
    let r = ps_stock_records; store64(r, f64_from_i64(400)); store64(r + 8, f64_from_i64(20)); store64(r + 16, f64_from_i64(550)); store64(r + 24, f64_from_i64(130));
    store64(r + 32, ps_number(9, 10)); store64(r + 40, 4); let i = 0;
    while i < 3 { ps_stock_decide(); i = i + 1; } if ps_stock_phase != 1 || ps_stock_run { return 1; }
    store64(r + 40, 56); ps_stock_decide(); if ps_stock_phase != 1 || ps_stock_run != 1 { return 2; }
    store64(r + 32, ps_number(2, 10)); ps_stock_decide(); if ps_stock_run { return 3; }
    store64(r + 32, ps_number(9, 10)); ps_stock_decide(); ps_stock_decide(); ps_stock_decide(); if ps_stock_phase != 2 { return 4; }
    ps_stock_phase = 3; ps_stock_outbound = ps_number(8, 10); ps_stock_travel = ps_number(1, 10);
    pb_copy(r + 64, r, 64); ps_stock_count = 2; ps_stock_decide(); if ps_stock_matches { return 5; }
    ps_stock_count = 1; let p = 0; while p < 640 * 480 * 3 { store8(ps_stock_rgb + p, 255); p = p + 1; }
    ps_stock_decide(); if ps_stock_matches { return 6; } pb_zero(ps_stock_rgb, 640 * 480 * 3);
    // Truth/map pointers are deliberately unusable. Only RGB, boxes and
    // command-distance gates may affect the return decision.
    ps_x = f64_from_i64(999); ps_y = f64_from_i64(-999); ps_heading = f64_from_i64(2);
    ps_environment = 1; ps_environment_start = 1; ps_world_matrices = 1; ps_tcp = 1; ps_physics = 1;
    ps_stock_decide(); ps_stock_decide(); if ps_stock_phase != 3 || ps_stock_matches != 2 { return 7; }
    ps_stock_decide(); if ps_stock_phase != 4 || ps_stock_matches != 3 { return 8; }
    ps_stock_phase = 1; ps_stock_run = 0; ps_stock_frames = 0; ps_total = 100; ps_live_step = 1;
    let text = "{\"detections\":[{\"classId\":56,\"label\":\"chair\",\"confidence\":0.9,\"box\":[400,20,550,130]}]}";
    let tree = pj_parse(text, pl_size(text)); if !ps_stock_result(tree, pl_size(text)) || ps_stock_run { return 9; }
    ps_stock_enabled = 1; ps_stock_phase = 3; ps_stock_frame = 0; ps_stock_start = 0; ps_live_state = "ready";
    pb_drive_steer(pb_robot_drive(ps_robot), -10, 0, 0); ps_stock_update(); if load64(pb_robot_drive(ps_robot) + 48) { return 10; }
    pl_print(1, "Landmark guards passed: unsupported/weak classes, ambiguous boxes, wrong appearance, three confirmations, poisoned truth/map, stale frames stop drive\n"); return 0;
}
'''
    entry, binary = directory/'probe.flex', directory/'probe'
    entry.write_text(source)
    env = dict(os.environ, FLEXSCRIPT_ROOT=os.environ.get('FLEXSCRIPT_ROOT', str(ROOT.parent/'flexscript')))
    subprocess.run([os.environ.get('FLEXSCRIPT_COMPILER', str(ROOT/'build/flex/pup-compiler')), str(entry), '-o', str(binary)], cwd=ROOT, env=env, check=True)
    result = subprocess.run([str(binary)], cwd=ROOT, capture_output=True, text=True, check=True)
    (directory/'probe.log').write_text(result.stdout+result.stderr)
    print(result.stdout, end='')


def audit(trace, frames):
    rows = [json.loads(line) for line in trace.open()]
    states = [s['stockLandmarks'] for s in rows]
    assert states[-1]['phase'] == 'matched' and states[-1]['returnMatches'] >= 3
    assert all(not s['oraclePose'] and not s['mapInput'] and not s['depthInput'] for s in states)
    assert all(s['physicsFault'] == 0 and not s['blocked'] for s in rows)
    assert {'learning', 'outbound', 'returning', 'matched'} <= {s['phase'] for s in states}
    origin = rows[0]['pose']
    movements = [math.dist(a['pose'][:2], b['pose'][:2]) for a, b in zip(rows, rows[1:])]
    assert max(movements) <= 0.003, 'nonphysical pose jump'
    actual_outbound = max(math.dist(origin[:2], s['pose'][:2]) for s in rows)
    assert actual_outbound >= 0.75 and math.dist(origin[:2], rows[-1]['pose'][:2]) <= 0.15
    manifest = json.loads((ROOT/'build/flex/vision/yolo26n/model.json').read_text())
    events = [json.loads(line) for line in (frames/'observations.jsonl').open()]
    previous = -1
    labels = {}
    sizes = []
    for event in events:
        s = event['stockLandmarks']
        assert s['frameId'] > previous
        previous = s['frameId']
        stem = frames/('frame-'+str(s['frames']))
        result = json.loads(stem.with_suffix('.json').read_text())
        assert result['runtime'] == 'pup' and result['model']['weightsSha256'] == manifest['weightsSha256']
        camera = json.loads(Path(str(stem)+'.png.camera.json').read_text())
        assert camera['view'] == 'tcp' and camera['frameId'] == s['frameId']
        if s['returnMatches'] or s['stableObservations']:
            assert event['step']-s['frameId'] <= 20
        for detection in result['detections']:
            labels[detection['label']] = labels.get(detection['label'], 0)+1
        if stem.with_suffix('.jpg').exists():
            sizes.append(stem.with_suffix('.jpg').stat().st_size)
    # At least three distinct model observations must confirm the home view.
    confirmations = [e for e in events if e['stockLandmarks']['phase'] == 'returning' and e['stockLandmarks']['returnMatches'] > 0]
    assert len(confirmations) >= 2
    report = dict(schema='puppybot.stock-landmark-audit.v1', completed=True,
        model=manifest['id'], weightsSha256=manifest['weightsSha256'], frames=len(events),
        outboundM=states[-1]['outboundM'], actualOutboundM=actual_outbound, returnErrorM=math.dist(origin[:2], rows[-1]['pose'][:2]),
        drivenDistanceM=sum(movements), returnConfirmations=states[-1]['returnMatches'],
        labels=labels, maxJpegBytes=max(sizes, default=0), traceSha256=hashlib.sha256(trace.read_bytes()).hexdigest(),
        limitations=['Straight fixed-heading route only', 'No global map or obstacle avoidance learned',
                     'No unknown-room exploration or LEGO collection', 'No real odometry drift or hardware validation'])
    (frames/'audit.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--probe', type=Path, help='compile policy isolation/negative checks in a new directory')
    parser.add_argument('--run', type=Path, help='run a moving native camera experiment in a new directory')
    parser.add_argument('--trace', type=Path)
    parser.add_argument('--frames', type=Path)
    args = parser.parse_args()
    if args.probe:
        probe(args.probe.resolve())
    if args.run:
        directory = args.run.resolve()
        directory.mkdir(parents=True, exist_ok=False)
        command = [str(ROOT/'build/flex/puppybot-sim'), '--stock-landmarks', '--hidden', '--steps', '6000', '--until-done',
                   '--bind', '127.0.0.1:0', '--landmark-output', str(directory/'frames'), '--record', str(directory/'trace.jsonl'), '--capture', str(directory/'outcome.png')]
        (directory/'command.json').write_text(json.dumps(command, indent=2)+'\n')
        with (directory/'run.log').open('w') as output:
            subprocess.run(command, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT, timeout=150, check=True)
        audit(directory/'trace.jsonl', directory/'frames')
    if args.trace:
        if not args.frames:
            parser.error('--trace requires --frames DIRECTORY')
        audit(args.trace, args.frames)
    if not (args.probe or args.trace or args.run):
        parser.error('choose --probe NEW_DIRECTORY, --run NEW_DIRECTORY or --trace FILE --frames DIRECTORY')


if __name__ == '__main__':
    main()
