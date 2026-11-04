#!/usr/bin/env python3
"""Pre-registered four-arm replay of reused training-family games.

This is a local diagnostic, not independent selection or held-out evidence.
Direct execution is disabled; no original experiment is changed.
"""
import importlib.util
import json
import math
import os
import shutil
import subprocess
import sys
import time
import types
from pathlib import Path
from unittest import mock


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
P = ROOT / 'build/flex/sim/levels-v2/pitch82'
OUTPUT = P / 'fresh-policy-selection-v4'
MONITOR = P / 'fresh-policy-selection-monitored-v4'
PLAN = P / 'fresh-policy-selection-plan-v4.json'
PRIOR_PLAN = P / 'fresh-policy-selection-plan-v3.json'
PRIOR_OUTPUT = P / 'fresh-policy-selection-v3'
PRIOR_MONITOR = P / 'fresh-policy-selection-monitored-v3'
TRAINING = P / 'parent-route-full-pair-v1'
TRAINING_PLAN = P / 'parent-route-full-pair-plan-v1.json'
LOCK = P / '.l4-matched.lock'
ARMS = ('parent', 'control', 'treatment', 'teacher')
NEW_ARMS = ('control', 'treatment')
MODELS = {'parent': P / 'search-dagger-l35-4workers/student-s1',
          'control': TRAINING / 'fixed-control', 'treatment': TRAINING / 'fixed-treatment'}
WEIGHTS = {'parent': '9c586f40ad6fc1a13a17f325cd3b33da5aca07e4790ee0922fd59049cd89f0d1',
           'control': 'f78cd4346b42e7318e8b7252709b3e9a74fa31eca13e8ab6cc3c4a786172648d',
           'treatment': '37dc95406fb3c81590d4f1c83fd0bf2327a740e6c1d86943284c7bc83e2b6036'}
TRAIN_COMPLETION = '567cdbeaa77cf65e0df09d69f12771f8100dcab71e15f59bdb8ae0aa3fe3b21f'
PRIOR_COMPLETION = 'd37c1b6569d0ff7b68f1574933c9b68e46db04824c6002963adbeea4ad6fc6cf'
GIB = 1024 ** 3
OUTER_SECONDS = 36000
ARM_SECONDS = 3600
FINAL_SECONDS = 3600


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


base = load('four_arm_legacy_selection', ROOT / 'experiments/fresh-policy-comparison-v1/selection.py')
metric = load('four_arm_inclusive_metrics', ROOT / 'experiments/outbound-five-selection-metrics-v1/metrics.py')
catalog = load('four_arm_catalog', ROOT / 'experiments/fresh-policy-catalog-monitor-v1/adapter.py')
pair = load('four_arm_training', ROOT / 'experiments/parent-route-full-pair-v1/monitor.py')
guard = load('four_arm_guard', ROOT / 'experiments/dock-turn-rendered-probe-v1/guardian.py')
guard_owner = load('four_arm_live_lock', ROOT / 'experiments/dock-turn-rendered-probe-v1/run.py')
previous = load('four_arm_prior_v3', ROOT / 'experiments/outbound-five-selection-runner-v1/runner.py')
old_design, old_source_paths, old_current, old_reaudit = base.design, base.source_paths, base.current, base.reaudit
sha = base.base.sha


def design():
    value = old_design()
    value['arms'] = list(ARMS)
    value['newArms'] = list(NEW_ARMS)
    value['reusedArms'] = {'parent': str(PRIOR_OUTPUT), 'teacher': str(PRIOR_OUTPUT)}
    value['models'] = {name: str(path) for name, path in MODELS.items()}
    value['scope'] = ('reused training-family games, including two fitting scenes; '
                      'no independent selection, held-out, physical or promotion claim')
    return value


base.MODELS = MODELS
base.OUTPUT, base.MONITOR, base.MANIFEST = OUTPUT, MONITOR, PLAN
base.design = design
base.auditor.ARMS = NEW_ARMS
metric.ARMS = ARMS


def regular(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f'missing or linked input: {path}')
    return path


def read(path):
    return json.loads(regular(path).read_text())


