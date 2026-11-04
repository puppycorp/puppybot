#!/usr/bin/env python3
"""Dedicated serial two-arm monitor; direct command-line launch remains disabled."""
import importlib.util
import json
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


base = load('turn_existing_monitor', ROOT / 'experiments/physical-search-fallback-monitor-v1/monitor.py')
base.__file__ = str(HERE / 'monitor.py'); base.TRIAL = HERE
base.runner = load('turn_pair_runner', HERE / 'run.py')
original_pins, original_sample_disk = base.source_pins, base.sample_disk
original_verify_logs, original_final_worker = base.verify_logs, base.final_worker
original_base_env = base.base_env
guardian = load('turn_lock_guardian', HERE / 'guardian.py')


def source_pins():
    result = original_pins()
    for path in (ROOT / 'experiments/physical-search-fallback-monitor-v1/monitor.py',
                 HERE / 'build.py', HERE / 'transform.py', HERE / 'guardian.py',
                 ROOT / 'experiments/dock-turn-reacquire-current-v1/baseline-case.flex',
                 ROOT / 'experiments/dock-turn-reacquire-current-v1/transform.py',
                 ROOT / 'experiments/dock-turn-reacquire-v1/transform.py'):
        result[str(path)] = base.runner.sha(path)
    return result


def sample_disk(stream, phase, paths, gib):
    result = original_sample_disk(stream, phase, paths, max(gib, 38) if phase in ('pre-baseline', 'post-baseline') else gib)
    if phase == 'post-baseline':
        output = Path(os.environ['PUPPY_TURN_GUARD_OUTPUT'])
        temporary, marker = output / 'baseline-passed.tmp', output / 'baseline-passed.json'
        base.write_new(temporary, {'status': 'passed', 'monotonicSeconds': time.monotonic()})
        os.link(temporary, marker); temporary.unlink()
    return result


def verify_logs(output):
    original_verify_logs(output)
    rows = [json.loads(line) for line in (Path(output) / 'disk.jsonl').read_text().splitlines()]
    if any(min(row['freeBytes'].values()) < 38 * base.GIB for row in rows
           if row['phase'] in ('pre-baseline', 'post-baseline')):
        raise ValueError('pilot baseline disk below 38 GiB')


def final_worker(output, worker_hash):
    trial = Path(output) / 'trial'; manifest = json.loads((trial / 'inputs.json').read_text())
    base.runner.check_manifest(trial, manifest)
    original_final_worker(output, worker_hash)
    base.runner.check_manifest(trial, manifest)


def base_env():
    env = original_base_env()
    for key in ('PUPPY_TURN_GUARD_PID', 'PUPPY_TURN_GUARD_FD', 'PUPPY_TURN_GUARD_OUTPUT'):
        if key not in os.environ:
            raise RuntimeError('guardian identity missing')
        env[key] = os.environ[key]
    return env


base.source_pins = source_pins
base.sample_disk = sample_disk
base.verify_logs = verify_logs
base.final_worker = final_worker
base.base_env = base_env
trial_worker, monitor_worker = base.trial_worker, base.monitor_worker


def resource_read(output):
    # Snapshot phase before reading any resource. A marker appearing during
    # sampling retains the stricter baseline floor for this whole sample.
    marker = Path(output) / 'baseline-passed.json'
    passed = marker.is_file() and not marker.is_symlink()
    if passed:
        value = json.loads(marker.read_text()); tick = value.get('monotonicSeconds')
        if value.get('status') != 'passed' or type(tick) not in (int, float) or not 0 < tick <= time.monotonic():
            raise ValueError('invalid baseline marker')
    gpu = base.telemetry.telemetry(base.telemetry.DEVICE)
    volumes = {key: shutil.disk_usage(path).free for key, path in base.disk_paths(output).items()}
    return {'freeBytes': min(volumes.values()), 'volumes': volumes, 'gpuFreeBytes': gpu['freeBytes'],
            'gpuTotalBytes': gpu['totalBytes'], 'gpuUsedBytes': gpu['usedBytes'], 'gpuBusyPercent': gpu['busyPercent'],
            'baselinePassed': passed}


