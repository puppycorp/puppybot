#!/usr/bin/env python3
"""Disabled GPU/disk monitor for the paired L5 steering diagnostic."""
import importlib.util
import json
import math
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
OUTER_SECONDS = 19800
WORKER_SECONDS = 18000
FINAL_CHECK_SECONDS = 900


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


base = load('steering_monitor_base', ROOT / 'datasets/visual-control/chase-v1/levels/run-route-factorial.py')
guard = load('steering_monitor_guard', ROOT / 'experiments/sim-stop-supervisor/supervisor.py')
P = ROOT / 'build/flex/sim/levels-v2/pitch82'
OUTPUT = P / 'l5-steering-kick-diagnostic-v1'
MONITOR = P / 'l5-steering-kick-monitored-v1'
MANIFEST = P / 'l5-steering-kick-plan-v1.json'
RUNNER = HERE / 'runner.py'
REGISTER = HERE / 'register.py'
telemetry = load('hybrid_gpu_telemetry', ROOT / 'flex/tests/monitored-visual-v4-smoke.py')


def disk_free():
    result = {name: shutil.disk_usage(path).free for name, path in
              (('output', P), ('workspace', ROOT), ('home', Path.home()))}
    if any(type(value) is not int or value < 0 for value in result.values()):
        raise ValueError('invalid disk telemetry')
    return result


def require_disk(gib):
    if min(disk_free().values()) < gib * telemetry.GIB:
        raise RuntimeError(f'free disk below {gib} GiB')


def sample_disk(stream, phase, gib):
    volumes = disk_free(); free = min(volumes.values())
    row = {'phase': phase, 'monotonicSeconds': time.monotonic(), 'freeBytes': free, 'volumes': volumes}
    stream.write(json.dumps(row, sort_keys=True) + '\n'); stream.flush()
    if type(free) is not int or free < gib * telemetry.GIB:
        raise RuntimeError(f'free disk below {gib} GiB or unavailable')


def baseline(log):
    first = None; consecutive = 0
    while True:
        row = telemetry.sample(log, 'baseline')
        if first is None: first = row['monotonicSeconds']
        if row['freeBytes'] < 6 * telemetry.GIB: raise RuntimeError('baseline free VRAM below 6 GiB')
        consecutive = consecutive + 1 if row['busyPercent'] > 10 else 0
        if consecutive >= 5: raise RuntimeError('GPU busy above 10% for five consecutive samples')
        remaining = 30 - (row['monotonicSeconds'] - first)
        if remaining <= 0: return
        time.sleep(min(1, remaining))


def verify_logs(output):
    def rows(name):
        values = [json.loads(line) for line in (Path(output) / name).read_text().splitlines()]
        previous = -1.0
        for row in values:
            tick = row.get('monotonicSeconds')
            if type(tick) not in (int, float) or not math.isfinite(tick) or tick <= previous:
                raise ValueError('invalid monitor timestamp')
            previous = tick
        return values
    gpu = rows('telemetry.jsonl'); disk = rows('disk.jsonl')
    base = [r for r in gpu if r.get('phase') == 'baseline']
    active = [r for r in gpu if r.get('phase') == 'steering']
    if (len(base) < 2 or not active or [r.get('phase') for r in gpu] !=
            ['baseline'] * len(base) + ['steering'] * len(active) + ['after-steering'] or
            base[-1]['monotonicSeconds'] - base[0]['monotonicSeconds'] < 30 or
            any(b['monotonicSeconds'] - a['monotonicSeconds'] > 2.5 for a, b in zip(gpu, gpu[1:]))):
        raise ValueError('GPU baseline or active telemetry incomplete')
    consecutive = 0
    for row in gpu:
        if (any(type(row.get(k)) is not int for k in ('busyPercent', 'totalBytes', 'usedBytes', 'freeBytes')) or
                not 0 <= row['busyPercent'] <= 100 or row['totalBytes'] <= 0 or
                not 0 <= row['usedBytes'] <= row['totalBytes'] or row['freeBytes'] != row['totalBytes'] - row['usedBytes'] or
                row['freeBytes'] < (6 if row['phase'] == 'baseline' else 2) * telemetry.GIB):
            raise ValueError('invalid GPU telemetry or free memory')
        if row['phase'] == 'baseline':
            consecutive = consecutive + 1 if row['busyPercent'] > 10 else 0
            if consecutive >= 5: raise ValueError('GPU baseline busy guard exceeded')
    if ([r.get('phase') for r in disk] != ['pre-baseline', 'post-baseline'] +
            ['steering'] * len(active) + ['after-steering'] or
            disk[0]['monotonicSeconds'] > base[0]['monotonicSeconds'] or
            disk[1]['monotonicSeconds'] < base[-1]['monotonicSeconds'] or
            disk[1]['monotonicSeconds'] > active[0]['monotonicSeconds'] or
            disk[-1]['monotonicSeconds'] < gpu[-1]['monotonicSeconds']):
        raise ValueError('disk telemetry incomplete or out of order')
    for row in disk:
        floor = 36 if row['phase'] in ('pre-baseline', 'post-baseline') else 34
        volumes = row.get('volumes')
        if (not isinstance(volumes, dict) or set(volumes) != {'output', 'workspace', 'home'} or
                any(type(value) is not int or value < 0 for value in volumes.values()) or
                type(row.get('freeBytes')) is not int or row['freeBytes'] != min(volumes.values()) or
                row['freeBytes'] < floor * telemetry.GIB):
            raise ValueError('disk telemetry below guard')
    for index, row in enumerate(active):
        disk_tick = disk[index + 2]['monotonicSeconds']
        next_gpu = gpu[len(base) + index + 1]['monotonicSeconds']
        if not row['monotonicSeconds'] <= disk_tick <= next_gpu:
            raise ValueError('GPU and disk samples are not paired in order')