def training_receipts():
    completion = read(TRAINING / 'completion.json')
    if (sha(TRAINING / 'completion.json') != TRAIN_COMPLETION or
            completion.get('status') != 'full_epoch_pair_diagnostic_only' or
            completion.get('planSHA256') != sha(TRAINING_PLAN)):
        raise ValueError('matched training completion differs')
    retained = {'coordinatorSHA256': TRAINING / 'coordinator-result.json',
                'guardianResultSHA256': TRAINING / 'guardian-result.json',
                'guardianTelemetrySHA256': TRAINING / 'guardian-telemetry.jsonl'}
    for key, path in retained.items():
        if completion.get(key) != sha(regular(path)):
            raise ValueError(f'training receipt changed: {key}')
    result, final = read(TRAINING / 'coordinator-result.json'), read(TRAINING / 'final-result.json')
    if (result.get('status') != 'full_epoch_pair_diagnostic_only' or
            result.get('planSHA256') != completion['planSHA256'] or
            final.get('status') != 'full_epoch_pair_diagnostic_only' or
            final.get('planSHA256') != completion['planSHA256']):
        raise ValueError('training report does not bind the registered plan')
    for path, expected in result['evidenceSHA256'].items():
        if sha(regular(TRAINING / path)) != expected:
            raise ValueError(f'training evidence changed: {path}')
    guardian_result = read(TRAINING / 'guardian-result.json')
    if (guardian_result.get('status') != 'passed' or guardian_result.get('reason') is not None or
            type(guardian_result.get('coordinatorExit')) is not int or guardian_result['coordinatorExit'] != 0 or
            guardian_result.get('descendantsTerminated') is not False or
            guardian_result.get('diskEmergency') is not False):
        raise ValueError('training guardian did not pass')
    for arm in ('control', 'treatment'):
        package = pair.audit.verify_package(pair.plan, arm)
        if (package['weightsSHA256'] != WEIGHTS[arm] or
                final['report']['arms'][arm]['fixedPackage'] != package):
            raise ValueError(f'fixed epoch-one package differs: {arm}')
    for arm, path in MODELS.items():
        if sha(regular(path / 'weights.bin')) != WEIGHTS[arm]:
            raise ValueError(f'wrong {arm} model')
    return {'completionSHA256': TRAIN_COMPLETION, 'planSHA256': completion['planSHA256'],
            'finalResultSHA256': sha(TRAINING / 'final-result.json'),
            'coordinatorSHA256': completion['coordinatorSHA256'],
            'scope': 'retained matched-training evidence, not execution attestation'}


def prior_receipts():
    done = read(PRIOR_MONITOR / 'completion.json')
    if sha(PRIOR_MONITOR / 'completion.json') != PRIOR_COMPLETION or done.get('status') != 'diagnostic_only':
        raise ValueError('prior selection did not complete')
    paths = {'evidenceSHA256': 'evidence.json', 'launchSHA256': 'launch.json',
             'telemetrySHA256': 'telemetry.jsonl', 'diskSHA256': 'disk.jsonl',
             'monitorResultSHA256': 'monitor-result.json', 'outerSupervisorStatusSHA256': 'outer-monitor/supervisor-result.json',
             'frozenManifestSHA256': 'frozen-manifest.json',
             'finalInventoryInvocationSHA256': 'final-inventory-monitor/invocation.json',
             'finalInventoryStatusSHA256': 'final-inventory-monitor/supervisor-result.json',
             'finalInventoryResultSHA256': 'final-inventory-monitor/client.log'}
    for key, relative in paths.items():
        if done.get(key) != sha(regular(PRIOR_MONITOR / relative)):
            raise ValueError(f'prior selection evidence changed: {key}')
    if (read(PRIOR_MONITOR / 'monitor-result.json') != {'status': 'passed'} or
            not base.monitor.clean(read(PRIOR_MONITOR / 'outer-monitor/supervisor-result.json')) or
            not base.monitor.clean(read(PRIOR_MONITOR / 'final-inventory-monitor/supervisor-result.json')) or
            read(PRIOR_MONITOR / 'final-inventory-monitor/client.log') != {'status': 'final_inventory_verified'}):
        raise ValueError('prior selection monitor did not pass')
    old = read(PRIOR_PLAN)
    if (done['frozenManifestSHA256'] != sha(PRIOR_PLAN) or
            old != read(PRIOR_MONITOR / 'frozen-manifest.json') or
            old != read(PRIOR_OUTPUT / 'inputs.json')):
        raise ValueError('prior selection plans differ')
    if (old['design']['models'].get('control') != str(MODELS['parent']) or
            old['files'].get(str(MODELS['parent'] / 'weights.bin')) != WEIGHTS['parent']):
        raise ValueError('reused parent model identity differs')
    tasks, prior_tasks = design()['tasks'], old['design']['tasks']
    if ([task['name'] for task in tasks] != [f'L{i}' for i in range(1, 6)] or
            [task['name'] for task in prior_tasks] != [f'L{i}' for i in range(1, 6)] or
            any(len(task['rows']) != 32 for task in tasks + prior_tasks)):
        raise ValueError('prior selection rows incomplete')
    for task, prior in zip(tasks, prior_tasks):
        if (task['name'], task['level'], task['rows']) != (prior['name'], prior['level'], prior['rows']):
            raise ValueError('reused selection rows differ')
        for row in task['rows']:
            for name in ('case.json', 'environment.bin', 'layout.json'):
                path = Path(row['scene']) / name
                if old['files'].get(str(path)) != sha(path):
                    raise ValueError('reused scene bytes differ')
    for path in (ROOT / 'build/flex/control/control', ROOT / 'build/flex/control/simulator',
                 ROOT / 'build/flex/sim/puppybot.bin', base.EVALUATE):
        if old['files'].get(str(path)) != sha(path):
            raise ValueError('replay binary or evaluator differs from prior run')
    if base.old.runtime_chain() != old.get('runtime'):
        raise ValueError('GPU runtime chain differs from prior run')
    return {'completionSHA256': sha(PRIOR_MONITOR / 'completion.json'),
            'priorPlanSHA256': sha(PRIOR_PLAN), 'sceneRows': 160,
            'scope': 'reused training-family scenes and legacy simulator; not independent held-out data'}


