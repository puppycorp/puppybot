#!/usr/bin/env python3
"""Sweep repeatable RGB collection challenges, retaining failures and exact replays."""
import argparse
from collections import Counter
from datetime import datetime
import hashlib
import html
import importlib.util
import json
import math
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
BINARY = ROOT/'build/flex/puppybot-sim'
CHALLENGES = ('distractors', 'touching', 'occlusion')
NAMES = {'control': 'Separated bricks control', 'distractors': 'Coloured distractors',
         'touching': 'Touching same-colour bricks', 'occlusion': 'Partially hidden bricks'}
spec = importlib.util.spec_from_file_location('case_checks', ROOT/'flex/tests/sim-cases.py')
cases = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cases)


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2)+'\n')


def sha256(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def floor_layout(scene, seed):
    """Freeze the existing seeded floor generator into an editable replay scene."""
    settings = scene.pop('randomFloor')
    objects = scene['objects']
    result = []
    rng = seed

    def unit():
        nonlocal rng
        rng = (rng*1664525+1013904223) & 0xffffffff
        return rng/4294967296

    def box_clear(x, y, radius, bx, by, hx, hy):
        return max(abs(x-bx)-hx, 0)**2+max(abs(y-by)-hy, 0)**2 > radius**2

    for attempt in range(4096):
        obj = objects[len(result)]
        radius = math.hypot(*obj['halfSize'][:2])
        x, y = [a+unit()*(b-a) for a, b in zip(settings['min'], settings['max'])]
        yaw = (2*unit()-1)*settings['yawDegrees']
        guard = radius+settings['clearance']
        container = scene['container']
        obstacles = [(0, 0, 0.14, 0.12), (0.65, -0.35, 0.12, 0.12), (-0.55, 0.45, 0.10, 0.18),
                     (*container['position'][:2], *[v/2+container['wallThickness'] for v in container['innerSize'][:2]])]
        if (all(a <= v-radius and v+radius <= b for v, a, b in zip((x, y), settings['min'], settings['max']))
                and all(box_clear(x, y, guard, *box) for box in obstacles)
                and all(math.hypot(x-px, y-py) >= guard+pr for px, py, _, pr in result)):
            result.append((x, y, yaw, radius))
            if len(result) == len(objects):
                break
        if (attempt+1) % 256 == 0:
            result.clear()
    if len(result) != len(objects):
        raise ValueError('cannot generate the control layout')
    for obj, (x, y, yaw, _) in zip(objects, result):
        obj.update(position=[x, y, obj['halfSize'][2]+0.001], yawDegrees=yaw)


def footprint(obj):
    angle = math.radians(obj.get('yawDegrees', 0))
    hx, hy = obj['halfSize'][:2]
    return abs(math.cos(angle))*hx+abs(math.sin(angle))*hy, abs(math.sin(angle))*hx+abs(math.cos(angle))*hy


def separated(a, b, clearance=0.002):
    ah, bh = footprint(a), footprint(b)
    return any(abs(a['position'][i]-b['position'][i]) >= ah[i]+bh[i]+clearance for i in range(2))


def definition(challenge, level, seed):
    """Generate the world only. Controller and detector parameters stay unchanged."""
    scene = json.loads((ROOT/'flex/sim/cases/search-blocks-into-box.json').read_text())
    floor_layout(scene, seed)
    scene['id'] = 'stress-'+challenge
    scene['scenery'] = []
    details = {'challenge': challenge, 'level': level, 'seed': seed}

    def prop(name, position, half, colour):
        item = dict(id=name, position=position, halfSize=half, color=colour)
        if not all(separated(item, obj) for obj in scene['objects']+scene['scenery']):
            raise ValueError('scenery overlaps a target in the initial scene')
        scene['scenery'].append(item)

    if challenge == 'distractors':
        if level == 1:
            prop('large-red-slab', [0.90, 0.23, 0.012], [0.065, 0.03, 0.012], [95, 22, 22])
        else:
            # A plain fixed cuboid of the same size/colour as a brick, without studs.
            position = [0.27, 0.08, 0.012]
            if level == 3:
                # Keep one decoy entirely in the original front camera's view;
                # the nearer level-2 decoy also tests cropping and blind spots.
                position = next(([x, y, 0.012] for x in (0.31, 0.34, 0.37) for y in (0.15, 0.09, 0.12, 0.18)
                                 if all(separated(dict(position=[x, y, 0.012], halfSize=[0.022, 0.014, 0.012]), obj) for obj in scene['objects'])), None)
                if position is None:
                    raise ValueError('cannot place a visible decoy without target overlap')
            prop('red-decoy', position, [0.022, 0.014, 0.012], [95, 22, 22])
            if level == 3:
                prop('blue-decoy', [0.85, 0.18, 0.012], [0.022, 0.014, 0.012], [20, 45, 95])
                prop('green-decoy', [0.85, 0.04, 0.012], [0.022, 0.014, 0.012], [24, 85, 38])
        details['nonTargets'] = len(scene['scenery'])
    elif challenge == 'touching':
        gap = (0.015, 0.003, 0)[level-1]
        first, second = scene['objects'][:2]
        first['yawDegrees'] = second['yawDegrees'] = 0
        second['color'] = first['color'][:]
        # Find room for the pair without intersecting the other four bricks.
        # A shared anchor across all levels isolates the gap within each seed.
        anchor = None
        for ix in range(35, 67, 2):
            for iy in range(5, 19, 2):
                first['position'] = [ix/100, iy/100, 0.013]
                second['position'] = [ix/100+0.044+0.015, iy/100, 0.013]
                if all(separated(obj, other, 0.015) for obj in (first, second) for other in scene['objects'][2:]):
                    anchor = first['position'][:]
                    break
            if anchor:
                break
        if not anchor:
            raise ValueError('cannot fit the touching pair without overlapping other targets')
        second['position'][0] = anchor[0]+0.044+gap
        details.update(gapM=gap, pairAnchorM=anchor)
    elif challenge == 'occlusion':
        # Real grey divider, between the original front mount and one brick.
        # Nominal coverage describes the initial front projection, not a promise
        # that the controller cannot find another view as the robot moves.
        fraction = (0.25, 0.55, 1)[level-1]
        selected = None
        for obj in scene['objects']:
            x, y, _ = obj['position']
            for offset in (0.08, 0.10, 0.12):
                ratio = (x-offset-0.09)/(x-0.09)
                half = ratio*footprint(obj)[1]
                edge = ratio*y-half+(1-fraction)*2*half
                cy = edge+0.018 if level < 3 else ratio*y
                hy = 0.018 if level < 3 else half+0.004
                height = 0.24+(0.024-0.24)*ratio+0.02
                divider = dict(position=[x-offset, cy, height/2], halfSize=[0.004, hy, height/2])
                if all(separated(divider, other, 0.005) for other in scene['objects']):
                    selected = obj['id']
                    break
            if selected:
                break
        if not selected:
            raise ValueError('cannot place a divider without initial target overlap')
        prop('grey-divider', divider['position'], divider['halfSize'], [40, 40, 40])
        details.update(nominalInitialCoverage=fraction, occludedTarget=selected)
    elif challenge != 'control':
        raise ValueError(challenge)
    return scene, details


def fixture(directory, scene, details):
    target = directory/'flex/sim/cases'
    target.mkdir(parents=True)
    write_json(directory/'case.json', scene)
    write_json(directory/'challenge.json', details)
    write_json(target/'catalog.json', dict(schema='puppybot.cases.v1', cases=[dict(
        id=scene['id'], name=NAMES[details['challenge']], file='case.json', controller='rgb-search', objects=len(scene['objects']))]))
    (directory/'build').symlink_to(ROOT/'build', target_is_directory=True)


def ray(calibration, pixel):
    focal = 1.732051*480/2
    return [calibration[3+i]+(pixel[0]-320)/focal*calibration[6+i]+(pixel[1]-240)/focal*calibration[9+i] for i in range(3)]


def intersect(eye, direction, position, rotation, half):
    """Independent ray/OBB judge, used only after the simulator exits."""
    origin = [sum(rotation[k][i]*(eye[k]-position[k]) for k in range(3)) for i in range(3)]
    local = [sum(rotation[k][i]*direction[k] for k in range(3)) for i in range(3)]
    near, far = 0, math.inf
    for a, d, h in zip(origin, local, half):
        if abs(d) < 1e-12:
            if abs(a) > h:
                return None
        else:
            lo, hi = sorted(((-h-a)/d, (h-a)/d))
            near, far = max(near, lo), min(far, hi)
            if near > far:
                return None
    return near


def judge_pixel(state, scene, pixel):
    perception = state['case']['perception']
    eye = perception['calibration'][:3]
    direction = ray(perception['calibration'], pixel)
    hits = []
    for observed, source in zip(state['case']['objects'], scene['objects']):
        distance = intersect(eye, direction, observed['position'], cases.rotation(observed['quaternion']), source['halfSize'])
        if distance is not None:
            hits.append((distance, 'target', observed['id']))
    identity = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    for prop in state['case']['scenery']:
        distance = intersect(eye, direction, prop['position'], identity, prop['halfSize'])
        if distance is not None:
            hits.append((distance, 'scenery', prop['id']))
    return min(hits)[1:] if hits else ('unmatched', None)


def project(calibration, position):
    delta = [position[i]-calibration[i] for i in range(3)]
    depth = sum(delta[i]*calibration[3+i] for i in range(3))
    if depth <= 0:
        return None
    focal = 1.732051*480/2
    return [320+focal*sum(delta[i]*calibration[6+i] for i in range(3))/depth,
            240+focal*sum(delta[i]*calibration[9+i] for i in range(3))/depth]


def analyse(journal, scene, state, returncode):
    metrics = Counter()
    events = {}
    phases = Counter()
    last_frame = -1
    previous = None
    for line in journal.open():
        current = json.loads(line)
        case = current['case']
        phase = case['phase']
        phases[phase] += 1
        perception = case['perception']
        if current['physicsFault'] or current['vehicle']['queryFault']:
            metrics['physicsFaults'] += 1
        if current['blocked']:
            metrics['blockedDriveSteps'] += 1
            body = current['vehicle']['blockedBody']
            if body >= 0 and 'driveBlocked' not in events:
                obstacle = next((obj['id'] for obj in case['objects']+case['scenery'] if obj['body'] == body), None)
                events['driveBlocked'] = dict(step=current['step'], object=obstacle, image=perception['image'], perception=perception)
        if current['collision']['armBlocked']:
            metrics['blockedArmSteps'] += 1
        if previous and not previous['gripper']['held'] and current['gripper']['held']:
            metrics['physicalGrasps'] += 1
            if current['gripper']['body'] not in {obj['body'] for obj in case['objects']}:
                metrics['wrongObjectGrasps'] += 1
        if perception['samples'] and perception['frameId'] != last_frame:
            last_frame = perception['frameId']
            metrics['cameraFrames'] += 1
            # Box frames use the same sensor but have a separate detector.
            if phase in ('searching', 'approaching', 'visually aligning', 'lowering', 'grasping'):
                metrics['brickFrames'] += 1
                if not perception['detections']:
                    metrics['framesWithoutBrickDetections'] += 1
                for index, detection in enumerate(perception['detections']):
                    metrics['detections'] += 1
                    kind, name = judge_pixel(current, scene, detection['pixel'])
                    if kind == 'scenery':
                        metrics['nonTargetDetections'] += 1
                        if 'nonTargetDetection' not in events:
                            events['nonTargetDetection'] = dict(step=current['step'], image=perception['image'], object=name, perception=perception)
                        if index == perception['chosen']:
                            metrics['nonTargetSelections'] += 1
                            if 'nonTargetSelection' not in events:
                                events['nonTargetSelection'] = dict(step=current['step'], image=perception['image'], object=name, perception=perception)
                    x1, y1, x2, y2 = detection['box']
                    covered = [obj['id'] for obj in case['objects'] if (pixel := project(perception['calibration'], obj['position']))
                               and x1 <= pixel[0] < x2 and y1 <= pixel[1] < y2]
                    if len(covered) > 1:
                        metrics['boxesCoveringMultipleTargets'] += 1
                        if 'multipleTargets' not in events:
                            events['multipleTargets'] = dict(step=current['step'], image=perception['image'], objects=covered, perception=perception)
            events['lastCamera'] = dict(step=current['step'], image=perception['image'], perception=perception)
        if phase == 'failed' and 'failure' not in events:
            body = current['collision']['body'] if current['collision']['armBlocked'] else current['vehicle']['blockedBody']
            obstacle = next((obj['id'] for obj in case['objects']+case['scenery'] if obj['body'] == body), None)
            events['failure'] = dict(step=current['step'], phase=previous['case']['phase'] if previous else phase,
                                     reason=case['reason'], obstacle=obstacle, collision=current['collision'], vehicle=current['vehicle'])
        previous = current
    if previous != state:
        raise ValueError('recording does not match final simulator state')
    case = state['case']
    passed = returncode == 0 and case['passed'] and case['inside'] == case['required'] and not state['gripper']['held'] and not metrics['physicsFaults']
    if passed:
        for obj in case['objects']:
            cases.contained(obj, scene, case['container'])
        outcome = 'passed'
    elif metrics['physicsFaults'] or returncode not in (0, 1):
        outcome = 'execution-error'
    elif metrics['wrongObjectGrasps']:
        outcome = 'wrong-object-grasp'
    elif state['collision']['armBlocked'] or 'blocked' in case['reason']:
        outcome = 'collision-blocked'
    elif 'wrist camera' in case['reason']:
        outcome = 'lost-wrist-detection'
    elif 'contact both fingers' in case['reason']:
        outcome = 'grasp-failed'
    elif case['phase'] != 'failed':
        outcome = 'step-budget-exhausted'
    elif 'timed out' in case['reason']:
        outcome = 'phase-timeout'
    else:
        outcome = 'controller-failed'
    return dict(outcome=outcome, passed=passed, reason=case['reason'], phase=case['phase'], steps=state['step'],
                inside=case['inside'], required=case['required'], metrics=dict(metrics), phases=dict(phases), events=events)


def evidence(directory, result):
    # Overlays are offline diagnostic artifacts, never inputs to perception.
    for label in ('nonTargetSelection', 'nonTargetDetection', 'multipleTargets', 'driveBlocked', 'lastCamera'):
        event = result['events'].get(label)
        if not event or not event['image']:
            continue
        image = directory/'camera'/event['image']
        shapes = []
        for index, detection in enumerate(event['perception']['detections']):
            x1, y1, x2, y2 = detection['box']
            colour = '#58ff8c' if index == event['perception']['chosen'] else '#ffdb70'
            shapes.append(f'<rect x="{x1}" y="{y1}" width="{x2-x1}" height="{y2-y1}" fill="none" stroke="{colour}" stroke-width="2"/>')
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="640" height="480" viewBox="0 0 640 480">'
               f'<image width="640" height="480" xlink:href="camera/{html.escape(image.name)}"/>'
               +''.join(shapes)+'<rect width="640" height="24" fill="#081a25"/>'
               f'<text x="8" y="17" font-family="monospace" fill="white">OFFLINE REVIEW: {label} / frame {event["perception"]["frameId"]}</text></svg>')
        (directory/(label+'.svg')).write_text(svg)
        event['review'] = label+'.svg'


