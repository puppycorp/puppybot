#!/usr/bin/env python3
"""Fresh training-family selection comparison; direct CLI is disabled.

Explicitly reviewed dedicated processes may call freeze() then launch().
The held-out catalog is neither loaded nor evaluated.
"""
import importlib.util
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
P = ROOT / 'build/flex/sim/levels-v2/pitch82'
SCENES = ROOT / 'build/flex/sim/expanded-rooms-v1/scenes'
SEED = 7820000
GAMES = 32
MANIFEST = P / 'fresh-policy-selection-plan-v1.json'
OUTPUT = P / 'fresh-policy-selection-v1'
MONITOR = P / 'fresh-policy-selection-monitored-v1'
MODELS = {
    'control': P / 'search-dagger-l35-4workers/student-s1',
    'treatment': P / 'search-dagger-heading/models/heading-epoch8-pair/treatment',
}
EVALUATE = ROOT / 'datasets/visual-control/chase-v1/evaluate.sh'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


old = load('fresh_prior_inventory', ROOT / 'experiments/l5-steering-kick-v1/register.py')
base = old.base
guard = load('fresh_process_guard', ROOT / 'experiments/sim-stop-supervisor/supervisor.py')
monitor = load('fresh_monitor_base', ROOT / 'experiments/l5-steering-hysteresis-v1/monitor.py')
auditor = load('fresh_teacher_audit', ROOT / 'experiments/heading-teacher-audit/audit.py')
metrics = load('fresh_long_loop_metrics', ROOT / 'datasets/visual-control/chase-v1/levels/heading-selection-metrics.py')
auditor.BASE = SEED
auditor.selection.BASE = SEED


def design():
    tasks = []
    for level in range(1, 6):
        rows = []
        for index in range(GAMES):
            layout = 13 + 2 * (index % 3) if level >= 4 else 12 + index % 6
            rows.append({'index': index, 'seed': SEED + index, 'layout': layout,
                         'variant': index % 16, 'scene': str(SCENES / str(layout) / str(index % 16))})
        tasks.append({'name': f'L{level}', 'level': level, 'rows': rows})
    return {'schema': 'puppybot.fresh-policy-selection-design.v1', 'tasks': tasks,
            'arms': ['control', 'treatment', 'teacher'], 'gamesPerArmPerLevel': GAMES,
            'horizon': 300, 'actionSeconds': 0.2, 'cameraPitch': 82,
            'models': {name: str(path) for name, path in MODELS.items()},
            'scope': 'training-family selection only; no held-out or physical claim; no promotion rule'}


def environment(level):
    return {'PATH': '/usr/bin:/bin', 'HOME': str(Path.home()), 'PUPPYBOT_PROJECT': str(ROOT),
            'SDL_VIDEODRIVER': 'offscreen', 'LD_LIBRARY_PATH': str(ROOT / 'build/flex/rocm-runtime'),
            'PUPPYBOT_EVAL_SELECTION': '1', 'PUPPYBOT_EVAL_SELECTION_SEED': str(SEED),
            'PUPPYBOT_EVAL_TWO_ROOM': '1' if level >= 4 else '0',
            'PUPPYBOT_CHASE_PARTS': '4', 'PUPPYBOT_CHASE_HORIZON': '300', 'PUPPYBOT_CHASE_FULL': '0'}


def command(task, arm):
    if task not in design()['tasks'] or arm not in design()['arms']: raise ValueError('unknown task or arm')
    model = 'teacher' if arm == 'teacher' else str(MODELS[arm])
    result = ['/usr/bin/bash', str(EVALUATE), str(OUTPUT / task['name']), arm, model,
              '--fetch', '--level', str(task['level']), '--camera-pitch', '82']
    if arm == 'teacher': result.append('--explore-teacher')
    return result


def scene_links(row, scenes=SCENES):
    """Validate every scene path before reading any scene file content.

    The generated training catalog shares environment and layout files only
    within the same layout. Do not follow a changed or reserved-target link.
    """
    scenes = Path(scenes).absolute()
    if scenes.is_symlink() or scenes.resolve() != scenes:
        raise ValueError('training scene root is symlinked')
    layout = scenes / str(row['layout']); scene = layout / str(row['variant'])
    if (layout.is_symlink() or scene.is_symlink() or not layout.is_dir() or
            not scene.is_dir() or str(scene) != row['scene']):
        raise ValueError('invalid training scene path')
    result = {}
    case = scene / 'case.json'
    if case.is_symlink() or not case.is_file(): raise ValueError('invalid training case path')
    result[str(case)] = 'regular-file'
    for name in ('environment.bin', 'layout.json'):
        link = scene / name; expected = layout / name
        if not link.is_symlink() or expected.is_symlink() or not expected.is_file():
            raise ValueError('invalid training scene link')
        target = os.readlink(link)
        if link.resolve(strict=True) != expected:
            raise ValueError('training scene link escaped its layout')
        result[str(link)] = target
    return result


