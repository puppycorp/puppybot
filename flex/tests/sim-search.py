#!/usr/bin/env python3
"""Verify RGB search, calibrated targets, physical grasps and blind-grasp guards."""
import argparse
import importlib.util
import json
import math
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
SIM = ROOT/'build/flex/puppybot-sim'
spec = importlib.util.spec_from_file_location('case_checks', Path(__file__).with_name('sim-cases.py'))
cases = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cases)


def run(directory, steps, *options, cwd=ROOT, expected=0):
    journal = directory/'observations.jsonl'
    process = subprocess.run([str(SIM), '--hidden', '--bind', '127.0.0.1:0', '--steps', str(steps),
                              '--case', 'search-blocks-into-box', '--record', str(journal), *map(str, options)],
                             cwd=cwd, capture_output=True, text=True, timeout=360)
    (directory/'stdout.log').write_text(process.stdout)
    (directory/'stderr.log').write_text(process.stderr)
    assert process.returncode == expected, process.stdout+process.stderr
    return json.loads(process.stdout.strip().splitlines()[-1]), journal


def project(calibration, pixel):
    eye, forward, right, down = [calibration[i:i+3] for i in range(0, 12, 3)]
    focal = 1.732051*480/2
    u, v = pixel
    ray = [forward[i]+(u-320)/focal*right[i]+(v-240)/focal*down[i] for i in range(3)]
    distance = (0.024-eye[2])/ray[2]
    return [eye[0]+distance*ray[0], eye[1]+distance*ray[1], 0.012]


def inspect(journal, images=None):
    previous = None
    captures = []
    samples = set()
    phases = set()
    selected_frames = []
    for line in journal.open():
        state = json.loads(line)
        case = state['case']
        perception = case['perception']
        phases.add(case['phase'])
        assert state['physicsFault'] == 0 and state['vehicle']['queryFault'] == 0
        assert perception['targetSource'] == 'camera-rgb' and perception['detector'] == 'rgb-components-v1'
        assert all('body' not in d and 'id' not in d for d in perception['detections'])
        if not state['gripper']['grasps']:
            assert case['selected'] == -1, 'planner learned an object ID before contact'
        frame = perception['frameId']
        if perception['samples'] and frame not in samples:
            samples.add(frame)
            for detection in perception['detections']:
                assert math.dist(project(perception['calibration'], detection['pixel']), detection['targetM']) < 1e-9
                assert 0 < detection['fill'] <= 1
            if images:
                image = images/(perception.get('image') or f'frame-{frame}.png')
                assert image.read_bytes().startswith(b'\x89PNG\r\n\x1a\n')
                camera = json.loads(image.with_suffix('.png.camera.json').read_text())
                assert camera['frameId'] == frame and camera['view'] == perception['view']
                assert camera['eyeM'] == perception['calibration'][:3]
            if perception['chosen'] >= 0:
                chosen = perception['detections'][perception['chosen']]
                assert math.dist(case['pickupTargetM'], chosen['targetM']) < 1e-9
                selected_frames.append((state['step'], perception['view']))
        if previous and not previous['gripper']['held'] and state['gripper']['held']:
            assert state['gripper']['captureContactMask'] == 3
            body = state['gripper']['body']
            before = next(o for o in previous['case']['objects'] if o['body'] == body)
            after = next(o for o in case['objects'] if o['body'] == body)
            assert math.dist(before['position'], after['position']) < 0.003, 'capture snapped the brick'
            captures.append(body)
        previous = state
    return previous, phases, captures, selected_frames


def fixture(directory, colour):
    target = directory/'flex/sim/cases'
    target.mkdir(parents=True)
    definition = json.loads((ROOT/'flex/sim/cases/search-blocks-into-box.json').read_text())
    definition.pop('randomFloor')
    definition['objects'] = [dict(definition['objects'][0], position=[0.72, 0.08, 0.013], color=colour)]
    (target/'search.json').write_text(json.dumps(definition))
    catalog = dict(schema='puppybot.cases.v1', cases=[dict(id='search-blocks-into-box', name='Search fixture', controller='rgb-search', file='flex/sim/cases/search.json')])
    (target/'catalog.json').write_text(json.dumps(catalog))
    (directory/'build').symlink_to(ROOT/'build', target_is_directory=True)
    return definition


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed', type=int, default=42)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='sim-search-', dir=ROOT/'build/flex/sim') as temp:
        directory = Path(temp)
        positive = directory/'positive'
        positive.mkdir()
        images = positive/'camera'
        state, journal = run(positive, 24000, '--seed', args.seed, '--search-output', images, '--capture', positive/'outcome.png', '--tcp-view')
        final, phases, captures, selected = inspect(journal, images)
        assert final == state
        case = state['case']
        assert case['passed'] and case['placed'] == case['inside'] == case['required'] == 6
        assert len(captures) == len(set(captures)) == 6
        assert case['visualRefinements'] >= 6 and {'searching', 'visually aligning', 'grasping'} <= phases
        assert {view for _, view in selected} == {'rover', 'tcp'}
        definition = json.loads((ROOT/'flex/sim/cases/search-blocks-into-box.json').read_text())
        for obj in case['objects']:
            cases.contained(obj, definition, case['container'])
        metadata = json.loads((positive/'outcome.png.sensor.camera.json').read_text())
        assert metadata['frameId'] == case['perception']['frameId']
        assert metadata['eyeM'] == case['perception']['calibration'][:3]
        print('Six camera-located bricks: calibrated pixels, visual refinement, contact-only IDs, no snapping and independent containment passed', flush=True)

        # A far object needs exploration before the arm can approach it.
        far = directory/'far'
        fixture(far, [95, 22, 22])
        state, journal = run(far, 4200, cwd=far)
        _, phases, captures, _ = inspect(journal)
        assert state['case']['passed'] and len(captures) == 1
        assert state['case']['searchDistanceM'] > 0.1
        print('Far brick: drove along the search lane before selecting a reachable visual target', flush=True)

        # Simulator truth still knows this neutral-coloured brick's position.
        # The RGB detector cannot recognize it, so the arm must never grasp.
        blank = directory/'blank'
        fixture(blank, [40, 40, 40])
        state, journal = run(blank, 800, cwd=blank, expected=1)
        _, phases, captures, _ = inspect(journal)
        assert phases <= {'settling', 'searching'} and not captures
        assert state['case']['searchDistanceM'] > 0.1 and state['case']['visualRefinements'] == 0
        assert state['case']['perception']['detections'] == [] and not state['gripper']['grasps']
        print('Invisible-to-detector brick: search continues without any scene-position fallback or blind grasp', flush=True)
    print('Camera search checks passed')


if __name__ == '__main__':
    main()