def write_new(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False); stream.write('\n')


def clean(status):
    return (isinstance(status, dict) and 'signal' in status and type(status.get('clientExit')) is int and status['clientExit'] == 0 and
            status.get('signal') is None and status.get('timedOut') is False and
            status.get('remainingWorkersTerminated') is False and
            type(status.get('processGroup')) is int and status['processGroup'] > 0)


def worker_command():
    code = ('import importlib.util,sys;'
            's=importlib.util.spec_from_file_location("runner",sys.argv[1]);'
            'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.run()')
    return [sys.executable, '-I', '-c', code, str(RUNNER)]


def environment():
    return {'PATH': '/usr/bin:/bin', 'HOME': str(Path.home()), 'SDL_VIDEODRIVER': 'offscreen',
            'PUPPYBOT_PROJECT': str(ROOT), 'LD_LIBRARY_PATH': str(ROOT / 'build/flex/rocm-runtime')}


def inventory(root):
    root = Path(root); result = {}
    if root.is_symlink() or not root.is_dir(): raise ValueError('missing or symlinked output root')
    def walk_error(error): raise error
    for directory, dirs, files in os.walk(root, topdown=True, onerror=walk_error, followlinks=False):
        parent = Path(directory)
        for name in sorted(dirs):
            path = parent / name
            if path.is_symlink() or not path.is_dir(): raise ValueError('unsafe or vanished output directory')
        for name in sorted(files):
            path = parent / name
            if path.is_symlink() or not path.is_file(): raise ValueError('unsafe or vanished output file')
            result[str(path.relative_to(root))] = base.sha(path)
    return result


def verify_saved(frozen):
    inputs = json.loads((OUTPUT / 'inputs.json').read_text())
    if inputs != frozen: raise ValueError('runner input manifest differs from registered plan')
    runner = load('steering_reaudit', RUNNER)
    report = json.loads((OUTPUT / 'report.json').read_text())
    if (not isinstance(report, dict) or report.get('schema') != 'puppybot.l5-steering-comparison.v1' or
            report.get('status') != 'diagnostic_only' or not isinstance(report.get('pairs'), list) or
            len(report['pairs']) != 12 or not isinstance(report.get('screen'), dict)):
        raise ValueError('diagnostic report is incomplete')
    if report != runner.reaudit(frozen): raise ValueError('independent saved-game re-audit differs')
    return report


