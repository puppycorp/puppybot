#!/usr/bin/env python3
"""Exercise actual native YOLO camera pickup and detection-failure guards."""
import argparse
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile

# Keep tests/numbers.py from shadowing Python's numbers module when Pillow
# lazily imports fractions while opening PNGs.
sys.path = [p for p in sys.path if Path(p).resolve() != Path(__file__).resolve().parent]
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SIM = ROOT/'build/flex/puppybot-sim'
DETECTOR = ROOT/'build/flex/puppybot-vision'
MANIFEST = ROOT/'build/flex/vision/yolo26n/model.json'


def simulate(*args, expected=0):
    process = subprocess.run([str(SIM), '--bind', '127.0.0.1:0', *map(str, args)], cwd=ROOT, capture_output=True, text=True, timeout=40)
    assert process.returncode == expected, process.stdout + process.stderr
    return json.loads(process.stdout.strip().splitlines()[-1])


def ray(camera, box):
    # Independent estimate from the published calibration and detector box.
    k = camera['intrinsics']
    u, v = (box[0]+box[2])/2, (box[1]+box[3])/2
    direction = [camera['forward'][i] + (u-k['cx'])/k['fx']*camera['right'][i] + (v-k['cy'])/k['fy']*camera['down'][i] for i in range(3)]
    distance = (0.035-camera['eyeM'][2])/direction[2]
    return [camera['eyeM'][i]+distance*direction[i] for i in range(3)]


def fixture(path, result):
    # These fixtures only exercise rejection paths. Positive evidence always
    # comes from the real native detector and the actual prepared checkpoint.
    path.write_text('#!/usr/bin/env python3\nprint('+repr(json.dumps(result))+')\n')
    path.chmod(0o700)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend', default='auto', choices=('auto', 'sass', 'cuda', 'hip', 'cpu'))
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='sim-vision-', dir=ROOT/'build/flex/sim') as temp:
        directory = Path(temp)
        # Confirm native PNG's bottom-up stride agrees with the existing PPM.
        png, ppm = directory/'tcp.png', directory/'tcp.ppm'
        for image in (png, ppm):
            simulate('--hidden', '--steps', 2, '--camera', 'tcp', '--capture', image)
        with Image.open(png) as a, Image.open(ppm) as b:
            assert a.size == b.size == (640, 480)
            assert a.convert('RGB').tobytes() == b.convert('RGB').tobytes()

        journal = directory/'pickup.jsonl'
        state = simulate('--hidden', '--steps', 1150, '--vision-pickup', '--vision-backend', args.backend,
                         '--vision-output', directory, '--record', journal, '--tcp-view', '--capture', directory/'held.png')
        assert state['pickup']['source'] == 'yolo-floor-plane-v1'
        assert state['pickup']['passed'] and state['gripper']['held']
        assert state['gripper']['captureContactMask'] == 3 and state['physicsFault'] == 0
        assert state['ball'][2] > 0.12 and state['vision']['confidence'] > 0.5
        evidence = Path(state['vision']['directory'])
        if not evidence.is_absolute():
            evidence = ROOT/evidence
        camera = json.loads((evidence/'camera.png.camera.json').read_text())
        detections = json.loads((evidence/'detections.json').read_text())
        assert json.loads((directory/'held.png.tcp.camera.json').read_text())['view'] == 'tcp'
        assert camera['view'] == 'tcp' and (camera['width'], camera['height']) == (640, 480)
        assert set(camera) == {'schema', 'view', 'width', 'height', 'imageRotationDeg', 'frameId', 'capturedMs', 'intrinsics', 'eyeM', 'right', 'down', 'forward'}
        assert detections['runtime'] == 'pup' and detections['backend'] in ('sass', 'cuda', 'hip', 'cpu')
        model = json.loads(MANIFEST.read_text())
        assert detections['model']['weightsSha256'] == model['weightsSha256']
        best = max((d for d in detections['detections'] if d['label'] == 'sports ball' and d['classId'] == 32), key=lambda d: d['confidence'])
        assert abs(best['confidence']-state['vision']['confidence']) < 1e-9
        assert math.dist(ray(camera, best['box']), state['vision']['targetM']) < 1e-9
        observations = [json.loads(line) for line in journal.read_text().splitlines()]
        captured = next(s for s in observations if s['step'] == state['vision']['cameraFrameId'])
        assert math.dist(captured['ball'], state['vision']['targetM']) < 0.005
        with Image.open(evidence/'camera.png') as source, Image.open(evidence/'detected.png') as preview:
            assert source.size == preview.size == (640, 480)
            assert source.tobytes() != preview.tobytes()
            pixels = preview.convert('RGB').tobytes()
            green = sum(g > 240 and r < 50 and b < 80 for r, g, b in zip(pixels[0::3], pixels[1::3], pixels[2::3]))
            assert green > 200
        # Replay the identical saved RGB through the real executable; inference
        # must agree with the result actually used for robot planning.
        rerun = subprocess.run([str(DETECTOR), '--model', str(MANIFEST), '--image', str(evidence/'camera.png'), '--backend', args.backend], cwd=ROOT, capture_output=True, text=True, timeout=30)
        assert rerun.returncode == 0, rerun.stderr
        rerun_ball = max((d for d in json.loads(rerun.stdout)['detections'] if d['label'] == 'sports ball'), key=lambda d: d['confidence'])
        assert abs(rerun_ball['confidence']-best['confidence']) < 1e-5

        empty = {'schema': 'puppybot.detections.v1', 'coordinates': 'image-pixels', 'frame': {'width': 640, 'height': 480}, 'detections': []}
        wrong_class = {**empty, 'detections': [{'classId': 4, 'label': 'airplane', 'confidence': 0.99, 'box': [180, 260, 270, 355]}]}
        upward = {**empty, 'detections': [{'classId': 32, 'label': 'sports ball', 'confidence': 0.99, 'box': [250, 0, 300, 20]}]}
        for name, result in (('empty', empty), ('wrong-class', wrong_class), ('upward-ray', upward)):
            executable = directory/(name+'.py')
            fixture(executable, result)
            rejected = simulate('--hidden', '--steps', 60, '--vision-pickup', '--vision-binary', executable, '--vision-output', directory, expected=1)
            assert rejected['vision']['state'] == 'failed' and rejected['pickup']['phase'] == 'failed'
            assert not rejected['pickup']['passed'] and rejected['pose'] == [0, 0, 0]
            assert rejected['gripper']['grasps'] == 0 and rejected['vision']['targetM'] is None
        failed = simulate('--hidden', '--steps', 60, '--vision-pickup', '--detector-model', directory/'missing-model.json', '--vision-output', directory, expected=1)
        assert failed['vision']['state'] == 'failed' and failed['pose'] == [0, 0, 0]
        assert 'detector failed' in failed['pickup']['reason']
        log = Path(failed['vision']['directory'])/'detector.log'
        assert log.read_text().strip()
    print('Camera/YOLO checks passed: native PNG orientation, real RGB inference and checkpoint, calibrated target, successful pickup, bounding-box preview, no-target/wrong-class/ray/model rejection without oracle fallback')


if __name__ == '__main__':
    main()
