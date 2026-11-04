#!/usr/bin/env python3
"""Move/occlude the physical box during a task; require fresh visual returns."""
import argparse
import importlib.util
import json
import math
from pathlib import Path
import signal
import struct
import subprocess
import tempfile
import time
import urllib.error

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('search_checks', Path(__file__).with_name('sim-search.py'))
search = importlib.util.module_from_spec(spec)
spec.loader.exec_module(search)
request = search.cases.simulation.request
with (ROOT/'build/flex/sim/puppybot.bin').open('rb') as model:
    header = model.read(64)
    model.seek(64+struct.unpack_from('<Q', header, 8)[0]*256+64)
    ARM_BASE_YAW = struct.unpack('<d', model.read(8))[0]


def tcp_eye(state):
    yaw = state['pose'][2]+ARM_BASE_YAW+state['jointAnglesRad'][0]+struct.unpack('>d', bytes.fromhex('3ff70be937858458'))[0]
    pitch = state['jointAnglesRad'][1]-state['jointAnglesRad'][2]+state['jointAnglesRad'][3]-struct.unpack('>d', bytes.fromhex('40095e2a7b8b5d8d'))[0]
    cy, sy, cp, sp = math.cos(yaw), math.sin(yaw), math.cos(pitch), math.sin(pitch)
    local_y = [cy*cp, sy*cp, sp]
    local_z = [cy*sp, sy*sp, -cp]
    return [state['tcp'][i]+0.065*(local_y[i]-local_z[i]) for i in range(3)]


def project(calibration, pixel, height):
    eye, forward, right, down = [calibration[i:i+3] for i in range(0, 12, 3)]
    u, v = pixel
    focal = 1.732051*480/2
    ray = [forward[i]+(u-320)/focal*right[i]+(v-240)/focal*down[i] for i in range(3)]
    distance = (height-eye[2])/ray[2]
    return [eye[i]+distance*ray[i] for i in range(3)]


def inspect(journal, definition):
    previous = None
    frames = set()
    releases = 0
    for line in journal.open():
        state = json.loads(line)
        if state['case'] is None:
            continue
        case = state['case']
        dock = case['dockVision']
        assert state['physicsFault'] == 0 and state['vehicle']['queryFault'] == 0
        if dock['valid'] and dock['frameId'] not in frames:
            frames.add(dock['frameId'])
            assert dock['camera'] == 'tcp' and case['perception']['view'] == 'tcp'
            assert max(abs(a-b) for a, b in zip(tcp_eye(state), dock['calibration'][:3])) < 0.00051, 'box used a different camera mount'
            height = definition['container']['wallThickness']+definition['container']['innerSize'][2]+0.001
            for marker in dock['markers']:
                assert math.dist(project(dock['calibration'], marker['pixel'], height), marker['positionM']) < 1e-9
            truth = case['container']
            assert math.dist(dock['positionM'][:2], truth['position'][:2]) < 0.008
            rotation = search.cases.rotation(truth['quaternion'])
            actual = math.atan2(rotation[1][0], rotation[0][0])
            error = (dock['yawRad']-actual+math.pi/2) % math.pi-math.pi/2
            assert abs(error) < math.radians(4)
        if previous and previous['gripper']['held'] and not state['gripper']['held']:
            assert dock['valid'] and dock['releaseFrameId'] == state['totalSteps'] == dock['frameId']
            assert dock['stableObservations'] >= 3
            releases += 1
        previous = state
    assert frames and releases == len(definition['objects'])
    for obj in previous['case']['objects']:
        search.cases.contained(obj, definition, previous['case']['container'])
    return previous