def source_paths():
    levels = ROOT / 'datasets/visual-control/chase-v1/levels'
    paths = [Path(__file__), EVALUATE, ROOT / 'build/flex/control/control',
             ROOT / 'build/flex/control/simulator', ROOT / 'build/flex/sim/puppybot.bin',
             ROOT / 'puppybot.json', ROOT / 'experiments/heading-teacher-audit/audit.py',
             ROOT / 'experiments/l5-steering-kick-v1/register.py',
             ROOT / 'experiments/l5-steering-kick-v1/prepare.py',
             ROOT / 'experiments/l5-steering-kick-v1/plan.py',
             ROOT / 'experiments/l5-steering-kick-v1/transform.py',
             ROOT / 'experiments/l5-steering-hysteresis-v1/monitor.py',
             ROOT / 'experiments/sim-stop-supervisor/supervisor.py',
             ROOT / 'experiments/sim-stop-supervisor/proxy.py',
             ROOT / 'flex/tests/monitored-visual-v4-smoke.py',
             ROOT / 'flex/tests/run-physical-hidden-trial.py',
             ROOT / 'flex/tests/run-physical-rescan-trial.py',
             ROOT / 'flex/tests/run-physical-hybrid-trial.py', Path(sys.executable).resolve()]
    paths += [levels / name for name in ('audit-selection.py', 'qualify-selection.py', 'audit-heldout.py',
              'heading-selection-metrics.py', 'search-loops-odometry.py', 'run-route-factorial.py',
              'prepare-route-factorial.py', 'route-coverage.py', 'package-matched-epoch8.py',
              'audit-matched-training.py', 'prepare-heldout.py', 'heldout-protocol.md')]
    paths += [Path('/usr/bin') / name for name in ('bash', 'jq', 'find', 'sort', 'env', 'nice', 'ln', 'mkdir')]
    for model in MODELS.values():
        auditor.qualification.model_files(model)
        paths += [model / name for name in ('receipt.json', 'weights.bin', 'policy')]
        paths += sorted((model / 'kernels').iterdir())
    for task in design()['tasks']:
        for row in task['rows']:
            scene_links(row)
            scene = Path(row['scene']); info = json.loads((scene / 'layout.json').read_text())
            if (info.get('layoutId') != row['layout'] or info.get('fit') is not True or
                    info.get('reservedHeldOut') is True or 226 <= row['layout'] <= 289):
                raise ValueError('unauthorized training scene')
            paths += [scene / name for name in ('layout.json', 'case.json', 'environment.bin')]
    return sorted(set(paths))


def current(include_history=True):
    heldout = load('fresh_reservation_spec', ROOT / 'datasets/visual-control/chase-v1/levels/prepare-heldout.py')
    reserved = {heldout.BASE_SEED + level * 100 + i for level in range(1, 6) for i in range(32)}
    candidates = set(range(SEED, SEED + GAMES))
    if candidates & reserved or candidates & set(range(990000, 990032)):
        raise ValueError('selection overlaps reserved seed')
    old.plan.design = lambda: {'conditions': [{'seed': seed} for seed in sorted(candidates)]}
    extra = ('l5-steering-kick-diagnostic-v1', 'l5-steering-hysteresis-diagnostic-v1',
             'l5-steering-hysteresis-debug-v1')
    history = old.historical_inventory(roots=old.HISTORY + tuple(P / name for name in extra),
                                       excluded=(OUTPUT, MONITOR), require_known=True) if include_history else None
    links = {}
    for task in design()['tasks']:
        for row in task['rows']:
            links.update(scene_links(row))
    return {'schema': 'puppybot.fresh-policy-selection-plan.v1', 'status': 'frozen_before_play',
            'design': design(), 'files': {str(p): base.sha(p) for p in source_paths()},
            'sceneLinks': links, 'runtime': old.runtime_chain(), 'history': history,
            'scope': 'named history only; no proof of unrecorded ancestry, execution, held-out or physical outcomes'}