def run(directory, scene, details, binary, steps, timeout):
    fixture(directory, scene, details)
    replay = ['#!/usr/bin/env bash', 'set -euo pipefail', 'cd '+shlex.quote(str(directory)),
              'exec '+shlex.join([str(binary), '--model', str(binary.parent/'puppybot.bin'), '--case', scene['id'], '--seed', str(details['seed']), '--tcp-view', '--bind', '127.0.0.1:0'])+' "$@"']
    (directory/'replay.sh').write_text('\n'.join(replay)+'\n')
    (directory/'replay.sh').chmod(0o755)
    command = [str(binary), '--model', str(binary.parent/'puppybot.bin'), '--hidden', '--case', scene['id'], '--seed', str(details['seed']), '--steps', str(steps), '--until-done',
               '--bind', '127.0.0.1:0', '--tcp-view', '--record', str(directory/'observations.jsonl'),
               '--search-output', str(directory/'camera'), '--capture', str(directory/'outcome.png')]
    write_json(directory/'command.json', dict(cwd=str(directory), argv=command))
    started = time.monotonic()
    with (directory/'stdout.log').open('w') as stdout, (directory/'stderr.log').open('w') as stderr:
        try:
            initial = subprocess.run([str(binary), '--model', str(binary.parent/'puppybot.bin'), '--hidden', '--case', scene['id'], '--steps', '1', '--bind', '127.0.0.1:0',
                                      '--tcp-view', '--capture', str(directory/'initial.png')], cwd=directory, capture_output=True, text=True, timeout=min(timeout, 30))
            (directory/'initial.log').write_text(initial.stdout+initial.stderr)
            if initial.returncode not in (0, 1) or not (directory/'initial.png').is_file():
                raise ValueError('initial scene capture failed; see initial.log')
            process = subprocess.run(command, cwd=directory, stdout=stdout, stderr=stderr, timeout=timeout)
            state = json.loads((directory/'stdout.log').read_text().strip().splitlines()[-1])
            write_json(directory/'state.json', state)
            result = analyse(directory/'observations.jsonl', scene, state, process.returncode)
            if result['outcome'] == 'step-budget-exhausted' and state['step'] < steps:
                result.update(outcome='execution-error', reason='simulator exited before the step budget; inspect stderr.log')
            result['returnCode'] = process.returncode
            evidence(directory, result)
        except (OSError, subprocess.TimeoutExpired, ValueError, IndexError, AssertionError) as error:
            result = dict(outcome='execution-error', passed=False, reason=repr(error), events={})
    result.update(details, elapsedSeconds=round(time.monotonic()-started, 2), definitionSha256=sha256(directory/'case.json'),
                  directory=directory.name, replay=str(directory/'replay.sh'))
    write_json(directory/'result.json', result)
    return result


