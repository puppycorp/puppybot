#!/usr/bin/env python3
"""Compare the existing virtual-agent protocol against a candidate simulator.

Usage: python3 -I flex/tests/virtual-agent-runtime-parity.py --check
       python3 -I flex/tests/virtual-agent-runtime-parity.py NEW_OUTPUT_DIR

Run only with the GPU otherwise idle. Each simulator receives the same frozen
scene, seed and action sequence. Compare every raw RGB frame and complete JSON
response; this is a focused protocol regression, not model or task validation.
"""
import hashlib
import ctypes
import importlib.util
import json
import os
import shutil
import signal
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[2]
BASE = PROJECT / 'build/flex/sim/levels-v2/pitch82'
SCENE = BASE / 'search-dagger-4workers/selection-L3/baseline-s0/0/7800000/scene'
BASELINE = PROJECT / 'build/flex/control/simulator'
CANDIDATE = Path('/tmp/puppybot-physical-bridge-sim')
ASSET = PROJECT / 'build/flex/sim/puppybot.bin'
ACTIONS = [(1, 0, 0, 0), (2, 0, 0, 10), (2, 0, 600, 10),
           (2, 500, 600, 10), (2, -500, -600, 10), (2, 0, 0, 10)]
supervisor_spec = importlib.util.spec_from_file_location('hybrid_supervisor', Path(__file__).with_name('run-physical-hybrid-trial.py'))
supervisor = importlib.util.module_from_spec(supervisor_spec)
supervisor_spec.loader.exec_module(supervisor)


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def read_exact(sock, size, deadline):
    chunks = []
    while size:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('virtual protocol exceeded wall-clock budget')
        sock.settimeout(remaining)
        block = sock.recv(size)
        if not block:
            raise EOFError('virtual protocol closed mid-frame')
        chunks.append(block)
        size -= len(block)
    return b''.join(chunks)


def execute(binary, case, environment, name, output):
    parent, child = socket.socketpair()
    env = os.environ.copy()
    env.pop('DISPLAY', None)
    env.pop('WAYLAND_DISPLAY', None)
    env['SDL_VIDEODRIVER'] = 'offscreen'
    args = [str(binary), '--hidden', '--case-file', str(case), '--environment', str(environment),
            '--steps', '1000000', '--bind', '127.0.0.1:0', '--agent-fd', str(child.fileno()),
            '--no-visual-odometry', '--camera-pitch', '82', '--seed', '7800000']
    frames = []
    deadline = time.monotonic() + 120
    with (output / f'{name}.log').open('wb') as log:
        process = subprocess.Popen(args, cwd=PROJECT, env=env, stdout=log, stderr=log,
                                   pass_fds=(child.fileno(),), start_new_session=True)
        child.close()
        try:
            for sequence, (command, steering, speed, hold) in enumerate(ACTIONS, 1):
                parent.settimeout(max(0.1, deadline - time.monotonic()))
                parent.sendall(struct.pack('<8q', command, sequence, steering, speed, hold, 0, 3, 0))
                header = struct.unpack('<4q', read_exact(parent, 32, deadline))
                size, rgb_size, returned_sequence, blocked = header
                if not 0 < size <= 65536 or rgb_size != 640 * 480 * 3 or returned_sequence != sequence or blocked not in (0, 1):
                    raise ValueError(f'{name}: malformed header {header}')
                state = read_exact(parent, size, deadline)
                image = read_exact(parent, rgb_size, deadline)
                frames.append({'sequence': sequence, 'blocked': blocked,
                               'state': json.loads(state), 'rgbSHA256': hashlib.sha256(image).hexdigest()})
            parent.sendall(struct.pack('<8q', 3, len(ACTIONS) + 1, 0, 0, 0, 0, 3, 0))
            if process.wait(timeout=max(0.1, deadline - time.monotonic())) != 0:
                raise RuntimeError(f'{name}: nonzero simulator exit; see {name}.log')
        finally:
            parent.close()
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait()
            (output / f'{name}.json').write_text(json.dumps(frames, indent=2) + '\n')
            if supervisor.cleanup_descendants():
                raise RuntimeError(f'{name}: leftover simulator workers were stopped')
    return frames


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    for binary in (BASELINE, CANDIDATE):
        if not os.access(binary, os.X_OK):
            raise ValueError(f'missing simulator binary: {binary}')
    case_data = json.loads((SCENE / 'case.json').read_text())
    if case_data.get('controller') != 'rgb-find-return':
        raise ValueError('reference scene is not a virtual find-return case')
    if sys.argv[1] == '--check':
        print(json.dumps({'status': 'ready', 'baselineSHA256': digest(BASELINE),
                          'candidateSHA256': digest(CANDIDATE), 'caseSHA256': digest(SCENE / 'case.json'),
                          'environmentSHA256': digest(SCENE / 'environment.bin'),
                          'note': 'preflight only; no GPU process started'}, indent=2))
        return
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), 'cannot supervise orphaned simulator workers')
    def interrupted(signum, _frame):
        raise InterruptedError(f'supervisor received signal {signum}')
    signal.signal(signal.SIGTERM, interrupted)
    output = Path(sys.argv[1]).resolve()
    output.mkdir(parents=False, exist_ok=False)
    inputs = output / 'inputs'
    inputs.mkdir()
    for source, target in ((BASELINE, 'baseline'), (CANDIDATE, 'candidate'),
                           (SCENE / 'case.json', 'case.json'), (SCENE / 'environment.bin', 'environment.bin')):
        shutil.copy2(source, inputs / target)
        if digest(source) != digest(inputs / target):
            raise ValueError(f'input snapshot changed: {source}')
    manifest = {name: digest(inputs / name) for name in ('baseline', 'candidate', 'case.json', 'environment.bin')}
    manifest['robotAssetSHA256'] = digest(ASSET)
    manifest['scope'] = 'virtual protocol, fixed scene and actions; host graphics/runtime libraries are not pinned'
    (output / 'inputs.json').write_text(json.dumps(manifest, indent=2) + '\n')
    left = execute(inputs / 'baseline', inputs / 'case.json', inputs / 'environment.bin', 'baseline', output)
    right = execute(inputs / 'candidate', inputs / 'case.json', inputs / 'environment.bin', 'candidate', output)
    if any(digest(inputs / name) != manifest[name] for name in ('baseline', 'candidate', 'case.json', 'environment.bin')) or digest(ASSET) != manifest['robotAssetSHA256']:
        raise ValueError('simulator, scene or robot asset changed during run')
    differences = [i + 1 for i, (a, b) in enumerate(zip(left, right)) if a != b]
    report = {'status': 'matched' if not differences else 'different', 'frames': len(ACTIONS),
              'differentSequences': differences, 'scope': manifest['scope']}
    (output / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))
    if differences:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