def verify():
    frozen = json.loads(MANIFEST.read_text())
    if current() != frozen: raise ValueError('registered selection inputs changed')
    return frozen


def write_new(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False); stream.write('\n')


def freeze():
    guard.require_dedicated_process()
    with base.acquire_lock(P / '.l4-matched.lock'):
        for path in (MANIFEST, OUTPUT, MONITOR): base.require_new_output(path)
        base.require_capacity(P, 38 * 1024**3)
        value = current()
        if current() != value: raise ValueError('inputs changed during registration')
        write_new(MANIFEST, value)
        return value


def reaudit(frozen):
    if json.loads((OUTPUT / 'inputs.json').read_text()) != frozen: raise ValueError('input manifest differs')
    results = {}
    for task in design()['tasks']:
        root = OUTPUT / task['name']; level = task['level']
        for arm in design()['arms']:
            receipt = OUTPUT / 'supervisors' / task['name'] / arm
            expected = {'argv': command(task, arm), 'environment': environment(level), 'wallSeconds': 3600}
            if json.loads((receipt / 'invocation.json').read_text()) != expected or not monitor.clean(json.loads((receipt / 'supervisor-result.json').read_text())):
                raise ValueError('arm invocation or supervisor differs')
        result = auditor.audit_task(task['name'], root, root, MODELS)
        if result.get('status') != 'complete_diagnostic': raise ValueError('saved task audit censored: ' + str(result))
        for arm in MODELS:
            games = auditor.qualification.strict_games(root / arm, MODELS[arm], level, auditor.selection, auditor.heldout)
            result['results'][arm]['longerSearchLoops'] = metrics.summarize(root / arm, games, level)
        results[task['name']] = result
    return {'schema': 'puppybot.fresh-policy-selection-result.v1', 'status': 'diagnostic_only',
            'tasks': results, 'pool': auditor.audit_pool(results),
            'scope': 'matched training-family simulations; no held-out, physical or execution attestation'}


def run():
    guard.require_dedicated_process()
    with base.acquire_lock(P / '.l4-matched.lock'):
        base.require_new_output(OUTPUT); base.require_capacity(P, 38 * 1024**3)
        frozen = verify(); OUTPUT.mkdir(); write_new(OUTPUT / 'inputs.json', frozen)
        (OUTPUT / 'supervisors').mkdir(); completed = []
        try:
            for task in design()['tasks']:
                (OUTPUT / task['name']).mkdir(); (OUTPUT / 'supervisors' / task['name']).mkdir()
                for arm in design()['arms']:
                    base.require_capacity(P, 34 * 1024**3)
                    if verify() != frozen: raise ValueError('selection inputs changed')
                    receipt = OUTPUT / 'supervisors' / task['name'] / arm; receipt.mkdir()
                    argv = command(task, arm); env = environment(task['level'])
                    write_new(receipt / 'invocation.json', {'argv': argv, 'environment': env, 'wallSeconds': 3600})
                    status = base.hidden.supervise(argv, receipt, env, 3600)
                    if not monitor.clean(status) or json.loads((receipt / 'supervisor-result.json').read_text()) != status:
                        raise ValueError('arm supervisor failed')
                    completed.append([task['name'], arm])
            report = reaudit(frozen)
            if verify() != frozen: raise ValueError('selection inputs changed after audit')
            base.require_capacity(P, 32 * 1024**3); write_new(OUTPUT / 'report.json', report)
        except BaseException as error:
            if not (OUTPUT / 'report.json').exists(): write_new(OUTPUT / 'partial.json', {'status': 'censored', 'completed': completed, 'reason': str(error)})
            raise


def verify_saved(frozen):
    report = json.loads((OUTPUT / 'report.json').read_text())
    if reaudit(frozen) != report: raise ValueError('saved re-audit differs')
    return report


def python_call(function, *args):
    code = ('import importlib.util,sys;'
            's=importlib.util.spec_from_file_location("fresh_selection",sys.argv[1]);'
            'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);'
            'getattr(m,sys.argv[2])(*sys.argv[3:])')
    return [sys.executable, '-I', '-c', code, str(Path(__file__).resolve()), function, *map(str, args)]