def _worker(output):
    output = Path(output)
    registrar = load('steering_preflight_register', REGISTER)
    frozen = registrar.verify()
    write_new(output / 'frozen-manifest.json', frozen)
    with (output / 'telemetry.jsonl').open('x') as log, (output / 'disk.jsonl').open('x') as disk:
        sample_disk(disk, 'pre-baseline', 36); baseline(log); sample_disk(disk, 'post-baseline', 36)
        with (output / 'worker.log').open('x') as child_log:
            process = subprocess.Popen(worker_command(), cwd=ROOT, env=environment(), stdout=child_log, stderr=subprocess.STDOUT)
            # An open failure exits the monitor; the outer subreaper adopts and cleans the child.
            pidfd = os.pidfd_open(process.pid)
            deadline = time.monotonic() + WORKER_SECONDS; reason = None
            try:
                while True:
                    try:
                        row = telemetry.sample(log, 'steering'); sample_disk(disk, 'steering', 34)
                        if row['freeBytes'] < 2 * telemetry.GIB: reason = 'free VRAM below 2 GiB'
                    except (OSError, RuntimeError, ValueError) as error: reason = str(error)
                    if time.monotonic() >= deadline: reason = reason or 'steering worker deadline exceeded'
                    if reason: break
                    if process.poll() is not None: break
                    time.sleep(1)
            finally:
                try:
                    if process.poll() is None:
                        try: signal.pidfd_send_signal(pidfd, signal.SIGTERM)
                        except ProcessLookupError: pass
                        try: process.wait(timeout=15)
                        except subprocess.TimeoutExpired:
                            try: signal.pidfd_send_signal(pidfd, signal.SIGKILL)
                            except ProcessLookupError: pass
                            process.wait()
                finally: os.close(pidfd)
            if reason: raise RuntimeError(reason)
            if process.returncode != 0: raise RuntimeError(f'steering worker exited {process.returncode}')
            if telemetry.sample(log, 'after-steering')['freeBytes'] < 2 * telemetry.GIB:
                raise RuntimeError('free VRAM below 2 GiB after steering diagnostic')
            sample_disk(disk, 'after-steering', 34)
    verify_logs(output)
    if registrar.verify() != frozen: raise ValueError('registered inputs changed after collection')
    report = verify_saved(frozen)
    files = inventory(OUTPUT)
    if registrar.verify() != frozen: raise ValueError('registered inputs changed during re-audit')
    require_disk(32)
    write_new(output / 'evidence.json', {'status': 'diagnostic_only', 'report': report, 'files': files,
              'scope': 'saved training-family records only; no OS, actor or physical attestation'})


def monitor_worker(output):
    try: _worker(output)
    except BaseException as error:
        write_new(Path(output) / 'monitor-result.json', {'status': 'failed', 'reason': str(error)})
        raise
    write_new(Path(output) / 'monitor-result.json', {'status': 'passed'})


def final_check(output, evidence_sha):
    """Runs under its own absolute watchdog after GPU monitoring ends."""
    output = Path(output)
    if base.sha(output / 'evidence.json') != evidence_sha: raise ValueError('evidence changed before final check')
    evidence = json.loads((output / 'evidence.json').read_text())
    frozen = json.loads((output / 'frozen-manifest.json').read_text())
    registrar = load('steering_final_register', REGISTER)
    if registrar.verify() != frozen: raise ValueError('registered inputs changed before final inventory')
    if verify_saved(frozen) != evidence.get('report'): raise ValueError('final saved-game audit changed')
    if inventory(OUTPUT) != evidence.get('files'): raise ValueError('diagnostic output inventory changed')
    if registrar.verify() != frozen: raise ValueError('registered inputs changed during final inventory')
    if base.sha(output / 'evidence.json') != evidence_sha: raise ValueError('evidence changed during final inventory')
    return {'status': 'final_inventory_verified'}


