#!/usr/bin/env python3
"""Dedicated resource supervisor for one pre-registered training job."""
import importlib.util
import json
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
P = ROOT / 'build/flex/sim/levels-v2/pitch82'
MONITOR = P / 'outbound-five-training-monitored-v1'
WORKER = P / 'outbound-five-train-worker-v1'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    obj = importlib.util.module_from_spec(spec); spec.loader.exec_module(obj)
    return obj


train = load('outbound_five_worker', HERE / 'train.py')
old = load('outbound_five_monitor_base', ROOT / 'experiments/l5-teacher-rollin-pilot-v1/monitor.py')
old.pilot = train
train.OUTPUT = train.MODEL
train.pin_inputs = train.verify_manifest
old.WORKER_SECONDS = 7200
old.OUTER_SECONDS = 7800
old.FINAL_CHECK_SECONDS = 600
old_inventory = old.inventory


def worker_command():
    code = ('import importlib.util,sys;'
            's=importlib.util.spec_from_file_location("training",sys.argv[1]);'
            'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.run()')
    return [sys.executable, '-I', '-c', code, str(HERE / 'train.py')]


def verify_training(frozen):
    if train.verify_manifest() != frozen:
        raise ValueError('training registration changed')
    receipt = train.verify_model()
    package = train.verify_package()
    result = json.loads((WORKER / 'result.json').read_text())
    if (result.get('status') != 'training_diagnostic_only' or result.get('planSHA256') != train.sha(train.MANIFEST) or
            result.get('trainingReceiptSHA256') != train.sha(train.MODEL / 'receipt.json') or
            result.get('supervisorStatusSHA256') != train.sha(WORKER / 'supervisor-result.json') or
            result.get('package') != package or receipt.get('epochs') != 1):
        raise ValueError('training result differs')
    status = json.loads((WORKER / 'supervisor-result.json').read_text())
    if (type(status.get('clientExit')) is not int or status['clientExit'] != 0 or status.get('signal') is not None or
            status.get('timedOut') is not False or status.get('remainingWorkersTerminated') is not False or
            type(status.get('processGroup')) is not int or status['processGroup'] <= 0):
        raise ValueError('training subprocess was not clean')
    invocation = json.loads((WORKER / 'invocation.json').read_text())
    if invocation != {'argv': train.command(), 'environment': train.environment(), 'wallSeconds': 3600}:
        raise ValueError('training invocation differs')
    return result


def inventory(_root):
    result = {}
    for name, path in (('model', train.MODEL), ('package', train.PACKAGE), ('supervisor', WORKER)):
        for key, value in old_inventory(path).items(): result[f'{name}/{key}'] = value
    return result


def final_check(output, evidence_sha):
    output = Path(output); evidence_path = output / 'evidence.json'
    if train.sha(evidence_path) != evidence_sha:
        raise ValueError('monitor evidence changed')
    evidence = json.loads(evidence_path.read_text()); frozen = json.loads((output / 'frozen-inputs.json').read_text())
    if (train.verify_manifest() != frozen or inventory(train.MODEL) != evidence.get('files') or
            verify_training(frozen) != evidence.get('report') or train.sha(evidence_path) != evidence_sha):
        raise ValueError('final training inventory or verification differs')
    return {'status': 'final_inventory_verified'}


old.worker_command = worker_command
old.verify_pilot = verify_training
old.inventory = inventory
monitor_worker = old.monitor_worker


def clean(status):
    return (type(status.get('clientExit')) is int and status['clientExit'] == 0 and
            status.get('signal') is None and status.get('timedOut') is False and
            status.get('remainingWorkersTerminated') is False and
            type(status.get('processGroup')) is int and status['processGroup'] > 0)


