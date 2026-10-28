#!/usr/bin/env python3
"""Run and independently audit complete native RGB find-and-return episodes."""
import argparse
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import time

import cv2
import numpy as np

from bootstrap import module
from policy import sha256

ROOT = Path(__file__).resolve().parents[2]


def room_at(layout, xy):
    return next((i for i, room in enumerate(layout['rooms'])
        if room[0] <= xy[0] <= room[2] and room[1] <= xy[1] <= room[3]), None)


def hide_brick(layout, generator):
    """Scene construction only: one reachable distant target outside home room."""
    free = generator.free_grid(layout['bounds'], layout['objects'])
    reached = generator.flood(free, layout['bounds'], layout['spawn'])
    rows, cols = np.nonzero(reached)
    xy = np.column_stack((cols, rows))*.1+np.asarray(layout['bounds'][:2])+.05
    candidates = []
    for point in xy:
        room = room_at(layout, point)
        distance = math.dist(point, layout['spawn'][:2])
        if room is None or room == layout['startRoom'] or distance < 4.3:
            continue
        bounds = layout['rooms'][room]
        if min(point[0]-bounds[0], bounds[2]-point[0], point[1]-bounds[1], bounds[3]-point[1]) < .55:
            continue
        candidates.append((distance, point, room))
    if not candidates:
        raise ValueError('layout has no reachable hidden target at least 4.3 m from home')
    distance, point, room = min(candidates, key=lambda candidate: candidate[0])
    brick = layout['case']['objects'][0]
    brick['position'][:2] = point.tolist()
    layout['case']['objects'] = [brick]
    layout['validation'].pop('sixReachableBrickLocations', None)
    layout['validation']['oneReachableHiddenBrick'] = True
    layout['findReturnTask'] = dict(kind='hidden-room', targetRoom=room,
        initialTargetDistanceM=distance, minimumExcursionM=1.5,
        initiallyOutsideCameraRange=True, requiresLeavingStartRoom=True)
    return layout


