#!/usr/bin/env python3
"""Hard-bound the complete low-priority CPU plan registration process."""
import importlib.util
import json
import shutil
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
P = ROOT / 'build/flex/sim/levels-v2/pitch82'
OUTER = P / 'outbound-five-freeze-outer-monitor-v1'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    obj = importlib.util.module_from_spec(spec); spec.loader.exec_module(obj)
    return obj


freeze = load('outer_outbound_freeze', HERE / 'supervise-freeze.py')
base = freeze.base


def command():
    code = ('import importlib.util,sys;'
            's=importlib.util.spec_from_file_location("freeze",sys.argv[1]);'
            'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.launch()')
    return [str(base.NICE), '-n', '15', str(base.IONICE), '-c', '3', sys.executable, '-I', '-c', code, str(HERE / 'supervise-freeze.py')]


def launch():
    base.guard.require_dedicated_process(); priority = base.low_priority()
    freeze.train.no_existing(OUTER, freeze.MONITOR, freeze.train.MANIFEST, freeze.train.MODEL, freeze.train.PACKAGE)
    if any(shutil.disk_usage(p).free < 36 * 1024**3 for p in (ROOT, Path.home(), P)):
        raise ValueError('disk below 36 GiB before outer freeze')
    pins = freeze.source_pins(); pins[str(Path(__file__).resolve())] = freeze.train.sha(Path(__file__))
    env = {'PATH': '/usr/bin:/bin', 'HOME': str(Path.home())}; OUTER.mkdir()
    base.write_new(OUTER / 'invocation.json', {'command': command(), 'environment': env, 'wallSeconds': 2400,
        'sourcePins': pins, 'supervisorPriority': priority,
        'scope': 'bounded CPU plan registration only; no GPU or training'})
    try:
        status = base.hidden.supervise(command(), OUTER, env, 2400)
        if not base.clean(status) or json.loads((OUTER / 'supervisor-result.json').read_text()) != status:
            raise ValueError('outer freeze supervisor not clean')
        receipt = json.loads((freeze.MONITOR / 'result.json').read_text())
        current = freeze.source_pins(); current[str(Path(__file__).resolve())] = freeze.train.sha(Path(__file__))
        if (current != pins or receipt.get('status') != 'plan_registered_only' or receipt.get('reason') is not None or
                receipt.get('planSHA256') != freeze.train.sha(freeze.train.MANIFEST) or
                receipt.get('launchSHA256') != freeze.train.sha(freeze.MONITOR / 'launch.json') or
                receipt.get('workerSHA256') != freeze.train.sha(freeze.MONITOR / 'worker-result.json')):
            raise ValueError('outer freeze receipt or source pins differ')
        if any(shutil.disk_usage(p).free < 36 * 1024**3 for p in (ROOT, Path.home(), P)):
            raise ValueError('disk below 36 GiB after outer freeze')
        result = {'status': 'plan_registered_only', 'reason': None, 'supervisorStatus': status,
                  'invocationSHA256': freeze.train.sha(OUTER / 'invocation.json'),
                  'innerReceiptSHA256': freeze.train.sha(freeze.MONITOR / 'result.json'),
                  'planSHA256': freeze.train.sha(freeze.train.MANIFEST),
                  'scope': 'bounded CPU plan registration only; no GPU, training or promotion'}
        base.write_new(OUTER / 'result.json', result)
        return result
    except BaseException as error:
        if not (OUTER / 'result.json').exists():
            base.write_new(OUTER / 'result.json', {'status': 'failed', 'reason': str(error)})
        raise


if __name__ == '__main__':
    raise SystemExit('Disabled pending independent review and scheduling.')
