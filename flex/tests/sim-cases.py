#!/usr/bin/env python3
"""Check catalog execution, physical containment, repeatability and case API."""
import argparse
import importlib.util
import json
import math
from pathlib import Path
import signal
import subprocess
import tempfile
import time
import urllib.error

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('simulation_checks', Path(__file__).with_name('sim.py'))
simulation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(simulation)
BINARY = ROOT/'build/flex/puppybot-sim'


def simulate(*args):
    p = subprocess.run([str(BINARY), *map(str, args)], cwd=ROOT, capture_output=True, text=True, timeout=360)
    assert p.returncode == 0, f'exit {p.returncode}: '+p.stdout+p.stderr
    return json.loads(p.stdout.strip().splitlines()[-1])


def rotation(quaternion):
    x, y, z, w = quaternion
    return [[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
            [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
            [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]]


def contained(obj, definition, observed_container):
    # Judge complete bounds in the moving container frame, independently of
    # the simulator's inside flag or its cached physics rotations.
    obj_rotation = rotation(obj['quaternion'])
    box_rotation = rotation(observed_container['quaternion'])
    relative = [[sum(box_rotation[k][i]*obj_rotation[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
    position = [sum(box_rotation[k][i]*(obj['position'][k]-observed_container['position'][k]) for k in range(3)) for i in range(3)]
    source = next(o for o in definition['objects'] if o['id'] == obj['id'])
    half = source['halfSize']
    extent = [half[0]]*3 if source['kind'] == 'ball' else [sum(abs(relative[i][j])*half[j] for j in range(3)) for i in range(3)]
    container = definition['container']
    for axis in range(2):
        assert abs(position[axis])+extent[axis] <= container['innerSize'][axis]/2+0.002
    floor = container['wallThickness']
    assert position[2]-extent[2] >= floor-0.003
    assert position[2]+extent[2] <= floor+container['innerSize'][2]
    # A passing case also requires the box to have stopped sliding/tipping.
    assert observed_container['settled']
    assert math.sqrt(sum(v*v for v in observed_container['velocity'])) <= definition['success']['maxLinearSpeed']+1e-6
    width, depth, height = container['innerSize']
    thickness = container['wallThickness']
    floor_volume = (width+2*thickness)*(depth+2*thickness)*thickness
    wall_volume = 2*thickness*(depth+2*thickness)*height+2*width*thickness*height
    centre_z = (floor_volume*thickness/2+wall_volume*(thickness+height/2))/(floor_volume+wall_volume)
    centre = [observed_container['position'][i]+box_rotation[i][2]*centre_z for i in range(3)]
    r = [obj['position'][i]-centre[i] for i in range(3)]
    omega = observed_container['angularVelocity']
    relative_velocity = [obj['velocity'][i]-observed_container['velocity'][i]-(omega[(i+1)%3]*r[(i+2)%3]-omega[(i+2)%3]*r[(i+1)%3]) for i in range(3)]
    assert math.sqrt(sum(v*v for v in relative_velocity)) <= definition['success']['maxLinearSpeed']+1e-6


def api(directory, catalog):
    log = directory/'api.log'
    with log.open('w') as output:
        p = subprocess.Popen([str(BINARY), '--headless', '--steps', '10000', '--realtime', '--bind', '127.0.0.1:0'], cwd=ROOT, stdout=output, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic()+5
            while 'robot API port ' not in log.read_text():
                assert p.poll() is None and time.monotonic() < deadline, log.read_text()
                time.sleep(0.02)
            port = int(log.read_text().split('robot API port ')[1].splitlines()[0])
            assert simulation.request(port, '/api/sim/cases') == catalog
            for entry in catalog['cases']:
                if entry['controller'] in ('rgb-search', 'rgb-house', 'rgb-discovery', 'rgb-find-return'):
                    before = simulation.request(port, '/api/sim/state')
                    try:
                        simulation.request(port, '/api/sim/cases/'+entry['id'], {})
                        raise AssertionError('headless camera case accepted')
                    except urllib.error.HTTPError as error:
                        assert error.code == 400
                    after = simulation.request(port, '/api/sim/state')
                    assert before['episode'] == after['episode'] and before['case']['id'] == after['case']['id']
                    continue
                state = simulation.request(port, '/api/sim/cases/'+entry['id'], {})
                assert state['case']['id'] == entry['id'] and state['case']['phase'] == 'settling'
                paused = simulation.request(port, '/api/sim/pause', {})
                time.sleep(0.1)
                frozen = simulation.request(port, '/api/sim/state')
                assert frozen['timeMs'] == paused['timeMs'] and frozen['case']['phase'] == paused['case']['phase']
                simulation.request(port, '/api/sim/resume', {})
                reset = simulation.request(port, '/api/sim/reset', {})
                assert reset['case']['phase'] == 'idle' and reset['case']['placed'] == 0
                assert not reset['case']['passed'] and not reset['gripper']['held']
            before = simulation.request(port, '/api/sim/state')
            try:
                simulation.request(port, '/api/sim/cases/missing', {})
                raise AssertionError('unknown case accepted')
            except urllib.error.HTTPError as error:
                assert error.code == 404
            after = simulation.request(port, '/api/sim/state')
            assert before['episode'] == after['episode'] and before['case']['id'] == after['case']['id']
            legacy = simulation.request(port, '/api/sim/pickup', {})
            assert legacy['case'] is None and legacy['pickup']['phase'] == 'settling'
        finally:
            p.send_signal(signal.SIGTERM)
            p.wait(timeout=5)
        assert p.returncode == 0, log.read_text()


def invalid(directory):
    cases = directory/'flex/sim/cases'
    cases.mkdir(parents=True)
    catalog = {'schema':'puppybot.cases.v1','cases':[{'id':'bad','name':'Bad case','file':'bad.json'}]}
    (cases/'catalog.json').write_text(json.dumps(catalog))
    example = json.loads((ROOT/'flex/sim/cases/ball-into-bin.json').read_text())
    example['id'] = 'bad'
    for mutate in (lambda d: d['objects'][0].update(halfSize=[0, 0, 0]),
                   lambda d: d['objects'][0].update(mass=-1),
                   lambda d: d['container'].update(innerSize=[-1, 1, 1]),
                   lambda d: d['container'].update(mass=0),
                   lambda d: d['container'].update(fixed=1)):
        broken = json.loads(json.dumps(example))
        mutate(broken)
        (directory/'bad.json').write_text(json.dumps(broken))
        result = subprocess.run([str(BINARY), '--headless', '--steps', '1', '--case', 'bad'], cwd=directory, capture_output=True)
        assert result.returncode == 2 and b'robot API port' not in result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--render', action='store_true')
    args = parser.parse_args()
    result = subprocess.run([str(BINARY), '--list-cases'], cwd=ROOT, capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr
    catalog = json.loads(result.stdout)
    with tempfile.TemporaryDirectory(prefix='sim-cases-', dir=ROOT/'build/flex/sim') as temp:
        directory = Path(temp)
        for entry in catalog['cases']:
            if entry.get('stress') or entry.get('longRunning'):
                continue  # Dedicated stress/house checks retain their own outcomes.
            case = entry['id']
            definition = json.loads((ROOT/entry['file']).read_text())
            journal = directory/(case+'.jsonl')
            steps = max(6500, 2200*len(definition['objects'])+1000)
            mode = '--headless'
            if entry['controller'] == 'rgb-search':
                mode = '--hidden'
                steps = max(steps, 24000)
            state = simulate(mode, '--steps', steps, '--case', case, '--bind', '127.0.0.1:0', '--record', journal)
            assert state['case']['passed'] and state['case']['controller'] == entry['controller']
            assert state['case']['placed'] == state['case']['inside'] == len(definition['objects'])
            assert not state['gripper']['held'] and not state['gripper']['constraintActive'] and state['physicsFault'] == 0
            assert state['gripper']['grasps'] == state['gripper']['releases'] == len(definition['objects'])
            for obj in state['case']['objects']:
                contained(obj, definition, state['case']['container'])
            observations = [json.loads(line) for line in journal.read_text().splitlines()]
            captures = [b for a, b in zip(observations, observations[1:]) if not a['gripper']['held'] and b['gripper']['held']]
            assert len(captures) == len(definition['objects'])
            assert len({s['gripper']['body'] for s in captures}) == len(captures)
            assert all(s['gripper']['captureContactMask'] == 3 for s in captures)
            assert all(not s['collision']['armBlocked'] and not s['blocked'] for s in observations), 'case crossed a robot collision guard'
            assert state['collision']['armProxies'] == len(json.loads((ROOT/'build/flex/sim/puppybot.json').read_text())['armColliders'])
            first_pass = next(i for i, s in enumerate(observations) if s['case']['passed'])
            assert all(all(o['inside'] for o in s['case']['objects']) and not s['gripper']['held'] for s in observations[first_pass-99:first_pass+1])
            repeated = simulate(mode, '--steps', steps, '--case', case, '--bind', '127.0.0.1:0')
            assert state == repeated, 'case outcome is not deterministic'
            if args.render:
                image = directory/(case+'.ppm')
                rendered = simulate('--hidden', '--steps', steps, '--case', case, '--bind', '127.0.0.1:0', '--capture', image)
                assert rendered == state
                rgb = image.read_bytes().split(b'\n', 3)[3]
                assert len(rgb) == 1280*800*3 and len(set(rgb)) > 100
            print(case+': physical outcome and repeatability checked', flush=True)
        api(directory, catalog)
        invalid(directory/'invalid')
    print('Case checks passed: native catalog, bilateral multi-object grasps, independent physical containment, release/stability, repeatability, case switching/reset/pause, invalid definitions'+(', GPU catalog and outcomes' if args.render else ''))


if __name__ == '__main__':
    main()
