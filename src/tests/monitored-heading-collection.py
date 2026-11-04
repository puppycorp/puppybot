#!/usr/bin/env python3
"""Disabled telemetry wrapper around the eight-shard heading collection."""
import importlib.util
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
P = ROOT / 'build/flex/sim/levels-v2/pitch82'
MONITORED = P / 'heading-full-collection-monitored-v1'
COLLECTOR = ROOT / 'datasets/visual-control/chase-v1/levels/run-heading-rollin.py'
RECEIPT = ROOT / 'datasets/visual-control/chase-v1/levels/heading-collection-receipt.py'
OUTER_SECONDS = 33000
COLLECTION_SECONDS = 32400
SNAPSHOT_SECONDS = 600


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


telemetry = load('visual_gpu_monitor', ROOT / 'flex/tests/monitored-visual-v4-smoke.py')


def require_disk():
    if shutil.disk_usage(P).free < 40 * telemetry.GIB:
        raise RuntimeError('free disk below 40 GiB')


def require_collection_inputs():
    if not (P / 'heading-rollin-full-catalogs/catalogs.json').is_file():
        raise ValueError('prepared full collection catalogs are missing')
    if not (P / 'heading-trainer-pilot-monitored-v1/completion.json').is_file():
        raise ValueError('monitored trainer pilot completion is missing')
    path = P / 'search-dagger-heading'
    if path.exists() or path.is_symlink():
        raise FileExistsError(f'full collection output already exists: {path}')


def _monitor_worker(output):
    output = Path(output)
    with (output / 'telemetry.jsonl').open('x') as log:
        require_disk()
        telemetry.baseline(log)
        require_disk()
        command = [sys.executable, '-I', str(COLLECTOR), 'collect']
        with (output / 'collection-worker.log').open('x') as child_log:
            process = subprocess.Popen(command, cwd=ROOT, stdout=child_log, stderr=subprocess.STDOUT)
            pidfd = os.pidfd_open(process.pid)
            deadline = time.monotonic() + COLLECTION_SECONDS
            reason = None
            try:
                while process.poll() is None:
                    try:
                        row = telemetry.sample(log, 'full-collection')
                        if row['freeBytes'] < 2 * telemetry.GIB:
                            reason = 'free VRAM below 2 GiB'
                    except RuntimeError as exc:
                        reason = str(exc)
                    if time.monotonic() >= deadline:
                        reason = reason or 'full collection worker deadline exceeded'
                    if reason:
                        break
                    time.sleep(1)
            finally:
                try:
                    if process.poll() is None:
                        try:
                            signal.pidfd_send_signal(pidfd, signal.SIGTERM)
                        except ProcessLookupError:
                            pass
                        try:
                            process.wait(timeout=15)
                        except subprocess.TimeoutExpired:
                            try:
                                signal.pidfd_send_signal(pidfd, signal.SIGKILL)
                            except ProcessLookupError:
                                pass
                            process.wait()
                finally:
                    os.close(pidfd)
            if reason:
                raise RuntimeError(reason)
            if process.returncode != 0:
                raise RuntimeError(f'full collection exited {process.returncode}')
            final = telemetry.sample(log, 'after-collection')
            if final['freeBytes'] < 2 * telemetry.GIB:
                raise RuntimeError('free VRAM below 2 GiB after full collection')


def monitor_worker(output):
    try:
        _monitor_worker(output)
    except BaseException as exc:
        (Path(output) / 'monitor-result.json').write_text(json.dumps({'status': 'failed', 'reason': str(exc)}, indent=2) + '\n')
        raise
    (Path(output) / 'monitor-result.json').write_text(json.dumps({'status': 'passed'}, indent=2) + '\n')


def snapshot_evidence():
    code = ('import importlib.util,json,sys;'
            's=importlib.util.spec_from_file_location("receipt",sys.argv[1]);'
            'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);'
            'print(json.dumps(m.snapshot(),sort_keys=True))')
    result = subprocess.run([sys.executable, '-I', '-c', code, str(RECEIPT)], cwd=ROOT,
                            check=True, text=True, capture_output=True, timeout=SNAPSHOT_SECONDS)
    return json.loads(result.stdout)


def launch(output):
    """Dedicated standalone process only; do not use in a process with other children."""
    require_disk()
    require_collection_inputs()
    output = Path(output).absolute()
    if output != MONITORED:
        raise ValueError(f'monitored collection output must be {MONITORED}')
    verifier = load('collection_preflight_receipt', RECEIPT)
    frozen = verifier.source_pins()
    output.mkdir(parents=False, exist_ok=False)
    monitor = output / 'outer-monitor'; monitor.mkdir()
    hidden = load('hidden_supervisor', ROOT / 'flex/tests/run-physical-hidden-trial.py')
    code = ('import importlib.util,sys;'
            's=importlib.util.spec_from_file_location("monitored",sys.argv[1]);'
            'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);'
            'm.monitor_worker(sys.argv[2])')
    command = [sys.executable, '-I', '-c', code, str(Path(__file__).resolve()), str(output)]
    env = {'PATH': '/usr/bin:/bin', 'HOME': str(Path.home()), 'SDL_VIDEODRIVER': 'offscreen',
           'LD_LIBRARY_PATH': str(ROOT / 'build/flex/rocm-runtime')}
    (output / 'launch.json').write_text(json.dumps({'command': command, 'wallSeconds': OUTER_SECONDS,
                                                    'sourcePins': frozen}, indent=2) + '\n')
    status = hidden.supervise(command, monitor, env, OUTER_SECONDS)
    if status['signal'] is not None or status['timedOut'] or status['clientExit'] != 0 or status['remainingWorkersTerminated']:
        raise RuntimeError('monitored full collection failed; partial outputs retained')
    result = json.loads((output / 'monitor-result.json').read_text())
    if result.get('status') != 'passed':
        raise RuntimeError('monitored full collection evidence did not pass')
    checked = snapshot_evidence()
    if any(checked.get(name) != value for name, value in frozen.items()):
        raise RuntimeError('monitoring source changed during collection')
    receipt = {'status': 'passed', 'hashes': checked,
               'scope': 'monitored full training-layout collection; no policy qualification'}
    with (output / 'completion.json').open('x') as stream:
        stream.write(json.dumps(receipt, indent=2, sort_keys=True) + '\n')


if __name__ == '__main__':
    raise SystemExit('Disabled pending independent review; no GPU launch authorized.')
