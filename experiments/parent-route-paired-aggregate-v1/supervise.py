#!/usr/bin/env python3
"""Guarded, serial CPU creation and independent paired-byte recheck."""
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
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


plan = load('parent_pair_plan', HERE / 'plan.py')
guardian = plan.guardian
hidden = plan.collector.hidden
telemetry = plan.collector.telemetry
standalone = plan.collector.standalone
GIB = 1024 ** 3
LOCK = plan.P / '.l4-matched.lock'


def write_new(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False); stream.write('\n')
        stream.flush(); os.fsync(stream.fileno())


def clean(status):
    return (isinstance(status, dict) and type(status.get('clientExit')) is int and status['clientExit'] == 0 and
            status.get('timedOut') is False and status.get('remainingWorkersTerminated') is False and
            status.get('signal') is None and type(status.get('processGroup')) is int and status['processGroup'] > 0)


def source_args():
    return [plan.COLLECTION / f'shard-{index}' for index in range(2)]


def selected():
    return [tuple(row) for row in plan.SELECTED]


def verify_outputs():
    return plan.verify.verify(plan.BASE / 'data.bin', plan.BASE / 'map.bin', plan.source_specs(),
                              plan.OUTPUT / 'control/data.bin', plan.OUTPUT / 'control/map.bin',
                              plan.OUTPUT / 'treatment/data.bin', plan.OUTPUT / 'treatment/map.bin')


def output_inventory():
    expected = {'report.json', 'control/data.bin', 'control/map.bin', 'treatment/data.bin', 'treatment/map.bin'}
    if plan.OUTPUT.is_symlink() or not plan.OUTPUT.is_dir():
        raise ValueError('unsafe paired output root')
    files = set(); directories = set()
    def onerror(error):
        raise error
    for directory, children, names in os.walk(plan.OUTPUT, followlinks=False, onerror=onerror):
        parent = Path(directory)
        for name in children:
            path = parent / name
            if path.is_symlink() or not path.is_dir():
                raise ValueError('unsafe paired output directory')
            directories.add(str(path.relative_to(plan.OUTPUT)))
        for name in names:
            path = parent / name
            if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1:
                raise ValueError('unsafe paired output file')
            files.add(str(path.relative_to(plan.OUTPUT)))
    if directories != {'control', 'treatment'} or files != expected:
        raise ValueError('paired output inventory differs')
    return {name: {'size': (plan.OUTPUT / name).stat().st_size, 'sha256': plan.sha(plan.OUTPUT / name)}
            for name in sorted(files)}


def priority():
    cpu = os.getpriority(os.PRIO_PROCESS, 0)
    io = subprocess.run(['/usr/bin/ionice', '-p', str(os.getpid())], capture_output=True, text=True,
                        check=True, timeout=5).stdout.strip()
    if cpu < 15 or io != 'idle':
        raise ValueError('CPU worker must use low CPU and idle I/O priority')
    return {'cpuNice': cpu, 'ioClass': io}


