#!/usr/bin/env python3
"""Lock and supervise the isolated fault-diagnostic CPU build."""
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


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


base = load('fault_build_supervisor_base', ROOT / 'experiments/physical-search-fallback-build-supervisor-v1/supervisor.py')
builder = load('fault_real_peer_builder', HERE / 'build.py')
P = builder.P
BUILD = P / 'sim-fault-real-peer-build-v1'
MONITOR = P / 'sim-fault-real-peer-build-monitor-v1'


def sources():
    pins = base.sources(); builder.inputs()
    paths = (Path(__file__), HERE / 'build.py', HERE / 'probe.flex',
             ROOT / 'experiments/contact-stop-io-failsafe-v1/transform.py',
             ROOT / 'experiments/contact-stop-trial-v1/build.py',
             ROOT / 'experiments/physical-dock-confirm-trial-v1/run.py', Path(sys.executable).resolve())
    pins.update({str(path): builder.sha(path) for path in paths})
    return pins


def command():
    code = ('import importlib.util,sys;s=importlib.util.spec_from_file_location("b",sys.argv[1]);'
            'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.worker()')
    return [str(base.NICE), '-n', '15', str(base.IONICE), '-c', '3', sys.executable, '-I', '-c', code, str(Path(__file__).resolve())]


def worker():
    nice = os.getpriority(os.PRIO_PROCESS, 0)
    io = subprocess.run([str(base.IONICE), '-p', str(os.getpid())], capture_output=True, text=True, timeout=5, check=True).stdout.strip()
    if nice < 15 or io != 'idle': raise ValueError('low priority not applied')
    pins = sources(); report = builder.build(BUILD)
    if builder.verify(BUILD) != report or sources() != pins: raise ValueError('built inputs changed')
    base.write_new(MONITOR / 'worker-result.json', {'status': 'isolated_build_only', 'sourcePins': pins,
        'buildSHA256': builder.sha(BUILD / 'build.json'), 'cpuNice': nice, 'ioClass': io})


def launch():
    base.guard.require_dedicated_process(); priority = base.low_priority()
    if min(shutil.disk_usage(path).free for path in (ROOT, Path.home(), P)) < 36 * base.GIB:
        raise ValueError('free disk below 36 GiB')
    for path in (BUILD, MONITOR):
        if path.exists() or path.is_symlink(): raise FileExistsError('preserve existing output')
    with base.LOCK.open('r+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for path in (BUILD, MONITOR):
            if path.exists() or path.is_symlink(): raise FileExistsError('preserve existing output')
        if min(shutil.disk_usage(path).free for path in (ROOT, Path.home(), P)) < 36 * base.GIB:
            raise ValueError('free disk below 36 GiB')
        pins = sources(); env = {'PATH': '/usr/bin:/bin', 'HOME': str(Path.home()),
                                 'SDL_VIDEODRIVER': 'offscreen', 'LD_LIBRARY_PATH': str(ROOT / 'build/flex/rocm-runtime')}
        MONITOR.mkdir(); base.write_new(MONITOR / 'launch.json', {'command': command(), 'environment': env,
            'wallSeconds': base.WALL_SECONDS, 'sourcePins': pins, 'supervisorPriority': priority})
        try:
            status = base.hidden.supervise(command(), MONITOR, env, base.WALL_SECONDS)
            if not base.clean(status) or json.loads((MONITOR / 'supervisor-result.json').read_text()) != status:
                raise ValueError('unclean build supervisor')
            result = json.loads((MONITOR / 'worker-result.json').read_text()); builder.verify(BUILD)
            if (sources() != pins or result.get('sourcePins') != pins or result.get('status') != 'isolated_build_only' or
                    result.get('cpuNice', 0) < 15 or result.get('ioClass') != 'idle' or
                    result.get('buildSHA256') != builder.sha(BUILD / 'build.json')):
                raise ValueError('build receipt differs')
            if min(shutil.disk_usage(path).free for path in (ROOT, Path.home(), P)) < 32 * base.GIB:
                raise ValueError('final disk floor')
            base.write_new(MONITOR / 'result.json', {'status': 'isolated_build_only', 'supervisorStatus': status,
                           'workerSHA256': builder.sha(MONITOR / 'worker-result.json')})
            return 0
        except BaseException as error:
            base.write_new(MONITOR / 'result.json', {'status': 'failed', 'reason': str(error)})
            raise


if __name__ == '__main__':
    raise SystemExit('Disabled pending independent review and scheduling.')
