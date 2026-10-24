#!/usr/bin/env python3
"""Audit a real house rollout: room coverage, drive motion, RGB and contacts.

Use --trace on a retained JSONL, or run a new native camera mission in --output.
This audit reads judge observations; it does not supply targets to the policy.
"""
import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
BINARY = ROOT/'build/flex/puppybot-sim'


def probe():
    # Keep production modules intact. Rename only the generated test copy of
    # the application entry point so native helpers can be exercised directly.
    source = (ROOT/'flex/sim/main.flex').read_text().replace('fn main(argc, argv)', 'fn ps_application_main(argc, argv)')
    source = re.sub(r'^import "([^"]+)";', lambda m: 'import '+json.dumps(str(ROOT/'flex/sim'/m[1]))+';', source, flags=re.MULTILINE)
    source += r'''
fn main() {
    if !pl_init() { return 1; }
    ps_catalog_entries = alloc(2 * 768);
    pb_copy(ps_catalog_entries, "search-blocks-into-box", 22); pb_copy(ps_catalog_entries + 768, "house-blocks-into-box", 21);
    ps_catalog_cameras = alloc(16); store64(ps_catalog_cameras, 1); store64(ps_catalog_cameras + 8, 2);
    if !ps_case_available(0) || ps_case_available(1) { return 7; }
    ps_environment = alloc(256); if !ps_case_available(1) { return 8; } ps_environment = 0;
    ps_brick_records = alloc(16 * 128); ps_brick_count = 2;
    let a = ps_brick_records; let b = a + 128;
    store64(a, 141); store64(a + 8, 247); store64(a + 16, 186); store64(a + 24, 287);
    store64(b, 164); store64(b + 8, 257); store64(b + 16, 189); store64(b + 24, 287);
    store64(a + 32, ps_number(66010, 10000)); store64(a + 40, ps_number(16002, 10000));
    store64(b + 32, ps_number(66295, 10000)); store64(b + 40, ps_number(15712, 10000));
    if !ps_house_detection(0) || ps_house_detection(1) { pl_print(2, "overlapping orange component regression\n"); return 1; }
    store64(b, 400); store64(b + 16, 425);
    if !ps_house_detection(1) { return 2; }
    ps_nav_nodes = alloc(7 * 80); ps_nav_heap = alloc(7 * 8); ps_nav_heap_count = 7; let i = 0;
    while i < 7 { store64(ps_nav_heap + i * 8, i); store64(ps_nav_nodes + i * 80 + 32, f64_from_i64(i + 1)); store64(ps_nav_nodes + i * 80 + 72, i); i = i + 1; }
    store64(ps_nav_nodes + 80 + 32, f64_from_i64(10)); ps_nav_heap_down(1);
    store64(ps_nav_nodes + 6 * 80 + 32, ps_number(1, 2)); ps_nav_heap_up(load64(ps_nav_nodes + 6 * 80 + 72));
    let previous = 0;
    while ps_nav_heap_count { let id = ps_nav_pop(); let value = load64(ps_nav_nodes + id * 80 + 32); if f64_lt(value, previous) { return 3; } previous = value; }
    ps_case_bin = alloc(128); store64(ps_case_bin + 24, ps_number(22, 100)); store64(ps_case_bin + 32, ps_number(20, 100)); store64(ps_case_bin + 48, ps_number(8, 1000)); ps_dock_reset();
    let rotation = 0;
    while rotation < 2 {
        ps_dock_count = 5; let angle = ps_number(rotation, 2); let c = f64_cos(angle); let s = f64_sin(angle); i = 0;
        while i < 5 {
            let index = i; if i == 2 { index = 6; } if i == 3 { index = 4; } if i == 4 { index = 5; }
            let x = ps_dock_corner_x(index); let y = ps_dock_corner_y(index); let p = ps_dock_markers + i * 96 + 32;
            store64(p, f64_add(ps_number(34, 100), f64_sub(f64_mul(c, x), f64_mul(s, y))));
            store64(p + 8, f64_add(ps_number(-24, 100), f64_add(f64_mul(s, x), f64_mul(c, y)))); i = i + 1;
        }
        if !ps_dock_template() || f64_gt(f64_magnitude(f64_sub(load64(ps_dock_frame + 96), ps_number(34, 100))), ps_number(1, 1000000)) || f64_gt(f64_magnitude(f64_sub(load64(ps_dock_frame + 104), ps_number(-24, 100))), ps_number(1, 1000000)) { return 4; }
        if f64_gt(f64_magnitude(pb_wrap_pi(f64_sub(ps_dock_yaw, angle))), ps_number(1, 1000000)) { return 5; }
        ps_dock_count = 4; if ps_dock_template() { return 6; } rotation = rotation + 1;
    }
    pl_print(1, "Native house helpers passed: overlapping RGB blobs, priority increases/decreases, partial rim with rotation, insufficient landmark rejection\n"); return 0;
}
'''
    with tempfile.TemporaryDirectory(prefix='house-probe-', dir=ROOT/'build/flex/sim') as temporary:
        directory = Path(temporary)
        entry, binary = directory/'probe.flex', directory/'probe'
        entry.write_text(source)
        env = dict(os.environ, FLEXSCRIPT_ROOT=os.environ.get('FLEXSCRIPT_ROOT', str(ROOT.parent/'flexscript')))
        subprocess.run([os.environ.get('FLEXSCRIPT_COMPILER', str(ROOT/'build/flex/pup-compiler')), str(entry), '-o', str(binary)], cwd=ROOT, env=env, check=True)
        subprocess.run([str(binary)], cwd=ROOT, check=True)