def loaded_sources(roots):
    pending, seen, paths = list(roots), set(), set()
    while pending:
        module = pending.pop()
        if not isinstance(module, types.ModuleType) or id(module) in seen:
            continue
        seen.add(id(module)); path = getattr(module, '__file__', None)
        if path:
            path = Path(path).resolve()
            if path.suffix == '.py' and path.is_relative_to(ROOT):
                paths.add(path)
                pending.extend(value for value in vars(module).values() if isinstance(value, types.ModuleType))
    return paths


def source_paths():
    paths = set(old_source_paths())
    paths.update(loaded_sources((base, metric, catalog, pair, guard, guard_owner, previous)))
    paths.update((Path(__file__).resolve(), PRIOR_PLAN, PRIOR_OUTPUT / 'report.json',
                  PRIOR_MONITOR / 'completion.json', PRIOR_MONITOR / 'evidence.json', TRAINING_PLAN,
                  TRAINING / 'completion.json', TRAINING / 'coordinator-result.json',
                  TRAINING / 'guardian-result.json', TRAINING / 'guardian-telemetry.jsonl', TRAINING / 'final-result.json'))
    return sorted(paths)


def current():
    value = old_current(include_history=False)
    value['history'] = prior_receipts()
    value['trainingCompletion'] = training_receipts()
    value['schema'] = 'puppybot.matched-four-arm-diagnostic-plan.v1'
    value['scope'] = ('reused training-family scenes, including two fitting cases; '
                      'no independent selection, held-out, physical or promotion claim')
    return value


def verify():
    frozen = read(PLAN)
    if current() != frozen:
        raise ValueError('registered diagnostic inputs changed')
    return frozen


def pairs(arms):
    if set(arms) != set(ARMS):
        raise ValueError('all four matched arms required')
    for item in arms.values():
        if item['games'] != 32 or item['actions'] != 9600:
            raise ValueError('incomparable game horizon')
    result = {}
    for name in ('control', 'treatment'):
        against = {}
        candidate = arms[name]
        for reference in ('parent', 'teacher'):
            other = arms[reference]
            left, right = candidate['perGame'], other['perGame']
            if ([game['seed'] for game in left] != list(range(base.SEED, base.SEED + 32)) or
                    [game['seed'] for game in right] != list(range(base.SEED, base.SEED + 32))):
                raise ValueError('unmatched game order')
            wins = sum(a['completedDelivery'] and not b['completedDelivery'] for a, b in zip(left, right))
            losses = sum(not a['completedDelivery'] and b['completedDelivery'] for a, b in zip(left, right))
            against[reference] = {'deliveryRateAtLeastReference': candidate['deliveries'] >= other['deliveries'],
                                  'deliveredGamesAtLeastReference': candidate['gamesWithDelivery'] >= other['gamesWithDelivery'],
                                  'pairedGameWins': wins, 'pairedGameLosses': losses}
        result[name] = against
    return {'comparisons': result, 'scope': 'matched horizons; not a held-out or promotion decision'}


