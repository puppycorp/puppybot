#!/usr/bin/env python3
"""Disabled telemetry wrapper around the one-epoch matched trainer pilot."""
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
MONITORED = P / 'heading-trainer-pilot-monitored-v1'
TRAINER = ROOT / 'datasets/visual-control/chase-v1/levels/run-heading-trainer-pilot.py'
OUTER_SECONDS = 4200
PILOT_SECONDS = 4100


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


telemetry = load('visual_gpu_monitor', ROOT / 'flex/tests/monitored-visual-v4-smoke.py')


def require_disk():
    if shutil.disk_usage(P).free < 40 * telemetry.GIB:
        raise RuntimeError('free disk below 40 GiB')


def require_trainer_inputs():
    if not (P / 'search-dagger-heading-pilot/pilot-report.json').is_file():
        raise ValueError('completed roll-in pilot report is missing')
    if not (P / 'search-dagger-heading-trainer-build/inputs.json').is_file():
        raise ValueError('prepared trainer build receipt is missing')
    path = P / 'search-dagger-heading-trainer-pilot'
    if path.exists() or path.is_symlink():
        raise FileExistsError(f'trainer pilot output already exists: {path}')


def _monitor_worker(output):
    output = Path(output)
    with (output / 'telemetry.jsonl').open('x') as log:
        require_disk()
        telemetry.baseline(log)
        require_disk()
        command = [sys.executable, '-I', str(TRAINER)]
        with (output / 'trainer-worker.log').open('x') as child_log:
            process = subprocess.Popen(command, cwd=ROOT, stdout=child_log, stderr=subprocess.STDOUT)
            pidfd = os.pidfd_open(process.pid)
            deadline = time.monotonic() + PILOT_SECONDS
            reason = None
            try:
                while process.poll() is None:
                    try:
                        row = telemetry.sample(log, 'trainer-pilot')
                        if row['freeBytes'] < 2 * telemetry.GIB:
                            reason = 'free VRAM below 2 GiB'
                    except RuntimeError as exc:
                        reason = str(exc)
                    if time.monotonic() >= deadline:
                        reason = reason or 'trainer worker deadline exceeded'
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
                raise RuntimeError(f'trainer pilot exited {process.returncode}')
            final = telemetry.sample(log, 'after-trainer')
            if final['freeBytes'] < 2 * telemetry.GIB:
                raise RuntimeError('free VRAM below 2 GiB after trainer pilot')


def monitor_worker(output):
    try:
        _monitor_worker(output)
    except BaseException as exc:
        (Path(output) / 'monitor-result.json').write_text(json.dumps({'status': 'failed', 'reason': str(exc)}, indent=2) + '\n')
        raise
    (Path(output) / 'monitor-result.json').write_text(json.dumps({'status': 'passed'}, indent=2) + '\n')


def launch(output):
    """Dedicated standalone process only; do not use in a process with other children."""
    require_disk()
    require_trainer_inputs()
    output = Path(output).absolute()
    if output != MONITORED:
        raise ValueError(f'monitored trainer output must be {MONITORED}')
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
    (output / 'launch.json').write_text(json.dumps({'command': command, 'wallSeconds': OUTER_SECONDS}, indent=2) + '\n')
    status = hidden.supervise(command, monitor, env, OUTER_SECONDS)
    if status['signal'] is not None or status['timedOut'] or status['clientExit'] != 0 or status['remainingWorkersTerminated']:
        raise RuntimeError('monitored trainer pilot failed; partial outputs retained')
    result = json.loads((output / 'monitor-result.json').read_text())
    report = json.loads((P / 'search-dagger-heading-trainer-pilot/comparison.json').read_text())
    if result.get('status') != 'passed' or report.get('status') != 'passed' or report.get('differences') != []:
        raise RuntimeError('monitored trainer pilot evidence did not pass')
    trainer = load('verified_trainer_pilot', TRAINER)
    if trainer.verify_small_pilot(require_monitor=False) != report:
        raise RuntimeError('trainer pilot independent verification differs')
    paths = {'comparison': P / 'search-dagger-heading-trainer-pilot/comparison.json',
             'monitorResult': output / 'monitor-result.json', 'outerSupervisor': monitor / 'supervisor-result.json',
             'telemetry': output / 'telemetry.jsonl', 'monitorScript': Path(__file__).resolve()}
    receipt = {'status': 'passed', 'hashes': {key: trainer.base.sha(path) for key, path in paths.items()},
               'scope': 'monitored one-epoch trainer pilot completion, not physical or held-out qualification'}
    with (output / 'completion.json').open('x') as stream:
        stream.write(json.dumps(receipt, indent=2, sort_keys=True) + '\n')


if __name__ == '__main__':
    raise SystemExit('Disabled pending independent review; no GPU launch authorized.')
