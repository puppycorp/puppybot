#!/usr/bin/env python3
"""Disabled dedicated CPU-only watchdog for steering-plan registration."""
import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
P = ROOT / 'build/flex/sim/levels-v2/pitch82'
MONITOR = P / 'l5-steering-hysteresis-registration-monitor-v1'
FREEZE = HERE / 'register.py'
WALL_SECONDS = 3600


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


watch = load('steering_registration_watch', ROOT / 'flex/tests/supervise-heading-overlays.py')
registration = load('steering_registration_wrapper', FREEZE)
base = registration.base
plan = registration.plan
standalone = load('steering_registration_standalone', ROOT / 'experiments/sim-stop-supervisor/supervisor.py')


def command():
    code = ('import importlib.util,json,sys;'
            's=importlib.util.spec_from_file_location("registration",sys.argv[1]);'
            'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);'
            'print(json.dumps({"status":m.freeze()["status"]},sort_keys=True))')
    return [sys.executable, '-I', '-c', code, str(FREEZE)]


def launch():
    standalone.require_dedicated_process()
    if min(shutil.disk_usage(path).free for path in (P, ROOT, Path.home())) < 36 * 1024**3:
        raise ValueError('free disk below 36 GiB')
    for path in (MONITOR, registration.MANIFEST, plan.OUTPUT): base.require_new_output(path)
    if not (plan.BUILD / 'build.json').is_file(): raise ValueError('isolated build receipt missing')
    paths = [Path(__file__), FREEZE, HERE / 'plan.py', HERE / 'prepare.py',
             ROOT / 'flex/tests/supervise-heading-overlays.py',
             ROOT / 'experiments/sim-stop-supervisor/supervisor.py',
             ROOT / 'experiments/sim-stop-supervisor/proxy.py']
    pins = {str(path): base.sha(path) for path in paths}
    env = {'PATH': '/usr/bin:/bin', 'HOME': str(Path.home()), 'SDL_VIDEODRIVER': 'offscreen',
           'LD_LIBRARY_PATH': str(ROOT / 'build/flex/rocm-runtime')}
    MONITOR.mkdir(); invocation = {'argv': command(), 'environment': env, 'wallSeconds': WALL_SECONDS, 'sourcePins': pins}
    with (MONITOR / 'launch.json').open('x') as stream: json.dump(invocation, stream, indent=2, sort_keys=True); stream.write('\n')
    status, code = watch.supervise(MONITOR, command(), env, WALL_SECONDS)
    if code == 0:
        try:
            if json.loads((MONITOR / 'supervisor-result.json').read_text()) != status:
                raise ValueError('persisted registration supervisor status differs')
            if any(base.sha(Path(path)) != digest for path, digest in pins.items()): raise ValueError('registration source changed')
            saved = json.loads(registration.MANIFEST.read_text())
            if (saved.get('schema') != 'puppybot.l5-steering-hysteresis-plan.v1' or saved.get('status') != 'frozen_before_play' or
                    saved.get('design') != plan.design() or saved.get('files', {}).get(str(FREEZE)) != pins[str(FREEZE)] or
                    saved.get('files', {}).get(str(Path(__file__))) != pins[str(Path(__file__))]):
                raise ValueError('frozen plan metadata differs')
            if json.loads((MONITOR / 'client.log').read_text()) != {'status': 'frozen_before_play'}:
                raise ValueError('registration child output differs')
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError): code = 1
    with (MONITOR / 'result.json').open('x') as stream:
        json.dump({'wrapperExit': code, 'childExit': status.get('clientExit'), 'signal': status.get('signal'),
                   'timedOut': status.get('timedOut'), 'remainingWorkersTerminated': status.get('remainingWorkersTerminated'),
                   'scope': 'bounded saved CPU registration only; no GPU or actor execution claim'}, stream, indent=2, sort_keys=True);stream.write('\n')
    return code


if __name__ == '__main__':
    raise SystemExit('Disabled pending independent review and scheduling; no plan registration authorized.')
