#!/usr/bin/env python3
"""Check real model markings, frame pairing, empty results and worker cleanup."""
import json
import math
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request

sys.path = [p for p in sys.path if Path(p).resolve() != Path(__file__).resolve().parent]
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SIM = ROOT/'build/flex/puppybot-sim'
DETECTOR = ROOT/'build/flex/puppybot-vision'
MANIFEST = ROOT/'build/flex/vision/yolo26n/model.json'


def simulate(*args, expected=0):
    p = subprocess.run([str(SIM), '--bind', '127.0.0.1:0', *map(str, args)], cwd=ROOT, capture_output=True, text=True, timeout=40)
    assert p.returncode == expected, p.stdout+p.stderr
    return json.loads(p.stdout.strip().splitlines()[-1])


def marked(path, state):
    raw = json.loads(Path(str(path)+'.yolo.json').read_text())
    candidates = [d for d in raw['detections'] if d['classId'] in (32, 49)]
    best = max(candidates, key=lambda d: d['confidence'])
    live = state['vision']['live']
    assert live['label'] == best['label'] and live['box'] == best['box']
    assert live['confidence'] == best['confidence'] > 0.5
    assert raw['frame']['id'] == live['frameId']
    assert raw['frame']['capturedMs'] == live['capturedMs'] == state['timeMs']
    replay = subprocess.run([str(DETECTOR), '--model', str(MANIFEST), '--image', str(path)+'.yolo.jpg'], cwd=ROOT, capture_output=True, text=True, timeout=20)
    assert replay.returncode == 0, replay.stderr
    repeated = max((d for d in json.loads(replay.stdout)['detections'] if d['classId'] in (32, 49)), key=lambda d: d['confidence'])
    assert repeated['label'] == best['label']
    assert abs(repeated['confidence']-best['confidence']) < 1e-5
    assert math.dist(repeated['box'], best['box']) < 1e-4
    with Image.open(str(path)+'.yolo.png') as image:
        assert image.size == (640, 480)
        x1, y1, x2, y2 = map(int, best['box'])
        # Check actual border locations in the exported observation, rather
        # than merely checking that some green pixels were rendered.
        for x, y in ((x1, (y1+y2)//2), (x2-1, (y1+y2)//2), ((x1+x2)//2, y2-1)):
            r, g, b = image.getpixel((x, y))
            assert g > 240 and r < 50 and b < 80, (x, y, (r, g, b))
        tag = image.crop((x1, max(0, y1-25), min(640, x1+len(best['label']+' 100%')*12+12), max(0, y1-25)+24)).tobytes()
        assert sum(r > 100 and g > 220 and b > 220 for r, g, b in zip(tag[::3], tag[1::3], tag[2::3])) > 100


def fixture(path):
    # Negative fixture only: no positive detection is fabricated.
    path.write_text('''#!/usr/bin/env python3
import json, socket, struct, time
s = socket.socket(fileno=3)
s.setblocking(True)
time.sleep(0.4)
s.send(b'{"ready":true}')
while True:
    packet = s.recv(49168)
    if not packet: break
    frame, captured = struct.unpack('<QQ', packet[:16])
    time.sleep(0.3)
    s.send(json.dumps({'schema':'puppybot.detections.v1','coordinates':'image-pixels',
        'frame':{'id':frame,'capturedMs':captured,'width':640,'height':480},'detections':[]}).encode())
''')
    path.chmod(0o700)


def request(port, route, post=False):
    req = urllib.request.Request(f'http://127.0.0.1:{port}/api/sim/'+route, data=b'{}' if post else None)
    with urllib.request.urlopen(req, timeout=1) as response:
        return json.load(response)


def responsive(directory, worker):
    log = directory/'live.log'
    with log.open('w') as output:
        p = subprocess.Popen([str(SIM), '--hidden', '--steps', '5000', '--realtime', '--detector-view', '--vision-binary', str(worker), '--bind', '127.0.0.1:0'], cwd=ROOT, stdout=output, stderr=subprocess.STDOUT)
        children = []
        try:
            deadline = time.monotonic()+5
            while 'robot API port ' not in log.read_text():
                assert p.poll() is None and time.monotonic() < deadline, log.read_text()
                time.sleep(0.02)
            port = int(log.read_text().split('robot API port ')[1].splitlines()[0])
            first = request(port, 'state')
            time.sleep(0.7)
            second = request(port, 'state')
            assert second['totalSteps']-first['totalSteps'] > 10, 'worker blocked simulation steps'
            assert second['vision']['live']['state'] in ('ready', 'busy')
            reset = request(port, 'reset', True)
            assert reset['vision']['live']['confidence'] == 0 and reset['vision']['live']['box'] is None
            request(port, 'pause', True)
            deadline = time.monotonic()+3
            while time.monotonic() < deadline:
                state = request(port, 'state')
                live = state['vision']['live']
                if live['frameId'] and live['capturedMs'] == state['timeMs']:
                    break
                time.sleep(0.05)
            else:
                raise AssertionError(state)
            assert live['label'] is None and live['box'] is None and live['confidence'] == 0
            children = [int(n) for n in Path(f'/proc/{p.pid}/task/{p.pid}/children').read_text().split()]
            assert children, 'expected the resident detector worker'
        finally:
            p.send_signal(signal.SIGTERM)
            p.wait(timeout=5)
        assert p.returncode == 0, log.read_text()
        assert all(not Path(f'/proc/{pid}').exists() for pid in children), 'worker survived simulator shutdown'


def main():
    with tempfile.TemporaryDirectory(prefix='sim-markings-', dir=ROOT/'build/flex/sim') as temp:
        directory = Path(temp)
        path = directory/'held.png'
        state = simulate('--hidden', '--steps', 1150, '--vision-pickup', '--tcp-view', '--detector-view', '--capture', path)
        assert state['pickup']['passed'] and state['gripper']['held']
        assert state['vision']['live']['view'] == 'tcp'
        marked(path, state)
        camera = json.loads(Path(str(path)+'.tcp.camera.json').read_text())
        assert camera['capturedMs'] == state['vision']['live']['capturedMs']
        path = directory/'tcp.png'
        tcp = simulate('--hidden', '--steps', 60, '--camera', 'tcp', '--detector-view', '--capture', path)
        assert tcp['vision']['live']['view'] == 'tcp'
        assert tcp['vision']['live']['label'] == 'sports ball'
        marked(path, tcp)
        worker = directory/'empty-worker.py'
        fixture(worker)
        path = directory/'empty.png'
        empty = simulate('--hidden', '--steps', 2, '--detector-view', '--vision-binary', worker, '--capture', path)
        assert empty['vision']['live']['confidence'] == 0 and empty['vision']['live']['box'] is None
        with Image.open(str(path)+'.yolo.png') as image:
            rgb = image.convert('RGB').tobytes()
            assert not any(g > 240 and r < 50 and b < 80 for r, g, b in zip(rgb[::3], rgb[1::3], rgb[2::3]))
        failed = simulate('--hidden', '--steps', 2, '--detector-view', '--detector-model', directory/'missing.json', '--capture', directory/'failed.png', expected=1)
        assert failed['vision']['live']['state'] == 'error'
        assert failed['vision']['live']['confidence'] == 0 and failed['vision']['live']['box'] is None
        invalid = subprocess.run([str(SIM), '--headless', '--steps', '1', '--detector-view'], cwd=ROOT, capture_output=True)
        assert invalid.returncode == 2
        responsive(directory, worker)
    print('Marking checks passed: real wrist inference, exact source replay, confidence and border placement, no invented detections, responsive steps/API, reset invalidation, worker cleanup')


if __name__ == '__main__':
    main()