def reaudit(frozen):
    if read(OUTPUT / 'inputs.json') != frozen:
        raise ValueError('output plan differs')
    old = read(PRIOR_OUTPUT / 'report.json')
    strict, summary, comparisons = {}, {}, {}
    for level in range(1, 6):
        task = f'L{level}'; arms = {}
        task_info = design()['tasks'][level - 1]
        for arm in NEW_ARMS:
            receipt = OUTPUT / 'supervisors' / task / arm
            expected = {'argv': base.command(task_info, arm), 'environment': base.environment(level),
                        'wallSeconds': ARM_SECONDS}
            if (read(receipt / 'invocation.json') != expected or
                    not base.monitor.clean(read(receipt / 'supervisor-result.json'))):
                raise ValueError('new arm invocation or supervisor differs')
        result = base.auditor.audit_task(task, PRIOR_OUTPUT / task, OUTPUT / task,
                                         {name: MODELS[name] for name in NEW_ARMS})
        if result.get('status') != 'complete_diagnostic':
            raise ValueError(f'cross-root matched game audit censored: {task}')
        strict[task] = result
        for arm in ARMS:
            root = PRIOR_OUTPUT / task if arm in ('parent', 'teacher') else OUTPUT / task
            saved_arm = 'control' if arm == 'parent' else arm
            games = metric.load_games(root, saved_arm)
            if any('backForthMetric' in game['result'] for game in games):
                raise ValueError('expected legacy score format from pinned simulator')
            observed = metric.summarize(games, level)
            original = (old['strictAudit']['tasks'][task]['results'][saved_arm]
                        if arm in ('parent', 'teacher') else result['results'][arm])
            if (observed['gamesWithDelivery'] != original['gamesWithDelivery'] or
                    observed['deliveries'] != original['deliveries'] or
                    observed['legacyBackForthActions'] != round(original['backForthShare'] * 9600)):
                raise ValueError('inclusive metrics disagree with strict audit')
            arms[arm] = observed
        summary[task], comparisons[task] = arms, pairs(arms)
    return {'schema': 'puppybot.matched-four-arm-diagnostic-result.v1', 'status': 'diagnostic_only',
            'strictAudit': strict, 'inclusiveMetrics': summary, 'comparisons': comparisons,
            'scope': ('reused fitting-family virtual-fetch games, including two fitted cases; '
                      'parent and teacher came from separately monitored v3; '
                      'not independent selection, held-out, physical or execution attestation')}


def deep_inputs(frozen):
    """Reconstruct retained prior and training output under an outer watchdog."""
    if current() != frozen:
        raise ValueError('inputs changed before deep review')
    old = read(PRIOR_PLAN)
    evidence = read(PRIOR_MONITOR / 'evidence.json')
    report = previous.verify_saved(old)
    if (evidence.get('status') != 'diagnostic_only' or evidence.get('report') != report or
            report != read(PRIOR_OUTPUT / 'report.json')):
        raise ValueError('reused prior selection report differs')
    prior_inventory()
    previous.base.monitor.verify_logs(PRIOR_MONITOR)
    training = read(TRAINING / 'final-result.json')
    if pair.verify_arms() != training.get('report'):
        raise ValueError('matched training reports differ')
    training_inventory()
    launch = read(TRAINING / 'launcher.json'); guardian = read(TRAINING / 'guardian-launch.json')
    if (launch.get('planSHA256') != sha(TRAINING_PLAN) or
            launch.get('environment') != pair.plan.smoke.plan.environment() or
            not isinstance(launch.get('argv'), list) or not launch['argv'] or
            type(guardian.get('parentPID')) is not int or launch['argv'][-1] != str(guardian['parentPID']) or
            type(guardian.get('guardianPID')) is not int):
        raise ValueError('historical training guardian identity differs')
    # This validates retained log consistency only, not a live historical PID.
    with mock.patch.object(pair.plan.smoke.plan.paired.os, 'getpid', return_value=guardian['parentPID']):
        pair.verify_guardian(guardian['guardianPID'])
    if current() != frozen:
        raise ValueError('inputs changed during deep review')
    return {'status': 'retained_inputs_consistent', 'priorGames': 480,
            'scope': 'local saved-output consistency; no live actor or GPU attestation'}


