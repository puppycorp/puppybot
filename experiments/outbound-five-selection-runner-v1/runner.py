#!/usr/bin/env python3
"""Fresh monitored replay of fixed training-family selection; no held-out use.

Direct CLI is disabled. Freeze only after the fixed training completes with a
clean monitor, then use the separately supervised GPU launch after review.
"""
import importlib.util
import json
import sys
import types
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
P = ROOT / 'build/flex/sim/levels-v2/pitch82'
OUTPUT = P / 'fresh-policy-selection-v3'
MONITOR = P / 'fresh-policy-selection-monitored-v3'
MANIFEST = P / 'fresh-policy-selection-plan-v3.json'
TRAIN_PLAN = P / 'outbound-five-train-plan-v1.json'
TRAIN_MONITOR = P / 'outbound-five-training-monitored-v1'
TRAIN_WORKER = P / 'outbound-five-train-worker-v1'
PRIOR_SELECTION = P / 'fresh-policy-selection-v2/inputs.json'
PRIOR_MONITOR = P / 'fresh-policy-selection-monitored-v2/monitor-result.json'
FREEZE_MONITOR = P / 'fresh-policy-selection-freeze-monitor-v3'
FREEZE_OUTER = P / 'fresh-policy-selection-freeze-outer-v3'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


base = load('outbound_selection_prior', ROOT / 'experiments/fresh-policy-comparison-v1/selection.py')
strict_inventory = load('outbound_selection_catalog', ROOT / 'experiments/fresh-policy-catalog-monitor-v1/adapter.py')
metric = load('outbound_selection_inclusive_metric', ROOT / 'experiments/outbound-five-selection-metrics-v1/metrics.py')
training = load('outbound_selection_training_monitor', ROOT / 'experiments/outbound-five-trainer-v1/monitor.py')
sha = base.base.sha
old_source_paths = base.source_paths
old_reaudit = base.reaudit
old_current = base.current

# Preserve the fixed arm names used by the strict auditor and evaluation script.
base.MODELS = {'control': P / 'search-dagger-l35-4workers/student-s1',
               'treatment': P / 'outbound-five-fixed-epoch1-v1'}
base.OUTPUT, base.MONITOR, base.MANIFEST = OUTPUT, MONITOR, MANIFEST


def loaded_local_sources(roots):
    pending = list(roots); visited = set(); paths = set()
    while pending:
        module = pending.pop()
        if not isinstance(module, types.ModuleType) or id(module) in visited:
            continue
        visited.add(id(module)); path = getattr(module, '__file__', None)
        if path:
            path = Path(path).resolve()
            if path.suffix == '.py' and path.is_relative_to(ROOT):
                paths.add(path)
                pending.extend(item for item in vars(module).values() if isinstance(item, types.ModuleType))
    return paths


def training_receipts():
    return {'planSHA256': TRAIN_PLAN, 'launchSHA256': TRAIN_MONITOR / 'launch.json',
            'outerStatusSHA256': TRAIN_MONITOR / 'outer-monitor/supervisor-result.json',
            'monitorResultSHA256': TRAIN_MONITOR / 'monitor-result.json',
            'workerResultSHA256': TRAIN_WORKER / 'result.json',
            'frozenInputsSHA256': TRAIN_MONITOR / 'frozen-inputs.json',
            'evidenceSHA256': TRAIN_MONITOR / 'evidence.json',
            'telemetrySHA256': TRAIN_MONITOR / 'telemetry.jsonl',
            'diskSHA256': TRAIN_MONITOR / 'disk.jsonl',
            'finalInventoryInvocationSHA256': TRAIN_MONITOR / 'final-inventory-monitor/invocation.json',
            'finalInventoryStatusSHA256': TRAIN_MONITOR / 'final-inventory-monitor/supervisor-result.json',
            'finalInventoryResultSHA256': TRAIN_MONITOR / 'final-inventory-monitor/client.log'}


def check_training_receipts():
    completion_path = TRAIN_MONITOR / 'completion.json'
    if completion_path.is_symlink() or not completion_path.is_file():
        raise ValueError('completed training receipt is missing')
    completion = json.loads(completion_path.read_text())
    if completion.get('status') != 'training_diagnostic_only':
        raise ValueError('training was not completed under its monitor')
    for key, path in training_receipts().items():
        if path.is_symlink() or not path.is_file() or completion.get(key) != sha(path):
            raise ValueError(f'training evidence absent or changed: {key}')
    if json.loads((TRAIN_MONITOR / 'monitor-result.json').read_text()) != {'status': 'passed'}:
        raise ValueError('training resource monitor did not pass')
    for path in (TRAIN_MONITOR / 'outer-monitor/supervisor-result.json',
                 TRAIN_MONITOR / 'final-inventory-monitor/supervisor-result.json',
                 TRAIN_WORKER / 'supervisor-result.json'):
        if not training.clean(json.loads(path.read_text())):
            raise ValueError('training supervisor did not exit cleanly')
    if json.loads((TRAIN_MONITOR / 'final-inventory-monitor/client.log').read_text()) != {'status': 'final_inventory_verified'}:
        raise ValueError('training final inventory did not complete')
    return completion