def report(output, results, provenance):
    grouped = {}
    for result in results:
        key = result['challenge']+'-'+str(result['level'])
        group = grouped.setdefault(key, dict(passed=0, runs=0, outcomes=Counter()))
        group['runs'] += 1
        group['passed'] += result['passed']
        group['outcomes'][result['outcome']] += 1
    first = {}
    for challenge in CHALLENGES:
        failed = [r['level'] for r in results if r['challenge'] == challenge and not r['passed'] and r['outcome'] != 'execution-error']
        first[challenge] = min(failed) if failed else None
    valid = all(r['passed'] for r in results if r['challenge'] == 'control') and all(r['outcome'] != 'execution-error' for r in results)
    write_json(output/'report.json', dict(schema='puppybot.stress-run.v1', **provenance, validExperiment=valid, firstObservedFailureLevel=first, groups=grouped, runs=results))
    rows = []
    for result in results:
        base = html.escape(result['directory'])
        links = ' '.join(f'<a href="{base}/{file}">{label}</a>' for file, label in (
            ('initial.png', 'scene'), ('outcome.png', 'outcome'), ('result.json', 'details'), ('replay.sh', 'replay')))
        links += ' '+ ' '.join(f'<a href="{base}/{event["review"]}">{html.escape(label)}</a>' for label, event in result['events'].items() if 'review' in event)
        metrics = result.get('metrics', {})
        issues = f'{metrics.get("nonTargetSelections", 0)} non-target selections; {metrics.get("boxesCoveringMultipleTargets", 0)} boxes covering multiple targets'
        if metrics.get('blockedDriveSteps'):
            issues += f'; {metrics["blockedDriveSteps"]} drive steps blocked'
        failure = result['events'].get('failure', {})
        phase = failure.get('phase', result.get('phase', ''))
        if failure.get('obstacle'):
            phase += ' / '+failure['obstacle']
        rows.append(f'<tr><td>{html.escape(result["challenge"])}</td><td>{result["level"]}</td><td>{result["seed"]}</td>'
                    f'<td>{html.escape(result["outcome"])}</td><td>{result.get("inside", "?")}/{result.get("required", "?")}</td>'
                    f'<td>{html.escape(phase)}</td><td>{html.escape(result["reason"])}</td><td>{issues}</td><td>{links}</td></tr>')
    (output/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>PuppyBot stress results</title>'
        '<style>body{font:15px system-ui;background:#101d27;color:#d9e9ed;padding:24px}table{border-collapse:collapse;width:100%}td,th{padding:10px;text-align:left;border-bottom:1px solid #37505c}a{color:#6fe6dc;margin-right:8px}</style>'
        '<h1>PuppyBot stress results</h1><p>'+('Controls and execution checks passed. ' if valid else 'Experiment invalid: inspect the control failures or execution errors. ')+
        'Original front and TCP cameras; unchanged RGB detector and controller. '
        'Scene difficulty increases from 1 to 3. Failures are experimental results. Execution errors are separate. '
        'Non-target selections are judged offline by RGB-centroid ray intersections with scene geometry; '
        'boxes covering multiple target centres suggest possible merging, rather than proving it. '
        'The box retains its rim markers. Replay files run the saved executable against the saved scene.</p>'
        '<table><thead><tr><th>Challenge</th><th>Level</th><th>Seed</th><th>Outcome</th><th>Inside</th><th>Phase / obstacle</th><th>Reason</th><th>Observed issues</th><th>Evidence</th></tr></thead><tbody>'
        +''.join(rows)+'</tbody></table>')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--challenge', choices=CHALLENGES, action='append', help='repeat to select challenges; default: all')
    parser.add_argument('--level', type=int, choices=(1, 2, 3), action='append', help='repeat to select levels; default: 1, 2, 3')
    parser.add_argument('--seed', type=int, action='append', help='repeat to select seeds; default: 42, 43')
    parser.add_argument('--steps', type=int, default=24000)
    parser.add_argument('--timeout', type=int, default=360, help='wall-clock limit per run, seconds')
    parser.add_argument('--output', type=Path, help='new result directory')
    args = parser.parse_args()
    seeds, levels, challenges = args.seed or [42, 43], sorted(set(args.level or [1, 2, 3])), list(dict.fromkeys(args.challenge or CHALLENGES))
    if any(not 0 <= seed <= 4294967295 for seed in seeds) or len(seeds) != len(set(seeds)):
        parser.error('seeds must be unique integers from 0 to 4294967295')
    if not 1 <= args.steps <= 1000000 or not 1 <= args.timeout <= 3600:
        parser.error('steps must be 1..1000000; timeout must be 1..3600 seconds')
    output = (args.output or ROOT/'build/flex/sim/stress'/f'run-{datetime.now():%Y%m%d-%H%M%S}-{os.getpid()}').resolve()
    output.mkdir(parents=True, exist_ok=False)
    binary = output/'puppybot-sim'
    shutil.copy2(BINARY, binary)
    shutil.copy2(ROOT/'build/flex/sim/puppybot.bin', output/'puppybot.bin')
    provenance = dict(binarySha256=sha256(binary), modelSha256=sha256(output/'puppybot.bin'),
                      runnerSha256=sha256(Path(__file__)), steps=args.steps, seeds=seeds, levels=levels, challenges=challenges)
    results = []
    queue = [('control', 0, seed) for seed in seeds]+[(challenge, level, seed) for challenge in challenges for level in levels for seed in seeds]
    for challenge, level, seed in queue:
        directory = output/f'{challenge}-l{level}-s{seed}'
        scene, details = definition(challenge, level, seed)
        result = run(directory, scene, details, binary, args.steps, args.timeout)
        results.append(result)
        report(output, results, provenance)
        print(f'{directory.name}: {result["outcome"]} ({result.get("inside", "?")}/{result.get("required", "?")} inside) - {result["reason"]}', flush=True)
    print(output/'index.html', flush=True)
    # A broken control or execution error invalidates this experiment. Actual
    # stress failures remain results, not a failed software test command.
    return int(any(r['outcome'] == 'execution-error' or (r['challenge'] == 'control' and not r['passed']) for r in results))


if __name__ == '__main__':
    raise SystemExit(main())
