#!/usr/bin/env python3
"""Disabled, independently bounded resource monitor for teacher comparison."""
import importlib.util
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
S = ROOT / 'datasets/visual-control/chase-v1/levels'
OUTER_SECONDS = 32600
WORKER_SECONDS = 32000
SNAPSHOT_SECONDS = 1800


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


frozen = load('teacher_frozen', S / 'heading-teacher-frozen-v1.py')
telemetry = load('teacher_gpu_telemetry', ROOT / 'flex/tests/monitored-visual-v4-smoke.py')


def disk_sample(stream, phase):
    row = {'phase': phase, 'monotonicSeconds': time.monotonic(), 'unixSeconds': time.time()}
    try:
        row['freeBytes'] = shutil.disk_usage(frozen.P).free
        if type(row['freeBytes']) is not int or row['freeBytes'] < 0: raise ValueError('invalid free bytes')
    except (OSError, ValueError) as error:
        row['error'] = str(error); stream.write(json.dumps(row) + '\n'); stream.flush()
        raise RuntimeError('disk telemetry unavailable') from error
    stream.write(json.dumps(row) + '\n'); stream.flush()
    if row['freeBytes'] < 34 * frozen.GIB: raise RuntimeError('free disk below 34 GiB')
    return row


def baseline(log):
    first = None; consecutive = 0
    while True:
        row = telemetry.sample(log, 'baseline')
        if first is None: first = row['monotonicSeconds']
        if row['freeBytes'] < 6 * frozen.GIB: raise RuntimeError('baseline free VRAM below 6 GiB')
        consecutive = consecutive + 1 if row['busyPercent'] > 10 else 0
        if consecutive >= 5: raise RuntimeError('GPU busy above 10% for five consecutive samples')
        remaining = 30 - (row['monotonicSeconds'] - first)
        if remaining <= 0: return
        time.sleep(min(1, remaining))


def _monitor_worker(output):
    output = Path(output)
    with (output / 'telemetry.jsonl').open('x') as log, (output / 'disk.jsonl').open('x') as disk:
        frozen.base.require_capacity(frozen.P, 38 * frozen.GIB)
        disk_sample(disk, 'pre-baseline'); baseline(log)
        frozen.base.require_capacity(frozen.P, 38 * frozen.GIB)
        disk_sample(disk, 'post-baseline')
        code = ('import importlib.util,sys;'
                's=importlib.util.spec_from_file_location("teacher_runner",sys.argv[1]);'
                'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.run()')
        command = [sys.executable, '-I', '-c', code, str(frozen.RUNNER)]
        with (output / 'worker-invocation.json').open('x') as stream:
            json.dump({'argv': command, 'cwd': str(ROOT)}, stream, indent=2); stream.write('\n')
        with (output / 'worker.log').open('x') as child_log:
            process = subprocess.Popen(command, cwd=ROOT, stdout=child_log, stderr=subprocess.STDOUT)
            pidfd = os.pidfd_open(process.pid); deadline = time.monotonic() + WORKER_SECONDS
            reason = None
            try:
                while True:
                    try:
                        row = telemetry.sample(log, 'selection')
                        if row['freeBytes'] < 2 * frozen.GIB: reason = 'free VRAM below 2 GiB'
                        disk_sample(disk, 'selection')
                    except RuntimeError as error: reason = str(error)
                    if time.monotonic() >= deadline: reason = reason or 'teacher worker deadline exceeded'
                    if reason or process.poll() is not None: break
                    time.sleep(1)
            finally:
                try:
                    if process.poll() is None:
                        try: signal.pidfd_send_signal(pidfd, signal.SIGTERM)
                        except ProcessLookupError: pass
                        try: process.wait(timeout=15)
                        except subprocess.TimeoutExpired:
                            try: signal.pidfd_send_signal(pidfd, signal.SIGKILL)
                            except ProcessLookupError: pass
                            process.wait()
                finally: os.close(pidfd)
            if reason: raise RuntimeError(reason)
            if process.returncode != 0: raise RuntimeError(f'teacher worker exited {process.returncode}')
            if telemetry.sample(log, 'after-selection')['freeBytes'] < 2 * frozen.GIB:
                raise RuntimeError('free VRAM below 2 GiB after teacher')
            disk_sample(disk, 'after-selection')


