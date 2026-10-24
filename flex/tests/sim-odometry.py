#!/usr/bin/env python3
"""Prove wheel-mode geometry ignores truth; audit retained drift experiments."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]


def probe():
    source = (ROOT/'flex/sim/main.flex').read_text().replace('fn main(argc, argv)', 'fn ps_application_main(argc, argv)')
    source = re.sub(r'^import "([^"]+)";', lambda m: 'import '+json.dumps(str(ROOT/'flex/sim'/m[1]))+';', source, flags=re.MULTILINE)
    source += r'''
fn check_same(a, b, size) {
    let i = 0; while i < size { if load8(a + i) != load8(b + i) { return 0; } i = i + 1; } return 1;
}
fn snapshot(out) {
    ps_local_camera(out, 1); ps_local_camera(out + 96, 2);
    let valid = ps_arm_solve(ps_case_target, 180, 40); store64(out + 192, valid); pb_copy(out + 200, ps_pickup_targets, 32);
    store64(out + 232, ps_house_path(ps_number(18, 100), 0));
    if !ps_nav_plan(ps_number(23, 10), 0, 0) { return 0; }
    store64(out + 240, ps_nav_path_count); let hash = 0; let i = 0;
    while i < ps_nav_path_count { hash = (hash * 31 + load64(ps_nav_path + i * 8)) & 0xffffffff; i = i + 1; } store64(out + 248, hash);
    ps_case_attachment_capture(); pb_copy(out + 256, ps_case_attachment, 24); return 1;
}
fn main() {
    if !pl_init() || !ps_catalog_load() || !ps_case_load(ps_case_find("house-blocks-into-box")) || !ps_environment_load("build/flex/sim/environments/apartment/apartment.bin") || !ps_model_load("build/flex/sim/puppybot.bin") { return 1; }
    ps_robot = alloc(8192); ps_system = alloc(2048); ps_config = alloc(448); ps_app = alloc(2048); ps_bus = alloc(16384); ps_plant = alloc(2048); ps_trace = alloc(69632);
    pb_config_default(ps_config); pb_vset(ps_config + 40, 2, 5); ps_local_requested = 1; if !ps_reset() { return 2; } ps_pickup_targets = alloc(32);
    store64(ps_case_target, ps_number(20, 100)); store64(ps_case_target + 8, ps_number(8, 100)); store64(ps_case_target + 16, ps_number(12, 1000));
    let a = alloc(280); let b = alloc(280); if !snapshot(a) || !load64(a + 192) || !load64(a + 232) { return 3; }
    // Corrupt all live world geometry used by the old policy/calibration.
    // Wheel-mode camera, IK, path and grasp estimates must remain identical.
    ps_x = f64_from_i64(50); ps_y = f64_from_i64(-50); ps_heading = f64_from_i64(2);
    pb_zero(ps_tcp, 24); pb_zero(ps_world_matrices, ps_groups * 128); pb_zero(ps_gripper_frame, 128);
    if !snapshot(b) || !check_same(a, b, 280) { pl_print(2, "world truth leaked into wheel-mode geometry\n"); return 4; }
    ps_local_reset(); if ps_pose_x() || ps_pose_y() || ps_pose_heading() { return 5; }
    let d = pb_robot_drive(ps_robot); store64(d + 48, 60); store64(d + 56, 60); store64(d + 64, 90); let i = 0;
    while i < 100 { ps_local_step(); i = i + 1; }
    if f64_gt(f64_magnitude(f64_sub(ps_pose_x(), ps_number(6, 10))), ps_number(1, 1000000)) || ps_pose_y() || ps_pose_heading() { return 6; }
    ps_local_requested = 2; ps_local_reset(); i = 0;
    while i < 100 { ps_local_step(); i = i + 1; } let x = ps_pose_x(); let y = ps_pose_y(); let heading = ps_pose_heading();
    ps_local_reset(); i = 0; while i < 100 { ps_local_step(); i = i + 1; }
    if x != ps_pose_x() || y != ps_pose_y() || heading != ps_pose_heading() || !y || !heading { return 7; }
    ps_local_seed = ps_local_seed + 1; ps_local_reset(); i = 0; while i < 100 { ps_local_step(); i = i + 1; } if x == ps_pose_x() { return 8; }
    pl_print(1, "Odometry isolation passed: poisoned truth leaves camera/IK/map path/grasp unchanged; configured prior, ideal integration, seeded drift verified\n"); return 0;
}
'''
    with tempfile.TemporaryDirectory(prefix='odometry-probe-', dir=ROOT/'build/flex/sim') as temporary:
        directory = Path(temporary)
        entry, binary = directory/'probe.flex', directory/'probe'
        entry.write_text(source)
        env = dict(os.environ, FLEXSCRIPT_ROOT=os.environ.get('FLEXSCRIPT_ROOT', str(ROOT.parent/'flexscript')))
        subprocess.run([os.environ.get('FLEXSCRIPT_COMPILER', str(ROOT/'build/flex/pup-compiler')), str(entry), '-o', str(binary)], cwd=ROOT, env=env, check=True)
        subprocess.run([str(binary)], cwd=ROOT, check=True)


def audit(path):
    previous = last = None
    captures, releases = [], []
    distance = 0
    max_error = 0
    random = None
    for line in path.open():
        state = json.loads(line)
        local = state['localization']
        if random is None:
            random = local['seed']
        assert local['mode'] in ('wheel', 'wheel-drift')
        assert local['source'] == ('wheel-steering-and-front-rgb-features' if 'breadcrumbs' in state else 'wheel-steering-command-integration')
        assert local['cameraCalibration'] == 'estimated-base-and-joint-feedback'
        assert state['case']['navigation']['localization'] == local['source']
        error = math.dist(local['pose'][:2], state['pose'][:2])
        assert abs(error-local['evaluation']['positionErrorM']) < 1e-9
        max_error = max(max_error, error)
        assert state['physicsFault'] == state['vehicle']['queryFault'] == 0
        if previous:
            drive = previous['controller']['drive']
            travelled = (drive['leftSpeed']+drive['rightSpeed'])/20000
            steering = math.radians(drive['steeringAngleDeg']-90)
            if travelled and local['mode'] == 'wheel-drift':
                random = (random*1664525+1013904223) & 0xffffffff
                noise = (random % 2001-1000)/1000
                travelled *= 1+local['driftPermille']/1000*(1+noise/5)
                steering += math.radians(local['driftPermille']/50)
            x, y, heading = previous['localization']['pose']
            heading = (heading-travelled/0.18*math.tan(steering)+math.pi) % (2*math.pi)-math.pi
            expected = [x+travelled*math.cos(heading), y+travelled*math.sin(heading), heading]
            if 'breadcrumbs' in state:
                delta = state['breadcrumbs']['correctionDelta']
                expected = [expected[i]+delta[i] for i in range(3)]
            assert math.dist(local['pose'][:2], expected[:2]) < 1e-8, (state['step'], local['pose'], expected)
            assert abs((local['pose'][2]-expected[2]+math.pi) % (2*math.pi)-math.pi) < 1e-8
            movement = math.dist(state['pose'][:2], previous['pose'][:2])
            assert movement < 0.010001, (state['step'], movement)
            distance += movement
            if state['gripper']['held'] and not previous['gripper']['held']:
                assert state['gripper']['captureContactMask'] == 3
                assert state['case']['visualRefinements'] > 0
                captures.append(state['step'])
            if not state['gripper']['held'] and previous['gripper']['held']:
                dock = state['case']['dockVision']
                assert dock['releaseFrameId'] == state['totalSteps'] and dock['stableObservations'] >= 3
                releases.append(state['step'])
        camera = state['case']['perception']
        if camera['frameId'] == state['totalSteps'] and camera['view'] == 'rover':
            x, y, heading = local['pose']
            assert math.dist(camera['calibration'][:3], [x+0.09*math.cos(heading), y+0.09*math.sin(heading), 0.24]) < 0.003
        last = previous = state
    assert last
    case = last['case']
    assert case['phase'] in ('passed', 'failed'), case['phase']
    if case['passed']:
        assert case['placed'] == case['inside'] == case['required'] == len(captures) == len(releases)
    report = dict(schema='puppybot.odometry-audit.v1', mode=last['localization']['mode'], driftPermille=last['localization']['driftPermille'],
                  seed=last['localization']['seed'], completed=case['passed'], placed=case['placed'], inside=case['inside'],
                  reason=case['reason'], steps=last['step'], distanceM=distance, maxPositionErrorM=max_error,
                  finalPositionErrorM=last['localization']['evaluation']['positionErrorM'], captures=captures, releases=releases,
                  blocked=last['blocked'], armBlocked=last['collision']['armBlocked'],
                  traceSha256=hashlib.sha256(path.read_bytes()).hexdigest())
    (path.parent/'audit.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))
    return report


def run(directory, mode, drift, seed, breadcrumbs=False):
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    command = [str(ROOT/'build/flex/puppybot-sim'), '--hidden', '--case', 'house-blocks-into-box',
               '--localization', mode, '--odometry-drift', str(drift), '--odometry-seed', str(seed),
               '--until-done', '--steps', '150000', '--bind', '127.0.0.1:0',
               '--record', str(directory/'trace.jsonl'), '--capture', str(directory/'outcome.png')]
    if breadcrumbs:
        command += ['--breadcrumbs', '--breadcrumb-output', str(directory/'visual')]
    (directory/'command.json').write_text(json.dumps(command, indent=2)+'\n')
    with (directory/'run.log').open('w') as output:
        child = subprocess.Popen(command, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT)
        deadline = time.monotonic()+1800
        next_report = 0
        try:
            while child.poll() is None:
                assert time.monotonic() < deadline, 'native rollout timed out'
                if time.monotonic() >= next_report:
                    path = directory/'trace.jsonl'
                    if path.exists() and path.stat().st_size:
                        with path.open('rb') as trace:
                            trace.seek(max(0, path.stat().st_size-65536))
                            for line in reversed(trace.read().splitlines()):
                                try:
                                    state = json.loads(line)
                                    break
                                except json.JSONDecodeError:
                                    continue
                        print(f"{mode}: step {state['step']}, {state['case']['phase']}, placed {state['case']['placed']}/6", flush=True)
                    next_report = time.monotonic()+15
                time.sleep(0.1)
        finally:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=10)
    assert child.returncode in (0, 1), f'native process exited {child.returncode}'
    state = json.loads((directory/'run.log').read_text().splitlines()[-1])
    assert child.returncode == int(not state['case']['passed'])
    return audit(directory/'trace.jsonl')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--probe', action='store_true')
    parser.add_argument('--trace', type=Path)
    parser.add_argument('--run', type=Path, help='run and audit a new house experiment')
    parser.add_argument('--mode', choices=('wheel', 'wheel-drift'), default='wheel-drift')
    parser.add_argument('--drift', type=int, choices=range(101), default=10, metavar='0..100')
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--breadcrumbs', action='store_true')
    args = parser.parse_args()
    if args.probe:
        probe()
    if args.trace:
        audit(args.trace)
    if args.run:
        run(args.run, args.mode, args.drift, args.seed, args.breadcrumbs)
    if not args.probe and not args.trace and not args.run:
        parser.error('choose --probe, --trace FILE or --run NEW_DIRECTORY')


if __name__ == '__main__':
    main()
