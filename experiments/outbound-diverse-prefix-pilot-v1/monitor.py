#!/usr/bin/env python3
"""Run the paired diverse pilot under the existing GPU/disk supervisor."""
import importlib.util
import json
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pilot = load('diverse_monitored_pilot', HERE / 'run.py')
old = load('diverse_prior_resource_monitor', ROOT / 'experiments/l5-teacher-rollin-pilot-v1/monitor.py')
old.pilot = pilot
old.HERE = HERE
old.OUTER_SECONDS = 7900
old.WORKER_SECONDS = 7500
old.FINAL_CHECK_SECONDS = 300
MONITOR = pilot.P / 'outbound-diverse-prefix-pilot-monitored-v1'


def worker_command():
    code = ('import importlib.util,sys;'
            's=importlib.util.spec_from_file_location("diverse_pilot",sys.argv[1]);'
            'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.run()')
    return [sys.executable, '-I', '-c', code, str(HERE / 'run.py')]


def verify_pilot(frozen):
    if pilot.pin_inputs() != frozen:
        raise ValueError('registered inputs changed')
    saved = json.loads((pilot.OUTPUT / 'report.json').read_text())
    fresh = pilot.auditor.audit()
    if saved != fresh:
        raise ValueError('fresh saved-game audit differs')
    return saved


old.worker_command = worker_command
old.verify_pilot = verify_pilot
monitor_worker = old.monitor_worker
final_check = old.final_check


def launch():
    """Run only in a separately scheduled dedicated process with GPU access."""
    pilot.standalone.require_dedicated_process()
    old.require_disk(36)
    for path in (MONITOR, pilot.OUTPUT):
        if path.exists() or path.is_symlink():
            raise FileExistsError(f'output exists: {path}')
    frozen = pilot.pin_inputs()
    MONITOR.mkdir(); outer = MONITOR / 'outer-monitor'; outer.mkdir()
    code = ('import importlib.util,sys;'
            's=importlib.util.spec_from_file_location("diverse_monitor",sys.argv[1]);'
            'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.monitor_worker(sys.argv[2])')
    argv = [sys.executable, '-I', '-c', code, str(HERE / 'monitor.py'), str(MONITOR)]
    env = old.environment()
    pilot.write_new(MONITOR / 'launch.json', {'command': argv, 'environment': env,
                    'wallSeconds': old.OUTER_SECONDS, 'inputs': frozen})
    status = pilot.base.hidden.supervise(argv, outer, env, old.OUTER_SECONDS)
    if not pilot.clean(status) or json.loads((outer / 'supervisor-result.json').read_text()) != status:
        raise RuntimeError('outer monitor failed; retained evidence is censored')
    if pilot.pin_inputs() != frozen:
        raise ValueError('registered inputs changed after monitor')
    monitor_result = json.loads((MONITOR / 'monitor-result.json').read_text())
    evidence = json.loads((MONITOR / 'evidence.json').read_text())
    saved = json.loads((pilot.OUTPUT / 'report.json').read_text())
    if json.loads((MONITOR / 'frozen-inputs.json').read_text()) != frozen:
        raise ValueError('worker input receipt differs from launch')
    if (monitor_result.get('status') != 'passed' or evidence.get('status') != 'diagnostic_only' or
            evidence.get('report') != saved or saved.get('status') not in ('screen_passed', 'screen_failed') or
            saved.get('trainingAuthorized') is not False):
        raise ValueError('monitor evidence incomplete or inconsistent')
    old.verify_logs(MONITOR); old.require_disk(32)
    final_dir = MONITOR / 'final-inventory-monitor'; final_dir.mkdir()
    evidence_sha = pilot.sha(MONITOR / 'evidence.json')
    code = ('import importlib.util,json,sys;'
            's=importlib.util.spec_from_file_location("diverse_monitor",sys.argv[1]);'
            'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);'
            'print(json.dumps(m.final_check(sys.argv[2],sys.argv[3]),sort_keys=True))')
    final_argv = [sys.executable, '-I', '-c', code, str(HERE / 'monitor.py'), str(MONITOR), evidence_sha]
    pilot.write_new(final_dir / 'invocation.json', {'argv': final_argv, 'environment': env,
                    'wallSeconds': old.FINAL_CHECK_SECONDS})
    final = pilot.base.hidden.supervise(final_argv, final_dir, env, old.FINAL_CHECK_SECONDS)
    if (not pilot.clean(final) or json.loads((final_dir / 'supervisor-result.json').read_text()) != final or
            json.loads((final_dir / 'client.log').read_text()) != {'status': 'final_inventory_verified'}):
        raise RuntimeError('final inventory failed; retained evidence is censored')
    if pilot.sha(MONITOR / 'evidence.json') != evidence_sha or pilot.pin_inputs() != frozen:
        raise ValueError('evidence or registered inputs changed during final inventory')
    old.require_disk(32)
    pilot.write_new(MONITOR / 'completion.json', {'status': 'diagnostic_only',
                    'screenStatus': saved['status'], 'trainingAuthorized': False,
                    'launchSHA256': pilot.sha(MONITOR / 'launch.json'),
                    'outerStatusSHA256': pilot.sha(outer / 'supervisor-result.json'),
                    'frozenInputsSHA256': pilot.sha(MONITOR / 'frozen-inputs.json'),
                    'reportSHA256': pilot.sha(pilot.OUTPUT / 'report.json'),
                    'evidenceSHA256': evidence_sha,
                    'telemetrySHA256': pilot.sha(MONITOR / 'telemetry.jsonl'),
                    'diskSHA256': pilot.sha(MONITOR / 'disk.jsonl'),
                    'finalInventoryStatusSHA256': pilot.sha(final_dir / 'supervisor-result.json'),
                    'scope': 'local training-family feasibility pilot; no model training, held-out or physical claim'})
    return saved


if __name__ == '__main__':
    raise SystemExit('Disabled pending independent review and GPU scheduling.')
