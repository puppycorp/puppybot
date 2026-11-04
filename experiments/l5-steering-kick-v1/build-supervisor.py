#!/usr/bin/env python3
"""Disabled dedicated CPU-only watchdog for isolated steering build."""
import importlib.util
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
P = ROOT / 'build/flex/sim/levels-v2/pitch82'
MONITOR = P / 'l5-steering-kick-build-cpu-monitor-v1'
PREPARE = HERE / 'prepare.py'
WALL_SECONDS = 1800


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


watch = load('steering_build_watch', ROOT / 'flex/tests/supervise-heading-overlays.py')
prepare = load('steering_build_preparation', PREPARE)
plan = load('steering_build_plan', HERE / 'plan.py')
base = prepare.base
standalone = load('steering_build_standalone', ROOT / 'experiments/sim-stop-supervisor/supervisor.py')


def command():
    code = ('import importlib.util,json,sys;'
            's=importlib.util.spec_from_file_location("prepare",sys.argv[1]);'
            'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);'
            'print(json.dumps({"status":m.prepare()["status"]},sort_keys=True))')
    return [sys.executable, '-I', '-c', code, str(PREPARE)]


def launch():
    standalone.require_dedicated_process()
    if min(shutil.disk_usage(path).free for path in (P, ROOT, Path.home())) < 36 * 1024**3:
        raise ValueError('free disk below 36 GiB')
    for path in (MONITOR, plan.BUILD, plan.OUTPUT, P / 'l5-steering-kick-plan-v1.json'):
        base.require_new_output(path)
    paths = [Path(__file__), PREPARE, HERE / 'plan.py', HERE / 'transform.py', HERE / 'probe.flex',
             ROOT / 'flex/tests/supervise-heading-overlays.py', ROOT / 'experiments/sim-stop-supervisor/supervisor.py',
             ROOT / 'experiments/sim-stop-supervisor/proxy.py',
             ROOT / 'flex/tests/run-physical-hidden-trial.py', ROOT / 'flex/tests/run-physical-rescan-trial.py',
             ROOT / 'flex/tests/run-physical-hybrid-trial.py']
    levels = ROOT / 'datasets/visual-control/chase-v1/levels'
    paths += [levels / name for name in ('run-route-factorial.py', 'prepare-route-factorial.py',
              'route-coverage.py', 'package-matched-epoch8.py', 'audit-matched-training.py', 'audit-selection.py')]
    pins = {str(path): base.sha(path) for path in paths}
    env = {'PATH': '/usr/bin:/bin', 'HOME': str(Path.home()), 'SDL_VIDEODRIVER': 'offscreen',
           'LD_LIBRARY_PATH': str(ROOT / 'build/flex/rocm-runtime')}
    MONITOR.mkdir(); invocation = {'argv': command(), 'environment': env, 'wallSeconds': WALL_SECONDS, 'sourcePins': pins}
    with (MONITOR / 'launch.json').open('x') as stream: json.dump(invocation, stream, indent=2, sort_keys=True); stream.write('\n')
    status, code = watch.supervise(MONITOR, command(), env, WALL_SECONDS)
    if code == 0:
        try:
            if json.loads((MONITOR / 'supervisor-result.json').read_text()) != status:
                raise ValueError('persisted build supervisor status differs')
            if any(base.sha(Path(path)) != digest for path, digest in pins.items()): raise ValueError('build source changed')
            report = json.loads((plan.BUILD / 'build.json').read_text())
            if (report.get('schema') != 'puppybot.l5-steer-build.v1' or report.get('status') != 'diagnostic_build_only' or
                    report.get('inputs', {}).get(str(PREPARE)) != pins[str(PREPARE)] or
                    report.get('inputs', {}).get(str(HERE / 'transform.py')) != pins[str(HERE / 'transform.py')] or
                    report.get('inputs', {}).get(str(HERE / 'probe.flex')) != pins[str(HERE / 'probe.flex')]):
                raise ValueError('isolated build receipt differs')
            lines = (MONITOR / 'client.log').read_text().splitlines()
            if not lines or json.loads(lines[-1]) != {'status': 'diagnostic_build_only'}:
                raise ValueError('build child output differs')
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError): code = 1
    with (MONITOR / 'result.json').open('x') as stream:
        json.dump({'wrapperExit': code, 'childExit': status.get('clientExit'), 'signal': status.get('signal'),
                   'timedOut': status.get('timedOut'), 'remainingWorkersTerminated': status.get('remainingWorkersTerminated'),
                   'scope': 'bounded CPU build only; no GPU, actor or physical execution'}, stream, indent=2, sort_keys=True);stream.write('\n')
    return code


if __name__ == '__main__':
    raise SystemExit('Disabled pending independent review and scheduling; no build authorized.')
