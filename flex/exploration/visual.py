"""YOLO features anchored only by measured stereo points and own calibration."""
import atexit
import json
import os
from pathlib import Path
import subprocess
import socket

import numpy as np

from policy import sha256

VISUAL_NAMES = tuple(f'yolo_channel_{i}' for i in range(128)) + ('visual_observed_fraction', 'visual_age')


class Encoder:
    def __init__(self, directory, cache, use_service=True):
        self.directory, self.cache = Path(directory), Path(cache)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.manifest = json.loads((self.directory/'receipt.json').read_text())
        for name, digest in [('encoder', self.manifest['binarySha256']), ('weights.bin', self.manifest['weightsSha256']),
                             ('model.pup', self.manifest['modelSha256'])]:
            assert sha256(self.directory/name) == digest, name
        self.kernel = Path(os.environ.get('PUPPYBOT_ENCODER_KERNEL', str(self.directory/'kernels')))
        for name, digest in self.manifest['kernels'].items():
            assert sha256(self.kernel/name) == digest, name
        self.service = os.environ.get('PUPPYBOT_ENCODER_SOCKET') if use_service else None
        self.backend = os.environ.get('PUPPYBOT_ENCODER_BACKEND', 'cuda')
        self.worker = self.channel = self.log = None
        atexit.register(self.close)

    def close(self):
        if self.channel is not None:
            self.channel.close()
            self.channel = None
        if self.worker is not None:
            try:
                self.worker.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.worker.kill()
                self.worker.wait(timeout=3)
            self.worker = None
        if self.log is not None:
            self.log.close()
            self.log = None

    def execute(self, image, temporary):
        if self.channel is None:
            self.channel, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
            self.channel.settimeout(12)
            self.log = (self.cache/f'worker-{os.getpid()}.log').open('wb')
            self.worker = subprocess.Popen([str(self.directory/'encoder'), '--model', str(self.directory/'model.json'),
                '--kernel', str(self.kernel), '--backend', self.backend,
                '--worker-fd', str(child.fileno())], pass_fds=(child.fileno(),), stdout=self.log, stderr=self.log)
            child.close()
            ready = json.loads(self.channel.recv(4096))
            assert ready['shape'] == self.manifest['outputShape']
        self.channel.sendall(os.fsencode(image.resolve())+b'\0'+os.fsencode(temporary.resolve())+b'\0')
        return json.loads(self.channel.recv(4096))

    def cache_key(self, digest):
        return digest+'-'+self.manifest['binarySha256']+'-'+self.manifest['weightsSha256']+'-'+self.backend

    def encode(self, frame):
        image = Path(frame['rgb'])
        digest = sha256(image)
        key = self.cache_key(digest)
        path = self.cache/(key+'.f32')
        if not path.exists():
            temporary = path.with_suffix(f'.{os.getpid()}.tmp')
            if self.service:
                with socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET) as client:
                    client.settimeout(12)
                    client.connect(self.service)
                    client.sendall(json.dumps(dict(rgb=str(image.resolve()), modelSha256=self.manifest['modelSha256'],
                        weightsSha256=self.manifest['weightsSha256'], backend=self.backend)).encode())
                    response = json.loads(client.recv(8192))
                assert response['modelSha256'] == self.manifest['modelSha256']
                assert response['weightsSha256'] == self.manifest['weightsSha256'] and response['backend'] == self.backend
                temporary.write_bytes(Path(response['path']).read_bytes())
            else:
                response = self.execute(image, temporary)
            assert response['shape'] == self.manifest['outputShape']
            path.with_suffix('.json').write_text(json.dumps(response)+'\n')
            temporary.replace(path)
        values = np.fromfile(path, dtype='<f4')
        shape = self.manifest['outputShape'][1:]
        assert values.size == np.prod(shape) and np.isfinite(values).all(), path
        return values.reshape(shape), digest


class VisualMemory:
    def __init__(self, path=None):
        self.path = Path(path) if path else None
        self.values = np.zeros((200, 200, 128), np.float32)
        self.stamps = np.full((200, 200), -1, np.int64)
        if self.path and self.path.exists():
            with np.load(self.path) as saved:
                self.values[:] = saved['values']
                self.stamps[:] = saved['stamps']

    def update(self, request, points, encoder):
        pose = np.asarray(request['pose'])
        distance = np.linalg.norm(points[:, :2]-pose[:2], axis=1)
        points = points[(distance > .12) & (distance < 1.3) & (points[:, 2] > -.025) & (points[:, 2] < .45)]
        cells = np.floor((points[:, :2]+10)/.1).astype(int)
        valid = ((cells >= 0) & (cells < 200)).all(axis=1)
        points, cells = points[valid], cells[valid]
        receipts = []
        for frame in request['frames']:
            image, digest = encoder.encode(frame)
            calibration = np.asarray(frame['calibration']).reshape(4, 3)
            axes = np.column_stack((calibration[2], calibration[3], calibration[1]))
            camera = (points-calibration[0]) @ axes
            depth = np.maximum(camera[:, 2], .001)
            u = 415.6921938*camera[:, 0]/depth+320
            v = 415.6921938*camera[:, 1]/depth+240
            valid = (camera[:, 2] > .01) & (u >= 0) & (u < 640) & (v >= 0) & (v < 480)
            indices = cells[valid, 1]*200+cells[valid, 0]
            sample = image[:, ((v[valid]+80)*image.shape[1]/640).astype(int),
                           (u[valid]*image.shape[2]/640).astype(int)].T
            unique, inverse, counts = np.unique(indices, return_inverse=True, return_counts=True)
            pooled = np.zeros((len(unique), 128), np.float32)
            np.add.at(pooled, inverse, sample)
            pooled /= counts[:, None]
            pooled /= np.maximum(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-6)
            self.values.reshape(-1, 128)[unique] = pooled
            self.stamps.ravel()[unique] = request['frameId']
            receipts.append(dict(frameId=frame['frameId'], rgbSha256=digest, projectedPoints=len(indices), cells=len(unique)))
        if self.path:
            np.savez_compressed(self.path, values=self.values, stamps=self.stamps)
        return receipts

    def features(self, candidates, step):
        rows = []
        for candidate in candidates:
            col, row = np.floor((np.asarray(candidate[1][:2])+10)/.1).astype(int)
            values = self.values[max(0, row-3):min(200, row+4), max(0, col-3):min(200, col+4)]
            stamps = self.stamps[max(0, row-3):min(200, row+4), max(0, col-3):min(200, col+4)]
            seen = stamps >= 0
            pooled = values[seen].mean(0) if seen.any() else np.zeros(128, np.float32)
            age = min(float((step-stamps[seen]).mean())/50000, 1.) if seen.any() else 1.
            rows.append(np.r_[pooled, seen.mean(), age])
        return np.asarray(rows, np.float32).reshape(-1, len(VISUAL_NAMES))