def prior_inventory():
    old = read(PRIOR_PLAN); evidence = read(PRIOR_MONITOR / 'evidence.json')
    expected = catalog.postrun.expected_catalogs(old)
    if catalog.postrun.inventory(PRIOR_OUTPUT, expected) != evidence.get('files'):
        raise ValueError('reused prior selection inventory differs')
    return {'status': 'prior_inventory_consistent', 'evidenceSHA256': sha(PRIOR_MONITOR / 'evidence.json')}


def training_inventory():
    evidence = read(TRAINING / 'final-result.json')
    if pair.inventory() != evidence.get('inventory'):
        raise ValueError('matched training output inventory differs')
    return {'status': 'training_inventory_consistent', 'finalResultSHA256': sha(TRAINING / 'final-result.json')}


def output_inventory(frozen):
    return catalog.postrun.inventory(OUTPUT, catalog.postrun.expected_catalogs(frozen))


def disk(gib):
    roots = (ROOT, Path.home(), P)
    free = min(shutil.disk_usage(path).free for path in roots)
    if free < gib * GIB:
        raise RuntimeError(f'free disk below {gib} GiB')
    return free


def write_new(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False); stream.write('\n')
        stream.flush(); os.fsync(stream.fileno())


def freeze():
    base.guard.require_dedicated_process()
    with base.base.acquire_lock(LOCK):
        catalog.require_fresh(OUTPUT, MONITOR, PLAN)
        disk(38)
        frozen = current()
        deep_inputs(frozen)
        if current() != frozen:
            raise ValueError('inputs changed during diagnostic registration')
        disk(34); write_new(PLAN, frozen)
        if verify() != frozen:
            raise ValueError('registered diagnostic differs')
        return frozen


def child_command(function):
    if function not in ('coordinator', 'final_check'):
        raise ValueError('unknown diagnostic child')
    code = ('import importlib.util,sys;s=importlib.util.spec_from_file_location("diag",sys.argv[1]);'
            'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);getattr(m,sys.argv[2])()')
    return [sys.executable, '-I', '-c', code, str(Path(__file__).resolve()), function]


def environment():
    return base.monitor.environment()


def child_environment():
    env = environment()
    for key in ('PUPPY_TURN_GUARD_PID', 'PUPPY_TURN_GUARD_FD', 'PUPPY_TURN_GUARD_OUTPUT'):
        if key not in os.environ:
            raise RuntimeError('guardian identity missing')
        env[key] = os.environ[key]
    return env


def resources():
    marker = MONITOR / 'baseline-passed.json'
    passed = marker.is_file() and not marker.is_symlink()
    if passed:
        value = read(marker); tick = value.get('monotonicSeconds')
        if (value.get('status') != 'passed' or type(tick) not in (int, float) or
                not math.isfinite(tick) or not 0 < tick <= time.monotonic()):
            raise ValueError('invalid baseline marker')
    gpu = base.monitor.telemetry.telemetry(base.monitor.telemetry.DEVICE)
    volumes = {name: shutil.disk_usage(path).free for name, path in
               (('workspace', ROOT), ('home', Path.home()), ('output', MONITOR))}
    return {'freeBytes': min(volumes.values()), 'volumes': volumes,
            'gpuFreeBytes': gpu['freeBytes'], 'gpuTotalBytes': gpu['totalBytes'],
            'gpuUsedBytes': gpu['usedBytes'], 'gpuBusyPercent': gpu['busyPercent'],
            'baselinePassed': passed}


def baseline():
    rows = []; consecutive = 0
    with (MONITOR / 'baseline.jsonl').open('x') as log:
        while True:
            row = base.monitor.telemetry.sample(log, 'baseline'); rows.append(row)
            if row['freeBytes'] < 6 * GIB:
                raise ValueError('baseline GPU memory below 6 GiB')
            consecutive = consecutive + 1 if row['busyPercent'] > 10 else 0
            if consecutive >= 5:
                raise ValueError('GPU busy during baseline')
            remaining = 30 - (row['monotonicSeconds'] - rows[0]['monotonicSeconds'])
            if remaining <= 0:
                break
            time.sleep(min(1, remaining))
    pair.check_baseline(rows)
    marker = MONITOR / 'baseline-passed.json'; temporary = MONITOR / 'baseline-passed.tmp'
    write_new(temporary, {'status': 'passed', 'monotonicSeconds': time.monotonic()})
    os.link(temporary, marker); temporary.unlink()


