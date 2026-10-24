#!/usr/bin/env python3
"""Check physical scenery guards, transactional loading and replayable stress fixtures."""
import importlib.util
import json
from pathlib import Path
import signal
import subprocess
import tempfile
import time
import urllib.error

ROOT = Path(__file__).resolve().parents[2]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


stress = module('stress_cases', ROOT/'flex/scripts/stress-cases.py')
simulation = module('simulation_checks', Path(__file__).with_name('sim.py'))


def check(directory):
    scene, details = stress.definition('control', 0, 42)
    scene['controller'] = 'scene-state'
    scene['scenery'] = [dict(id='solid-divider', position=[0.30, 0, 0.10], halfSize=[0.012, 0.18, 0.10], color=[40, 40, 40])]
    stress.fixture(directory, scene, details)
    catalog_path = directory/'flex/sim/cases/catalog.json'
    catalog = json.loads(catalog_path.read_text())
    catalog['cases'][0]['controller'] = 'scene-state'
    stress.write_json(catalog_path, catalog)
    case_path = directory/'case.json'
    log = directory/'simulation.log'
    with log.open('w') as output:
        process = subprocess.Popen([str(simulation.BINARY), '--headless', '--steps', '10000', '--realtime', '--bind', '127.0.0.1:0'],
                                   cwd=directory, stdout=output, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic()+5
            while 'robot API port ' not in log.read_text():
                assert process.poll() is None and time.monotonic() < deadline, log.read_text()
                time.sleep(0.02)
            port = int(log.read_text().split('robot API port ')[1].splitlines()[0])
            simulation.request(port, '/api/sim/cases/stress-control', {})
            simulation.request(port, '/api/sim/reset', {})
            state = simulation.request(port, '/api/sim/state')
            prop = state['case']['scenery'][0]
            assert prop['fixed'] and prop['position'] == scene['scenery'][0]['position']
            assert prop['body'] < state['vehicle']['wheels'][0]['body']
            simulation.request(port, '/api/drive', dict(throttle=100, steering=0))
            state = simulation.await_state(port, lambda s: s['blocked'])
            assert state['vehicle']['blockedBody'] == prop['body'] and state['pose'][0] < 0.18
            assert state['physicsFault'] == state['vehicle']['queryFault'] == 0
            stopped = state['pose']
            simulation.request(port, '/api/drive', dict(throttle=100, steering=0))
            time.sleep(0.12)
            assert simulation.request(port, '/api/sim/state')['pose'] == stopped
            simulation.request(port, '/api/drive', dict(throttle=-100, steering=0))
            escaped = simulation.await_state(port, lambda s: s['pose'][0] < stopped[0]-0.02)
            assert not escaped['blocked']
            print('Scenery: chassis stops before a solid prop, cannot tunnel through it and can reverse away', flush=True)
            simulation.request(port, '/api/sim/pause', {})
            before = simulation.request(port, '/api/sim/state')
            for bad in ({}, [dict(scene['scenery'][0], halfSize=[0, 0.1, 0.1])], scene['scenery']*9,
                        [dict(scene['scenery'][0], id='')], scene['scenery']*2,
                        [dict(scene['scenery'][0], position=[0, 0, -0.1])],
                        [dict(scene['scenery'][0], color=[101, 0, 0])]):
                stress.write_json(case_path, dict(scene, scenery=bad))
                try:
                    simulation.request(port, '/api/sim/cases/stress-control', {})
                    raise AssertionError('invalid scenery accepted')
                except urllib.error.HTTPError as error:
                    assert error.code == 400
                assert simulation.request(port, '/api/sim/state') == before, 'invalid definition mutated the running scene'
            for yaw in (181, True, '90'):
                broken = json.loads(json.dumps(scene))
                broken['objects'][0]['yawDegrees'] = yaw
                stress.write_json(case_path, broken)
                try:
                    simulation.request(port, '/api/sim/cases/stress-control', {})
                    raise AssertionError('invalid object yaw accepted')
                except urllib.error.HTTPError as error:
                    assert error.code == 400
                assert simulation.request(port, '/api/sim/state') == before
            stress.write_json(case_path, scene)
            reset = simulation.request(port, '/api/sim/cases/stress-control', {})
            assert reset['case']['scenery'] == before['case']['scenery']
            print('Scenery: malformed/oversized/duplicate records rejected without mutating paused state; reload restores the scene', flush=True)
        finally:
            process.send_signal(signal.SIGTERM)
            process.wait(timeout=5)
        assert process.returncode == 0, log.read_text()


def capacity(directory):
    scene, details = stress.definition('control', 0, 42)
    scene['controller'] = 'scene-state'
    template = scene['objects'][0]
    scene['objects'] = [dict(template, id=f'brick-{i}', position=[0.30+i*0.10, 0.15, 0.013]) for i in range(8)]
    scene['scenery'] = [dict(id=f'prop-{i}', position=[0.30+i*0.10, 0.8, 0.012], halfSize=[0.022, 0.014, 0.012], color=[40, 40, 40]) for i in range(8)]
    stress.fixture(directory, scene, details)
    path = directory/'flex/sim/cases/catalog.json'
    catalog = json.loads(path.read_text())
    catalog['cases'][0]['controller'] = 'scene-state'
    stress.write_json(path, catalog)
    result = subprocess.run([str(simulation.BINARY), '--headless', '--steps', '1', '--case', scene['id'], '--bind', '127.0.0.1:0'],
                            cwd=directory, capture_output=True, text=True, timeout=30)
    assert result.returncode == 1, result.stdout+result.stderr  # A one-step task is deliberately incomplete.
    state = json.loads(result.stdout.strip().splitlines()[-1])
    assert len(state['case']['objects']) == len(state['case']['scenery']) == 8
    assert state['vehicle']['wheels'][0]['body'] == 24 and state['collision']['armProxies'] == 32
    assert state['physicsFault'] == 0
    print('Capacity: eight targets plus eight solid props, four tyres and 32 arm proxies fit and serialize', flush=True)


def main():
    with tempfile.TemporaryDirectory(prefix='sim-stress-', dir=ROOT/'build/flex/sim') as temp:
        check(Path(temp)/'scenery')
        capacity(Path(temp)/'capacity')
    print('Stress infrastructure checks passed')


if __name__ == '__main__':
    main()