def launch():
    """Dedicated standalone process only; outer supervisor adopts descendants."""
    guard.require_dedicated_process()
    require_disk(36)
    if not MANIFEST.is_file() or MANIFEST.is_symlink(): raise ValueError('registered steering manifest missing')
    for path in (MONITOR, OUTPUT):
        if path.exists() or path.is_symlink(): raise FileExistsError(f'output exists: {path}')
    code = ('import importlib.util,sys;'
            's=importlib.util.spec_from_file_location("monitor",sys.argv[1]);'
            'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.monitor_worker(sys.argv[2])')
    command = [sys.executable, '-I', '-c', code, str(Path(__file__).resolve()), str(MONITOR)]
    env = environment()
    paths = (Path(__file__), RUNNER, REGISTER, HERE / 'plan.py', HERE / 'audit.py', HERE / 'prepare.py',
             HERE / 'transform.py', HERE / 'probe.flex', ROOT / 'flex/tests/monitored-visual-v4-smoke.py',
             ROOT / 'flex/tests/run-physical-hidden-trial.py', ROOT / 'flex/tests/run-physical-rescan-trial.py',
             ROOT / 'flex/tests/run-physical-hybrid-trial.py', ROOT / 'experiments/sim-stop-supervisor/supervisor.py',
             ROOT / 'experiments/sim-stop-supervisor/proxy.py')
    source = {str(path): base.sha(path) for path in paths}
    MONITOR.mkdir(); outer = MONITOR / 'outer-monitor'; outer.mkdir()
    write_new(MONITOR / 'launch.json', {'command': command, 'environment': env,
              'wallSeconds': OUTER_SECONDS, 'workerCommand': worker_command(), 'workerEnvironment': env,
              'workerWallSeconds': WORKER_SECONDS, 'sourcePins': source,
              'scope': 'intended invocation and source pins; no execution attestation'})
    status = base.hidden.supervise(command, outer, env, OUTER_SECONDS)
    outer_status = json.loads((outer / 'supervisor-result.json').read_text())
    if not clean(status) or outer_status != status: raise RuntimeError('resource monitor failed; retained evidence is censored')
    outer_sha = base.sha(outer / 'supervisor-result.json')
    if any(base.sha(Path(path)) != expected for path, expected in source.items()): raise ValueError('monitor sources changed')
    result = json.loads((MONITOR / 'monitor-result.json').read_text())
    evidence = json.loads((MONITOR / 'evidence.json').read_text())
    frozen = json.loads((MONITOR / 'frozen-manifest.json').read_text())
    frozen_sha = base.sha(MONITOR / 'frozen-manifest.json')
    inputs = json.loads((OUTPUT / 'inputs.json').read_text())
    report = json.loads((OUTPUT / 'report.json').read_text())
    if (result.get('status') != 'passed' or evidence.get('status') != 'diagnostic_only' or inputs != frozen or
            evidence.get('report') != report or not isinstance(report, dict) or
            report.get('schema') != 'puppybot.l5-steering-comparison.v1' or report.get('status') != 'diagnostic_only' or
            not isinstance(report.get('pairs'), list) or len(report['pairs']) != 12 or not isinstance(report.get('screen'), dict)):
        raise ValueError('monitor evidence incomplete or mismatched')
    files = evidence.get('files')
    if not isinstance(files, dict): raise ValueError('missing output inventory')
    for name in ('inputs.json', 'report.json'):
        if files.get(name) != base.sha(OUTPUT / name): raise ValueError('diagnostic metadata changed')
    verify_logs(MONITOR); require_disk(32)
    telemetry_sha = base.sha(MONITOR / 'telemetry.jsonl'); disk_sha = base.sha(MONITOR / 'disk.jsonl')
    final_dir = MONITOR / 'final-inventory-monitor'; final_dir.mkdir()
    evidence_sha = base.sha(MONITOR / 'evidence.json')
    code = ('import importlib.util,json,sys;'
            's=importlib.util.spec_from_file_location("monitor",sys.argv[1]);'
            'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);'
            'print(json.dumps(m.final_check(sys.argv[2],sys.argv[3]),sort_keys=True))')
    final_command = [sys.executable, '-I', '-c', code, str(Path(__file__).resolve()), str(MONITOR), evidence_sha]
    write_new(final_dir / 'invocation.json', {'argv': final_command, 'environment': env, 'wallSeconds': FINAL_CHECK_SECONDS})
    final_invocation_sha = base.sha(final_dir / 'invocation.json')
    final = base.hidden.supervise(final_command, final_dir, env, FINAL_CHECK_SECONDS)
    final_status = json.loads((final_dir / 'supervisor-result.json').read_text())
    if not clean(final) or final_status != final or json.loads((final_dir / 'client.log').read_text()) != {'status': 'final_inventory_verified'}:
        raise RuntimeError('final inventory failed; retained evidence is censored')
    final_status_sha = base.sha(final_dir / 'supervisor-result.json')
    if any(base.sha(Path(path)) != expected for path, expected in source.items()): raise ValueError('sources changed during final inventory')
    if base.sha(MONITOR / 'evidence.json') != evidence_sha: raise ValueError('evidence changed after final inventory')
    if base.sha(MONITOR / 'telemetry.jsonl') != telemetry_sha or base.sha(MONITOR / 'disk.jsonl') != disk_sha:
        raise ValueError('resource evidence changed during final inventory')
    if (base.sha(outer / 'supervisor-result.json') != outer_sha or
            base.sha(final_dir / 'invocation.json') != final_invocation_sha or
            base.sha(final_dir / 'supervisor-result.json') != final_status_sha or
            base.sha(MONITOR / 'frozen-manifest.json') != frozen_sha):
        raise ValueError('supervisor or manifest evidence changed during final inventory')
    require_disk(32)
    write_new(MONITOR / 'completion.json', {'status': 'diagnostic_only', 'evidenceSHA256': evidence_sha,
              'telemetrySHA256': telemetry_sha, 'diskSHA256': disk_sha,
              'outerSupervisorStatusSHA256': outer_sha, 'frozenManifestSHA256': frozen_sha,
              'finalInventoryInvocationSHA256': final_invocation_sha,
              'finalInventoryStatusSHA256': final_status_sha,
              'scope': 'local saved simulator evidence only; no OS, actor or physical attestation'})
    return evidence['report']


if __name__ == '__main__':
    raise SystemExit('Disabled pending independent review and scheduling; no GPU launch authorized.')
