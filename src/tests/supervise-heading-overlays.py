#!/usr/bin/env python3
"""Disabled standalone CPU watchdog for full heading overlay preparation."""
import importlib.util
import json
import os
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
P = ROOT / 'build/flex/sim/levels-v2/pitch82'
OUTPUT = P / 'search-dagger-heading'
MONITOR = P / 'heading-overlays-cpu-monitor-v1'
COLLECTION_RECEIPT = P / 'heading-full-collection-monitored-v1/completion.json'
PREPARE = ROOT / 'datasets/visual-control/chase-v1/levels/prepare-heading-overlays.py'
WALL_SECONDS = 7200
GIB = 1024**3


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


hidden = load('overlay_hidden_supervisor', ROOT / 'flex/tests/run-physical-hidden-trial.py')
base = load('overlay_route_base', ROOT / 'datasets/visual-control/chase-v1/levels/run-route-factorial.py')


def exit_code(status):
    code = status.get('clientExit')
    signum = status.get('signal')
    if signum is not None:
        return min(255, 128 + signum) if type(signum) is int and 0 < signum < 128 else 1
    if status.get('timedOut') is True:
        return 124
    if type(code) is not int:
        return 1
    if code > 0:
        return code
    if code < 0:
        return min(255, 128 - code)
    if ('signal' not in status or status.get('timedOut') is not False or
            status.get('remainingWorkersTerminated') is not False or
            type(status.get('processGroup')) is not int or status['processGroup'] <= 0):
        return 1
    return 0


def supervise(output, command, env, wall_seconds):
    status = hidden.supervise(command, output, env, wall_seconds)
    code = exit_code(status)
    return status, code


def native_task_count():
    return sum(path.name.isdigit() for path in Path('/proc/self/task').iterdir())


def launch():
    """Run only in a dedicated one-thread process with no existing children."""
    if threading.active_count() != 1 or native_task_count() != 1 or hidden.supervisor.children(os.getpid()):
        raise RuntimeError('overlay supervisor requires a dedicated process without other children')
    if not COLLECTION_RECEIPT.is_file(): raise ValueError('monitored collection completion is missing')
    base.require_capacity(P, 34 * GIB)
    base.require_new_output(MONITOR)
    for name in ('aggregate-control', 'aggregate-treatment', 'slot-plan.json', 'pair-ready.json',
                 'resource-control.json', 'resource-treatment.json'):
        base.require_new_output(OUTPUT / name)
    command = [sys.executable, '-I', str(PREPARE)]
    env = {'PATH': '/usr/bin:/bin', 'HOME': str(Path.home()), 'PUPPYBOT_PROJECT': str(ROOT),
           'SDL_VIDEODRIVER': 'offscreen', 'LD_LIBRARY_PATH': str(ROOT / 'build/flex/rocm-runtime')}
    MONITOR.mkdir(parents=False, exist_ok=False)
    with (MONITOR / 'launch.json').open('x') as stream:
        json.dump({'command': command, 'environment': env, 'wallSeconds': WALL_SECONDS,
                   'prepareSHA256': base.sha(PREPARE),
                   'scope': 'bounded CPU preparation; inherited advisory lock and retained partials'}, stream, indent=2)
        stream.write('\n')
    status, code = supervise(MONITOR, command, env, WALL_SECONDS)
    if code == 0:
        try:
            ready = json.loads((OUTPUT / 'pair-ready.json').read_text())
            if ready.get('status') != 'paired_inputs_only' or ready.get('aggregateValidation', {}).get('validationGames') != 96:
                raise ValueError('invalid pair-ready report')
        except (OSError, ValueError, TypeError, AttributeError, json.JSONDecodeError):
            code = 1
    with (MONITOR / 'result.json').open('x') as stream:
        json.dump({'wrapperExit': code, 'childExit': status.get('clientExit'), 'signal': status.get('signal'),
                   'timedOut': status.get('timedOut'), 'remainingWorkersTerminated': status.get('remainingWorkersTerminated'),
                   'scope': 'raw child outcome retained; no claim of model qualification'}, stream, indent=2)
        stream.write('\n')
    return code


if __name__ == '__main__':
    raise SystemExit('Disabled pending independent review; no production overlay launch authorized.')
