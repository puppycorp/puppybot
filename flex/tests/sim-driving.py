#!/usr/bin/env python3
"""Drive the production simulator into low bricks and taller obstacles via HTTP."""
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


def drive(directory, name, position, half_size, throttle, steering=0, clearance=False):
    work = directory/name
    cases = work/'flex/sim/cases'
    cases.mkdir(parents=True)
    (work/'build').symlink_to(ROOT/'build', target_is_directory=True)
    definition = json.loads((ROOT/'flex/sim/cases/blocks-into-box.json').read_text())
    definition['id'] = name
    definition['objects'] = [dict(definition['objects'][0], position=position, halfSize=half_size)]
    definition['container']['position'] = [1.2, -1.2, 0]
    (work/'fixture.json').write_text(json.dumps(definition))
    (cases/'catalog.json').write_text(json.dumps({'schema':'puppybot.cases.v1', 'cases':[{'id':name, 'name':name, 'file':'fixture.json'}]}))
    log = work/'simulation.log'
    with log.open('w') as output:
        child = subprocess.Popen([str(simulation.BINARY), '--headless', '--steps', '5000', '--realtime', '--bind', '127.0.0.1:0'], cwd=work, stdout=output, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic()+5
            while 'robot API port ' not in log.read_text():
                assert child.poll() is None and time.monotonic() < deadline, log.read_text()
                time.sleep(0.02)
            port = int(log.read_text().split('robot API port ')[1].splitlines()[0])
            simulation.request(port, '/api/sim/cases/'+name, {})
            simulation.request(port, '/api/sim/reset', {})
            settled = simulation.await_state(port, lambda s: s['step'] >= 30)
            wheels = settled['vehicle']['wheels']
            assert len(wheels) == 4 and len({w['body'] for w in wheels}) == 4
            for wheel in wheels:
                assert abs(wheel['radius']-0.0325) < 1e-6
                assert 0.017 < wheel['halfWidth'] < 0.019
                assert abs(math.sqrt(sum(v*v for v in wheel['axis']))-1) < 1e-6
                assert abs(wheel['centre'][2]-wheel['radius']) < 0.0002
            initial = settled['case']['objects'][0]['position']
            simulation.request(port, '/api/drive', {'throttle':throttle, 'steering':steering})
            if clearance:
                state = simulation.await_state(port, lambda s: s['pose'][0] > 0.45)
                assert not state['blocked']
            else:
                state = simulation.await_state(port, lambda s: s['blocked'])
                assert state['vehicle']['blockedBody'] == 3, state
                assert (state['vehicle']['blockedPart'] == 0) == (half_size[2] > 0.03), state
                # At maximum speed the accepted root must still be before the
                # obstacle. The swept query must neither shove nor tunnel through it.
                assert abs(state['pose'][0]) < abs(position[0])-0.07, state['pose']
                assert math.dist(initial, state['case']['objects'][0]['position']) < 0.001
                stopped = state['pose']
                simulation.request(port, '/api/drive', {'throttle':throttle, 'steering':steering})
                time.sleep(0.12)
                state = simulation.request(port, '/api/sim/state')
                assert state['pose'] == stopped and state['blocked']
                simulation.request(port, '/api/drive', {'throttle':-throttle, 'steering':0})
                escaped = simulation.await_state(port, lambda s: math.dist(s['pose'][:2], stopped[:2]) > 0.02)
                assert not escaped['blocked']
            assert state['physicsFault'] == state['vehicle']['queryFault'] == 0
            print(name+': checked', flush=True)
        finally:
            child.send_signal(signal.SIGTERM)
            child.wait(timeout=5)
        assert child.returncode == 0, log.read_text()


def main():
    with tempfile.TemporaryDirectory(prefix='sim-driving-', dir=ROOT/'build/flex/sim') as temp:
        directory = Path(temp)
        drive(directory, 'front-wheel', [0.28, 0.08, 0.012], [0.022, 0.014, 0.012], 100)
        drive(directory, 'rear-wheel', [-0.28, 0.08, 0.012], [0.022, 0.014, 0.012], -100)
        drive(directory, 'turning-wheel', [0.28, -0.03, 0.012], [0.022, 0.014, 0.012], 100, steering=100)
        drive(directory, 'narrow-brick', [0.28, 0.08, 0.005], [0.005, 0.005, 0.005], 100)
        drive(directory, 'chassis', [0.28, 0, 0.04], [0.022, 0.014, 0.04], 100)
        drive(directory, 'under-belly', [0.28, 0, 0.012], [0.022, 0.014, 0.012], 100, clearance=True)
    print('Drive checks passed: mesh-aligned tyres, forward/reverse wheel stops, chassis stop, escape, genuine ground clearance, no tunnelling or query faults')


if __name__ == '__main__':
    main()