def supervisor(name, function, seconds):
    directory = MONITOR / name; directory.mkdir()
    argv = child_command(function); env = child_environment()
    write_new(directory / 'invocation.json', {'argv': argv, 'environment': env, 'wallSeconds': seconds})
    status = base.base.hidden.supervise(argv, directory, env, seconds)
    if (not base.monitor.clean(status) or read(directory / 'supervisor-result.json') != status):
        raise RuntimeError(f'{name} failed or left descendants; evidence retained')
    return status


def final_check():
    guard_owner.require_guardian()
    frozen = verify(); digest = sha(PLAN)
    report = read(OUTPUT / 'report.json')
    if reaudit(frozen) != report:
        raise ValueError('diagnostic report changed')
    before = output_inventory(frozen)
    deep = deep_inputs(frozen)
    prior_inventory(); training_inventory()
    if output_inventory(frozen) != before or verify() != frozen or sha(PLAN) != digest:
        raise ValueError('inputs or diagnostic output changed during final review')
    guard_owner.require_guardian()
    write_new(MONITOR / 'final-result.json', {'status': 'diagnostic_only', 'planSHA256': digest,
              'reportSHA256': sha(OUTPUT / 'report.json'), 'inventory': before, 'deepInputs': deep})


def coordinator():
    guard_owner.require_guardian()
    if os.environ.get('PUPPY_TURN_GUARD_OUTPUT') != str(MONITOR):
        raise RuntimeError('guardian output identity differs')
    frozen = verify(); digest = sha(PLAN)
    baseline(); guard_owner.require_guardian(); disk(38)
    if OUTPUT.exists() or OUTPUT.is_symlink():
        raise FileExistsError('diagnostic output exists; retain it')
    OUTPUT.mkdir(); write_new(OUTPUT / 'inputs.json', frozen)
    (OUTPUT / 'supervisors').mkdir(); completed = []
    try:
        for task in design()['tasks']:
            task_root = OUTPUT / task['name']; task_root.mkdir()
            (OUTPUT / 'supervisors' / task['name']).mkdir()
            for arm in NEW_ARMS:
                guard_owner.require_guardian(); free = disk(34)
                if verify() != frozen or sha(PLAN) != digest:
                    raise ValueError('diagnostic inputs changed before arm')
                directory = OUTPUT / 'supervisors' / task['name'] / arm; directory.mkdir()
                argv = base.command(task, arm); env = base.environment(task['level'])
                write_new(directory / 'invocation.json', {'argv': argv, 'environment': env, 'wallSeconds': ARM_SECONDS})
                write_new(directory / 'disk-before.json', {'freeBytes': free, 'floorGiB': 34})
                status = base.base.hidden.supervise(argv, directory, env, ARM_SECONDS)
                if not base.monitor.clean(status) or read(directory / 'supervisor-result.json') != status:
                    raise RuntimeError('diagnostic arm failed; evidence retained')
                guard_owner.require_guardian(); disk(34)
                completed.append([task['name'], arm])
        report = reaudit(frozen)
        if verify() != frozen or sha(PLAN) != digest:
            raise ValueError('diagnostic inputs changed after games')
        disk(34); write_new(OUTPUT / 'report.json', report)
        supervisor('final-supervisor', 'final_check', FINAL_SECONDS)
        final = read(MONITOR / 'final-result.json')
        if (final.get('status') != 'diagnostic_only' or final.get('planSHA256') != digest or
                final.get('reportSHA256') != sha(OUTPUT / 'report.json')):
            raise ValueError('diagnostic final audit missing')
        write_new(MONITOR / 'coordinator-result.json', {'status': 'diagnostic_only', 'planSHA256': digest,
                  'finalSHA256': sha(MONITOR / 'final-result.json'),
                  'finalInvocationSHA256': sha(MONITOR / 'final-supervisor/invocation.json'),
                  'finalStatusSHA256': sha(MONITOR / 'final-supervisor/supervisor-result.json'),
                  'finalLogSHA256': sha(MONITOR / 'final-supervisor/client.log')})
    except BaseException as error:
        if not (OUTPUT / 'report.json').exists():
            write_new(OUTPUT / 'partial.json', {'status': 'censored', 'completed': completed, 'reason': str(error)})
        raise


