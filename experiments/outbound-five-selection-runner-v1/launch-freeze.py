#!/usr/bin/env python3
"""Hard-bound the entire low-priority selection plan registration."""
import importlib.util
import json
import shutil
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
P = ROOT / 'build/flex/sim/levels-v2/pitch82'
OUTER = P / 'fresh-policy-selection-freeze-outer-v3'
WALL_SECONDS = 4800


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


freeze = load('selection_outer_freeze', HERE / 'supervise-freeze.py')
base = freeze.base


def command():
    code = ('import importlib.util,sys;'
            's=importlib.util.spec_from_file_location("freeze",sys.argv[1]);'
            'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.launch()')
    return [str(base.NICE), '-n', '15', str(base.IONICE), '-c', '3', sys.executable, '-I', '-c', code, str(HERE / 'supervise-freeze.py')]


def source_pins():
    pins = freeze.source_pins()
    pins[str(Path(__file__).resolve())] = freeze.selection.sha(Path(__file__))
    return pins


def launch():
    base.guard.require_dedicated_process(); priority = base.low_priority()
    freeze.selection.strict_inventory.require_fresh(freeze.selection.OUTPUT, freeze.selection.MONITOR, freeze.selection.MANIFEST)
    if any(path.exists() or path.is_symlink() for path in (OUTER, freeze.MONITOR)):
        raise FileExistsError('selection freeze monitor already exists')
    if any(shutil.disk_usage(path).free < 38 * freeze.GIB for path in (ROOT, Path.home(), P)):
        raise ValueError('disk below 38 GiB before outer selection registration')
    pins = source_pins(); env = {'PATH': '/usr/bin:/bin', 'HOME': str(Path.home())}
    OUTER.mkdir()
    base.write_new(OUTER / 'invocation.json', {'command': command(), 'environment': env,
        'wallSeconds': WALL_SECONDS, 'sourcePins': pins, 'supervisorPriority': priority,
        'scope': 'bounded CPU registration of reused selection only; no GPU or promotion'})
    try:
        status = base.hidden.supervise(command(), OUTER, env, WALL_SECONDS)
        if ((OUTER / 'supervisor-result.json').is_symlink() or not base.clean(status) or
                json.loads((OUTER / 'supervisor-result.json').read_text()) != status):
            raise ValueError('outer selection freeze supervisor not clean')
        receipt = json.loads((freeze.MONITOR / 'result.json').read_text())
        if (source_pins() != pins or receipt.get('status') != 'plan_registered_only' or receipt.get('reason') is not None or
                receipt.get('planSHA256') != freeze.selection.sha(freeze.selection.MANIFEST) or
                receipt.get('launchSHA256') != freeze.selection.sha(freeze.MONITOR / 'launch.json') or
                receipt.get('workerSHA256') != freeze.selection.sha(freeze.MONITOR / 'worker-result.json') or
                (freeze.MONITOR / 'supervisor-result.json').is_symlink() or
                receipt.get('supervisorSHA256') != freeze.selection.sha(freeze.MONITOR / 'supervisor-result.json') or
                json.loads((freeze.MONITOR / 'supervisor-result.json').read_text()) != receipt.get('supervisorStatus') or
                not base.clean(receipt.get('supervisorStatus', {}))):
            raise ValueError('outer selection freeze receipt or source pins differ')
        if any(shutil.disk_usage(path).free < 38 * freeze.GIB for path in (ROOT, Path.home(), P)):
            raise ValueError('disk below 38 GiB after outer selection registration')
        result = {'status': 'plan_registered_only', 'reason': None, 'supervisorStatus': status,
                  'supervisorSHA256': freeze.selection.sha(OUTER / 'supervisor-result.json'),
                  'invocationSHA256': freeze.selection.sha(OUTER / 'invocation.json'),
                  'innerReceiptSHA256': freeze.selection.sha(freeze.MONITOR / 'result.json'),
                  'planSHA256': freeze.selection.sha(freeze.selection.MANIFEST),
                  'scope': 'bounded CPU registration only; no GPU or promotion'}
        base.write_new(OUTER / 'result.json', result)
        return result
    except BaseException as error:
        if not (OUTER / 'result.json').exists():
            base.write_new(OUTER / 'result.json', {'status': 'failed', 'reason': str(error)})
        raise


if __name__ == '__main__':
    raise SystemExit('Disabled pending independent review and dedicated supervised scheduling.')