class Scene:
    def __init__(self, directory):
        self.directory = directory
        self.definition = search.fixture(directory, [95, 22, 22])
        self.log = directory/'simulation.log'
        self.output = self.log.open('w')
        self.journal = directory/'observations.jsonl'
        self.child = subprocess.Popen([str(search.SIM), '--hidden', '--steps', '100000', '--bind', '127.0.0.1:0', '--record', str(self.journal), '--search-output', str(directory/'camera')],
                                      cwd=directory, stdout=self.output, stderr=subprocess.STDOUT)
        deadline = time.monotonic()+10
        while 'robot API port ' not in self.log.read_text():
            assert self.child.poll() is None and time.monotonic() < deadline, self.log.read_text()
            time.sleep(0.02)
        self.port = int(self.log.read_text().split('robot API port ')[1].splitlines()[0])
        self.request('/api/sim/pause', {})
        self.request('/api/sim/cases/search-blocks-into-box', {})
        self.request('/api/sim/resume', {})

    def request(self, path, body=None):
        return request(self.port, path, body)

    def wait(self, predicate, timeout=80):
        deadline = time.monotonic()+timeout
        while time.monotonic() < deadline:
            assert self.child.poll() is None, self.log.read_text()
            state = self.request('/api/sim/state')
            assert state['case']['phase'] != 'failed', state['case']['reason']
            if predicate(state):
                return state
            time.sleep(0.005)
        raise AssertionError('Timed out: '+json.dumps(state))

    def close(self):
        self.child.send_signal(signal.SIGTERM)
        self.child.wait(timeout=5)
        self.output.close()
        assert self.child.returncode == 0, self.log.read_text()


def moved(directory):
    scene = Scene(directory)
    try:
        scene.wait(lambda s: s['case']['phase'] == 'lifting' and s['gripper']['held'])
        before = scene.request('/api/sim/pause', {})
        for path, body in (('/api/sim/container/push', {'impulse':[100, 0, 0]}),
                           ('/api/sim/container/markers', {'enabled':1})):
            try:
                scene.request(path, body)
                raise AssertionError('invalid perturbation accepted')
            except urllib.error.HTTPError as error:
                assert error.code == 400
        scene.request('/api/sim/container/push', {'impulse':[0.27, 0.015, 0], 'pointOffset':[0, 0.015, 0]})
        scene.request('/api/sim/resume', {})
        state = scene.wait(lambda s: s['case']['passed'])
        assert math.dist(before['case']['container']['position'][:2], state['case']['container']['position'][:2]) > 0.03
    finally:
        scene.close()
    inspect(scene.journal, scene.definition)
    print('Pushed/rotated box: camera rays and pose accuracy checked, visual return and physical containment passed', flush=True)


def occluded(directory):
    scene = Scene(directory)
    try:
        scene.wait(lambda s: s['case']['phase'] == 'placing' and s['case']['dockVision']['valid'])
        before = scene.request('/api/sim/pause', {})
        scene.request('/api/sim/container/markers', {'enabled':False})
        scene.request('/api/sim/container/push', {'impulse':[0.17, 0.04, 0]})
        scene.request('/api/sim/resume', {})
        hidden = scene.wait(lambda s: s['step'] >= before['step']+150)
        assert hidden['gripper']['held'] and hidden['gripper']['releases'] == 0
        assert not hidden['case']['dockVision']['valid']
        assert hidden['case']['dockVision']['frameId'] <= before['totalSteps']
        scene.request('/api/sim/container/markers', {'enabled':True})
        state = scene.wait(lambda s: s['case']['passed'])
        assert state['gripper']['releases'] == 1
        assert math.dist(before['case']['container']['position'][:2], state['case']['container']['position'][:2]) > 0.01
    finally:
        scene.close()
    inspect(scene.journal, scene.definition)
    print('Occluded/moved box: stale observation refused, brick held, camera reacquired and release succeeded', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='retain traces in a new directory')
    args = parser.parse_args()
    if args.output:
        directory = args.output.resolve()
        directory.mkdir(parents=True, exist_ok=False)
        moved(directory/'moved')
        occluded(directory/'occluded')
        print('Camera return-box checks passed')
        return
    with tempfile.TemporaryDirectory(prefix='sim-dock-', dir=ROOT/'build/flex/sim') as temp:
        directory = Path(temp)
        moved(directory/'moved')
        occluded(directory/'occluded')
    print('Camera return-box checks passed')


if __name__ == '__main__':
    main()
