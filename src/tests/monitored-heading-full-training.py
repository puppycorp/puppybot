#!/usr/bin/env python3
"""Disabled telemetry wrapper around matched full heading training."""
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
MONITORED = P / 'heading-full-training-monitored-v1'
RUNNER = ROOT / 'datasets/visual-control/chase-v1/levels/run-heading-training.py'
RECEIPT = ROOT / 'datasets/visual-control/chase-v1/levels/heading-full-training-receipt.py'
OUTER_SECONDS = 15000
TRAINING_SECONDS = 14400
SNAPSHOT_SECONDS = 1800


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


telemetry = load('visual_gpu_monitor', ROOT / 'flex/tests/monitored-visual-v4-smoke.py')


def require_disk():
    if shutil.disk_usage(P).free < 34 * telemetry.GIB:
        raise RuntimeError('free disk below 34 GiB including 2 GiB headroom')


def sample_disk(stream, phase):
    row = {'phase': phase, 'monotonicSeconds': time.monotonic(), 'unixSeconds': time.time()}
    try:
        row['freeBytes'] = shutil.disk_usage(P).free
        if type(row['freeBytes']) is not int or row['freeBytes'] < 0:
            raise ValueError('invalid disk free bytes')
    except (OSError, ValueError) as exc:
        row['error'] = str(exc)
        stream.write(json.dumps(row, sort_keys=True) + '\n'); stream.flush()
        raise RuntimeError('disk telemetry unavailable') from exc
    stream.write(json.dumps(row, sort_keys=True) + '\n'); stream.flush()
    if row['freeBytes'] < 34 * telemetry.GIB:
        raise RuntimeError('free disk below 34 GiB including 2 GiB headroom')
    return row


def baseline(log):
    first = None; consecutive = 0
    while True:
        row = telemetry.sample(log, 'baseline')
        if first is None: first = row['monotonicSeconds']
        if row['freeBytes'] < 6 * telemetry.GIB:
            raise RuntimeError('baseline free VRAM below 6 GiB')
        consecutive = consecutive + 1 if row['busyPercent'] > 10 else 0
        if consecutive >= 5:
            raise RuntimeError('GPU busy above 10% for five consecutive samples')
        remaining = 30 - (row['monotonicSeconds'] - first)
        if remaining <= 0: return
        time.sleep(min(1, remaining))


def require_training_inputs():
    if not (P / 'search-dagger-heading/pair-ready.json').is_file():
        raise ValueError('paired overlay receipt is missing')
    if not (P / 'heading-full-collection-monitored-v1/completion.json').is_file():
        raise ValueError('monitored collection receipt is missing')
    path = P / 'search-dagger-heading/models'
    if path.exists() or path.is_symlink():
        raise FileExistsError(f'training output already exists: {path}')


def _monitor_worker(output):
    output = Path(output)
    with (output / 'telemetry.jsonl').open('x') as log, (output / 'disk.jsonl').open('x') as disk:
        require_disk()
        sample_disk(disk, 'pre-baseline')
        baseline(log)
        require_disk()
        sample_disk(disk, 'post-baseline')
        command = [sys.executable, '-I', str(RUNNER)]
        with (output / 'worker-invocation.json').open('x') as stream:
            json.dump({'argv': command, 'cwd': str(ROOT)}, stream, indent=2); stream.write('\n')
        with (output / 'training-worker.log').open('x') as child_log:
            process = subprocess.Popen(command, cwd=ROOT, stdout=child_log, stderr=subprocess.STDOUT)
            pidfd = os.pidfd_open(process.pid)
            deadline = time.monotonic() + TRAINING_SECONDS
            reason = None
            try:
                while True:
                    try:
                        row = telemetry.sample(log, 'training')
                        if row['freeBytes'] < 2 * telemetry.GIB:
                            reason = 'free VRAM below 2 GiB'
                        sample_disk(disk, 'training')
                    except RuntimeError as exc:
                        reason = str(exc)
                    if time.monotonic() >= deadline:
                        reason = reason or 'training worker deadline exceeded'
                    if reason:
                        break
                    if process.poll() is not None:
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
                raise RuntimeError(f'training worker exited {process.returncode}')
            final = telemetry.sample(log, 'after-training')
            if final['freeBytes'] < 2 * telemetry.GIB:
                raise RuntimeError('free VRAM below 2 GiB after training')
            sample_disk(disk, 'after-training')


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
    require_training_inputs()
    output = Path(output).absolute()
    if output != MONITORED:
        raise ValueError(f'monitored training output must be {MONITORED}')
    verifier = load('training_preflight_receipt', RECEIPT)
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
    (output / 'launch.json').write_text(json.dumps({'command': command, 'environment': env,
                                                    'wallSeconds': OUTER_SECONDS, 'sourcePins': frozen}, indent=2) + '\n')
    status = hidden.supervise(command, monitor, env, OUTER_SECONDS)
    if status['signal'] is not None or status['timedOut'] or status['clientExit'] != 0 or status['remainingWorkersTerminated']:
        raise RuntimeError('monitored full training failed; partial outputs retained')
    result = json.loads((output / 'monitor-result.json').read_text())
    if result.get('status') != 'passed':
        raise RuntimeError('monitored full training evidence did not pass')
    checked = snapshot_evidence()
    if any(checked.get(name) != value for name, value in frozen.items()):
        raise RuntimeError('monitoring source changed during full training')
    free_before_receipt = shutil.disk_usage(P).free
    if free_before_receipt < 32 * telemetry.GIB:
        raise RuntimeError('free disk below 32 GiB before completion receipt')
    receipt = {'status': 'passed', 'hashes': checked,
               'freeBytesBeforeReceipt': free_before_receipt,
               'scope': 'monitored matched training only; no held-out or physical qualification'}
    with (output / 'completion.json').open('x') as stream:
        stream.write(json.dumps(receipt, indent=2, sort_keys=True) + '\n')


if __name__ == '__main__':
    raise SystemExit('Disabled pending independent review; no GPU launch authorized.')
