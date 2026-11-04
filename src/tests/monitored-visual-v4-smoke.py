#!/usr/bin/env python3
"""Disabled, separately supervised telemetry wrapper for the v4 smoke."""
import importlib.util
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEVICE = Path('/sys/class/drm/card1/device')
EXPECTED_PCI = '0000:03:00.0'
GIB = 1024**3
BASELINE_SECONDS = 30
OUTER_SECONDS = 300
SMOKE_SECONDS = 240
STOP_GRACE_SECONDS = 15


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def telemetry(device):
    if device.resolve(strict=True).name != EXPECTED_PCI:
        raise ValueError('GPU PCI identity changed')
    busy = int((device / 'gpu_busy_percent').read_text().strip())
    total = int((device / 'mem_info_vram_total').read_text().strip())
    used = int((device / 'mem_info_vram_used').read_text().strip())
    if not (0 <= busy <= 100 and 0 < total and 0 <= used <= total):
        raise ValueError('invalid GPU telemetry')
    return {'busyPercent': busy, 'totalBytes': total, 'usedBytes': used, 'freeBytes': total - used}


def sample(stream, phase, read=telemetry):
    row = {'phase': phase, 'monotonicSeconds': time.monotonic(), 'unixSeconds': time.time()}
    try:
        row.update(read(DEVICE))
    except (OSError, ValueError) as exc:
        row['error'] = str(exc)
        stream.write(json.dumps(row, sort_keys=True) + '\n'); stream.flush()
        raise RuntimeError('GPU telemetry unavailable') from exc
    stream.write(json.dumps(row, sort_keys=True) + '\n'); stream.flush()
    return row


def baseline(stream, read=telemetry, sleep=time.sleep, clock=time.monotonic):
    start = clock(); sustained = 0
    while True:
        row = sample(stream, 'baseline', read)
        if row['freeBytes'] < 6 * GIB:
            raise RuntimeError('baseline free VRAM below 6 GiB')
        sustained = sustained + 1 if row['busyPercent'] > 10 else 0
        if sustained >= 5:
            raise RuntimeError('GPU busy above 10% for five consecutive samples')
        remaining = BASELINE_SECONDS - (clock() - start)
        if remaining <= 0:
            return
        sleep(min(1, remaining))


def _monitor_worker(pilot, matrix, output):
    output = Path(output)
    with (output / 'telemetry.jsonl').open('x') as log:
        baseline(log)
        code = ('import importlib.util,sys;'
                's=importlib.util.spec_from_file_location("smoke",sys.argv[1]);'
                'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);'
                'm.run(sys.argv[2],sys.argv[3],sys.argv[4])')
        command = [sys.executable, '-I', '-c', code, str(ROOT / 'flex/tests/sim-visual-v4-smoke.py'),
                   str(pilot), str(matrix), str(output / 'smoke')]
        with (output / 'smoke-worker.log').open('x') as child_log:
            process = subprocess.Popen(command, cwd=ROOT, stdout=child_log, stderr=subprocess.STDOUT)
            # A pidfd guarantees an abort cannot hit a recycled process ID.
            pidfd = os.pidfd_open(process.pid)
            deadline = time.monotonic() + SMOKE_SECONDS
            reason = None
            try:
                while process.poll() is None:
                    try:
                        row = sample(log, 'smoke')
                        if row['freeBytes'] < 2 * GIB:
                            reason = 'free VRAM below 2 GiB'
                    except RuntimeError as exc:
                        reason = str(exc)
                    if time.monotonic() >= deadline:
                        reason = reason or 'smoke worker deadline exceeded'
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
                            process.wait(timeout=STOP_GRACE_SECONDS)
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
                raise RuntimeError(f'smoke worker exited {process.returncode}')
            final = sample(log, 'after-smoke')
            if final['freeBytes'] < 2 * GIB:
                raise RuntimeError('free VRAM below 2 GiB after smoke')


def monitor_worker(pilot, matrix, output):
    try:
        _monitor_worker(pilot, matrix, output)
    except BaseException as exc:
        (Path(output) / 'monitor-result.json').write_text(json.dumps({'status': 'failed', 'reason': str(exc)}, indent=2) + '\n')
        raise
    (Path(output) / 'monitor-result.json').write_text(json.dumps({'status': 'passed'}, indent=2) + '\n')


def launch(pilot, matrix, output):
    """Launch only after independent review; parent supervisor reaps descendants."""
    output = Path(output).absolute()
    output.mkdir(parents=False, exist_ok=False)
    monitor = output / 'outer-monitor'; monitor.mkdir()
    hidden = load('hidden_supervisor', ROOT / 'flex/tests/run-physical-hidden-trial.py')
    code = ('import importlib.util,sys;'
            's=importlib.util.spec_from_file_location("monitored",sys.argv[1]);'
            'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);'
            'm.monitor_worker(sys.argv[2],sys.argv[3],sys.argv[4])')
    command = [sys.executable, '-I', '-c', code, str(Path(__file__).resolve()),
               str(Path(pilot).absolute()), str(Path(matrix).absolute()), str(output)]
    env = {'PATH': '/usr/bin:/bin', 'HOME': str(Path.home()), 'SDL_VIDEODRIVER': 'offscreen',
           'LD_LIBRARY_PATH': str(ROOT / 'build/flex/rocm-runtime')}
    (output / 'launch.json').write_text(json.dumps({'command': command, 'wallSeconds': OUTER_SECONDS}, indent=2) + '\n')
    status = hidden.supervise(command, monitor, env, OUTER_SECONDS)
    if status['signal'] is not None or status['timedOut'] or status['clientExit'] != 0 or status['remainingWorkersTerminated']:
        raise RuntimeError('monitored smoke failed; partial outputs retained')
    result = json.loads((output / 'monitor-result.json').read_text())
    report = json.loads((output / 'smoke/report.json').read_text())
    if result.get('status') != 'passed' or report.get('status') != 'simulated_rendered_startup_observed':
        raise RuntimeError('monitored smoke evidence did not pass')


if __name__ == '__main__':
    raise SystemExit('Disabled pending independent review; no GPU launch authorized.')
