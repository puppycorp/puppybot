#!/usr/bin/env python3
"""Disabled, serial, monitored recapture of two training-family L5 scenes.

The outer subreaper supervises the monitor and cleans orphaned descendants.
Import and launch only in a dedicated process after independent review.
"""
import importlib.util
import ctypes
import fcntl
import json
import os
import shutil
import signal
import struct
import subprocess
import sys
import time
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUTPUT = ROOT / 'build/flex/sim/levels-v2/pitch82/l5-actor-frame-capture-v1'
GIB = 1024 ** 3
START_GIB = 38
STOP_GIB = 34
BASELINE_SECONDS = 30
GAME_SECONDS = 600
OUTER_SECONDS = 2700
LOCK = ROOT / 'build/flex/sim/levels-v2/pitch82/.l4-matched.lock'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


diagnostic = load('l5_frame_diagnostic', HERE / 'diagnose.py')
guard = load('l5_frame_supervisor', ROOT / 'experiments/sim-stop-supervisor/supervisor.py')
telemetry = load('l5_frame_gpu_telemetry', ROOT / 'flex/tests/monitored-visual-v4-smoke.py')


def write_new(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')


def acquire_lock(path):
    stream = Path(path).open('a')
    try:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BaseException:
        stream.close()
        raise
    return stream


def clean(status):
    return (isinstance(status, dict) and status.get('clientExit') == 0 and
            status.get('timedOut') is False and status.get('signal') is None and
            status.get('reason') is None and
            status.get('remainingWorkersTerminated') is False and
            type(status.get('processGroup')) is int and status['processGroup'] > 0)


def selection_completion():
    root = diagnostic.BASE / 'fresh-policy-selection-monitored-v3'
    completion = diagnostic.read_json(root / 'completion.json')
    paths = {'monitorResultSHA256': 'monitor-result.json', 'evidenceSHA256': 'evidence.json',
             'frozenManifestSHA256': 'frozen-manifest.json', 'launchSHA256': 'launch.json',
             'diskSHA256': 'disk.jsonl', 'telemetrySHA256': 'telemetry.jsonl',
             'outerSupervisorStatusSHA256': 'outer-monitor/supervisor-result.json',
             'finalInventoryInvocationSHA256': 'final-inventory-monitor/invocation.json',
             'finalInventoryStatusSHA256': 'final-inventory-monitor/supervisor-result.json',
             'finalInventoryResultSHA256': 'final-inventory-monitor/client.log'}
    if completion.get('status') != 'diagnostic_only':
        raise ValueError('selection completion is not diagnostic-only')
    for key, relative in paths.items():
        if diagnostic.digest(root / relative) != completion.get(key):
            raise ValueError(f'selection completion evidence differs: {key}')
    if diagnostic.digest(diagnostic.SELECTION / 'inputs.json') != completion['frozenManifestSHA256']:
        raise ValueError('selection completion refers to a different frozen manifest')
    if (diagnostic.read_json(root / 'monitor-result.json') != {'status': 'passed'} or
            not clean(diagnostic.read_json(root / 'outer-monitor/supervisor-result.json')) or
            not clean(diagnostic.read_json(root / 'final-inventory-monitor/supervisor-result.json'))):
        raise ValueError('selection monitor or supervisor did not pass cleanly')
    if json.loads((root / 'final-inventory-monitor/client.log').read_text()) != {'status': 'final_inventory_verified'}:
        raise ValueError('selection final inventory did not pass')
    return {'path': str(root / 'completion.json'), 'sha256': diagnostic.digest(root / 'completion.json')}


def source_pins():
    paths = (Path(__file__).resolve(), HERE / 'diagnose.py',
             ROOT / 'experiments/sim-stop-supervisor/supervisor.py',
             ROOT / 'experiments/sim-stop-supervisor/proxy.py',
             ROOT / 'flex/tests/run-physical-hidden-trial.py',
             ROOT / 'flex/tests/run-physical-rescan-trial.py',
             ROOT / 'flex/tests/run-physical-hybrid-trial.py',
             ROOT / 'flex/tests/monitored-visual-v4-smoke.py', Path(sys.executable).resolve())
    return {str(path): diagnostic.digest(path) for path in paths}


def environment():
    return {'PATH': '/usr/bin:/bin', 'HOME': str(Path.home()), 'SDL_VIDEODRIVER': 'offscreen',
            'PUPPYBOT_PROJECT': str(ROOT), 'LD_LIBRARY_PATH': str(ROOT / 'build/flex/rocm-runtime')}


def command(seed, arm, model):
    catalog = OUTPUT / 'catalogs' / str(seed)
    out = OUTPUT / 'runs' / str(seed) / arm
    return [str(ROOT / 'build/flex/control/control'), 'run', '--chase', '--policy', model,
            '--scene-catalog', str(catalog), '--output', str(out), '--episodes', '1',
            '--horizon', '300', '--seed', str(seed), '--wheel-odometry', '--fetch',
            '--level', '5', '--camera-pitch', '82']


def verify_catalog(game):
    scene = Path(game['scene']['scene'])
    catalog = OUTPUT / 'catalogs' / str(game['seed'])
    link = catalog / '0'
    if (catalog.is_symlink() or not catalog.is_dir() or {p.name for p in catalog.iterdir()} != {'0'} or
            not link.is_symlink() or os.readlink(link) != str(scene) or link.resolve(strict=True) != scene):
        raise ValueError(f'capture catalog differs: {catalog}')
    frozen = diagnostic.read_json(diagnostic.SELECTION / 'inputs.json')['files']
    for name in ('case.json', 'environment.bin', 'layout.json'):
        diagnostic.check_file(scene / name, frozen)


def verify_runtime(plan):
    current = diagnostic.runtime_chain(ROOT / 'build/flex/rocm-runtime/libamdhip64.so')
    if current != plan['diagnostic']['runtime']:
        raise ValueError('capture runtime chain differs from frozen selection')


def sample(stream, phase, floor, gpu_floor, read_gpu=telemetry.telemetry):
    volumes = {name: shutil.disk_usage(path).free for name, path in
               (('workspace', ROOT), ('output', OUTPUT), ('home', Path.home()))}
    gpu = read_gpu(telemetry.DEVICE)
    row = {'phase': phase, 'monotonicSeconds': time.monotonic(), 'volumes': volumes, 'gpu': gpu}
    stream.write(json.dumps(row, sort_keys=True) + '\n')
    stream.flush()
    if min(volumes.values()) < floor * GIB:
        raise RuntimeError(f'disk below {floor} GiB')
    if gpu['freeBytes'] < gpu_floor * GIB:
        raise RuntimeError(f'GPU free memory below {gpu_floor} GiB')
    return row


def baseline(stream):
    start = time.monotonic()
    busy = 0
    while True:
        row = sample(stream, 'baseline', START_GIB, 6)
        busy = busy + 1 if row['gpu']['busyPercent'] > 10 else 0
        if busy >= 5:
            raise RuntimeError('GPU busy above 10% for five consecutive baseline samples')
        remaining = BASELINE_SECONDS - (time.monotonic() - start)
        if remaining <= 0:
            return
        time.sleep(min(1, remaining))


def run_game(seed, arm, model):
    argv = command(seed, arm, model)
    supervisor = OUTPUT / 'game-supervisors' / f'{seed}-{arm}'
    supervisor.mkdir()
    status = guard.hidden.supervise(argv, supervisor, environment(), GAME_SECONDS)
    if not clean(status) or diagnostic.read_json(supervisor / 'supervisor-result.json') != status:
        raise RuntimeError(f'game failed or left descendants: {seed} {arm}')


def audit_game(seed, arm, original):
    run = OUTPUT / 'runs' / str(seed) / arm / str(seed)
    if diagnostic.read_json(run / 'initial.json') != diagnostic.read_json(Path(original['run']) / 'initial.json'):
        raise ValueError(f'captured initial state differs: {seed} {arm}')
    result = diagnostic.read_json(run / 'result.json')
    if result != diagnostic.read_json(Path(original['run']) / 'result.json'):
        raise ValueError(f'captured result differs from lean game: {seed} {arm}')
    current = diagnostic.read_rows(run / 'decisions.jsonl')
    old = diagnostic.read_rows(Path(original['run']) / 'decisions.jsonl')
    if len(current) != 300 or len(old) != len(current):
        raise ValueError('incomplete captured actions')
    if diagnostic.read_rows(run / 'chase.jsonl') != diagnostic.read_rows(Path(original['run']) / 'chase.jsonl'):
        raise ValueError(f'captured task events differ: {seed} {arm}')
    for before, after in zip(old, current):
        for key in ('step', 'sequence', 'action', 'proprio', 'state'):
            if before[key] != after[key]:
                raise ValueError(f'captured {key} differs: {seed} {arm}')
        frame = after['state']['totalSteps']
        image, feedback = run / f'actor-{frame}.rgb', run / f'actor-{frame}.feedback'
        if (image.stat().st_size != 21168 or feedback.stat().st_size != 28 or
                diagnostic.digest(image) != after['actorSHA256'] or
                feedback.read_bytes() != struct.pack('<7f', *after['proprio'])):
            raise ValueError(f'captured actor frame missing or hash differs: {seed} {arm}')
    initial = diagnostic.read_json(run / 'initial.json')['totalSteps']
    image, feedback = run / f'actor-{initial}.rgb', run / f'actor-{initial}.feedback'
    if image.stat().st_size != 21168 or feedback.stat().st_size != 28:
        raise ValueError('initial actor observation missing')
    frames = [initial] + [row['state']['totalSteps'] for row in current]
    expected = {f'actor-{frame}.{suffix}' for frame in frames for suffix in ('rgb', 'feedback')}
    present = {path.name for path in run.glob('actor-*')}
    if len(set(frames)) != 301 or expected != present:
        raise ValueError('missing, duplicate or unexpected actor observation')
    return {'seed': seed, 'arm': arm, 'run': str(run), 'actions': len(current),
            'resultSHA256': diagnostic.digest(run / 'result.json'),
            'decisionsSHA256': diagnostic.digest(run / 'decisions.jsonl'),
            'eventsSHA256': diagnostic.digest(run / 'chase.jsonl'),
            'initialActorSHA256': diagnostic.digest(image),
            'initialFeedbackSHA256': diagnostic.digest(feedback),
            'scope': 'saved action/feedback/event parity and post-action actor-file hashes; not raw-camera attestation'}


def inventory():
    files, links, directories = {}, {}, []
    def walk_error(error):
        raise error
    for directory, children, names in os.walk(OUTPUT, topdown=True, followlinks=False, onerror=walk_error):
        parent = Path(directory)
        for name in sorted(children):
            path = parent / name
            relative = str(path.relative_to(OUTPUT))
            if path.is_symlink():
                links[relative] = os.readlink(path)
            elif path.is_dir():
                directories.append(relative)
            else:
                raise ValueError(f'unsafe inventory directory: {path}')
        for name in sorted(names):
            path = parent / name
            relative = str(path.relative_to(OUTPUT))
            if relative in ('inventory.json', 'completion.json', 'telemetry.jsonl',
                            'outer-monitor/client.log', 'outer-monitor/supervisor-result.json',
                            'outer-monitor/final-client.log', 'outer-monitor/final-supervisor-result.json'):
                continue
            if path.is_symlink() or not path.is_file():
                raise ValueError(f'unsafe inventory file: {path}')
            files[relative] = diagnostic.digest(path)
    return {'directories': sorted(directories), 'links': links, 'files': files}


def worker():
    plan = diagnostic.read_json(OUTPUT / 'plan.json')
    if (diagnostic.diagnose() != plan['diagnostic'] or source_pins() != plan['sourcePins'] or
            selection_completion() != plan['selectionCompletion']):
        raise ValueError('capture inputs differ from plan')
    captures = []
    for game in plan['diagnostic']['games']:
        seed = game['seed']
        for arm in diagnostic.ARMS:
            original = game['arms'][arm]
            verify_catalog(game)
            verify_runtime(plan)
            run_game(seed, arm, original['model'])
            verify_catalog(game)
            verify_runtime(plan)
            captures.append(audit_game(seed, arm, original))
    if (diagnostic.diagnose() != plan['diagnostic'] or source_pins() != plan['sourcePins'] or
            selection_completion() != plan['selectionCompletion']):
        raise ValueError('capture inputs changed during run')
    write_new(OUTPUT / 'worker-result.json', {'status': 'captured_diagnostic_only', 'captures': captures,
        'scope': 'reused training-family scenes; no held-out, physical, raw-camera or actor attestation'})
    for game in plan['diagnostic']['games']:
        verify_catalog(game)
    observed = inventory()
    expected_links = {f"catalogs/{game['seed']}/0": game['scene']['scene'] for game in plan['diagnostic']['games']}
    if observed['links'] != expected_links:
        raise ValueError('unexpected capture symlink')
    if inventory() != observed:
        raise ValueError('capture output changed during final inventory')
    write_new(OUTPUT / 'inventory.json', observed)
    if diagnostic.read_json(OUTPUT / 'inventory.json') != observed or inventory() != observed:
        raise ValueError('capture output inventory readback differs')
    if (diagnostic.diagnose() != plan['diagnostic'] or source_pins() != plan['sourcePins'] or
            selection_completion() != plan['selectionCompletion']):
        raise ValueError('capture inputs changed during final inventory')


def supervise_monitored(argv, phase='worker'):
    """Watch a dedicated worker, including audits, and reap all descendants."""
    libc = ctypes.CDLL(None, use_errno=True)
    old = ctypes.c_int()
    if libc.prctl(37, ctypes.byref(old), 0, 0, 0) or libc.prctl(36, 1, 0, 0, 0):
        raise OSError(ctypes.get_errno(), 'cannot configure subreaper')
    signals = []
    handlers = {sig: signal.signal(sig, lambda number, _frame: signals.append(number))
                for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
    status = {'clientExit': None, 'timedOut': False, 'remainingWorkersTerminated': False,
              'signal': None, 'reason': None}
    process = None
    start = time.monotonic()
    try:
        log_name = 'client.log' if phase == 'worker' else 'final-client.log'
        result_name = 'supervisor-result.json' if phase == 'worker' else 'final-supervisor-result.json'
        with (OUTPUT / 'telemetry.jsonl').open('x' if phase == 'worker' else 'a') as stream, (OUTPUT / 'outer-monitor' / log_name).open('x') as log:
            try:
                if phase == 'worker':
                    baseline(stream)
                else:
                    sample(stream, phase, STOP_GIB, 2)
                if signals:
                    raise RuntimeError('interrupted during baseline')
                process = subprocess.Popen(argv, cwd=ROOT, env=environment(), stdout=log,
                                           stderr=subprocess.STDOUT, start_new_session=True)
                status['processGroup'] = process.pid
                while True:
                    sample(stream, phase, STOP_GIB, 2)
                    if signals:
                        raise RuntimeError('interrupted during capture')
                    if time.monotonic() - start >= OUTER_SECONDS:
                        status['timedOut'] = True
                        raise TimeoutError('capture deadline exceeded')
                    if process.poll() is not None:
                        break
                    time.sleep(1)
            except BaseException as error:
                status['reason'] = f'{type(error).__name__}: {error}'
            finally:
                if process is not None and process.poll() is None:
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    deadline = time.monotonic() + 2
                    while process.poll() is None and time.monotonic() < deadline:
                        try:
                            if min(shutil.disk_usage(path).free for path in (ROOT, OUTPUT, Path.home())) < 32 * GIB:
                                break
                        except OSError:
                            break
                        time.sleep(0.1)
                    if process.poll() is None:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    process.wait()
                if process is not None:
                    status['clientExit'] = process.returncode
                status['remainingWorkersTerminated'] = guard.hidden.supervisor.cleanup_descendants()
                status['signal'] = signals[0] if signals else None
                status['wallSeconds'] = round(time.monotonic() - start, 3)
    finally:
        if libc.prctl(36, old.value, 0, 0, 0):
            raise OSError(ctypes.get_errno(), 'cannot restore subreaper')
        for sig, handler in handlers.items():
            signal.signal(sig, handler)
    write_new(OUTPUT / 'outer-monitor' / result_name, status)
    return status


def final_check():
    plan_path, inventory_path = OUTPUT / 'plan.json', OUTPUT / 'inventory.json'
    plan_sha, inventory_sha = diagnostic.digest(plan_path), diagnostic.digest(inventory_path)
    plan = diagnostic.read_json(plan_path)
    if (diagnostic.diagnose() != plan['diagnostic'] or source_pins() != plan['sourcePins'] or
            selection_completion() != plan['selectionCompletion']):
        raise ValueError('final capture inputs differ')
    for game in plan['diagnostic']['games']:
        verify_catalog(game)
    verify_runtime(plan)
    if diagnostic.read_json(inventory_path) != inventory():
        raise ValueError('final capture output inventory differs')
    if diagnostic.digest(plan_path) != plan_sha or diagnostic.digest(inventory_path) != inventory_sha:
        raise ValueError('capture plan or inventory changed during final scan')
    if (diagnostic.diagnose() != plan['diagnostic'] or source_pins() != plan['sourcePins'] or
            selection_completion() != plan['selectionCompletion']):
        raise ValueError('capture inputs changed during final scan')
    for game in plan['diagnostic']['games']:
        verify_catalog(game)
    verify_runtime(plan)
    if diagnostic.digest(plan_path) != plan_sha or diagnostic.digest(inventory_path) != inventory_sha:
        raise ValueError('capture plan or inventory changed during final verification')
    print(json.dumps({'status': 'final_inventory_verified', 'planSHA256': plan_sha,
                      'inventorySHA256': inventory_sha}, sort_keys=True))


def launch_locked():
    if OUTPUT.exists() or OUTPUT.is_symlink():
        raise FileExistsError('capture output exists; retain it')
    if min(shutil.disk_usage(path).free for path in (ROOT, diagnostic.BASE, Path.home())) < START_GIB * GIB:
        raise RuntimeError('disk below startup floor')
    saved = diagnostic.diagnose()
    completion = selection_completion()
    pins = source_pins()
    OUTPUT.mkdir()
    write_new(OUTPUT / 'owner.json', {'process': os.getpid()})
    for name in ('catalogs', 'runs', 'game-supervisors', 'outer-monitor'):
        (OUTPUT / name).mkdir()
    for game in saved['games']:
        catalog = OUTPUT / 'catalogs' / str(game['seed'])
        catalog.mkdir()
        (catalog / '0').symlink_to(game['scene']['scene'], target_is_directory=True)
        (OUTPUT / 'runs' / str(game['seed'])).mkdir()
    commands = [command(game['seed'], arm, game['arms'][arm]['model'])
                for game in saved['games'] for arm in diagnostic.ARMS]
    plan = {'diagnostic': saved, 'selectionCompletion': completion, 'sourcePins': pins,
            'commands': commands, 'environment': environment(),
            'thresholds': {'startupGiB': START_GIB, 'runningGiB': STOP_GIB,
                           'baselineFreeVramGiB': 6, 'runningFreeVramGiB': 2,
                           'baselineSeconds': BASELINE_SECONDS, 'gameSeconds': GAME_SECONDS,
                           'outerSeconds': OUTER_SECONDS},
            'scope': 'four non-lean training-family recaptures; no held-out or physical claim'}
    write_new(OUTPUT / 'plan.json', plan)
    code = ('import importlib.util,sys;'
            's=importlib.util.spec_from_file_location("capture",sys.argv[1]);'
            'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.worker()')
    argv = [sys.executable, '-I', '-c', code, str(Path(__file__).resolve())]
    status = supervise_monitored(argv)
    if not clean(status) or diagnostic.read_json(OUTPUT / 'outer-monitor/supervisor-result.json') != status:
        raise RuntimeError('capture worker failed or required descendant cleanup; retain outputs')
    report = diagnostic.read_json(OUTPUT / 'worker-result.json')
    if report.get('status') != 'captured_diagnostic_only' or len(report.get('captures', [])) != 4:
        raise ValueError('capture report incomplete')
    if not (OUTPUT / 'inventory.json').is_file():
        raise ValueError('capture output inventory missing')
    final_code = ('import importlib.util,sys;'
                  's=importlib.util.spec_from_file_location("capture",sys.argv[1]);'
                  'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.final_check()')
    final_status = supervise_monitored([sys.executable, '-I', '-c', final_code, str(Path(__file__).resolve())], 'final-check')
    final_result = json.loads((OUTPUT / 'outer-monitor/final-client.log').read_text())
    if (not clean(final_status) or
            diagnostic.read_json(OUTPUT / 'outer-monitor/final-supervisor-result.json') != final_status or
            final_result.get('status') != 'final_inventory_verified'):
        raise RuntimeError('final capture inventory did not complete cleanly')
    if (diagnostic.digest(OUTPUT / 'plan.json') != final_result['planSHA256'] or
            diagnostic.digest(OUTPUT / 'inventory.json') != final_result['inventorySHA256'] or
            diagnostic.diagnose() != saved or source_pins() != pins or
            selection_completion() != completion or
            min(shutil.disk_usage(path).free for path in (ROOT, OUTPUT, Path.home())) < STOP_GIB * GIB):
        raise ValueError('capture inputs changed after final inventory')
    for game in saved['games']:
        verify_catalog(game)
    verify_runtime(plan)
    if (diagnostic.digest(OUTPUT / 'plan.json') != final_result['planSHA256'] or
            diagnostic.digest(OUTPUT / 'inventory.json') != final_result['inventorySHA256']):
        raise ValueError('capture plan or inventory changed before completion')
    write_new(OUTPUT / 'completion.json', {'status': 'captured_diagnostic_only',
        'planSHA256': diagnostic.digest(OUTPUT / 'plan.json'),
        'workerResultSHA256': diagnostic.digest(OUTPUT / 'worker-result.json'),
        'telemetrySHA256': diagnostic.digest(OUTPUT / 'telemetry.jsonl'),
        'supervisorSHA256': diagnostic.digest(OUTPUT / 'outer-monitor/supervisor-result.json'),
        'outerClientLogSHA256': diagnostic.digest(OUTPUT / 'outer-monitor/client.log'),
        'finalSupervisorSHA256': diagnostic.digest(OUTPUT / 'outer-monitor/final-supervisor-result.json'),
        'finalClientLogSHA256': diagnostic.digest(OUTPUT / 'outer-monitor/final-client.log'),
        'inventorySHA256': diagnostic.digest(OUTPUT / 'inventory.json')})
    return report


def launch():
    guard.require_dedicated_process()
    with acquire_lock(LOCK):
        preexisting = OUTPUT.exists() or OUTPUT.is_symlink()
        try:
            return launch_locked()
        except BaseException as error:
            try:
                if (not preexisting and OUTPUT.is_dir() and not OUTPUT.is_symlink() and
                        diagnostic.read_json(OUTPUT / 'owner.json') == {'process': os.getpid()} and
                        not (OUTPUT / 'failure.json').exists()):
                    write_new(OUTPUT / 'failure.json', {'status': 'failed',
                              'reason': f'{type(error).__name__}: {error}',
                              'scope': 'capture stopped or did not complete; prior and partial artifacts retained'})
            except (OSError, ValueError, KeyError):
                pass
            raise


if __name__ == '__main__':
    raise SystemExit('Disabled pending independent review and supervised scheduling.')