def coordinator(output, build, case, environment, model):
    return base.launch(output, build, case, environment, model)


def guardian_entry(output, build, case, environment, model, parent_pid):
    output = Path(output).absolute()
    code = ('import importlib.util,sys;'
            's=importlib.util.spec_from_file_location("turn_monitor",sys.argv[1]);'
            'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.coordinator(*sys.argv[2:])')
    command = [sys.executable, '-I', '-c', code, str(HERE / 'monitor.py'), str(output / 'coordinator'),
               str(build), str(case), str(environment), str(model)]
    env = original_base_env()
    result = guardian.run(output, base.runner.LOCK, command, env, int(parent_pid), lambda: resource_read(output))
    if result['status'] != 'passed':
        raise RuntimeError('guardian did not complete cleanly; retained evidence is censored')


def verify_guardian(output):
    output = Path(output)
    outer = json.loads((output / 'launcher.json').read_text())
    launch = json.loads((output / 'guardian-launch.json').read_text())
    result = json.loads((output / 'guardian-result.json').read_text())
    rows = [json.loads(line) for line in (output / 'guardian-telemetry.jsonl').read_text().splitlines()]
    active = [row for row in rows if row.get('phase') == 'active']
    cleanup = [row for row in rows if row.get('phase') == 'cleanup']
    args = outer.get('command', [])
    if (len(args) != 11 or args[4] != str(HERE / 'monitor.py') or args[5] != str(output) or
            type(launch.get('guardianPID')) is not int or launch['guardianPID'] <= 1 or
            type(launch.get('coordinatorPID')) is not int or launch['coordinatorPID'] <= 1 or
            launch.get('parentPID') != int(args[10]) or launch.get('wallSeconds') != 4200):
        raise ValueError('guardian launch identity differs')
    code = ('import importlib.util,sys;'
            's=importlib.util.spec_from_file_location("turn_monitor",sys.argv[1]);'
            'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.coordinator(*sys.argv[2:])')
    expected_command = [sys.executable, '-I', '-c', code, str(HERE / 'monitor.py'), str(output / 'coordinator'), *args[6:10]]
    env = dict(outer['environment']); env.update(PUPPY_TURN_GUARD_PID=str(launch['guardianPID']),
        PUPPY_TURN_GUARD_FD=launch['environment'].get('PUPPY_TURN_GUARD_FD'), PUPPY_TURN_GUARD_OUTPUT=str(output))
    if (launch.get('command') != expected_command or launch.get('environment') != env or
            not str(env['PUPPY_TURN_GUARD_FD']).isdigit()):
        raise ValueError('guardian coordinator invocation differs')
    if (result.get('status') != 'passed' or result.get('reason') is not None or
            type(result.get('coordinatorExit')) is not int or result['coordinatorExit'] != 0 or
            result.get('descendantsTerminated') is not False or result.get('diskEmergency') is not False or
            len(active) < 1 or len(cleanup) < 2 or len(rows) != result.get('samples') or
            [row.get('phase') for row in rows] != ['active'] * len(active) + ['cleanup'] * len(cleanup)):
        raise ValueError('guardian did not finish cleanly')
    times = [row.get('monotonicSeconds') for row in rows]
    if (any(type(t) not in (int, float) or not math.isfinite(t) for t in times) or
            any(not 0 < b - a <= 2.5 for a, b in zip(times, times[1:])) or
            not launch['startedMonotonic'] <= times[0] <= result['observedDoneMonotonic'] <= times[-1] <= result['endedMonotonic'] or
            times[0] - launch['startedMonotonic'] > 2.5 or result['endedMonotonic'] - times[-1] > 2.5):
        raise ValueError('guardian resource sample coverage incomplete')
    marker_path = output / 'baseline-passed.json'
    if marker_path.is_symlink() or not marker_path.is_file(): raise ValueError('invalid baseline marker file')
    marker = json.loads(marker_path.read_text()); marker_tick = marker.get('monotonicSeconds')
    if (marker.get('status') != 'passed' or type(marker_tick) not in (int, float) or not math.isfinite(marker_tick) or
            not launch['startedMonotonic'] <= marker_tick <= result['observedDoneMonotonic']):
        raise ValueError('baseline marker differs')
    seen_passed = False
    for row in rows:
        volumes = row.get('volumes')
        passed = row.get('baselinePassed')
        if type(passed) is not bool or (seen_passed and not passed) or (passed and row['monotonicSeconds'] < marker_tick):
            raise ValueError('guardian baseline phase differs')
        seen_passed = seen_passed or passed
        floor = 34 if passed else 38
        if (not isinstance(volumes, dict) or set(volumes) != {'workspace', 'home', 'output'} or
                any(type(v) is not int or v < floor * base.GIB for v in volumes.values()) or
                row.get('freeBytes') != min(volumes.values()) or type(row.get('gpuFreeBytes')) is not int or
                type(row.get('gpuTotalBytes')) is not int or type(row.get('gpuUsedBytes')) is not int or
                row['gpuTotalBytes'] <= 0 or not 0 <= row['gpuUsedBytes'] <= row['gpuTotalBytes'] or
                row['gpuFreeBytes'] != row['gpuTotalBytes'] - row['gpuUsedBytes'] or
                row['gpuFreeBytes'] < 2 * base.GIB or type(row.get('gpuBusyPercent')) is not int or
                not 0 <= row['gpuBusyPercent'] <= 100):
            raise ValueError('guardian resource sample invalid')
    if not seen_passed: raise ValueError('guardian missed baseline completion')
    return result


