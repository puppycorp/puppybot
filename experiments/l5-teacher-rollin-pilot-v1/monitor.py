#!/usr/bin/env python3
"""Disabled GPU/disk monitor for the paired L5 training roll-in pilot."""
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
OUTER_SECONDS = 2100
WORKER_SECONDS = 1950
FINAL_CHECK_SECONDS = 300


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


pilot = load('teacher_rollin_monitor_pilot', HERE / 'pilot.py')
telemetry = load('hybrid_gpu_telemetry', ROOT / 'flex/tests/monitored-visual-v4-smoke.py')


def require_disk(gib):
    if shutil.disk_usage(pilot.P).free < gib * telemetry.GIB:
        raise RuntimeError(f'free disk below {gib} GiB')


def sample_disk(stream, phase, gib):
    free = shutil.disk_usage(pilot.P).free
    row = {'phase': phase, 'monotonicSeconds': time.monotonic(), 'freeBytes': free}
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
    active = [r for r in gpu if r.get('phase') == 'rollin']
    if (len(base) < 2 or not active or [r.get('phase') for r in gpu] !=
            ['baseline'] * len(base) + ['rollin'] * len(active) + ['after-rollin'] or
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
            ['rollin'] * len(active) + ['after-rollin'] or
            disk[0]['monotonicSeconds'] > base[0]['monotonicSeconds'] or
            disk[1]['monotonicSeconds'] < base[-1]['monotonicSeconds'] or
            disk[1]['monotonicSeconds'] > active[0]['monotonicSeconds'] or
            disk[-1]['monotonicSeconds'] < gpu[-1]['monotonicSeconds']):
        raise ValueError('disk telemetry incomplete or out of order')
    for row in disk:
        floor = 36 if row['phase'] in ('pre-baseline', 'post-baseline') else 34
        if type(row.get('freeBytes')) is not int or row['freeBytes'] < floor * telemetry.GIB:
            raise ValueError('disk telemetry below guard')
    for index, row in enumerate(active):
        disk_tick = disk[index + 2]['monotonicSeconds']
        next_gpu = gpu[len(base) + index + 1]['monotonicSeconds']
        if not row['monotonicSeconds'] <= disk_tick <= next_gpu:
            raise ValueError('GPU and disk samples are not paired in order')


def worker_command():
    code = ('import importlib.util,sys;'
            's=importlib.util.spec_from_file_location("pilot",sys.argv[1]);'
            'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.run()')
    return [sys.executable, '-I', '-c', code, str(HERE / 'pilot.py')]


def environment():
    return {'PATH': '/usr/bin:/bin', 'HOME': str(Path.home()), 'SDL_VIDEODRIVER': 'offscreen',
            'LD_LIBRARY_PATH': str(ROOT / 'build/flex/rocm-runtime')}


def inventory(root):
    result = {}
    for path in sorted(Path(root).rglob('*')):
        if path.is_symlink(): raise ValueError('symlink in pilot output')
        if path.is_file(): result[str(path.relative_to(root))] = pilot.sha(path)
        elif not path.is_dir(): raise ValueError('unexpected pilot output')
    return result


def verify_pilot(frozen):
    root = pilot.OUTPUT
    inputs = json.loads((root / 'inputs.json').read_text())
    if inputs.get('files') != frozen or inputs.get('seeds') != list(pilot.SEEDS):
        raise ValueError('pilot input receipt differs')
    for arm in ('student', 'teacher'):
        directory = root / f'monitor-{arm}'
        invocation = json.loads((directory / 'invocation.json').read_text())
        if invocation != {'argv': pilot.command(arm, root / arm), 'environment': environment(), 'wallSeconds': 600}:
            raise ValueError('arm invocation differs')
        status = json.loads((directory / 'supervisor-result.json').read_text())
        if (type(status.get('clientExit')) is not int or status['clientExit'] != 0 or status.get('signal') is not None or
                status.get('timedOut') is not False or status.get('remainingWorkersTerminated') is not False or
                type(status.get('processGroup')) is not int or status['processGroup'] <= 0):
            raise ValueError('arm supervisor not clean')
    student = pilot.audit_arm(root / 'student', 'student', frozen)
    teacher = pilot.audit_arm(root / 'teacher', 'teacher', frozen)
    report = json.loads((root / 'report.json').read_text())
    if report != pilot.compare(student, teacher): raise ValueError('fresh pilot audit differs from report')
    return report