def worker():
    priorities = priority(); frozen = plan.verify_plan()
    if plan.OUTPUT.exists() or plan.OUTPUT.is_symlink():
        raise FileExistsError('paired output exists; retain evidence')
    plan.OUTPUT.mkdir()
    first = plan.builder.create_control(plan.BASE / 'data.bin', plan.BASE / 'map.bin', source_args(),
                                        plan.OUTPUT / 'control', selected())
    write_new(plan.MONITOR / 'control-result.json', {'status': 'control_bytes_created_unverified', **first,
              'dataSHA256': plan.sha(plan.OUTPUT / 'control/data.bin'),
              'mapSHA256': plan.sha(plan.OUTPUT / 'control/map.bin')})
    if plan.verify_plan() != frozen:
        raise ValueError('input changed before treatment reservation')
    # This independently reserves a second full unshared output after control.
    second = plan.builder.create_treatment(plan.OUTPUT / 'control', source_args(),
                                           plan.OUTPUT / 'treatment', selected())
    verified = verify_outputs()
    if verified.get('status') != 'paired_aggregate_bytes_verified' or verified.get('trainingAuthorized') is not False:
        raise ValueError('paired byte verifier did not pass')
    if verified.get('prefixLabelDifferences') != [35, 31] or plan.verify_plan() != frozen:
        raise ValueError('paired labels or source provenance changed')
    hashes = {arm: {name: plan.sha(plan.OUTPUT / arm / name) for name in ('data.bin', 'map.bin')}
              for arm in ('control', 'treatment')}
    report = {'schema': 'puppybot.parent-route-paired-aggregate-result.v1',
              'status': 'candidate_data_only', 'trainingAuthorized': False, 'control': first,
              'treatment': second, 'verification': verified, 'outputSHA256': hashes,
              'trainerRequirement': {'episodes': 1031, 'fitting': 935, 'length': 300,
                                     'auxiliaryMaskEpisodeRange': [928, 935],
                                     'status': 'not_verified_or_authorized'},
              'scope': 'paired training-family candidate bytes only; no model, selection or physical claim'}
    write_new(plan.OUTPUT / 'report.json', report)
    write_new(plan.MONITOR / 'worker-result.json', {'status': 'candidate_data_only',
              'reportSHA256': plan.sha(plan.OUTPUT / 'report.json'), 'priority': priorities})


def final_check():
    priorities = priority(); frozen = plan.verify_plan(); plan_hash = plan.sha(plan.PLAN)
    worker = json.loads((plan.MONITOR / 'worker-result.json').read_text())
    report = json.loads((plan.OUTPUT / 'report.json').read_text()); report_hash = plan.sha(plan.OUTPUT / 'report.json')
    if worker.get('status') != 'candidate_data_only' or worker.get('reportSHA256') != report_hash:
        raise ValueError('worker evidence differs')
    fresh = verify_outputs()
    if fresh != report.get('verification') or fresh.get('trainingAuthorized') is not False:
        raise ValueError('independent paired byte verification differs')
    hashes = {arm: {name: plan.sha(plan.OUTPUT / arm / name) for name in ('data.bin', 'map.bin')}
              for arm in ('control', 'treatment')}
    if hashes != report.get('outputSHA256'):
        raise ValueError('paired output hash differs')
    if (plan.verify_plan() != frozen or plan.sha(plan.PLAN) != plan_hash or
            plan.sha(plan.OUTPUT / 'report.json') != report_hash):
        raise ValueError('input or report changed during final audit')
    inventory = output_inventory()
    if (output_inventory() != inventory or plan.verify_plan() != frozen or plan.sha(plan.PLAN) != plan_hash or
            plan.sha(plan.OUTPUT / 'report.json') != report_hash):
        raise ValueError('paired output or source changed during final inventory')
    write_new(plan.MONITOR / 'final-result.json', {'status': 'paired_bytes_verified',
              'planSHA256': plan_hash, 'reportSHA256': report_hash, 'verification': fresh,
              'outputSHA256': hashes, 'outputInventory': inventory, 'priority': priorities})


def command(function):
    if function not in ('worker', 'final_check', 'coordinator'):
        raise ValueError('unknown paired-data subprocess')
    code = ('import importlib.util,sys;s=importlib.util.spec_from_file_location("pair",sys.argv[1]);'
            'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);getattr(m,sys.argv[2])()')
    return ['/usr/bin/nice', '-n', '15', '/usr/bin/ionice', '-c', '3', sys.executable, '-I', '-c', code,
            str(Path(__file__).resolve()), function]


def environment():
    return {'PATH': '/usr/bin:/bin', 'HOME': str(Path.home())}


