"""Optional real-GPU camera API bounds, residency, failure and cleanup checks."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[2]


def main():
    image = (ROOT/'build/flex/vision/live-test.jpg').read_bytes()
    assert 8192 < len(image) <= 48000
    with tempfile.TemporaryDirectory(prefix='puppybot-live-') as directory:
        command = [str(ROOT/'build/flex/puppybotgym'),'serve','--bind','127.0.0.1:0',
                   '--data',directory,'--model',str(ROOT/'build/flex/vision/yolo26n/model.json'),
                   '--vision',str(ROOT/'build/flex/puppybot-vision'),
                   '--vision-kernel',str(ROOT/'build/flex/vision-kernel.hip')]
        process = subprocess.Popen(command,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        worker = None
        try:
            line = process.stdout.readline()
            base = 'http://127.0.0.1:'+re.search(r'port (\d+)',line)[1]
            html = urllib.request.urlopen(base+'/live').read().decode()
            token = re.search('name="monolith-token" content="([^"]+)',html)[1]

            def request(path,data=None,headers=None):
                h = {'X-Monolith-Token':token,**(headers or {})}
                try:
                    response = urllib.request.urlopen(urllib.request.Request(base+path,data=data,headers=h),timeout=15)
                except urllib.error.HTTPError as error:
                    response = error
                return response.status,json.load(response)

            assert request('/api/gym/vision',headers={'X-Monolith-Token':'bad'})[0] == 403
            assert request('/api/gym/vision/start',b'',{'Origin':'http://example.com'})[0] == 403
            assert request('/api/gym/vision/start',b'')[0] == 200

            def ready():
                for _ in range(100):
                    state = request('/api/gym/vision')[1]['state']
                    if state == 'ready':
                        return
                    assert state != 'error'
                    time.sleep(.05)
                raise AssertionError('detector did not become ready')

            ready()
            child_file = Path(f'/proc/{process.pid}/task/{process.pid}/children')
            worker = int(child_file.read_text().strip())
            assert request('/api/gym/vision/frame',b'png!',{'Content-Type':'image/png'})[0] == 415
            assert request('/api/gym/vision/frame',b'x'*48001,{'Content-Type':'image/jpeg'})[0] == 413
            headers = {'Content-Type':'image/jpeg'}
            def detect():
                return request('/api/gym/vision/frame',image,headers)
            for _ in range(3):
                code,result = detect()
                assert code == 200 and result['runtime'] == 'pup'
                assert {'bus','person'} <= {row['label'] for row in result['detections']}
            maps = Path(f'/proc/{worker}/maps')
            before = len(maps.read_text().splitlines())
            for _ in range(30):
                assert detect()[0] == 200
            assert len(maps.read_text().splitlines()) <= before+8, 'per-frame mappings leaked'
            assert int(child_file.read_text().strip()) == worker, 'model was reloaded per frame'
            with ThreadPoolExecutor(max_workers=2) as pool:
                pending = pool.submit(detect)
                begin = time.monotonic()
                assert request('/api/gym/vision')[0] == 200
                assert time.monotonic()-begin < 2
                assert pending.result()[0] == 200
            # A fatal decoder error is isolated to the child, then recoverable.
            code,_ = request('/api/gym/vision/frame',b'\xff\xd8'+b'x'*30,headers)
            assert code == 503
            assert request('/api/gym/vision')[1]['state'] == 'error'
            assert request('/api/gym/vision/start',b'')[0] == 200
            ready()
            assert detect()[0] == 200
            worker = int(child_file.read_text().strip())
            assert all(path.suffix in ('.db','.log') or path.name.startswith('.lock') for path in Path(directory).iterdir()), 'camera frame persisted'
        finally:
            process.terminate()
            process.communicate(timeout=5)
            if worker is not None:
                try:
                    os.kill(worker,0)
                except ProcessLookupError:
                    pass
                else:
                    raise AssertionError('detector child survived manager shutdown')
    print('Gym camera API: auth/origin/bounds, large JPEGs, resident worker/memory, responsiveness, crash/restart/cleanup passed')


if __name__ == '__main__':
    main()