def _worker(output):
    output = Path(output)
    # Hashes, collection and independent saved-data re-audit all run inside
    # the outer absolute deadline, including work before and after GPU use.
    frozen = pilot.pin_inputs()
    pilot.write_new(output / 'frozen-inputs.json', frozen)
    with (output / 'telemetry.jsonl').open('x') as log, (output / 'disk.jsonl').open('x') as disk:
        sample_disk(disk, 'pre-baseline', 36); baseline(log); sample_disk(disk, 'post-baseline', 36)
        with (output / 'worker.log').open('x') as child_log:
            process = subprocess.Popen(worker_command(), cwd=ROOT, stdout=child_log, stderr=subprocess.STDOUT)
            # If pidfd_open fails, the enclosing subreaper still cleans the worker tree.
            pidfd = os.pidfd_open(process.pid)
            deadline = time.monotonic() + WORKER_SECONDS; reason = None
            try:
                while True:
                    try:
                        row = telemetry.sample(log, 'rollin'); sample_disk(disk, 'rollin', 34)
                        if row['freeBytes'] < 2 * telemetry.GIB: reason = 'free VRAM below 2 GiB'
                    except (OSError, RuntimeError, ValueError) as error: reason = str(error)
                    if time.monotonic() >= deadline: reason = reason or 'pilot worker deadline exceeded'
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
            if process.returncode != 0: raise RuntimeError(f'pilot worker exited {process.returncode}')
            if telemetry.sample(log, 'after-rollin')['freeBytes'] < 2 * telemetry.GIB:
                raise RuntimeError('free VRAM below 2 GiB after pilot')
            sample_disk(disk, 'after-rollin', 34)
    verify_logs(output)
    if pilot.pin_inputs() != frozen: raise ValueError('pilot inputs changed after collection')
    report = verify_pilot(frozen)
    files = inventory(pilot.OUTPUT)
    if pilot.pin_inputs() != frozen: raise ValueError('pilot inputs changed during re-audit')
    require_disk(32)
    pilot.write_new(output / 'evidence.json', {'status': 'diagnostic_only', 'report': report, 'files': files,
                    'scope': 'saved-data training pilot only; no runtime attestation, training or physical claim'})


def monitor_worker(output):
    try: _worker(output)
    except BaseException as error:
        pilot.write_new(Path(output) / 'monitor-result.json', {'status': 'failed', 'reason': str(error)})
        raise
    pilot.write_new(Path(output) / 'monitor-result.json', {'status': 'passed'})


def final_check(output, evidence_sha):
    """Run under a separate absolute deadline, after resource monitoring stops."""
    output = Path(output)
    if pilot.sha(output / 'evidence.json') != evidence_sha: raise ValueError('evidence changed before inventory')
    evidence = json.loads((output / 'evidence.json').read_text())
    frozen = json.loads((output / 'frozen-inputs.json').read_text())
    if pilot.pin_inputs() != frozen: raise ValueError('inputs changed before final inventory')
    if inventory(pilot.OUTPUT) != evidence.get('files'):
        raise ValueError('pilot output inventory changed')
    report = json.loads((pilot.OUTPUT / 'report.json').read_text())
    if evidence.get('status') != 'diagnostic_only' or evidence.get('report') != report:
        raise ValueError('pilot report changed')
    if pilot.pin_inputs() != frozen: raise ValueError('inputs changed during final inventory')
    if pilot.sha(output / 'evidence.json') != evidence_sha: raise ValueError('evidence changed during inventory')
    return {'status': 'final_inventory_verified'}