def supervise_phase(name, function, seconds):
    directory = plan.MONITOR / name; directory.mkdir()
    argv = command(function); env = environment()
    write_new(directory / 'invocation.json', {'argv': argv, 'environment': env, 'wallSeconds': seconds})
    status = hidden.supervise(argv, directory, env, seconds)
    if not clean(status) or json.loads((directory / 'supervisor-result.json').read_text()) != status:
        raise RuntimeError(f'{name} failed or left descendants; retain outputs')
    return status


def supervisor_hashes():
    names = {}
    for phase in ('worker-supervisor', 'final-supervisor'):
        for filename in ('client.log', 'invocation.json', 'supervisor-result.json'):
            path = plan.MONITOR / phase / filename
            if path.is_symlink() or not path.is_file():
                raise ValueError('missing or linked supervisor evidence')
            names[f'{phase}/{filename}'] = plan.sha(path)
    return names


def verify_phase_results():
    for phase, function, seconds in (('worker-supervisor', 'worker', 3600),
                                     ('final-supervisor', 'final_check', 2400)):
        directory = plan.MONITOR / phase
        expected = {'argv': command(function), 'environment': environment(), 'wallSeconds': seconds}
        if (json.loads((directory / 'invocation.json').read_text()) != expected or
                not clean(json.loads((directory / 'supervisor-result.json').read_text()))):
            raise ValueError('paired supervisor invocation or status differs')


def coordinator():
    frozen = plan.verify_plan()
    # No GPU is used; this marker switches the guardian from 38 GiB startup
    # to the 34 GiB active floor. Each writer also requires a full unshared
    # output reservation, independently before each arm.
    temporary = plan.MONITOR / 'baseline-passed.tmp'; marker = plan.MONITOR / 'baseline-passed.json'
    write_new(temporary, {'status': 'passed', 'monotonicSeconds': time.monotonic()})
    os.link(temporary, marker); temporary.unlink()
    supervise_phase('worker-supervisor', 'worker', 3600)
    supervise_phase('final-supervisor', 'final_check', 2400)
    final = json.loads((plan.MONITOR / 'final-result.json').read_text())
    if (final.get('status') != 'paired_bytes_verified' or final.get('planSHA256') != plan.sha(plan.PLAN) or
            final.get('reportSHA256') != plan.sha(plan.OUTPUT / 'report.json') or plan.verify_plan() != frozen):
        raise ValueError('final paired-data audit differs')
    write_new(plan.MONITOR / 'coordinator-result.json', {'status': 'candidate_data_only',
              'planSHA256': plan.sha(plan.PLAN), 'workerSHA256': plan.sha(plan.MONITOR / 'worker-result.json'),
              'finalSHA256': plan.sha(plan.MONITOR / 'final-result.json'),
              'reportSHA256': plan.sha(plan.OUTPUT / 'report.json'), 'supervisorSHA256': supervisor_hashes(),
              'trainingAuthorized': False})


def resource_read():
    marker = plan.MONITOR / 'baseline-passed.json'
    passed = marker.is_file() and not marker.is_symlink()
    if passed:
        data = json.loads(marker.read_text()); tick = data.get('monotonicSeconds')
        if data.get('status') != 'passed' or type(tick) not in (int, float) or not 0 < tick <= time.monotonic():
            raise ValueError('invalid startup marker')
    gpu = telemetry.telemetry(telemetry.DEVICE)
    volumes = {key: shutil.disk_usage(path).free for key, path in
               (('workspace', ROOT), ('home', Path.home()), ('output', plan.MONITOR))}
    return {'freeBytes': min(volumes.values()), 'volumes': volumes, 'gpuFreeBytes': gpu['freeBytes'],
            'gpuTotalBytes': gpu['totalBytes'], 'gpuUsedBytes': gpu['usedBytes'],
            'gpuBusyPercent': gpu['busyPercent'], 'baselinePassed': passed}


def guardian_entry(parent_pid):
    result = guardian.run(plan.MONITOR, LOCK, command('coordinator'), environment(), int(parent_pid),
                          resource_read, wall_seconds=7500)
    if result.get('status') != 'passed':
        raise RuntimeError('paired-data guardian failed; partial evidence retained')


