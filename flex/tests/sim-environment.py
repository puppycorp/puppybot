#!/usr/bin/env python3
"""Exercise Blender furniture and doorways using the production drive API."""
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

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('simulation_checks', Path(__file__).with_name('sim.py'))
simulation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(simulation)
ASSET = ROOT/'build/flex/sim/environments/apartment/apartment.bin'


def drive(directory, name, spawn, done, obstacle=None, timeout=12):
    log = directory/(name+'.log')
    with log.open('w') as output:
        child = subprocess.Popen([str(simulation.BINARY), '--headless', '--steps', '1000000',
            '--environment', str(ASSET), '--spawn', json.dumps(spawn), '--bind', '127.0.0.1:0'],
            cwd=ROOT, stdout=output, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic()+10
            while 'robot API port ' not in log.read_text():
                assert child.poll() is None and time.monotonic() < deadline, log.read_text()
                time.sleep(0.02)
            port = int(log.read_text().split('robot API port ')[1].splitlines()[0])
            initial = simulation.request(port, '/api/sim/state')
            assert initial['environment']['staticColliders'] == 66
            assert initial['environment']['sensorCameras'] == ['tcp']
            simulation.request(port, '/api/drive', {'throttle':100, 'steering':0})
            state = simulation.await_state(port, done, timeout=timeout)
            if obstacle:
                assert state['blocked'] and state['environment']['blockedCollider'].startswith(obstacle), state
                assert math.dist(state['pose'][:2], initial['pose'][:2]) > 0.01, state
                simulation.request(port, '/api/drive/stop', {})
                stopped = simulation.request(port, '/api/sim/state')['pose']
                simulation.request(port, '/api/drive', {'throttle':-100, 'steering':0})
                escaped = simulation.await_state(port, lambda s: math.dist(s['pose'][:2], stopped[:2]) > 0.03)
                assert not escaped['blocked'], escaped
            else:
                assert not state['blocked'], state
            assert state['physicsFault'] == state['vehicle']['queryFault'] == 0
            simulation.request(port, '/api/drive/stop', {})
            (directory/(name+'.json')).write_text(json.dumps(state, indent=2)+'\n')
            print(name+': checked', flush=True)
        finally:
            child.send_signal(signal.SIGTERM)
            child.wait(timeout=10)
        assert child.returncode == 0, log.read_text()


def invalid_assets(directory):
    raw = ASSET.read_bytes()
    variants = {'truncated':raw[:-1], 'short':raw[:128]}
    for name, offset, fmt, value in (
        ('count', 8, '<Q', 161), ('bound-nan', 64, '<d', float('nan')),
        ('half-zero', 256+72, '<d', 0), ('vertex-inf', 256+66*128, '<f', float('inf')),
    ):
        changed = bytearray(raw)
        struct.pack_into(fmt, changed, offset, value)
        variants[name] = changed
    for name, data in variants.items():
        path = directory/(name+'.bin')
        path.write_bytes(data)
        result = subprocess.run([str(simulation.BINARY), '--headless', '--steps', '1',
            '--environment', str(path)], cwd=ROOT, capture_output=True, text=True, timeout=10)
        assert result.returncode == 2 and 'Invalid/missing Blender environment' in result.stderr, (name, result)
    for spawn in ('[8,0,0]', '[0,0]', '[0,"bad",0]', '[0,0,101]'):
        result = subprocess.run([str(simulation.BINARY), '--headless', '--steps', '1', '--environment',
            str(ASSET), '--spawn', spawn], cwd=ROOT, capture_output=True, text=True, timeout=10)
        assert result.returncode == 2, (spawn, result)
    result = subprocess.run([str(simulation.BINARY), '--headless', '--steps', '1', '--environment',
        str(ASSET), '--spawn', '[0.6,2.18,0]'], cwd=ROOT, capture_output=True, text=True, timeout=10)
    assert result.returncode == 1 and 'spawn intersects' in result.stderr, result
    print('Malformed world/spawn rejection: checked', flush=True)


def render(directory):
    # Original mount checks use independent URDF transforms. The world observer
    # is already part of the simulator, not another robot sensor.
    view_spec = importlib.util.spec_from_file_location('view_checks', Path(__file__).with_name('sim-views.py'))
    views = importlib.util.module_from_spec(view_spec)
    view_spec.loader.exec_module(views)
    for camera in ('orbit', 'tcp'):
        path = directory/(camera+'.png')
        state = simulation.run('--hidden', '--steps', '1', '--environment', str(ASSET), '--camera', camera,
            '--bind', '127.0.0.1:0', '--capture', path, '--no-tcp-view')
        metadata = json.loads(Path(str(path)+'.camera.json').read_text())
        assert state['physicsFault'] == 0
        if camera == 'tcp':
            views.check_mount(state, metadata)
    print('Native overview and original TCP mount: checked', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--render', action='store_true')
    parser.add_argument('--output', type=Path, default=ROOT/'build/flex/sim/environments/checks')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='fixtures-', dir=args.output) as temporary:
        invalid_assets(Path(temporary))
    drive(args.output, 'two-doorways', [2.2, 0, 0], lambda s: s['pose'][0] > 4.9, timeout=30)
    drive(args.output, 'outer-wall', [6.6, 0, 0], lambda s: s['blocked'], 'Wall.outer-east')
    drive(args.output, 'sofa', [0.6, 1.0, math.pi/2], lambda s: s['blocked'], 'Sofa.')
    drive(args.output, 'table-leg', [4.72, -2.08, 0], lambda s: s['blocked'], 'Dining.leg-')
    drive(args.output, 'under-table', [5.5, -1.65, 0], lambda s: s['pose'][0] > 6.15)
    drive(args.output, 'low-tabletop', [1.35, -2.35, math.pi/2], lambda s: s['blocked'], 'Coffee.top')
    drive(args.output, 'door-frame', [2.3, 0.68, 0], lambda s: s['blocked'], ('Wall.living', 'Trim.living'))
    if args.render:
        render(args.output)
    print('Environment checks passed: two doorways, expanded bounds, walls, sofa, leg, under-table clearance, low tabletop, door frame, reverse escape, invalid assets', flush=True)


if __name__ == '__main__':
    main()
