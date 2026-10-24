#!/usr/bin/env python3
"""Check seeded random floor geometry, replay, API reset/shuffle and rejection."""
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
CASE = 'random-blocks-into-box'
DEFINITION = json.loads((ROOT/'flex/sim/cases'/f'{CASE}.json').read_text())


def initial(state):
    return [(o['id'], o['initialPosition'], o['initialYawRad']) for o in state['case']['objects']]


def layout(seed):
    result = subprocess.run([str(simulation.BINARY), '--headless', '--steps', '1', '--case', CASE, '--seed', str(seed), '--bind', '127.0.0.1:0'], cwd=ROOT, capture_output=True, text=True, timeout=10)
    # A one-tick case capture is deliberately incomplete, not a failed spawn.
    assert result.returncode == 1 and 'Case incomplete:' in result.stderr, result.stdout+result.stderr
    state = json.loads(result.stdout.splitlines()[-1])
    assert state['case']['seed'] == seed and state['physicsFault'] == 0
    assert state['case']['phase'] == 'settling'
    return state


def clearance(point, box, radius):
    dx = max(abs(point[0]-box[0])-box[2], 0)
    dy = max(abs(point[1]-box[1])-box[3], 0)
    assert math.hypot(dx, dy) > radius


def geometry(state):
    config = DEFINITION['randomFloor']
    objects = state['case']['objects']
    container = DEFINITION['container']
    obstacles = [(0, 0, 0.14, 0.12), (0.65, -0.35, 0.12, 0.12), (-0.55, 0.45, 0.10, 0.18),
                 (*container['position'][:2], container['innerSize'][0]/2+container['wallThickness'], container['innerSize'][1]/2+container['wallThickness'])]
    radii = []
    for obj in objects:
        definition = next(o for o in DEFINITION['objects'] if o['id'] == obj['id'])
        hx, hy, hz = definition['halfSize']
        radius = math.hypot(hx, hy)
        radii.append(radius)
        x, y, z = obj['initialPosition']
        yaw = obj['initialYawRad']
        assert abs(yaw) <= math.radians(config['yawDegrees']) and abs(z-hz-0.001) < 1e-12
        # Independent rotated-corner check against the original definition.
        for sx, sy in ((-1,-1), (-1,1), (1,-1), (1,1)):
            corner = (x+sx*hx*math.cos(yaw)-sy*hy*math.sin(yaw), y+sx*hx*math.sin(yaw)+sy*hy*math.cos(yaw))
            assert all(lo <= value <= hi for value, lo, hi in zip(corner, config['min'], config['max']))
        for obstacle in obstacles:
            clearance((x,y), obstacle, radius+config['clearance'])
    for i, a in enumerate(objects):
        for j, b in enumerate(objects[:i]):
            assert math.dist(a['initialPosition'][:2], b['initialPosition'][:2]) >= radii[i]+radii[j]+config['clearance']


def api(directory):
    log = directory/'api.log'
    with log.open('w') as output:
        child = subprocess.Popen([str(simulation.BINARY), '--headless', '--steps', '10000', '--realtime', '--bind', '127.0.0.1:0'], cwd=ROOT, stdout=output, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic()+5
            while 'robot API port ' not in log.read_text():
                assert child.poll() is None and time.monotonic() < deadline, log.read_text()
                time.sleep(0.02)
            port = int(log.read_text().split('robot API port ')[1].splitlines()[0])
            simulation.request(port, '/api/sim/pause', {})
            seeded = simulation.request(port, '/api/sim/cases/'+CASE, {'seed':1234})
            assert seeded['case']['seed'] == 1234 and initial(seeded) == initial(layout(1234))
            replay = simulation.request(port, '/api/sim/reset', {})
            assert replay['case']['phase'] == 'idle' and initial(replay) == initial(seeded)
            shuffled = simulation.request(port, '/api/sim/shuffle', {})
            assert shuffled['case']['seed'] == 1235 and shuffled['case']['phase'] == 'settling'
            assert initial(shuffled) == initial(layout(1235)) and initial(shuffled) != initial(seeded)
            for seed in (-1, 4294967296, 1.5, '42', True):
                try:
                    simulation.request(port, '/api/sim/cases/'+CASE, {'seed':seed})
                    raise AssertionError('invalid seed accepted')
                except urllib.error.HTTPError as error:
                    assert error.code == 400
                after = simulation.request(port, '/api/sim/state')
                assert after['episode'] == shuffled['episode'] and initial(after) == initial(shuffled) and after['case']['seed'] == 1235
            fixed = simulation.request(port, '/api/sim/cases/blocks-into-box', {})
            assert fixed['case']['seed'] is None
            try:
                simulation.request(port, '/api/sim/shuffle', {})
                raise AssertionError('fixed case shuffled')
            except urllib.error.HTTPError as error:
                assert error.code == 400
            assert simulation.request(port, '/api/sim/state')['episode'] == fixed['episode']
        finally:
            child.send_signal(signal.SIGTERM)
            child.wait(timeout=5)
        assert child.returncode == 0, log.read_text()


def invalid(directory):
    for seed in ('-1','4294967296','1.5','bad'):
        result = subprocess.run([str(simulation.BINARY), '--headless', '--steps', '1', '--case', CASE, '--seed', seed], cwd=ROOT, capture_output=True)
        assert result.returncode == 2 and b'robot API port' not in result.stdout
    cases = directory/'flex/sim/cases'
    cases.mkdir(parents=True)
    (cases/'catalog.json').write_text(json.dumps({'schema':'puppybot.cases.v1','cases':[{'id':CASE,'name':'Invalid','file':'bad.json'}]}))
    for random_floor in ({'min':[0.4,0.1],'max':[0.3,0.2],'clearance':0.025,'yawDegrees':75},
                         {'min':[0.4,0.1],'max':[0.401,0.101],'clearance':0.025,'yawDegrees':75},
                         {'min':[0.3,0.0],'max':[0.5,0.2],'clearance':-1,'yawDegrees':75}):
        definition = dict(DEFINITION, randomFloor=random_floor)
        (directory/'bad.json').write_text(json.dumps(definition))
        result = subprocess.run([str(simulation.BINARY), '--headless', '--steps', '1', '--case', CASE], cwd=directory, capture_output=True, timeout=5)
        assert result.returncode == 2 and b'robot API port' not in result.stdout


def main():
    layouts = []
    seeds = [*range(32), 42, 99, 1234, 65535, 4294967295]
    for seed in seeds:
        state = layout(seed)
        geometry(state)
        layouts.append(initial(state))
    assert len({json.dumps(s) for s in layouts}) == len(seeds)
    assert initial(layout(42)) == initial(layout(42))
    with tempfile.TemporaryDirectory(prefix='sim-random-', dir=ROOT/'build/flex/sim') as temp:
        directory = Path(temp)
        api(directory)
        invalid(directory/'invalid')
    print(f'Random floor checks passed: {len(seeds)} distinct seeds, independent bounds/clearances/rotations, repeatability, API replay/reset/shuffle, invalid seeds and impossible layouts rejected')


if __name__ == '__main__':
    main()