def verify_guardian(guardian_pid):
    launch = json.loads((plan.MONITOR / 'guardian-launch.json').read_text())
    result = json.loads((plan.MONITOR / 'guardian-result.json').read_text())
    rows = [json.loads(line) for line in (plan.MONITOR / 'guardian-telemetry.jsonl').read_text().splitlines()]
    active = [row for row in rows if row.get('phase') == 'active']; cleanup = [row for row in rows if row.get('phase') == 'cleanup']
    env = dict(environment())
    env.update(PUPPY_TURN_GUARD_PID=str(guardian_pid),
               PUPPY_TURN_GUARD_FD=launch.get('environment', {}).get('PUPPY_TURN_GUARD_FD'),
               PUPPY_TURN_GUARD_OUTPUT=str(plan.MONITOR))
    if (launch.get('guardianPID') != guardian_pid or launch.get('parentPID') != os.getpid() or
            launch.get('command') != command('coordinator') or launch.get('wallSeconds') != 7500 or
            launch.get('environment') != env or not isinstance(env['PUPPY_TURN_GUARD_FD'], str) or
            not env['PUPPY_TURN_GUARD_FD'].isdigit() or
            result.get('status') != 'passed' or result.get('reason') is not None or
            type(result.get('coordinatorExit')) is not int or result['coordinatorExit'] != 0 or
            result.get('descendantsTerminated') is not False or result.get('diskEmergency') is not False or
            len(active) < 1 or len(cleanup) < 2 or result.get('samples') != len(rows) or
            [row.get('phase') for row in rows] != ['active'] * len(active) + ['cleanup'] * len(cleanup)):
        raise ValueError('guardian identity or completion differs')
    times = [row.get('monotonicSeconds') for row in rows]
    if (any(type(t) not in (int, float) or not math.isfinite(t) for t in times) or
            any(not 0 < b - a <= 2.5 for a, b in zip(times, times[1:])) or
            not launch['startedMonotonic'] <= times[0] <= result['observedDoneMonotonic'] <= times[-1] <= result['endedMonotonic'] or
            times[0] - launch['startedMonotonic'] > 2.5 or result['endedMonotonic'] - times[-1] > 2.5):
        raise ValueError('guardian sampling coverage incomplete')
    marker = plan.MONITOR / 'baseline-passed.json'
    if marker.is_symlink() or not marker.is_file():
        raise ValueError('missing startup marker')
    recorded = json.loads(marker.read_text()); marker_tick = recorded.get('monotonicSeconds')
    if (recorded.get('status') != 'passed' or type(marker_tick) not in (int, float) or
            not math.isfinite(marker_tick) or not launch['startedMonotonic'] <= marker_tick <= result['observedDoneMonotonic']):
        raise ValueError('startup marker differs')
    seen = False
    for row in rows:
        values = row.get('volumes'); passed = row.get('baselinePassed')
        if type(passed) is not bool or (seen and not passed) or (passed and row['monotonicSeconds'] < marker_tick):
            raise ValueError('guardian phase differs')
        seen = seen or passed; threshold = 34 if passed else 38
        if (not isinstance(values, dict) or set(values) != {'workspace', 'home', 'output'} or
                any(type(value) is not int or value < threshold * GIB for value in values.values()) or
                row.get('freeBytes') != min(values.values()) or type(row.get('gpuFreeBytes')) is not int or
                type(row.get('gpuTotalBytes')) is not int or type(row.get('gpuUsedBytes')) is not int or
                row['gpuTotalBytes'] <= 0 or not 0 <= row['gpuUsedBytes'] <= row['gpuTotalBytes'] or
                row['gpuFreeBytes'] != row['gpuTotalBytes'] - row['gpuUsedBytes'] or row['gpuFreeBytes'] < 2 * GIB or
                type(row.get('gpuBusyPercent')) is not int or not 0 <= row['gpuBusyPercent'] <= 100):
            raise ValueError('guardian resource sample invalid')
    if not seen:
        raise ValueError('guardian missed startup')
    return result