def launch(output, build, case, environment, model):
    base.guard.require_dedicated_process()
    output, build, case, environment, model = (Path(p).absolute() for p in (output, build, case, environment, model))
    if output.exists() or output.is_symlink(): raise FileExistsError('output exists; preserve evidence')
    if any(shutil.disk_usage(path).free < 38 * base.GIB for path in base.disk_paths(output.parent).values()):
        raise ValueError('insufficient disk before baseline')
    pins = source_pins(); output.mkdir()
    code = ('import importlib.util,sys;'
            's=importlib.util.spec_from_file_location("turn_monitor",sys.argv[1]);'
            'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.guardian_entry(*sys.argv[2:])')
    command = [sys.executable, '-I', '-c', code, str(HERE / 'monitor.py'), str(output), str(build), str(case),
               str(environment), str(model), str(os.getpid())]
    env = original_base_env()
    base.write_new(output / 'launcher.json', {'command': command, 'environment': env, 'sourcePins': pins})
    with (output / 'guardian.log').open('x') as log:
        process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        code = process.wait()
    if code != 0 or source_pins() != pins:
        raise RuntimeError('guardian failed or sources changed; retained evidence is censored')
    verify_guardian(output)
    coordinator_receipt = output / 'coordinator/completion.json'
    receipt = json.loads(coordinator_receipt.read_text())
    if receipt.get('status') != 'diagnostic_only':
        raise RuntimeError('coordinator did not complete')
    if any(shutil.disk_usage(path).free < 32 * base.GIB for path in base.disk_paths(output).values()):
        raise RuntimeError('disk below final 32 GiB floor')
    base.write_new(output / 'completion.json', {'status': 'diagnostic_only',
        'comparisonEligible': receipt.get('comparisonEligible'), 'censorReason': receipt.get('censorReason'),
        'coordinatorCompletionSHA256': base.runner.sha(coordinator_receipt),
        'guardianLaunchSHA256': base.runner.sha(output / 'guardian-launch.json'),
        'guardianResultSHA256': base.runner.sha(output / 'guardian-result.json'),
        'guardianTelemetrySHA256': base.runner.sha(output / 'guardian-telemetry.jsonl'),
        'baselineMarkerSHA256': base.runner.sha(output / 'baseline-passed.json'),
        'scope': 'simulated two-arm selection diagnostic; no held-out or physical qualification'})
    return receipt


if __name__ == '__main__':
    raise SystemExit('Disabled pending independent review and resource scheduling.')