def configure_monitor():
    monitor.OUTPUT = OUTPUT; monitor.MONITOR = MONITOR; monitor.MANIFEST = MANIFEST
    monitor.REGISTER = Path(__file__).resolve(); monitor.verify_saved = verify_saved
    monitor.worker_command = lambda: python_call('run')


def describe_configuration():
    configure_monitor()
    print(json.dumps({'output': str(monitor.OUTPUT), 'registration': str(monitor.REGISTER),
                      'worker': monitor.worker_command()}, sort_keys=True))


def monitor_worker(path):
    configure_monitor(); monitor.monitor_worker(path)


def final_check(path, evidence_sha):
    configure_monitor(); print(json.dumps(monitor.final_check(path, evidence_sha), sort_keys=True))


def launch():
    guard.require_dedicated_process(); configure_monitor(); monitor.require_disk(38)
    frozen = verify()
    for path in (MONITOR, OUTPUT): base.require_new_output(path)
    env = monitor.environment(); command_line = python_call('monitor_worker', MONITOR)
    MONITOR.mkdir(); outer = MONITOR / 'outer-monitor'; outer.mkdir()
    write_new(MONITOR / 'launch.json', {'command': command_line, 'environment': env,
              'wallSeconds': monitor.OUTER_SECONDS, 'workerCommand': monitor.worker_command(), 'sourcePins': frozen['files']})
    status = base.hidden.supervise(command_line, outer, env, monitor.OUTER_SECONDS)
    if not monitor.clean(status) or json.loads((outer / 'supervisor-result.json').read_text()) != status:
        raise RuntimeError('resource monitor failed; retained outputs censored')
    if (verify() != frozen or json.loads((MONITOR / 'frozen-manifest.json').read_text()) != frozen or
            json.loads((MONITOR / 'monitor-result.json').read_text()).get('status') != 'passed'):
        raise ValueError('registered inputs or monitor differ')
    evidence_path = MONITOR / 'evidence.json'; evidence_sha = base.sha(evidence_path)
    evidence = json.loads(evidence_path.read_text())
    if evidence.get('status') != 'diagnostic_only' or evidence.get('report') != verify_saved(frozen):
        raise ValueError('selection evidence differs')
    monitor.verify_logs(MONITOR); monitor.require_disk(34)
    retained = {'launchSHA256': MONITOR / 'launch.json',
                'telemetrySHA256': MONITOR / 'telemetry.jsonl',
                'diskSHA256': MONITOR / 'disk.jsonl',
                'monitorResultSHA256': MONITOR / 'monitor-result.json',
                'outerSupervisorStatusSHA256': outer / 'supervisor-result.json',
                'frozenManifestSHA256': MONITOR / 'frozen-manifest.json'}
    hashes = {name: base.sha(path) for name, path in retained.items()}
    final_dir = MONITOR / 'final-inventory-monitor'; final_dir.mkdir()
    argv = python_call('final_check', MONITOR, evidence_sha)
    write_new(final_dir / 'invocation.json', {'argv': argv, 'environment': env, 'wallSeconds': monitor.FINAL_CHECK_SECONDS})
    invocation_sha = base.sha(final_dir / 'invocation.json')
    final = base.hidden.supervise(argv, final_dir, env, monitor.FINAL_CHECK_SECONDS)
    if (not monitor.clean(final) or json.loads((final_dir / 'supervisor-result.json').read_text()) != final or
            json.loads((final_dir / 'client.log').read_text()) != {'status': 'final_inventory_verified'}):
        raise RuntimeError('final inventory failed; retained outputs censored')
    if (verify() != frozen or base.sha(evidence_path) != evidence_sha or
            any(base.sha(path) != hashes[name] for name, path in retained.items()) or
            base.sha(final_dir / 'invocation.json') != invocation_sha):
        raise ValueError('inputs or evidence changed during final audit')
    monitor.require_disk(32)
    write_new(MONITOR / 'completion.json', {'status': 'diagnostic_only', 'evidenceSHA256': evidence_sha,
              **hashes, 'finalInventoryInvocationSHA256': invocation_sha,
              'finalInventoryStatusSHA256': base.sha(final_dir / 'supervisor-result.json'),
              'finalInventoryResultSHA256': base.sha(final_dir / 'client.log'),
              'scope': 'training-family selection only, no promotion, held-out, physical or actor attestation'})
    return evidence['report']


if __name__ == '__main__':
    raise SystemExit('Disabled pending independent review and supervised scheduling.')
