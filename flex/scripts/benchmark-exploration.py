#!/usr/bin/env python3
"""Run identical no-map discovery controllers on reproducible generated worlds."""
import argparse
import csv
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(output):
    sources = sorted((ROOT/'flex/sim').glob('*.flex'))+[ROOT/'flex/core/kinematics.flex']
    expected = {path: digest(path) for path in sources}
    manifest = {}
    for path in sources:
        retained = output/'source-snapshot'/path.relative_to(ROOT)
        retained.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, retained)
        assert digest(retained) == expected[path]
        manifest[str(retained)] = expected[path]
    compiler = os.environ.get('FLEXSCRIPT_COMPILER', str(ROOT/'build/flex/pup-compiler'))
    binary = output/'simulator'
    with (output/'build.log').open('w') as log:
        result = subprocess.run([compiler, str(ROOT/'flex/sim/main.flex'), '-o', str(binary)], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    assert result.returncode == 0, f"Compilation failed; see {output/'build.log'}"
    assert all(digest(path) == value for path, value in expected.items()), 'sources changed during compilation'
    manifest[str(binary)] = digest(binary)
    for path in (ROOT/'flex/vision/discovery.py', ROOT/'build/flex/sim/puppybot.bin'):
        manifest[str(path)] = digest(path)
    return binary, manifest


def audit_trace(run, definition, layout):
    checks = module('pickup_checks', ROOT/'flex/tests/sim-discovery-pickup.py')
    containment = module('case_containment', ROOT/'flex/tests/sim-cases.py')
    judge = checks.HeldGeometry()
    first = previous = refinement = None
    captures, releases, rooms = [], [], set()
    distance = 0.
    with (run/'trace.jsonl').open('rb') as source:
        for line in source:
            if not line.endswith(b'\n'):
                break
            state = json.loads(line)
            case, discovery = state['case'], state['discovery']
            assert not discovery['suppliedMap'] and not discovery['worldPoseInput']
            assert case['navigation']['coverageCount'] == 0
            assert not state['physicsFault'] and not state['vehicle']['queryFault']
            if first is None:
                first = state
                checks.check_scene_start(first, definition)
                assert first['localization']['pose'] == [0, 0, 0]
                assert discovery['freeCells'] == discovery['occupiedCells'] == discovery['images'] == 0
                assert discovery['pickup']['observedTargets'] == 0
                assert not first['gripper']['held'] and case['placed'] == 0
                assert case['controller'] == 'rgb-discovery'
            judge.check(state)
            for index, room in enumerate(layout['rooms']):
                x, y = state['pose'][:2]
                if room[0] < x < room[2] and room[1] < y < room[3]:
                    rooms.add(index)
            if previous:
                old = previous['case']
                drive = previous['controller']['drive']
                travelled = (drive['leftSpeed']+drive['rightSpeed'])/20000
                x, y, heading = previous['pose']
                heading = (heading-travelled/.18*math.tan(math.radians(drive['steeringAngleDeg']-90))+math.pi)%(2*math.pi)-math.pi
                expected = previous['pose'] if state['blocked'] else [x+travelled*math.cos(heading), y+travelled*math.sin(heading), heading]
                assert math.dist(state['pose'][:2], expected[:2]) < 1e-7, 'nonphysical base increment'
                assert abs((state['pose'][2]-expected[2]+math.pi)%(2*math.pi)-math.pi) < 1e-7
                distance += math.dist(state['pose'][:2], previous['pose'][:2])
                if case['visualRefinements'] > old['visualRefinements']:
                    refinement = state['step'], state['pose']
                if state['gripper']['held'] and not previous['gripper']['held']:
                    assert refinement and state['step']-refinement[0] <= 1500 and state['pose'] == refinement[1]
                    assert state['gripper']['captureContactMask'] == 3
                    body = state['gripper']['body']
                    assert body not in captures
                    captures.append(body)
                if not state['gripper']['held'] and previous['gripper']['held']:
                    dock = case['dockVision']
                    assert dock['valid'] and dock['frameId'] == dock['releaseFrameId'] == state['step'] and dock['stableObservations'] >= 3
                    releases.append(state['step'])
            previous = state
    assert first is not None
    inside = [obj for obj in previous['case']['objects'] if obj['inside']]
    for obj in inside:
        containment.contained(obj, definition, previous['case']['container'])
    passed = previous['case']['passed']
    if passed:
        assert len(captures) == len(releases) == len(inside) == len(definition['objects']) == 6
        assert previous['case']['container']['settled'] and len(rooms) == len(layout['rooms'])
    receipt = dict(schema='puppybot.generated-trace-audit.v1', passed=True,
                   initialMapEmpty=True, initialOwnPose=[0, 0, 0], referenceMapSupplied=False,
                   sensorCameras=first['environment']['sensorCameras'], capturedBodies=captures,
                   freshReleaseSteps=releases, heldFramesChecked=judge.frames,
                   independentlyContained=len(inside), roomsVisited=sorted(rooms),
                   distanceM=distance, throughStep=previous['step'], taskPassed=passed)
    (run/'trace-audit.json').write_text(json.dumps(receipt, indent=2)+'\n')
    return previous, receipt


def execute(binary, run, layout_path, steps, video):
    args = [str(binary), '--hidden', '--case-file', str(run/'case-definition.json'),
            '--environment', str(layout_path/'environment.bin'), '--steps', str(steps),
            '--mapping-scans', '100', '--until-done', '--bind', '127.0.0.1:0',
            '--map-output', str(run/'map'), '--record', str(run/'trace.jsonl'),
            '--search-output', str(run/'sensor'), '--capture', str(run/'outcome.png')]
    if video:
        args += ['--video', str(run/'mission.mp4'), '--video-fps', '10']
    (run/'launch.json').write_text(json.dumps(dict(args=args, steps=steps, cwd=str(ROOT)), indent=2)+'\n')
    with (run/'run.log').open('w') as log:
        child = subprocess.Popen(args, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        try:
            code = child.wait()
        except BaseException:
            child.send_signal(signal.SIGINT)
            try:
                child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)
            raise
    (run/'exit.json').write_text(json.dumps(dict(exitCode=code))+'\n')
    return code


def summarize(output, rows, requested_seeds):
    with (output/'summary.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    complete = len(rows) == len(requested_seeds)
    result = dict(schema='puppybot.exploration-benchmark.v1', runs=rows,
                  requestedSeeds=requested_seeds, completedSeeds=[row['seed'] for row in rows],
                  batchComplete=complete,
                  allRequestedSeedsPassed=complete and all(row['taskPassed'] for row in rows),
                  scope='Only these seeds and step budgets. Incomplete trials do not establish generalization.',
                  referenceFloorplansSuppliedToRobot=False)
    (output/'summary.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seeds', nargs='+', type=int, required=True)
    parser.add_argument('--rooms', nargs='+', type=int, default=[3])
    parser.add_argument('--steps', type=int, default=750000)
    parser.add_argument('--video', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if len(set(args.seeds)) != len(args.seeds) or any(not 0 <= seed <= 4294967295 for seed in args.seeds):
        parser.error('use distinct seeds between 0 and 4294967295')
    if len(args.rooms) not in (1, len(args.seeds)) or any(not 2 <= count <= 6 for count in args.rooms):
        parser.error('--rooms needs one count or one per seed, each between 2 and 6')
    if not 1 <= args.steps <= 1000000:
        parser.error('--steps must be between 1 and 1000000')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    generator = module('layout_generator', ROOT/'flex/scripts/generate-layout.py')
    evaluator = module('map_evaluator', ROOT/'flex/scripts/benchmark-map.py')
    binary, common = build(output)
    rows = []
    for index, seed in enumerate(args.seeds):
        count = args.rooms[index % len(args.rooms)]
        run = output/f'seed-{seed}'
        run.mkdir()
        layout = generator.generate(seed, count)
        layout_path = generator.write(layout, run/'layout')
        shutil.copyfile(layout_path/'case.json', run/'case-definition.json')
        manifest = dict(common)
        for path in (layout_path/'environment.bin', run/'case-definition.json'):
            manifest[str(path)] = digest(path)
        assert all(digest(Path(path)) == value for path, value in manifest.items()), 'runtime inputs changed between seeds'
        (run/'source-manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
        print(json.dumps(dict(startingSeed=seed, rooms=count, steps=args.steps, run=str(run))), flush=True)
        code = execute(binary, run, layout_path, args.steps, args.video)
        row = dict(seed=seed, rooms=count, steps=0, exitCode=code, taskStatus='error', auditPassed=False,
                   taskPassed=False, placed=0, independentlyContained=0, roomsVisited=0,
                   driveStops=0, armStops=0, freeFloorCoverage=None, freeSpacePrecision=None,
                   obstacleIoU=None, falselyFreeM2=None, positionRMSEM=None, auditError='')
        try:
            state, audit = audit_trace(run, layout['case'], layout)
            case, discovery = state['case'], state['discovery']
            row.update(steps=state['step'], taskStatus='passed' if case['passed'] else 'failed' if case['phase'] == 'failed' else 'incomplete',
                       taskPassed=case['passed'], placed=case['placed'], independentlyContained=audit['independentlyContained'],
                       roomsVisited=len(audit['roomsVisited']), driveStops=discovery['protectiveStops'], armStops=discovery['armProtectiveStops'])
        except (AssertionError, ValueError, FileNotFoundError) as error:
            row['auditError'] = str(error) or type(error).__name__
        try:
            scores = evaluator.benchmark(run, run/'benchmark', layout_path/'environment.bin', run/'case-definition.json')
            row.update({key: scores['coarseMap'][key] for key in ('freeFloorCoverage', 'freeSpacePrecision', 'obstacleIoU', 'falselyFreeM2')})
            row['positionRMSEM'] = scores['odometry']['positionRMSEM']
        except (AssertionError, ValueError, FileNotFoundError) as error:
            row['auditError'] += ('; ' if row['auditError'] else '')+'Map benchmark: '+(str(error) or type(error).__name__)
        row['auditPassed'] = not row['auditError']
        if not row['auditPassed']:
            row['taskPassed'] = False
            if row['taskStatus'] == 'passed':
                row['taskStatus'] = 'audit-failed'
        rows.append(row)
        summarize(output, rows, args.seeds)


if __name__ == '__main__':
    main()
