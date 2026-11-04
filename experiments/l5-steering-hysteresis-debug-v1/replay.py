#!/usr/bin/env python3
"""Dedicated post-hoc replay using the existing audited simulator machinery.

The CLI is disabled. A reviewed caller must explicitly invoke freeze() and
then launch() in separate dedicated processes. No held-out scenes are read.
"""
import importlib.util
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


plan = load('debug_plan', HERE / 'plan.py')
original = ROOT / 'experiments/l5-steering-hysteresis-v1'
registration = load('debug_base_registration', original / 'register.py')
saved = load('debug_saved_audit', original / 'audit.py')
monitor = load('debug_base_monitor', original / 'monitor.py')
selection = load('debug_selection_snapshot', ROOT / 'datasets/visual-control/chase-v1/levels/audit-selection.py')
base = registration.base
guard = monitor.guard
MANIFEST = plan.P / 'l5-steering-hysteresis-debug-plan-v1.json'
MONITOR = plan.P / 'l5-steering-hysteresis-debug-monitored-v1'
ARM_SECONDS = 600


def write_new(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n')


def current():
    # Re-run the original full registration verification, including its build,
    # runtime chain, model/kernel and named-history pins. Historical overlap is
    # intentional here and is checked against the old frozen plan separately.
    hys = registration.verify()
    kick = json.loads(plan.KICK_PLAN.read_text())
    report = json.loads(plan.KICK_REPORT.read_text())
    plan.preflight(kick, report, hys)
    scenes = []
    for row in plan.design()['conditions']:
        old = next(scene for scene in kick['scenes'] if scene['index'] == row['oldIndex'])
        scenes.append({**row, 'files': old['files'], 'sceneLinks': old['sceneLinks'], 'spawn': old['spawn']})
    paths = [Path(__file__), HERE / 'plan.py', plan.KICK_PLAN, plan.KICK_REPORT, plan.HYS_PLAN,
             original / 'monitor.py', original / 'runner.py', original / 'audit.py',
             ROOT / 'experiments/l5-steering-kick-v1/audit.py',
             ROOT / 'experiments/sim-stop-supervisor/supervisor.py',
             ROOT / 'experiments/sim-stop-supervisor/proxy.py',
             ROOT / 'flex/tests/monitored-visual-v4-smoke.py',
             ROOT / 'datasets/visual-control/chase-v1/levels/audit-selection.py', Path(sys.executable).resolve()]
    for row in plan.design()['conditions']:
        old = prior_game(row)
        paths.extend(old / name for name in ('result.json', 'initial.json', 'chase.jsonl', 'decisions.jsonl',
                                               'steer-probe.jsonl', 'scene/case.json', 'scene/environment.bin'))
    return {'schema': 'puppybot.l5-steering-hysteresis-debug-plan.v1', 'status': 'frozen_before_play',
            'design': plan.design(), 'scenes': scenes,
            'files': {str(path): base.sha(path) for path in paths},
            'basePlanSHA256': base.sha(plan.HYS_PLAN),
            'weightsSHA256': hys['files'][str(plan.MODEL / 'weights.bin')],
            'scope': 'post-hoc known training failures; archived pins and intended commands are not execution attestation'}


def verify():
    frozen = json.loads(MANIFEST.read_text())
    if current() != frozen:
        raise ValueError('registered debug inputs changed')
    return frozen


def freeze():
    guard.require_dedicated_process()
    with base.acquire_lock(plan.P / '.l4-matched.lock'):
        for path in (MANIFEST, plan.OUTPUT, MONITOR):
            base.require_new_output(path)
        base.require_capacity(plan.P, 36 * 1024**3)
        frozen = current()
        if current() != frozen:
            raise ValueError('inputs changed during debug registration')
        base.require_capacity(plan.P, 36 * 1024**3)
        with MANIFEST.open('x') as stream:
            json.dump(frozen, stream, sort_keys=True, indent=2, allow_nan=False)
            stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
        fd = os.open(MANIFEST.parent, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(fd)
        finally: os.close(fd)
        return frozen


def environment():
    return {'PATH': '/usr/bin:/bin', 'HOME': str(Path.home()), 'SDL_VIDEODRIVER': 'offscreen',
            'LD_LIBRARY_PATH': str(ROOT / 'build/flex/rocm-runtime')}


def prior_game(row):
    return (plan.P / 'l5-steering-kick-diagnostic-v1/games' / str(row['oldIndex']) /
            'intervention' / str(row['seed']))


def compare_prior(row, current_path, inputs):
    old = saved.kick.saved_game(prior_game(row), row['seed'], inputs)
    new = saved.kick.saved_game(current_path, row['seed'], inputs)
    keys = ('proposed', 'applied', 'feedback', 'imageSHA256', 'hiddenBeforeSHA256', 'hiddenAfterSHA256')
    first = next((index for index, (a, b) in enumerate(zip(old['probe'], new['probe']))
                  if any(a[key] != b[key] for key in keys)), None)
    return {'sameInitialBytes': old['initialBytes'] == new['initialBytes'],
            'sameStartBytes': old['startBytes'] == new['startBytes'],
            'firstActorDifference': None if first is None else first + 1,
            'priorBackForthSteps': old['backForthSteps'], 'currentBackForthSteps': new['backForthSteps'],
            'priorMetrics': old['metrics'], 'currentMetrics': new['metrics'],
            'scope': 'saved-trace comparison between different controller builds; no execution attestation'}


def reaudit(frozen):
    if (json.loads((plan.OUTPUT / 'inputs.json').read_text()) != frozen or
            frozen.get('design') != plan.design() or len(frozen.get('scenes', [])) != 2):
        raise ValueError('debug manifest differs')
    pairs = []
    for row, expected_row in zip(frozen['scenes'], plan.design()['conditions']):
        if any(row.get(key) != value for key, value in expected_row.items()):
            raise ValueError('debug case differs')
        for arm in plan.design()['arms']:
            output = plan.OUTPUT / 'games' / str(row['index']) / arm
            receipt = plan.OUTPUT / 'monitors' / str(row['index']) / arm
            invocation = {'argv': plan.command(expected_row, arm), 'environment': environment(), 'wallSeconds': ARM_SECONDS}
            if json.loads((receipt / 'invocation.json').read_text()) != invocation:
                raise ValueError('debug invocation differs')
            if not monitor.clean(json.loads((receipt / 'supervisor-result.json').read_text())):
                raise ValueError('unclean arm')
            if selection.snapshot(output / 'policy', plan.MODEL) != frozen['weightsSHA256']:
                raise ValueError('debug policy snapshot differs')
        paths = [plan.OUTPUT / 'games' / str(row['index']) / arm / str(row['seed'])
                 for arm in plan.design()['arms']]
        inputs = {'weightsSHA256': frozen['weightsSHA256'], 'case.json': row['files']['case.json'],
                  'environment.bin': row['files']['environment.bin']}
        pair = saved.saved_three(*paths, row['seed'], inputs)
        pair['priorKickComparison'] = compare_prior(row, paths[1], inputs)
        pairs.append(pair)
    if len(pairs) != 2 or [item['seed'] for item in pairs] != [6800102, 6800107]:
        raise ValueError('incomplete debug pairs')
    return {'schema': 'puppybot.l5-steering-hysteresis-debug-comparison.v1', 'status': 'diagnostic_only',
            'pairs': pairs, 'scope': 'two deliberately selected prior failures; no promotion or generalization claim'}


def run():
    guard.require_dedicated_process()
    with base.acquire_lock(plan.P / '.l4-matched.lock'):
        base.require_new_output(plan.OUTPUT)
        base.require_capacity(plan.P, 36 * 1024**3)
        frozen = verify()
        plan.OUTPUT.mkdir(); write_new(plan.OUTPUT / 'inputs.json', frozen)
        (plan.OUTPUT / 'games').mkdir(); (plan.OUTPUT / 'monitors').mkdir()
        finished = []
        try:
            for row in plan.design()['conditions']:
                (plan.OUTPUT / 'games' / str(row['index'])).mkdir()
                (plan.OUTPUT / 'monitors' / str(row['index'])).mkdir()
                for arm in plan.design()['arms']:
                    base.require_capacity(plan.P, 34 * 1024**3)
                    if verify() != frozen: raise ValueError('inputs changed before arm')
                    receipt = plan.OUTPUT / 'monitors' / str(row['index']) / arm
                    receipt.mkdir(); argv = plan.command(row, arm); env = environment()
                    write_new(receipt / 'invocation.json', {'argv': argv, 'environment': env, 'wallSeconds': ARM_SECONDS})
                    status = base.hidden.supervise(argv, receipt, env, ARM_SECONDS)
                    if not monitor.clean(status) or json.loads((receipt / 'supervisor-result.json').read_text()) != status:
                        raise ValueError('arm supervisor failed')
                    finished.append({'seed': row['seed'], 'arm': arm})
            report = reaudit(frozen)
            if verify() != frozen: raise ValueError('inputs changed during debug replay')
            base.require_capacity(plan.P, 32 * 1024**3)
            write_new(plan.OUTPUT / 'report.json', report)
            return report
        except BaseException as error:
            if not (plan.OUTPUT / 'report.json').exists():
                write_new(plan.OUTPUT / 'partial.json', {'status': 'censored', 'finished': finished, 'reason': str(error)})
            raise


def verify_saved(frozen):
    report = json.loads((plan.OUTPUT / 'report.json').read_text())
    if report != reaudit(frozen): raise ValueError('independent debug re-audit differs')
    return report


def python_call(function, *args):
    code = ('import importlib.util,sys;'
            's=importlib.util.spec_from_file_location("debug_replay",sys.argv[1]);'
            'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);'
            'getattr(m,sys.argv[2])(*sys.argv[3:])')
    return [sys.executable, '-I', '-c', code, str(Path(__file__).resolve()), function, *map(str, args)]


def configure_monitor():
    # Reapply the adapter in every spawned Python process; changing globals in
    # the outer launcher alone would not affect the monitor or final audit.
    monitor.OUTPUT = plan.OUTPUT
    monitor.MONITOR = MONITOR
    monitor.MANIFEST = MANIFEST
    monitor.REGISTER = Path(__file__).resolve()
    monitor.verify_saved = verify_saved
    monitor.worker_command = lambda: python_call('run')


def describe_configuration():
    """Expose process-local adapter bindings for a CPU-only subprocess check."""
    configure_monitor()
    print(json.dumps({'output': str(monitor.OUTPUT), 'registration': str(monitor.REGISTER),
                      'worker': monitor.worker_command()}, sort_keys=True))


def monitor_worker(path):
    configure_monitor()
    monitor.monitor_worker(path)


def final_check(path, evidence_sha):
    configure_monitor()
    result = monitor.final_check(path, evidence_sha)
    print(json.dumps(result, sort_keys=True))


def launch():
    guard.require_dedicated_process()
    configure_monitor(); monitor.require_disk(36)
    frozen = verify()
    for path in (MONITOR, plan.OUTPUT): base.require_new_output(path)
    env = monitor.environment(); command = python_call('monitor_worker', MONITOR)
    MONITOR.mkdir(); outer = MONITOR / 'outer-monitor'; outer.mkdir()
    write_new(MONITOR / 'launch.json', {'command': command, 'environment': env, 'wallSeconds': monitor.OUTER_SECONDS,
              'workerCommand': monitor.worker_command(), 'workerWallSeconds': monitor.WORKER_SECONDS,
              'sourcePins': frozen['files'],
              'scope': 'intended commands, no execution attestation'})
    status = base.hidden.supervise(command, outer, env, monitor.OUTER_SECONDS)
    if not monitor.clean(status) or json.loads((outer / 'supervisor-result.json').read_text()) != status:
        raise RuntimeError('debug monitor failed; retained evidence is censored')
    if (verify() != frozen or json.loads((MONITOR / 'frozen-manifest.json').read_text()) != frozen):
        raise ValueError('debug inputs changed')
    if json.loads((MONITOR / 'monitor-result.json').read_text()).get('status') != 'passed':
        raise ValueError('debug monitor did not pass')
    evidence_path = MONITOR / 'evidence.json'; evidence_sha = base.sha(evidence_path)
    evidence = json.loads(evidence_path.read_text())
    if evidence.get('status') != 'diagnostic_only' or evidence.get('report') != verify_saved(frozen):
        raise ValueError('debug evidence differs')
    monitor.verify_logs(MONITOR); monitor.require_disk(32)
    telemetry_sha = base.sha(MONITOR / 'telemetry.jsonl'); disk_sha = base.sha(MONITOR / 'disk.jsonl')
    outer_sha = base.sha(outer / 'supervisor-result.json')
    frozen_sha = base.sha(MONITOR / 'frozen-manifest.json')
    final_dir = MONITOR / 'final-inventory-monitor'; final_dir.mkdir()
    final_argv = python_call('final_check', MONITOR, evidence_sha)
    write_new(final_dir / 'invocation.json', {'argv': final_argv, 'environment': env,
              'wallSeconds': monitor.FINAL_CHECK_SECONDS})
    invocation_sha = base.sha(final_dir / 'invocation.json')
    final = base.hidden.supervise(final_argv, final_dir, env, monitor.FINAL_CHECK_SECONDS)
    if (not monitor.clean(final) or json.loads((final_dir / 'supervisor-result.json').read_text()) != final or
            json.loads((final_dir / 'client.log').read_text()) != {'status': 'final_inventory_verified'}):
        raise RuntimeError('debug final inventory failed; retained evidence is censored')
    if (verify() != frozen or base.sha(evidence_path) != evidence_sha or
            base.sha(MONITOR / 'telemetry.jsonl') != telemetry_sha or base.sha(MONITOR / 'disk.jsonl') != disk_sha or
            base.sha(outer / 'supervisor-result.json') != outer_sha or
            base.sha(MONITOR / 'frozen-manifest.json') != frozen_sha or
            base.sha(final_dir / 'invocation.json') != invocation_sha):
        raise ValueError('debug inputs or evidence changed')
    monitor.require_disk(32)
    write_new(MONITOR / 'completion.json', {'status': 'diagnostic_only', 'evidenceSHA256': evidence_sha,
              'telemetrySHA256': telemetry_sha, 'diskSHA256': disk_sha,
              'outerSupervisorStatusSHA256': outer_sha, 'frozenManifestSHA256': frozen_sha,
              'finalInventoryInvocationSHA256': invocation_sha,
              'finalInventoryStatusSHA256': base.sha(final_dir / 'supervisor-result.json'),
              'scope': 'two post-hoc training cases; no actor execution or physical attestation'})
    return evidence['report']


if __name__ == '__main__':
    raise SystemExit('Disabled; explicit reviewed dedicated-process freeze and launch required.')
