#!/usr/bin/env python3
"""Run and independently audit pickup, stock-landmark return and visual release."""
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]


def module(name, file):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(file))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def audit(trace, frames):
    motion = module('odometry_audit', 'sim-odometry.py').audit(trace)
    rows = [json.loads(line) for line in trace.open()]
    last = rows[-1]
    assert last['case']['id'] in ('stock-landmark-pickup', 'stock-landmark-room')
    assert all(s['stockLandmarks']['pickupSequence'] and not s['stockLandmarks']['oraclePose'] and not s['stockLandmarks']['mapInput'] for s in rows)
    assert all(s['case']['navigation']['mapSource'] == 'known-blender-static-colliders' for s in rows)
    stages = {s['case']['phase'] for s in rows}
    returns = [s for s in rows if s['case']['phase'] == 'navigating rooms' and s['stockLandmarks']['phase'] == 'returning']
    matches = [s for s in rows if s['stockLandmarks']['phase'] == 'matched']
    learned = next((s for s in rows if s['stockLandmarks']['phase'] == 'learning'), rows[0])
    trips, active, previous_phase = [], None, None
    for state in rows:
        phase = state['stockLandmarks']['phase']
        if phase == 'returning' and previous_phase != 'returning':
            angle = (state['pose'][2]-learned['pose'][2]+math.pi) % (2*math.pi)-math.pi
            active = dict(startStep=state['step'], placedBefore=state['case']['placed'],
                          initialHeadingDifferenceDeg=math.degrees(angle), matched=False)
            trips.append(active)
        if active and phase == 'matched':
            active.update(matched=True, endStep=state['step'], returnErrorM=math.dist(learned['pose'][:2], state['pose'][:2]))
            active = None
        if active and state['case']['phase'] == 'failed':
            active.update(endStep=state['step'], reason=state['case']['reason'])
            active = None
        previous_phase = phase
    if last['case']['passed']:
        assert {'grasping', 'lifting', 'carrying', 'placing', 'releasing', 'passed'} <= stages
        assert returns and matches and all(s['gripper']['held'] for s in returns)
        first = matches[0]
        assert first['stockLandmarks']['returnMatches'] >= 3 and first['gripper']['held']
        # The return branch must not execute or replan an A* home path.
        trip_plans = {}
        for s in returns:
            trip_plans.setdefault(s['case']['placed'], set()).add(s['case']['navigation']['plans'])
        assert all(len(plans) == 1 for plans in trip_plans.values())
        assert len(motion['captures']) == len(motion['releases']) == last['case']['required']
        assert len(trips) >= last['case']['required']
        assert all(t['matched'] for t in trips)
        for capture, release in zip(motion['captures'], motion['releases']):
            # A moved/temporarily hidden box can trigger another visual-home
            # confirmation while carrying the same brick. Every release
            # needs matched return trips after its grasp, including retries.
            carrying_trips = [t for t in trips if capture < t['startStep'] < release]
            assert carrying_trips and all(t['matched'] and t['endStep'] < release for t in carrying_trips)
        assert first['step'] < motion['releases'][0]
        release = next(s for s in rows if s['step'] == motion['releases'][0])
        assert release['case']['dockVision']['frameId'] == release['totalSteps']
    if 'route' in last['stockLandmarks']:
        for a, b in zip(rows, rows[1:]):
            route = a['stockLandmarks']['route']
            assert not route['mapInput'] and not route['oraclePose']
            if a['stockLandmarks']['phase'] != 'returning':
                continue
            assert route['trackingErrorM'] <= 0.12 and abs(route['headingErrorRad']) <= 0.35
            if b['stockLandmarks']['phase'] == 'returning' and route['cursor'] >= 0:
                moved = a['controller']['drive']['leftSpeed'] != 0
                assert b['stockLandmarks']['route']['cursor'] == route['cursor']-int(moved), (a['step'], route, b['stockLandmarks']['route'])
    definition_path = frames/'case.json'
    definition = json.loads((definition_path if definition_path.exists() else ROOT/f'flex/sim/cases/{last["case"]["id"]}.json').read_text())
    independent = module('physical_case_audit', 'sim-cases.py')
    for obj in last['case']['objects']:
        if obj['inside']:
            independent.contained(obj, definition, last['case']['container'])
    manifest = json.loads((ROOT/'build/flex/vision/yolo26n/model.json').read_text())
    events = [json.loads(line) for line in (frames/'observations.jsonl').open()]
    return_events = [e for e in events if e['stockLandmarks']['phase'] == 'returning' and e['stockLandmarks']['returnMatches'] > 0]
    for event in events:
        s = event['stockLandmarks']
        path = frames/f'frame-{s["frames"]}.json'
        result = json.loads(path.read_text())
        assert result['runtime'] == 'pup' and result['model']['weightsSha256'] == manifest['weightsSha256']
        camera = json.loads((frames/f'frame-{s["frames"]}.png.camera.json').read_text())
        assert camera['frameId'] == s['frameId'] and camera['view'] == 'tcp'
        if s['returnMatches'] and s['phase'] == 'returning':
            assert event['step']-s['frameId'] <= 20
    if last['case']['passed']:
        assert len(return_events) >= 2
    report = dict(motion, schema='puppybot.stock-pickup-audit.v1', caseId=last['case']['id'], required=last['case']['required'], stockModel=manifest['id'],
        minimumConfidence=last['stockLandmarks'].get('minimumConfidence', 0.4), stockFrames=len(events),
        returnMatches=last['stockLandmarks']['returnMatches'], returnPoseErrorM=None,
        returnTrips=trips,
        learnedReferenceClass=last['stockLandmarks']['referenceClassId'],
        maxRememberedRgbObstacles=max((s['case']['navigation'].get('rememberedRgbObstacles', 0) for s in rows), default=0),
        maxRouteTrackingErrorM=max((s['stockLandmarks'].get('route', {}).get('trackingErrorM', 0) for s in rows), default=0),
        policy=dict(outbound='known-static-map-wheel-integration-and-RGB-floor-memory' if 'rememberedRgbObstacles' in last['case']['navigation'] else 'known-static-map-and-wheel-integration', brick='rgb-colour-components',
                    returnNavigation='recorded-command-route-and-stock-YOLO-home-confirmation' if 'route' in last['stockLandmarks'] else 'stock-YOLO-and-RGB-view-match', box='fresh-TCP-rim-RGB', outcome='physical-judge'),
        limitations=['Command integration cannot observe wheel slip; no visual drift correction in the route controller' if 'route' in last['stockLandmarks'] else 'Straight stock-view return; room turns are an experimental challenge', 'Outbound still uses supplied map and spawn prior',
                     'Stock COCO does not detect LEGO or the storage box', 'Synthetic physics; no hardware validation'])
    if matches:
        report['returnPoseErrorM'] = math.dist(learned['pose'][:2], matches[0]['pose'][:2])
    (frames/'sequence-audit.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))
    return report


def run(directory, confidence, case, drift=None):
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    frames = directory/'frames'
    command = [str(ROOT/'build/flex/puppybot-sim'), '--case', case, '--landmark-confidence', str(confidence),
               '--hidden', '--steps', '60000' if case == 'stock-landmark-room' else '12000', '--until-done', '--bind', '127.0.0.1:0',
               '--landmark-output', str(frames), '--record', str(directory/'trace.jsonl'), '--capture', str(directory/'outcome.png')]
    if drift is not None:
        command += ['--drift', str(drift)]
    (directory/'command.json').write_text(json.dumps(command, indent=2)+'\n')
    receipt = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in
               (ROOT/'build/flex/puppybot-sim', ROOT/'build/flex/puppybot-vision', ROOT/'build/flex/vision/yolo26n/model.json',
                ROOT/f'flex/sim/cases/{case}.json')}
    (directory/'hashes.json').write_text(json.dumps(receipt, indent=2)+'\n')
    with (directory/'run.log').open('w') as output:
        child = subprocess.Popen(command, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT)
        deadline, next_report = time.monotonic()+(1500 if case == 'stock-landmark-room' else 320), 0
        try:
            while child.poll() is None:
                if time.monotonic() >= deadline:
                    raise RuntimeError('native sequence exceeded wall-clock deadline')
                if time.monotonic() >= next_report:
                    path = directory/'trace.jsonl'
                    if path.exists() and path.stat().st_size:
                        with path.open('rb') as journal:
                            journal.seek(max(0, path.stat().st_size-65536))
                            state = json.loads(journal.read().splitlines()[-1])
                        print(f'{state["step"]}: {state["case"]["phase"]}, stock {state["stockLandmarks"]["phase"]}, held={state["gripper"]["held"]}', flush=True)
                    next_report = time.monotonic()+15
                time.sleep(0.1)
        finally:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=10)
    assert child.returncode in (0, 1), (directory/'run.log').read_text()
    (frames/'case.json').write_text((ROOT/f'flex/sim/cases/{case}.json').read_text())
    return audit(directory/'trace.jsonl', frames)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, help='run the complete experiment in a new directory')
    parser.add_argument('--confidence', type=int, choices=range(25, 101), default=40, metavar='25..100')
    parser.add_argument('--case', choices=('stock-landmark-pickup', 'stock-landmark-room'), default='stock-landmark-pickup')
    parser.add_argument('--trace', type=Path)
    parser.add_argument('--frames', type=Path)
    parser.add_argument('--drift', type=int, choices=range(101), metavar='0..100')
    args = parser.parse_args()
    if args.run:
        run(args.run, args.confidence, args.case, args.drift)
    if args.trace:
        if not args.frames:
            parser.error('--trace requires --frames DIRECTORY')
        audit(args.trace, args.frames)
    if not (args.run or args.trace):
        parser.error('choose --run NEW_DIRECTORY or --trace FILE --frames DIRECTORY')


if __name__ == '__main__':
    main()
