#!/usr/bin/env python3
"""Check TCP mounting, camera motion and isolation of the native viewports."""
import importlib.util
import json
import math
from pathlib import Path
import sys
import tempfile

# Avoid tests/numbers.py shadowing the standard module used by Pillow.
sys.path = [p for p in sys.path if Path(p).resolve() != Path(__file__).resolve().parent]
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('simulation_checks', Path(__file__).with_name('sim.py'))
simulation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(simulation)


def capture(directory, name, *args):
    path = directory/(name+'.png')
    state = simulation.run('--hidden', '--bind', '127.0.0.1:0', '--capture', path, *args)
    camera = json.loads(Path(str(path)+'.camera.json').read_text())
    with Image.open(path) as image:
        pixels = image.convert('RGB').copy()
    return state, camera, pixels


def check_mount(state, camera, grasp_offset=0.045):
    assert camera['view'] == 'tcp'
    # Independent URDF traversal supplies the TCP position. The finger axis
    # comes from the observable grasp centre and the configured finger offset.
    tcp = simulation.urdf_tcp(state)
    axis = [(state['gripper']['centre'][i]-tcp[i])/grasp_offset for i in range(3)]
    offset = [camera['eyeM'][i]-tcp[i] for i in range(3)]
    assert abs(math.dist(offset, [0, 0, 0])-math.hypot(0.065, 0.065)) < 0.001
    assert abs(sum(a*b for a, b in zip(axis, offset))+0.065) < 0.001
    target = [tcp[i]+0.065*axis[i]-camera['eyeM'][i] for i in range(3)]
    length = math.dist(target, [0, 0, 0])
    assert math.dist([v/length for v in target], camera['forward']) < 0.008
    for key in ('right', 'down', 'forward'):
        assert abs(math.dist(camera[key], [0, 0, 0])-1) < 0.00001
    assert abs(sum(a*b for a, b in zip(camera['right'], camera['down']))) < 0.00001
    assert camera['frameId'] == state['totalSteps']


