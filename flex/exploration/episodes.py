#!/usr/bin/env python3
"""Compare complete no-map pickup systems on the same held-out native scenes."""
import argparse
import csv
import importlib.util
import json
import math
import os
from pathlib import Path
import platform
import shutil
import signal
import subprocess
import sys
import tempfile
import time

import cv2
import numpy as np

from policy import sha256


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def released_inside(state, definition, geometry):
    inside = []
    for obj in state['case']['objects']:
        if state['gripper']['held'] and obj['body'] == state['gripper']['body']:
            continue
        try:
            geometry.contained(obj, definition, state['case']['container'])
        except AssertionError:
            continue
        inside.append(obj['id'])
    return inside


def audit(run, workspace, definition):
    checks = module('episode_geometry', workspace/'flex/tests/sim-discovery-pickup.py')
    geometry = module('episode_containment', workspace/'flex/tests/sim-cases.py')
    checks.ROOT = workspace
    judge = checks.HeldGeometry()
    requests = [json.loads(p.read_text()) for p in (run/'map').rglob('input-*.json')]
    needed = {r['frameId'] for r in requests} | {f['frameId'] for r in requests for f in r['frames']}
    states, captures, releases, arrivals = {}, [], [], []
    first = previous = None
    distance = 0.
    timeline = []
    inside_since = {obj['id']: None for obj in definition['objects']}
    for line in (run/'trace.jsonl').open('rb'):
        assert line.endswith(b'\n'), 'truncated native observation'
        state = json.loads(line)
        case = state['case']
        assert not state['physicsFault'] and not state['vehicle']['queryFault']
        assert not state['discovery']['suppliedMap'] and not state['discovery']['worldPoseInput']
        assert case['navigation']['coverageCount'] == 0
        if first is None:
            first = state
            checks.check_scene_start(first, definition)
            assert state['localization']['pose'] == [0, 0, 0]
            assert state['discovery']['freeCells'] == state['discovery']['occupiedCells'] == 0
        if state['step'] in needed:
            states[state['step']] = state
        judge.check(state)
        inside = {obj['id'] for obj in case['objects'] if obj['inside']}
        if not timeline or timeline[-1]['delivered'] != len(inside):
            timeline.append(dict(step=state['step'], delivered=len(inside)))
        assert not (state['gripper']['held'] and any(obj['body'] == state['gripper']['body'] for obj in case['objects'] if obj['inside']))
        for obj in case['objects']:
            if obj['id'] in inside:
                if inside_since[obj['id']] is None:
                    geometry.contained(obj, definition, case['container'])
                    inside_since[obj['id']] = state['step']
                    arrivals.append(dict(object=obj['id'], step=state['step']))
            else:
                inside_since[obj['id']] = None
        if previous:
            assert state['step'] == previous['step']+1
            drive = previous['controller']['drive']
            travel = (drive['leftSpeed']+drive['rightSpeed'])/20000
            x, y, heading = previous['pose']
            heading = (heading-travel/.18*math.tan(math.radians(drive['steeringAngleDeg']-90))+math.pi)%(2*math.pi)-math.pi
            expected = previous['pose'] if state['blocked'] else [x+travel*math.cos(heading), y+travel*math.sin(heading), heading]
            assert math.dist(state['pose'][:2], expected[:2]) < 1e-7, ('nonphysical base increment', state['step'])
            assert abs((state['pose'][2]-expected[2]+math.pi)%(2*math.pi)-math.pi) < 1e-7
            distance += math.dist(state['pose'][:2], previous['pose'][:2])
            if state['gripper']['held'] and not previous['gripper']['held']:
                assert state['gripper']['captureContactMask'] == 3
                captures.append(dict(body=state['gripper']['body'], step=state['step']))
            if previous['gripper']['held'] and not state['gripper']['held']:
                releases.append(dict(body=previous['gripper']['body'], step=state['step']))
        previous = state
    assert first is not None and previous is not None and set(states) == needed
    images = set()
    for request in requests:
        assert set(request) == {'schema', 'frameId', 'newScan', 'pose', 'frames'}
        assert request['pose'] == states[request['frameId']]['localization']['pose']
        for frame in request['frames']:
            assert set(frame) == {'rgb', 'frameId', 'calibration', 'robot'}
            state = states[frame['frameId']]
            assert frame['calibration'] == state['case']['perception']['calibration']
            np.testing.assert_allclose(frame['robot'], judge.robot_boxes(state), atol=1e-8, rtol=0)
            metadata = json.loads((run/'sensor'/f'frame-{frame["frameId"]}.png.camera.json').read_text())
            eye, axis = checks.camera_frame_error(state, frame['calibration'], metadata)
            assert eye < .003 and axis < .00003
            image = cv2.imread(str(run/'sensor'/f'frame-{frame["frameId"]}.png'))
            assert image is not None and Path(frame['rgb']).read_bytes() == cv2.cvtColor(image, cv2.COLOR_BGR2RGB).tobytes()
            images.add(frame['frameId'])
    last = previous
    case = last['case']
    independently_inside = released_inside(last, definition, geometry)
    success = len(independently_inside) == len(definition['objects']) and not last['gripper']['held']
    if case['passed']:
        assert success
    result = dict(passed=True, physicalMotionIncrementsChecked=last['step']-1,
        heldFramesChecked=judge.frames, stereoRequestsChecked=len(requests), rawRGBMatched=len(images),
        coldUnknownMap=True, actorReferenceGeometry=False, captures=captures, releases=releases,
        settledArrivals=arrivals, independentlyContained=independently_inside, distanceM=distance,
        deliveryTimeline=timeline,
        fullTaskSuccess=success and case['passed'])
    (run/'audit.json').write_text(json.dumps(result, indent=2)+'\n')
    return last, result