def guardian_entry(parent_pid):
    result = guard.run(MONITOR, LOCK, child_command('coordinator'), environment(), int(parent_pid),
                       resources, wall_seconds=OUTER_SECONDS)
    if result.get('status') != 'passed':
        raise RuntimeError('diagnostic guardian failed; partial outputs retained')


def guardian_command(parent_pid):
    code = ('import importlib.util,sys;s=importlib.util.spec_from_file_location("diag",sys.argv[1]);'
            'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.guardian_entry(sys.argv[2])')
    return [sys.executable, '-I', '-c', code, str(Path(__file__).resolve()), str(parent_pid)]


def verify_guardian(pid):
    launch = read(MONITOR / 'guardian-launch.json'); result = read(MONITOR / 'guardian-result.json')
    outer = read(MONITOR / 'launcher.json')
    rows = [json.loads(line) for line in regular(MONITOR / 'guardian-telemetry.jsonl').read_text().splitlines()]
    active = [row for row in rows if row.get('phase') == 'active']
    cleanup = [row for row in rows if row.get('phase') == 'cleanup']
    env = dict(environment())
    env.update(PUPPY_TURN_GUARD_PID=str(pid),
               PUPPY_TURN_GUARD_FD=launch.get('environment', {}).get('PUPPY_TURN_GUARD_FD'),
               PUPPY_TURN_GUARD_OUTPUT=str(MONITOR))
    if (type(pid) is not int or pid <= 1 or type(outer.get('parentPID')) is not int or
            outer['parentPID'] <= 1 or outer.get('argv') != guardian_command(outer['parentPID']) or
            outer.get('environment') != environment() or outer.get('planSHA256') != sha(PLAN) or
            launch.get('guardianPID') != pid or
            type(launch.get('coordinatorPID')) is not int or launch['coordinatorPID'] <= 1 or
            launch.get('parentPID') != outer.get('parentPID') or launch.get('wallSeconds') != OUTER_SECONDS or
            launch.get('command') != child_command('coordinator') or launch.get('environment') != env or
            not isinstance(env['PUPPY_TURN_GUARD_FD'], str) or not env['PUPPY_TURN_GUARD_FD'].isdigit() or
            result.get('status') != 'passed' or
            result.get('reason') is not None or type(result.get('coordinatorExit')) is not int or
            result['coordinatorExit'] != 0 or result.get('descendantsTerminated') is not False or
            result.get('diskEmergency') is not False or len(active) < 1 or len(cleanup) < 2 or
            result.get('samples') != len(rows) or
            [row.get('phase') for row in rows] != ['active'] * len(active) + ['cleanup'] * len(cleanup)):
        raise ValueError('guardian invocation or completion differs')
    times = [row.get('monotonicSeconds') for row in rows]
    if (any(type(t) not in (int, float) or not math.isfinite(t) for t in times) or
            any(not 0 < b - a <= 2.5 for a, b in zip(times, times[1:])) or
            not launch['startedMonotonic'] <= times[0] <= result['observedDoneMonotonic'] <= times[-1] <= result['endedMonotonic'] or
            times[0] - launch['startedMonotonic'] > 2.5 or result['endedMonotonic'] - times[-1] > 2.5):
        raise ValueError('guardian sample coverage incomplete')
    marker = read(MONITOR / 'baseline-passed.json'); marker_tick = marker.get('monotonicSeconds')
    if (marker.get('status') != 'passed' or type(marker_tick) not in (int, float) or
            not math.isfinite(marker_tick) or not launch['startedMonotonic'] <= marker_tick <= result['observedDoneMonotonic']):
        raise ValueError('baseline marker differs')
    seen = False
    for row in rows:
        volumes, passed = row.get('volumes'), row.get('baselinePassed')
        if (type(passed) is not bool or (seen and not passed) or
                (passed and row['monotonicSeconds'] < marker_tick)):
            raise ValueError('guardian baseline phase differs')
        seen = seen or passed; floor = 34 if passed else 38
        if (not isinstance(volumes, dict) or set(volumes) != {'workspace', 'home', 'output'} or
                any(type(v) is not int or v < floor * GIB for v in volumes.values()) or
                row.get('freeBytes') != min(volumes.values()) or
                any(type(row.get(k)) is not int for k in ('gpuFreeBytes', 'gpuTotalBytes', 'gpuUsedBytes', 'gpuBusyPercent')) or
                row['gpuTotalBytes'] <= 0 or not 0 <= row['gpuUsedBytes'] <= row['gpuTotalBytes'] or
                row['gpuFreeBytes'] != row['gpuTotalBytes'] - row['gpuUsedBytes'] or
                row['gpuFreeBytes'] < 2 * GIB or not 0 <= row['gpuBusyPercent'] <= 100):
            raise ValueError('guardian resource sample differs')
    if not seen:
        raise ValueError('guardian did not observe baseline completion')
    baseline_rows = [json.loads(line) for line in regular(MONITOR / 'baseline.jsonl').read_text().splitlines()]
    pair.check_baseline(baseline_rows)
    if not (launch['startedMonotonic'] <= baseline_rows[0]['monotonicSeconds'] <=
            baseline_rows[-1]['monotonicSeconds'] <= marker_tick <= result['observedDoneMonotonic']):
        raise ValueError('baseline timing differs from guardian coverage')
    return result