def check_reused_selection(design, training_plan):
    old = json.loads(PRIOR_SELECTION.read_text())
    if json.loads(PRIOR_MONITOR.read_text()) != {'status': 'failed', 'reason': 'unsafe or vanished output directory'}:
        raise ValueError('prior selection monitor status differs')
    expected = training_plan['inputs']['design']['evaluation']
    if (expected['selectionManifest'] != str(PRIOR_SELECTION) or
            expected['selectionManifestSHA256'] != sha(PRIOR_SELECTION)):
        raise ValueError('training registration uses different prior selection')
    rows = expected['selectionRows']
    tasks = design['tasks']
    if len(rows) != 160 or len(tasks) != 5:
        raise ValueError('selection rows are incomplete')
    for level, task in enumerate(tasks, 1):
        if task['name'] != f'L{level}' or task['level'] != level or len(task['rows']) != 32:
            raise ValueError('selection tasks differ')
        prior_task = old['design']['tasks'][level - 1]
        if task['rows'] != prior_task['rows']:
            raise ValueError('replayed scenes differ from prior registered design')
        for row, frozen in zip(task['rows'], rows[(level - 1) * 32:level * 32]):
            if any(row[k] != frozen[k] for k in ('index', 'seed', 'layout', 'variant', 'scene')) or frozen['level'] != level:
                raise ValueError('training selection design differs')
            if set(frozen['files']) != {'case.json', 'environment.bin', 'layout.json'}:
                raise ValueError('training selection scene inventory differs')
            for name, expected_hash in frozen['files'].items():
                if sha(Path(row['scene']) / name) != expected_hash:
                    raise ValueError('training selection scene bytes differ')
    return {'trainingPlanSHA256': sha(TRAIN_PLAN), 'priorSelectionSHA256': sha(PRIOR_SELECTION),
            'priorMonitor': 'failed', 'sceneRows': len(rows),
            'scope': 'reused training-family selection; original monitor remains failed; not independent held-out data'}


def source_paths():
    paths = set(old_source_paths())
    paths.update(loaded_local_sources((base, strict_inventory, metric, training)))
    paths.update((Path(__file__).resolve(), HERE / 'supervise-freeze.py', HERE / 'launch-freeze.py', PRIOR_SELECTION, PRIOR_MONITOR, TRAIN_PLAN,
                  TRAIN_MONITOR / 'completion.json', *training_receipts().values()))
    if any(not path.is_file() for path in paths):
        raise ValueError('selection or training evidence input is missing')
    return sorted(paths)


def current():
    # The selection deliberately reuses existing selection seeds. Do not invoke
    # the old fresh-seed history test or claim this is an unseen evaluation.
    result = old_current(include_history=False)
    plan = json.loads(TRAIN_PLAN.read_text())
    result['history'] = check_reused_selection(result['design'], plan)
    result['trainingCompletion'] = check_training_receipts()
    result['schema'] = 'puppybot.outbound-five-selection-plan.v1'
    result['scope'] = ('reused training-family selection, after fixed epoch-1 training; '
                       'no held-out, execution attestation, physical or promotion claim')
    return result


def verify():
    frozen = json.loads(MANIFEST.read_text())
    if current() != frozen:
        raise ValueError('registered selection inputs changed')
    return frozen


def strict_plus_metrics(frozen):
    strict = old_reaudit(frozen)
    if strict.get('status') != 'diagnostic_only' or strict['pool'].get('status') != 'complete_diagnostic':
        raise ValueError('strict matched saved-game audit did not complete')
    summary, comparisons = {}, {}
    for level in range(1, 6):
        task = f'L{level}'; arms = {}
        for arm in metric.ARMS:
            observed = metric.summarize(metric.load_games(OUTPUT / task, arm), level)
            original = strict['tasks'][task]['results'][arm]
            if (observed['gamesWithDelivery'] != original['gamesWithDelivery'] or
                    observed['deliveries'] != original['deliveries'] or
                    observed['legacyBackForthActions'] != round(original['backForthShare'] * 32 * 300)):
                raise ValueError('inclusive metrics disagree with strict saved-game audit')
            arms[arm] = observed
        summary[task] = arms; comparisons[task] = metric.compare(arms)
    return {'schema': 'puppybot.outbound-five-selection-result.v1', 'status': 'diagnostic_only',
            'strictAudit': strict, 'inclusiveMetrics': summary, 'comparisons': comparisons,
            'scope': ('previously used training-family games only; scene/model/monitor consistency is local, '
                      'not held-out, physical, raw-camera or actor execution attestation; no automatic promotion')}


def verify_saved(frozen):
    saved = json.loads((OUTPUT / 'report.json').read_text())
    if strict_plus_metrics(frozen) != saved:
        raise ValueError('saved selection audit differs')
    return saved