def audit(path):
    previous = first = last = None
    captures, releases = [], []
    rooms = set()
    max_step = distance = 0
    guard_stops = 0
    seen_navigation = False
    for line in path.open():
        state = json.loads(line)
        if first is None:
            first = state
        last = state
        assert state['physicsFault'] == state['vehicle']['queryFault'] == 0, state
        assert not state['collision']['armBlocked'], (state['step'], state['environment'], state['collision'])
        guard_stops += bool(state['blocked'])
        case = state['case']
        assert case['controller'] == 'rgb-house' and case['perception']['targetSource'] == 'camera-rgb'
        nav = case['navigation']
        assert nav['mapSource'] == 'known-blender-static-colliders' and nav['objectTargets'] == 'camera-rgb-only'
        if case['phase'] == 'navigating rooms':
            seen_navigation = True
        x = state['pose'][0]
        rooms.add('living' if x < 3 else 'hall' if x < 4.4 else 'dining')
        if previous:
            movement = math.dist(state['pose'][:2], previous['pose'][:2])
            max_step = max(max_step, movement)
            distance += movement
            # At 100% throttle the real controller advances at most 1 cm/tick.
            assert movement <= 0.010001, (state['step'], movement)
            drive = previous['controller']['drive']
            travelled = (drive['leftSpeed']+drive['rightSpeed'])/20000
            heading = previous['pose'][2]-travelled/0.18*math.tan(math.radians(drive['steeringAngleDeg']-90))
            heading = (heading+math.pi) % (2*math.pi)-math.pi
            expected = [previous['pose'][0]+travelled*math.cos(heading), previous['pose'][1]+travelled*math.sin(heading)]
            if state['blocked']:
                # A protective stop rejects the whole proposed chassis step.
                # Recovery can continue, but it must never move through it.
                expected = previous['pose'][:2]
                heading = previous['pose'][2]
            assert math.dist(state['pose'][:2], expected) < 1e-7, (state['step'], state['pose'], expected)
            assert abs((state['pose'][2]-heading+math.pi) % (2*math.pi)-math.pi) < 1e-7
            if state['gripper']['held'] and not previous['gripper']['held']:
                assert state['gripper']['captureContactMask'] == 3
                assert case['visualRefinements'] > 0 and case['perception']['view'] == 'tcp'
                captures.append(dict(step=state['step'], body=state['gripper']['body'], pose=state['pose']))
            if previous['gripper']['held'] and not state['gripper']['held']:
                dock = case['dockVision']
                assert dock['valid'] and dock['frameId'] == dock['releaseFrameId'] == state['totalSteps']
                assert dock['stableObservations'] >= 3
                releases.append(state['step'])
        previous = state
    assert first and last and seen_navigation
    initial_rooms = [0, 0, 0]
    for obj in first['case']['objects']:
        x = obj['initialPosition'][0]
        initial_rooms[0 if x < 3 else 1 if x < 4.4 else 2] += 1
    assert initial_rooms == [2, 2, 2], initial_rooms
    assert rooms == {'living', 'hall', 'dining'}, rooms
    assert len(captures) == len(releases) == len({c['body'] for c in captures}) == 6
    assert last['case']['passed'] and last['case']['placed'] == last['case']['inside'] == 6, last['case']['reason']
    assert not last['gripper']['held'] and all(o['inside'] for o in last['case']['objects'])
    # Recompute complete object bounds in the observed moving box, rather
    # than accepting the simulator's inside flags as the only evidence.
    spec = importlib.util.spec_from_file_location('case_geometry', Path(__file__).with_name('sim-cases.py'))
    geometry = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(geometry)
    definition = json.loads((ROOT/'flex/sim/cases/house-blocks-into-box.json').read_text())
    for obj in last['case']['objects']:
        geometry.contained(obj, definition, last['case']['container'])
    report = dict(schema='puppybot.house-audit.v1', passed=True, steps=last['step'], distanceM=distance,
        maxStepM=max_step, initialRoomCounts=initial_rooms, captures=captures, releases=releases,
        placed=6, inside=6, faults=0, guardStops=guard_stops, traceSha256=hashlib.sha256(path.read_bytes()).hexdigest())
    (path.parent/'house-audit.json').write_text(json.dumps(report, indent=2)+'\n')
    print(f'House audit passed: 6/6 released and settled, all three rooms, {distance:.1f} m driven, RGB targets, fresh visual dock, bilateral grasps, {guard_stops} stationary guard stops, no teleports/physics faults')
    return report