def main():
    with tempfile.TemporaryDirectory(prefix='sim-views-', dir=ROOT/'build/flex/sim') as temp:
        directory = Path(temp)
        initial, first_camera, first = capture(directory, 'initial', '--camera', 'tcp', '--steps', 1, '--demo')
        moved, next_camera, second = capture(directory, 'moved', '--camera', 'tcp', '--steps', 120, '--demo', '--tcp-view')
        assert not (directory/'moved.png.tcp.camera.json').exists()
        check_mount(initial, first_camera)
        check_mount(moved, next_camera)
        assert first.size == second.size == (640, 480)
        assert math.dist(first_camera['eyeM'], next_camera['eyeM']) > 0.02
        assert math.dist(first_camera['forward'], next_camera['forward']) > 0.01
        assert initial['pose'] != moved['pose'] and initial['ticks'] != moved['ticks']
        assert first.tobytes() != second.tobytes()

        _, base_camera, base = capture(directory, 'world', '--steps', 120, '--demo', '--tcp-view', '--no-tcp-view', '--record', directory/'baseline.jsonl')
        state, main_camera, inset = capture(directory, 'inset', '--steps', 120, '--demo', '--tcp-view')
        tcp_camera = json.loads((directory/'inset.png.tcp.camera.json').read_text())
        check_mount(state, tcp_camera)
        assert main_camera == base_camera
        width, height = tcp_camera['width'], tcp_camera['height']
        x, top = inset.width-width-20, 20
        changes = 0
        for y in range(inset.height):
            for column in range(inset.width):
                a, b = base.getpixel((column, y)), inset.getpixel((column, y))
                if x-3 <= column < x+width+3 and top-3 <= y < top+height+31:
                    changes += a != b
                else:
                    assert a == b, 'inset cleared or changed the main viewport'
        assert changes > 10000
        caption = inset.crop((x, top+height, x+width, top+height+28))
        rgb = caption.tobytes()
        assert sum(r > 100 and g > 220 and b > 220 for r, g, b in zip(rgb[0::3], rgb[1::3], rgb[2::3])) > 100

        _, _, outlined = capture(directory, 'colliders', '--steps', 120, '--demo', '--tcp-view', '--colliders')
        assert outlined.crop((x, top, x+width, top+height)).tobytes() == inset.crop((x, top, x+width, top+height)).tobytes(), 'collider overlay entered the TCP sensor'
        assert sum(a != b for a, b in zip(outlined.tobytes(), inset.tobytes())) > 1000
        _, _, rover = capture(directory, 'rover-clean', '--steps', 1, '--camera', 'rover')
        _, _, rover_debug = capture(directory, 'rover-debug', '--steps', 1, '--camera', 'rover', '--colliders')
        assert rover.tobytes() == rover_debug.tobytes(), 'collider overlay entered the rover sensor'

        held, _, image = capture(directory, 'held', '--steps', 1150, '--pickup', '--tcp-view')
        assert held['pickup']['passed'] and held['gripper']['held']
        pane = image.crop((x, top, x+width, top+height))
        rgb = pane.tobytes()
        assert sum(r > 140 and r > g*1.2 and g > b*2 for r, g, b in zip(rgb[0::3], rgb[1::3], rgb[2::3])) > 1000

        state, _, _ = capture(directory, 'panels', '--steps', 120, '--demo', '--no-tcp-view', '--camera-panels', '--record', directory/'panels.jsonl')
        assert (directory/'panels.jsonl').read_bytes() == (directory/'baseline.jsonl').read_bytes(), 'live panes changed controller observations'
        panels = json.loads((directory/'panels.png.views.json').read_text())
        assert panels['enabled'] and panels['updateIntervalMs'] == 100
        assert [v['camera'] for v in panels['views']] == ['front', 'tcp']
        for view in panels['views']:
            assert view['frameId'] == state['totalSteps'] and view['capturedMs'] == state['timeMs']
            name = 'panels.png.'+view['camera']+'.png'
            metadata = json.loads((directory/(name+'.camera.json')).read_text())
            assert metadata['frameId'] == view['frameId'] and metadata['capturedMs'] == view['capturedMs']
            with Image.open(directory/name) as pane:
                assert pane.size == (640, 480)
            if view['camera'] == 'tcp':
                check_mount(state, metadata)
            else:
                x, y, heading = state['pose']
                assert math.dist(metadata['eyeM'], [x+0.09*math.cos(heading), y+0.09*math.sin(heading), 0.24]) < 0.003

        # Dedicated model input must not depend on observer/debug overlays.
        _, _, front_reference = capture(directory, 'front-reference', '--steps', 120, '--demo', '--camera', 'rover', '--no-tcp-view', '--sensor-capture', directory/'clean')
        exported = simulation.run('--hidden', '--bind', '127.0.0.1:0', '--steps', 120, '--demo',
                                  '--camera-panels', '--colliders', '--sensor-capture', directory/'sensor', '--record', directory/'sensor.jsonl')
        assert (directory/'sensor.jsonl').read_bytes() == (directory/'baseline.jsonl').read_bytes(), 'sensor export changed controller observations'
        for camera, reference in (('front', front_reference), ('tcp', second)):
            with Image.open(directory/f'sensor.{camera}.png') as image:
                pixels = image.convert('RGB').tobytes()
            with Image.open(directory/f'clean.{camera}.png') as image:
                assert pixels == image.convert('RGB').tobytes(), 'observer markup entered model input'
            # Window/default-FBO colour conversion differs by one level at a
            # few pixels from RGB8 texture conversion; geometry must agree.
            assert max(abs(a-b) for a, b in zip(pixels, reference.tobytes())) <= 1
            metadata = json.loads((directory/f'sensor.{camera}.png.camera.json').read_text())
            assert metadata['frameId'] == exported['totalSteps'] and metadata['capturedMs'] == exported['timeMs']
            if camera == 'tcp':
                check_mount(exported, metadata)
    print('View checks passed: URDF-relative TCP mounting, arm and chassis motion, isolated inset color/depth, caption, visible held ball')
    print('Live pair checks passed: full-resolution front/TCP captures, original mounts, fresh metadata, unchanged controller trace')
    print('Model input checks passed: clean sensor exports match original RGB with observer/debug overlays enabled')


if __name__ == '__main__':
    main()