def audit(run, workspace):
    checks = module('seek_camera_checks', workspace/'flex/tests/sim-discovery-pickup.py')
    checks.ROOT = workspace
    boxes = checks.HeldGeometry()
    requests = [json.loads(p.read_text()) for p in (run/'map').rglob('input-*.json')]
    needed = {r['frameId'] for r in requests} | {f['frameId'] for r in requests for f in r['frames']}
    states, events = {}, []
    layout = None
    if (run/'launch.json').exists():
        args = json.loads((run/'launch.json').read_text())['args']
        path = Path(args[args.index('--environment')+1]).parent/'layout.json'
        if path.exists():
            layout = json.loads(path.read_text())
    previous = first = None
    distance = search_distance = max_excursion = search_excursion = 0.
    moving_steps = 0
    rooms, search_rooms = set(), set()
    image_checks = 0
    for line in (run/'trace.jsonl').open():
        assert line.endswith('\n')
        state = json.loads(line)
        assert not state['physicsFault'] and not state['vehicle']['queryFault']
        assert not state['discovery']['suppliedMap'] and not state['discovery']['worldPoseInput']
        assert state['case']['navigation']['coverageCount'] == 0
        assert state['gripper']['grasps'] == state['gripper']['releases'] == 0
        assert not state['gripper']['held'] and not state['gripper']['constraintActive']
        assert state['case']['phase'] not in ('grasping', 'lifting', 'carrying', 'placing', 'releasing')
        if first is None:
            first = state
            assert state['localization']['pose'] == [0, 0, 0]
            assert state['discovery']['freeCells'] == state['discovery']['occupiedCells'] == 0
        if state['step'] in needed:
            states[state['step']] = state
        excursion = math.dist(state['pose'][:2], first['pose'][:2])
        max_excursion = max(max_excursion, excursion)
        searching = state['findReturn']['consumedIndex'] < 0 or (
            previous is not None and previous['findReturn']['consumedIndex'] < 0)
        if searching:
            search_excursion = max(search_excursion, excursion)
        if layout is not None:
            room = room_at(layout, state['pose'][:2])
            if room is not None:
                rooms.add(room)
                if searching:
                    search_rooms.add(room)
        if previous is not None:
            assert state['step'] == previous['step']+1
            drive = previous['controller']['drive']
            travel = (drive['leftSpeed']+drive['rightSpeed'])/20000
            x, y, heading = previous['pose']
            heading = (heading-travel/.18*math.tan(math.radians(drive['steeringAngleDeg']-90))+math.pi)%(2*math.pi)-math.pi
            expected = previous['pose'] if state['blocked'] else [x+travel*math.cos(heading), y+travel*math.sin(heading), heading]
            assert math.dist(state['pose'][:2], expected[:2]) < 1e-7
            assert abs((state['pose'][2]-expected[2]+math.pi)%(2*math.pi)-math.pi) < 1e-7
            increment = math.dist(state['pose'][:2], previous['pose'][:2])
            distance += increment
            moving_steps += increment > 1e-9
            if previous['findReturn']['consumedIndex'] < 0:
                search_distance += increment
            event = state['findReturn']
            if event['consumedIndex'] >= 0 and previous['findReturn']['consumedIndex'] < 0:
                index = event['consumedIndex']
                assert state['step'] == event['detectionStep'] and len(events) == 0
                before = previous['case']['objects'][index]
                after = state['case']['objects'][index]
                assert before['position'][2] > -.01 and after['position'][2] == -10
                assert after['velocity'] == [0, 0, 0]
                camera = json.loads((run/'sensor'/f'frame-{state["step"]}.png.camera.json').read_text())
                image = cv2.imread(str(run/'sensor'/f'frame-{state["step"]}.png'))
                assert image is not None and camera['frameId'] == state['step']
                x1, y1, x2, y2 = event['detectionPixelBox']
                assert 0 <= x1 < x2 <= 640 and 0 <= y1 < y2 <= 480
                patch = image[y1:y2, x1:x2].astype(float)
                assert np.count_nonzero(patch.max(2)-patch.min(2) > 35) >= 18
                point = np.asarray(before['position'])-camera['eyeM']
                depth = float(point@camera['forward'])
                assert depth > 0
                uv = [320+415.69224*float(point@camera['right'])/depth,
                      240+415.69224*float(point@camera['down'])/depth]
                assert x1-12 <= uv[0] <= x2+12 and y1-12 <= uv[1] <= y2+12, (uv, event)
                events.append(dict(step=state['step'], object=before['id'], body=before['body'],
                    pixelBox=event['detectionPixelBox'], independentlyProjectedPixel=uv))
            if event['consumedIndex'] >= 0:
                assert state['case']['objects'][event['consumedIndex']]['position'][2] == -10
        previous = state
    assert first is not None and previous is not None and set(states) == needed
    for request in requests:
        assert set(request) == {'schema', 'frameId', 'newScan', 'pose', 'frames', 'seek'}
        assert set(request['seek']) == {'returning', 'box'}
        state = states[request['frameId']]
        assert request['pose'] == state['localization']['pose']
        assert request['seek']['returning'] == (state['findReturn']['consumedIndex'] >= 0)
        if request['seek']['box'] is not None:
            np.testing.assert_allclose(request['seek']['box'], state['case']['dockVision']['positionM'][:2], atol=0, rtol=0)
        for frame in request['frames']:
            state = states[frame['frameId']]
            np.testing.assert_allclose(frame['robot'], boxes.robot_boxes(state), atol=1e-8, rtol=0)
            metadata = json.loads((run/'sensor'/f'frame-{frame["frameId"]}.png.camera.json').read_text())
            eye, axis = checks.camera_frame_error(state, frame['calibration'], metadata)
            assert eye < .003 and axis < .00003
            image = cv2.imread(str(run/'sensor'/f'frame-{frame["frameId"]}.png'))
            assert Path(frame['rgb']).read_bytes() == cv2.cvtColor(image, cv2.COLOR_BGR2RGB).tobytes()
            image_checks += 1
    last = previous
    delta = np.asarray(last['case']['container']['position'][:2])-last['pose'][:2]
    range_m = float(np.linalg.norm(delta))
    heading_error = abs((math.atan2(delta[1], delta[0])-last['pose'][2]+math.pi)%(2*math.pi)-math.pi)
    dock = last['case']['dockVision']
    drive = last['controller']['drive']
    verified = bool(len(events) == 1 and .30 <= range_m <= .65 and heading_error <= math.radians(35)
        and dock['valid'] and last['step']-dock['frameId'] <= 2 and dock['stableObservations'] >= 3
        and not drive['leftSpeed'] and not drive['rightSpeed'] and last['findReturn']['stableReturnObservations'] >= 3)
    if last['case']['passed']:
        assert verified, (range_m, heading_error, dock)
    rankings = [json.loads(p.read_text()) for p in (run/'map').rglob('seek-ranking-*.json')]
    assert all(not r['masksChanged'] for r in rankings)
    require_exploration = layout is not None and layout.get('findReturnTask', {}).get('requiresLeavingStartRoom', False)
    explored = layout is not None and bool(search_rooms-{layout['startRoom']}) and search_excursion >= 1.5
    result = dict(passed=True, taskSuccess=verified and last['case']['passed'],
        frames=last['step'], physicalMotionIncrementsChecked=last['step']-first['step'],
        coldUnknownMap=True, suppliedCoveragePoses=0, actorWorldCoordinates=False,
        grasps=0, releases=0, consumptionEvents=events, rawRGBMatched=image_checks,
        stereoRequests=len(requests), distanceM=distance, finalTrueBoxRangeM=range_m,
        searchDistanceM=search_distance, maxExcursionM=max_excursion, searchMaxExcursionM=search_excursion,
        movingSeconds=moving_steps*.02, stationarySeconds=(last['step']-first['step']+1-moving_steps)*.02,
        roomsVisited=sorted(rooms), searchRoomsVisited=sorted(search_rooms),
        explorationRequired=require_exploration, explorationDemonstrated=explored,
        finalTrueHeadingErrorDegrees=math.degrees(heading_error),
        rankingCalls=len(rankings), rankingPhases=sorted({r['phase'] for r in rankings}),
        modelHashes=sorted({r['weightsSHA256'] for r in rankings if r['weightsSHA256']}))
    (run/'audit.json').write_text(json.dumps(result, indent=2)+'\n')
    return last, result