def summarize(output, rows, plan):
    with (output/'summary.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    policies = {}
    for mode in plan['policies']:
        selected = [r for r in rows if r['policy'] == mode]
        if not selected:
            continue
        successful = [r for r in selected if r['taskPassed']]
        policies[mode] = dict(episodes=len(selected), completedMissions=len(successful),
            successRate=len(successful)/len(selected), delivered=sum(r['delivered'] for r in selected),
            deliveriesPerActionMinute=60*sum(r['delivered'] for r in selected)/sum(r['actionSeconds'] for r in selected),
            deliveriesPerBudgetMinute=60*sum(r['delivered'] for r in selected)/sum(r['actionSeconds'] if r['taskPassed'] else plan['steps']*.02 for r in selected),
            meanActionSeconds=float(np.mean([r['actionSeconds'] for r in selected])),
            meanWallSeconds=float(np.mean([r['wallSeconds'] for r in selected])),
            meanCappedCompletionSeconds=float(np.mean([r['actionSeconds'] if r['taskPassed'] else plan['steps']*.02 for r in selected])),
            completedActionSeconds=[r['actionSeconds'] for r in successful])
    result = dict(schema='puppybot.pickup-system-comparison.v1',
        complete=len(rows) == len(plan['seeds'])*len(plan['policies'])*plan['repeats'],
        allAuditsPassed=all(r.get('auditPassed', False) for r in rows),
        rows=rows, policies=policies, evaluationUnit='Complete six-brick episode; no architecture score',
        timeDefinition='actionSeconds excludes stationary mapping worker waits; wallSeconds includes all inference and rendering; actionPlusMappingSeconds adds measured mapping waits',
        limitations=['Small held-out pilot; no broad generalization or hardware claim.',
            'Training uses approximate visibility labels; episode evaluation uses actual pickup and physical containment.',
            'Failed and timed-out episodes remain in success and throughput denominators.'])
    (output/'summary.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(dict(complete=result['complete'], policies=policies)), flush=True)


def trial(output, workspace, scene, seed, mode, repeat, plan):
    run = output/'episodes'/f'{seed}-{mode}-{repeat}'
    run.mkdir(parents=True, exist_ok=False)
    encoder = Path(plan['encoder'])
    weights = Path(plan['weights'])
    environment = dict(os.environ, OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1',
        PUPPYBOT_EXPLORATION_POLICY=mode, PUPPYBOT_EXPLORATION_WEIGHTS=str(weights),
        PUPPYBOT_ENCODER=str(encoder), PUPPYBOT_ENCODER_BACKEND='cuda')
    environment.pop('PUPPYBOT_ENCODER_KERNEL', None)
    args = [str(workspace.parent/'controller'), '--hidden', '--case-file', str(scene/'case.json'),
        '--environment', str(scene/'environment.bin'), '--steps', str(plan['steps']), '--mapping-scans', '100',
        '--until-done', '--bind', '127.0.0.1:0', '--map-output', str(run/'map'),
        '--record', str(run/'trace.jsonl'), '--search-output', str(run/'sensor'), '--capture', str(run/'outcome.png'), '--tcp-view']
    (run/'launch.json').write_text(json.dumps(dict(args=args, cwd=str(workspace), seed=seed, policy=mode,
        repeat=repeat, initialMap='unknown', odometrySeed=42, inferenceCache='new empty directory per episode'), indent=2)+'\n')
    print(json.dumps(dict(startingEpisode=str(run), policy=mode, seed=seed, stepBudget=plan['steps'])), flush=True)
    started = time.monotonic()
    timed_out = False
    service = temporary = service_log = None
    if mode == 'yolo':
        temporary = tempfile.TemporaryDirectory(prefix='puppybot-encoder-')
        endpoint = Path(temporary.name)/'encoder.sock'
        environment['PUPPYBOT_ENCODER_SOCKET'] = str(endpoint)
        service_log = (run/'encoder-service.log').open('wb')
        service = subprocess.Popen(['python3', str(workspace/'flex/exploration/encoder_service.py'),
            '--encoder', str(encoder), '--cache', str(run/'encoder-cache'), '--socket', str(endpoint)],
            env=environment, stdout=service_log, stderr=service_log)
        deadline = time.monotonic()+15
        while not endpoint.exists():
            assert service.poll() is None and time.monotonic() < deadline, 'encoder service failed to start'
            time.sleep(.01)
    with (run/'run.log').open('wb') as log:
        process = subprocess.Popen(args, cwd=workspace, env=environment, stdout=log, stderr=subprocess.STDOUT)
        try:
            code = process.wait(timeout=plan['wallTimeoutSeconds'])
        except BaseException as error:
            process.send_signal(signal.SIGINT)
            try:
                code = process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
                code = process.wait(timeout=5)
            if not isinstance(error, subprocess.TimeoutExpired):
                raise
            timed_out = True
        finally:
            if service is not None:
                service.terminate()
                try:
                    service.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    service.kill()
                    service.wait(timeout=5)
                service_log.close()
                temporary.cleanup()
    elapsed = time.monotonic()-started
    (run/'exit.json').write_text(json.dumps(dict(code=code, timedOut=timed_out, wallSeconds=elapsed))+'\n')
    row = dict(seed=seed, policy=mode, repeat=repeat, exitCode=code, timedOut=timed_out,
        auditPassed=False, taskPassed=False, delivered=0, required=6, actionSeconds=plan['steps']*.02,
        mappingWaitSeconds=0., actionPlusMappingSeconds=plan['steps']*.02, wallSeconds=elapsed,
        firstDeliveryActionSeconds=None, captures=0, releases=0, driveStops=0, armStops=0,
        yoloRankingCalls=0, yoloVisualDecisions=0, distanceM=0., reason='', auditError='')
    try:
        last, result = audit(run, workspace, json.loads((scene/'case.json').read_text()))
        action = last['step']*.02
        waiting = last['benchmarkMappingWaitMs']/1000
        reason = last['case']['reason']
        if last['discovery']['phase'] == 7:
            reason = last['discovery']['reason']
        if last['step'] >= plan['steps'] and not result['fullTaskSuccess']:
            reason = 'action budget exhausted: '+reason
        if timed_out:
            reason = 'wall time budget exhausted: '+reason
        row.update(auditPassed=True, taskPassed=not timed_out and code == 0 and result['fullTaskSuccess'],
            delivered=len(result['independentlyContained']), actionSeconds=action, mappingWaitSeconds=waiting,
            actionPlusMappingSeconds=action+waiting, firstDeliveryActionSeconds=result['settledArrivals'][0]['step']*.02 if result['settledArrivals'] else None,
            captures=len(result['captures']), releases=len(result['releases']), distanceM=result['distanceM'],
            driveStops=last['discovery']['protectiveStops'], armStops=last['discovery']['armProtectiveStops'], reason=reason)
        rankings = [json.loads(p.read_text()) for p in (run/'map').rglob('ranking-*.json')]
        if mode == 'yolo':
            assert rankings and all(r['networkWeight'] > 0 and not r['fallback'] and not r['masksChanged'] for r in rankings)
            row['yoloRankingCalls'] = len(rankings)
            row['yoloVisualDecisions'] = sum(r['topScoreVisualNorm'] > 0 and r['visualAblationMaxScoreDifference'] > 0 for r in rankings)
            assert row['yoloVisualDecisions'] > 0
        else:
            assert not rankings
    except (AssertionError, ValueError, KeyError, FileNotFoundError) as error:
        row.update(auditPassed=False, taskPassed=False, auditError=str(error) or type(error).__name__)
    (run/'episode.json').write_text(json.dumps(row, indent=2)+'\n')
    print(json.dumps(row), flush=True)
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts', type=Path, required=True)
    parser.add_argument('--frozen', type=Path, required=True)
    parser.add_argument('--encoder', type=Path, required=True)
    parser.add_argument('--training', type=Path, required=True)
    parser.add_argument('--seeds', type=int, nargs='+', default=[81001, 81002])
    parser.add_argument('--rooms', type=int, nargs='+', default=[2, 3])
    parser.add_argument('--steps', type=int, default=350000)
    parser.add_argument('--repeats', type=int, default=1)
    parser.add_argument('--timeout', type=int, default=2400)
    args = parser.parse_args()
    assert len(args.seeds) == len(set(args.seeds)) == len(args.rooms)
    assert 1 <= args.steps <= 1000000 and args.repeats > 0 and args.timeout > 0
    output, workspace = args.artifacts.resolve(), args.frozen.resolve()/'workspace'
    output.mkdir(parents=True, exist_ok=False)
    training = json.loads((args.training/'training-report.json').read_text())
    used = {seed for split in training['sceneSplit'].values() for seed in split}
    assert not used.intersection(args.seeds)
    assert json.loads((args.frozen/'freeze-receipt.json').read_text())['synchronousMapping']
    generator = module('episode_generator', workspace/'flex/scripts/generate-layout.py')
    scenes = {}
    for seed, count in zip(args.seeds, args.rooms):
        assert 2 <= count <= 6
        scenes[seed] = generator.write(generator.generate(seed, count), output/'scenes'/str(seed))
    plan = dict(schema='puppybot.pickup-experiment.v1', seeds=args.seeds, rooms=args.rooms,
        policies=['heuristic', 'yolo'], repeats=args.repeats, steps=args.steps, wallTimeoutSeconds=args.timeout,
        encoder=str(args.encoder.resolve()), weights=str(args.training.resolve()/'checkpoint.npz'),
        checkpointSha256=sha256(args.training/'checkpoint.npz'),
        runtimeSha256=sha256(args.training/'runtime.json'), split=training['sceneSplit'],
        encoderBackend='cuda', encoderLifetime='one resident native worker per episode; fresh cache and startup included',
        comparison='Same robot, RGB-only sensors, no supplied map, physics, case files, scheduler and action budget; frozen heads before held-out episodes')
    (output/'experiment-plan.json').write_text(json.dumps(plan, indent=2)+'\n')
    (output/'environment.json').write_text(json.dumps(dict(python=sys.version, platform=platform.platform(),
        numpy=np.__version__, opencv=cv2.__version__, execution='Sequential episodes; no concurrent training or simulation in this benchmark'), indent=2)+'\n')
    evaluation = output/'evaluation-source'
    evaluation.mkdir()
    for path in (Path(__file__), Path(__file__).with_name('policy.py'), Path(__file__).with_name('episode_report.py')):
        shutil.copyfile(path, evaluation/path.name)
    paths = [p for p in workspace.rglob('*') if p.is_file() and '__pycache__' not in str(p)]
    paths += [args.frozen.resolve()/'controller', args.training.resolve()/'checkpoint.npz', args.training.resolve()/'runtime.json']
    paths += [p for p in args.encoder.resolve().rglob('*') if p.is_file()]
    paths += [p for p in (output/'scenes').rglob('*') if p.is_file()]
    paths += list(evaluation.iterdir())
    manifest = {str(path): sha256(path) for path in paths}
    (output/'source-manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    rows = []
    for repeat in range(1, args.repeats+1):
        for index, seed in enumerate(args.seeds):
            modes = plan['policies'][::1 if (index+repeat)%2 else -1]
            for mode in modes:
                rows.append(trial(output, workspace, scenes[seed], seed, mode, repeat, plan))
                assert all(sha256(Path(path)) == digest for path, digest in manifest.items()), 'frozen runtime changed'
                summarize(output, rows, plan)


if __name__ == '__main__':
    main()