def python_call(function, *args):
    code = ('import importlib.util,sys;'
            's=importlib.util.spec_from_file_location("outbound_selection",sys.argv[1]);'
            'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);'
            'getattr(m,sys.argv[2])(*sys.argv[3:])')
    return [sys.executable, '-I', '-c', code, str(Path(__file__).resolve()), function, *map(str, args)]


def configure_monitor():
    monitor = base.monitor
    monitor.OUTPUT, monitor.MONITOR, monitor.MANIFEST = OUTPUT, MONITOR, MANIFEST
    monitor.REGISTER = Path(__file__).resolve(); monitor.verify_saved = verify_saved
    monitor.worker_command = lambda: python_call('run')
    return strict_inventory.install(monitor, OUTPUT, MONITOR, MANIFEST, verify)


def verify_training_before_registration():
    """Run the real full-data training audit once, under the freeze watchdog."""
    completion = check_training_receipts()
    frozen = training.train.verify_manifest()
    if json.loads((TRAIN_MONITOR / 'frozen-inputs.json').read_text()) != frozen:
        raise ValueError('training frozen inputs differ')
    evidence = json.loads((TRAIN_MONITOR / 'evidence.json').read_text())
    if (evidence.get('status') != 'diagnostic_only' or
            evidence.get('report') != training.verify_training(frozen)):
        raise ValueError('training saved evidence differs')
    training.old.verify_logs(TRAIN_MONITOR)
    if training.final_check(TRAIN_MONITOR, completion['evidenceSHA256']) != {'status': 'final_inventory_verified'}:
        raise ValueError('training final inventory differs')
    if check_training_receipts() != completion:
        raise ValueError('training completion changed during review')
    return completion


def freeze():
    base.guard.require_dedicated_process()
    with base.base.acquire_lock(P / '.l4-matched.lock'):
        strict_inventory.require_fresh(OUTPUT, MONITOR, MANIFEST)
        base.base.require_capacity(P, 38 * 1024**3)
        verify_training_before_registration()
        frozen = current()
        if current() != frozen:
            raise ValueError('selection inputs changed during registration')
        base.write_new(MANIFEST, frozen)
        return frozen


def run():
    return base.run()


def monitor_worker(path):
    configure_monitor(); base.monitor.monitor_worker(path)


def final_check(path, evidence_sha):
    configure_monitor(); print(json.dumps(base.monitor.final_check(path, evidence_sha), sort_keys=True))


def launch():
    outer = json.loads((FREEZE_OUTER / 'result.json').read_text())
    inner = json.loads((FREEZE_MONITOR / 'result.json').read_text())
    outer_supervisor = FREEZE_OUTER / 'supervisor-result.json'
    inner_supervisor = FREEZE_MONITOR / 'supervisor-result.json'
    if (outer.get('status') != 'plan_registered_only' or outer.get('reason') is not None or
            inner.get('status') != 'plan_registered_only' or inner.get('reason') is not None or
            any(path.is_symlink() or not path.is_file() for path in (outer_supervisor, inner_supervisor)) or
            outer.get('supervisorSHA256') != sha(outer_supervisor) or
            inner.get('supervisorSHA256') != sha(inner_supervisor) or
            json.loads(outer_supervisor.read_text()) != outer.get('supervisorStatus') or
            json.loads(inner_supervisor.read_text()) != inner.get('supervisorStatus') or
            outer.get('innerReceiptSHA256') != sha(FREEZE_MONITOR / 'result.json') or
            outer.get('invocationSHA256') != sha(FREEZE_OUTER / 'invocation.json') or
            outer.get('planSHA256') != sha(MANIFEST) or inner.get('planSHA256') != sha(MANIFEST) or
            inner.get('launchSHA256') != sha(FREEZE_MONITOR / 'launch.json') or
            inner.get('workerSHA256') != sha(FREEZE_MONITOR / 'worker-result.json') or
            not training.clean(outer.get('supervisorStatus', {})) or not training.clean(inner.get('supervisorStatus', {}))):
        raise ValueError('selection freeze did not complete cleanly')
    return base.launch()


def describe_configuration():
    # Does not mutate monitor or require a training output; useful for checking
    # that every fresh subprocess imports the v3 bindings.
    print(json.dumps({'output': str(OUTPUT), 'monitor': str(MONITOR), 'manifest': str(MANIFEST),
                      'worker': python_call('run'), 'registrar': str(Path(__file__).resolve())}, sort_keys=True))


# Each spawned worker, monitor, and final checker reloads this module afresh.
base.source_paths = source_paths
base.current = lambda include_history=True: current()
base.verify = verify
base.reaudit = strict_plus_metrics
base.verify_saved = verify_saved
base.python_call = python_call
base.configure_monitor = configure_monitor


if __name__ == '__main__':
    raise SystemExit('Disabled: use a reviewed dedicated freeze and monitored GPU process.')
