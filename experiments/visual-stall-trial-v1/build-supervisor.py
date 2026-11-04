#!/usr/bin/env python3
"""Locked, low-priority, bounded CPU build; no simulator or GPU execution."""
import fcntl
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


base = load('visual_build_supervisor_base', ROOT / 'experiments/physical-search-fallback-build-supervisor-v1/supervisor.py')
build = load('visual_supervised_builder', HERE / 'build.py')
P = build.P
MONITOR = P / 'visual-stall-build-cpu-monitor-v1'


def sources():
    result = base.sources()
    paths = (Path(__file__), HERE / 'build.py', ROOT / 'experiments/l5-steering-hysteresis-v1/prepare.py',
             ROOT / 'experiments/contact-stop-v1/transform.py', ROOT / 'experiments/visual-exact-stall-v1/transform.py', build.VISUAL, build.CONTACT, build.ARCHIVE / 'build.json',
             build.ARCHIVE / 'control', build.COMPILER, Path(sys.executable).resolve())
    result.update({str(path): base.sha(path) for path in paths})
    # The archived source tree is verified by the pinned archive receipt.
    build.inputs()
    return result


def command():
    code = ('import importlib.util,sys;s=importlib.util.spec_from_file_location("b",sys.argv[1]);'
            'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.worker()')
    return [str(base.NICE), '-n', '15', str(base.IONICE), '-c', '3', sys.executable, '-I', '-c', code, str(Path(__file__).resolve())]


def worker():
    cpu_nice = os.getpriority(os.PRIO_PROCESS, 0)
    io = subprocess.run([str(base.IONICE), '-p', str(os.getpid())], capture_output=True, text=True, timeout=5, check=True).stdout.strip()
    if cpu_nice < 15 or io != 'idle': raise RuntimeError('low priority not applied')
    pins = sources(); report = build.build(build.BUILD)
    if build.verify(build.BUILD) != report or sources() != pins: raise ValueError('build changed')
    base.write_new(MONITOR / 'worker-result.json', {'status': 'isolated_build_only', 'sourcePins': pins,
        'buildReceiptSHA256': base.sha(build.BUILD / 'build.json'), 'controlSHA256': report['controlSHA256'],
        'cpuNice': cpu_nice, 'ioClass': io})


def launch():
    base.guard.require_dedicated_process(); priority = base.low_priority()
    if min(shutil.disk_usage(path).free for path in (ROOT, Path.home(), P)) < 36 * base.GIB: raise ValueError('free disk below 36 GiB')
    for path in (build.BUILD, MONITOR):
        if path.exists() or path.is_symlink(): raise FileExistsError('output exists')
    with base.LOCK.open('r+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for path in (build.BUILD, MONITOR):
            if path.exists() or path.is_symlink(): raise FileExistsError('output exists')
        if min(shutil.disk_usage(path).free for path in (ROOT, Path.home(), P)) < 36 * base.GIB: raise ValueError('free disk below 36 GiB')
        pins = sources(); env = {'PATH': '/usr/bin:/bin', 'HOME': str(Path.home()), 'SDL_VIDEODRIVER': 'offscreen',
                                 'LD_LIBRARY_PATH': str(ROOT / 'build/flex/rocm-runtime')}
        MONITOR.mkdir(); base.write_new(MONITOR / 'launch.json', {'command': command(), 'environment': env,
            'wallSeconds': base.WALL_SECONDS, 'sourcePins': pins, 'supervisorPriority': priority})
        try:
            status = base.hidden.supervise(command(), MONITOR, env, base.WALL_SECONDS)
            if not base.clean(status) or json.loads((MONITOR / 'supervisor-result.json').read_text()) != status: raise ValueError('unclean build supervisor')
            result = json.loads((MONITOR / 'worker-result.json').read_text()); report = build.verify(build.BUILD)
            if (sources() != pins or result.get('sourcePins') != pins or result.get('status') != 'isolated_build_only' or
                    result.get('cpuNice', 0) < 15 or result.get('ioClass') != 'idle' or
                    result.get('buildReceiptSHA256') != base.sha(build.BUILD / 'build.json') or
                    result.get('controlSHA256') != report['controlSHA256']): raise ValueError('build receipt differs')
            if min(shutil.disk_usage(path).free for path in (ROOT, Path.home(), P)) < 32 * base.GIB: raise ValueError('final disk floor')
            base.write_new(MONITOR / 'result.json', {'status': 'isolated_build_only', 'supervisorStatus': status,
                           'workerSHA256': base.sha(MONITOR / 'worker-result.json')})
            return 0
        except BaseException as error:
            base.write_new(MONITOR / 'result.json', {'status': 'failed', 'reason': str(error)})
            raise


if __name__ == '__main__':
    raise SystemExit('Disabled; independent review and scheduling required.')
