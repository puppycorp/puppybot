#!/usr/bin/env python3
"""Container collision probes through the production robot and simulation APIs."""
import importlib.util
import json
import math
from pathlib import Path
import signal
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('simulation_checks', Path(__file__).with_name('sim.py'))
simulation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(simulation)


class Scene:
    def __init__(self, directory, name, position, height=0.09, dynamic=False, mass=0.3):
        self.work = directory/name
        cases = self.work/'flex/sim/cases'
        cases.mkdir(parents=True)
        (self.work/'build').symlink_to(ROOT/'build', target_is_directory=True)
        definition = json.loads((ROOT/'flex/sim/cases/blocks-into-box.json').read_text())
        definition['id'] = name
        definition['objects'] = [dict(definition['objects'][0], position=[1.2, 1.2, 0.012])]
        definition['container'].update(position=position, innerSize=[0.16, 0.16, height], fixed=not dynamic, mass=mass)
        (self.work/'fixture.json').write_text(json.dumps(definition))
        (cases/'catalog.json').write_text(json.dumps({'schema':'puppybot.cases.v1', 'cases':[{'id':name, 'name':name, 'file':'fixture.json'}]}))
        self.log = self.work/'simulation.log'
        self.output = self.log.open('w')
        self.child = subprocess.Popen([str(simulation.BINARY), '--headless', '--steps', '10000', '--realtime', '--bind', '127.0.0.1:0', '--record', str(self.work/'trace.jsonl')], cwd=self.work, stdout=self.output, stderr=subprocess.STDOUT)
        deadline = time.monotonic()+5
        while 'robot API port ' not in self.log.read_text():
            assert self.child.poll() is None and time.monotonic() < deadline, self.log.read_text()
            time.sleep(0.02)
        self.port = int(self.log.read_text().split('robot API port ')[1].splitlines()[0])
        self.request('/api/sim/cases/'+name, {})
        self.request('/api/sim/reset', {})

    def request(self, path, body=None):
        return simulation.request(self.port, path, body)

    def wait(self, predicate, timeout=18):
        return simulation.await_state(self.port, predicate, timeout)

    def angles(self, values):
        self.request('/api/arm/speed', {'speed':220})
        self.request('/api/arm/goto-angles', dict(zip(('yawDeg','shoulderDeg','elbowDeg','wristDeg'), values)))
        self.command_step = self.request('/api/sim/state')['step']

    def reached(self, values):
        return self.wait(lambda s: s['step'] > self.command_step and not s['collision']['armBlocked'] and max(abs(math.degrees(a)-b) for a, b in zip(s['jointAnglesRad'], values)) < 0.8)

    def close(self):
        self.child.send_signal(signal.SIGTERM)
        self.child.wait(timeout=5)
        self.output.close()
        assert self.child.returncode == 0, self.log.read_text()


def box_drive(directory, reverse):
    sign = -1 if reverse else 1
    scene = Scene(directory, 'back-box' if reverse else 'front-box', [sign*0.35, 0, 0])
    try:
        scene.request('/api/drive', {'throttle':sign*100, 'steering':0})
        state = scene.wait(lambda s: s['blocked'])
        first_bin = state['case']['container']['body']
        assert state['vehicle']['blockedBody'] == first_bin, state
        assert abs(state['pose'][0]) < 0.13 and state['vehicle']['queryFault'] == 0
        stopped = state['pose']
        time.sleep(0.1)
        assert scene.request('/api/sim/state')['pose'] == stopped
        scene.request('/api/drive', {'throttle':-sign*100, 'steering':0})
        state = scene.wait(lambda s: math.dist(s['pose'][:2], stopped[:2]) > 0.02)
        assert not state['blocked'] and state['physicsFault'] == 0
    finally:
        scene.close()
    print(('Reverse' if reverse else 'Forward')+' chassis/container stop and escape checked', flush=True)


def gripper_wall(directory):
    scene = Scene(directory, 'gripper-wall', [0.34, -0.21, 0])
    try:
        scene.request('/api/drive', {'throttle':20, 'steering':0})
        scene.wait(lambda s: s['pose'][0] >= 0.22)
        scene.request('/api/drive/stop', {})
        above = [-149.94140625, 75.498046875, 107.40234375, -107.05078125]
        upright = [above[0], 90, 0, 0]
        scene.angles(upright)
        assert not scene.reached(upright)['collision']['armBlocked']
        scene.angles(above)
        safe = scene.reached(above)
        assert not safe['collision']['armBlocked'], safe
        # This direct diagonal transfer lowers a finger through the box's X
        # wall. Both endpoints are valid joint targets; the path must stop.
        across = [-49.39453125, 66.4453125, 117.333984375, -107.40234375]
        scene.angles(across)
        blocked = scene.wait(lambda s: s['collision']['armBlocked'])
        first_bin = blocked['case']['container']['body']
        assert blocked['collision']['body'] == first_bin
        assert 0 <= blocked['collision']['part'] < 3, blocked['collision']
        assert blocked['pose'] == safe['pose'] and blocked['physicsFault'] == 0
        ticks = blocked['ticks']
        time.sleep(0.15)
        assert scene.request('/api/sim/state')['ticks'] == ticks
        scene.angles(above)
        escaped = scene.reached(above)
        assert not escaped['collision']['armBlocked']
        print('Gripper/container wall stop, stable feedback and reverse arm escape checked', flush=True)
    finally:
        scene.close()


def arm_wall(directory):
    scene = Scene(directory, 'arm-wall', [0.055, 0.22, 0], height=0.3)
    try:
        target = [0, 40, 0, 0]
        scene.angles(target)
        blocked = scene.wait(lambda s: s['collision']['armBlocked'])
        assert blocked['collision']['part'] >= 3, blocked['collision']
        assert blocked['physicsFault'] == 0 and blocked['collision']['armProxies'] > 20
        scene.angles([0, 90, 0, 0])
        escaped = scene.reached([0, 90, 0, 0])
        assert not escaped['collision']['armBlocked']
        print('Visual arm link/container stop and escape checked', flush=True)
    finally:
        scene.close()


def main():
    with tempfile.TemporaryDirectory(prefix='sim-box-', dir=ROOT/'build/flex/sim') as temp:
        directory = Path(temp)
        box_drive(directory, False)
        box_drive(directory, True)
        gripper_wall(directory)
        arm_wall(directory)
    print('Container collision checks passed')


if __name__ == '__main__':
    main()