def launch():
    base.guard.require_dedicated_process()
    if OUTPUT.exists() or OUTPUT.is_symlink() or MONITOR.exists() or MONITOR.is_symlink():
        raise FileExistsError('diagnostic output exists; retain it')
    disk(38); frozen = verify(); digest = sha(PLAN)
    MONITOR.mkdir()
    argv = guardian_command(os.getpid())
    write_new(MONITOR / 'launcher.json', {'argv': argv, 'environment': environment(),
                                          'parentPID': os.getpid(), 'planSHA256': digest})
    with (MONITOR / 'guardian.log').open('x') as log:
        process = subprocess.Popen(argv, cwd=ROOT, env=environment(), stdout=log, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        status = process.wait()
    if status != 0:
        raise RuntimeError('diagnostic guardian failed; retained outputs censored')
    verify_guardian(process.pid); disk(34)
    result = read(MONITOR / 'coordinator-result.json'); final = read(MONITOR / 'final-result.json')
    expected = {'argv': child_command('final_check'),
                'environment': read(MONITOR / 'guardian-launch.json')['environment'],
                'wallSeconds': FINAL_SECONDS}
    if (result.get('status') != 'diagnostic_only' or result.get('planSHA256') != digest or
            final.get('status') != 'diagnostic_only' or final.get('planSHA256') != digest or
            result.get('finalSHA256') != sha(MONITOR / 'final-result.json') or
            result.get('finalInvocationSHA256') != sha(MONITOR / 'final-supervisor/invocation.json') or
            result.get('finalStatusSHA256') != sha(MONITOR / 'final-supervisor/supervisor-result.json') or
            result.get('finalLogSHA256') != sha(MONITOR / 'final-supervisor/client.log') or
            read(MONITOR / 'final-supervisor/invocation.json') != expected or
            not base.monitor.clean(read(MONITOR / 'final-supervisor/supervisor-result.json')) or
            final.get('reportSHA256') != sha(OUTPUT / 'report.json') or
            final.get('inventory') != output_inventory(frozen) or
            verify() != frozen or sha(PLAN) != digest):
        raise ValueError('diagnostic final evidence changed after guardian')
    prior_inventory(); training_inventory()
    if verify() != frozen or sha(PLAN) != digest:
        raise ValueError('diagnostic inputs changed during post-guardian prior review')
    disk(34)
    write_new(MONITOR / 'completion.json', {'status': 'diagnostic_only', 'planSHA256': digest,
              'coordinatorSHA256': sha(MONITOR / 'coordinator-result.json'),
              'finalSHA256': sha(MONITOR / 'final-result.json'),
              'guardianLaunchSHA256': sha(MONITOR / 'guardian-launch.json'),
              'guardianResultSHA256': sha(MONITOR / 'guardian-result.json'),
              'guardianTelemetrySHA256': sha(MONITOR / 'guardian-telemetry.jsonl'),
              'baselineSHA256': sha(MONITOR / 'baseline.jsonl'),
              'scope': 'two new arms and sealed historical references on reused fitting-family scenes; no promotion'})
    return {'status': 'diagnostic_only', 'planSHA256': digest, 'reportSHA256': sha(OUTPUT / 'report.json')}


base.source_paths = source_paths
base.current = lambda include_history=True: current()
base.verify = verify
base.reaudit = reaudit


if __name__ == '__main__':
    raise SystemExit('Disabled: registration, supervision, and independent review are required.')