def trial(frozen, scene, output, policy, weights, steps, timeout, video=False, observer_distance=None):
    output.mkdir(parents=True, exist_ok=False)
    environment = dict(os.environ, OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1',
        PUPPYBOT_SEEK_POLICY=policy, PUPPYBOT_SEEK_WEIGHTS=str(weights))
    args = [str(frozen/'controller'), '--hidden', '--case-file', str(scene/'case.json'),
        '--environment', str(scene/'environment.bin'), '--steps', str(steps), '--mapping-scans', '60',
        '--until-done', '--bind', '127.0.0.1:0', '--map-output', str(output/'map'),
        '--record', str(output/'trace.jsonl'), '--search-output', str(output/'sensor'), '--capture', str(output/'outcome.png'), '--tcp-view']
    if video:
        args += ['--video', str(output/'mission.mp4'), '--video-fps', '5']
    if observer_distance is not None:
        args += ['--observer-distance-mm', str(observer_distance)]
    (output/'launch.json').write_text(json.dumps(dict(args=args, policy=policy, initialMap='unknown', weightsSHA256=sha256(weights)), indent=2)+'\n')
    started = time.monotonic()
    timed_out = False
    with (output/'run.log').open('w') as log:
        process = subprocess.Popen(args, cwd=frozen/'workspace', env=environment, stdout=log, stderr=log)
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            process.send_signal(signal.SIGINT)
            try:
                code = process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                code = process.wait()
    elapsed = time.monotonic()-started
    last, checks = audit(output, frozen/'workspace')
    if policy == 'mlp':
        assert checks['modelHashes'] == [sha256(weights)]
    task_passed = checks['taskSuccess'] and (not checks['explorationRequired'] or checks['explorationDemonstrated'])
    row = dict(policy=policy, taskPassed=task_passed, found=bool(checks['consumptionEvents']),
        actionSeconds=last['step']*.02, wallSeconds=elapsed, timedOut=timed_out, exitCode=code,
        mappingWaitSeconds=last.get('benchmarkMappingWaitMs', 0)/1000,
        reason=last['case']['reason'], distanceM=checks['distanceM'],
        searchDistanceM=checks['searchDistanceM'], maxExcursionM=checks['maxExcursionM'],
        movingSeconds=checks['movingSeconds'], stationarySeconds=checks['stationarySeconds'],
        roomsVisited=checks['roomsVisited'], searchRoomsVisited=checks['searchRoomsVisited'], run=str(output))
    (output/'result.json').write_text(json.dumps(row, indent=2)+'\n')
    print(json.dumps(row), flush=True)
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--frozen', type=Path, required=True)
    parser.add_argument('--audit-run', type=Path, help='independently recheck an existing recording')
    parser.add_argument('--weights', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--seeds', type=int, nargs='+', default=[96001, 96002])
    parser.add_argument('--steps', type=int, default=60000)
    parser.add_argument('--timeout', type=int, default=300)
    parser.add_argument('--hidden-brick', action='store_true', default=True, help='require search outside the start room for one distant brick (default)')
    parser.add_argument('--nearby-bricks', dest='hidden_brick', action='store_false', help='legacy nearby-sighting smoke test; not an exploration benchmark')
    parser.add_argument('--policies', nargs='+', choices=('heuristic', 'mlp'), default=['heuristic', 'mlp'])
    parser.add_argument('--observer-distance-mm', type=int, default=3500, help='closer camera following the robot, without changing sensor views')
    args = parser.parse_args()
    if args.audit_run:
        _, result = audit(args.audit_run.resolve(), args.frozen.resolve()/'workspace')
        print(json.dumps(result, indent=2))
        return
    if args.weights is None or args.output is None:
        parser.error('--weights and --output are required for a comparison')
    args.frozen, args.weights, args.output = args.frozen.resolve(), args.weights.resolve(), args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    generator = module('native_seek_generator', args.frozen/'workspace/flex/scripts/generate-layout.py')
    plan = dict(seeds=args.seeds, policies=args.policies, hiddenBrick=args.hidden_brick, steps=args.steps, timeoutSeconds=args.timeout,
        explorationGate='leave starting room and reach at least 1.5 m search excursion' if args.hidden_brick else 'none; nearby-sighting smoke test only',
        weightsSHA256=sha256(args.weights), frozenManifestSHA256=sha256(args.frozen/'frozen-source-manifest.json'),
        task='First RGB sighting consumes one brick; stopped at 0.30-0.65 m from freshly observed box, facing it within 35 degrees; no manipulation')
    (args.output/'plan.json').write_text(json.dumps(plan, indent=2)+'\n')
    rows = []
    for index, seed in enumerate(args.seeds):
        scene = args.output/f'scene-{seed}'
        layout = generator.generate(seed, 2+index%2)
        layout['case']['id'] = f'find-return-{seed}'
        layout['case']['controller'] = 'rgb-find-return'
        if args.hidden_brick:
            hide_brick(layout, generator)
        generator.write(layout, scene)
        for policy in (args.policies if index%2 == 0 else args.policies[::-1]):
            row = trial(args.frozen, scene, args.output/f'{seed}-{policy}', policy, args.weights, args.steps, args.timeout, video=True, observer_distance=args.observer_distance_mm)
            row['seed'] = seed
            rows.append(row)
            (args.output/'summary.json').write_text(json.dumps(dict(complete=len(rows) == len(args.policies)*len(args.seeds), rows=rows, plan=plan), indent=2)+'\n')


if __name__ == '__main__':
    main()
