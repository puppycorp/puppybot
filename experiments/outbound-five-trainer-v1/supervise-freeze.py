#!/usr/bin/env python3
"""Bound and record the CPU-only freeze of the fixed training plan."""
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
MONITOR = P / 'outbound-five-freeze-cpu-monitor-v1'
LOCK = P / '.l4-matched.lock'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    obj = importlib.util.module_from_spec(spec); spec.loader.exec_module(obj)
    return obj


train = load('outbound_freeze_training', HERE / 'train.py')
base = load('outbound_freeze_supervisor', ROOT / 'experiments/physical-search-fallback-build-supervisor-v1/supervisor.py')


def source_pins():
    paths = (Path(__file__), HERE / 'train.py', HERE / 'design.py', HERE / 'build.py', HERE / 'monitor.py',
             HERE / 'supervise-build.py', ROOT / 'experiments/physical-search-fallback-build-supervisor-v1/supervisor.py',
             ROOT / 'flex/tests/run-physical-hidden-trial.py', ROOT / 'experiments/sim-stop-supervisor/supervisor.py',
             ROOT / 'experiments/sim-stop-supervisor/proxy.py', Path(sys.executable).resolve(), base.NICE, base.IONICE)
    return {str(path): train.sha(path) for path in paths}


def command():
    code = ('import importlib.util,sys;'
            's=importlib.util.spec_from_file_location("freeze",sys.argv[1]);'
            'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.worker()')
    return [str(base.NICE), '-n', '15', str(base.IONICE), '-c', '3', sys.executable, '-I', '-c', code, str(HERE / 'supervise-freeze.py')]


def worker():
    cpu = os.getpriority(os.PRIO_PROCESS, 0)
    io = subprocess.run([str(base.IONICE), '-p', str(os.getpid())], capture_output=True, text=True, timeout=5, check=True).stdout.strip()
    if cpu < 15 or io != 'idle': raise ValueError('freeze worker priority differs')
    launch = json.loads((MONITOR / 'launch.json').read_text())
    if source_pins() != launch['sourcePins']: raise ValueError('freeze source changed before registration')
    frozen = train.freeze()
    if (train.verify_manifest() != frozen or train.hashlib_json(frozen['inputs']) != launch['inputsSHA256'] or
            source_pins() != launch['sourcePins']):
        raise ValueError('frozen plan or input changed')
    base.write_new(MONITOR / 'worker-result.json', {'status': 'plan_registered_only',
        'planSHA256': train.sha(train.MANIFEST), 'inputsSHA256': launch['inputsSHA256'],
        'sourcePins': launch['sourcePins'], 'cpuNice': cpu, 'ioClass': io})


def launch():
    base.guard.require_dedicated_process(); priority = base.low_priority()
    train.no_existing(MONITOR, train.MANIFEST, train.MODEL, train.PACKAGE,
                      P / 'outbound-five-train-worker-v1', P / 'outbound-five-training-monitored-v1')
    if any(shutil.disk_usage(path).free < 36 * 1024**3 for path in (ROOT, Path.home(), P)):
        raise ValueError('disk below 36 GiB before plan registration')
    with LOCK.open('r+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        train.no_existing(MONITOR, train.MANIFEST, train.MODEL, train.PACKAGE,
                          P / 'outbound-five-train-worker-v1', P / 'outbound-five-training-monitored-v1')
        if any(shutil.disk_usage(path).free < 36 * 1024**3 for path in (ROOT, Path.home(), P)):
            raise ValueError('disk below 36 GiB after taking lock')
        pins = source_pins(); digest = train.hashlib_json(train.inputs()); env = {'PATH': '/usr/bin:/bin', 'HOME': str(Path.home())}
        if source_pins() != pins: raise ValueError('freeze sources changed during input audit')
        MONITOR.mkdir()
        base.write_new(MONITOR / 'launch.json', {'command': command(), 'environment': env, 'wallSeconds': 1800,
            'sourcePins': pins, 'inputsSHA256': digest, 'supervisorPriority': priority,
            'scope': 'CPU plan freeze only; no GPU, training or promotion'})
        try:
            status = base.hidden.supervise(command(), MONITOR, env, 1800)
            if not base.clean(status) or json.loads((MONITOR / 'supervisor-result.json').read_text()) != status:
                raise ValueError('plan freeze supervisor not clean')
            worker_result = json.loads((MONITOR / 'worker-result.json').read_text())
            frozen = train.verify_manifest()
            if (worker_result.get('status') != 'plan_registered_only' or worker_result.get('sourcePins') != pins or
                    worker_result.get('inputsSHA256') != digest or train.hashlib_json(frozen['inputs']) != digest or
                    worker_result.get('planSHA256') != train.sha(train.MANIFEST) or
                    worker_result.get('cpuNice', 0) < 15 or worker_result.get('ioClass') != 'idle' or source_pins() != pins):
                raise ValueError('plan freeze evidence differs')
            if any(shutil.disk_usage(path).free < 36 * 1024**3 for path in (ROOT, Path.home(), P)):
                raise ValueError('disk below 36 GiB after plan registration')
            result = {'status': 'plan_registered_only', 'reason': None, 'supervisorStatus': status,
                      'launchSHA256': train.sha(MONITOR / 'launch.json'),
                      'workerSHA256': train.sha(MONITOR / 'worker-result.json'),
                      'planSHA256': train.sha(train.MANIFEST), 'inputsSHA256': digest,
                      'scope': 'CPU-only plan freeze; no GPU, training, selection or promotion'}
            base.write_new(MONITOR / 'result.json', result)
            return result
        except BaseException as error:
            if not (MONITOR / 'result.json').exists():
                base.write_new(MONITOR / 'result.json', {'status': 'failed', 'reason': str(error)})
            raise


if __name__ == '__main__':
    raise SystemExit('Disabled pending independent review and scheduling.')
