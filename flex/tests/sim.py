#!/usr/bin/env python3
"""Independent URDF pose, physics, determinism and live API checks."""
import argparse
import json
import math
from pathlib import Path
import signal
import subprocess
import tempfile
import time
import urllib.request
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
BINARY = ROOT/'build/flex/puppybot-sim'


def run(*args):
    result = subprocess.run([str(BINARY), *map(str, args)], cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr + result.stdout
    return json.loads(result.stdout.strip().splitlines()[-1])


def product(a, b):
    return [[sum(a[i][k]*b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def identity():
    return [[float(i == j) for j in range(4)] for i in range(4)]


def rpy(xyz, angles):
    r, p, y = angles
    cr, sr, cp, sp, cy, sy = math.cos(r), math.sin(r), math.cos(p), math.sin(p), math.cos(y), math.sin(y)
    return [[cy*cp, cy*sp*sr-sy*cr, cy*sp*cr+sy*sr, xyz[0]],
            [sy*cp, sy*sp*sr+cy*cr, sy*sp*cr-cy*sr, xyz[1]],
            [-sp, cp*sr, cp*cr, xyz[2]], [0, 0, 0, 1]]


def axis_angle(axis, angle):
    length = math.sqrt(sum(v*v for v in axis))
    axis = [v/length for v in axis]
    c, s = math.cos(angle), math.sin(angle)
    skew = [[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]]
    m = identity()
    for i in range(3):
        for j in range(3):
            m[i][j] = c*(i == j) + (1-c)*axis[i]*axis[j] + s*skew[i][j]
    return m


def urdf_tcp(state):
    # Read the original model and model profile. Do not read the packed joint
    # records or import the converter's transform implementation as an oracle.
    model = ROOT/'models/puppybot'
    profile = json.loads((model/'robotdreams.json').read_text())
    robot = ET.parse(model/'final2/urdf/final2.urdf').getroot()
    joints = {j.find('child').get('link'): j for j in robot.findall('joint')}
    mapping = profile['analyticToUrdf']['joints']
    values = {mapping[name]['joint']: angle*mapping[name]['scale']+mapping[name]['offset']
              for name, angle in zip(('yaw', 'shoulder', 'elbow', 'wrist'), state['jointAnglesRad'])}
    chain = []
    link = profile['tcp']['link']
    while link in joints:
        j = joints[link]
        chain.append(j)
        link = j.find('parent').get('link')
    x, y, heading = state['pose']
    matrix = rpy((x, y, 0.032), (0, 0, heading))
    mt = profile['robot']['model']['modelTransformation']
    matrix = product(matrix, rpy(mt['translation'], mt['rotation']))
    for j in reversed(chain):
        o = j.find('origin')
        if o is not None:
            matrix = product(matrix, rpy(list(map(float, o.get('xyz', '0 0 0').split())), list(map(float, o.get('rpy', '0 0 0').split()))))
        if j.get('type') != 'fixed':
            matrix = product(matrix, axis_angle(list(map(float, j.find('axis').get('xyz').split())), values.get(j.get('name'), 0)))
    tcp = [*profile['tcp']['offset'], 1]
    return [sum(matrix[i][j]*tcp[j] for j in range(4)) for i in range(3)]


def request(port, route, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f'http://127.0.0.1:{port}'+route, data=data, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=3) as response:
        return json.load(response)


def await_state(port, predicate, timeout=4):
    deadline = time.monotonic() + timeout
    state = None
    while time.monotonic() < deadline:
        state = request(port, '/api/sim/state')
        if predicate(state):
            return state
        time.sleep(0.025)
    raise AssertionError(f'timed out: {state}')


def live_api(directory):
    log = directory/'live.log'
    with log.open('w') as output:
        child = subprocess.Popen([str(BINARY), '--headless', '--steps', '5000', '--realtime', '--bind', '127.0.0.1:0'], cwd=ROOT, stdout=output, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic()+5
            while 'robot API port ' not in log.read_text():
                assert child.poll() is None, log.read_text()
                assert time.monotonic() < deadline, log.read_text()
                time.sleep(0.02)
            port = int(log.read_text().split('robot API port ')[1].splitlines()[0])
            request(port, '/api/sim/pause', {})
            paused = request(port, '/api/sim/state')
            time.sleep(0.15)
            assert request(port, '/api/sim/state')['timeMs'] == paused['timeMs']
            assert paused['paused'] and paused['physicsFault'] == 0
            assert request(port, '/api/state')['arm']['joints'][0]['online']
            request(port, '/api/sim/resume', {})
            request(port, '/api/drive', {'throttle': 100, 'steering': 0})
            driven = await_state(port, lambda s: s['pose'][0] > 0.035)
            assert driven['pose'][0] > paused['pose'][0]
            request(port, '/api/drive/stop', {})
            stopped = request(port, '/api/sim/state')
            time.sleep(0.15)
            assert request(port, '/api/sim/state')['pose'] == stopped['pose']
            request(port, '/api/arm/joints/0/spin', {'direction': 1})
            moved = await_state(port, lambda s: s['ticks'][0] != stopped['ticks'][0])
            request(port, '/api/arm/stop', {})
            assert abs(moved['jointAnglesRad'][0]) > 0
            # Wheel/body sweep must stop before crossing a dynamic ball.
            request(port, '/api/sim/reset', {})
            request(port, '/api/drive', {'throttle': 100, 'steering': 0})
            barrier = await_state(port, lambda s: s['blocked'])
            assert barrier['vehicle']['blockedBody'] == 3
            assert barrier['pose'][0] < 0.25 and barrier['ball'][0] < 0.39
            assert barrier['vehicle']['queryFault'] == 0
            request(port, '/api/drive/stop', {})
            reset = request(port, '/api/sim/reset', {})
            assert reset['episode'] == 2 and reset['pose'] == [0, 0, 0]
            assert reset['ticks'] == paused['ticks']
            # Turn toward obstacle 1, straighten, then meet its footprint.
            request(port, '/api/drive', {'throttle': 100, 'steering': 100})
            await_state(port, lambda s: s['pose'][2] < -0.45)
            request(port, '/api/drive', {'throttle': 100, 'steering': 0})
            blocked = await_state(port, lambda s: s['blocked'])
            assert blocked['pose'][0] < 0.55
            request(port, '/api/drive/stop', {})
            assert request(port, '/api/sim/state')['physicsFault'] == 0
            request(port, '/api/sim/reset', {})
            request(port, '/api/sim/gripper/close', {})
            empty = await_state(port, lambda s: s['gripper']['openingMm'] == 0)
            assert not empty['gripper']['held'] and empty['gripper']['grasps'] == 0
            assert empty['gripper']['captureContactMask'] == 0
            request(port, '/api/sim/gripper/open', {})
            assert await_state(port, lambda s: s['gripper']['openingMm'] == 90)['gripper']['ballDynamic']
            request(port, '/api/sim/pickup', {})
            await_state(port, lambda s: s['pickup']['phase'] == 'hovering')
            paused_pickup = request(port, '/api/sim/pause', {})
            targets = [j['targetTick'] for j in paused_pickup['controller']['arm']['joints']]
            assert any(t is not None for t in targets)
            time.sleep(0.1)
            frozen = request(port, '/api/sim/state')
            assert frozen['timeMs'] == paused_pickup['timeMs']
            assert [j['targetTick'] for j in frozen['controller']['arm']['joints']] == targets
            request(port, '/api/sim/resume', {})
            await_state(port, lambda s: s['ticks'] != frozen['ticks'])
        finally:
            child.send_signal(signal.SIGTERM)
            child.wait(timeout=5)
        assert child.returncode == 0, log.read_text()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--render', action='store_true', help='also exercise the native GPU renderer')
    args = parser.parse_args()
    receipt = json.loads((ROOT/'build/flex/sim/puppybot.json').read_text())
    assert receipt['visuals'] == receipt['links'] == 221
    assert receipt['groups'] == 18 and receipt['vertices'] > 2000000
    with tempfile.TemporaryDirectory(prefix='puppybot-sim-', dir=ROOT/'build/flex/sim') as temp:
        directory = Path(temp)
        first, second = directory/'first.jsonl', directory/'second.jsonl'
        a = run('--headless', '--steps', 250, '--demo', '--bind', '127.0.0.1:0', '--record', first)
        b = run('--headless', '--steps', 250, '--demo', '--bind', '127.0.0.1:0', '--record', second)
        assert a == b and first.read_bytes() == second.read_bytes(), 'non-deterministic rollout'
        states = [json.loads(line) for line in first.read_text().splitlines()]
        assert len(states) == 250 and [s['step'] for s in states] == list(range(1, 251))
        assert all(s['physicsFault'] == 0 for s in states)
        for s in states[::7]:
            expected = urdf_tcp(s)
            assert max(abs(a-b) for a, b in zip(expected, s['tcp'])) < 1e-10, (expected, s['tcp'])
        assert states[0]['ticks'] != states[-1]['ticks']
        assert a['pose'][0] > 0.15 and a['pose'][2] > 0.1
        idle = run('--headless', '--steps', 200, '--bind', '127.0.0.1:0')
        assert idle['pose'] == [0, 0, 0]
        assert abs(idle['ball'][2]-0.035) < 0.001 and idle['contacts'] > 0
        assert abs(idle['ball'][0]-0.38) < 1e-6
        pickup = directory/'pickup.jsonl'
        held = run('--headless', '--steps', 1150, '--pickup', '--bind', '127.0.0.1:0', '--record', pickup)
        assert held['pickup']['passed'] and held['pickup']['phase'] == 'holding'
        assert held['gripper']['held'] and held['gripper']['constraintActive']
        assert held['gripper']['captureContactMask'] == 3 and held['gripper']['grasps'] == 1
        assert held['ball'][2] > 0.12
        assert held['gripper']['maxHeldBallHeight'] - held['gripper']['captureBallHeight'] > 0.09
        observations = [json.loads(line) for line in pickup.read_text().splitlines()]
        phases = list(dict.fromkeys(s['pickup']['phase'] for s in observations))
        assert phases == ['settling', 'approaching', 'hovering', 'lowering', 'closing', 'lifting', 'holding'], phases
        assert all(s['gripper']['ballDynamic'] and s['physicsFault'] == 0 for s in observations)
        captured = next(s for s in observations if s['gripper']['held'])
        assert captured['gripper']['contactMask'] == 3
        # Capture must not snap the ball off the floor or across the scene.
        assert abs(captured['ball'][2]-0.035) < 0.002
        assert math.dist(captured['ball'][:2], [0.38, 0.08]) < 0.025
        before_capture = observations[observations.index(captured)-1]
        assert math.dist(captured['ball'], before_capture['ball']) < 0.003, 'capture snapped the physically contacted ball'
        fixed_hold = [s['ball'][2] for s in observations[-100:]]
        assert max(fixed_hold)-min(fixed_hold) < 0.001
        for s in observations[::19]:
            assert math.dist(urdf_tcp(s), s['tcp']) < 1e-10
        released_file = directory/'released.jsonl'
        released = run('--headless', '--steps', 1300, '--pickup-release', '--bind', '127.0.0.1:0', '--record', released_file)
        assert released['pickup']['passed'] and released['pickup']['phase'] == 'released'
        assert not released['gripper']['held'] and not released['gripper']['constraintActive']
        assert released['gripper']['releases'] == 1 and abs(released['ball'][2]-0.035) < 0.001
        released_states = [json.loads(line) for line in released_file.read_text().splitlines()]
        drop = next(i for i, s in enumerate(released_states) if s['pickup']['phase'] == 'releasing')
        assert 0.001 < released_states[drop]['ball'][2]-released_states[drop+1]['ball'][2] < 0.004
        repeated = run('--headless', '--steps', 1150, '--pickup', '--bind', '127.0.0.1:0')
        assert repeated == held, 'pickup is not repeatable'
        live_api(directory)
        # Preserve existing recordings; malformed assets and unbounded startup
        # combinations fail before entering the event loop.
        original = first.read_bytes()
        rejected = subprocess.run([str(BINARY), '--headless', '--steps', '1', '--record', str(first), '--bind', '127.0.0.1:0'], cwd=ROOT, capture_output=True)
        assert rejected.returncode == 2 and first.read_bytes() == original
        invalid = directory/'bad-model.bin'
        invalid.write_bytes(b'bad model')
        assert subprocess.run([str(BINARY), '--headless', '--steps', '1', '--model', str(invalid)], cwd=ROOT, capture_output=True).returncode == 2
        if args.render:
            screenshots = []
            for count in (1, 120):
                path = directory/f'frame-{count}.ppm'
                state = run('--hidden', '--steps', count, '--demo', '--bind', '127.0.0.1:0', '--capture', path)
                raw = path.read_bytes()
                assert raw.startswith(b'P6\n1280 800\n255\n')
                pixels = raw.split(b'\n', 3)[3]
                assert len(pixels) == 1280*800*3 and len(set(pixels)) > 100
                assert state['physicsFault'] == 0
                screenshots.append(pixels)
            assert sum(a != b for a, b in zip(*screenshots)) > 100000
            grasp_image = directory/'grasp.ppm'
            grasp_state = run('--hidden', '--steps', 1150, '--pickup', '--bind', '127.0.0.1:0', '--capture', grasp_image)
            assert grasp_state['gripper']['held'] and grasp_state['pickup']['passed']
            assert grasp_image.stat().st_size > 3000000
    print('Simulation checks passed: independent URDF TCP, repeated rollouts and pickup, bilateral capture, stable lift/hold, gravity release, empty-grasp rejection, live robot API, artifact preservation'+(', GPU captures' if args.render else ''))


if __name__ == '__main__':
    main()
