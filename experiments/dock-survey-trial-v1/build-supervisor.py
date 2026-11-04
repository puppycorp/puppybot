#!/usr/bin/env python3
"""Low-priority, bounded CPU build supervisor; direct CLI remains disabled."""
import fcntl
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
P = ROOT / 'build/flex/sim/levels-v2/pitch82'
BUILD = P / 'dock-survey-diagnostic-build-v1'
MONITOR = P / 'dock-survey-diagnostic-build-cpu-monitor-v1'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


base = load('dock_build_supervisor_base', ROOT / 'experiments/physical-search-fallback-build-supervisor-v1/supervisor.py')
runner = load('dock_build_supervisor_runner', HERE / 'run.py')


def sources():
    result = base.sources(); archive = runner.builder.ARCHIVE
    paths = [Path(__file__), HERE / 'run.py', ROOT / 'experiments/dock-survey-diagnostic-v1/build.py',
             ROOT / 'experiments/dock-survey-diagnostic-v1/transform.py',
             ROOT / 'experiments/physical-dock-confirm-v1/build.py',
             ROOT / 'experiments/physical-dock-confirm-v1/transform.py',
             ROOT / 'experiments/physical-dock-confirm-trial-v1/run.py', archive / 'build.json',
             archive / 'client', archive / 'simulator']
    for folder in (archive / 'source', archive / 'build/flex/sim/library'):
        for directory, dirs, files in os.walk(folder, followlinks=False, onerror=lambda error: (_ for _ in ()).throw(error)):
            for name in dirs + files:
                if (Path(directory) / name).is_symlink(): raise ValueError('symlink in archive')
            for name in files:
                path = Path(directory) / name
                if path.suffix != '.pyc' and '__pycache__' not in path.parts: paths.append(path)
    result.update({str(path): base.sha(path) for path in paths})
    return result


def command():
    code = ('import importlib.util,sys;'
            's=importlib.util.spec_from_file_location("b",sys.argv[1]);'
            'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.worker()')
    return [str(base.NICE), '-n', '15', str(base.IONICE), '-c', '3', sys.executable, '-I', '-c', code, str(Path(__file__).resolve())]


def worker():
    cpu_nice = os.getpriority(os.PRIO_PROCESS, 0)
    io = subprocess.run([str(base.IONICE), '-p', str(os.getpid())], capture_output=True, text=True, timeout=5, check=True).stdout.strip()
    if cpu_nice < 15 or io != 'idle': raise RuntimeError('CPU or I/O priority not applied')
    pins = sources(); report = runner.builder.build(BUILD); verified = runner.check_build(BUILD)
    if report != verified or sources() != pins: raise ValueError('build source or receipt changed')
    base.write_new(MONITOR / 'worker-result.json', {'status': 'isolated_build_only', 'sourcePins': pins,
        'buildReceiptSHA256': base.sha(BUILD / 'build.json'), 'clientSHA256': base.sha(BUILD / 'client'),
        'simulatorSHA256': base.sha(BUILD / 'simulator'), 'cpuNice': cpu_nice, 'ioClass': io,
        'scope': 'CPU build consistency only; no rendered or physical validation'})


def launch():
    base.guard.require_dedicated_process(); priority = base.low_priority()
    if any(shutil.disk_usage(path).free < 36 * base.GIB for path in (ROOT, Path.home(), P)):
        raise ValueError('free disk below 36 GiB')
    for path in (BUILD, MONITOR):
        if path.exists() or path.is_symlink(): raise FileExistsError('output exists; preserve evidence')
    with base.LOCK.open('r+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for path in (BUILD, MONITOR):
            if path.exists() or path.is_symlink(): raise FileExistsError('output exists; preserve evidence')
        if any(shutil.disk_usage(path).free < 36 * base.GIB for path in (ROOT, Path.home(), P)):
            raise ValueError('free disk below 36 GiB')
        pins = sources(); env = {'PATH': '/usr/bin:/bin', 'HOME': str(Path.home()),
            'SDL_VIDEODRIVER': 'offscreen', 'LD_LIBRARY_PATH': str(ROOT / 'build/flex/rocm-runtime')}
        MONITOR.mkdir(); base.write_new(MONITOR / 'launch.json', {'command': command(), 'environment': env,
            'wallSeconds': base.WALL_SECONDS, 'build': str(BUILD), 'sourcePins': pins,
            'supervisorPriority': priority, 'scope': 'local CPU build invocation; advisory lock'})
        try: status = base.hidden.supervise(command(), MONITOR, env, base.WALL_SECONDS)
        except BaseException as error:
            base.write_new(MONITOR / 'result.json', {'status': 'failed', 'reason': str(error)})
            raise
        failure = None
        try:
            if not base.clean(status) or json.loads((MONITOR / 'supervisor-result.json').read_text()) != status:
                raise ValueError('unclean supervisor status')
            result = json.loads((MONITOR / 'worker-result.json').read_text()); report = runner.check_build(BUILD)
            if sources() != pins or result.get('sourcePins') != pins: raise ValueError('build inputs changed')
            if (result.get('status') != 'isolated_build_only' or type(result.get('cpuNice')) is not int or
                    result['cpuNice'] < 15 or result.get('ioClass') != 'idle' or
                    result.get('buildReceiptSHA256') != base.sha(BUILD / 'build.json') or
                    result.get('clientSHA256') != report['clientSHA256'] or
                    result.get('simulatorSHA256') != report['simulatorSHA256']):
                raise ValueError('build receipt differs')
            if any(shutil.disk_usage(path).free < 32 * base.GIB for path in (ROOT, Path.home(), P)):
                raise ValueError('free disk below final 32 GiB floor')
        except (OSError, ValueError, KeyError, TypeError) as error: failure = str(error)
        base.write_new(MONITOR / 'result.json', {'status': 'failed' if failure else 'isolated_build_only',
            'reason': failure, 'supervisorStatus': status, 'launchSHA256': base.sha(MONITOR / 'launch.json'),
            'workerSHA256': base.sha(MONITOR / 'worker-result.json') if (MONITOR / 'worker-result.json').is_file() else None,
            'scope': 'CPU build only; no rendered or physical validation'})
        return 1 if failure else 0


if __name__ == '__main__':
    raise SystemExit('Disabled pending independent review and scheduling.')