def negative_control(directory):
    directory.mkdir(parents=True, exist_ok=False)
    cases = directory/'flex/sim/cases'
    cases.mkdir(parents=True)
    (directory/'build').symlink_to(ROOT/'build', target_is_directory=True)
    definition = json.loads((ROOT/'flex/sim/cases/house-blocks-into-box.json').read_text())
    definition['id'] = 'house-gray-control'
    for obj in definition['objects']:
        obj['color'] = [40, 40, 40]
    (directory/'case.json').write_text(json.dumps(definition))
    (cases/'catalog.json').write_text(json.dumps(dict(schema='puppybot.cases.v1', cases=[dict(
        id=definition['id'], name='Gray brick negative control', controller='rgb-house', file='case.json')])) )
    command = [str(BINARY), '--hidden', '--case', definition['id'], '--steps', '2000', '--until-done',
        '--bind', '127.0.0.1:0', '--record', str((directory/'trace.jsonl').resolve())]
    result = subprocess.run(command, cwd=directory, capture_output=True, text=True, timeout=180)
    (directory/'run.log').write_text(result.stdout+result.stderr)
    state = json.loads(result.stdout.strip().splitlines()[-1])
    assert state['case']['perception']['samples'] > 1 and state['case']['navigation']['distanceM'] > 1
    assert state['gripper']['grasps'] == state['case']['placed'] == 0 and not state['case']['passed']
    assert state['physicsFault'] == state['vehicle']['queryFault'] == 0
    print('Gray brick control passed: searched with RGB; no hidden-pose pickup when brick colours were removed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trace', type=Path)
    parser.add_argument('--negative', type=Path, help='run a gray-brick control in a new directory')
    parser.add_argument('--probe', action='store_true', help='compile and check native navigation/perception helpers')
    parser.add_argument('--output', type=Path, default=ROOT/'build/flex/sim/house/verified')
    args = parser.parse_args()
    if args.probe:
        probe()
        return
    if args.negative:
        negative_control(args.negative)
        if not args.trace:
            return
    if args.trace:
        audit(args.trace)
        return
    args.output.mkdir(parents=True, exist_ok=False)
    trace = args.output/'trace.jsonl'
    command = [str(BINARY), '--hidden', '--case', 'house-blocks-into-box', '--drift', '10', '--until-done', '--steps', '150000',
        '--bind', '127.0.0.1:0', '--record', str(trace.resolve()), '--capture', str((args.output/'outcome.png').resolve())]
    with (args.output/'run.log').open('w') as log:
        result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, timeout=1800)
    assert result.returncode == 0, (args.output/'run.log').read_text()[-2000:]
    audit(trace)
    negative_control(args.output/'negative')


if __name__ == '__main__':
    main()