def launch():
    """Dedicated standalone process only; outer supervisor adopts descendants."""
    pilot.standalone.require_dedicated_process()
    require_disk(36)
    output = pilot.P / 'l5-teacher-rollin-pilot-monitored-v1'
    for path in (output, pilot.OUTPUT):
        if path.exists() or path.is_symlink(): raise FileExistsError(f'output exists: {path}')
    output.mkdir(); outer = output / 'outer-monitor'; outer.mkdir()
    code = ('import importlib.util,sys;'
            's=importlib.util.spec_from_file_location("monitor",sys.argv[1]);'
            'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.monitor_worker(sys.argv[2])')
    command = [sys.executable, '-I', '-c', code, str(Path(__file__).resolve()), str(output)]
    env = environment()
    # This small source pin is checked again after the bounded child exits.
    paths = (Path(__file__), ROOT / 'flex/tests/monitored-visual-v4-smoke.py',
             ROOT / 'flex/tests/run-physical-hidden-trial.py', HERE / 'pilot.py')
    source = {str(path): pilot.sha(path) for path in paths}
    pilot.write_new(output / 'launch.json', {'command': command, 'environment': env,
                    'wallSeconds': OUTER_SECONDS, 'sourcePins': source})
    status = pilot.base.hidden.supervise(command, outer, env, OUTER_SECONDS)
    if (type(status.get('clientExit')) is not int or status['clientExit'] != 0 or status.get('signal') is not None or
            status.get('timedOut') is not False or status.get('remainingWorkersTerminated') is not False or
            type(status.get('processGroup')) is not int or status['processGroup'] <= 0):
        raise RuntimeError('resource monitor failed; retained evidence is censored')
    if any(pilot.sha(Path(path)) != expected for path, expected in source.items()):
        raise ValueError('monitor sources changed')
    result = json.loads((output / 'monitor-result.json').read_text())
    evidence = json.loads((output / 'evidence.json').read_text())
    if result.get('status') != 'passed' or evidence.get('status') != 'diagnostic_only':
        raise ValueError('monitor evidence incomplete')
    frozen = json.loads((output / 'frozen-inputs.json').read_text())
    inputs = json.loads((pilot.OUTPUT / 'inputs.json').read_text())
    report = json.loads((pilot.OUTPUT / 'report.json').read_text())
    if inputs.get('files') != frozen or evidence.get('report') != report or report.get('status') != 'diagnostic_only':
        raise ValueError('pilot report or frozen inputs differ')
    files = evidence.get('files')
    if not isinstance(files, dict): raise ValueError('pilot inventory missing')
    names = ['inputs.json', 'report.json']
    for arm in ('student', 'teacher'):
        names += [f'monitor-{arm}/invocation.json', f'monitor-{arm}/supervisor-result.json']
        if not all(f'{arm}/{name}' in files for name in ('report.json', 'data.bin', 'map.bin')):
            raise ValueError('pilot data inventory incomplete')
    if any(files.get(name) != pilot.sha(pilot.OUTPUT / name) for name in names):
        raise ValueError('pilot evidence changed after re-audit')
    verify_logs(output)
    require_disk(32)
    final_dir = output / 'final-inventory-monitor'; final_dir.mkdir()
    evidence_sha = pilot.sha(output / 'evidence.json')
    code = ('import importlib.util,json,sys;'
            's=importlib.util.spec_from_file_location("monitor",sys.argv[1]);'
            'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);'
            'print(json.dumps(m.final_check(sys.argv[2],sys.argv[3]),sort_keys=True))')
    final_command = [sys.executable, '-I', '-c', code, str(Path(__file__).resolve()), str(output), evidence_sha]
    pilot.write_new(final_dir / 'invocation.json', {'argv': final_command, 'environment': env,
                    'wallSeconds': FINAL_CHECK_SECONDS})
    final = pilot.base.hidden.supervise(final_command, final_dir, env, FINAL_CHECK_SECONDS)
    if (type(final.get('clientExit')) is not int or final['clientExit'] != 0 or final.get('signal') is not None or
            final.get('timedOut') is not False or final.get('remainingWorkersTerminated') is not False or
            type(final.get('processGroup')) is not int or final['processGroup'] <= 0 or
            json.loads((final_dir / 'client.log').read_text()) != {'status': 'final_inventory_verified'}):
        raise RuntimeError('final inventory failed; retained evidence is censored')
    if any(pilot.sha(Path(path)) != expected for path, expected in source.items()):
        raise ValueError('monitor sources changed during final inventory')
    if pilot.sha(output / 'evidence.json') != evidence_sha: raise ValueError('evidence changed after final inventory')
    require_disk(32)
    pilot.write_new(output / 'completion.json', {'status': 'diagnostic_only',
                    'evidenceSHA256': evidence_sha,
                    'telemetrySHA256': pilot.sha(output / 'telemetry.jsonl'),
                    'diskSHA256': pilot.sha(output / 'disk.jsonl'),
                    'finalInventoryStatusSHA256': pilot.sha(final_dir / 'supervisor-result.json'),
                    'scope': 'local training-pilot diagnostic; no runtime attestation or physical claim'})
    return evidence['report']


if __name__ == '__main__':
    raise SystemExit('Disabled pending independent review and scheduling; no GPU launch authorized.')