def monitor_worker(output):
    try: _monitor_worker(output)
    except BaseException as error:
        (Path(output) / 'monitor-result.json').write_text(json.dumps({'status': 'failed', 'reason': str(error)}) + '\n')
        raise
    (Path(output) / 'monitor-result.json').write_text(json.dumps({'status': 'passed'}) + '\n')


def bounded_json(code, path):
    env = {'PATH': '/usr/bin:/bin', 'HOME': str(Path.home()), 'SDL_VIDEODRIVER': 'offscreen',
           'LD_LIBRARY_PATH': str(ROOT / 'build/flex/rocm-runtime')}
    with tempfile.TemporaryDirectory(prefix='teacher-preflight-') as tmp:
        directory = Path(tmp)
        status = frozen.base.hidden.supervise([sys.executable, '-I', '-c', code, str(path)], directory, env,
                                               wall_seconds=SNAPSHOT_SECONDS)
        if status['signal'] is not None or status['timedOut'] or status['clientExit'] != 0 or status['remainingWorkersTerminated']:
            detail = (directory / 'client.log').read_text(errors='replace')[-2000:]
            raise RuntimeError(f'bounded teacher verification failed: {detail}')
        return json.loads((directory / 'client.log').read_text())


def verify_plan():
    code = ('import importlib.util,json,sys;'
            's=importlib.util.spec_from_file_location("teacher_frozen",sys.argv[1]);'
            'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);'
            'print(json.dumps(m.verify(),sort_keys=True))')
    return bounded_json(code, S / 'heading-teacher-frozen-v1.py')


def snapshot_evidence():
    code = ('import importlib.util,json,sys;'
            's=importlib.util.spec_from_file_location("teacher_receipt",sys.argv[1]);'
            'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);'
            'print(json.dumps(m.snapshot(),sort_keys=True))')
    return bounded_json(code, frozen.RECEIPT)


def launch(output):
    """Standalone-only: the outer subreaper must own this process's children."""
    output = Path(output).absolute()
    if output != frozen.MONITORED: raise ValueError('wrong teacher monitor destination')
    frozen.base.require_new_output(output); frozen.base.require_new_output(frozen.OUTPUT)
    frozen.base.require_capacity(frozen.P, 38 * frozen.GIB)
    plan = verify_plan()
    output.mkdir(parents=False, exist_ok=False)
    monitor = output / 'outer-monitor'; monitor.mkdir()
    hidden = load('teacher_outer_supervisor', ROOT / 'flex/tests/run-physical-hidden-trial.py')
    code = ('import importlib.util,sys;'
            's=importlib.util.spec_from_file_location("teacher_monitor",sys.argv[1]);'
            'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.monitor_worker(sys.argv[2])')
    command = [sys.executable, '-I', '-c', code, str(frozen.MONITOR), str(output)]
    env = {'PATH': '/usr/bin:/bin', 'HOME': str(Path.home()), 'SDL_VIDEODRIVER': 'offscreen',
           'LD_LIBRARY_PATH': str(ROOT / 'build/flex/rocm-runtime')}
    (output / 'launch.json').write_text(json.dumps({'command': command, 'environment': env,
        'wallSeconds': OUTER_SECONDS, 'sourcePins': plan['sourcePins']}, indent=2) + '\n')
    status = hidden.supervise(command, monitor, env, OUTER_SECONDS)
    if status['signal'] is not None or status['timedOut'] or status['clientExit'] != 0 or status['remainingWorkersTerminated']:
        raise RuntimeError('teacher monitor failed; partial output retained')
    if json.loads((output / 'monitor-result.json').read_text()).get('status') != 'passed':
        raise RuntimeError('teacher resource monitor failed')
    checked = snapshot_evidence()
    if frozen.pins() != plan['sourcePins']: raise RuntimeError('teacher source changed')
    free = shutil.disk_usage(frozen.P).free
    if free < 32 * frozen.GIB: raise RuntimeError('free disk below 32 GiB before completion')
    with (output / 'completion.json').open('x') as stream:
        json.dump({'status': 'complete_diagnostic', 'hashes': checked, 'freeBytesBeforeReceipt': free,
                   'scope': 'saved teacher comparison only; no physical or held-out qualification'}, stream, indent=2)
        stream.write('\n')


if __name__ == '__main__':
    raise SystemExit('Disabled pending independent review; no GPU launch authorized.')
