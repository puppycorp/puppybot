#!/usr/bin/env python3
"""Retry the unstarted v1 selection using separate paths and the same limits."""
import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
ORIGINAL = ROOT / 'experiments/fresh-policy-comparison-v1/selection.py'
spec = importlib.util.spec_from_file_location('fresh_selection_v1', ORIGINAL)
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)

P = base.P
PRIOR_PLAN = P / 'fresh-policy-selection-plan-v1.json'
PRIOR_OUTPUT = P / 'fresh-policy-selection-v1'
PRIOR_MONITOR = P / 'fresh-policy-selection-monitored-v1'
MANIFEST = P / 'fresh-policy-selection-plan-v2.json'
OUTPUT = P / 'fresh-policy-selection-v2'
MONITOR = P / 'fresh-policy-selection-monitored-v2'
prior_source_paths = base.source_paths


def prior_files():
    return [PRIOR_PLAN, PRIOR_MONITOR / 'frozen-manifest.json', PRIOR_MONITOR / 'launch.json',
            PRIOR_MONITOR / 'telemetry.jsonl', PRIOR_MONITOR / 'disk.jsonl',
            PRIOR_MONITOR / 'monitor-result.json', PRIOR_MONITOR / 'outer-monitor/client.log',
            PRIOR_MONITOR / 'outer-monitor/supervisor-result.json']


def check_prior():
    """Only a terminal pre-game resource-gate failure may reuse these seeds."""
    if PRIOR_OUTPUT.exists() or PRIOR_OUTPUT.is_symlink():
        raise ValueError('prior game output exists; do not retry the same cases')
    for name in ('worker.log', 'worker-launch.json', 'evidence.json', 'completion.json'):
        if (PRIOR_MONITOR / name).exists(): raise ValueError('prior run advanced beyond baseline')
    frozen = json.loads(PRIOR_PLAN.read_text())
    if (frozen.get('status') != 'frozen_before_play' or frozen.get('design') != base.design() or
            json.loads((PRIOR_MONITOR / 'frozen-manifest.json').read_text()) != frozen):
        raise ValueError('prior frozen plan differs')
    if base.old.runtime_chain() != frozen.get('runtime'):
        raise ValueError('prior runtime symlink chain changed')
    links = {}
    for task in base.design()['tasks']:
        for row in task['rows']:
            links.update(base.scene_links(row))
    if links != frozen.get('sceneLinks'):
        raise ValueError('prior scene links changed')
    result = json.loads((PRIOR_MONITOR / 'monitor-result.json').read_text())
    if result != {'status': 'failed', 'reason': 'GPU busy above 10% for five consecutive samples'}:
        raise ValueError('prior failure is not the pre-game GPU baseline')
    status = json.loads((PRIOR_MONITOR / 'outer-monitor/supervisor-result.json').read_text())
    if (status.get('clientExit') != 1 or status.get('signal') is not None or
            status.get('timedOut') is not False or status.get('remainingWorkersTerminated') is not False):
        raise ValueError('prior monitor did not terminate cleanly after baseline failure')
    samples = [json.loads(line) for line in (PRIOR_MONITOR / 'telemetry.jsonl').read_text().splitlines()]
    if len(samples) != 5 or any(row.get('phase') != 'baseline' or
                                type(row.get('busyPercent')) is not int or row['busyPercent'] <= 10
                                for row in samples):
        raise ValueError('prior GPU baseline evidence differs')
    if any(base.base.sha(Path(path)) != digest for path, digest in frozen['files'].items()):
        raise ValueError('prior selection input changed')
    return frozen


def source_paths():
    check_prior()
    return sorted(set(prior_source_paths() + [Path(__file__)] + prior_files()))


def python_call(function, *args):
    code = ('import importlib.util,sys;'
            's=importlib.util.spec_from_file_location("fresh_retry",sys.argv[1]);'
            'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);'
            'getattr(m,sys.argv[2])(*sys.argv[3:])')
    return [sys.executable, '-I', '-c', code, str(Path(__file__).resolve()), function, *map(str, args)]


def configure_monitor():
    base.monitor.OUTPUT = OUTPUT; base.monitor.MONITOR = MONITOR; base.monitor.MANIFEST = MANIFEST
    base.monitor.REGISTER = Path(__file__).resolve(); base.monitor.verify_saved = base.verify_saved
    base.monitor.worker_command = lambda: python_call('run')


base.MANIFEST = MANIFEST
base.OUTPUT = OUTPUT
base.MONITOR = MONITOR
base.source_paths = source_paths
base.python_call = python_call
base.configure_monitor = configure_monitor


def verify(): return base.verify()
def freeze(): return base.freeze()
def run(): return base.run()
def launch(): return base.launch()


def describe_configuration():
    configure_monitor()
    print(json.dumps({'output': str(base.monitor.OUTPUT), 'registration': str(base.monitor.REGISTER),
                      'worker': base.monitor.worker_command()}, sort_keys=True))


def monitor_worker(path):
    configure_monitor(); base.monitor.monitor_worker(path)


def final_check(path, evidence_sha):
    configure_monitor(); print(json.dumps(base.monitor.final_check(path, evidence_sha), sort_keys=True))


if __name__ == '__main__':
    raise SystemExit('Disabled; independent review and resource scheduling are required.')
