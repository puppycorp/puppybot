#!/usr/bin/env python3
"""Disabled single-arm GPU/disk monitor for the hybrid simulator diagnostic."""
import importlib.util
import json
import math
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
OUTER_SECONDS = 1500
WORKER_SECONDS = 1350


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


hybrid = load('hybrid_monitor_runner', HERE / 'run.py')
telemetry = load('hybrid_gpu_telemetry', ROOT / 'flex/tests/monitored-visual-v4-smoke.py')


def require_disk(gib):
    if shutil.disk_usage(hybrid.P).free < gib * telemetry.GIB:
        raise RuntimeError(f'free disk below {gib} GiB')


def sample_disk(stream, phase, gib):
    free = shutil.disk_usage(hybrid.P).free
    row = {'phase': phase, 'monotonicSeconds': time.monotonic(), 'freeBytes': free}
    stream.write(json.dumps(row, sort_keys=True) + '\n'); stream.flush()
    if type(free) is not int or free < gib * telemetry.GIB:
        raise RuntimeError(f'free disk below {gib} GiB or unavailable')


def baseline(log):
    first = None; consecutive = 0
    while True:
        row = telemetry.sample(log, 'baseline')
        if first is None: first = row['monotonicSeconds']
        if row['freeBytes'] < 6 * telemetry.GIB: raise RuntimeError('baseline free VRAM below 6 GiB')
        consecutive = consecutive + 1 if row['busyPercent'] > 10 else 0
        if consecutive >= 5: raise RuntimeError('GPU busy above 10% for five consecutive samples')
        remaining = 30 - (row['monotonicSeconds'] - first)
        if remaining <= 0: return
        time.sleep(min(1, remaining))


def verify_logs(output):
    def rows(name):
        values = [json.loads(line) for line in (Path(output) / name).read_text().splitlines()]
        previous = -1.0
        for row in values:
            tick = row.get('monotonicSeconds')
            if type(tick) not in (int, float) or not math.isfinite(tick) or tick <= previous:
                raise ValueError('invalid monitor timestamp')
            previous = tick
        return values
    gpu = rows('telemetry.jsonl'); disk = rows('disk.jsonl')
    base = [r for r in gpu if r.get('phase') == 'baseline']
    active = [r for r in gpu if r.get('phase') == 'hybrid']
    if (len(base) < 2 or not active or [r.get('phase') for r in gpu] !=
            ['baseline'] * len(base) + ['hybrid'] * len(active) + ['after-hybrid'] or
            base[-1]['monotonicSeconds'] - base[0]['monotonicSeconds'] < 30 or
            any(b['monotonicSeconds'] - a['monotonicSeconds'] > 2.5 for a, b in zip(gpu, gpu[1:]))):
        raise ValueError('GPU baseline or active telemetry incomplete')
    consecutive = 0
    for row in gpu:
        if (any(type(row.get(k)) is not int for k in ('busyPercent', 'totalBytes', 'usedBytes', 'freeBytes')) or
                not 0 <= row['busyPercent'] <= 100 or row['totalBytes'] <= 0 or
                not 0 <= row['usedBytes'] <= row['totalBytes'] or row['freeBytes'] != row['totalBytes'] - row['usedBytes'] or
                row['freeBytes'] < (6 if row['phase'] == 'baseline' else 2) * telemetry.GIB):
            raise ValueError('invalid GPU telemetry or free memory')
        if row['phase'] == 'baseline':
            consecutive = consecutive + 1 if row['busyPercent'] > 10 else 0
            if consecutive >= 5: raise ValueError('GPU baseline busy guard exceeded')
    if ([r.get('phase') for r in disk] != ['pre-baseline', 'post-baseline'] +
            ['hybrid'] * len(active) + ['after-hybrid'] or
            disk[0]['monotonicSeconds'] > base[0]['monotonicSeconds'] or
            disk[1]['monotonicSeconds'] < base[-1]['monotonicSeconds'] or
            disk[1]['monotonicSeconds'] > active[0]['monotonicSeconds'] or
            disk[-1]['monotonicSeconds'] < gpu[-1]['monotonicSeconds']):
        raise ValueError('disk telemetry incomplete or out of order')
    for row in disk:
        floor = 36 if row['phase'] in ('pre-baseline', 'post-baseline') else 34
        if type(row.get('freeBytes')) is not int or row['freeBytes'] < floor * telemetry.GIB:
            raise ValueError('disk telemetry below guard')
    for index, row in enumerate(active):
        disk_tick = disk[index + 2]['monotonicSeconds']
        next_gpu = gpu[len(base) + index + 1]['monotonicSeconds']
        if not row['monotonicSeconds'] <= disk_tick <= next_gpu:
            raise ValueError('GPU and disk samples are not paired in order')


def worker_command(arm):
    code = ('import importlib.util,sys;'
            's=importlib.util.spec_from_file_location("hybrid",sys.argv[1]);'
            'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.run(sys.argv[2])')
    return [sys.executable, '-I', '-c', code, str(HERE / 'run.py'), arm]


