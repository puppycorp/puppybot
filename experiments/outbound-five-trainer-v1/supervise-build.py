#!/usr/bin/env python3
"""Serialize and supervise the private trainer's CPU-only build."""
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
MONITOR = P / 'outbound-five-trainer-build-cpu-monitor-v1'
LOCK = P / '.l4-matched.lock'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    obj = importlib.util.module_from_spec(spec); spec.loader.exec_module(obj)
    return obj


builder = load('five_trainer_builder', HERE / 'build.py')
base = load('five_trainer_cpu_supervisor', ROOT / 'experiments/physical-search-fallback-build-supervisor-v1/supervisor.py')


def source_pins():
    archive = builder.ARCHIVE / 'flex-source'
    expected = json.loads((builder.ARCHIVE / 'inputs.json').read_text())['patchedSourceFiles']
    files = builder.tree(archive)
    if files != expected: raise ValueError('trainer archive changed')
    pins = {str(archive / name): digest for name, digest in files.items()}
    paths = (Path(__file__), HERE / 'build.py', HERE / 'design.py', HERE / 'train.py', HERE / 'monitor.py',
             ROOT / 'experiments/outbound-episode-cap-v1/transform.py', ROOT / 'experiments/outbound-aux-mask-v1/transform.py',
             ROOT / 'datasets/visual-control/chase-v1/levels/heading-reflink-source.py', builder.COMPILER,
             builder.ARCHIVE / 'inputs.json', builder.ARCHIVE / 'dataset.original.flex',
             ROOT / 'experiments/physical-search-fallback-build-supervisor-v1/supervisor.py',
             ROOT / 'flex/tests/run-physical-hidden-trial.py', ROOT / 'experiments/sim-stop-supervisor/supervisor.py',
             ROOT / 'experiments/sim-stop-supervisor/proxy.py', Path(sys.executable).resolve(), base.NICE, base.IONICE)
    pins.update({str(path): builder.sha(path) for path in paths})
    pins.update(builder.imports((ROOT / 'build/flex/pup-device.flex', ROOT / 'build/flex/pup-kernel-ops.flex')))
    return dict(sorted(pins.items()))


def command():
    code = ('import importlib.util,sys;'
            's=importlib.util.spec_from_file_location("trainer_supervisor",sys.argv[1]);'
            'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.worker()')
    return [str(base.NICE), '-n', '15', str(base.IONICE), '-c', '3', sys.executable, '-I', '-c', code, str(HERE / 'supervise-build.py')]


def worker():
    cpu = os.getpriority(os.PRIO_PROCESS, 0)
    io = subprocess.run([str(base.IONICE), '-p', str(os.getpid())], capture_output=True, text=True, timeout=5, check=True).stdout.strip()
    if cpu < 15 or io != 'idle': raise ValueError('worker priority differs')
    pins = json.loads((MONITOR / 'launch.json').read_text())['sourcePins']
    if source_pins() != pins: raise ValueError('trainer sources changed before build')
    receipt = builder.build(); verified = builder.verify()
    if receipt != verified or source_pins() != pins: raise ValueError('trainer build or source changed')
    outside = {path: digest for path, digest in receipt['imports'].items()
               if not Path(path).is_relative_to(builder.DEFAULT / 'flex-source')}
    if any(pins.get(path) != digest for path, digest in outside.items()):
        raise ValueError('built trainer has an unpinned external source import')
    base.write_new(MONITOR / 'worker-result.json', {'status': 'isolated_build_only', 'sourcePins': pins,
        'buildSHA256': builder.sha(builder.DEFAULT / 'build.json'), 'binaries': receipt['binaries'],
        'cpuNice': cpu, 'ioClass': io})


def launch():
    base.guard.require_dedicated_process(); priority = base.low_priority()
    for path in (builder.DEFAULT, MONITOR):
        if path.exists() or path.is_symlink(): raise FileExistsError('output exists; preserve it')
    if any(shutil.disk_usage(path).free < 36 * 1024**3 for path in (ROOT, Path.home(), P)):
        raise ValueError('disk below 36 GiB before trainer build')
    with LOCK.open('r+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for path in (builder.DEFAULT, MONITOR):
            if path.exists() or path.is_symlink(): raise FileExistsError('output exists; preserve it')
        if any(shutil.disk_usage(path).free < 36 * 1024**3 for path in (ROOT, Path.home(), P)):
            raise ValueError('disk below 36 GiB before locked trainer build')
        pins = source_pins(); env = {'PATH': '/usr/bin:/bin', 'HOME': str(Path.home())}
        MONITOR.mkdir()
        base.write_new(MONITOR / 'launch.json', {'command': command(), 'environment': env,
            'wallSeconds': 900, 'sourcePins': pins, 'supervisorPriority': priority,
            'scope': 'bounded low-priority CPU build only'})
        try:
            status = base.hidden.supervise(command(), MONITOR, env, 900)
            if not base.clean(status) or json.loads((MONITOR / 'supervisor-result.json').read_text()) != status:
                raise ValueError('trainer build supervisor not clean')
            work = json.loads((MONITOR / 'worker-result.json').read_text()); built = builder.verify()
            if (work.get('status') != 'isolated_build_only' or work.get('sourcePins') != pins or
                    work.get('buildSHA256') != builder.sha(builder.DEFAULT / 'build.json') or
                    work.get('binaries') != built['binaries'] or work.get('cpuNice', 0) < 15 or
                    work.get('ioClass') != 'idle' or source_pins() != pins):
                raise ValueError('trainer build receipt or source pins differ')
            if any(shutil.disk_usage(path).free < 32 * 1024**3 for path in (ROOT, Path.home(), P)):
                raise ValueError('disk below 32 GiB after trainer build')
            result = {'status': 'isolated_build_only', 'reason': None, 'supervisorStatus': status,
                      'launchSHA256': builder.sha(MONITOR / 'launch.json'),
                      'workerSHA256': builder.sha(MONITOR / 'worker-result.json'),
                      'buildSHA256': builder.sha(builder.DEFAULT / 'build.json'),
                      'scope': 'CPU-only build and clone fixture; no GPU or training'}
            base.write_new(MONITOR / 'result.json', result)
            return result
        except BaseException as error:
            if not (MONITOR / 'result.json').exists():
                base.write_new(MONITOR / 'result.json', {'status': 'failed', 'reason': str(error)})
            raise


if __name__ == '__main__':
    raise SystemExit('Disabled pending independent review and scheduling.')
