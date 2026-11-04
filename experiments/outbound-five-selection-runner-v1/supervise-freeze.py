#!/usr/bin/env python3
"""Bound the CPU-only registration of the fixed selection replay."""
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
MONITOR = P / 'fresh-policy-selection-freeze-monitor-v3'
WALL_SECONDS = 3600
GIB = 1024**3


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


selection = load('selection_freeze_worker', HERE / 'runner.py')
base = load('selection_freeze_supervisor', ROOT / 'experiments/physical-search-fallback-build-supervisor-v1/supervisor.py')


def source_pins():
    paths = (Path(__file__).resolve(), HERE / 'runner.py',
             ROOT / 'experiments/physical-search-fallback-build-supervisor-v1/supervisor.py',
             ROOT / 'flex/tests/run-physical-hidden-trial.py',
             ROOT / 'experiments/sim-stop-supervisor/supervisor.py',
             ROOT / 'experiments/sim-stop-supervisor/proxy.py', Path(sys.executable).resolve(), base.NICE, base.IONICE)
    if any(not path.is_file() for path in paths):
        raise ValueError('missing freeze source or tool')
    return {str(path): selection.sha(path) for path in paths}


def command():
    code = ('import importlib.util,sys;'
            's=importlib.util.spec_from_file_location("selection_freeze",sys.argv[1]);'
            'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.worker()')
    return [str(base.NICE), '-n', '15', str(base.IONICE), '-c', '3', sys.executable, '-I', '-c', code, str(HERE / 'supervise-freeze.py')]


def worker():
    cpu = os.getpriority(os.PRIO_PROCESS, 0)
    io = subprocess.run([str(base.IONICE), '-p', str(os.getpid())], capture_output=True,
                        text=True, timeout=5, check=True).stdout.strip()
    if cpu < 15 or io != 'idle':
        raise ValueError('freeze worker priority differs')
    launch = json.loads((MONITOR / 'launch.json').read_text())
    if source_pins() != launch['sourcePins']:
        raise ValueError('freeze sources changed before registration')
    frozen = selection.freeze()
    if selection.verify() != frozen or source_pins() != launch['sourcePins']:
        raise ValueError('frozen plan or sources changed')
    base.write_new(MONITOR / 'worker-result.json', {'status': 'plan_registered_only',
        'planSHA256': selection.sha(selection.MANIFEST), 'sourcePins': launch['sourcePins'],
        'cpuNice': cpu, 'ioClass': io})


def launch():
    """Call under an additional external whole-process deadline."""
    base.guard.require_dedicated_process(); priority = base.low_priority()
    selection.strict_inventory.require_fresh(selection.OUTPUT, selection.MONITOR, selection.MANIFEST)
    if MONITOR.exists() or MONITOR.is_symlink():
        raise FileExistsError('freeze monitor already exists')
    if any(shutil.disk_usage(path).free < 38 * GIB for path in (ROOT, Path.home(), P)):
        raise ValueError('disk below 38 GiB before selection registration')
    pins = source_pins(); env = {'PATH': '/usr/bin:/bin', 'HOME': str(Path.home())}
    MONITOR.mkdir()
    base.write_new(MONITOR / 'launch.json', {'command': command(), 'environment': env,
        'wallSeconds': WALL_SECONDS, 'sourcePins': pins, 'supervisorPriority': priority,
        'scope': 'CPU-only selection plan registration; reused training-family scenes; no GPU or promotion'})
    try:
        status = base.hidden.supervise(command(), MONITOR, env, WALL_SECONDS)
        if ((MONITOR / 'supervisor-result.json').is_symlink() or not base.clean(status) or
                json.loads((MONITOR / 'supervisor-result.json').read_text()) != status):
            raise ValueError('selection freeze worker did not exit cleanly')
        worker_result = json.loads((MONITOR / 'worker-result.json').read_text())
        frozen = selection.verify()
        if (worker_result.get('status') != 'plan_registered_only' or worker_result.get('sourcePins') != pins or
                worker_result.get('planSHA256') != selection.sha(selection.MANIFEST) or
                worker_result.get('cpuNice', 0) < 15 or worker_result.get('ioClass') != 'idle' or source_pins() != pins or
                frozen.get('schema') != 'puppybot.outbound-five-selection-plan.v1'):
            raise ValueError('selection freeze receipt differs')
        if any(shutil.disk_usage(path).free < 38 * GIB for path in (ROOT, Path.home(), P)):
            raise ValueError('disk below 38 GiB after selection registration')
        result = {'status': 'plan_registered_only', 'reason': None, 'supervisorStatus': status,
                  'supervisorSHA256': selection.sha(MONITOR / 'supervisor-result.json'),
                  'launchSHA256': selection.sha(MONITOR / 'launch.json'),
                  'workerSHA256': selection.sha(MONITOR / 'worker-result.json'),
                  'planSHA256': selection.sha(selection.MANIFEST),
                  'scope': 'CPU-only registration; no GPU, selection game or promotion'}
        base.write_new(MONITOR / 'result.json', result)
        return result
    except BaseException as error:
        if not (MONITOR / 'result.json').exists():
            base.write_new(MONITOR / 'result.json', {'status': 'failed', 'reason': str(error)})
        raise


if __name__ == '__main__':
    raise SystemExit('Disabled pending independent review and dedicated supervised scheduling.')