def _worker(output, arm):
    output = Path(output)
    with (output / 'telemetry.jsonl').open('x') as log, (output / 'disk.jsonl').open('x') as disk:
        sample_disk(disk, 'pre-baseline', 36); baseline(log); sample_disk(disk, 'post-baseline', 36)
        with (output / 'worker.log').open('x') as child_log:
            process = subprocess.Popen(worker_command(arm), cwd=ROOT, stdout=child_log, stderr=subprocess.STDOUT)
            # If pidfd_open fails, the enclosing subreaper still cleans the worker tree.
            pidfd = os.pidfd_open(process.pid)
            deadline = time.monotonic() + WORKER_SECONDS
            reason = None
            try:
                while True:
                    try:
                        row = telemetry.sample(log, 'hybrid')
                        sample_disk(disk, 'hybrid', 34)
                        if row['freeBytes'] < 2 * telemetry.GIB: reason = 'free VRAM below 2 GiB'
                    except (OSError, RuntimeError, ValueError) as error:
                        reason = str(error)
                    if time.monotonic() >= deadline: reason = reason or 'hybrid worker deadline exceeded'
                    if reason: break
                    if process.poll() is not None: break
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
            if process.returncode != 0: raise RuntimeError(f'hybrid worker exited {process.returncode}')
            if telemetry.sample(log, 'after-hybrid')['freeBytes'] < 2 * telemetry.GIB:
                raise RuntimeError('free VRAM below 2 GiB after hybrid trial')
            sample_disk(disk, 'after-hybrid', 34)


def monitor_worker(output, arm):
    try: _worker(output, arm)
    except BaseException as error:
        hybrid.write_new(Path(output) / 'monitor-result.json', {'status': 'failed', 'reason': str(error)})
        raise
    hybrid.write_new(Path(output) / 'monitor-result.json', {'status': 'passed'})


def launch(arm):
    """Dedicated standalone process only; the outer supervisor adopts descendants."""
    hybrid.guard.require_dedicated_process()
    if arm not in ('control', 'treatment'): raise ValueError('expected control or treatment')
    require_disk(36)
    output = hybrid.P / f'hybrid-physical-eval-monitored-v1-{arm}'
    trial = hybrid.P / f'hybrid-physical-eval-v1-{arm}'
    for path in (output, trial):
        if path.exists() or path.is_symlink(): raise FileExistsError(f'output exists: {path}')
    source = {str(path): hybrid.hidden.sha(path) for path in
              (Path(__file__), ROOT / 'flex/tests/monitored-visual-v4-smoke.py',
               ROOT / 'flex/tests/run-physical-hidden-trial.py', Path(sys.executable).resolve())}
    trial_pins = hybrid.pins(arm)
    output.mkdir(); outer = output / 'outer-monitor'; outer.mkdir()
    code = ('import importlib.util,sys;'
            's=importlib.util.spec_from_file_location("monitor",sys.argv[1]);'
            'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.monitor_worker(sys.argv[2],sys.argv[3])')
    command = [sys.executable, '-I', '-c', code, str(Path(__file__).resolve()), str(output), arm]
    env = {'PATH': '/usr/bin:/bin', 'HOME': str(Path.home()), 'SDL_VIDEODRIVER': 'offscreen',
           'LD_LIBRARY_PATH': str(ROOT / 'build/flex/rocm-runtime')}
    hybrid.write_new(output / 'launch.json', {'arm': arm, 'command': command, 'environment': env,
                     'wallSeconds': OUTER_SECONDS, 'sourcePins': source, 'trialPins': trial_pins})
    status = hybrid.hidden.supervise(command, outer, env, OUTER_SECONDS)
    if (type(status.get('clientExit')) is not int or status['clientExit'] != 0 or status.get('signal') is not None or
            status.get('timedOut') is not False or status.get('remainingWorkersTerminated') is not False or
            type(status.get('processGroup')) is not int or status['processGroup'] <= 0):
        raise RuntimeError('hybrid resource monitor failed; retained evidence is censored')
    if any(hybrid.hidden.sha(Path(path)) != digest for path, digest in source.items()) or hybrid.pins(arm) != trial_pins:
        raise RuntimeError('monitor or trial inputs changed')
    result = json.loads((output / 'monitor-result.json').read_text())
    outcome = json.loads((trial / 'outcome.json').read_text())
    trial_launch = json.loads((trial / 'launch.json').read_text())
    audit_status = json.loads((trial / 'audit-monitor/supervisor-result.json').read_text())
    audit_log = json.loads((trial / 'audit-monitor/client.log').read_text())
    if (result.get('status') != 'passed' or outcome.get('status') != 'diagnostic_only' or
            trial_launch.get('arm') != arm or audit_log != outcome or
            trial_launch.get('sourcePins') != trial_pins or
            trial_launch.get('weightsSHA256') != trial_pins[str(hybrid.PACKAGE / arm / 'weights.bin')] or
            trial_launch.get('policySHA256') != trial_pins[str(hybrid.PACKAGE / arm / 'policy')] or
            type(audit_status.get('clientExit')) is not int or audit_status['clientExit'] != 0 or
            audit_status.get('signal') is not None or audit_status.get('timedOut') is not False or
            audit_status.get('remainingWorkersTerminated') is not False or
            type(audit_status.get('processGroup')) is not int or audit_status['processGroup'] <= 0):
        raise RuntimeError('hybrid evidence incomplete')
    verify_logs(output)
    require_disk(32)
    hybrid.write_new(output / 'completion.json', {'status': 'diagnostic_only', 'arm': arm,
                     'outcomeSHA256': hybrid.hidden.sha(trial / 'outcome.json'),
                     'telemetrySHA256': hybrid.hidden.sha(output / 'telemetry.jsonl'),
                     'diskSHA256': hybrid.hidden.sha(output / 'disk.jsonl'),
                     'scope': 'simulator-only diagnostic; not actor attestation or hardware qualification'})
    return outcome


if __name__ == '__main__':
    raise SystemExit('Disabled pending independent review and scheduling; no GPU launch authorized.')