def verify_post_guard(frozen, plan_hash, result):
    if any(shutil.disk_usage(path).free < 34 * GIB for path in (ROOT, Path.home(), plan.MONITOR, plan.OUTPUT)):
        raise ValueError('disk below floor after guardian')
    final = json.loads((plan.MONITOR / 'final-result.json').read_text())
    if (final.get('status') != 'paired_bytes_verified' or final.get('planSHA256') != plan_hash or
            final.get('reportSHA256') != result.get('reportSHA256') or
            output_inventory() != final.get('outputInventory')):
        raise ValueError('paired output changed after guardian cleanup')
    if plan.verify_plan() != frozen or plan.sha(plan.PLAN) != plan_hash:
        raise ValueError('input changed after guardian cleanup')
    if any(shutil.disk_usage(path).free < 34 * GIB for path in (ROOT, Path.home(), plan.MONITOR, plan.OUTPUT)):
        raise ValueError('disk below floor during final source verification')


def launch():
    standalone.require_dedicated_process(); frozen = plan.verify_plan(); plan_hash = plan.sha(plan.PLAN)
    if plan.MONITOR.exists() or plan.MONITOR.is_symlink() or plan.OUTPUT.exists() or plan.OUTPUT.is_symlink():
        raise FileExistsError('paired output or monitor exists; retain it')
    # Check capacity for one full unshared output before even starting.
    plan.builder.reservation(plan.OUTPUT, 1031, 300, 21168, 56, 144)
    plan.MONITOR.mkdir()
    code = ('import importlib.util,sys;s=importlib.util.spec_from_file_location("pair",sys.argv[1]);'
            'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.guardian_entry(sys.argv[2])')
    argv = [sys.executable, '-I', '-c', code, str(Path(__file__).resolve()), str(os.getpid())]
    write_new(plan.MONITOR / 'launcher.json', {'argv': argv, 'environment': environment(), 'planSHA256': plan_hash})
    with (plan.MONITOR / 'guardian.log').open('x') as log:
        process = subprocess.Popen(argv, cwd=ROOT, env=environment(), stdout=log, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        exit_code = process.wait()
    if exit_code != 0:
        raise RuntimeError('paired-data guardian failed; partial evidence retained')
    verify_guardian(process.pid)
    result = json.loads((plan.MONITOR / 'coordinator-result.json').read_text())
    verify_phase_results()
    if (result.get('status') != 'candidate_data_only' or result.get('trainingAuthorized') is not False or
            result.get('planSHA256') != plan_hash or result.get('workerSHA256') != plan.sha(plan.MONITOR / 'worker-result.json') or
            result.get('finalSHA256') != plan.sha(plan.MONITOR / 'final-result.json') or
            result.get('reportSHA256') != plan.sha(plan.OUTPUT / 'report.json') or result.get('supervisorSHA256') != supervisor_hashes()):
        raise ValueError('coordinator evidence differs')
    verify_post_guard(frozen, plan_hash, result)
    write_new(plan.MONITOR / 'completion.json', {'status': 'candidate_data_only', 'trainingAuthorized': False,
              'planSHA256': plan_hash, 'coordinatorSHA256': plan.sha(plan.MONITOR / 'coordinator-result.json'),
              'guardianLaunchSHA256': plan.sha(plan.MONITOR / 'guardian-launch.json'),
              'guardianResultSHA256': plan.sha(plan.MONITOR / 'guardian-result.json'),
              'guardianTelemetrySHA256': plan.sha(plan.MONITOR / 'guardian-telemetry.jsonl'),
              'scope': 'paired dataset candidates only; separate trainer mask audit and model evaluation required'})
    return result


if __name__ == '__main__':
    raise SystemExit('Disabled pending independent review and scheduling.')