def launch():
    """Run only in a separately scheduled process with an idle GPU."""
    train.aggregate.monitor.pilot.standalone.require_dedicated_process()
    old.require_disk(36)
    train.no_existing(MONITOR, WORKER, train.MODEL, train.PACKAGE)
    frozen = train.verify_manifest(); plan_sha = train.sha(train.MANIFEST)
    MONITOR.mkdir(); outer = MONITOR / 'outer-monitor'; outer.mkdir()
    code = ('import importlib.util,sys;'
            's=importlib.util.spec_from_file_location("monitor",sys.argv[1]);'
            'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.monitor_worker(sys.argv[2])')
    argv = [sys.executable, '-I', '-c', code, str(HERE / 'monitor.py'), str(MONITOR)]
    env = old.environment()
    train.write_new(MONITOR / 'launch.json', {'command': argv, 'environment': env,
                    'wallSeconds': old.OUTER_SECONDS, 'planSHA256': plan_sha})
    status = train.prior.base.hidden.supervise(argv, outer, env, old.OUTER_SECONDS)
    if not clean(status) or json.loads((outer / 'supervisor-result.json').read_text()) != status:
        raise RuntimeError('outer monitor failed; retained training is censored')
    if train.verify_manifest() != frozen or train.sha(train.MANIFEST) != plan_sha:
        raise ValueError('training plan changed')
    monitor_result = json.loads((MONITOR / 'monitor-result.json').read_text())
    evidence = json.loads((MONITOR / 'evidence.json').read_text())
    if (monitor_result.get('status') != 'passed' or evidence.get('status') != 'diagnostic_only' or
            json.loads((MONITOR / 'frozen-inputs.json').read_text()) != frozen or
            evidence.get('report') != verify_training(frozen)):
        raise ValueError('training monitor evidence differs')
    old.verify_logs(MONITOR); old.require_disk(32)
    final_dir = MONITOR / 'final-inventory-monitor'; final_dir.mkdir()
    evidence_sha = train.sha(MONITOR / 'evidence.json')
    code = ('import importlib.util,json,sys;'
            's=importlib.util.spec_from_file_location("monitor",sys.argv[1]);'
            'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);'
            'print(json.dumps(m.final_check(sys.argv[2],sys.argv[3]),sort_keys=True))')
    final_argv = [sys.executable, '-I', '-c', code, str(HERE / 'monitor.py'), str(MONITOR), evidence_sha]
    train.write_new(final_dir / 'invocation.json', {'argv': final_argv, 'environment': env,
                    'wallSeconds': old.FINAL_CHECK_SECONDS})
    final = train.prior.base.hidden.supervise(final_argv, final_dir, env, old.FINAL_CHECK_SECONDS)
    if (not clean(final) or json.loads((final_dir / 'supervisor-result.json').read_text()) != final or
            json.loads((final_dir / 'client.log').read_text()) != {'status': 'final_inventory_verified'}):
        raise RuntimeError('final training inventory failed; retained output is censored')
    if train.sha(MONITOR / 'evidence.json') != evidence_sha or train.verify_manifest() != frozen:
        raise ValueError('training evidence or inputs changed during final check')
    old.require_disk(32)
    completion = {'status': 'training_diagnostic_only', 'planSHA256': plan_sha,
                  'launchSHA256': train.sha(MONITOR / 'launch.json'),
                  'outerStatusSHA256': train.sha(outer / 'supervisor-result.json'),
                  'monitorResultSHA256': train.sha(MONITOR / 'monitor-result.json'),
                  'workerResultSHA256': train.sha(WORKER / 'result.json'),
                  'frozenInputsSHA256': train.sha(MONITOR / 'frozen-inputs.json'),
                  'evidenceSHA256': evidence_sha,
                  'telemetrySHA256': train.sha(MONITOR / 'telemetry.jsonl'),
                  'diskSHA256': train.sha(MONITOR / 'disk.jsonl'),
                  'finalInventoryInvocationSHA256': train.sha(final_dir / 'invocation.json'),
                  'finalInventoryStatusSHA256': train.sha(final_dir / 'supervisor-result.json'),
                  'finalInventoryResultSHA256': train.sha(final_dir / 'client.log'),
                  'scope': 'one exploratory training seed; no selection, held-out, promotion or physical claim'}
    train.write_new(MONITOR / 'completion.json', completion)
    return evidence['report']


if __name__ == '__main__':
    raise SystemExit('Disabled pending independent review and GPU scheduling.')
